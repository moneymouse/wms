"""Unrestricted order edits and re-quote adjustment regressions."""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from data import order_model
from data.DB import (
    BoxCostRecordTable,
    CargoTable,
    OrderTable,
    OrderPriceAdjustmentTable,
    OrderQuoteVersionTable,
    OrderReceiptRevisionTable,
    PaymentReceiptItemTable,
)
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable
from services import receivable_service
from services.order_edit_policy import (
    OrderEditConflictError,
    build_edit_policy,
)
from tests.unit.test_order_receipt_revision import (
    ADMIN,
    _add_receipt_history,
    _headers,
    _mark_order_fully_outbound,
    _seed_world,
)


SALES = {"user_id": 3, "name": "业务员测试", "role": "salesperson"}


@pytest.mark.parametrize("with_receipt", [False, True])
def test_fully_outbound_order_remains_editable(setup_test_database, with_receipt):
    session = setup_test_database
    customer, orders, cargos = _seed_world(session)
    order = orders[0]
    if with_receipt:
        _add_receipt_history(session, customer, order, status="approved")
    _mark_order_fully_outbound(session, order, cargos[0])
    policy = build_edit_policy(session, order.uid, {"salesperson"}, 3)["edit_policy"]
    assert policy["fully_outbound"] is True
    for field in ("transportation", "tracking_numbers", "order_weight", "box_membership", "customer_assignment"):
        assert policy[field] is True
    assert "lock_status" not in policy
    assert "financial_locked" not in policy


def test_clerk_is_a_box_editor_but_not_a_box_weigher(setup_test_database):
    session = setup_test_database
    _, orders, _ = _seed_world(session)

    policy = build_edit_policy(
        session, orders[0].uid, {"clerk"}, current_user_id=99
    )["edit_policy"]

    assert policy["box_content"] is True
    assert policy["tracking_numbers"] is True
    assert policy["box_workers"] is True
    assert policy["box_weight"] is False


