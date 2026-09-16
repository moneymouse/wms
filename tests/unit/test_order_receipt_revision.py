"""管理员订单收据修订窗口。"""

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


def _headers(token):
    return {"x-token": token, "Content-Type": "application/json"}


def test_order_without_receipt_history_has_no_lock(setup_test_database):
    session = setup_test_database
    _, orders, _ = _seed_world(session)

    state = receivable_service.get_order_receipt_lock_state(session, orders[0].uid)

    assert state == {
        "status": "none",
        "has_history": False,
        "unlock_eligible": False,
        "blockers": [],
        "revision": None,
    }


def test_rejected_receipt_can_open_and_close_revision(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _add_receipt_history(session, customer, order, status="rejected")

    locked = receivable_service.get_order_receipt_lock_state(session, order.uid)
    assert locked["status"] == "locked"
    assert locked["unlock_eligible"] is True

    opened = receivable_service.open_order_receipt_revision(
        order.uid, "修正收件地址", ADMIN
    )
    assert opened["status"] == "revision_open"
    assert opened["revision"]["reason"] == "修正收件地址"

    closed = receivable_service.close_order_receipt_revision(
        order.uid, "修订完成", ADMIN
    )
    assert closed["status"] == "locked"
    assert closed["revision"] is None


@pytest.mark.parametrize(
    ("receipt_status", "blocker"),
    [("pending", "pending_receipt"), ("approved", "approved_receipt")],
)
def test_pending_or_approved_receipt_blocks_revision(
    setup_test_database, receipt_status, blocker
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _add_receipt_history(session, customer, order, status=receipt_status)

    state = receivable_service.get_order_receipt_lock_state(session, order.uid)
    assert state["unlock_eligible"] is False
    assert blocker in state["blockers"]
    with pytest.raises(receivable_service.OrderReceiptRevisionConflictError):
        receivable_service.open_order_receipt_revision(order.uid, "尝试修订", ADMIN)


def test_only_admin_can_open_revision(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _add_receipt_history(session, customer, order, status="rejected")

    with pytest.raises(PermissionError, match="只有管理员"):
        receivable_service.open_order_receipt_revision(
            order.uid,
            "无权修订",
            {"user_id": 3, "name": "业务员测试", "role": "salesperson"},
        )


def test_unlock_and_relock_routes_are_available(
    client, setup_test_database, admin_token
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    order = orders[0]
    _add_receipt_history(session, customer, order, status="rejected")

    unlock = client.post(
        f"/api/orders/{order.uid}/receipt-unlock",
        headers=_headers(admin_token),
        json={"reason": "修正地址"},
    )
    assert unlock.status_code == 200
    assert unlock.get_json()["data"]["status"] == "revision_open"

    detail = client.get(f"/api/orders/{order.uid}", headers=_headers(admin_token))
    assert detail.status_code == 200
    assert detail.get_json()["data"]["receipt_locked"] is False
    assert detail.get_json()["data"]["receipt_lock"]["status"] == "revision_open"
    assert "copy_relation" not in detail.get_json()["data"]

    relock = client.post(
        f"/api/orders/{order.uid}/receipt-relock",
        headers=_headers(admin_token),
        json={"remark": "完成"},
    )
    assert relock.status_code == 200
    assert relock.get_json()["data"]["status"] == "locked"
