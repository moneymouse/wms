"""Opt-in financial row-lock tests on an explicitly empty loopback MySQL database.

Set WMS_TEST_FINANCE_DATABASE_URL to a pre-created database whose name starts
with wms_test_finance_, and WMS_TEST_FINANCE_ALLOW_SCHEMA_CREATE=1. These tests
never use the application DATABASE_URL or connect without explicit configuration.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Event, Lock

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from data.database import Base
from data.customer.Customer import CustomerTable
from services import finance_accounting_service as accounting
from services import finance_ledger_service as ledger
from tests.finance.test_ledger import ACTOR


@pytest.fixture
def rowlock_finance(monkeypatch):
    dsn = os.environ.get("WMS_TEST_FINANCE_DATABASE_URL")
    if not dsn:
        pytest.skip("No isolated MySQL finance concurrency database configured")
    if os.environ.get("WMS_TEST_FINANCE_ALLOW_SCHEMA_CREATE") != "1":
        pytest.fail("WMS_TEST_FINANCE_ALLOW_SCHEMA_CREATE=1 is required")
    url = make_url(dsn)
    if (url.get_backend_name() not in {"mysql", "mariadb"}
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not re.fullmatch(r"wms_test_finance_[a-zA-Z0-9_]+", url.database or "") or url.query):
        pytest.fail("Use a loopback MySQL database named wms_test_finance_*, without URL options")
    engine = create_engine(url, isolation_level="REPEATABLE READ", pool_pre_ping=True)
    created = False
    try:
        inspector = inspect(engine)
        if inspector.get_table_names() or inspector.get_view_names():
            pytest.fail("Refusing to use a nonempty finance test database")
        Base.metadata.create_all(engine)
        created = True
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(ledger, "SessionFactory", factory)
        monkeypatch.setattr(accounting, "SessionFactory", factory)
        with factory() as session:
            customer = CustomerTable(name="并发财务客户")
            session.add(customer)
            session.commit()
            customer_id = customer.id
        accounting.configure({"company_name": "并发测试", "opening_date": "2026-01-01", "revenue_policy": "invoice"}, ACTOR)
        accounting.create_period({"name": "并发期间", "date_from": "2026-01-01", "date_to": "2026-12-31"}, ACTOR)
        account = ledger.save_master("accounts", {"name": "并发银行", "account_type": "bank"}, ACTOR)
        yield customer_id, account, factory
    finally:
        if created:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize("race", ["two_refunds", "allocation_and_refund"])
def test_finance_writes_serialize_before_spending_same_balance(rowlock_finance, monkeypatch, race):
    customer_id, account, factory = rowlock_finance
    def make_payment(direction, amount, post):
        row = ledger.create_payment({"partner_type": "customer", "partner_id": customer_id,
            "direction": direction, "account_id": account["id"], "amount": amount, "payment_date": "2026-01-05"}, ACTOR)
        return ledger.post_payment(row["id"], {"version": row["version"]}, ACTOR) if post else row
    advance = make_payment("incoming", "100", True)
    second_refund = make_payment("outgoing", "60", False)
    if race == "two_refunds":
        first_refund = make_payment("outgoing", "60", False)
        first_action = lambda: ledger.post_payment(first_refund["id"], {"version": first_refund["version"]}, ACTOR)
    else:
        doc = ledger.create_document({"document_type": "customer_invoice", "partner_id": customer_id,
            "document_date": "2026-01-05", "lines": [{"description": "运输", "unit_price": "100"}]}, ACTOR)
        doc = ledger.post_document(doc["id"], {"version": doc["version"]}, ACTOR)
        first_action = lambda: ledger.create_allocations({"payment_id": advance["id"], "version": advance["version"],
            "allocation_date": "2026-01-05", "allocations": [{"document_id": doc["id"], "amount": "70"}]}, ACTOR)
    first_locked, release_first, second_started, second_passed_lock = Event(), Event(), Event(), Event()
    counter_lock, counter = Lock(), 0
    original = ledger._lock_financial_row
    def pause_after_settings_lock(*args, **kwargs):
        nonlocal counter
        with counter_lock:
            counter += 1
            call = counter
        if call == 1:
            first_locked.set()
            if not release_first.wait(10):
                raise RuntimeError("Concurrency test release timed out")
        else:
            second_passed_lock.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, "_lock_financial_row", pause_after_settings_lock)
    def second_action():
        second_started.set()
        return ledger.post_payment(second_refund["id"], {"version": second_refund["version"]}, ACTOR)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_action)
        try:
            assert first_locked.wait(5)
            second = executor.submit(second_action)
            assert second_started.wait(5)
            assert not second_passed_lock.wait(0.25), "Second writer bypassed the finance settings lock"
        finally:
            release_first.set()
        first.result(timeout=10)
        with pytest.raises(ValueError, match="可退余额"):
            second.result(timeout=10)
    assert ledger.get_payment(second_refund["id"], ACTOR)["status"] == "draft"
    with factory() as session:
        assert ledger._refundable_balance(session, "customer", customer_id) in {30, 40}
