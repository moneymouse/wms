from unittest.mock import patch

import pytest

from data import cargo_model
from data.DB import CargoTable, OrderTable
from data.packing import box_model
from services.cargo_service import apply_waybill_table
from services.order_edit_policy import (
    OUTBOUND_WEIGHT_IMMUTABLE_MESSAGE,
    OrderEditConflictError,
    cargo_is_outbound_or_later,
)


def _seed_packages(session):
    session.add_all(
        [
            CargoTable(
                uid="manual-outbound",
                origin_id="MANUAL-001",
                transfer_id="ORIGINAL-001",
                waybill_id="WAYBILL-001",
                weight=1.5,
                status=1,
                archive=False,
                create_date="2026-09-21 10:00",
            ),
            CargoTable(
                uid="box-outbound",
                origin_id="BOX-001",
                transfer_id="ORIGINAL-002",
                waybill_id="WAYBILL-002",
                weight=2.5,
                status=1,
                packing_list_uid="packing-list-001",
                archive=False,
                create_date="2026-09-21 10:00",
            ),
            CargoTable(
                uid="manual-pending",
                origin_id="MANUAL-002",
                transfer_id="ORIGINAL-003",
                waybill_id="",
                weight=3.5,
                status=0,
                archive=False,
                create_date="2026-09-21 10:00",
            ),
            CargoTable(
                uid="manual-pending-with-waybill",
                origin_id="MANUAL-004",
                transfer_id="ORIGINAL-006",
                waybill_id="LEGACY-WAYBILL",
                weight=6.5,
                status=0,
                archive=False,
                create_date="2026-09-21 10:00",
            ),
            CargoTable(
                uid="manual-outbound-no-waybill",
                origin_id="MANUAL-003",
                transfer_id="ORIGINAL-005",
                waybill_id="",
                weight=5.5,
                status=1,
                archive=False,
                create_date="2026-09-21 10:00",
            ),
            CargoTable(
                uid="box-pending",
                origin_id="BOX-002",
                transfer_id="ORIGINAL-004",
                waybill_id="",
                weight=4.5,
                status=0,
                packing_list_uid="packing-list-002",
                archive=False,
                create_date="2026-09-21 10:00",
            ),
        ]
    )
    session.commit()


@pytest.mark.unit
@pytest.mark.cargo
def test_models_reject_weight_changes_for_outbound_packages(setup_test_database):
    session = setup_test_database
    _seed_packages(session)

    with pytest.raises(OrderEditConflictError, match="货物已出库"):
        cargo_model.update("manual-outbound", {"weight": 9.5})
    with pytest.raises(OrderEditConflictError, match="货物已出库"):
        box_model.update("box-outbound", {"weight": 9.5})
    with pytest.raises(OrderEditConflictError, match="货物已出库"):
        cargo_model.update("manual-outbound-no-waybill", {"weight": 9.5})

    session.expire_all()
    assert session.get(CargoTable, "manual-outbound").weight == 1.5
    assert session.get(CargoTable, "box-outbound").weight == 2.5


@pytest.mark.unit
@pytest.mark.cargo
def test_pending_packages_remain_weighable(setup_test_database):
    session = setup_test_database
    _seed_packages(session)

    cargo_model.update("manual-pending", {"weight": 5.5})
    cargo_model.update("manual-pending-with-waybill", {"weight": 7.5})
    assert box_model.update("box-pending", {"weight": 6.5}) is True

    session.expire_all()
    assert session.get(CargoTable, "manual-pending").weight == 5.5
    assert session.get(CargoTable, "manual-pending-with-waybill").weight == 7.5
    assert session.get(CargoTable, "box-pending").weight == 6.5


@pytest.mark.unit
@pytest.mark.cargo
def test_idempotent_weight_payloads_are_allowed_for_outbound_packages(
    setup_test_database,
):
    session = setup_test_database
    _seed_packages(session)

    cargo_model.update("manual-outbound", {"weight": "1.5"})
    assert box_model.update("box-outbound", {"weight": "2.5"}) is True

    session.expire_all()
    assert session.get(CargoTable, "manual-outbound").weight == 1.5
    assert session.get(CargoTable, "box-outbound").weight == 2.5


@pytest.mark.unit
@pytest.mark.cargo
def test_waybill_changes_do_not_bypass_an_outbound_status(setup_test_database):
    session = setup_test_database
    _seed_packages(session)

    with pytest.raises(OrderEditConflictError):
        cargo_model.update(
            "manual-outbound",
            {"waybill_id": "WAYBILL-NEW", "weight": 8.5},
        )
    with pytest.raises(OrderEditConflictError):
        box_model.update(
            "box-outbound",
            {"waybill_id": "WAYBILL-NEW", "weight": 8.5},
        )

    session.expire_all()
    manual = session.get(CargoTable, "manual-outbound")
    box = session.get(CargoTable, "box-outbound")
    assert (manual.waybill_id, manual.weight, manual.status) == (
        "WAYBILL-001",
        1.5,
        1,
    )
    assert (box.waybill_id, box.weight, box.status) == ("WAYBILL-002", 2.5, 1)


