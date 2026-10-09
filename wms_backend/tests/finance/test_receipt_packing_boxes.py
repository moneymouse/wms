"""Packing-box notes survive cash posting and resolve later to unique orders."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql

from Auth import create_jwt
from data.DB import CargoTable, OrderTable
from data.customer.Customer import CustomerTable
from data.finance.ledger import FinanceAllocation, FinancePayment
from data.packing.PackingList import PackingListTable
from services import finance_ledger_service as ledger
from services import finance_order_service as orders
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import finance, ACTOR, SALES
from tests.finance.test_customer_payments import body
from tests.finance.test_order_settlement import order_finance, TODAY
from utils.finance_payment_pdf import build_finance_payment_pdf


@pytest.fixture
def packing_boxes(finance):
    with TestSessionFactory() as session:
        session.add_all([
            PackingListTable(uid="packing-a", list_number="MARK-A", customer_id=finance["customer"], creator_id=702, create_date="2026-10-06", archive=False),
            PackingListTable(uid="packing-b", list_number="MARK-B", customer_id=finance["customer"], creator_id=702, create_date="2026-10-05", archive=False),
            PackingListTable(uid="packing-other", list_number="OTHER-MARK", customer_id=finance["other_customer"], creator_id=702, archive=False),
        ])
        session.add_all([
            CargoTable(uid="packing-box-1", packing_list_uid="packing-a", box_number=1, transfer_id="XD123456L", item_name="服装", weight=5, archive=False),
            CargoTable(uid="packing-box-2", packing_list_uid="packing-a", box_number=2, weight=5, archive=False),
            CargoTable(uid="packing-box-3", packing_list_uid="packing-b", box_number=1, weight=7, archive=False),
            CargoTable(uid="packing-box-other", packing_list_uid="packing-other", box_number=1, weight=9, archive=False),
        ])
        session.commit()
    return ["packing-box-1", "packing-box-2", "packing-box-3"]


@pytest.fixture
def unbound_packing_box(finance):
    with TestSessionFactory() as session:
        session.add(PackingListTable(uid="packing-unbound", list_number="UNBOUND-MARK", customer_id=None,
            creator_id=702, create_date="2026-10-07", archive=False))
        session.add(CargoTable(uid="unbound-box", packing_list_uid="packing-unbound", box_number=1,
            transfer_id="XDUNBOUNDL", weight=6, archive=False))
        session.commit()
    return "unbound-box"


def test_unbound_packing_boxes_can_be_noted_without_changing_customer_binding(finance, packing_boxes, unbound_packing_box):
    choices = ledger.payment_options("packing-boxes", SALES, customer_id=finance["customer"])
    assert {row["box_uid"] for row in choices["items"]} == {*packing_boxes, unbound_packing_box}
    assert "packing-box-other" not in {row["box_uid"] for row in choices["items"]}
    found = ledger.payment_options("packing-boxes", SALES, customer_id=finance["customer"], q="UNBOUND-MARK")
    assert found["items"][0]["box_uid"] == unbound_packing_box
    assert found["items"][0]["customer_id"] is None
    draft = ledger.create_payment(body(finance, reference_box_uids=[unbound_packing_box]), SALES)
    assert draft["partner_id"] == finance["customer"]
    assert draft["reference_packing_boxes"][0]["customer_id"] is None
    assert draft["packing_order_uids"] == []
    with pytest.raises(ValueError, match="其他客户"):
        ledger.create_payment(body(finance, reference_box_uids=["packing-box-other"]), SALES)
    with TestSessionFactory() as session:
        assert session.get(PackingListTable, "packing-unbound").customer_id is None
        assert session.query(FinanceAllocation).count() == 0


def test_unbound_box_later_assigned_to_a_different_customer_order_remains_unresolved(order_finance, unbound_packing_box):
    draft = ledger.create_payment(body(order_finance, reference_box_uids=[unbound_packing_box]), SALES)
    with TestSessionFactory() as session:
        session.get(CargoTable, unbound_packing_box).target_order_uid = "order-one"
        session.get(OrderTable, "order-one").customers = [session.get(CustomerTable, order_finance["other_customer"])]
        session.commit()
    refreshed = ledger.get_payment(draft["id"], SALES)
    assert refreshed["packing_order_uids"] == []
    assert refreshed["unresolved_packing_boxes"][0]["reason"] == "箱子所属订单与收付款客户不一致"
    assert refreshed["reference_packing_boxes"][0]["customer_id"] is None
    assert refreshed["partner_id"] == draft["partner_id"]
    assert refreshed["allocated_amount"] == "0.00"


def test_sales_can_receive_before_orders_and_preserve_box_snapshots(finance, packing_boxes):
    draft = ledger.create_payment(body(finance, reference_box_uids=packing_boxes, amount="168.50"), SALES)
    assert draft["reference_box_uids"] == packing_boxes
    assert draft["reference_packing_boxes"][0]["list_number"] == "MARK-A"
    assert draft["reference_packing_boxes"][0]["transfer_id"] == "XD123456L"
    assert draft["packing_order_uids"] == []
    assert len(draft["unresolved_packing_boxes"]) == 3
    pending = ledger.submit_payment(draft["id"], {"version": draft["version"]}, SALES)
    with TestSessionFactory() as session:
        session.get(CargoTable, packing_boxes[0]).transfer_id = "CHANGED"
        session.get(CargoTable, packing_boxes[0]).weight = 50
        session.get(PackingListTable, "packing-a").list_number = "NEW-MARK"
        session.commit()
    posted = ledger.post_payment(draft["id"], {"version": pending["version"]}, ACTOR)
    assert posted["amount"] == "168.50"
    assert posted["reference_packing_boxes"] == draft["reference_packing_boxes"]
    assert posted["allocated_amount"] == "0.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).count() == 0


@pytest.mark.parametrize("uids", [["packing-box-other"], ["missing"], ["packing-box-1", "packing-box-1"], "packing-box-1", ["packing-box-1"] * 501])
def test_invalid_packing_notes_rejected_before_creating_cash(finance, packing_boxes, uids):
    with pytest.raises(ValueError):
        ledger.create_payment(body(finance, reference_box_uids=uids), SALES)
    with TestSessionFactory() as session:
        assert session.query(FinancePayment).count() == 0


def test_existing_snapshot_survives_archive_and_adding_other_packing_boxes(finance, packing_boxes):
    draft = ledger.create_payment(body(finance, reference_box_uids=packing_boxes[:1]), SALES)
    with TestSessionFactory() as session:
        session.get(CargoTable, packing_boxes[0]).archive = True
        session.commit()
    updated = ledger.update_payment(draft["id"], {"version": draft["version"], "reference_box_uids": [packing_boxes[0], packing_boxes[2]]}, SALES)
    assert updated["reference_packing_boxes"][0] == draft["reference_packing_boxes"][0]
    assert updated["unresolved_packing_boxes"][0]["reason"] == "箱子不存在或已归档"


def test_finance_resolves_assigned_boxes_once_and_allocates_only_order_money(order_finance, packing_boxes):
    draft = ledger.create_payment(body(order_finance, payment_date=TODAY, amount="180", reference_box_uids=packing_boxes), ACTOR)
    posted = ledger.post_payment(draft["id"], {"version": draft["version"]}, ACTOR)
    with TestSessionFactory() as session:
        for uid in packing_boxes[:2]:
            session.get(CargoTable, uid).target_order_uid = "order-one"
        session.commit()
    refreshed = ledger.get_payment(posted["id"], ACTOR)
    assert refreshed["packing_order_uids"] == ["order-one"]
    assert refreshed["packing_order_references"][0]["box_uids"] == packing_boxes[:2]
    assert [row["box_uid"] for row in refreshed["unresolved_packing_boxes"]] == packing_boxes[2:]
    choices = orders.list_orders(ACTOR, payment_id=posted["id"], partner_id=order_finance["customer"])
    assert [row["order_uid"] for row in choices["items"]] == ["order-one"]
    assert choices["total"] == 1
    row = choices["items"][0]
    result = orders.allocate_orders({"payment_id": posted["id"], "version": refreshed["version"], "packing_only": True,
        "allocation_date": TODAY, "allocations": [{"order_uid": row["order_uid"], "amount": "80", "source_hash": row["source_hash"]}]}, ACTOR)
    assert result["source"]["amount"] == "180.00"
    assert result["source"]["allocated_amount"] == "80.00"
    assert result["source"]["unallocated_amount"] == "100.00"
    assert len(result["items"]) == 1
    assert result["items"][0]["order_uid"] == "order-one"
    assert ledger.get_payment(posted["id"], ACTOR)["reference_packing_boxes"] == posted["reference_packing_boxes"]


def test_packing_scoped_allocation_rejects_changed_box_ownership(order_finance, packing_boxes):
    draft = ledger.create_payment(body(order_finance, payment_date=TODAY, reference_box_uids=packing_boxes), ACTOR)
    posted = ledger.post_payment(draft["id"], {"version": draft["version"]}, ACTOR)
    row = next(row for row in orders.list_orders(ACTOR)["items"] if row["order_uid"] == "order-one")
    with pytest.raises(ledger.FinanceConflictError, match="归属已变化"):
        orders.allocate_orders({"payment_id": posted["id"], "version": posted["version"], "packing_only": True,
            "allocation_date": TODAY, "allocations": [{"order_uid": row["order_uid"], "amount": "10", "source_hash": row["source_hash"]}]}, ACTOR)
    assert ledger.get_payment(posted["id"], ACTOR)["allocated_amount"] == "0.00"


def test_moving_a_box_after_order_preview_rejects_stale_financial_hash(order_finance, packing_boxes):
    with TestSessionFactory() as session:
        session.get(CargoTable, packing_boxes[0]).target_order_uid = "order-one"
        session.commit()
    draft = ledger.create_payment(body(order_finance, payment_date=TODAY, reference_box_uids=packing_boxes[:2]), ACTOR)
    posted = ledger.post_payment(draft["id"], {"version": draft["version"]}, ACTOR)
    row = orders.list_orders(ACTOR, payment_id=posted["id"])["items"][0]
    with TestSessionFactory() as session:
        session.get(CargoTable, packing_boxes[0]).target_order_uid = "order-two"
        # Keep another noted box in the old order: membership still passes but
        # the full operational snapshot must reject the old financial preview.
        session.get(CargoTable, packing_boxes[1]).target_order_uid = "order-one"
        session.commit()
    with pytest.raises(ledger.FinanceConflictError, match="已变化"):
        orders.allocate_orders({"payment_id": posted["id"], "version": posted["version"], "packing_only": True,
            "allocation_date": TODAY, "allocations": [{"order_uid": row["order_uid"], "amount": "10", "source_hash": row["source_hash"]}]}, ACTOR)
    assert ledger.get_payment(posted["id"], ACTOR)["allocated_amount"] == "0.00"


def test_box_assigned_to_another_customers_order_stays_an_unresolved_note(order_finance, packing_boxes):
    draft = ledger.create_payment(body(order_finance, reference_box_uids=packing_boxes[:1]), SALES)
    with TestSessionFactory() as session:
        session.get(CargoTable, packing_boxes[0]).target_order_uid = "order-one"
        session.get(OrderTable, "order-one").customers = [session.get(CustomerTable, order_finance["other_customer"])]
        session.commit()
    refreshed = ledger.get_payment(draft["id"], SALES)
    assert refreshed["packing_order_uids"] == []
    assert refreshed["unresolved_packing_boxes"][0]["reason"] == "箱子所属订单与收付款客户不一致"
    assert refreshed["amount"] == draft["amount"]
    assert refreshed["reference_packing_boxes"] == draft["reference_packing_boxes"]


def test_packing_options_customer_search_paging_and_http_scope(finance, packing_boxes, client):
    first = ledger.payment_options("packing-boxes", SALES, customer_id=finance["customer"], page_size=1)
    assert first["total"] == 3
    assert first["items"][0]["box_uid"] == packing_boxes[0]
    matches = ledger.payment_options("packing-boxes", SALES, customer_id=finance["customer"], q="XD123456L")
    assert [row["box_uid"] for row in matches["items"]] == packing_boxes[:1]
    assert ledger.payment_options("packing-boxes", SALES, customer_id=finance["other_customer"], q="XD123456L")["total"] == 0
    response = client.get(f"/api/finance/v2/payment-options/packing-boxes?customer_id={finance['customer']}&packing_list_uid=packing-b", headers={"x-token": create_jwt(SALES)})
    assert response.status_code == 200
    assert response.get_json()["data"]["items"][0]["box_uid"] == packing_boxes[2]


def test_packing_receipt_pdf_handles_many_boxes_and_escaped_descriptions(finance, packing_boxes):
    value = ledger.create_payment(body(finance, reference_box_uids=packing_boxes), SALES)
    value["reference_packing_boxes"] *= 30
    value["reference_packing_boxes"][0]["item_name"] = "长品名 <服装> & 鞋类" * 12
    data = build_finance_payment_pdf(value).getvalue()
    assert data.startswith(b"%PDF-")
    assert len(data) > 5000


def test_packing_receipt_migration_keeps_existing_payments_and_downgrades():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261006_57c2d3e4f5a6_receipt_packing_boxes.py"
    spec = importlib.util.spec_from_file_location("packing_receipt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE finance_payments (id INTEGER PRIMARY KEY, amount NUMERIC, status VARCHAR(16))"))
        connection.execute(text("INSERT INTO finance_payments VALUES (1, 168.50, 'posted')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text("SELECT reference_packing_boxes_json FROM finance_payments")).scalar() is None
        migration.downgrade()
        assert "reference_packing_boxes_json" not in {row["name"] for row in inspect(connection).get_columns("finance_payments")}
        assert connection.execute(text("SELECT status FROM finance_payments")).scalar() == "posted"


def test_packing_snapshot_storage_supports_large_mysql_receipts():
    # Up to 500 boxes with Unicode descriptions exceed MySQL TEXT's 64 KiB.
    assert FinancePayment.__table__.c.reference_packing_boxes_json.type.compile(dialect=mysql.dialect()) == "LONGTEXT"
