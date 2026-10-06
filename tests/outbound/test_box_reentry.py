"""Box reentry preserves historical records and permits a fresh shipment."""

import pytest
from sqlalchemy import text

from Auth import create_jwt
from data import cargo_model
from data.DB import (
    BoxCostRecordTable,
    CargoOutboundRecordTable,
    CargoTable,
    OrderQuoteVersionTable,
    PaymentReceiptItemTable,
    PaymentReceiptTable,
    TransportationModeTable,
)
from data.finance.BonusItem import BonusItemTable
from data.order_version import OrderVersionTable
from data.packing import box_model, packing_list_model
from data.packing.PackingList import BoxWorkerTable, PackingListTable
from services.outbound_service import confirm_outbound, update_cargo_details
from services.order_edit_policy import OrderEditConflictError


ADMIN = {"user_id": 1, "name": "管理员", "role": "admin"}


def _rows(session, table):
    return [
        {column.name: getattr(row, column.name) for column in table.__table__.columns}
        for row in session.query(table).order_by(table.id).all()
    ]


def _ship_box(world):
    update_cargo_details("box", {"waybill_id": "WB-OLD"}, confirm_outbound=True, operator=ADMIN)
    with world["factory"]() as session:
        return _rows(session, BoxCostRecordTable)[0]


def _seed_financial_history(world):
    with world["factory"]() as session:
        receipt = PaymentReceiptTable(
            receipt_no="RCPT-REENTRY", customer_id=1, customer_name="客户",
            status="approved", receipt_date="2026-10-05", payment_method="cash",
            creator_name="管理员", create_date="2026-10-05 10:00", update_date="2026-10-05 10:00",
        )
        bonus = BonusItemTable(id=1, label="打包奖金", base_amount=10, worker_count_rule=1)
        quote = OrderQuoteVersionTable(
            order_uid="order", version_no=1, weight_snapshot=2,
            receivable_amount=20, status="approved", is_final=True,
        )
        session.add_all([receipt, bonus, quote])
        session.flush()
        session.add(PaymentReceiptItemTable(
            receipt_id=receipt.id, order_uid="order", order_id="ORD",
            receivable_snapshot=20, amount=20, remaining_after=0,
        ))
        box = session.get(CargoTable, "box")
        box.bonus_item_id = 1
        box.bonus_assigned = True
        box.bonus_assigned_by = 1
        box.bonus_assigned_date = "2026-10-05 09:00"
        session.add(BoxWorkerTable(box_uid="box", worker_id=1, create_date="2026-10-05 09:00"))
        session.commit()


def test_reentry_with_receipt_clears_shipment_and_preserves_history(world):
    original_cost = _ship_box(world)
    _seed_financial_history(world)
    tables = [PaymentReceiptTable, PaymentReceiptItemTable, OrderQuoteVersionTable,
              BonusItemTable, BoxWorkerTable, CargoOutboundRecordTable]
    with world["factory"]() as session:
        history = {table: _rows(session, table) for table in tables}
        other_cargo = session.get(CargoTable, "cargo")
        other_state = (other_cargo.status, other_cargo.date, other_cargo.transfer_id, other_cargo.weight)

    assert box_model.undo_ship("box", operator=ADMIN)

    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.date, box.waybill_id) == (0, None, "")
        assert (box.transfer_id, box.target_order_uid, box.weight) == ("ORIG-BOX", "order", 2)
        assert (box.bonus_item_id, box.bonus_assigned, box.bonus_assigned_by,
                box.bonus_assigned_date) == (1, True, 1, "2026-10-05 09:00")
        assert _rows(session, BoxCostRecordTable) == [{**original_cost, "archive": True}]
        assert session.query(BoxCostRecordTable).filter_by(archive=False).count() == 0
        assert {table: _rows(session, table) for table in tables} == history
        other = session.get(CargoTable, "cargo")
        assert (other.status, other.date, other.transfer_id, other.weight) == other_state
        version = session.query(OrderVersionTable).order_by(OrderVersionTable.version_no.desc()).first()
        assert version.action == "box_shipment_undone"
        assert version.operator_id == 1 and version.operator_name == "管理员"

    # Reentry restores the ability to weigh a box, even with prior receipts.
    assert box_model.update("box", {"weight": 5})


def test_new_shipment_preserves_archived_cost_and_creates_current_snapshot(world):
    original_cost = _ship_box(world)
    with world["factory"]() as session:
        original_facts = _rows(session, CargoOutboundRecordTable)
    assert box_model.undo_ship("box", operator=ADMIN)
    box_model.update("box", {"weight": 5})
    with world["factory"]() as session:
        session.get(TransportationModeTable, 1).cost = 7
        session.commit()

    update_cargo_details("box", {"waybill_id": "WB-NEW"}, confirm_outbound=True, operator=ADMIN)

    with world["factory"]() as session:
        costs = _rows(session, BoxCostRecordTable)
        assert len(costs) == 2
        assert costs[0] == {**original_cost, "archive": True}
        current = session.query(BoxCostRecordTable).filter_by(box_uid="box", archive=False).one()
        assert (current.weight, current.unit_cost, current.total_cost, current.waybill_id) == (5, 7, 35, "WB-NEW")
        facts = _rows(session, CargoOutboundRecordTable)
        assert len(facts) == 2 and facts[:1] == original_facts
        box = session.get(CargoTable, "box")
        assert box.status == 1 and box.date == facts[1]["recorded_at"]

    assert confirm_outbound(["box"], operator=ADMIN)["unchanged"] == ["box"]
    with world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 2
        assert session.query(BoxCostRecordTable).filter_by(archive=False).count() == 1


