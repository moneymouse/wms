"""Order edit regression coverage and shared finance fixtures."""

from decimal import Decimal

import pytest

from data.DB import (
    CargoTable,
    OrderQuoteVersionTable,
    OrderTable,
    PaymentReceiptItemTable,
    PaymentReceiptTable,
    TransportationModeTable,
)
from data.customer.Customer import CustomerTable
from data.packing.PackingList import PackingListTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import receivable_service


NOW = "2026-09-04 09:00:00"
ADMIN = {"user_id": 1, "name": "管理员测试", "role": "admin"}


def _seed_world(session, order_count=1):
    """Shared finance fixture retained for settlement/concurrency tests."""
    admin_role = RoleTable(name="admin", label="管理员")
    salesperson_role = RoleTable(name="salesperson", label="业务员")
    admin = UserTable(
        id=1,
        phone="13800000001",
        name="管理员测试",
        password="unused",
        status="approved",
    )
    salesperson = UserTable(
        id=3,
        phone="13800000003",
        name="业务员测试",
        password="unused",
        status="approved",
    )
    admin.roles = [admin_role]
    salesperson.roles = [salesperson_role]
    customer = CustomerTable(name="修订窗口测试客户")
    mode = TransportationModeTable(
        name="修订测试渠道",
        channel_group="revision-test",
        cost=10,
        min_price=11,
        archive=False,
        create_date=NOW,
    )
    session.add_all([admin, salesperson, customer, mode])
    session.flush()

    orders = []
    cargos = []
    for index in range(1, order_count + 1):
        order = OrderTable(
            uid=f"revision-order-{index}",
            order_id=f"REV-{index:03d}",
            customer_name=customer.name,
            transportation=mode.name,
            total_weight=10.5,
            cargo_count=1,
            tag_all=f"REV-{index}",
            salesman_id=salesperson.id,
            archive=False,
            create_date=NOW,
        )
        order.customers = [customer]
        cargo = CargoTable(
            uid=f"revision-cargo-{index}",
            origin_id=f"REV-{index:03d}-1",
            target_order_uid=order.uid,
            weight=10.5 + index - 1,
            count=1,
            status=0,
            bonus_assigned=False,
            archive=False,
            create_date=NOW,
        )
        session.add_all([order, cargo])
        orders.append(order)
        cargos.append(cargo)
    session.flush()

    for order in orders:
        raw_weight = receivable_service.current_order_weight(session, order.uid)
        billing_weight = receivable_service.current_order_billing_weight(
            session, order.uid
        )
        amount = receivable_service.calculate_receivable(
            billing_weight, Decimal("12"), Decimal("0")
        )
        session.add(
            OrderQuoteVersionTable(
                order_uid=order.uid,
                version_no=1,
                transportation_mode_id=mode.id,
                transportation_name=mode.name,
                channel_cost=mode.cost,
                min_price=mode.min_price,
                unit_price=Decimal("12"),
                surcharge=Decimal("0"),
                weight_snapshot=raw_weight,
                billing_weight_snapshot=billing_weight,
                receivable_amount=amount,
                quoted_price=12,
                status="adopted",
                is_final=True,
                quoter_id=salesperson.id,
                quoter_name=salesperson.name,
                create_date=NOW,
                effective_date=NOW,
            )
        )
    session.commit()
    return customer, orders, cargos


def _add_receipt_history(session, customer, order, status="rejected"):
    receipt = PaymentReceiptTable(
        receipt_no=f"RCPT-{status.upper()}-{order.order_id}",
        customer_id=customer.id,
        customer_name=customer.name,
        receipt_date="2026-09-04",
        payment_method="bank_transfer",
        status=status,
        settlement_status="unsettled",
        creator_id=3,
        creator_name="业务员测试",
        reviewer_id=1 if status != "pending" else None,
        reviewer_name="管理员测试" if status != "pending" else None,
        review_date=NOW if status != "pending" else None,
        create_date=NOW,
        update_date=NOW,
    )
    session.add(receipt)
    session.flush()
    session.add(
        PaymentReceiptItemTable(
            receipt_id=receipt.id,
            order_uid=order.uid,
            order_id=order.order_id,
            receivable_snapshot=Decimal("132.00"),
            received_before=Decimal("0.00"),
            amount=Decimal("20.00"),
            remaining_after=Decimal("112.00"),
        )
    )
    session.commit()
    return receipt


def _mark_order_fully_outbound(session, order, cargo):
    packing_list = PackingListTable(
        uid=f"packing-{order.uid}",
        list_number=f"PL-{order.order_id}",
        customer_id=order.customers[0].id if order.customers else None,
        creator_id=1,
        status="completed",
        archive=False,
        create_date=NOW,
    )
    session.add(packing_list)
    session.flush()
    cargo.packing_list_uid = packing_list.uid
    cargo.status = 1
    cargo.waybill_id = f"WB-{order.order_id}"
    session.commit()


