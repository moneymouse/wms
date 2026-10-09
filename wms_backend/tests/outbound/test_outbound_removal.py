"""Removal requires reversing the current shipment, not deleting its history."""
from unittest.mock import patch

import pytest

from Auth import create_jwt
from data import cargo_model, order_model
from data.DB import BoxCostRecordTable, CargoOutboundRecordTable, CargoTable, OrderTable
from data.order_version import OrderVersionTable
from data.packing import box_model, packing_list_model
from services.order_edit_policy import OrderEditConflictError
from services.outbound_service import undo_outbound, update_cargo_details

ADMIN = {"user_id": 1, "name": "管理员", "role": "admin"}


def shipped(world, uid="cargo"):
    update_cargo_details(uid, {"waybill_id": "WB-ORIGINAL"}, confirm_outbound=True, operator=ADMIN)


@pytest.mark.parametrize("uid", ["cargo", "box"])
@pytest.mark.parametrize("status", [1, 2, 10, "Delivered"])
def test_current_outbound_or_later_cannot_be_unbound(world, headers, uid, status):
    with world["factory"]() as session:
        session.get(CargoTable, uid).status = status
        session.commit()
    response = world["client"].post("/api/cargo/unbind", json={"cargo_id_list": [uid]}, headers=headers)
    assert response.status_code == 409
    assert "先撤销出库" in response.get_json()["msg"]
    with world["factory"]() as session:
        assert session.get(CargoTable, uid).target_order_uid == "order"
        assert session.query(OrderVersionTable).count() == 0


@pytest.mark.parametrize("operation", ["unbind", "delete", "archive"])
def test_mixed_batch_fails_before_mutating_any_member(world, headers, operation):
    shipped(world, "cargo")
    with world["factory"]() as session:
        versions = session.query(OrderVersionTable).count()
    route, method = ("/api/cargo", "delete") if operation == "delete" else (f"/api/cargo/{operation}", "post")
    response = getattr(world["client"], method)(route, json={"cargo_id_list": ["box", "cargo"]}, headers=headers)
    assert response.status_code == 409
    with world["factory"]() as session:
        for uid in ("box", "cargo"):
            row = session.get(CargoTable, uid)
            assert row.target_order_uid == "order" and row.archive is False
        assert session.query(OrderVersionTable).count() == versions


@pytest.mark.parametrize("operation", [
    lambda: cargo_model.unbind_from_order("box"),
    lambda: cargo_model.delete("box"),
    lambda: cargo_model.archive("box"),
    lambda: box_model.delete("box"),
    lambda: box_model.archive("box"),
    lambda: packing_list_model.delete("packing"),
])
def test_model_paths_cannot_bypass_current_shipment(world, operation):
    shipped(world, "box")
    with pytest.raises(OrderEditConflictError, match="先撤销出库"):
        operation()
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert box.target_order_uid == "order" and box.archive is False and box.status == 1
        assert session.query(BoxCostRecordTable).filter_by(archive=False).count() == 1


@pytest.mark.parametrize("batch", [False, True])
def test_hard_order_delete_cannot_indirectly_detach_shipped_cargo(world, batch):
    # Ordinary cargo has an outbound fact but no legacy financial FK snapshot.
    shipped(world, "cargo")
    with pytest.raises(OrderEditConflictError, match="先撤销出库"):
        order_model.delete_many(["order"]) if batch else order_model.delete("order")
    with world["factory"]() as session:
        assert session.get(OrderTable, "order") is not None
        assert session.get(CargoTable, "cargo").target_order_uid == "order"


@pytest.mark.parametrize("uid", ["cargo", "box"])
def test_undo_preserves_facts_then_removal_is_allowed(world, headers, uid):
    shipped(world, uid)
    assert cargo_model.read(uid)["removal_allowed"] is False
    with world["factory"]() as session:
        count = session.query(CargoOutboundRecordTable).count()
        transfer = session.get(CargoTable, uid).transfer_id
    response = world["client"].post(f"/api/cargo/{uid}/undo-outbound", headers=headers)
    assert response.status_code == 200
    current = cargo_model.read(uid)
    assert current["removal_allowed"] is True
    assert current["removal_blocked_reason"] is None
    with world["factory"]() as session:
        row = session.get(CargoTable, uid)
        assert (row.status, row.date, row.waybill_id, row.transfer_id) == (0, None, "", transfer)
        assert session.query(CargoOutboundRecordTable).count() == count
        if uid == "box":
            assert session.query(BoxCostRecordTable).one().archive is True
        version = session.query(OrderVersionTable).order_by(OrderVersionTable.id.desc()).first()
        assert version.action == ("box_shipment_undone" if uid == "box" else "cargo_shipment_undone")
        assert version.operator_name == "管理员"
    result = world["client"].post("/api/cargo/unbind", json={"cargo_id_list": [uid]}, headers=headers)
    assert result.status_code == 200
    with world["factory"]() as session:
        assert session.get(CargoTable, uid).target_order_uid is None
        assert session.query(CargoOutboundRecordTable).count() == count


@pytest.mark.parametrize("role", ["salesperson", "clerk", "finance", "worker"])
def test_reversal_permission_is_enforced_in_service_and_http(world, role):
    shipped(world)
    actor = {"user_id": 1, "name": "业务用户", "role": role}
    with pytest.raises(PermissionError):
        undo_outbound("cargo", operator=actor)
    result = world["client"].post("/api/cargo/cargo/undo-outbound", headers={"x-token": create_jwt(actor)})
    assert result.status_code == 403
    with world["factory"]() as session:
        assert session.get(CargoTable, "cargo").status == 1


def test_reversal_audit_failure_rolls_back_current_state_and_cost(world):
    shipped(world, "box")
    with patch("services.outbound_service.record_mutation", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            undo_outbound("box", operator=ADMIN)
    with world["factory"]() as session:
        row = session.get(CargoTable, "box")
        assert row.status == 1 and row.date and row.waybill_id == "WB-ORIGINAL"
        assert session.query(BoxCostRecordTable).one().archive is False


@pytest.mark.parametrize("batch", [False, True])
def test_locked_removal_refreshes_stale_orm_state(world, monkeypatch, batch):
    stale_session = world["factory"]()
    stale_row = stale_session.get(CargoTable, "cargo")
    stale_session.commit()
    with world["factory"]() as session:
        session.get(CargoTable, "cargo").status = 1
        session.commit()
    assert stale_row.status == 0
    monkeypatch.setattr("data.DB.SessionFactory", lambda: stale_session)
    with pytest.raises(OrderEditConflictError, match="先撤销出库"):
        cargo_model.mutate_many(["cargo"], "unbind") if batch else cargo_model.unbind_from_order("cargo")
    with world["factory"]() as session:
        assert session.get(CargoTable, "cargo").target_order_uid == "order"


def test_current_shipment_date_cannot_be_ignored_by_resetting_status(world):
    with world["factory"]() as session:
        row = session.get(CargoTable, "cargo")
        row.status, row.date = 0, "2026-10-05 10:00"
        session.commit()
    with pytest.raises(OrderEditConflictError, match="先撤销出库"):
        cargo_model.unbind_from_order("cargo")
    undo_outbound("cargo", operator=ADMIN)
    assert cargo_model.unbind_from_order("cargo")