@pytest.mark.parametrize("role", ["salesperson", "clerk", "finance", "worker", "employee"])
def test_reentry_enforces_privilege_in_model_and_http(world, role):
    original_cost = _ship_box(world)
    with world["factory"]() as session:
        versions = _rows(session, OrderVersionTable)
    with pytest.raises(PermissionError):
        box_model.undo_ship("box", operator={"user_id": 1, "role": role})
    response = world["client"].post("/api/box/box/undo-ship", headers={
        "x-token": create_jwt({"user_id": 1, "role": role}),
    })
    assert response.status_code == 403
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.waybill_id) == (1, "WB-OLD")
        assert _rows(session, BoxCostRecordTable) == [original_cost]
        assert _rows(session, OrderVersionTable) == versions


@pytest.mark.parametrize("role", ["admin", "store_manager"])
def test_http_reentry_allows_admin_and_manager_with_receipt(world, role):
    _ship_box(world)
    _seed_financial_history(world)
    headers = {"x-token": create_jwt({"user_id": 1, "name": "操作员", "roles": [role]})}
    response = world["client"].post("/api/box/box/undo-ship", headers=headers)
    assert response.status_code == 200, response.get_json()
    with world["factory"]() as session:
        assert session.get(CargoTable, "box").status == 0
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1
    assert world["client"].post("/api/box/box/undo-ship", headers=headers).status_code == 400
    assert world["client"].post("/api/box/missing/undo-ship", headers=headers).status_code == 404
    assert world["client"].post("/api/box/cargo/undo-ship", headers=headers).status_code == 404


@pytest.mark.parametrize("status", [2, 3])
def test_reentry_accepts_legacy_post_outbound_status(world, headers, status):
    _ship_box(world)
    with world["factory"]() as session:
        session.get(CargoTable, "box").status = status
        session.commit()
    response = world["client"].post("/api/box/box/undo-ship", headers=headers)
    assert response.status_code == 200, response.get_json()
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.date, box.waybill_id) == (0, None, "")
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1
        assert session.query(CargoOutboundRecordTable).count() == 1


@pytest.mark.parametrize("status", [2, 3])
@pytest.mark.parametrize("batch", [False, True])
def test_unbind_with_receipt_requires_reentry_and_preserves_history(world, status, batch):
    original_cost = _ship_box(world)
    _seed_financial_history(world)
    tables = [PaymentReceiptTable, PaymentReceiptItemTable, OrderQuoteVersionTable,
              BonusItemTable, BoxWorkerTable, CargoOutboundRecordTable]
    with world["factory"]() as session:
        history = {table: _rows(session, table) for table in tables}
        session.get(CargoTable, "box").status = status
        session.commit()

    with pytest.raises(OrderEditConflictError, match="先撤销出库"):
        cargo_model.mutate_many(["box"], "unbind") if batch else cargo_model.unbind_from_order("box")
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.target_order_uid, box.date, box.waybill_id) == (
            status, "order", original_cost["create_date"], "WB-OLD",
        )
        assert _rows(session, BoxCostRecordTable) == [original_cost]

    assert box_model.undo_ship("box", operator=ADMIN)
    if batch:
        assert cargo_model.mutate_many(["box"], "unbind") == {"success": ["box"], "failed": []}
    else:
        assert cargo_model.unbind_from_order("box")

    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.target_order_uid, box.date, box.waybill_id) == (0, None, None, "")
        assert _rows(session, BoxCostRecordTable) == [{**original_cost, "archive": True}]
        assert {table: _rows(session, table) for table in tables} == history


def test_reentry_version_failure_rolls_back_state_and_cost_archive(world, monkeypatch):
    original_cost = _ship_box(world)
    with world["factory"]() as session:
        versions = _rows(session, OrderVersionTable)

    def fail(*args, **kwargs):
        raise RuntimeError("version failed")

    monkeypatch.setattr("data.order_version.record_mutation", fail)
    with pytest.raises(RuntimeError, match="version failed"):
        box_model.undo_ship("box", operator=ADMIN)
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.status, box.waybill_id, box.date) == (1, "WB-OLD", original_cost["create_date"])
        assert _rows(session, BoxCostRecordTable) == [original_cost]
        assert session.query(CargoOutboundRecordTable).count() == 1
        assert _rows(session, OrderVersionTable) == versions


@pytest.mark.parametrize("delete_list", [False, True])
def test_delete_after_reentry_preserves_foreign_key_history(world, delete_list):
    _ship_box(world)
    _seed_financial_history(world)
    assert box_model.undo_ship("box", operator=ADMIN)
    tables = [BoxCostRecordTable, PaymentReceiptTable, PaymentReceiptItemTable,
              OrderQuoteVersionTable, BonusItemTable, BoxWorkerTable,
              CargoOutboundRecordTable]
    with world["factory"]() as session:
        # Exercise actual FK behavior, including the archived cost references.
        session.execute(text("PRAGMA foreign_keys=ON"))
        history = {table: _rows(session, table) for table in tables}

    assert (packing_list_model.delete("packing") if delete_list else box_model.delete("box"))

    with world["factory"]() as session:
        assert session.get(CargoTable, "box").archive is True
        assert bool(session.get(PackingListTable, "packing").archive) == delete_list
        assert {table: _rows(session, table) for table in tables} == history
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert box_model.read("box") is None
