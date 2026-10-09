import json
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from data.DB import BoxCostRecordTable, CargoTable
from data.intake import IntakePhotoTable, IntakeTable, PaperPhotoCleanupTable
from data.order_version import OrderVersionTable
from data.packing import packing_list_model
from data.packing.PackingList import BoxWorkerTable, PackingListTable
from services import packing_photo_cleanup as cleanup
from services import paper_photo_storage


ROUTE = "/api/packing-list/packing"
SOURCE_PHOTO = "/api/intakes/source/photos/source-photo"


def attach_files(world, names=("owned.png",)):
    urls = [f"/static/uploads/photos/{name}" for name in names]
    for name in names:
        (world["folder"] / name).write_bytes(b"uploaded-file")
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps(urls)
    return urls


def history_count(world):
    with world["factory"]() as session:
        return session.query(OrderVersionTable).count()


def test_source_photos_delete_after_commit_and_cannot_recreate_inventory(world, admin, worker):
    client = world["client"]
    assert client.get(SOURCE_PHOTO, headers=worker).status_code == 200
    assert world["source_photo_path"].read_bytes() == b"source-photo-binary"
    response = client.delete(ROUTE, headers=admin)
    assert response.status_code == 200, response.json
    assert client.get(SOURCE_PHOTO, headers=worker).status_code == 404
    assert not world["source_photo_path"].exists()
    assert client.get("/api/intakes/source", headers=worker).status_code == 404
    for suffix, method, body in (("draft", "put", {"version": 3, "draft": world["draft"]}),
                                 ("confirm", "post", {"version": 3, "reviewed": True}),
                                 ("recognize", "post", {"version": 3})):
        assert getattr(client, method)(f"/api/intakes/source/{suffix}", headers=worker, json=body).status_code == 404
    assert client.get("/api/intakes/my-packing-lists", headers=worker).json["data"]["items"] == []
    with world["factory"]() as session:
        assert session.get(PackingListTable, "packing") is None
        assert session.query(IntakePhotoTable).count() == 0
        source = session.get(IntakeTable, "source")
        assert (source.status, source.packing_list_uid, source.submitted_by, source.confirmed_by) == ("deleted", None, 1, 1)
        assert json.loads(source.draft_json) == world["draft"]
        assert source.recognition_job_uid is None
        assert source.version > 3
        assert session.get(CargoTable, "box").packing_list_uid is None
        assert session.query(BoxWorkerTable).one().worker_id == 1
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert client.delete(ROUTE, headers=admin).status_code == 404


@pytest.mark.parametrize("suffix", ["", "?cache=1", "#preview", "?cache=1#preview"])
def test_owned_uploaded_files_removed_after_commit_and_shared_photos_survive(world, admin, suffix):
    urls = attach_files(world, ("owned.png", "shared.png"))
    with world["factory"].begin() as session:
        session.add(PackingListTable(uid="other", list_number="OTHER", creator_id=1, archive=True, photos=json.dumps([urls[1] + suffix])))
    assert world["client"].get(urls[0]).status_code == 200
    assert world["client"].delete(ROUTE, headers=admin).status_code == 200
    assert world["client"].get(urls[0]).status_code == 404
    assert not (world["folder"] / "owned.png").exists()
    assert (world["folder"] / "shared.png").read_bytes() == b"uploaded-file"
    assert world["client"].get(urls[1]).status_code == 200


@pytest.mark.parametrize("reference", [
    "../outside.png", "/static/uploads/photos/../outside.png",
    "/static/uploads/photos/%2e%2e/outside.png", "/static/uploads/photos/%2e%2e%5coutside.png",
    "https://example.invalid/static/uploads/photos/outside.png",
    "//example.invalid/static/uploads/photos/outside.png", "/etc/outside.png",
])
def test_unsafe_or_external_references_never_delete_unrelated_files(world, admin, reference):
    unrelated = world["folder"].parent / "outside.png"
    unrelated.write_bytes(b"unrelated")
    same_name = world["folder"] / "outside.png"
    same_name.write_bytes(b"unrelated-local")
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps([reference])
    assert world["client"].delete(ROUTE, headers=admin).status_code == 200
    assert unrelated.read_bytes() == b"unrelated"
    assert same_name.read_bytes() == b"unrelated-local"


@pytest.mark.parametrize("name", ["housekeeping.txt", ".DS_Store", "index.html"])
def test_non_photo_files_in_upload_storage_are_not_owned_cleanup_targets(world, admin, name):
    unrelated = world["folder"] / name
    unrelated.write_bytes(b"not-an-uploaded-photo")
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps(["/static/uploads/photos/" + name])
    assert world["client"].delete(ROUTE, headers=admin).status_code == 200
    assert unrelated.read_bytes() == b"not-an-uploaded-photo"


