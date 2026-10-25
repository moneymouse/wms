"""Opt-in InnoDB concurrency checks against a dedicated, empty test database.

Run with WMS_TEST_MYSQL_URL pointing at the disposable ``exception_test``
database or a database named ``wms_test_*``. No application DATABASE_URL is
used. These tests create and remove their own tables and refuse an existing
application schema. Without the opt-in URL, every check is skipped.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Barrier, Event

import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from data.database import Base
from data.DB import CargoTable, OrderTable
from data.message import MessageTable
from data.order_exception import OrderExceptionHistoryTable, OrderExceptionTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import order_exception_service as service


@pytest.fixture(scope="module")
def mysql_engine():
    configured_url = os.environ.get("WMS_TEST_MYSQL_URL")
    if not configured_url:
        pytest.skip("WMS_TEST_MYSQL_URL is absent; isolated MySQL is opt-in")
    url = make_url(configured_url)
    if url.get_backend_name() != "mysql" or not re.fullmatch(
        r"exception_test|wms_test_[a-z0-9_]+", url.database or "",
    ):
        pytest.fail("MySQL tests require a dedicated exception_test or wms_test_* database")

    engine = create_engine(
        url, isolation_level="REPEATABLE READ", pool_pre_ping=True,
        pool_size=4, max_overflow=0,
    )

    @sqlalchemy_event.listens_for(engine, "connect")
    def bound_lock_wait(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 10")

    with engine.connect() as connection:
        storage_engine = connection.execute(text("SELECT @@default_storage_engine")).scalar_one()
        assert storage_engine.lower() == "innodb", "Concurrency checks require InnoDB"
    owned_tables = set(Base.metadata.tables)
    existing = owned_tables.intersection(inspect(engine).get_table_names())
    if existing:
        engine.dispose()
        pytest.fail("Refusing to modify an existing application schema; use an empty test database")
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def mysql_database(mysql_engine):
    factory = sessionmaker(bind=mysql_engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        salesperson = RoleTable(name="salesperson", label="业务员")
        session.add(salesperson)
        session.add_all([
            UserTable(id=1, phone="13800000001", name="测试业务员甲", password="unused",
                      status="approved", roles=[salesperson]),
            UserTable(id=2, phone="13800000002", name="测试业务员乙", password="unused",
                      status="approved", roles=[salesperson]),
        ])
        session.flush()
        session.add_all([
            OrderTable(uid="order-a", order_id="ORDER-A", salesman_id=1, archive=False),
            OrderTable(uid="order-b", order_id="ORDER-B", salesman_id=2, archive=False),
        ])
        session.flush()
        session.add_all([
            CargoTable(uid="cargo-a", origin_id="PARCEL-A", target_order_uid="order-a",
                       waybill_id="WAYBILL-A", archive=False, status=1),
            CargoTable(uid="cargo-b", origin_id="PARCEL-B", target_order_uid="order-b",
                       waybill_id="WAYBILL-B", archive=False, status=1),
        ])
    try:
        yield factory
    finally:
        with mysql_engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())


def _event(event_key="tracking-event-1", **values):
    return {
        "order_uid": "order-a", "cargo_uid": "cargo-a", "reason": "投递异常",
        "source": "17track", "event_key": event_key,
        "tracking_status": "Exception_Other", **values,
    }


def _register(factory, values, barrier=None):
    with factory() as session:
        # Open a physical connection/transaction before releasing both workers.
        connection_id = session.execute(text("SELECT CONNECTION_ID()")).scalar_one()
        if barrier:
            barrier.wait(timeout=15)
        case = service.register_exception(session, **values)
        session.commit()
        return case.uid, connection_id


def _parallel(factory, first, second):
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(_register, factory, values, barrier) for values in (first, second)]
        results = [future.result(timeout=30) for future in futures]
    assert len({connection_id for _, connection_id in results}) == 2
    return [uid for uid, _ in results]


def _assert_consistent(factory, expected):
    with factory() as session:
        cases = session.query(OrderExceptionTable).all()
        history = session.query(OrderExceptionHistoryTable).all()
        notices = session.query(MessageTable).all()
        assert (len(cases), len(history), len(notices)) == expected
        assert all(case.status == "open" for case in cases)
        by_uid = {case.uid: case for case in cases}
        assert {row.event_key for row in history} == {row.event_key for row in notices}
        for notice in notices:
            case = by_uid[notice.business_id]
            assert notice.recipient_id == case.salesman_id
            assert notice.action_path == f"/order-exceptions?exception_uid={case.uid}"
            fact = next(row for row in history if row.event_key == notice.event_key)
            assert fact.exception_uid == case.uid
            assert fact.note in notice.body
        assert all(cargo.status == 1 for cargo in session.query(CargoTable).all())


def _chained_mysql_codes(error):
    """Collect driver codes without losing the cause of a rollback failure."""
    pending, visited, codes = [error], set(), set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, OperationalError) and current.orig.args:
            codes.add(current.orig.args[0])
        pending.extend(chained for chained in (current.__cause__, current.__context__) if chained is not None)
    return codes


@pytest.mark.parametrize("cargo_uid", [None, "cargo-a"])
def test_concurrent_identical_tracking_events_register_once(mysql_database, cargo_uid):
    event = _event(cargo_uid=cargo_uid)
    uids = _parallel(mysql_database, event, event)
    assert uids[0] == uids[1]
    _assert_consistent(mysql_database, (1, 1, 1))


@pytest.mark.parametrize("cargo_uid", [None, "cargo-a"])
def test_concurrent_distinct_events_share_open_order_or_parcel(mysql_database, cargo_uid):
    first = _event("tracking-event-1", cargo_uid=cargo_uid)
    second = _event("tracking-event-2", cargo_uid=cargo_uid, reason="需要确认收件地址")
    uids = _parallel(mysql_database, first, second)
    assert uids[0] == uids[1]
    _assert_consistent(mysql_database, (1, 2, 2))
    with mysql_database() as session:
        assert {row.note for row in session.query(OrderExceptionHistoryTable)} == {
            first["reason"], second["reason"],
        }


def test_failed_notice_and_concurrent_retry_do_not_consume_event(mysql_database, monkeypatch):
    queued, release_failure, retry_started = Event(), Event(), Event()
    original_send = service.send_message
    values = _event("retry-after-notice-failure")

    def fail_after_queue(session, **kwargs):
        notice = original_send(session, **kwargs)
        if session.info.get("fail_delivery"):
            queued.set()
            assert release_failure.wait(timeout=15)
            raise RuntimeError("simulated delivery failure after insert")
        return notice

    def failed_attempt():
        with mysql_database() as session:
            session.info["fail_delivery"] = True
            session.get(UserTable, 1).remark = "caller-owned business change"
            with pytest.raises(RuntimeError, match="delivery failure after insert"):
                service.register_exception(session, **values)
            assert session.is_active
            # Only the registrar's savepoint rolled back; the caller retains
            # its unrelated business change and decides to commit it.
            session.commit()

    def concurrent_retry():
        with mysql_database() as session:
            session.execute(text("SELECT CONNECTION_ID()"))
            retry_started.set()
            case = service.register_exception(session, **values)
            session.commit()
            return case.uid

    monkeypatch.setattr(service, "send_message", fail_after_queue)
    with ThreadPoolExecutor(max_workers=2) as workers:
        failed = workers.submit(failed_attempt)
        try:
            assert queued.wait(timeout=15)
            retry = workers.submit(concurrent_retry)
            assert retry_started.wait(timeout=15)
        finally:
            release_failure.set()
        failed.result(timeout=30)
        uid = retry.result(timeout=30)
    replay_uid, _ = _register(mysql_database, values)
    assert replay_uid == uid
    _assert_consistent(mysql_database, (1, 1, 1))
    with mysql_database() as session:
        assert session.get(UserTable, 1).remark == "caller-owned business change"


def test_global_event_key_race_cannot_leak_case_to_another_order(mysql_database, monkeypatch):
    both_missed = Barrier(2)
    start = Barrier(2)
    original_replay = service._replay
    key = "same-key-across-orders"

    def concurrent_miss(session, event_key, digest):
        result = original_replay(session, event_key, digest)
        if result is None:
            # Different orders have different locks. Force both transactions
            # to miss the global event key before either attempts its insert.
            both_missed.wait(timeout=15)
        return result

    monkeypatch.setattr(service, "_replay", concurrent_miss)
    first = _event(key)
    second = _event(key, order_uid="order-b", cargo_uid="cargo-b")
    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(_register, mysql_database, values, start) for values in (first, second)]
        for values, future in zip((first, second), futures):
            try:
                outcomes.append((values, future.result(timeout=30)))
            except service.ExceptionConflictError as exc:
                outcomes.append((values, exc))
            except OperationalError as exc:
                # InnoDB may select a deadlock victim while acquiring unique
                # index gap locks. The webhook returns 503 for this transaction
                # and the provider retries it in a fresh caller-owned session.
                # MySQL removes every savepoint when aborting for a deadlock;
                # SQLAlchemy's subsequent ROLLBACK TO SAVEPOINT can mask 1213
                # as 1305. Accept that surface error only with a proven lock
                # race in its cause/context chain, never a general DB failure.
                surface_code = exc.orig.args[0]
                assert surface_code in {1205, 1213} or (
                    surface_code == 1305 and _chained_mysql_codes(exc).intersection({1205, 1213})
                )
                outcomes.append((values, exc))
    monkeypatch.setattr(service, "_replay", original_replay)
    winners = [(values, result) for values, result in outcomes if isinstance(result, tuple)]
    losers = [(values, result) for values, result in outcomes if isinstance(result, Exception)]
    assert len(winners) == len(losers) == 1
    _assert_consistent(mysql_database, (1, 1, 1))

    losing_values, _ = losers[0]
    with pytest.raises(service.ExceptionConflictError):
        _register(mysql_database, losing_values)
    _assert_consistent(mysql_database, (1, 1, 1))
    with mysql_database() as session:
        case = session.query(OrderExceptionTable).one()
        assert case.order_uid == winners[0][0]["order_uid"]

    # A fresh fact for the losing order is accepted; the failed transaction did
    # not leave either a case, a notice or a misleadingly consumed event key.
    _register(mysql_database, {**losing_values, "event_key": "new-fact-after-conflict"})
    _assert_consistent(mysql_database, (2, 2, 2))
