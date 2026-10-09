import json

import pytest
from sqlalchemy import event, select, text

from Auth import create_jwt
from data.DB import BoxCostRecordTable, CargoTable
from data.finance.ledger import FinanceDocument
from data.intake import IntakePhotoTable, IntakeTable, PaperPhotoCleanupTable
from data.order_version import OrderVersionTable
from data.packing.PackingList import PackingListTable
from services import paper_photo_storage as storage
from utils.log import OperationLogTable


ROOT = "/api/storage"


def get_list(world, suffix=""):
    response = world["client"].get(ROOT + "/packing-lists" + suffix, headers=world["admin"])
    assert response.status_code == 200, response.json
    return response.json["data"]


def delete_photos(world, uid="packing", body=None):
    return world["client"].delete(f"{ROOT}/packing-lists/{uid}/photos", headers=world["admin"],
                                  json={"days": 90} if body is None else body)


def source_photos(world, uid, headers=None):
    return world["client"].get(f"{ROOT}/intakes/{uid}/photos", headers=headers or world["admin"])


def delete_source_photos(world, uid, body=None):
    return world["client"].delete(f"{ROOT}/intakes/{uid}/photos", headers=world["admin"],
                                  json={} if body is None else body)


def test_summary_uses_actual_private_files_and_counts_all_photo_sources(world):
    eligible = world["add_packing"](photo_data=(b"one", b"second"), archive=True)
    world["add_packing"]("recent", dates=("2026-10-01",), photo_data=(b"new",))
    world["add_intake"](mark_hint="PENDING", photo_data=(b"waiting",))
    world["add_packing"]("deleted", source_status="deleted", photo_data=(b"retained",))
    orphan = storage.save_bytes("0" * 32, "1" * 32, "image/png", b"orphan")
    with world["factory"].begin() as session:
        for photo in session.query(IntakePhotoTable):
            photo.size_bytes = 99999  # Stats must measure the disk, not the recorded upload size.
        session.add(PaperPhotoCleanupTable(storage_path=orphan["storage_path"], size_bytes=10000,
                                          packing_list_uid=None, created_at="2026-10-07"))
    response = world["client"].get(ROOT + "/summary", headers=world["admin"])
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"total_bytes": 33, "total_files": 6,
        "photo_groups": 4,
        "eligible_bytes": eligible["bytes"], "eligible_files": 2, "eligible_packing_lists": 1,
        "pending_cleanup_files": 1, "pending_cleanup_bytes": len(b"orphan")}
    rows = get_list(world)["items"]
    assert {row["list_number"] for row in rows} == {"PACKING", "RECENT", "PENDING", "DELETED"}
    assert all(row["can_delete_photos"] for row in rows)
    assert sum(not row["deletion_warning"] for row in rows) == 1
    deleted = next(row for row in rows if row["list_number"] == "DELETED")
    assert deleted["detail_url"] is None


def test_pending_recent_partial_unshipped_and_archived_sources_all_remain_visible_for_every_days_value(world):
    world["add_packing"]("recent", dates=("2026-10-01",))
    world["add_packing"]("partial", dates=("2026-06-01", None), statuses=(1, 0))
    world["add_packing"]("unshipped", dates=(None,), statuses=(0,))
    world["add_packing"]("archived", archive=True)
    pending = world["add_intake"](mark_hint="待处理唛头")
    expected = get_list(world)["items"]
    assert len(expected) == 5
    for days in (1, 30, 90, 3650):
        assert get_list(world, f"?days={days}")["items"] == expected
    rows = {row["list_number"]: row for row in expected}
    assert rows["ARCHIVED"]["can_delete_photos"] is True
    assert rows["ARCHIVED"]["archived"] is True
    assert rows["ARCHIVED"]["detail_url"] is None
    assert rows["ARCHIVED"]["detail_label"] is None
    for mark in ("RECENT", "PARTIAL", "UNSHIPPED", "待处理唛头"):
        assert rows[mark]["can_delete_photos"] is True
        assert rows[mark]["deletion_warning"]
    assert rows["待处理唛头"]["uid"] == rows["待处理唛头"]["intake_uid"] == pending["source_uid"]
    assert rows["待处理唛头"]["packing_list_uid"] is None
    assert rows["待处理唛头"]["detail_url"] is None
    assert rows["待处理唛头"]["last_shipped_at"] is None
    assert rows["待处理唛头"]["days_since_shipped"] is None
    assert len({row["intake_uid"] for row in expected}) == 5