def test_symlink_photo_is_not_followed_or_removed_and_reports_pending_cleanup(world, admin):
    outside = world["folder"].parent / "outside.png"
    outside.write_bytes(b"outside")
    (world["folder"] / "linked.png").symlink_to(outside)
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps(["/static/uploads/photos/linked.png"])
    response = world["client"].delete(ROUTE, headers=admin)
    assert response.status_code == 500, response.json
    assert response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert outside.read_bytes() == b"outside"
    assert (world["folder"] / "linked.png").is_symlink()


def test_symbolic_upload_directory_cannot_redirect_cleanup_outside_managed_storage(world, admin):
    outside = world["folder"].parent / "other-storage"
    outside.mkdir()
    (outside / "photo.png").write_bytes(b"not-owned")
    world["folder"].rmdir()
    world["folder"].symlink_to(outside, target_is_directory=True)
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps(["/static/uploads/photos/photo.png"])
    assert world["client"].delete(ROUTE, headers=admin).status_code == 500
    assert (outside / "photo.png").read_bytes() == b"not-owned"


def test_cleanup_helper_itself_rejects_a_path_outside_the_open_directory(world):
    outside = world["folder"].parent / "outside.png"
    outside.write_bytes(b"outside")
    with pytest.raises(cleanup.PackingPhotoCleanupError):
        cleanup.delete_photo_files({"../outside.png"}, world["folder"])
    assert outside.read_bytes() == b"outside"


def test_missing_file_is_an_idempotent_success(world, admin):
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").photos = json.dumps(["/static/uploads/photos/already-gone.png"])
    assert world["client"].delete(ROUTE, headers=admin).status_code == 200


@pytest.mark.parametrize("evidence", ["status", "date"])
def test_outbound_rejection_keeps_all_photo_storage_and_source(world, admin, worker, evidence):
    urls = attach_files(world)
    with world["factory"].begin() as session:
        box = session.get(CargoTable, "box")
        if evidence == "status":
            box.status = 1
        else:
            box.date = "2026-10-06"
    response = world["client"].delete(ROUTE, headers=admin)
    assert response.status_code == 409, response.json
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 200
    assert world["source_photo_path"].read_bytes() == b"source-photo-binary"
    assert world["client"].get(urls[0]).status_code == 200
    with world["factory"]() as session:
        assert session.get(IntakeTable, "source").status == "confirmed"
        assert session.get(PackingListTable, "packing").archive is False
    assert history_count(world) == 0


def test_initial_commit_rollback_preserves_source_and_uploaded_photos(world, worker, monkeypatch):
    attach_files(world)

    def failing_session():
        session = world["factory"]()
        session.commit = Mock(side_effect=RuntimeError("commit failed"))
        return session

    monkeypatch.setattr("data.packing.PackingList.SessionFactory", failing_session)
    with pytest.raises(RuntimeError, match="commit failed"):
        packing_list_model.delete("packing", photo_folder=world["folder"])
    assert (world["folder"] / "owned.png").read_bytes() == b"uploaded-file"
    assert world["source_photo_path"].read_bytes() == b"source-photo-binary"
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 200
    with world["factory"]() as session:
        assert session.get(IntakeTable, "source").status == "confirmed"
        assert session.get(PackingListTable, "packing").archive is False
        assert session.get(CargoTable, "box").packing_list_uid == "packing"
    assert history_count(world) == 0


def test_source_file_delete_failure_keeps_retry_queue_after_packing_record_is_deleted(world, admin, worker, monkeypatch):
    delete_file = paper_photo_storage.delete_file
    monkeypatch.setattr(paper_photo_storage, "delete_file", Mock(side_effect=PermissionError("not writable")))
    failed = world["client"].delete(ROUTE, headers=admin)
    assert failed.status_code == 500
    assert failed.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert world["source_photo_path"].read_bytes() == b"source-photo-binary"
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 404
    with world["factory"]() as session:
        assert session.get(PackingListTable, "packing") is None
        assert session.get(IntakeTable, "source").status == "deleted"
        assert session.query(IntakePhotoTable).count() == 0
        pending = session.query(PaperPhotoCleanupTable).one()
        assert pending.packing_list_uid == "packing"
    count = history_count(world)
    monkeypatch.setattr(paper_photo_storage, "delete_file", delete_file)
    retried = world["client"].delete(ROUTE, headers=admin)
    assert retried.status_code == 200, retried.json
    assert not world["source_photo_path"].exists()
    with world["factory"]() as session:
        assert session.query(PaperPhotoCleanupTable).count() == 0
    assert history_count(world) == count


