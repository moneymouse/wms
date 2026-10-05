"""Opt-in MySQL concurrency coverage for append-only order versions.

Set ``ORDER_VERSION_CONCURRENCY_DATABASE_URL`` to a migrated MySQL/MariaDB test
database.  The database name must contain ``test``.  Without that variable this
module is collected but every test is skipped and no network connection is made.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event, Lock, local
import uuid

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from data.DB import CargoTable, OrderTable, cargo_model, order_model
from data.order_version import (
    OrderVersionChangeTable,
    OrderVersionTable,
    create_order_version,
    snapshot_order,
)


@pytest.fixture
def mysql_version_scope(monkeypatch):
    dsn = os.environ.get("ORDER_VERSION_CONCURRENCY_DATABASE_URL")
    if not dsn:
        pytest.skip("ORDER_VERSION_CONCURRENCY_DATABASE_URL is not configured")

    url = make_url(dsn)
    if url.get_backend_name() not in {"mysql", "mariadb"}:
        pytest.fail("Order-version concurrency tests require MySQL or MariaDB")
    if "test" not in (url.database or "").lower():
        pytest.fail("Refusing to use a database whose name does not contain 'test'")

    engine = create_engine(
        url,
        isolation_level="REPEATABLE READ",
        pool_pre_ping=True,
    )
    required_tables = {
        "orders",
        "cargos",
        "order_versions",
        "order_version_changes",
    }
    existing_tables = set(inspect(engine).get_table_names())
    missing = sorted(required_tables - existing_tables)
    if missing:
        engine.dispose()
        pytest.fail(f"Apply migrations before running concurrency tests: {missing}")

    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    prefix = f"ovc{uuid.uuid4().hex[:12]}"
    scope = {
        "factory": factory,
        "prefix": prefix,
        "order_uids": set(),
        "cargo_uids": set(),
    }
    monkeypatch.setattr("data.DB.SessionFactory", factory)
    try:
        yield scope
    finally:
        order_uids = sorted(scope["order_uids"])
        cargo_uids = sorted(scope["cargo_uids"])
        with factory() as session:
            try:
                version_ids = [
                    row[0]
                    for row in session.query(OrderVersionTable.id)
                    .filter(OrderVersionTable.order_uid.in_(order_uids))
                    .all()
                ] if order_uids else []
                if version_ids:
                    session.query(OrderVersionChangeTable).filter(
                        OrderVersionChangeTable.version_id.in_(version_ids)
                    ).delete(synchronize_session=False)
                if order_uids:
                    session.query(OrderVersionTable).filter(
                        OrderVersionTable.order_uid.in_(order_uids)
                    ).delete(synchronize_session=False)
                if cargo_uids:
                    session.query(CargoTable).filter(
                        CargoTable.uid.in_(cargo_uids)
                    ).delete(synchronize_session=False)
                if order_uids:
                    session.query(OrderTable).filter(
                        OrderTable.uid.in_(order_uids)
                    ).delete(synchronize_session=False)
                session.commit()
            except Exception:
                session.rollback()
                raise
        engine.dispose()


def _seed_orders(scope, count):
    factory = scope["factory"]
    order_uids = [f"{scope['prefix']}o{index}" for index in range(1, count + 1)]
    scope["order_uids"].update(order_uids)
    with factory() as session:
        for index, order_uid in enumerate(order_uids, 1):
            order = OrderTable(
                uid=order_uid,
                order_id=f"{scope['prefix']}-ORDER-{index}",
                receiver="initial",
                archive=False,
                cargo_count=0,
                create_date="2026-09-16 12:00:00",
            )
            session.add(order)
            session.flush()
            create_order_version(session, order_uid, snapshot_order(session, order_uid))
        session.commit()
    return order_uids


def _install_first_snapshot_pause(monkeypatch):
    """Pause one marked thread inside its first before-snapshot while locks are held."""
    import data.order_version as version_module

    original_snapshot = version_module.snapshot_order
    thread_state = local()
    first_holds_lock = Event()
    release_first = Event()
    second_started = Event()
    pause_guard = Lock()
    paused = False

    def wrapped_snapshot(*args, **kwargs):
        nonlocal paused
        should_pause = False
        if getattr(thread_state, "pause", False):
            with pause_guard:
                if not paused:
                    paused = True
                    should_pause = True
        if should_pause:
            first_holds_lock.set()
            if not release_first.wait(10):
                raise RuntimeError("Timed out waiting to release MySQL row lock")
        return original_snapshot(*args, **kwargs)

    monkeypatch.setattr(version_module, "snapshot_order", wrapped_snapshot)
    return thread_state, first_holds_lock, release_first, second_started


def test_same_order_concurrent_writes_produce_contiguous_unique_versions(
    mysql_version_scope, monkeypatch
):
    scope = mysql_version_scope
    order_uid = _seed_orders(scope, 1)[0]
    state, first_holds, release_first, second_started = _install_first_snapshot_pause(
        monkeypatch
    )

    def first_write():
        state.pause = True
        return order_model.update(order_uid, {"receiver": "first"})

    def second_write():
        second_started.set()
        return order_model.update(order_uid, {"receiver": "second"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_write)
        try:
            assert first_holds.wait(5), "First mutation never acquired the order lock"
            second = executor.submit(second_write)
            assert second_started.wait(5)
            assert not second.done(), "Second mutation unexpectedly bypassed the row lock"
        finally:
            release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)

    with scope["factory"]() as session:
        versions = (
            session.query(OrderVersionTable)
            .filter(OrderVersionTable.order_uid == order_uid)
            .order_by(OrderVersionTable.version_no.asc())
            .all()
        )
        assert [row.version_no for row in versions] == [1, 2, 3]
        assert len({(row.order_uid, row.version_no) for row in versions}) == 3
        assert session.query(OrderTable).filter_by(uid=order_uid).one().receiver == "second"


def test_reverse_cross_order_batches_do_not_deadlock_and_share_correlation(
    mysql_version_scope, monkeypatch
):
    scope = mysql_version_scope
    order_a, order_b = _seed_orders(scope, 2)
    cargo_by_order = {}
    with scope["factory"]() as session:
        for order_index, order_uid in enumerate((order_a, order_b), 1):
            cargo_by_order[order_uid] = []
            for cargo_index in (1, 2):
                cargo_uid = f"{scope['prefix']}c{order_index}{cargo_index}"
                scope["cargo_uids"].add(cargo_uid)
                cargo_by_order[order_uid].append(cargo_uid)
                session.add(
                    CargoTable(
                        uid=cargo_uid,
                        origin_id=f"{scope['prefix']}-CARGO-{order_index}-{cargo_index}",
                        target_order_uid=order_uid,
                        status=0,
                        archive=False,
                        create_date="2026-09-16 12:01:00",
                    )
                )
        session.flush()
        # Replace the V1 snapshots so each baseline contains all seeded cargos.
        version_ids = [
            row[0]
            for row in session.query(OrderVersionTable.id)
            .filter(OrderVersionTable.order_uid.in_([order_a, order_b]))
            .all()
        ]
        session.query(OrderVersionChangeTable).filter(
            OrderVersionChangeTable.version_id.in_(version_ids)
        ).delete(synchronize_session=False)
        session.query(OrderVersionTable).filter(
            OrderVersionTable.id.in_(version_ids)
        ).delete(synchronize_session=False)
        session.flush()
        for order_uid in (order_a, order_b):
            create_order_version(session, order_uid, snapshot_order(session, order_uid))
        session.commit()

    state, first_holds, release_first, second_started = _install_first_snapshot_pause(
        monkeypatch
    )
    first_input = [cargo_by_order[order_b][0], cargo_by_order[order_a][0]]
    second_input = [cargo_by_order[order_a][1], cargo_by_order[order_b][1]]

    def first_batch():
        state.pause = True
        return cargo_model.mutate_many(first_input, "archive")

    def second_batch():
        second_started.set()
        return cargo_model.mutate_many(second_input, "archive")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_batch)
        try:
            assert first_holds.wait(5), "First batch never acquired both order locks"
            second = executor.submit(second_batch)
            assert second_started.wait(5)
            assert not second.done(), "Reverse batch unexpectedly bypassed order locks"
        finally:
            release_first.set()
        assert len(first.result(timeout=10)["success"]) == 2
        assert len(second.result(timeout=10)["success"]) == 2

    with scope["factory"]() as session:
        rows = (
            session.query(OrderVersionTable)
            .filter(OrderVersionTable.order_uid.in_([order_a, order_b]))
            .order_by(OrderVersionTable.order_uid.asc(), OrderVersionTable.version_no.asc())
            .all()
        )
        by_order = {
            order_uid: [row for row in rows if row.order_uid == order_uid]
            for order_uid in (order_a, order_b)
        }
        assert [row.version_no for row in by_order[order_a]] == [1, 2, 3]
        assert [row.version_no for row in by_order[order_b]] == [1, 2, 3]
        for version_no in (2, 3):
            correlation_ids = {
                row.correlation_id
                for row in rows
                if row.version_no == version_no
            }
            assert len(correlation_ids) == 1