def _headers(token):
    return {"x-token": token, "Content-Type": "application/json"}


@pytest.mark.parametrize("receipt_status", ["pending", "approved", "rejected"])
def test_receipt_history_does_not_restrict_order_edits(
    setup_test_database, receipt_status
):
    from data import order_model, cargo_model
    from services.order_edit_policy import build_edit_policy

    session = setup_test_database
    customer, orders, cargos = _seed_world(session)
    order, cargo = orders[0], cargos[0]
    receipt = _add_receipt_history(session, customer, order, status=receipt_status)
    item_id = session.query(PaymentReceiptItemTable.id).filter_by(receipt_id=receipt.id).scalar()
    order_uid, cargo_uid = order.uid, cargo.uid

    order_model.update(order_uid, {"total_weight": 15.0, "transportation": "新渠道"})
    cargo_model.update(cargo_uid, {"weight": 15.0})
    cargo_model.unbind_from_order(cargo_uid)

    session.expire_all()
    assert session.query(OrderTable).filter_by(uid=order_uid).one().total_weight == 15.0
    assert session.query(CargoTable).filter_by(uid=cargo_uid).one().weight == 15.0
    assert session.query(CargoTable).filter_by(uid=cargo_uid).one().target_order_uid is None
    assert session.query(PaymentReceiptItemTable).filter_by(id=item_id).one().amount == Decimal("20.00")
    policy = build_edit_policy(session, order_uid, {"admin"}, 1)["edit_policy"]
    assert policy["order_weight"] is True
    assert policy["cargo_weight"] is True
    assert policy["box_membership"] is True
    assert policy["customer_assignment"] is True
    assert not {"lock_status", "revision_open", "financial_locked", "has_receipt_history"} & policy.keys()


def test_old_lock_routes_are_removed(client, setup_test_database, admin_token):
    _, orders, cargos = _seed_world(setup_test_database)
    _mark_order_fully_outbound(setup_test_database, orders[0], cargos[0])
    for suffix in ("receipt-unlock", "receipt-relock"):
        response = client.post(
            f"/api/orders/{orders[0].uid}/{suffix}",
            headers=_headers(admin_token),
            json={"reason": "旧客户端"},
        )
        assert response.status_code in {404, 405}
    assert client.get("/api/admin/order-revisions/open", headers=_headers(admin_token)).status_code == 404


def test_approved_receipt_does_not_restrict_customer_assignment(setup_test_database):
    from data import order_model

    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    receipt = _add_receipt_history(session, customer, orders[0], status="approved")
    next_customer = CustomerTable(name="变更后的订单客户")
    session.add(next_customer)
    session.commit()
    order_uid = orders[0].uid
    old_customer_id, old_customer_name = customer.id, customer.name
    next_customer_id, receipt_id = next_customer.id, receipt.id

    assert order_model.add_customer(order_uid, next_customer_id) is True
    assert order_model.remove_customer(order_uid, old_customer_id) is True
    current = session.query(OrderTable).filter_by(uid=order_uid).one()
    assert [row.id for row in current.customers] == [next_customer_id]
    assert order_model.set_customers(order_uid, [old_customer_id]) is True

    session.expire_all()
    current = session.query(OrderTable).filter_by(uid=order_uid).one()
    assert [row.id for row in current.customers] == [old_customer_id]
    historical_receipt = session.query(PaymentReceiptTable).filter_by(id=receipt_id).one()
    assert historical_receipt.customer_id == old_customer_id
    assert historical_receipt.customer_name == old_customer_name
    item = session.query(PaymentReceiptItemTable).filter_by(receipt_id=receipt_id).one()
    assert item.amount == Decimal("20.00")
    assert item.receivable_snapshot == Decimal("132.00")


def test_historical_open_revision_does_not_affect_current_snapshot(setup_test_database):
    from data.DB import OrderReceiptRevisionTable
    from data.order_version import snapshot_order
    from services.order_edit_policy import build_edit_policy

    session = setup_test_database
    _, orders, cargos = _seed_world(session)
    _mark_order_fully_outbound(session, orders[0], cargos[0])
    session.add(OrderReceiptRevisionTable(
        order_uid=orders[0].uid, status="open", reason="历史记录",
        opened_by_id=1, opened_by_name="管理员", opened_at=NOW,
    ))
    session.commit()
    policy = build_edit_policy(session, orders[0].uid, {"admin"}, 1)["edit_policy"]
    assert policy["transportation"] is True
    assert policy["tracking_numbers"] is True
    snapshot = snapshot_order(session, orders[0].uid)
    assert "revision_status" not in snapshot["order"]
    assert "revision_reason" not in snapshot["order"]