@pytest.mark.parametrize("draft,candidate,hint,expected", [
    ({"mark": "人工唛头", "operator_name": "", "boxes": []}, {"mark": "识别唛头"}, "提示", "人工唛头"),
    ({"mark": "旧提示", "boxes": []}, {"mark": "识别唛头"}, "提示", "识别唛头"),
    ({"mark": "草稿唛头", "boxes": []}, {}, "提示", "草稿唛头"),
    ({"mark": "", "boxes": []}, {}, "提示唛头", "提示唛头"),
])
def test_unassociated_photo_group_uses_current_paper_identity_without_private_edit_link(world, draft, candidate, hint, expected):
    record = world["add_intake"](draft=draft, candidate=candidate, mark_hint=hint)
    row = get_list(world)["items"][0]
    assert row["list_number"] == expected
    assert row["photo_count"] == 1
    assert row["photo_bytes"] == record["bytes"]
    assert row["detail_url"] is None
    assert row["packing_list_uid"] is None
    assert row["can_delete_photos"] is True
    assert row["deletion_warning"] == "纸单上传尚未完成"
    assert delete_photos(world, uid=record["source_uid"]).status_code == 404
    assert storage.file_size(record["paths"][0]) == record["bytes"]


def test_formal_mark_and_detail_link_take_precedence_over_source_candidates(world):
    record = world["add_packing"](list_number="正式唛头")
    with world["factory"].begin() as session:
        source = session.get(IntakeTable, record["source_uid"])
        source.mark_hint = "旧提示"
        source.draft_json = '{"mark":"人工旧唛头","boxes":[]}'
        source.recognition_result_json = '{"mark":"识别旧唛头"}'
    row = get_list(world)["items"][0]
    assert row["list_number"] == "正式唛头"
    assert row["packing_list_uid"] == row["uid"] == "packing"
    assert row["detail_url"] == "/packing-lists/packing"
    assert row["detail_label"] == "查看装箱单"


def test_archived_source_is_marked_without_a_detail_link(world):
    record = world["add_packing"](archive=True)
    row = get_list(world)["items"][0]
    assert row["intake_uid"] == record["source_uid"]
    assert row["archived"] is True
    assert row["detail_url"] is None
    assert row["detail_label"] is None
    assert row["can_delete_photos"] is True
    assert row["cleanup_reason"] == ""


@pytest.mark.parametrize("source_status", ["pending", "deleted"])
def test_nonconfirmed_archived_sources_never_offer_private_or_invalid_detail_links(world, source_status):
    world["add_packing"](archive=True, source_status=source_status)
    row = get_list(world)["items"][0]
    assert row["detail_url"] is None
    assert row["detail_label"] is None


def test_pending_source_details_and_photos_remain_private_to_the_uploader(world):
    record = world["add_intake"](mark_hint="PENDING")
    other_worker = {"x-token": create_jwt({"user_id": 2, "role": "worker"})}
    other_admin = {"x-token": create_jwt({"user_id": 2, "role": "admin"})}
    with world["factory"]() as session:
        photo_uid = session.query(IntakePhotoTable.uid).filter_by(intake_uid=record["source_uid"]).scalar()
    detail_url = f"/api/intakes/{record['source_uid']}"
    photo_url = f"{detail_url}/photos/{photo_uid}"
    for headers in (other_worker, other_admin):
        assert world["client"].get(detail_url, headers=headers).status_code == 403
        assert world["client"].get(photo_url, headers=headers).status_code == 403
    owner = {"x-token": create_jwt({"user_id": 1, "role": "worker"})}
    detail = world["client"].get(detail_url, headers=owner)
    assert detail.status_code == 200
    assert "packing_list_archived" not in detail.json["data"]


