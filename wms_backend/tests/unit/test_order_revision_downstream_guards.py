"""历史修订记录不再限制出库和奖金分配。"""

from unittest.mock import patch

import pytest
from services.outbound_service import update_cargo_details

from data.DB import (
    BoxCostRecordTable,
    CargoTable,
    OrderReceiptRevisionTable,
    OrderTable,
)
from data.finance.BonusItem import BonusItemTable
from data.packing import box_model
from data.packing.PackingList import PackingListTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import work_finance_service
from services.order_edit_policy import OrderEditConflictError


def _seed_packing_list(
    session, *, open_revision=True, include_unassigned=False, outbound=False
):
    operator = UserTable(
        phone="13890000001",
        name="修订操作员",
        password="hashed-password",
        status="approved",
    )
    order = OrderTable(
        uid="revision-order",
        order_id="REVISION-001",
        transportation="",
        archive=False,
        create_date="2026-09-04 09:00",
    )
    packing_list = PackingListTable(
        uid="revision-packing-list",
        list_number="REVISION-PL-001",
        creator=operator,
        status="completed",
        archive=False,
        create_date="2026-09-04 09:00",
    )
    assigned_box = CargoTable(
        uid="revision-box",
        origin_id="REVISION-PL-001-1",
        tag="REVISION-PL-001_1",
        count=1,
        weight=2.5,
        status=1 if outbound else 0,
        archive=False,
        packing_list_uid=packing_list.uid,
        target_order_uid=order.uid,
        item_name="测试货物",
        real_en_name="测试货物",
        piece_count=1,
        box_number=1,
        waybill_id="WB-OLD" if outbound else "",
        date="2026-09-04 09:02" if outbound else None,
        bonus_assigned=False,
        create_date="2026-09-04 09:01",
    )
    session.add_all([operator, order, packing_list, assigned_box])
    if outbound:
        session.add(
            BoxCostRecordTable(
                box_uid=assigned_box.uid,
                packing_list_uid=packing_list.uid,
                order_uid=order.uid,
                transportation_name="",
                waybill_id="WB-OLD",
                weight=2.5,
                unit_cost=10,
                total_cost=25,
                create_date="2026-09-04 09:02",
            )
        )
    if include_unassigned:
        session.add(
            CargoTable(
                uid="unassigned-box",
                origin_id="REVISION-PL-001-2",
                tag="REVISION-PL-001_2",
                count=1,
                weight=1.5,
                status=0,
                archive=False,
                packing_list_uid=packing_list.uid,
                target_order_uid=None,
                item_name="未归属货物",
                real_en_name="未归属货物",
                piece_count=1,
                box_number=2,
                waybill_id="",
                bonus_assigned=False,
                create_date="2026-09-04 09:02",
            )
        )
    session.flush()
    if open_revision:
        session.add(
            OrderReceiptRevisionTable(
                order_uid=order.uid,
                status="open",
                reason="修正订单信息",
                opened_by_id=operator.id,
                opened_by_name=operator.name,
                opened_at="2026-09-04 09:03",
            )
        )
    session.commit()
    return order, assigned_box, packing_list


def _headers(token):
    return {"x-token": token, "Content-Type": "application/json"}


def test_first_waybill_during_revision_creates_outbound_snapshot(
    setup_test_database,
):
    session = setup_test_database
    _, box, _ = _seed_packing_list(session)
    box_uid = box.uid

    assert update_cargo_details(box_uid, {"waybill_id": "WB-REVISION-001"}, confirm_outbound=True)

    session.expire_all()
    changed = session.query(CargoTable).filter_by(uid=box_uid).one()
    assert changed.status == 1
    assert changed.waybill_id == "WB-REVISION-001"
    assert session.query(BoxCostRecordTable).filter_by(box_uid=box_uid).count() == 1


def test_recording_waybill_without_revision_still_ships_box(setup_test_database):
    session = setup_test_database
    _, box, _ = _seed_packing_list(session, open_revision=False)
    box_uid = box.uid

    assert update_cargo_details(box_uid, {"waybill_id": "WB-NORMAL-001"}, confirm_outbound=True)

    session.expire_all()
    shipped = session.query(CargoTable).filter_by(uid=box_uid).one()
    assert shipped.status == 1
    assert shipped.waybill_id == "WB-NORMAL-001"
    assert shipped.date is not None


def test_legacy_batch_shipping_implementation_is_removed(setup_test_database):
    session = setup_test_database
    _, box, packing_list = _seed_packing_list(session)
    box_uid = box.uid
    packing_list_uid = packing_list.uid

    assert not hasattr(box_model, "_legacy_batch_ship")
    with pytest.raises(ValueError, match="旧批量出库方法已停用"):
        box_model.batch_ship(packing_list_uid, [box_uid])

    session.expire_all()
    assert session.query(CargoTable).filter_by(uid=box_uid).one().status == 0


