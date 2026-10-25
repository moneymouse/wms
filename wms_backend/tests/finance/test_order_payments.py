"""Order detail cash reads preserve allocation semantics and payment visibility."""
import json

import pytest

from Auth import create_jwt
from data.DB import CargoTable, OrderTable
from data.customer.Customer import CustomerTable
from data.finance.ledger import FinanceAllocation, FinanceDocument, FinancePayment
from data.finance.order_settlement import FinanceOrderSettlement
from services import finance_ledger_service as ledger
from services import finance_order_service as orders
from tests.conftest import TestSessionFactory
from tests.finance.test_customer_payments import OTHER_SALES, body
from tests.finance.test_ledger import ACTOR, SALES, document, finance, payment
from tests.finance.test_order_settlement import TODAY, allocate, order_finance, price, sync


def read(uid="order-one", actor=ACTOR, **paging):
    return orders.list_order_payments(uid, actor, **paging)


def test_order_references_are_exact_notes_and_pagination_does_not_limit_totals(order_finance):
    first = payment(order_finance, "120", reference_order_uids=["order-one", "order-two"])
    second = payment(order_finance, "30", reference_order_uids=["order-one"])
    payment(order_finance, "900", reference="ORDER-one", memo="order-one")
    pending = ledger.create_payment(body(order_finance, reference_order_uids=["order-one"]), SALES)
    ledger.submit_payment(pending["id"], {"version": pending["version"]}, SALES)
    draft = ledger.create_payment(body(order_finance, amount="40", reference_order_uids=["order-one"]), SALES)
    cancelled = ledger.create_payment(body(order_finance, reference_order_uids=["order-one"]), SALES)
    ledger.cancel_payment(cancelled["id"], {"version": cancelled["version"], "reason": "录错"}, SALES)
    result = read(page=2, page_size=2)
    assert result["total"] == 5
    assert result["page"] == 2 and result["page_size"] == 2
    assert [item["id"] for item in result["items"]] == [pending["id"], second["id"]]
    assert result["summary"] == {"received_amount": "0.00", "refunded_amount": "0.00",
        "net_received_amount": "0.00", "related_received_amount": "150.00", "related_refunded_amount": "0.00",
        "draft_count": 1, "pending_count": 1}
    assert read("order-two")["summary"]["related_received_amount"] == "120.00"
    assert read("order-two")["items"][0]["relation_types"] == ["reference"]
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0
        assert session.query(FinanceAllocation).count() == 0
        assert session.query(FinanceOrderSettlement).count() == 0


def test_order_allocations_use_only_this_order_and_keep_reversed_history(order_finance):
    cash = payment(order_finance, "200", payment_date=TODAY,
        reference_order_uids=["order-one", "order-two"])
    allocation = allocate(cash, "60")["items"][0]
    allocate(cash, "40", uid="order-two")
    result = read()
    assert result["summary"]["received_amount"] == "60.00"
    assert result["summary"]["related_received_amount"] == "200.00"
    assert result["items"][0]["order_allocated_amount"] == "60.00"
    assert result["items"][0]["relation_types"] == ["reference", "allocation"]
    ledger.reverse_allocation(allocation["id"], {"version": allocation["version"],
        "reversal_date": TODAY, "reason": "核销错单"}, ACTOR)
    assert read()["summary"]["received_amount"] == "0.00"
    assert read()["items"][0]["order_allocated_amount"] == "0.00"
    assert read("order-two")["summary"]["received_amount"] == "40.00"