def test_all_missing_photos_keep_their_group_and_record_count_with_zero_disk_bytes(world):
    record = world["add_packing"](photo_data=(b"missing-one", b"missing-two"))
    for path in record["paths"]:
        (storage.root_path() / path).unlink()
    row = get_list(world)["items"][0]
    assert row["intake_uid"] == record["source_uid"]
    assert (row["photo_count"], row["photo_bytes"], row["missing_photo_count"]) == (2, 0, 2)
    summary = world["client"].get(ROOT + "/summary", headers=world["admin"]).json["data"]
    assert (summary["photo_groups"], summary["total_files"], summary["total_bytes"]) == (1, 0, 0)


def test_source_without_photo_records_is_not_a_photo_group(world):
    world["add_intake"](mark_hint="空来源", photo_data=())
    assert get_list(world)["total"] == 0
    summary = world["client"].get(ROOT + "/summary", headers=world["admin"]).json["data"]
    assert summary["photo_groups"] == 0


@pytest.mark.parametrize("dates,statuses,archives", [
    (("2026-06-01", None), (1, 1), (False, False)),
    (("2026-06-01", "invalid"), (1, 1), (False, False)),
    (("2026-06-01", "2026-09-01"), (1, 1), (False, True)),
    (("2026-06-01", "2026-06-01"), (1, 0), (False, True)),
    (("2026-06-01", "2026-06-01"), (1, None), (False, False)),
    ((), (), ()),
])
def test_incomplete_recent_or_archived_unshipped_box_warns_but_allows_deletion(world, dates, statuses, archives):
    record = world["add_packing"](dates=dates, statuses=statuses, box_archives=archives)
    row = get_list(world)["items"][0]
    assert row["intake_uid"] == record["source_uid"]
    assert row["can_delete_photos"] is True
    assert row["cleanup_reason"]
    assert row["deletion_warning"] == row["cleanup_reason"]
    with world["factory"]() as session:
        boxes_before = [(box.date, box.status, box.archive) for box in session.query(CargoTable).order_by(CargoTable.uid)]
    response = delete_photos(world)
    assert response.status_code == 200, response.json
    assert storage.file_size(record["paths"][0]) is None
    with world["factory"]() as session:
        assert session.query(IntakePhotoTable).count() == 0
        assert session.query(PaperPhotoCleanupTable).count() == 0
        assert [(box.date, box.status, box.archive) for box in session.query(CargoTable).order_by(CargoTable.uid)] == boxes_before


def test_age_comes_from_latest_box_shipment_but_days_never_filters_groups(world):
    world["add_packing"](dates=("2026-02-01", "2026-08-01"))
    assert get_list(world)["total"] == 1
    result = get_list(world, "?days=30")
    assert result["items"][0]["last_shipped_at"] == "2026-08-01 00:00:00"
    assert result["items"][0]["box_count"] == 2
    assert result["items"][0]["days_since_shipped"] == 67
    assert result["items"][0]["can_delete_photos"] is True
    assert result["items"][0]["deletion_warning"] == "最后出货未满90天"
    assert get_list(world, "?days=3650")["items"] == result["items"]
    summary = world["client"].get(ROOT + "/summary?days=30", headers=world["admin"]).json["data"]
    assert summary["photo_groups"] == 1
    assert summary["eligible_packing_lists"] == 0


def test_exact_retention_cutoff_and_timezone_dates_are_supported(world):
    world["add_packing"](dates=("2026-07-09T04:00:00+00:00",))
    row = get_list(world)["items"][0]
    assert row["last_shipped_at"] == "2026-07-09 12:00:00"
    assert row["days_since_shipped"] == 90
    assert row["deletion_warning"] == ""
    with world["factory"].begin() as session:
        session.get(CargoTable, "packing-box-0").date = "2026-07-09 12:00:01"
    result = get_list(world)
    assert result["total"] == 1
    assert result["items"][0]["can_delete_photos"] is True
    assert result["items"][0]["deletion_warning"] == "最后出货未满90天"