def test_box_update_maps_edit_conflict_to_http_409(client, admin_token):
    with patch(
        "services.packing_list_service.update_box",
        side_effect=OrderEditConflictError("箱子归属已变化，请刷新后重试"),
    ):
        response = client.put(
            "/api/box/revision-box",
            headers=_headers(admin_token),
            json={"waybill_id": "WB-REVISION-001"},
        )

    assert response.status_code == 409
    assert response.get_json() == {
        "code": 409,
        "msg": "箱子归属已变化，请刷新后重试",
    }


def test_outbound_cargo_waybill_update_is_allowed_during_revision(
    client, setup_test_database, admin_token
):
    session = setup_test_database
    _, box, _ = _seed_packing_list(session, outbound=True)
    box_uid = box.uid

    response = client.put(
        f"/api/cargo/{box_uid}",
        headers=_headers(admin_token),
        json={"waybill_id": "WB-REVISION-CARGO"},
    )

    assert response.status_code == 200
    session.expire_all()
    changed = session.query(CargoTable).filter_by(uid=box_uid).one()
    assert changed.status == 1
    assert changed.waybill_id == "WB-REVISION-CARGO"
    cost = session.query(BoxCostRecordTable).filter_by(box_uid=box_uid).one()
    assert cost.waybill_id == "WB-OLD"
    assert cost.total_cost == 25


def test_legacy_open_revision_allows_bonus_assignment(setup_test_database):
    session = setup_test_database
    _, box, packing_list = _seed_packing_list(session, include_unassigned=True)
    worker = UserTable(
        phone="13890000002",
        name="奖金工人",
        password="hashed-password",
        status="approved",
        roles=[RoleTable(name="worker", label="操作人员")],
    )
    bonus_item = BonusItemTable(
        label="历史记录测试奖金",
        base_amount=10,
        worker_count_rule=1,
        weight_min=0,
        weight_max=100,
        is_active=True,
    )
    session.add_all([worker, bonus_item])
    session.commit()

    result = work_finance_service.assign_bonus_for_packing_list(
        packing_list.uid,
        [
            {"box_uid": uid, "worker_ids": [worker.id], "bonus_item_id": bonus_item.id}
            for uid in ["unassigned-box", box.uid]
        ],
    )
    assert result["assigned_box_count"] == 2

    session.expire_all()
    boxes = {
        row.uid: row
        for row in session.query(CargoTable)
        .filter(CargoTable.uid.in_(["unassigned-box", box.uid]))
        .all()
    }
    assert boxes["unassigned-box"].bonus_assigned is True
    assert boxes[box.uid].bonus_assigned is True
    assert session.query(OrderReceiptRevisionTable).one().status == "open"


def test_unassigned_box_bonus_does_not_lock_an_order(setup_test_database):
    session = setup_test_database
    _, _, packing_list = _seed_packing_list(
        session, open_revision=False, include_unassigned=True
    )
    worker_role = RoleTable(name="worker", label="操作人员")
    worker = UserTable(
        phone="13890000002",
        name="奖金工人",
        password="hashed-password",
        status="approved",
        roles=[worker_role],
    )
    bonus_item = BonusItemTable(
        label="普通奖金",
        base_amount=10,
        worker_count_rule=1,
        weight_min=0,
        weight_max=100,
        is_active=True,
    )
    session.add_all([worker, bonus_item])
    session.commit()

    with patch(
        "services.work_finance_service.lock_order_for_update"
    ) as guard:
        result = work_finance_service.assign_bonus_for_packing_list(
            packing_list.uid,
            [
                {
                    "box_uid": "unassigned-box",
                    "worker_ids": [worker.id],
                    "bonus_item_id": bonus_item.id,
                }
            ],
        )

    assert result["assigned_box_count"] == 1
    guard.assert_not_called()
    session.expire_all()
    assert (
        session.query(CargoTable).filter_by(uid="unassigned-box").one().bonus_assigned
        is True
    )


def test_bonus_controller_maps_edit_conflict_to_http_409(client, admin_token):
    with patch(
        "services.work_finance_service.assign_bonus_for_packing_list",
        side_effect=OrderEditConflictError("箱子状态或归属已变化，请刷新后重试"),
    ):
        response = client.put(
            "/api/finance/bonus-allocation/packing-list/revision-packing-list",
            headers=_headers(admin_token),
            json={"assignments": [{"box_uid": "revision-box"}]},
        )

    assert response.status_code == 409
    assert response.get_json() == {
        "code": 409,
        "msg": "箱子状态或归属已变化，请刷新后重试",
    }