@pytest.mark.parametrize("has_cost", [False, True])
def test_cleanup_failure_is_structured_and_same_delete_retries_without_duplicate_history(world, admin, monkeypatch, has_cost):
    urls = attach_files(world, ("a.png", "b.png"))
    if has_cost:
        with world["factory"].begin() as session:
            session.add(BoxCostRecordTable(box_uid="box", packing_list_uid="packing", order_uid="order",
                                           transportation_name="历史渠道", archive=True, weight=2, total_cost=42))
    unlink = cleanup.os.unlink

    def fail_second(name, **kwargs):
        if name == "b.png":
            raise PermissionError("not writable")
        return unlink(name, **kwargs)

    monkeypatch.setattr(cleanup.os, "unlink", fail_second)
    failed = world["client"].delete(ROUTE, headers=admin)
    assert failed.status_code == 500 and failed.is_json
    assert "请重试删除" in failed.json["msg"]
    assert failed.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert not (world["folder"] / "a.png").exists()
    assert world["client"].get(urls[1]).status_code == 200
    count = history_count(world)
    assert count > 0
    with world["factory"]() as session:
        pending = session.get(PackingListTable, "packing")
        assert pending.archive is True and pending.status.startswith(cleanup.DELETE_PHOTOS_PREFIX)
        assert json.loads(pending.photos) == urls
        assert session.query(IntakePhotoTable).count() == 0
    assert world["client"].put(ROUTE, headers=admin, json={"photos": []}).status_code == 404
    assert world["client"].post(ROUTE + "/box", headers=admin, json={"item_name": "不可追加", "piece_count": 1}).status_code == 404
    assert world["client"].post(ROUTE + "/complete", headers=admin).status_code == 404
    monkeypatch.setattr(cleanup.os, "unlink", unlink)
    retried = world["client"].delete(ROUTE, headers=admin)
    assert retried.status_code == 200, retried.json
    assert not (world["folder"] / "b.png").exists()
    assert not world["source_photo_path"].exists()
    assert history_count(world) == count
    with world["factory"]() as session:
        packing = session.get(PackingListTable, "packing")
        if has_cost:
            assert (packing.archive, packing.status, packing.photos) == (True, "completed", "[]")
            assert session.get(CargoTable, "box").archive is True
            cost = session.query(BoxCostRecordTable).one()
            assert (cost.total_cost, cost.archive, cost.packing_list_uid, cost.box_uid) == (42, True, "packing", "box")
            assert session.query(BoxWorkerTable).one().worker_id == 1
        else:
            assert packing is None
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    # An in-flight second cleanup may acquire the row only after the first
    # completed. Both hard-delete and retained-history results are success.
    assert packing_list_model._finish_photo_deletion("packing", photo_folder=world["folder"])
    assert history_count(world) == count


def test_non_manager_delete_permission_does_not_remove_photos(world, worker):
    attach_files(world)
    assert world["client"].delete(ROUTE, headers=worker).status_code == 403
    assert (world["folder"] / "owned.png").exists()
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 200


@pytest.mark.parametrize("archive_first", [False, True])
def test_external_status_cannot_forge_cleanup_state_to_bypass_outbound_protection(world, admin, worker, archive_first):
    attach_files(world)
    with world["factory"].begin() as session:
        session.get(CargoTable, "box").status = 1
    if archive_first:
        assert world["client"].post(ROUTE + "/archive", headers=admin).status_code == 200
    forged = world["client"].put(ROUTE, headers=admin, json={"status": "deleting:completed"})
    assert forged.status_code == 400 and forged.is_json
    assert world["client"].post(ROUTE + "/complete", headers=admin, json={"status": "deleting:completed"}).status_code == 400
    assert world["client"].post("/api/packing-list", headers=admin, json={"mark": "FORGED", "status": "deleting:completed"}).status_code == 400
    assert world["client"].delete(ROUTE, headers=admin).status_code == 409
    assert (world["folder"] / "owned.png").exists()
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 200
    with world["factory"]() as session:
        assert session.get(CargoTable, "box").packing_list_uid == "packing"


def test_cleanup_only_retry_requires_a_committed_archived_tombstone(world, admin, worker):
    attach_files(world)
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").status = "deleting:completed"
        session.get(CargoTable, "box").status = 1
    response = world["client"].delete(ROUTE, headers=admin)
    assert response.status_code == 409, response.json
    assert (world["folder"] / "owned.png").exists()
    assert world["client"].get(SOURCE_PHOTO, headers=worker).status_code == 200