def test_archived_formal_list_can_release_only_photos_without_changing_history(world):
    record = world["add_packing"](archive=True, dates=("2026-07-01", "2026-06-01"), photo_data=(b"one", b"two"))
    before = get_list(world)["items"][0]
    assert before["photo_count"] == 2
    response = delete_photos(world)
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"deleted_files": 2, "deleted_bytes": 6, "pending_files": 0}
    assert all(storage.file_size(path) is None for path in record["paths"])
    with world["factory"]() as session:
        source = session.get(IntakeTable, record["source_uid"])
        assert (source.status, source.packing_list_uid, source.confirmed_by, source.confirmed_at, source.version) == (
            "confirmed", "packing", 1, "2026-06-01 13:00:00", 3)
        assert source.draft_json == '{"mark":"原纸单","boxes":[]}'
        packing = session.get(PackingListTable, "packing")
        assert (packing.status, packing.archive, packing.photos) == ("completed", True, "[]")
        assert [(box.status, box.date, box.archive) for box in session.query(CargoTable).order_by(CargoTable.uid)] == [
            (1, "2026-07-01", True), (1, "2026-06-01", True)]
        assert session.query(PaperPhotoCleanupTable).count() == 0
        assert session.query(IntakePhotoTable).count() == 0
        assert session.query(OperationLogTable).one().desc == "Delete shipped packing list source photos."
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert get_list(world)["total"] == 0
    assert delete_photos(world).json["data"] == {"deleted_files": 0, "deleted_bytes": 0, "pending_files": 0}


@pytest.mark.parametrize("dates,statuses", [
    ((None,), (0,)),
    ((None,), (1,)),
    (("2026-10-06",), (1,)),
    (("invalid",), (1,)),
    ((), ()),
])
def test_archived_photos_can_be_cleared_without_shipment_or_age_and_preserve_all_business_records(world, dates, statuses):
    record = world["add_packing"](archive=True, dates=dates, statuses=statuses)
    with world["factory"].begin() as session:
        session.add(FinanceDocument(number="AR-HISTORY", document_type="receivable", partner_type="customer",
                                    partner_id=1, partner_name="历史客户", document_date="2026-06-01", due_date="2026-06-30",
                                    subtotal=10, tax_amount=0, total_amount=10, reference="packing", status="posted",
                                    created_by_name="财务", created_at="2026-06-01", updated_at="2026-06-01", posted_at="2026-06-01"))
        session.add(OrderVersionTable(order_uid="historical-order", version_no=1, action="archived", summary="保留历史",
                                      correlation_id="preserve-history", created_at="2026-06-01"))
        if dates:
            session.add(BoxCostRecordTable(box_uid="packing-box-0", packing_list_uid="packing", archive=True,
                                           transportation_name="历史渠道", weight=2, total_cost=42))

    def business_snapshot():
        tables = (PackingListTable.__table__, CargoTable.__table__, BoxCostRecordTable.__table__,
                  FinanceDocument.__table__, OrderVersionTable.__table__)
        with world["factory"]() as session:
            return {table.name: [dict(row) for row in session.execute(select(table)).mappings()] for table in tables}

    before = business_snapshot()
    row = get_list(world)["items"][0]
    assert row["archived"] is True
    assert row["detail_url"] is None
    assert row["can_delete_photos"] is True
    assert row["cleanup_reason"]
    assert row["deletion_warning"] == row["cleanup_reason"]
    response = delete_photos(world, body={"days": 3650})
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"deleted_files": 1, "deleted_bytes": record["bytes"], "pending_files": 0}
    assert business_snapshot() == before
    with world["factory"]() as session:
        source = session.get(IntakeTable, record["source_uid"])
        assert (source.status, source.packing_list_uid, source.version) == ("confirmed", "packing", 3)
        assert session.query(IntakePhotoTable).count() == 0
        assert session.query(PaperPhotoCleanupTable).count() == 0
    assert storage.file_size(record["paths"][0]) is None