def test_allocated_cash_without_order_note_and_refunds_are_visible(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    allocate(cash, "100")
    price(8)
    sync()
    refund = payment(order_finance, "20", direction="outgoing", payment_date=TODAY)
    allocate(refund, "20")
    result = read()
    assert result["summary"]["received_amount"] == "100.00"
    assert result["summary"]["refunded_amount"] == "20.00"
    assert result["summary"]["net_received_amount"] == "80.00"
    assert result["summary"]["related_refunded_amount"] == "20.00"
    assert all(item["relation_types"] == ["allocation"] for item in result["items"])
    allocation = next(item for item in ledger.list_allocations(ACTOR)["items"] if item["payment_id"] == refund["id"])
    ledger.reverse_allocation(allocation["id"], {"version": allocation["version"],
        "reversal_date": TODAY, "reason": "退款核销撤销"}, ACTOR)
    ledger.reverse_payment(refund["id"], {"version": ledger.get_payment(refund["id"], ACTOR)["version"],
        "reversal_date": TODAY, "reason": "退款作废"}, ACTOR)
    result = read()
    assert result["total"] == 2
    assert result["summary"]["refunded_amount"] == "0.00"
    assert result["summary"]["related_refunded_amount"] == "0.00"
    assert result["items"][0]["status"] == "reversed"


def test_ordinary_multi_order_invoice_lines_cannot_attribute_whole_allocation(order_finance):
    invoice = document(order_finance, lines=[
        {"description": "第一单", "unit_price": "60", "order_uid": "order-one"},
        {"description": "第二单", "unit_price": "40", "order_uid": "order-two"}])
    cash = payment(order_finance, "100", reference_order_uids=["order-one"])
    ledger.create_allocations({"payment_id": cash["id"], "version": cash["version"],
        "allocation_date": TODAY, "allocations": [{"document_id": invoice["id"], "amount": "100"}]}, ACTOR)
    assert read()["summary"]["received_amount"] == "0.00"
    assert read()["items"][0]["relation_types"] == ["reference"]
    assert read("order-two")["total"] == 0


def test_current_packing_box_links_follow_order_and_customer_without_changing_cash(order_finance):
    cash = payment(order_finance, "50")
    with TestSessionFactory() as session:
        session.get(FinancePayment, cash["id"]).reference_packing_boxes_json = json.dumps([
            {"box_uid": "cargo-one", "target_order_uid": "order-two"}])
        session.commit()
    assert read()["items"][0]["relation_types"] == ["packing"]
    assert read()["summary"]["received_amount"] == "0.00"
    allocate(cash, "30")
    with TestSessionFactory() as session:
        session.get(CargoTable, "cargo-one").target_order_uid = "order-two"
        session.commit()
    assert read()["items"][0]["relation_types"] == ["allocation"]
    assert read()["summary"]["received_amount"] == "30.00"
    assert read("order-two")["items"][0]["relation_types"] == ["packing"]
    with TestSessionFactory() as session:
        session.get(OrderTable, "order-two").customers = [session.get(CustomerTable, order_finance["other_customer"])]
        session.commit()
    assert read("order-two")["total"] == 0
    assert read()["summary"]["received_amount"] == "30.00"


def test_sales_records_and_summary_share_existing_payment_visibility(order_finance):
    owned = ledger.create_payment(body(order_finance, reference_order_uids=["order-one"]), SALES)
    pending = ledger.submit_payment(owned["id"], {"version": owned["version"]}, SALES)
    posted = ledger.post_payment(owned["id"], {"version": pending["version"]}, ACTOR)
    allocate(posted, "25")
    ledger.create_payment(body(order_finance, amount="70", reference_order_uids=["order-one"]), OTHER_SALES)
    payment(order_finance, "80", reference_order_uids=["order-one"])
    mine = read(actor=SALES)
    assert mine["visibility"] == "own" and mine["total"] == 1
    assert mine["items"][0]["id"] == owned["id"]
    assert mine["summary"]["received_amount"] == "25.00"
    assert mine["summary"]["related_received_amount"] == "100.00"
    assert mine["summary"]["draft_count"] == 0
    assert read()["visibility"] == "all" and read()["total"] == 3
    assert read()["summary"]["related_received_amount"] == "180.00"
    assert read(actor=OTHER_SALES)["summary"]["received_amount"] == "0.00"


def test_order_payment_http_permissions_and_missing_order(order_finance, client):
    path = "/api/finance/v2/order-payments/order-one"
    payment(order_finance, "120", reference_order_uids=["order-one"])
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"x-token": create_jwt({"id": 1, "role": "clerk"})}).status_code == 403
    headers = {"x-token": create_jwt(ACTOR)}
    response = client.get(path + "?p=1&s=1", headers=headers)
    assert response.status_code == 200
    assert response.json["data"]["total"] == 1
    assert response.json["data"]["items"][0]["amount"] == "120.00"
    assert client.get("/api/finance/v2/order-payments/does-not-exist", headers=headers).status_code == 404
    with pytest.raises(PermissionError):
        read(actor={"id": 1, "roles": ["store_manager"]})


def test_opening_cash_is_labelled_and_excluded_for_sales_after_role_change(order_finance):
    opening = payment(order_finance, "50", is_opening=True, payment_date="2026-01-01",
        reference_order_uids=["order-one"])
    with TestSessionFactory() as session:
        session.get(FinancePayment, opening["id"]).created_by_id = SALES["id"]
        session.commit()
    assert read()["items"][0]["is_opening"] is True
    assert read()["summary"]["related_received_amount"] == "50.00"
    assert read(actor=SALES)["total"] == 0
    assert read(actor=SALES)["summary"]["related_received_amount"] == "0.00"
