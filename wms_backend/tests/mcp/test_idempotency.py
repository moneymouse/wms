from copy import deepcopy

import pytest

from data.DB import AuditLogTable, OrderTable
from data.customer.Customer import ReceiverTable
from data.mcp import McpIdempotencyTable
from data.order_version import OrderVersionTable
from data.packing.PackingList import PackingListTable
from services import mcp_service


@pytest.mark.parametrize("tool", ["create_order", "create_packing_list"])
def test_same_key_replays_result_and_different_arguments_conflict(mcp_db, tool):
    arguments = ({"order": {"customer_id": mcp_db["customer_id"], "receiver": "first"},
                  "idempotency_key": "durable-key"} if tool == "create_order" else
                 {"mark": "  box  ", "idempotency_key": "durable-key"})
    first = mcp_service.execute_tool(tool, arguments, mcp_db["principal"])
    equivalent = deepcopy(arguments)
    if tool == "create_packing_list":
        equivalent["mark"] = "BOX"
    replay = mcp_service.execute_tool(tool, equivalent, mcp_db["principal"])
    assert first == replay
    different = deepcopy(arguments)
    if tool == "create_order":
        different["order"]["receiver"] = "different"
    else:
        different["mark"] = "different"
    assert mcp_service.execute_tool(tool, different, mcp_db["principal"])["code"] == 409
    with mcp_db["factory"]() as session:
        assert session.query(McpIdempotencyTable).count() == 1
        assert session.query(OrderTable if tool == "create_order" else PackingListTable).count() == 1
        replay_audit = session.query(AuditLogTable).filter_by(event_type="mcp_tool_replay").one()
        assert replay_audit.operator_id == mcp_db["user_id"]


def test_keys_are_scoped_by_user_client_and_tool(mcp_db):
    principal = mcp_db["principal"]
    args = {"order": {}, "idempotency_key": "one-key"}
    first = mcp_service.execute_tool("create_order", args, principal)
    other_client = deepcopy(principal)
    other_client["client_id"] += "?different-client"
    second = mcp_service.execute_tool("create_order", args, other_client)
    packing = mcp_service.execute_tool("create_packing_list", {"mark": "MARK", "idempotency_key": "one-key"}, principal)
    assert first["uid"] != second["uid"]
    assert packing["code"] == 200
    with mcp_db["factory"]() as session:
        assert session.query(McpIdempotencyTable).count() == 3


def test_quote_failure_rolls_back_order_receiver_history_and_receipt(mcp_db, monkeypatch):
    def fail_quote(**kwargs):
        raise ValueError("injected quote failure")

    monkeypatch.setattr("services.receivable_service.create_order_quote", fail_quote)
    result = mcp_service.execute_tool("create_order", {
        "order": {"customer_id": mcp_db["customer_id"], "receiver": "Receiver rollback",
                  "quote": {"quoted_price": "1.00"}}, "idempotency_key": "quote-fail"}, mcp_db["principal"])
    assert result["code"] == 500
    assert "uid" not in result
    with mcp_db["factory"]() as session:
        for table in (OrderTable, ReceiverTable, OrderVersionTable, McpIdempotencyTable):
            assert session.query(table).count() == 0


@pytest.mark.parametrize("tool", ["create_order", "create_packing_list"])
def test_audit_failure_rolls_back_business_and_replay_receipt(mcp_db, monkeypatch, tool):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(mcp_service, "record_audit", fail_audit)
    arguments = {"order": {}, "idempotency_key": "audit-fail"} if tool == "create_order" else {"mark": "AUDIT", "idempotency_key": "audit-fail"}
    with pytest.raises(RuntimeError, match="injected audit failure"):
        mcp_service.execute_tool(tool, arguments, mcp_db["principal"])
    with mcp_db["factory"]() as session:
        assert session.query(McpIdempotencyTable).count() == 0
        assert session.query(OrderTable if tool == "create_order" else PackingListTable).count() == 0


def test_non_idempotency_integrity_errors_are_not_replayed(mcp_db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    def business_failure(*args, **kwargs):
        raise IntegrityError("insert business", {}, Exception("UNIQUE constraint failed: business_table.uid"))

    monkeypatch.setattr("services.order_service.create_order", business_failure)
    with pytest.raises(IntegrityError):
        mcp_service.execute_tool("create_order", {"order": {}, "idempotency_key": "other-unique"}, mcp_db["principal"])
    with mcp_db["factory"]() as session:
        assert session.query(McpIdempotencyTable).count() == 0