def test_shipment_undo_after_listing_warns_and_still_allows_delete(world):
    record = world["add_packing"]()
    assert get_list(world)["total"] == 1
    with world["factory"].begin() as session:
        box = session.get(CargoTable, "packing-box-0")
        box.status, box.date = 0, None
    assert get_list(world)["items"][0]["deletion_warning"] == "尚有箱子未出货"
    assert delete_photos(world).status_code == 200
    assert storage.file_size(record["paths"][0]) is None
    with world["factory"]() as session:
        assert session.query(PaperPhotoCleanupTable).count() == 0
        box = session.get(CargoTable, "packing-box-0")
        assert (box.status, box.date) == (0, None)


def test_box_added_before_parent_lock_is_preserved_during_photo_cleanup(world):
    record = world["add_packing"]()
    assert get_list(world)["total"] == 1
    engine = world["factory"].kw["bind"]
    inserted = []

    def add_box_before_parent_query(connection, cursor, statement, parameters, context, executemany):
        if not inserted and statement.lstrip().startswith("SELECT") and "FROM packing_lists" in statement:
            inserted.append(True)
            with world["factory"].begin() as session:
                session.add(CargoTable(uid="concurrent-new-box", packing_list_uid="packing", status=0,
                                       date=None, archive=False, box_number=2))

    event.listen(engine, "before_cursor_execute", add_box_before_parent_query)
    try:
        response = delete_photos(world)
    finally:
        event.remove(engine, "before_cursor_execute", add_box_before_parent_query)
    assert inserted
    assert response.status_code == 200, response.json
    assert storage.file_size(record["paths"][0]) is None
    with world["factory"]() as session:
        assert session.get(CargoTable, "concurrent-new-box").status == 0
        assert session.query(IntakePhotoTable).count() == 0
        assert session.query(PaperPhotoCleanupTable).count() == 0
        assert session.get(IntakeTable, record["source_uid"]).status == "confirmed"


def test_queue_and_photo_removal_are_committed_before_disk_cleanup_and_retry_succeeds(world, monkeypatch):
    record = world["add_packing"]()
    original = storage.drain_photo_cleanup

    def leave_pending(**kwargs):
        assert kwargs["packing_list_uid"] == "packing"
        with world["factory"]() as session:
            assert session.query(IntakePhotoTable).count() == 0
            assert session.query(PaperPhotoCleanupTable).count() == 1
            assert session.get(IntakeTable, record["source_uid"]).status == "confirmed"
        assert storage.file_size(record["paths"][0]) is not None
        return {"deleted_files": 0, "deleted_bytes": 0, "pending_files": 1}

    monkeypatch.setattr(storage, "drain_photo_cleanup", leave_pending)
    response = delete_photos(world)
    assert response.status_code == 200, response.json
    assert "待重试" in response.json["msg"]
    assert response.json["data"]["pending_files"] == 1
    summary = world["client"].get(ROOT + "/summary", headers=world["admin"]).json["data"]
    assert summary["eligible_bytes"] == 0
    assert summary["pending_cleanup_bytes"] == record["bytes"]
    assert summary["pending_cleanup_files"] == 1
    monkeypatch.setattr(storage, "drain_photo_cleanup", original)
    response = world["client"].post(ROOT + "/cleanup", headers=world["admin"])
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"deleted_files": 1, "deleted_bytes": record["bytes"], "pending_files": 0}


