"""Shipment history fixes box numbers; reentry restores original number editing."""

import pytest

from data import cargo_model
from data.DB import BoxCostRecordTable, CargoOutboundRecordTable, CargoTable
from data.order_version import OrderVersionTable
from data.packing import box_model, packing_list_model
from services.order_edit_policy import (
    BOX_IDENTITY_IMMUTABLE_MESSAGE,
    ORIGINAL_NUMBER_IMMUTABLE_MESSAGE,
    OrderEditConflictError,
)
from services.outbound_service import confirm_outbound, update_cargo_details


ADMIN = {"user_id": 1, "name": "管理员", "role": "admin"}


@pytest.fixture
def identity_world(world, monkeypatch):
    monkeypatch.setattr("controllers.packing_controller.SessionFactory", world["factory"])
    monkeypatch.setattr("services.cargo_service.getTrackInfo", lambda *args: [])
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        box.box_number = 1
        box.tag = "MARK_1"
        box.remark = "原备注"
        session.commit()
    return world


def _state(world, uid="box"):
    with world["factory"]() as session:
        cargo = session.get(CargoTable, uid)
        row = {column.name: getattr(cargo, column.name) for column in CargoTable.__table__.columns}
        versions = [
            (version.id, version.order_uid, version.version_no, version.action)
            for version in session.query(OrderVersionTable).order_by(OrderVersionTable.id)
        ]
        return row, versions


def _legacy_evidence(world, kind):
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        if kind == "date":
            box.date = "2026-09-01 10:00:00"
        elif kind == "event":
            session.add(CargoOutboundRecordTable(
                cargo_uid="box", order_uid="order", occurred_at=None,
                recorded_at="2026-09-01 10:00:00", source="legacy", operator_id=1,
            ))
        else:
            session.add(BoxCostRecordTable(
                box_uid="box", packing_list_uid="packing", order_uid="order",
                transportation_name="渠道", waybill_id="WB-OLD", weight=2,
                unit_cost=3, total_cost=6, create_date="2026-09-01 10:00:00",
                archive=kind == "archived_cost",
            ))
        session.commit()


@pytest.mark.parametrize("status", [1, 2, 3])
@pytest.mark.parametrize("model", [box_model, cargo_model], ids=["box_model", "cargo_model"])
@pytest.mark.parametrize("change", [{"box_number": 2}, {"transfer_id": "ORIG-NEW"}])
def test_models_reject_identity_change_atomically_after_outbound(identity_world, status, model, change):
    with identity_world["factory"]() as session:
        session.get(CargoTable, "box").status = status
        session.commit()
    before = _state(identity_world)

    message = (
        BOX_IDENTITY_IMMUTABLE_MESSAGE
        if "box_number" in change else ORIGINAL_NUMBER_IMMUTABLE_MESSAGE
    )
    with pytest.raises(OrderEditConflictError, match=message):
        model.update("box", {**change, "remark": "不得写入的备注"})

    assert _state(identity_world) == before


@pytest.mark.parametrize("route", ["/api/box/box", "/api/cargo/box"])
@pytest.mark.parametrize("change", [{"box_number": 2}, {"transfer_id": ""}])
def test_http_rejects_identity_change_without_mutation(identity_world, headers, route, change):
    confirm_outbound(["box"], operator=ADMIN)
    before = _state(identity_world)

    response = identity_world["client"].put(
        route, headers=headers,
        json={**change, "remark": "不得写入的备注", "confirm_outbound": False},
    )

    assert response.status_code == 409, response.get_json()
    expected_message = (
        BOX_IDENTITY_IMMUTABLE_MESSAGE
        if "box_number" in change else ORIGINAL_NUMBER_IMMUTABLE_MESSAGE
    )
    assert response.get_json()["msg"] == expected_message
    assert _state(identity_world) == before


