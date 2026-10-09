"""Financial history is part of the transaction, not a best-effort side effect."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import event

from Auth import create_jwt
from data.DB import AuditLogTable, PaymentReceiptTable
from services import receivable_service as service
from tests.unit.test_order_receipt_revision import _seed_world, _add_receipt_history
from tests.unit.test_receipt_settlement import SALES, FINANCE, _body
from utils.audit import field_changes, load_audit_logs, record_audit


@pytest.fixture(autouse=True)
def audit_database(setup_test_database):
    with patch("utils.audit.SessionFactory", return_value=setup_test_database), patch(
        "services.receivable_service.SessionFactory", return_value=setup_test_database
    ):
        yield


def _fail_audit_insert(mapper, connection, target):
    raise RuntimeError("audit storage unavailable")


def test_event_uses_callers_transaction_and_explicit_actor(setup_test_database):
    session = setup_test_database
    result = record_audit("payment_receipt", "receipt", 99, action="update",
                          before_data={"amount": "12.00"}, after_data={"amount": "14.00"},
                          session=session, operator_payload=SALES, correlation_id="same-request")
    assert result["operator_id"] == 3
    assert result["operator_name"] == SALES["name"]
    assert result["correlation_id"] == "same-request"
    assert result["changes"] == [{"field": "amount", "before": "12.00", "after": "14.00"}]
    assert "_audit_metadata" not in result["after_data"]
    session.rollback()
    assert session.query(AuditLogTable).count() == 0


def test_diff_tracks_line_ids_and_ignores_unchanged_fields():
    before = {"status": "draft", "amount": Decimal("10.00"), "lines": [{"id": 7, "amount": 10}, {"id": 8, "amount": 2}]}
    after = {"status": "posted", "amount": 10, "lines": [{"id": 8, "amount": 2}, {"id": 7, "amount": 15}]}
    assert field_changes(before, after) == [
        {"field": "lines[7].amount", "before": 10, "after": 15},
        {"field": "status", "before": "draft", "after": "posted"},
    ]
    assert field_changes({"is_final": False}, {"is_final": True}) == [
        {"field": "is_final", "before": False, "after": True}
    ]


def test_related_events_share_transaction_id_but_next_transaction_does_not(setup_test_database):
    session = setup_test_database
    first = record_audit("finance_document", "finance_document", 1, action="post", session=session)
    second = record_audit("finance_journal", "finance_journal", 2, action="post", session=session)
    assert first["correlation_id"] == second["correlation_id"]
    session.commit()
    third = record_audit("finance_document", "finance_document", 1, action="allocate", session=session)
    assert third["correlation_id"] != first["correlation_id"]


def test_receipt_creation_rolls_back_when_audit_insert_fails(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    body = _body(customer, orders, [50], settlement_status="unsettled")
    event.listen(AuditLogTable, "before_insert", _fail_audit_insert)
    try:
        with pytest.raises(RuntimeError, match="audit storage unavailable"):
            service.create_receipt(body, SALES)
    finally:
        event.remove(AuditLogTable, "before_insert", _fail_audit_insert)
    assert session.query(PaymentReceiptTable).count() == 0
    assert session.query(AuditLogTable).count() == 0


def test_receipt_approval_rolls_back_and_retry_records_real_before(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    receipt = service.create_receipt(_body(customer, orders, [100], settlement_status="settled"), SALES)
    event.listen(AuditLogTable, "before_insert", _fail_audit_insert)
    try:
        with pytest.raises(RuntimeError, match="audit storage unavailable"):
            service.review_receipt(receipt["id"], "approve", "到账核对", FINANCE)
    finally:
        event.remove(AuditLogTable, "before_insert", _fail_audit_insert)
    persisted = service.get_receipt_detail(receipt["id"], FINANCE)
    assert persisted["status"] == "pending"
    assert persisted["items"][0]["settlement_difference"] is None
    assert session.query(AuditLogTable).count() == 1
    approved = service.review_receipt(receipt["id"], "approve", "到账核对", FINANCE)
    logs = load_audit_logs(target_type="receipt", target_id=receipt["id"])["items"]
    assert len(logs) == 2
    assert logs[0]["before_data"]["status"] == "pending"
    assert logs[0]["after_data"]["status"] == approved["status"] == "approved"
    assert logs[0]["operator_id"] == FINANCE["user_id"]
    assert logs[0]["remark"] == "到账核对"
    assert any(change["field"].endswith("settlement_difference") for change in logs[0]["changes"])
    with pytest.raises(ValueError, match="已经审核"):
        service.review_receipt(receipt["id"], "approve", "重复", FINANCE)
    assert session.query(AuditLogTable).count() == 2


def test_receipt_history_uses_same_object_scope_as_receipt(client, setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database)
    receipt = service.create_receipt(_body(customer, orders, [50]), SALES)
    url = f"/api/receipts/{receipt['id']}/history"
    owner = client.get(url, headers={"x-token": create_jwt(SALES)})
    assert owner.status_code == 200
    data = owner.get_json()["data"]
    assert data["history_complete"] is True
    assert data["total"] == 1
    other_sales = {**SALES, "user_id": 77}
    assert client.get(url, headers={"x-token": create_jwt(other_sales)}).status_code == 403
    assert client.get(url, headers={"x-token": create_jwt(FINANCE)}).status_code == 200
    assert client.get("/api/audit-logs", headers={"x-token": create_jwt(SALES)}).status_code == 403


def test_legacy_receipt_history_discloses_gap(client, setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database)
    receipt = _add_receipt_history(setup_test_database, customer, orders[0])
    setup_test_database.commit()
    response = client.get(f"/api/receipts/{receipt.id}/history", headers={"x-token": create_jwt(FINANCE)})
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["items"] == []
    assert data["history_complete"] is False
    assert "不推测" in data["notice"]


def test_filters_are_applied_before_pagination_and_wildcards_are_literal(setup_test_database):
    session = setup_test_database
    for identifier, remark in ((1, "100%到账"), (2, "1000到账"), (3, "另一张单")):
        record_audit("payment_receipt", "receipt", identifier, action="create",
                     remark=remark, after_data={"amount": identifier, "receipt_no": f"RCPT-{identifier}"}, session=session,
                     operator_payload=FINANCE)
    session.commit()
    result = load_audit_logs(event_type="payment_receipt", query_text="100%", page_size=1)
    assert result["total"] == 1
    assert result["items"][0]["target_id"] == "1"
    assert load_audit_logs(target_type="receipt", target_id=3)["total"] == 1
    assert load_audit_logs(query_text="RCPT-2")["items"][0]["target_id"] == "2"


def test_bonus_configuration_keeps_actor_snapshot_outside_http(setup_test_database):
    from data.finance.BonusItem import bonus_item_model
    _seed_world(setup_test_database)
    with patch("data.finance.BonusItem.SessionFactory", return_value=setup_test_database):
        created = bonus_item_model.create_item("审核奖金", 20, 1, 0, 100, operator_id=1)
        bonus_item_model.update_item(created["id"], {"base_amount": 25}, operator_id=3)
    events = load_audit_logs(target_type="bonus_item", target_id=created["id"])["items"]
    assert events[0]["operator_id"] == 3
    assert events[0]["operator_name"] == SALES["name"]
    assert events[0]["after_data"]["updated_by_name"] == SALES["name"]
    assert events[1]["operator_id"] == 1