def test_queue_failure_rolls_back_photo_records_and_keeps_files(world, monkeypatch):
    record = world["add_packing"]()
    original = storage.queue_photo_deletion

    def fail_after_queue(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated queue failure")

    monkeypatch.setattr(storage, "queue_photo_deletion", fail_after_queue)
    assert delete_photos(world).status_code == 500
    assert storage.file_size(record["paths"][0]) == record["bytes"]
    with world["factory"]() as session:
        assert session.query(IntakePhotoTable).count() == 1
        assert session.query(PaperPhotoCleanupTable).count() == 0
        assert session.get(IntakeTable, record["source_uid"]).status == "confirmed"


def test_missing_and_symbolic_files_do_not_inflate_storage_or_eligible_space(world):
    record = world["add_packing"](photo_data=(b"missing", b"symbolic", b"real"))
    root = storage.root_path()
    (root / record["paths"][0]).unlink()
    linked = root / record["paths"][1]
    linked.unlink()
    outside = world["tmp_path"] / "outside.png"
    outside.write_bytes(b"outside-contents")
    linked.symlink_to(outside)
    row = get_list(world)["items"][0]
    assert (row["photo_count"], row["photo_bytes"], row["missing_photo_count"]) == (3, 4, 2)
    summary = world["client"].get(ROOT + "/summary", headers=world["admin"]).json["data"]
    assert summary["total_files"] == 1
    assert summary["total_bytes"] == 4
    assert outside.read_bytes() == b"outside-contents"


def test_pagination_and_case_insensitive_search_are_applied_to_all_sources(world):
    world["add_packing"]("a", list_number="MARK-ALPHA", dates=("2026-01-01",))
    world["add_packing"]("b", list_number="MARK-BETA", dates=("2026-10-01",))
    world["add_packing"]("c", list_number="OTHER", dates=("2026-03-01",))
    pending = world["add_intake"](candidate={"mark": "MARK-GAMMA"})
    result = get_list(world, "?q=mark&page=2&page_size=1")
    assert (result["total"], result["page"], result["page_size"]) == (3, 2, 1)
    assert [row["uid"] for row in result["items"]] == ["b"]
    row = get_list(world, "?q=mark&page=3&page_size=1")["items"][0]
    assert row["intake_uid"] == pending["source_uid"]
    assert row["detail_url"] is None
    assert get_list(world, "?page=100000")["items"] == []


@pytest.mark.parametrize("suffix", ["?days=0", "?days=3651", "?days=1.5", "?days=invalid",
    "?page=0", "?page=100001", "?page_size=0", "?page_size=101", "?q=" + "a" * 65,
    "?days=" + "1" * 5000, "?q=%0Amark"])
def test_invalid_list_parameters_are_rejected(world, suffix):
    response = world["client"].get(ROOT + "/packing-lists" + suffix, headers=world["admin"])
    assert response.status_code == 400, response.json


@pytest.mark.parametrize("value", [0, 3651, True, 1.5, "1.5", ""])
def test_invalid_delete_retention_is_rejected_before_queueing(world, value):
    record = world["add_packing"]()
    assert delete_photos(world, body={"days": value}).status_code == 400
    assert storage.file_size(record["paths"][0]) == record["bytes"]


def test_delete_requires_json_object_and_unknown_list_returns_404(world):
    assert delete_photos(world, body=[]).status_code == 400
    assert delete_photos(world, uid="unknown", body={}).status_code == 404


@pytest.mark.parametrize("method,path,body", [
    ("get", "/summary", None), ("get", "/packing-lists", None),
    ("get", "/intakes/source/photos", None), ("get", "/intakes/source/photos/photo", None),
    ("delete", "/intakes/source/photos", {}),
    ("delete", "/packing-lists/packing/photos", {"days": 90}), ("post", "/cleanup", None),
])
def test_authentication_and_management_roles_protect_every_route(world, method, path, body):
    call = getattr(world["client"], method)
    assert call(ROOT + path, json=body).status_code == 401
    headers = {"x-token": create_jwt({"user_id": 1, "role": "clerk"})}
    assert call(ROOT + path, json=body, headers=headers).status_code == 403
    with world["factory"]() as session:
        assert session.query(OperationLogTable).count() == 0


def test_store_manager_in_multi_role_token_can_read_storage(world):
    headers = {"x-token": create_jwt({"user_id": 1, "roles": ["worker", "store_manager"]})}
    assert world["client"].get(ROOT + "/summary", headers=headers).status_code == 200


@pytest.mark.parametrize("status,associated,archived", [
    ("pending", False, False), ("deleted", False, False),
    ("confirmed", True, False), ("confirmed", True, True),
    ("pending", True, True), ("deleted", True, True),
])
@pytest.mark.parametrize("role", ["admin", "store_manager"])
def test_storage_managers_can_view_every_source_original_without_uploader_permissions(world, status, associated, archived, role):
    if associated:
        record = world["add_packing"](source_status=status, archive=archived, list_number="正式唛头",
                                       photo_data=(b"first-photo", b"second-photo"))
        expected_number = "正式唛头"
    else:
        record = world["add_intake"](source_status=status, mark_hint="待确认唛头",
                                      photo_data=(b"first-photo", b"second-photo"))
        expected_number = "待确认唛头"
    headers = {"x-token": create_jwt({"user_id": 2, "role": role})}
    response = source_photos(world, record["source_uid"], headers)
    assert response.status_code == 200, response.json
    data = response.json["data"]
    assert data["intake_uid"] == record["source_uid"]
    assert data["list_number"] == expected_number
    assert len(data["photos"]) == 2
    for index, photo in enumerate(data["photos"]):
        assert photo["filename"] == f"{expected_number}-{index + 1:02d}.png"
        assert photo["original_filename"] == "paper.png"
        assert photo["missing"] is False
        assert "storage_path" not in photo
        assert photo["url"] == f"{ROOT}/intakes/{record['source_uid']}/photos/{photo['uid']}"
        image = world["client"].get(photo["url"], headers=headers)
        assert image.status_code == 200
        assert image.data == (b"first-photo", b"second-photo")[index]
        assert image.mimetype == "image/png"
        assert image.headers["Cache-Control"] == "private, no-store"
        assert image.headers["X-Content-Type-Options"] == "nosniff"


def test_photo_metadata_and_original_are_bound_to_the_requested_source(world):
    first = world["add_intake"](mark_hint="FIRST")
    second = world["add_intake"](mark_hint="SECOND")
    photo = source_photos(world, first["source_uid"]).json["data"]["photos"][0]
    wrong_source = f"{ROOT}/intakes/{second['source_uid']}/photos/{photo['uid']}"
    assert world["client"].get(wrong_source, headers=world["admin"]).status_code == 404
    assert source_photos(world, "unknown").status_code == 404
    assert delete_source_photos(world, "unknown").status_code == 404
    assert world["client"].get(f"{ROOT}/intakes/unknown/photos/{photo['uid']}", headers=world["admin"]).status_code == 404


@pytest.mark.parametrize("failure", ["missing", "symlink", "corrupted"])
def test_storage_photo_view_reports_unavailable_original_and_never_reads_external_files(world, failure):
    record = world["add_intake"]()
    photo = source_photos(world, record["source_uid"]).json["data"]["photos"][0]
    path = storage.root_path() / record["paths"][0]
    outside = world["tmp_path"] / "outside.png"
    outside.write_bytes(b"private-external-contents")
    if failure == "corrupted":
        path.write_bytes(b"changed")
    else:
        path.unlink()
        if failure == "symlink":
            path.symlink_to(outside)
    metadata = source_photos(world, record["source_uid"]).json["data"]["photos"][0]
    assert metadata["missing"] is (failure != "corrupted")
    response = world["client"].get(photo["url"], headers=world["admin"])
    assert response.status_code == (404 if failure == "missing" else 409)
    assert outside.read_bytes() == b"private-external-contents"


@pytest.mark.parametrize("status", ["pending", "deleted"])
def test_unconfirmed_source_photos_can_be_deleted_without_changing_paper_draft_or_business_data(world, status):
    record = world["add_intake"](source_status=status, mark_hint="未确认", draft={"mark": "未确认", "boxes": [{"item_name": "衣服"}]})
    world["add_packing"]("unrelated", dates=("2026-10-01",))
    with world["factory"]() as session:
        before = dict(session.execute(select(IntakeTable.__table__).where(IntakeTable.uid == record["source_uid"])).mappings().one())
    assert get_list(world, "?q=未确认")["items"][0]["can_delete_photos"] is True
    response = delete_source_photos(world, record["source_uid"])
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"deleted_files": 1, "deleted_bytes": record["bytes"], "pending_files": 0}
    assert storage.file_size(record["paths"][0]) is None
    with world["factory"]() as session:
        after = dict(session.execute(select(IntakeTable.__table__).where(IntakeTable.uid == record["source_uid"])).mappings().one())
        assert before == after
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == 1
        assert session.query(IntakePhotoTable).count() == 1
        assert session.query(PaperPhotoCleanupTable).count() == 0
        assert session.query(OperationLogTable).one().desc == "Delete paper intake source photos."
    assert source_photos(world, record["source_uid"]).json["data"]["photos"] == []
    assert delete_source_photos(world, record["source_uid"]).json["data"] == {"deleted_files": 0, "deleted_bytes": 0, "pending_files": 0}


