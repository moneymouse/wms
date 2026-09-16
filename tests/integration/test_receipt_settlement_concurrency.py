"""Opt-in MySQL row-lock tests against an explicitly supplied empty test database.

Set WMS_TEST_ROWLOCK_DATABASE_URL to a loopback MySQL URL whose database name
starts with wms_test_receipt_settlement_, and WMS_TEST_ROWLOCK_ALLOW_SCHEMA_CREATE
to 1. The database must already exist and contain no tables or views. Tests
create and remove only their own ORM tables; no application DATABASE_URL is
used. With neither variable set these tests never connect to MySQL.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Event, Lock

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from data.DB import PaymentReceiptItemTable, PaymentReceiptTable
from data.database import Base
from services import receivable_service as service
from tests.unit.test_order_receipt_revision import _seed_world
from tests.unit.test_receipt_settlement import FINANCE, SALES, _body


@pytest.fixture
def isolated_rowlock_database(monkeypatch):
    dsn = os.environ.get("WMS_TEST_ROWLOCK_DATABASE_URL")
    if not dsn:
        pytest.skip("No isolated MySQL row-lock test database configured")
    if os.environ.get("WMS_TEST_ROWLOCK_ALLOW_SCHEMA_CREATE") != "1":
        pytest.fail("Set WMS_TEST_ROWLOCK_ALLOW_SCHEMA_CREATE=1 for the isolated test database")
    url = make_url(dsn)
    if (
        url.get_backend_name() not in {"mysql", "mariadb"}
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not re.fullmatch(r"wms_test_receipt_settlement_[a-zA-Z0-9_]+", url.database or "")
        or url.query
    ):
        pytest.fail("Row-lock tests require a loopback MySQL URL, no URL options, and a dedicated wms_test_receipt_settlement_ database")
    engine = create_engine(url, isolation_level="REPEATABLE READ", pool_pre_ping=True)
    created = False
    try:
        inspector = inspect(engine)
        if inspector.get_table_names() or inspector.get_view_names():
            pytest.fail("Refusing to use a nonempty row-lock test database")
        Base.metadata.create_all(engine)
        created = True
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(service, "SessionFactory", factory)
        yield factory
    finally:
        if created:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize("race", ["two_creates_reverse_order", "approval_and_create", "two_approvals"])
def test_receipt_mutations_serialize_on_order_rows(isolated_rowlock_database, monkeypatch, race):
    factory = isolated_rowlock_database
    with factory() as session:
        customer, orders, _ = _seed_world(session, order_count=2 if race == "two_creates_reverse_order" else 1)
        if race == "two_creates_reverse_order":
            first_body = _body(customer, orders, [100, 100], settlement_status="settled")
            second_body = _body(customer, list(reversed(orders)), [1, 1], settlement_status="unsettled")
            first_action = lambda: service.create_receipt(first_body, SALES)
            second_action = lambda: service.create_receipt(second_body, SALES)
            expected_error = "已结清或存在待审核结清"
        else:
            created = service.create_receipt(
                _body(customer, orders, [40 if race == "approval_and_create" else 100],
                      settlement_status="unsettled" if race == "approval_and_create" else "settled"),
                SALES,
            )
            first_action = lambda: service.review_receipt(created["id"], "approve", "并发测试", FINANCE)
            if race == "approval_and_create":
                second_body = _body(customer, orders, [100], settlement_status="unsettled")
                second_action = lambda: service.create_receipt(second_body, SALES)
                expected_error = "最多可收 92.00"
            else:
                second_action = first_action
                expected_error = "已经审核"

    first_holds_orders = Event()
    release_first = Event()
    second_started = Event()
    second_passed_order_lock = Event()
    counter_lock = Lock()
    calls = 0
    original = service._locked_receipt_allocations

    def pause_after_order_locks(*args, **kwargs):
        nonlocal calls
        with counter_lock:
            calls += 1
            number = calls
        if number == 1:
            first_holds_orders.set()
            if not release_first.wait(10):
                raise RuntimeError("Timed out waiting for row-lock test release")
        else:
            second_passed_order_lock.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_locked_receipt_allocations", pause_after_order_locks)

    def run_second():
        second_started.set()
        return second_action()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_action)
        try:
            assert first_holds_orders.wait(5)
            second = executor.submit(run_second)
            assert second_started.wait(5)
            assert not second_passed_order_lock.wait(0.25), "Second mutation bypassed the order row lock"
        finally:
            release_first.set()
        first.result(timeout=10)
        with pytest.raises(ValueError, match=expected_error):
            second.result(timeout=10)

    with factory() as session:
        assert session.query(PaymentReceiptTable).count() == 1
        if race == "two_approvals":
            item = session.query(PaymentReceiptItemTable).one()
            assert item.settlement_difference == 32
