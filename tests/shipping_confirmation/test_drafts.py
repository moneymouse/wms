import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.dialects import mysql

from Auth import create_jwt
from data.DB import CargoTable, AuditLogTable
from data.packing.shipping_confirmation import ShippingConfirmationDraftTable
from services import shipping_confirmation_draft_service as service
from services.shipping_confirmation_service import ShippingConfirmationError
from utils.shipping_confirmation_pdf import build_shipping_confirmation_pdf, _order_cards, _styles


ACTOR = {"user_id": 1, "role": "salesperson", "name": "业务员"}
BASE = "/api/shipping-confirmation-drafts"


def headers(**override):
    return {"x-token": create_jwt({**ACTOR, **override})}


def create(world, entries=None):
    response = world["client"].post(BASE, headers=headers(), json={
        "title": "周二出货", "entries": entries if entries is not None else [{"cargo_uid": "box-a", "agent_name": "手填代理", "remarks": "地址 A\n邮编 100001"}],
    })
    assert response.status_code == 200, response.json
    return response.json["data"]


def test_draft_reopens_appends_cross_lists_and_prints_without_shipping(world):
    client = world["client"]
    draft = create(world)
    assert draft["version"] == 1
    assert draft["entries"][0]["target_order_uid"] is None
    reopened = client.get(f"{BASE}/{draft['uid']}", headers=headers()).json["data"]
    hydration = client.post("/api/packing-lists/shipping-confirmation/boxes", headers=headers(), json={"cargo_uids": ["box-b"]}).json["data"]["items"]
    assert hydration[0]["agent_name"] == "JF"
    response = client.put(f"{BASE}/{draft['uid']}", headers=headers(), json={
        "title": draft["title"], "expected_version": reopened["version"],
        "entries": reopened["entries"] + hydration,
    })
    assert response.status_code == 200, response.json
    saved = response.json["data"]
    assert saved["version"] == 2
    assert [entry["cargo_uid"] for entry in saved["entries"]] == ["box-a", "box-b"]
    with world["factory"].begin() as session:
        session.get(CargoTable, "box-a").transfer_id = "XD812345678L"
    details = service.load_draft_shipping_details(saved["uid"], {"expected_version": 2}, ACTOR)
    assert len(details) == 2
    assert details[0]["remarks"] == "地址 A\n邮编 100001"
    assert details[0]["boxes"][0]["transfer_id"] == "XD812345678L"
    pdf = client.post(f"{BASE}/{saved['uid']}/pdf", headers=headers(), json={"expected_version": 2})
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF-")
    assert pdf.headers["Content-Type"] == "application/pdf"
    assert pdf.headers["Cache-Control"] == "private, no-store"
    with world["factory"]() as session:
        assert all(box.status == 0 for box in session.query(CargoTable).filter(CargoTable.uid.in_(["box-a", "box-b"])))
        assert session.query(AuditLogTable).filter_by(event_type="shipping_confirmation").count() == 2


def test_same_customer_agent_and_notes_group_across_packing_lists(world):
    entries = [{"cargo_uid": uid, "agent_name": "代理", "remarks": "同一地址"} for uid in ["box-a", "box-b"]]
    details = service.load_packing_shipping_details({"entries": entries})
    assert len(details) == 1
    assert details[0]["identity_value"] == "MARK-A, MARK-B"
    assert len(details[0]["boxes"]) == 2


def test_version_conflicts_preserve_saved_draft_on_save_print_and_delete(world):
    draft = create(world)
    uid = draft["uid"]
    body = {"title": "新名称", "entries": draft["entries"], "expected_version": 1}
    assert world["client"].put(f"{BASE}/{uid}", headers=headers(), json=body).status_code == 200
    assert world["client"].put(f"{BASE}/{uid}", headers=headers(), json=body).status_code == 409
    assert world["client"].post(f"{BASE}/{uid}/pdf", headers=headers(), json={"expected_version": 1}).status_code == 409
    assert world["client"].delete(f"{BASE}/{uid}", headers=headers(), json={"expected_version": 1}).status_code == 409
    assert world["client"].get(f"{BASE}/{uid}", headers=headers()).json["data"]["title"] == "新名称"