@pytest.mark.parametrize("archived", [False, True])
def test_source_delete_allows_recent_shipment_and_preserves_formal_list_and_boxes(world, archived):
    record = world["add_packing"](archive=archived, dates=("2026-10-01",), photo_data=(b"source",))
    photo = source_photos(world, record["source_uid"]).json["data"]["photos"][0]
    assert get_list(world)["items"][0]["deletion_warning"] == "最后出货未满90天"
    response = delete_source_photos(world, record["source_uid"])
    assert response.status_code == 200, response.json
    with world["factory"]() as session:
        packing = session.get(PackingListTable, "packing")
        box = session.get(CargoTable, "packing-box-0")
        source = session.get(IntakeTable, record["source_uid"])
        assert (packing.archive, packing.status, packing.photos) == (archived, "completed", "[]")
        assert (box.status, box.date, box.archive) == (1, "2026-10-01", archived)
        assert (source.status, source.packing_list_uid, source.version) == ("confirmed", "packing", 3)
    assert world["client"].get(photo["url"], headers=world["admin"]).status_code == 404


def test_source_delete_commits_queue_then_retries_only_its_own_pending_files(world, monkeypatch):
    record = world["add_intake"]()
    unrelated = storage.save_bytes("other-source", "other-photo", "image/png", b"unrelated")
    with world["factory"].begin() as session:
        session.add(PaperPhotoCleanupTable(storage_path=unrelated["storage_path"], size_bytes=9,
                                           created_at="2026-10-07"))
    original = storage.delete_file

    def fail_delete(path):
        with world["factory"]() as session:
            assert session.query(IntakePhotoTable).count() == 0
            assert session.get(PaperPhotoCleanupTable, path) is not None
        raise storage.PhotoStorageError("temporary disk failure")

    monkeypatch.setattr(storage, "delete_file", fail_delete)
    response = delete_source_photos(world, record["source_uid"])
    assert response.status_code == 200, response.json
    assert response.json["data"] == {"deleted_files": 0, "deleted_bytes": 0, "pending_files": 1}
    monkeypatch.setattr(storage, "delete_file", original)
    response = delete_source_photos(world, record["source_uid"])
    assert response.json["data"] == {"deleted_files": 1, "deleted_bytes": record["bytes"], "pending_files": 0}
    with world["factory"]() as session:
        assert session.query(PaperPhotoCleanupTable).one().storage_path == unrelated["storage_path"]
    assert storage.file_size(unrelated["storage_path"]) == 9


def test_source_queue_failure_rolls_back_metadata_and_keeps_original(world, monkeypatch):
    record = world["add_intake"]()
    original = storage.queue_photo_deletion

    def fail_after_queue(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("simulated queue failure")

    monkeypatch.setattr(storage, "queue_photo_deletion", fail_after_queue)
    assert delete_source_photos(world, record["source_uid"]).status_code == 500
    with world["factory"]() as session:
        assert session.query(IntakePhotoTable).count() == 1
        assert session.query(PaperPhotoCleanupTable).count() == 0
    assert storage.file_size(record["paths"][0]) == record["bytes"]


def test_source_delete_rejects_invalid_request_before_touching_photo(world):
    record = world["add_intake"]()
    assert delete_source_photos(world, record["source_uid"], body=[]).status_code == 400
    assert delete_source_photos(world, record["source_uid"], body={"days": 0}).status_code == 400
    assert storage.file_size(record["paths"][0]) == record["bytes"]


def test_source_cleanup_path_filter_rejects_unsafe_paths(world):
    with pytest.raises(storage.PhotoStorageError):
        storage.drain_photo_cleanup(factory=world["factory"], storage_paths={"../outside.png"})
