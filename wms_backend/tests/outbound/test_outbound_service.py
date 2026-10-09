from io import BytesIO

import pytest

from data import cargo_model
from data.DB import (
    BoxCostRecordTable, CargoOutboundRecordTable, CargoTable, OrderTable,
    OrderReceiptRevisionTable, PaymentReceiptTable, PaymentReceiptItemTable,
    TransportationModeTable,
)
from data.order_version import OrderVersionTable
from data.packing import box_model
from services.cargo_service import apply_waybill_table
from services.order_edit_policy import OrderEditConflictError
from services.outbound_service import confirm_outbound, update_cargo_details

ADMIN = {"user_id": 1, "name": "管理员", "role": "admin"}


def state(world, uid="box"):
    with world["factory"]() as session:
        row = session.get(CargoTable, uid)
        return (row.status, row.date, row.waybill_id, row.weight,
                session.query(BoxCostRecordTable).count(),
                session.query(CargoOutboundRecordTable).count(),
                session.query(OrderVersionTable).count())


@pytest.mark.parametrize("uid,model", [("cargo", cargo_model), ("box", box_model)])
def test_models_update_numbers_without_shipping(world, uid, model):
    model.update(uid, {"waybill_id": "WB"})
    status, date, waybill, _, costs, records, _ = state(world, uid)
    assert (status, date, waybill, costs, records) == (0, None, "WB", 0, 0)
    model.update(uid, {"weight": 6})
    assert state(world, uid)[3] == 6


def test_create_with_number_is_still_pending(world):
    uid = cargo_model.create({"waybill_id": "WB", "weight": 2, "target_order_uid": "order"})
    assert state(world, uid)[:3] == (0, None, "WB")
    with pytest.raises(ValueError, match="确认出库"):
        cargo_model.create({"status": 1, "waybill_id": "WB", "weight": 2})


@pytest.mark.parametrize("uid", ["box", "cargo"])
def test_no_waybill_outbound_is_idempotent_and_tracks_unknown_time(world, uid):
    assert confirm_outbound([uid], operator=ADMIN)["confirmed"] == [uid]
    original = state(world, uid)
    assert original[0] == 1 and original[1] and original[2] == ""
    assert original[4] == (1 if uid == "box" else 0)
    assert confirm_outbound([uid], operator=ADMIN)["unchanged"] == [uid]
    assert state(world, uid) == original
    with world["factory"]() as session:
        event = session.query(CargoOutboundRecordTable).one()
        assert event.occurred_at is None
        assert event.recorded_at == original[1] and event.operator_id == 1


def test_first_number_after_no_number_outbound_preserves_snapshot(world):
    confirm_outbound(["box"], occurred_at="2026-09-30T15:00:00", operator=ADMIN)
    before = state(world)
    with world["factory"]() as session:
        session.get(TransportationModeTable, 1).cost = 99
        session.commit()
    update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    after = state(world)
    assert after[:3] == (1, before[1], "WB")
    assert after[4:6] == before[4:6]
    with world["factory"]() as session:
        cost = session.query(BoxCostRecordTable).one()
        event = session.query(CargoOutboundRecordTable).one()
        assert (cost.unit_cost, cost.total_cost, cost.waybill_id) == (3, 6, "")
        assert event.occurred_at == "2026-09-30T15:00:00"


def test_same_number_supplement_and_then_retry_noop(world):
    cargo_model.update("box", {"waybill_id": "WB"})
    update_cargo_details("box", {"remark": "备注"}, confirm_outbound=True, operator=ADMIN)
    assert state(world)[0] == 0
    result = update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert result["outbound_confirmed"] and not result["waybill_changed"]
    before = state(world)
    result = update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert not result["outbound_confirmed"]
    assert state(world) == before


def test_number_correction_needs_no_unlock_and_preserves_cost(world):
    update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    before = state(world)
    update_cargo_details("box", {"waybill_id": "CORRECT"}, confirm_outbound=True, operator=ADMIN)
    assert state(world)[:3] == (1, before[1], "CORRECT")
    with world["factory"]() as session:
        assert session.query(BoxCostRecordTable).one().waybill_id == "WB"
        assert session.query(CargoOutboundRecordTable).count() == 1