def test_own_drafts_are_private_and_manager_can_access(world):
    draft = create(world)
    assert world["client"].get(BASE, headers=headers(user_id=2)).json["data"]["items"] == []
    assert world["client"].get(f"{BASE}/{draft['uid']}", headers=headers(user_id=2)).status_code == 403
    assert world["client"].get(f"{BASE}/{draft['uid']}", headers=headers(user_id=2, role="store_manager")).status_code == 200
    assert world["client"].post(BASE, headers=headers(role="worker"), json={"entries": []}).status_code == 403
    assert world["client"].get(BASE).status_code == 401


def test_unavailable_boxes_remain_visible_but_cannot_silently_disappear_from_print(world):
    draft = create(world)
    with world["factory"].begin() as session:
        session.get(CargoTable, "box-a").archive = True
    detail = world["client"].get(f"{BASE}/{draft['uid']}", headers=headers()).json["data"]
    assert detail["entries"][0]["available"] is False
    assert detail["entries"][0]["list_number"] == "MARK-A"
    assert world["client"].post(f"{BASE}/{draft['uid']}/pdf", headers=headers(), json={"expected_version": 1}).status_code == 404
    body = {"title": draft["title"], "entries": [], "expected_version": 1}
    assert world["client"].put(f"{BASE}/{draft['uid']}", headers=headers(), json=body).status_code == 200


@pytest.mark.parametrize("entries", [None, {}, [{"cargo_uid": "missing"}], [{"cargo_uid": "archived"}],
    [{"cargo_uid": "box-a"}, {"cargo_uid": "box-a"}], [{"cargo_uid": "box-a", "agent_name": 12}],
    [{"cargo_uid": "box-a", "remarks": "a" * 2001}]])
def test_invalid_save_is_atomic(world, entries):
    draft = create(world)
    response = world["client"].put(f"{BASE}/{draft['uid']}", headers=headers(), json={"title": "失败修改", "entries": entries, "expected_version": 1})
    assert response.status_code in (400, 404)
    saved = world["client"].get(f"{BASE}/{draft['uid']}", headers=headers()).json["data"]
    assert saved["title"] == "周二出货"
    assert saved["version"] == 1


def test_delete_archive_and_empty_draft_behavior(world):
    draft = create(world, [])
    assert world["client"].post(f"{BASE}/{draft['uid']}/pdf", headers=headers(), json={"expected_version": 1}).status_code == 400
    assert world["client"].delete(f"{BASE}/{draft['uid']}", headers=headers(), json={"expected_version": 1}).status_code == 200
    assert world["client"].get(f"{BASE}/{draft['uid']}", headers=headers()).status_code == 404
    assert world["client"].get(BASE, headers=headers()).json["data"]["items"] == []


def test_pdf_escapes_notes_and_repeats_them_on_continuation():
    detail = {"uid": "1", "identity_label": "装箱单 / Packing", "identity_value": "MARK-A, MARK-B",
        "agent_name": "代理 <A>", "customer_name": "客户", "remarks": "地址 <A> & B\n邮编 100001",
        "boxes": [{"tag": f"M-{index}", "transfer_id": f"XD8{index:08d}L"} for index in range(100)]}
    cards = _order_cards(detail, _styles())
    assert len(cards) > 1
    for card in cards:
        metadata = next(item for item in card.flowables if hasattr(item, "_cellvalues"))
        cell = metadata._cellvalues[2][1]
        paragraph = cell[0] if isinstance(cell, tuple) else cell
        assert paragraph.getPlainText() == "地址 <A> & B邮编 100001"
    assert build_shipping_confirmation_pdf([detail]).getvalue().startswith(b"%PDF-")


def test_draft_migration_up_and_down(world, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261006_68d3e4f5a6b7_shipping_confirmation_drafts.py"
    spec = importlib.util.spec_from_file_location("draft_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with world["engine"].begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        assert "shipping_confirmation_drafts" not in inspect(connection).get_table_names()
        migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("shipping_confirmation_drafts")}
        assert {"entries_json", "version", "creator_id"} <= columns


def test_mysql_keeps_full_draft_and_audit_payloads():
    dialect = mysql.dialect()
    assert ShippingConfirmationDraftTable.entries_json.type.compile(dialect=dialect) == "LONGTEXT"
    assert AuditLogTable.before_data.type.compile(dialect=dialect) == "LONGTEXT"
    assert AuditLogTable.after_data.type.compile(dialect=dialect) == "LONGTEXT"
