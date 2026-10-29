"""Personal unregistered quotes, live money notes and exact paginated totals."""
import json

import pytest

from Auth import create_jwt
from data.DB import OrderQuoteVersionTable
from data.finance.ledger import FinanceAccount, FinanceAllocation, FinanceDocument, FinanceDocumentLine, FinancePayment
from services import receivable_service as service
from tests.unit.test_order_receipt_revision import ADMIN, NOW, _add_receipt_history, _seed_world
from tests.unit.test_receipt_settlement import SALES


def _payment(session, customer, orders=(), *, status="pending", direction="incoming", boxes=()):
    account = session.query(FinanceAccount).first()
    if account is None:
        account = FinanceAccount(name="测试账户", account_type="bank", created_at=NOW, updated_at=NOW)
        session.add(account)
        session.flush()
    payment = FinancePayment(number=f"TEST-{session.query(FinancePayment).count()}",
        direction=direction, partner_type="customer", partner_id=customer.id, partner_name=customer.name,
        account_id=account.id, account_name=account.name, payment_date="2026-09-04", amount=1,
        reference_orders_json=json.dumps([{"order_uid": order.uid} for order in orders]),
        reference_packing_boxes_json=json.dumps([{"box_uid": box.uid} for box in boxes]),
        status=status, created_by_id=999, created_by_name="另一登记人", created_at=NOW, updated_at=NOW)
    session.add(payment)
    session.commit()
    return payment


def _get(client, actor=SALES, **filters):
    return client.get("/api/receivables/unregistered-orders", query_string=filters,
                      headers={"x-token": create_jwt(actor)})


@pytest.mark.parametrize("status,hidden", [("draft", True), ("pending", True), ("posted", True),
                                           ("cancelled", False), ("reversed", False)])
@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
def test_live_registration_notes_exclude_before_count_and_pagination(client, setup_test_database, status, hidden, direction):
    customer, orders, _ = _seed_world(setup_test_database, order_count=3)
    _payment(setup_test_database, customer, orders[:2], status=status, direction=direction)
    first = _get(client, s=1).get_json()
    assert first["total"] == (1 if hidden else 3)
    assert len(first["data"]) == 1
    assert first["data"][0]["uid"] == orders[2].uid
    assert first["data"][0]["receivable_amount"] == 156
    assert _get(client, p=2, s=1).get_json()["total"] == first["total"]
    assert len(_get(client, p=2, s=1).get_json()["data"]) == (0 if hidden else 1)


def test_personal_scope_uses_current_effective_quote_owner_even_for_admin(client, setup_test_database):
    _, orders, _ = _seed_world(setup_test_database, order_count=2)
    quote = setup_test_database.query(OrderQuoteVersionTable).filter_by(order_uid=orders[1].uid).one()
    quote.quoter_id = ADMIN["user_id"]
    setup_test_database.commit()
    assert [row["uid"] for row in _get(client, owner_id=1).get_json()["data"]] == [orders[0].uid]
    assert [row["uid"] for row in _get(client, actor=ADMIN, owner_id=3).get_json()["data"]] == [orders[1].uid]
    assert _get(client, order_uid=orders[1].uid).get_json()["total"] == 0


@pytest.mark.parametrize("status,hidden", [("pending", True), ("approved", True), ("rejected", False)])
def test_partial_legacy_receipt_counts_as_registration(client, setup_test_database, status, hidden):
    customer, orders, _ = _seed_world(setup_test_database)
    _add_receipt_history(setup_test_database, customer, orders[0], status=status)
    assert _get(client).get_json()["total"] == (0 if hidden else 1)


def test_packing_box_notes_use_live_customer_checked_ownership(client, setup_test_database):
    customer, orders, cargos = _seed_world(setup_test_database, order_count=2)
    # Keep the original order collectible after its only box moves elsewhere.
    setup_test_database.query(OrderQuoteVersionTable).filter_by(order_uid=orders[0].uid).one().surcharge = 1
    _payment(setup_test_database, customer, boxes=cargos[:1])
    assert [row["uid"] for row in _get(client).get_json()["data"]] == [orders[1].uid]
    cargos[0].target_order_uid = orders[1].uid
    setup_test_database.commit()
    assert [row["uid"] for row in _get(client).get_json()["data"]] == [orders[0].uid]
    cargos[0].archive = True
    setup_test_database.commit()
    assert _get(client).get_json()["total"] == 2


@pytest.mark.parametrize("snapshot", ["broken json", "{}", "null", '[null, 1, {}, {"order_uid": []}]'])
def test_bad_legacy_notes_do_not_break_list(client, setup_test_database, snapshot):
    customer, _, _ = _seed_world(setup_test_database)
    payment = _payment(setup_test_database, customer)
    payment.reference_orders_json = snapshot
    payment.reference_packing_boxes_json = snapshot
    setup_test_database.commit()
    response = _get(client)
    assert response.status_code == 200
    assert response.get_json()["total"] == 1


def test_posted_allocations_count_without_optional_order_notes(client, setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database)
    payment = _payment(setup_test_database, customer, status="posted")
    document = FinanceDocument(number="TEST-INVOICE", document_type="customer_invoice", partner_type="customer",
        partner_id=customer.id, partner_name=customer.name, document_date="2026-09-04", due_date="2026-09-04",
        status="posted", subtotal=132, tax_amount=0, total_amount=132, created_by_name="财务",
        created_at=NOW, updated_at=NOW)
    setup_test_database.add(document)
    setup_test_database.flush()
    setup_test_database.add(FinanceDocumentLine(document_id=document.id, sequence=1, description="订单运费",
        quantity=1, unit_price=132, subtotal=132, tax_amount=0, total_amount=132, order_uid=orders[0].uid))
    allocation = FinanceAllocation(payment_id=payment.id, document_id=document.id, document_number=document.number,
        amount=1, status="active", allocation_date="2026-09-04", created_by_name="财务", created_at=NOW)
    setup_test_database.add(allocation)
    setup_test_database.commit()
    assert _get(client).get_json()["total"] == 0
    allocation.status = "reversed"
    setup_test_database.commit()
    assert _get(client).get_json()["total"] == 1


def test_filters_and_effective_quote_requirements(client, setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database, order_count=3)
    orders[0].archive = True
    setup_test_database.query(OrderQuoteVersionTable).filter_by(order_uid=orders[1].uid).one().status = "pending"
    setup_test_database.commit()
    assert _get(client, q="REV-003", customer_id=customer.id, date_from="2026-09-04", date_to="2026-09-04").get_json()["total"] == 1
    assert _get(client, q="REV-002").get_json()["total"] == 0
    assert _get(client, date_from="2026-09-05").get_json()["total"] == 0
    assert _get(client, date_from="bad").status_code == 400
    assert _get(client, date_from="2026-09-05", date_to="2026-09-04").status_code == 400
    assert _get(client, actor={"user_id": 5, "role": "store_manager"}).status_code == 403
