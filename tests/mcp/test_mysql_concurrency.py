"""Opt-in production-dialect receipt races.

Set MCP_CONCURRENCY_DATABASE_URL to a migrated MySQL/MariaDB database whose
name includes 'test'. Only records created by these tests are removed.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Event, Lock
import time
import uuid

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from data.DB import AuditLogTable, OrderTable
from data.mcp import McpIdempotencyTable
from services import mcp_service


@pytest.fixture
def mysql_mcp_scope(monkeypatch):
    dsn = os.environ.get("MCP_CONCURRENCY_DATABASE_URL")
    if not dsn:
        pytest.skip("MCP_CONCURRENCY_DATABASE_URL is not configured")
    url = make_url(dsn)
    if url.get_backend_name() not in {"mysql", "mariadb"} or "test" not in (url.database or "").lower():
        pytest.fail("MCP concurrency tests require a MySQL/MariaDB database whose name includes 'test'")
    engine = create_engine(url, isolation_level="REPEATABLE READ", pool_pre_ping=True)
    required = {"orders", "audit_logs", "mcp_idempotency"}
    missing = sorted(required - set(inspect(engine).get_table_names()))
    if missing:
        engine.dispose()
        pytest.fail(f"Apply migrations before MCP concurrency tests: {missing}")
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    prefix = "mcp-race-" + uuid.uuid4().hex[:12]
    # No user FK is involved in these isolated transport receipts or audit rows.
    user_id = 700000000 + int(uuid.uuid4().hex[:5], 16)
    principal = {"user_id": user_id, "client_id": f"https://client.example/{prefix}.json",
                 "operator_payload": {"user_id": user_id, "name": prefix, "roles": ["admin"]},
                 "scopes": ["mcp", "orders:create"], "expires_at": int(time.time()) + 900,
                 "resource": "https://wms.example/mcp", "issuer": "https://wms.example"}
    monkeypatch.setattr(mcp_service, "SessionFactory", factory)
    scope = {"factory": factory, "principal": principal, "prefix": prefix, "created": set()}
    try:
        yield scope
    finally:
        with factory() as session:
            session.query(McpIdempotencyTable).filter_by(user_id=user_id).delete(synchronize_session=False)
            session.query(AuditLogTable).filter_by(operator_id=user_id).delete(synchronize_session=False)
            if scope["created"]:
                session.query(OrderTable).filter(OrderTable.uid.in_(scope["created"])).delete(synchronize_session=False)
            session.commit()
        engine.dispose()


@pytest.mark.parametrize("different_arguments", [False, True])
def test_concurrent_same_key_has_one_business_commit(mysql_mcp_scope, monkeypatch, different_arguments):
    scope = mysql_mcp_scope
    first_inside = Event()
    release_first = Event()
    second_started = Event()
    calls, guard = [], Lock()

    def create(record, operator, session=None):
        with guard:
            calls.append(record.copy())
        uid = uuid.uuid4().hex
        scope["created"].add(uid)
        session.add(OrderTable(uid=uid, order_id=scope["prefix"], receiver=record.get("receiver"), archive=False))
        session.flush()
        first_inside.set()
        if not release_first.wait(10):
            raise RuntimeError("Timed out releasing MCP transaction")
        return {"code": 200, "uid": uid, "msg": "success"}

    monkeypatch.setattr("services.order_service.create_order", create)
    args = {"order": {"receiver": "one"}, "idempotency_key": "same-key"}
    other = deepcopy(args)
    if different_arguments:
        other["order"]["receiver"] = "two"

    def second_call():
        second_started.set()
        return mcp_service.execute_tool("create_order", other, scope["principal"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(mcp_service.execute_tool, "create_order", args, scope["principal"])
        try:
            assert first_inside.wait(5)
            second = pool.submit(second_call)
            assert second_started.wait(5)
            assert not second.done(), "Duplicate key bypassed the uncommitted receipt"
        finally:
            release_first.set()
        winner = first.result(timeout=10)
        loser = second.result(timeout=10)
    assert len(calls) == 1
    assert loser["code"] == 409 if different_arguments else loser == winner
    with scope["factory"]() as session:
        assert session.query(OrderTable).filter_by(order_id=scope["prefix"]).count() == 1
        assert session.query(McpIdempotencyTable).filter_by(user_id=scope["principal"]["user_id"]).count() == 1