@pytest.mark.parametrize("kind", ["date", "event", "cost", "archived_cost"])
@pytest.mark.parametrize("model", [box_model, cargo_model], ids=["box_model", "cargo_model"])
def test_legacy_evidence_keeps_identity_immutable_while_pending(identity_world, kind, model):
    _legacy_evidence(identity_world, kind)
    before = _state(identity_world)
    assert before[0]["status"] == 0

    with pytest.raises(OrderEditConflictError, match=BOX_IDENTITY_IMMUTABLE_MESSAGE):
        model.update("box", {"box_number": 2, "transfer_id": "ORIG-NEW", "remark": "新备注"})

    assert _state(identity_world) == before


@pytest.mark.parametrize("model", [box_model, cargo_model], ids=["box_model", "cargo_model"])
def test_reentry_keeps_box_number_fixed_and_allows_original_number_update(identity_world, model):
    confirm_outbound(["box"], operator=ADMIN)
    assert box_model.undo_ship("box", operator=ADMIN)
    before = _state(identity_world)
    assert (before[0]["status"], before[0]["date"]) == (0, None)
    with identity_world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 1
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1

    with pytest.raises(OrderEditConflictError, match=BOX_IDENTITY_IMMUTABLE_MESSAGE):
        model.update("box", {"box_number": 3, "transfer_id": "ORIG-NEW"})
    assert _state(identity_world) == before

    model.update("box", {"transfer_id": "ORIG-NEW", "waybill_id": "WB-NEXT"})
    after, after_versions = _state(identity_world)
    assert (after["box_number"], after["transfer_id"], after["waybill_id"], after["status"]) == (
        1, "ORIG-NEW", "WB-NEXT", 0,
    )
    assert after_versions[-1][3] == "box_updated"
    with identity_world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 1
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1

    # A fresh shipment protects the newly saved original number again.
    confirm_outbound(["box"], operator=ADMIN)
    shipped = _state(identity_world)
    with pytest.raises(OrderEditConflictError, match=ORIGINAL_NUMBER_IMMUTABLE_MESSAGE):
        model.update("box", {"transfer_id": "ORIG-AFTER-RESHIP"})
    assert _state(identity_world) == shipped


@pytest.mark.parametrize("route", ["/api/box/box", "/api/cargo/box"])
def test_http_reentry_keeps_box_number_fixed(identity_world, headers, route):
    confirm_outbound(["box"], operator=ADMIN)
    assert box_model.undo_ship("box", operator=ADMIN)
    before = _state(identity_world)
    response = identity_world["client"].put(
        route, headers=headers,
        json={"box_number": 2, "transfer_id": "ORIG-NEW", "remark": "新备注", "confirm_outbound": False},
    )
    assert response.status_code == 409, response.get_json()
    assert _state(identity_world) == before


@pytest.mark.parametrize("route", ["/api/box/box", "/api/cargo/box"])
def test_http_reentry_allows_original_number_change(identity_world, headers, route):
    confirm_outbound(["box"], operator=ADMIN)
    assert box_model.undo_ship("box", operator=ADMIN)

    response = identity_world["client"].put(
        route, headers=headers,
        json={"transfer_id": "ORIG-HTTP-NEW", "remark": "新备注", "confirm_outbound": False},
    )

    assert response.status_code == 200, response.get_json()
    row, versions = _state(identity_world)
    assert (row["box_number"], row["transfer_id"], row["remark"], row["status"], row["date"]) == (
        1, "ORIG-HTTP-NEW", "新备注", 0, None,
    )
    assert versions[-1][3] == "box_updated"


@pytest.mark.parametrize("model", [box_model, cargo_model], ids=["box_model", "cargo_model"])
@pytest.mark.parametrize("box_number", [1, "1"])
def test_same_identity_values_remain_valid_after_outbound(identity_world, model, box_number):
    confirm_outbound(["box"], operator=ADMIN)
    before = _state(identity_world)
    model.update("box", {"box_number": box_number, "transfer_id": " ORIG-BOX "})
    row, _ = _state(identity_world)
    assert row["box_number"] == 1
    assert row["transfer_id"] == "ORIG-BOX"
    assert _state(identity_world) == before