@pytest.mark.unit
@pytest.mark.cargo
def test_pure_waybill_assignment_accepts_weight_without_marking_outbound(
    setup_test_database,
):
    session = setup_test_database
    _seed_packages(session)

    cargo_model.update(
        "manual-pending",
        {"waybill_id": "WAYBILL-NEW", "weight": 5.5},
    )

    session.expire_all()
    cargo = session.get(CargoTable, "manual-pending")
    assert (cargo.waybill_id, cargo.weight, cargo.status) == (
        "WAYBILL-NEW",
        5.5,
        0,
    )
    assert cargo.date is None
    cargo_model.update("manual-pending", {"weight": 6.5})
    session.expire_all()
    assert session.get(CargoTable, "manual-pending").weight == 6.5


@pytest.mark.unit
@pytest.mark.cargo
def test_creating_cargo_with_a_waybill_keeps_it_pending(setup_test_database):
    session = setup_test_database

    uid = cargo_model.create(
        {
            "origin_id": "MANUAL-CREATED-OUTBOUND",
            "transfer_id": "ORIGINAL-CREATED",
            "waybill_id": "WAYBILL-CREATED",
            "weight": 4.5,
        }
    )

    session.expire_all()
    cargo = session.get(CargoTable, uid)
    assert cargo.status == 0
    assert cargo.date is None
    cargo_model.update(uid, {"weight": 5.5})
    session.expire_all()
    assert session.get(CargoTable, uid).weight == 5.5


@pytest.mark.unit
@pytest.mark.cargo
def test_undo_ship_returns_a_box_to_a_weighable_status(setup_test_database):
    session = setup_test_database
    _seed_packages(session)

    assert box_model.undo_ship("box-outbound") is True
    assert box_model.update("box-outbound", {"weight": 7.5}) is True

    session.expire_all()
    box = session.get(CargoTable, "box-outbound")
    assert (box.status, box.waybill_id, box.weight) == (0, "", 7.5)


@pytest.mark.unit
@pytest.mark.cargo
def test_bulk_waybill_assignment_marks_manual_cargo_outbound(setup_test_database):
    session = setup_test_database
    _seed_packages(session)
    session.add(OrderTable(uid="bulk-order", order_id="BULK", archive=False))
    session.get(CargoTable, "manual-pending").target_order_uid = "bulk-order"
    session.commit()

    with patch("services.cargo_service.registerTrack"):
        register_list, error = apply_waybill_table(
            cargo_model,
            {"ORIGINAL-003": "WAYBILL-BULK"},
        )

    assert error is None
    assert register_list == [("manual-pending", "WAYBILL-BULK")]
    session.expire_all()
    cargo = session.get(CargoTable, "manual-pending")
    assert (cargo.waybill_id, cargo.status) == ("WAYBILL-BULK", 1)

    with pytest.raises(OrderEditConflictError):
        cargo_model.update("manual-pending", {"weight": 7.5})


@pytest.mark.parametrize(
    "status",
    [
        1,
        2,
        "1",
        "outbound",
        "InfoReceived",
        "InTransit_Other",
        "Delivered_Other",
        "in_transit",
        "FutureCarrierState",
    ],
)
def test_outbound_and_tracking_statuses_are_locked(status):
    assert cargo_is_outbound_or_later(status) is True


@pytest.mark.parametrize(
    "status",
    [
        None,
        0,
        "",
        "0",
        "pending",
        "pending_assign",
        "pending_outbound",
        "in_stock",
        "instock",
    ],
)
def test_pending_statuses_are_not_locked(status):
    assert cargo_is_outbound_or_later(status) is False


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.cargo
def test_all_weight_update_endpoints_return_conflict_for_outbound_packages(
    client,
    admin_token,
    setup_test_database,
):
    session = setup_test_database
    _seed_packages(session)
    headers = {"x-token": admin_token}

    responses = [
        client.put(
            "/api/cargo/manual-outbound",
            json={"weight": 7.5},
            headers=headers,
        ),
        client.post(
            "/api/cargo/manual-outbound/input",
            json={"weight": 7.5, "count": 1},
            headers=headers,
        ),
        client.put(
            "/api/cargo/box-outbound",
            json={"weight": 7.5},
            headers=headers,
        ),
        client.put(
            "/api/box/box-outbound",
            json={"weight": 7.5},
            headers=headers,
        ),
        client.put(
            "/api/box/box-outbound/weigh",
            json={"weight": 7.5},
            headers=headers,
        ),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.get_json() == {
            "code": 409,
            "msg": OUTBOUND_WEIGHT_IMMUTABLE_MESSAGE,
        }

    session.expire_all()
    assert session.get(CargoTable, "manual-outbound").weight == 1.5
    assert session.get(CargoTable, "box-outbound").weight == 2.5


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.cargo
def test_generic_cargo_api_cannot_reset_status_to_bypass_weight_lock(
    client,
    admin_token,
    setup_test_database,
):
    _seed_packages(setup_test_database)

    response = client.put(
        "/api/cargo/manual-outbound",
        json={"status": 0},
        headers={"x-token": admin_token},
    )

    assert response.status_code == 400
    assert response.get_json() == {"code": 400, "msg": "不允许修改字段: status"}
