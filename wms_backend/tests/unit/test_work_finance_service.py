"""工作详情统计。"""

from decimal import Decimal

from data.DB import CargoTable, OrderQuoteVersionTable, OrderTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import work_finance_service


def test_work_details_use_current_order_salesman_and_live_weight(
    setup_test_database,
):
    session = setup_test_database
    salesperson_role = RoleTable(name="salesperson", label="业务员")
    order_salesman = UserTable(
        id=3,
        phone="13800000003",
        name="订单业务员",
        password="unused",
        status="approved",
    )
    quote_owner = UserTable(
        id=8,
        phone="13800000008",
        name="历史报价人",
        password="unused",
        status="approved",
    )
    order_salesman.roles = [salesperson_role]
    quote_owner.roles = [salesperson_role]
    order = OrderTable(
        uid="followup-order",
        order_id="FOLLOWUP-001",
        salesman_id=order_salesman.id,
        transportation="测试渠道",
        archive=False,
        create_date="2026-09-01 09:00:00",
    )
    cargo = CargoTable(
        uid="followup-cargo",
        target_order_uid=order.uid,
        weight=12.345,
        archive=False,
        create_date="2026-09-01 09:00:00",
    )
    quote = OrderQuoteVersionTable(
        order_uid=order.uid,
        version_no=1,
        unit_price=Decimal("10"),
        weight_snapshot=Decimal("1.000"),
        billing_weight_snapshot=Decimal("1.000"),
        receivable_amount=Decimal("10.00"),
        status="adopted",
        is_final=True,
        quoter_id=quote_owner.id,
        quoter_name=quote_owner.name,
        archive=False,
        effective_date="2026-09-01 10:00:00",
    )
    session.add_all([order_salesman, quote_owner, order, cargo, quote])
    session.commit()

    salesman_details = work_finance_service.get_worker_work_details(
        order_salesman.id, "2026-09"
    )
    quote_owner_details = work_finance_service.get_worker_work_details(
        quote_owner.id, "2026-09"
    )

    assert salesman_details["followup_order_count"] == 1
    assert salesman_details["followup_total_weight"] == 12.345
    assert salesman_details["orders"][0]["total_weight"] == 12.345
    assert quote_owner_details["followup_order_count"] == 0

    order.salesman_id = quote_owner.id
    cargo.weight = 20.125
    session.commit()

    reassigned_details = work_finance_service.get_worker_work_details(
        quote_owner.id, "2026-09"
    )
    previous_salesman_details = work_finance_service.get_worker_work_details(
        order_salesman.id, "2026-09"
    )

    assert reassigned_details["followup_order_count"] == 1
    assert reassigned_details["followup_total_weight"] == 20.125
    assert previous_salesman_details["followup_order_count"] == 0