def test_outbound_order_with_receipts_can_be_archived_in_batch(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, orders, cargos = _seed_world(session)
    order = orders[0]
    order_uid = order.uid
    receipt = _add_receipt_history(session, customer, order, status="rejected")
    receipt_id = receipt.id
    pending_quote = receivable_service.create_order_quote(
        order_uid,
        {"unit_price": 10, "surcharge": 0, "quote_remark": "待审报价"},
        SALES,
    )
    assert pending_quote["status"] == "pending"
    receivable_service.create_order_quote(
        order_uid,
        {"unit_price": 13, "surcharge": 0, "quote_remark": "生效报价"},
        SALES,
    )
    _mark_order_fully_outbound(session, order, cargos[0])
    session.add(OrderReceiptRevisionTable(
        order_uid=order_uid, status="open", reason="历史修订",
        opened_by_id=1, opened_by_name="管理员", opened_at="2026-09-17 10:00:00",
    ))
    session.add(
        BoxCostRecordTable(
            box_uid=cargos[0].uid,
            packing_list_uid=cargos[0].packing_list_uid,
            order_uid=order_uid,
            transportation_name=order.transportation or "",
            waybill_id=cargos[0].waybill_id,
            weight=cargos[0].weight,
            unit_cost=10,
            total_cost=105,
            create_date="2026-09-17 10:00:00",
        )
    )
    session.commit()

    response = client.post(
        "/api/orders/archive",
        headers=_headers(salesperson_token),
        json={"uid_list": [order_uid]},
    )
    assert response.status_code == 200

    session.expire_all()
    assert session.query(OrderTable).filter_by(uid=order_uid).one().archive is True
    assert all(
        row.archive is True
        for row in session.query(CargoTable).filter_by(target_order_uid=order_uid).all()
    )
    assert all(
        row.archive is True
        for row in session.query(OrderQuoteVersionTable).filter_by(order_uid=order_uid).all()
    )
    assert session.query(BoxCostRecordTable).filter_by(order_uid=order_uid).one().archive is True
    assert session.query(OrderPriceAdjustmentTable).filter_by(order_uid=order_uid).one().archive is True
    assert session.query(PaymentReceiptItemTable).filter_by(order_uid=order_uid).one().archive is True
    revision = (
        session.query(OrderReceiptRevisionTable)
        .filter_by(order_uid=order_uid)
        .one()
    )
    assert revision.status == "open"
    assert revision.close_type is None

    approvals = client.get(
        "/api/finance/quote-approvals",
        headers=_headers(admin_token),
    )
    assert approvals.status_code == 200
    assert approvals.get_json()["data"] == []
    assert receivable_service.list_price_adjustments(ADMIN)["items"] == []
    assert receivable_service.accounts_receivable_ledger()["items"] == []
    receipt_detail = receivable_service.get_receipt_detail(receipt_id, ADMIN)
    assert receipt_detail["items"][0]["archive"] is True


def test_cascade_archive_rolls_back_all_records_on_failure(setup_test_database):
    session = setup_test_database
    _, orders, cargos = _seed_world(session)
    order_uid = orders[0].uid
    _mark_order_fully_outbound(session, orders[0], cargos[0])

    with patch(
        "data.order_version.record_mutation",
        side_effect=RuntimeError("version write failed"),
    ):
        with pytest.raises(RuntimeError, match="version write failed"):
            order_model.archive_many([order_uid])

    session.expire_all()
    assert session.query(OrderTable).filter_by(uid=order_uid).one().archive is False
    assert all(
        row.archive is False
        for row in session.query(CargoTable).filter_by(target_order_uid=order_uid).all()
    )
    assert all(
        row.archive is False
        for row in session.query(OrderQuoteVersionTable).filter_by(order_uid=order_uid).all()
    )


def test_outbound_order_without_snapshots_can_be_deleted_in_batch(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    creator = UserTable(
        id=99,
        phone="13800000099",
        name="删除测试用户",
        password="unused",
        status="approved",
    )
    order = OrderTable(
        uid="locked-delete-order",
        order_id="LOCKED-DELETE-001",
        archive=False,
        create_date="2026-09-17 10:00:00",
    )
    packing_list = PackingListTable(
        uid="locked-delete-packing",
        list_number="LOCKED-DELETE-PL",
        creator_id=creator.id,
        status="completed",
        archive=False,
        create_date="2026-09-17 10:00:00",
    )
    box = CargoTable(
        uid="locked-delete-box",
        target_order_uid=order.uid,
        packing_list_uid=packing_list.uid,
        status=1,
        waybill_id="LOCKED-DELETE-WB",
        archive=False,
        create_date="2026-09-17 10:00:00",
    )
    session.add_all([creator, order, packing_list, box])
    session.commit()
    assert build_edit_policy(session, order.uid, {"admin"}, 1)["edit_policy"]["fully_outbound"] is True

    response = client.delete(
        "/api/orders",
        headers=_headers(salesperson_token),
        json={"uid_list": [order.uid]},
    )
    assert response.status_code == 200

    session.expire_all()
    assert session.query(OrderTable).filter_by(uid=order.uid).first() is None


@pytest.mark.parametrize("batch", [False, True])
def test_delete_preserves_referenced_history_with_foreign_keys_enabled(
    setup_test_database, batch
):
    session = setup_test_database
    connection = session.get_bind().connect()
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    connection.commit()
    try:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        customer, orders, cargos = _seed_world(session)
        order, cargo = orders[0], cargos[0]
        _mark_order_fully_outbound(session, order, cargo)
        receipt = _add_receipt_history(session, customer, order, status="approved")
        cost = BoxCostRecordTable(
            box_uid=cargo.uid,
            packing_list_uid=cargo.packing_list_uid,
            order_uid=order.uid,
            transportation_name=order.transportation,
            waybill_id=cargo.waybill_id,
            weight=cargo.weight,
            unit_cost=10,
            total_cost=105,
            create_date="2026-10-05 10:00:00",
        )
        session.add(cost)
        session.commit()
        order_uid, cargo_uid, receipt_id, cost_id = order.uid, cargo.uid, receipt.id, cost.id

        if batch:
            assert order_model.delete_many([order_uid]) == [order_uid]
        else:
            order_model.delete(order_uid)

        session.expire_all()
        assert session.query(OrderTable).filter_by(uid=order_uid).one().archive is True
        assert session.query(CargoTable).filter_by(uid=cargo_uid).one().archive is True
        assert session.query(OrderQuoteVersionTable).filter_by(order_uid=order_uid).one().archive is True
        assert session.query(PaymentReceiptItemTable).filter_by(receipt_id=receipt_id).one().amount == 20
        assert session.query(BoxCostRecordTable).filter_by(id=cost_id).one().total_cost == 105
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        session.rollback()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        connection.close()


def _requote(session, *, unit_price, with_receipt=True):
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    if with_receipt:
        _add_receipt_history(session, customer, order, status="rejected")
    result = receivable_service.create_order_quote(
        order.uid,
        {"unit_price": unit_price, "surcharge": 0, "quote_remark": "重报价"},
        SALES,
    )
    return order, result


def _settle_original_quote(session, customer, order):
    receipt = _add_receipt_history(session, customer, order, status="approved")
    receipt.settlement_status = "settled"
    item = (
        session.query(PaymentReceiptItemTable)
        .filter(PaymentReceiptItemTable.receipt_id == receipt.id)
        .one()
    )
    item.amount = item.receivable_snapshot
    item.remaining_after = 0
    item.settlement_difference = 0
    session.commit()
    return receipt


def test_effective_requote_creates_positive_pending_adjustment(setup_test_database):
    session = setup_test_database
    order, quote = _requote(session, unit_price=13)

    adjustment = session.query(OrderPriceAdjustmentTable).one()
    assert quote["status"] == "adopted"
    assert adjustment.order_uid == order.uid
    assert float(adjustment.delta_amount) == 11.0
    assert adjustment.direction == "collect"
    assert adjustment.status == "pending"
    listed = receivable_service.list_price_adjustments(SALES)
    assert listed["total"] == 1
    assert listed["items"][0]["new_quote_id"] == quote["id"]


def test_effective_requote_creates_negative_pending_adjustment(setup_test_database):
    session = setup_test_database
    _, quote = _requote(session, unit_price=11)

    adjustment = session.query(OrderPriceAdjustmentTable).one()
    assert quote["status"] == "adopted"
    assert float(adjustment.delta_amount) == -11.0
    assert adjustment.direction == "refund"


def test_equal_requote_and_quote_without_receipt_create_no_adjustment(
    setup_test_database,
):
    session = setup_test_database
    _requote(session, unit_price=12)
    assert session.query(OrderPriceAdjustmentTable).count() == 0

    session.rollback()


def test_low_price_adjustment_is_created_only_after_approval(
    client, setup_test_database, admin_token
):
    session = setup_test_database
    _, quote = _requote(session, unit_price=10)
    assert quote["status"] == "pending"
    assert session.query(OrderPriceAdjustmentTable).count() == 0

    response = client.put(
        f"/api/finance/quote-approvals/{quote['id']}",
        headers=_headers(admin_token),
        json={"action": "approve", "review_remark": "同意退款差价"},
    )

    assert response.status_code == 200
    adjustment = session.query(OrderPriceAdjustmentTable).one()
    assert float(adjustment.delta_amount) == -22.0
    assert adjustment.direction == "refund"
    assert adjustment.new_quote_id == quote["id"]


def test_quote_without_receipt_history_does_not_create_adjustment(
    setup_test_database,
):
    session = setup_test_database
    _requote(session, unit_price=13, with_receipt=False)
    assert session.query(OrderPriceAdjustmentTable).count() == 0


def test_positive_adjustment_reopens_collection_after_old_quote_was_settled(
    setup_test_database,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _settle_original_quote(session, customer, order)

    receivable_service.create_order_quote(
        order.uid, {"unit_price": 13, "surcharge": 0}, SALES
    )
    available = receivable_service.list_receivable_orders(
        customer.id, SALES
    )["items"]

    assert len(available) == 1
    assert available[0]["available_amount"] == 11.0


def test_negative_adjustment_exposes_refund_due_in_finance_ledger(
    setup_test_database,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _settle_original_quote(session, customer, order)

    receivable_service.create_order_quote(
        order.uid, {"unit_price": 11, "surcharge": 0}, SALES
    )
    ledger = receivable_service.accounts_receivable_ledger(date_to="2099-12-31")

    assert ledger["items"][0]["settlement_status"] == "refund_due"
    assert ledger["items"][0]["refund_due"] == 11.0
    assert ledger["items"][0]["signed_balance"] == -11.0
    assert ledger["totals"]["refund_due"] == 11.0