@pytest.mark.parametrize("route", ["/api/box/box", "/api/cargo/box"])
def test_waybill_can_still_change_after_outbound(identity_world, headers, route):
    confirm_outbound(["box"], operator=ADMIN)
    response = identity_world["client"].put(
        route, headers=headers,
        json={"waybill_id": "WB-CORRECTED", "confirm_outbound": False},
    )
    assert response.status_code == 200, response.get_json()
    row, _ = _state(identity_world)
    assert (row["box_number"], row["transfer_id"], row["waybill_id"], row["status"]) == (
        1, "ORIG-BOX", "WB-CORRECTED", 1,
    )


@pytest.mark.parametrize("model", [box_model, cargo_model], ids=["box_model", "cargo_model"])
def test_unshipped_box_keeps_identity_editable(identity_world, model):
    model.update("box", {"box_number": 2, "transfer_id": "ORIG-NEW", "remark": "新备注"})
    row, _ = _state(identity_world)
    assert (row["box_number"], row["transfer_id"], row["remark"], row["status"]) == (
        2, "ORIG-NEW", "新备注", 0,
    )


def test_outbound_ordinary_cargo_keeps_original_number_editable(identity_world, headers):
    confirm_outbound(["cargo"], operator=ADMIN)
    cargo_model.update("cargo", {"transfer_id": "CARGO-CHANGED"})
    response = identity_world["client"].put(
        "/api/cargo/cargo", headers=headers,
        json={"transfer_id": "CARGO-HTTP", "confirm_outbound": False},
    )
    assert response.status_code == 200, response.get_json()
    assert _state(identity_world, "cargo")[0]["transfer_id"] == "CARGO-HTTP"


@pytest.mark.parametrize("route", ["/api/box/box", "/api/cargo/box"])
def test_first_outbound_accepts_final_identity_in_same_request(identity_world, headers, route):
    response = identity_world["client"].put(
        route, headers=headers,
        json={"box_number": 2, "transfer_id": "ORIG-FINAL", "waybill_id": "WB-FIRST"},
    )
    assert response.status_code == 200, response.get_json()
    row, _ = _state(identity_world)
    assert (row["box_number"], row["transfer_id"], row["waybill_id"], row["status"]) == (
        2, "ORIG-FINAL", "WB-FIRST", 1,
    )
    with identity_world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 1
        assert session.query(BoxCostRecordTable).one().waybill_id == "WB-FIRST"


def test_serialized_identity_permission_survives_reentry(identity_world, headers):
    assert box_model.read("box")["identity_editable"] is True
    assert box_model.read("box")["original_number_editable"] is True
    confirm_outbound(["box"], operator=ADMIN)
    assert box_model.read("box")["original_number_editable"] is False
    assert cargo_model.read("box")["original_number_editable"] is False
    assert box_model.undo_ship("box", operator=ADMIN)

    assert box_model.read("box")["identity_editable"] is False
    assert box_model.read("box")["original_number_editable"] is True
    assert cargo_model.read("box")["identity_editable"] is False
    assert cargo_model.read("box")["original_number_editable"] is True
    assert packing_list_model.read("packing")["boxes"][0]["identity_editable"] is False
    assert packing_list_model.read("packing")["boxes"][0]["original_number_editable"] is True
    for route in ("/api/box/box", "/api/packing-list/packing"):
        response = identity_world["client"].get(route, headers=headers)
        assert response.status_code == 200, response.get_json()
        data = response.get_json()["data"]
        box = data["boxes"][0] if "boxes" in data else data
        assert box["identity_editable"] is False
        assert box["original_number_editable"] is True
    response = identity_world["client"].get("/api/orders/order/cargo", headers=headers)
    assert response.status_code == 200, response.get_json()
    box = next(row for row in response.get_json()["data"] if row["uid"] == "box")
    assert box["identity_editable"] is False
    assert box["original_number_editable"] is True
