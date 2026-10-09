"""Scoped draft printing uses only temporary SQLite and synthetic cargos."""

import json

import pytest

from test_drafts import ACTOR, BASE, create, headers
from data.DB import AuditLogTable, CargoTable
from data.packing.PackingList import PackingListTable
from data.packing.shipping_confirmation import ShippingConfirmationDraftTable
from services import shipping_confirmation_draft_service as service


def full_draft(world):
    return create(world, [{"cargo_uid": uid, "agent_name": "代理", "remarks": "同一地址"}
                          for uid in ("box-a", "box-b", "box-c")])


def state(world, uid):
    with world["factory"]() as session:
        draft = session.get(ShippingConfirmationDraftTable, uid)
        return (draft.entries_json, draft.version, draft.updated_at,
                [(box.uid, box.status, box.date, box.archive) for box in session.query(CargoTable).order_by(CargoTable.uid)],
                [(packing.uid, packing.status, packing.archive) for packing in session.query(PackingListTable).order_by(PackingListTable.uid)],
                session.query(AuditLogTable).count())


def printed_boxes(details):
    return [box["uid"] for group in details for box in group["boxes"]]


def pdf(world, draft, **body):
    return world["client"].post(f"{BASE}/{draft['uid']}/pdf", headers=headers(),
                                json={"expected_version": draft["version"], **body})


@pytest.mark.parametrize("selection", [None, ["box-b"], ["box-c", "box-a"], ["box-a", "box-b", "box-c"], ["box-b", "box-b"]])
def test_prints_all_or_only_selected_boxes_in_draft_order_without_mutation(world, selection):
    draft = full_draft(world)
    before = state(world, draft["uid"])
    body = {"expected_version": draft["version"]}
    if selection is not None:
        body["cargo_uids"] = selection
    details = service.load_draft_shipping_details(draft["uid"], body, ACTOR)
    expected = [uid for uid in ("box-a", "box-b", "box-c") if selection is None or uid in selection]
    assert printed_boxes(details) == expected
    assert len(details) == 1
    assert details[0]["remarks"] == "同一地址"
    assert details[0]["identity_value"] == ("MARK-A, MARK-B" if "box-b" in expected and len(expected) > 1 else "MARK-B" if expected == ["box-b"] else "MARK-A")
    response = pdf(world, draft, **({"cargo_uids": selection} if selection is not None else {}))
    assert response.status_code == 200 and response.data.startswith(b"%PDF-")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert state(world, draft["uid"]) == before


@pytest.mark.parametrize("selection", [None, [], {}, "box-a", True, [None], [False], [1], [""], [" "], ["x" * 33], ["missing"], ["box-a", "missing"], ["archived"], ["box-a"] * 501])
def test_explicit_invalid_scope_never_falls_back_to_full_pdf(world, selection):
    draft = full_draft(world)
    before = state(world, draft["uid"])
    response = pdf(world, draft, cargo_uids=selection)
    assert response.status_code == 400, response.json
    assert response.is_json and response.json["code"] == 400
    assert state(world, draft["uid"]) == before


def test_scope_is_limited_to_this_draft_even_when_box_is_live_and_accessible(world):
    draft = create(world)
    response = pdf(world, draft, cargo_uids=["box-a", "box-b"])
    assert response.status_code == 400
    assert "不属于当前草稿" in response.json["msg"]


@pytest.mark.parametrize("change", ["box_archived", "box_deleted", "packing_archived", "packing_missing"])
def test_invalid_selected_item_rejects_entire_request_instead_of_partial_or_all_pdf(world, change):
    draft = full_draft(world)
    with world["factory"].begin() as session:
        if change == "box_archived":
            session.get(CargoTable, "box-b").archive = True
        elif change == "box_deleted":
            session.delete(session.get(CargoTable, "box-b"))
        elif change == "packing_archived":
            session.get(PackingListTable, "packing-b").archive = True
        else:
            session.get(CargoTable, "box-b").packing_list_uid = None
    before = state(world, draft["uid"])
    response = pdf(world, draft, cargo_uids=["box-a", "box-b"])
    assert response.status_code == 404 and response.is_json
    assert state(world, draft["uid"]) == before


def test_invalid_unselected_box_does_not_block_scoped_print_but_full_print_is_rejected(world):
    draft = full_draft(world)
    with world["factory"].begin() as session:
        session.get(CargoTable, "box-b").archive = True
    before = state(world, draft["uid"])
    assert pdf(world, draft, cargo_uids=["box-a"]).status_code == 200
    assert pdf(world, draft).status_code == 404
    assert state(world, draft["uid"]) == before


def test_complete_save_preserves_unselected_entries_then_scoped_print_uses_new_version(world):
    draft = full_draft(world)
    entries = draft["entries"]
    entries[0]["remarks"] = "更新地址"
    saved = world["client"].put(f"{BASE}/{draft['uid']}", headers=headers(), json={
        "title": "完整保存", "expected_version": draft["version"], "entries": entries,
    }).json["data"]
    assert saved["version"] == draft["version"] + 1
    assert [item["cargo_uid"] for item in saved["entries"]] == ["box-a", "box-b", "box-c"]
    before = state(world, draft["uid"])
    assert pdf(world, draft, cargo_uids=["box-a"]).status_code == 409
    assert pdf(world, saved, cargo_uids=["box-a"]).status_code == 200
    details = service.load_draft_shipping_details(saved["uid"], {"expected_version": saved["version"], "cargo_uids": ["box-a"]}, ACTOR)
    assert printed_boxes(details) == ["box-a"] and details[0]["remarks"] == "更新地址"
    assert state(world, draft["uid"]) == before
    assert len(json.loads(before[0])) == 3


@pytest.mark.parametrize("actor,expected", [
    ({"user_id": 2}, 403), ({"role": "worker"}, 403),
    ({"role": "finance"}, 403), ({"user_id": 2, "role": "admin"}, 200),
    ({"user_id": 2, "role": "store_manager"}, 200), ({"role": "clerk"}, 200),
])
def test_scope_keeps_existing_draft_permissions(world, actor, expected):
    draft = full_draft(world)
    response = world["client"].post(f"{BASE}/{draft['uid']}/pdf", headers=headers(**actor),
                                    json={"expected_version": 1, "cargo_uids": ["box-a"]})
    assert response.status_code == expected


def test_auth_and_archived_draft_are_checked_for_scoped_print(world):
    draft = full_draft(world)
    assert world["client"].post(f"{BASE}/{draft['uid']}/pdf", json={"expected_version": 1, "cargo_uids": ["box-a"]}).status_code == 401
    with world["factory"].begin() as session:
        session.get(ShippingConfirmationDraftTable, draft["uid"]).archive = True
    assert pdf(world, draft, cargo_uids=["box-a"]).status_code == 404