def test_legacy_open_revision_does_not_affect_outbound(world):
    with world["factory"]() as session:
        session.add(OrderReceiptRevisionTable(order_uid="order", status="open", reason="修正", opened_by_id=1, opened_by_name="管理员", opened_at="2026-10-02 10:00"))
        session.commit()
    update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert state(world)[4:6] == (1, 1)


def test_receipt_history_allows_weighing_and_first_outbound(world):
    with world["factory"]() as session:
        receipt = PaymentReceiptTable(receipt_no="RCPT", customer_id=1, customer_name="客户",
                                      status="approved", receipt_date="2026-10-02", payment_method="cash",
                                      creator_name="管理员", create_date="2026-10-02 10:00", update_date="2026-10-02 10:00")
        session.add(receipt)
        session.flush()
        session.add(PaymentReceiptItemTable(receipt_id=receipt.id, order_uid="order", order_id="ORD",
                                           receivable_snapshot=10, amount=10, remaining_after=0))
        session.commit()
    update_cargo_details("box", {"weight": 8, "waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert state(world)[0] == 1
    assert state(world)[2:4] == ("WB", 8)
    assert state(world)[4:6] == (1, 1)
    with world["factory"]() as session:
        assert float(session.query(PaymentReceiptItemTable).one().amount) == 10
        assert session.query(BoxCostRecordTable).one().weight == 8


@pytest.mark.parametrize("bad", ["weight", "order_archive", "cargo_archive", "packing_archive"])
def test_invalid_member_rolls_back_all_import_items_of_same_order(world, bad):
    from data.packing.PackingList import PackingListTable
    with world["factory"]() as session:
        if bad == "weight": session.get(CargoTable, "box").weight = 0
        elif bad == "order_archive": session.get(OrderTable, "order").archive = True
        elif bad == "cargo_archive": session.get(CargoTable, "box").archive = True
        elif bad == "packing_archive": session.get(PackingListTable, "packing").archive = True
        session.commit()
    result, error = apply_waybill_table(
        cargo_model, {"ORIG-CARGO": "C", "ORIG-BOX": "B"}, operator=ADMIN,
        return_details=True,
    )
    assert error is None and not result.successful and not result.registered
    assert {item["uid"] for item in result.failed} == {"box", "cargo"}
    assert {item["order_uid"] for item in result.failed} == {"order"}
    assert all(item["code"] == 400 for item in result.failed)
    assert state(world, "cargo")[:3] == (0, None, "")
    assert state(world)[4:] == (0, 0, 0)


def test_unassigned_import_failure_does_not_roll_back_other_order(world):
    with world["factory"]() as session:
        session.get(CargoTable, "box").target_order_uid = None
        session.commit()
    result, error = apply_waybill_table(
        cargo_model, {"ORIG-CARGO": "C", "ORIG-BOX": "B"}, operator=ADMIN,
        return_details=True,
    )
    assert error is None and result.registered == [("cargo", "C")]
    assert [item["uid"] for item in result.successful] == ["cargo"]
    assert [item["uid"] for item in result.failed] == ["box"]
    assert result.failed[0]["order_uid"] is None
    assert "必须先归属订单" in result.failed[0]["reason"]
    assert state(world, "cargo")[:3] == (1, state(world, "cargo")[1], "C")
    assert state(world, "box")[:3] == (0, None, "")
    assert state(world)[4:6] == (0, 1)


def test_version_failure_rolls_back_number_outbound_cost_and_fact(world, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError("version failed")
    monkeypatch.setattr("services.outbound_service.record_mutation", fail)
    with pytest.raises(RuntimeError):
        update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert state(world) == (0, None, "", 2, 0, 0, 0)


def test_tracking_error_occurs_after_successful_commit(world, monkeypatch):
    def fail(records):
        assert state(world)[0] == 1
        raise RuntimeError("track failed")
    monkeypatch.setattr("services.cargo_service.registerTrack", fail)
    registered, error = apply_waybill_table(cargo_model, {"ORIG-BOX": "WB"}, operator=ADMIN)
    assert registered == [("box", "WB")] and str(error) == "track failed"
    assert state(world)[4:6] == (1, 1)


def test_action_permission_is_enforced_in_service(world):
    with pytest.raises(PermissionError):
        update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator={"role": "worker"})
    assert state(world) == (0, None, "", 2, 0, 0, 0)


def test_outbound_action_retry_still_requires_permission(world):
    confirm_outbound(["box"], operator=ADMIN)
    before = state(world)
    with pytest.raises(PermissionError):
        confirm_outbound(["box"], operator={"role": "finance"})
    assert state(world) == before


def test_legacy_outbound_correction_does_not_repeat_first_outbound_guards(world):
    with world["factory"]() as session:
        cargo = session.get(CargoTable, "cargo")
        cargo.status, cargo.weight, cargo.target_order_uid, cargo.date = 1, 0, None, "2020-01-01 10:00"
        session.commit()
    result = update_cargo_details("cargo", {"waybill_id": "CORRECTION"}, confirm_outbound=True, operator=ADMIN)
    assert not result["outbound_confirmed"]
    assert state(world, "cargo")[:6] == (1, "2020-01-01 10:00", "CORRECTION", 0, 0, 0)


def test_existing_pending_box_cost_cannot_be_overwritten(world):
    with world["factory"]() as session:
        session.add(BoxCostRecordTable(box_uid="box", packing_list_uid="packing", order_uid="order",
                                      unit_cost=99, total_cost=198, weight=2, waybill_id="HISTORY"))
        session.commit()
    with pytest.raises(OrderEditConflictError, match="不能覆盖"):
        update_cargo_details("box", {"waybill_id": "WB"}, confirm_outbound=True, operator=ADMIN)
    assert state(world)[:6] == (0, None, "", 2, 1, 0)
    with world["factory"]() as session:
        assert session.query(BoxCostRecordTable).one().unit_cost == 99


def test_undo_then_new_outbound_appends_a_new_fact(world):
    confirm_outbound(["box"], operator=ADMIN)
    assert box_model.undo_ship("box")
    confirm_outbound(["box"], operator=ADMIN)
    assert state(world)[4:6] == (2, 2)
    with world["factory"]() as session:
        assert session.query(BoxCostRecordTable).filter_by(archive=False).count() == 1
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1


@pytest.mark.parametrize("path", ["/api/cargo/box", "/api/cargo/cargo", "/api/box/box"])
@pytest.mark.parametrize("supplement", [True, False])
def test_http_details_default_compatibility_and_pure_option(world, headers, path, supplement):
    payload = {"waybill_id": "WB"}
    if not supplement: payload["confirm_outbound"] = False
    response = world["client"].put(path, headers=headers, json=payload)
    assert response.status_code == 200, response.get_json()
    uid = path.rsplit("/", 1)[1]
    assert state(world, uid)[0] == int(supplement)
    assert state(world, uid)[2] == "WB"


@pytest.mark.parametrize("supplement", [True, False])
def test_http_upload_default_compatibility_and_pure_option(world, headers, supplement):
    data = {"filename": "waybills.txt", "file": (BytesIO(b"ignored"), "waybills.txt")}
    if not supplement: data["confirm_outbound"] = "false"
    from unittest.mock import patch
    with patch("controllers.cargo_controller.parse_waybill_file", return_value={"ORIG-BOX": "WB", "ORIG-CARGO": "C"}):
        response = world["client"].post("/api/order/upload/transfer_table", headers={"x-token": headers["x-token"]}, data=data)
    assert response.status_code == 200, response.get_json()
    assert state(world)[0] == int(supplement)
    assert state(world, "cargo")[0] == int(supplement)


def test_http_explicit_outbound_with_optional_occurrence(world, headers):
    response = world["client"].put("/api/cargo/box/outbound", headers=headers, json={"occurred_at": "2026-10-01T09:00:00"})
    assert response.status_code == 200, response.get_json()
    assert state(world)[:3] == (1, state(world)[1], "")
    response = world["client"].put("/api/cargo/box/outbound", headers=headers, json={})
    assert response.get_json()["data"]["unchanged"] == ["box"]


def test_http_worker_cannot_trigger_outbound(world):
    from Auth import create_jwt
    headers = {"x-token": create_jwt({"user_id": 1, "role": "worker"})}
    assert world["client"].put("/api/cargo/cargo/outbound", headers=headers, json={}).status_code == 403
    assert world["client"].put("/api/cargo/cargo", headers=headers, json={"waybill_id": "WB"}).status_code == 403
    assert state(world, "cargo")[0] == 0


@pytest.mark.parametrize("body", ["[]", "null", "{", "false", '{"occurred_at":"2026-10-01"}'])
def test_explicit_outbound_rejects_invalid_json_without_mutation(world, headers, body):
    response = world["client"].put("/api/cargo/box/outbound", headers=headers, data=body)
    assert response.status_code == 400
    assert state(world)[0] == 0


def test_two_boxes_of_same_order_import_in_one_transaction(world):
    with world["factory"]() as session:
        session.add(CargoTable(uid="second-box", packing_list_uid="packing", target_order_uid="order",
                               transfer_id="ORIG-SECOND", waybill_id="", status=0, weight=3, archive=False))
        session.commit()
    registered, error = apply_waybill_table(cargo_model, {"ORIG-BOX": "WB1", "ORIG-SECOND": "WB2"}, operator=ADMIN)
    assert error is None and len(registered) == 2
    assert state(world)[4:6] == (2, 2)
    before = state(world)
    assert apply_waybill_table(cargo_model, {"ORIG-BOX": "WB1", "ORIG-SECOND": "WB2"}, operator=ADMIN) == ([], None)
    assert state(world) == before


def test_later_invalid_box_rolls_back_earlier_cost_fact_and_number(world):
    with world["factory"]() as session:
        session.add(CargoTable(uid="z-invalid-box", packing_list_uid="packing", target_order_uid="order",
                               transfer_id="ORIG-INVALID", waybill_id="", status=0, weight=0, archive=False))
        session.commit()
    result, error = apply_waybill_table(
        cargo_model, {"ORIG-BOX": "WB1", "ORIG-INVALID": "WB2"}, operator=ADMIN,
        return_details=True,
    )
    assert error is None and not result.successful and not result.registered
    assert {item["uid"] for item in result.failed} == {"box", "z-invalid-box"}
    assert all(item["code"] == 400 and "重量" in item["reason"] for item in result.failed)
    assert state(world) == (0, None, "", 2, 0, 0, 0)


def test_unknown_packing_customer_does_not_require_customer_migration(world):
    from data.packing.PackingList import PackingListTable
    with world["factory"]() as session:
        session.get(PackingListTable, "packing").customer_id = None
        session.commit()
    assert confirm_outbound(["box"], operator=ADMIN)["confirmed"] == ["box"]


def test_concurrent_confirmations_freeze_cost_and_fact_once(world, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from data.database import Base
    from data.packing.PackingList import PackingListTable
    from services import outbound_service

    engine = create_engine("sqlite:///" + str(tmp_path / "concurrency.sqlite"), connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with factory() as session:
        session.add(OrderTable(uid="concurrent-order", order_id="CONCURRENT", archive=False))
        session.add(PackingListTable(uid="concurrent-packing", list_number="CONCURRENT", creator_id=1, archive=False))
        session.add(CargoTable(uid="concurrent-box", target_order_uid="concurrent-order", packing_list_uid="concurrent-packing",
                               status=0, weight=2, archive=False))
        session.commit()
    monkeypatch.setattr("data.DB.SessionFactory", factory)
    barrier, context = Barrier(2), local()
    guard = outbound_service._guard_outbound
    def synchronized_guard(session, cargo):
        result = guard(session, cargo)
        if not getattr(context, "arrived", False):
            context.arrived = True
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(outbound_service, "_guard_outbound", synchronized_guard)
    def run():
        try:
            return confirm_outbound(["concurrent-box"], operator=ADMIN)
        except OrderEditConflictError:
            return "concurrent conflict"
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
        assert sum(isinstance(result, dict) and bool(result["confirmed"]) for result in results) == 1
        with factory() as session:
            assert session.get(CargoTable, "concurrent-box").status == 1
            assert session.query(BoxCostRecordTable).count() == 1
            assert session.query(CargoOutboundRecordTable).count() == 1
            assert session.query(OrderVersionTable).count() == 2
    finally:
        engine.dispose()
