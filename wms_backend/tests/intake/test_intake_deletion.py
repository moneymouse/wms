"""Delete mistaken paper uploads using isolated SQLite and temporary photographs.

Run with pytest --confcutdir=tests/intake tests/intake/test_intake_deletion.py.
The reused fixture registers only test blueprints and never imports app.py.
"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event

from test_intake_workflow import (  # noqa: F401 - imported pytest fixture
    add_user, headers, png, save_complete, setup, submit,
)
from data import database
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable, PaperPhotoCleanupTable
from data.packing.PackingList import PackingListTable
from services import intake_service as service
from services import paper_photo_storage as storage


def delete_upload(client, record, identity=None, body=None):
    return client.delete(
        f"/api/intakes/{record['uid']}", headers=identity or headers(),
        json={"version": record["version"]} if body is None else body,
    )


def photo_paths(factory, uid):
    with factory() as session:
        return [photo.storage_path for photo in session.query(IntakePhotoTable).filter_by(intake_uid=uid)]


def snapshot(factory, uid):
    with factory() as session:
        record = session.get(IntakeTable, uid)
        return {
            "status": record.status, "version": record.version,
            "job": record.recognition_job_uid, "draft": record.draft_json,
            "photos": [(photo.uid, photo.storage_path) for photo in record.photos],
        }


def assert_removed(factory, uid, paths):
    with factory() as session:
        assert session.get(IntakeTable, uid) is None
        assert session.query(IntakePhotoTable).filter_by(intake_uid=uid).count() == 0
        assert session.query(PaperPhotoCleanupTable).filter(
            PaperPhotoCleanupTable.storage_path.in_(paths),
        ).count() == 0
        assert session.query(CargoTable).count() == session.query(PackingListTable).count() == 0
    assert all(storage.file_size(path) is None for path in paths)


@pytest.mark.parametrize("recognition_status", ["idle", "running", "succeeded", "failed"])
def test_owner_can_delete_pending_upload_and_all_private_photos(setup, recognition_status):
    client, factory = setup
    record = client.post("/api/intakes", headers=headers(), data={
        "photos": [(png(), "first.png"), (png(), "second.png")],
    }).json["data"]
    with factory.begin() as session:
        session.get(IntakeTable, record["uid"]).recognition_status = recognition_status
    record = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    paths = photo_paths(factory, record["uid"])
    assert len(paths) == 2
    response = delete_upload(client, record)
    assert response.status_code == 200, response.json
    assert response.json["data"]["deleted"] is True
    assert_removed(factory, record["uid"], paths)
    assert client.get(f"/api/intakes/{record['uid']}", headers=headers()).status_code == 404
    assert all(client.get(photo["url"], headers=headers()).status_code == 404 for photo in record["photos"])
    assert client.get("/api/intakes/my-packing-lists?status=uploading", headers=headers()).json["data"]["total"] == 0


@pytest.mark.parametrize("role", sorted(service.SUBMIT_ROLES))
def test_all_existing_upload_roles_can_delete_only_their_own_upload(setup, role):
    client, factory = setup
    add_user(factory, 6, "测试上传者", role=role)
    identity = headers(6, role)
    record = client.post("/api/intakes", headers=identity, data={"photos": (png(), "own.png")}).json["data"]
    assert delete_upload(client, record, identity).status_code == 200


@pytest.mark.parametrize("role", sorted(service.SUBMIT_ROLES))
def test_other_upload_roles_including_admin_cannot_delete_another_users_upload(setup, role):
    client, factory = setup
    record = submit(client)
    before = snapshot(factory, record["uid"])
    paths = photo_paths(factory, record["uid"])
    response = delete_upload(client, record, headers(2, role))
    assert response.status_code == 403, response.json
    assert snapshot(factory, record["uid"]) == before
    assert all(storage.file_size(path) for path in paths)


def test_delete_requires_valid_authentication_and_allowed_role_even_when_uid_missing(setup):
    client, factory = setup
    record = submit(client)
    url = f"/api/intakes/{record['uid']}"
    assert client.delete(url, json={"version": record["version"]}).status_code == 401
    assert client.delete(url, headers={"x-token": "invalid"}, json={"version": record["version"]}).status_code == 401
    assert delete_upload(client, record, headers(4, "finance")).status_code == 403
    assert client.delete("/api/intakes/missing", headers=headers(4, "finance"), json={"version": 1}).status_code == 403
    assert snapshot(factory, record["uid"])["status"] == "pending"


@pytest.mark.parametrize("version", [None, True, False, "1", 1.0, 0, -1, 999])
def test_delete_rejects_invalid_or_stale_version_without_touching_metadata_or_file(setup, version):
    client, factory = setup
    record = submit(client)
    before = snapshot(factory, record["uid"])
    paths = photo_paths(factory, record["uid"])
    assert delete_upload(client, record, body={"version": version}).status_code == 409
    assert snapshot(factory, record["uid"]) == before
    assert all(storage.file_size(path) for path in paths)
    with factory() as session:
        assert session.query(PaperPhotoCleanupTable).count() == 0


def test_missing_version_and_non_object_body_are_rejected(setup):
    client, factory = setup
    record = submit(client)
    before = snapshot(factory, record["uid"])
    assert delete_upload(client, record, body={}).status_code == 409
    assert delete_upload(client, record, body=[]).status_code == 400
    assert snapshot(factory, record["uid"]) == before


@pytest.mark.parametrize("changes", [
    {"status": "confirmed"}, {"status": "completed"}, {"status": "draft"}, {"status": "deleted"},
    {"packing_list_uid": "formal"}, {"confirmed_by": 1}, {"confirmed_at": "2026-10-08T10:00:00"},
    {"status": "deleting", "confirmed_by": 1},
])
def test_delete_refuses_completed_linked_or_historical_sources(setup, changes):
    client, factory = setup
    record = submit(client)
    with factory.begin() as session:
        if "packing_list_uid" in changes:
            session.add(PackingListTable(uid="formal", list_number="FORMAL", creator_id=1, status="completed", photos="[]", archive=False))
        source = session.get(IntakeTable, record["uid"])
        for key, value in changes.items():
            setattr(source, key, value)
    before = snapshot(factory, record["uid"])
    paths = photo_paths(factory, record["uid"])
    record["version"] = before["version"]
    assert delete_upload(client, record).status_code == 409
    assert snapshot(factory, record["uid"]) == before
    assert all(storage.file_size(path) for path in paths)


def test_confirmed_paper_keeps_inventory_and_photos_after_delete_attempt(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    record = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(),
                         json={"version": record["version"], "reviewed": True}).json["data"]
    paths = photo_paths(factory, record["uid"])
    assert delete_upload(client, record).status_code == 409
    with factory() as session:
        assert session.get(IntakeTable, record["uid"]).status == "confirmed"
        assert session.query(CargoTable).count() == 2
        assert session.query(PackingListTable).count() == 1
    assert all(storage.file_size(path) for path in paths)


def test_duplicate_delete_is_idempotent_and_does_not_touch_other_sources(setup):
    client, factory = setup
    record = submit(client)
    other = submit(client, uid=3)
    paths = photo_paths(factory, record["uid"])
    other_before = snapshot(factory, other["uid"])
    other_paths = photo_paths(factory, other["uid"])
    for _ in range(2):
        response = delete_upload(client, record)
        assert response.status_code == 200 and response.json["data"]["deleted"] is True
    assert_removed(factory, record["uid"], paths)
    assert snapshot(factory, other["uid"]) == other_before
    assert all(storage.file_size(path) for path in other_paths)


def test_concurrent_duplicate_delete_can_finish_the_same_tombstone_once(setup):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    loads = 0
    winner = []

    def finish_competing_retry(session, instance):
        nonlocal loads
        if isinstance(instance, IntakeTable) and instance.uid == record["uid"]:
            loads += 1
            if loads == 2:
                winner.append(delete_upload(client, record))

    event.listen(factory, "loaded_as_persistent", finish_competing_retry)
    try:
        response = delete_upload(client, record)
    finally:
        event.remove(factory, "loaded_as_persistent", finish_competing_retry)
    assert winner[0].status_code == response.status_code == 200
    assert_removed(factory, record["uid"], paths)


def test_missing_photo_file_is_already_clean(setup):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    storage.delete_file(paths[0])
    assert delete_upload(client, record).status_code == 200
    assert_removed(factory, record["uid"], paths)


@pytest.mark.parametrize("path", ["../outside.png", "/tmp/outside.png", "other-source/other-photo.png"])
def test_unsafe_or_foreign_photo_path_is_rejected_before_any_removal(setup, path):
    client, factory = setup
    record = submit(client)
    owned_path = photo_paths(factory, record["uid"])[0]
    foreign = storage.save_bytes("other-source", "other-photo", "image/png", b"unrelated")
    with factory.begin() as session:
        session.query(IntakePhotoTable).filter_by(intake_uid=record["uid"]).one().storage_path = path
    before = snapshot(factory, record["uid"])
    assert delete_upload(client, record).status_code == 409
    assert snapshot(factory, record["uid"]) == before
    assert storage.file_size(owned_path)
    assert storage.read_bytes(SimpleNamespace(**foreign)) == b"unrelated"


def test_symbolic_link_is_never_deleted_and_outside_file_survives(setup, paper_photo_root, tmp_path):
    client, factory = setup
    record = submit(client)
    path = paper_photo_root / photo_paths(factory, record["uid"])[0]
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"unrelated")
    path.unlink()
    path.symlink_to(outside)
    response = delete_upload(client, record)
    assert response.status_code == 503, response.json
    assert response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert path.is_symlink() and outside.read_bytes() == b"unrelated"
    with factory() as session:
        assert session.get(IntakeTable, record["uid"]).status == "deleting"
        assert session.query(PaperPhotoCleanupTable).count() == 1


def test_new_active_reference_prevents_shared_file_cleanup(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        source_photo = session.query(IntakePhotoTable).filter_by(intake_uid=record["uid"]).one()
        metadata = {key: getattr(source_photo, key) for key in ("storage_path", "size_bytes", "sha256", "mime_type")}
    drain = storage.drain_photo_cleanup
    installed = False

    def drain_after_new_reference(*args, **kwargs):
        nonlocal installed
        if not installed:
            installed = True
            with factory.begin() as session:
                session.add(IntakeTable(uid="other", submitted_by=3, submitted_by_name="其他上传者", created_at=service.now(),
                                        photos=[IntakePhotoTable(uid="shared", position=0, filename="shared.png", **metadata)]))
        return drain(*args, **kwargs)

    monkeypatch.setattr(storage, "drain_photo_cleanup", drain_after_new_reference)
    response = delete_upload(client, record)
    assert response.status_code == 503, response.json
    assert storage.file_size(metadata["storage_path"]) == metadata["size_bytes"]
    with factory() as session:
        assert session.get(IntakeTable, "other").status == "pending"
        assert session.query(IntakePhotoTable).one().uid == "shared"
        assert session.query(PaperPhotoCleanupTable).count() == 1


def test_cleanup_failure_is_retryable_and_remains_in_the_owners_unfinished_list(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    unrelated = storage.save_bytes("unrelated", "queued", "image/png", b"keep")
    with factory.begin() as session:
        session.add(PaperPhotoCleanupTable(storage_path=unrelated["storage_path"], size_bytes=4, created_at=service.now()))
    original = storage.delete_file
    monkeypatch.setattr(storage, "delete_file", Mock(side_effect=PermissionError("temporary disk failure")))
    response = delete_upload(client, record)
    assert response.status_code == 503 and response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    with factory() as session:
        source = session.get(IntakeTable, record["uid"])
        assert source.status == "deleting" and source.recognition_job_uid is None
        assert source.photos == []
        assert source.version > record["version"]
    items = client.get("/api/intakes/my-packing-lists?status=uploading", headers=headers()).json["data"]["items"]
    assert len(items) == 1
    assert items[0]["uid"] == record["uid"]
    assert items[0]["status"] == "uploading" and items[0]["photo_cleanup_pending"] is True
    assert items[0]["can_delete"] is True and items[0]["version"] > record["version"]
    assert client.get("/api/intakes/my-packing-lists?status=uploading", headers=headers(3)).json["data"]["items"] == []
    assert delete_upload(client, record, headers(2, "admin")).status_code == 403
    base = f"/api/intakes/{record['uid']}"
    assert client.get(base, headers=headers()).status_code == 404
    assert client.get(record["photos"][0]["url"], headers=headers()).status_code == 404
    for suffix, method, body in (("draft", "put", {"version": items[0]["version"], "draft": {"mark": "RECREATE", "boxes": []}}),
                                 ("confirm", "post", {"version": items[0]["version"], "reviewed": True}),
                                 ("recognize", "post", {"version": items[0]["version"]})):
        assert getattr(client, method)(base + "/" + suffix, headers=headers(), json=body).status_code == 404
    monkeypatch.setattr(storage, "delete_file", original)
    assert delete_upload(client, record).status_code == 200
    assert_removed(factory, record["uid"], paths)
    with factory() as session:
        assert session.query(PaperPhotoCleanupTable).one().storage_path == unrelated["storage_path"]
    assert storage.file_size(unrelated["storage_path"]) == 4


def inject_commit_failure(monkeypatch, factory, stage, lose_ack=False):
    injected = False
    first = True

    def failing_factory():
        nonlocal first
        session = factory()
        first_session = first
        first = False
        commit = session.commit

        def fail_target_commit():
            nonlocal injected
            target = first_session if stage == "first" else any(isinstance(row, IntakeTable) for row in session.deleted)
            if target and not injected:
                injected = True
                if lose_ack:
                    commit()
                raise RuntimeError("injected deletion commit failure")
            return commit()

        session.commit = fail_target_commit
        return session

    monkeypatch.setattr(database, "SessionFactory", failing_factory)
    return lambda: injected


def test_first_transaction_failure_preserves_source_photo_and_empty_cleanup_queue(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    before = snapshot(factory, record["uid"])
    paths = photo_paths(factory, record["uid"])
    injected = inject_commit_failure(monkeypatch, factory, "first")
    response = delete_upload(client, record)
    assert injected() and response.status_code == 500
    assert "deleted" not in response.json.get("data", {})
    assert snapshot(factory, record["uid"]) == before
    assert all(storage.file_size(path) for path in paths)
    with factory() as session:
        assert session.query(PaperPhotoCleanupTable).count() == 0


def test_queue_insertion_failure_rolls_back_version_and_photo_metadata(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    before = snapshot(factory, record["uid"])
    paths = photo_paths(factory, record["uid"])
    queue = storage.queue_photo_deletion

    def queue_then_fail(*args, **kwargs):
        queue(*args, **kwargs)
        raise OSError("injected queue insertion failure")

    monkeypatch.setattr(storage, "queue_photo_deletion", queue_then_fail)
    response = delete_upload(client, record)
    assert response.status_code == 500 and "deleted" not in response.json.get("data", {})
    assert snapshot(factory, record["uid"]) == before
    assert all(storage.file_size(path) for path in paths)
    with factory() as session:
        assert session.query(PaperPhotoCleanupTable).count() == 0


def test_cleanup_queue_commit_failure_preserves_retry_after_file_has_been_removed(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    injected = False

    def failing_factory():
        session = factory()
        commit = session.commit

        def fail_cleanup_commit():
            nonlocal injected
            if not injected and any(isinstance(row, PaperPhotoCleanupTable) for row in session.deleted):
                injected = True
                raise RuntimeError("injected cleanup queue commit failure")
            return commit()

        session.commit = fail_cleanup_commit
        return session

    monkeypatch.setattr(database, "SessionFactory", failing_factory)
    response = delete_upload(client, record)
    assert injected and response.status_code == 503
    assert response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert all(storage.file_size(path) is None for path in paths)
    with factory() as session:
        assert session.get(IntakeTable, record["uid"]).status == "deleting"
        assert session.query(PaperPhotoCleanupTable).count() == 1
    monkeypatch.setattr(database, "SessionFactory", factory)
    assert delete_upload(client, record).status_code == 200
    assert_removed(factory, record["uid"], paths)


def test_committed_first_transaction_with_lost_ack_is_recoverable_without_recreating_upload(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    injected = inject_commit_failure(monkeypatch, factory, "first", lose_ack=True)
    response = delete_upload(client, record)
    assert injected() and response.status_code == 503
    assert response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    with factory() as session:
        assert session.get(IntakeTable, record["uid"]).status == "deleting"
        assert session.query(IntakePhotoTable).count() == 0
    monkeypatch.setattr(database, "SessionFactory", factory)
    assert delete_upload(client, record).status_code == 200
    assert_removed(factory, record["uid"], paths)


@pytest.mark.parametrize("lose_ack", [False, True])
def test_final_source_delete_commit_failure_can_be_retried_after_files_are_removed(setup, monkeypatch, lose_ack):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    injected = inject_commit_failure(monkeypatch, factory, "final", lose_ack=lose_ack)
    response = delete_upload(client, record)
    assert injected() and response.status_code in (200, 503)
    if response.status_code == 503:
        assert response.json["data"] == {"deleted": True, "photo_cleanup_pending": True}
    assert all(storage.file_size(path) is None for path in paths)
    with factory() as session:
        source = session.get(IntakeTable, record["uid"])
        if lose_ack:
            assert source is None
        else:
            assert source.status == "deleting"
        assert session.query(IntakePhotoTable).count() == 0
    monkeypatch.setattr(database, "SessionFactory", factory)
    assert delete_upload(client, record).status_code == 200
    assert_removed(factory, record["uid"], paths)


def when_source_loads(factory, uid, callback):
    fired = False

    def compete(session, instance):
        nonlocal fired
        if not fired and isinstance(instance, IntakeTable) and instance.uid == uid:
            fired = True
            callback()

    event.listen(factory, "loaded_as_persistent", compete)
    return compete


def test_confirmation_wins_before_delete_cas_and_delete_rolls_back_all_changes(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    paths = photo_paths(factory, record["uid"])
    winner = []
    hook = when_source_loads(factory, record["uid"], lambda: winner.append(
        client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(),
                    json={"version": record["version"], "reviewed": True}),
    ))
    try:
        response = delete_upload(client, record)
    finally:
        event.remove(factory, "loaded_as_persistent", hook)
    assert winner[0].status_code == 200, winner[0].json
    assert response.status_code == 409, response.json
    with factory() as session:
        assert session.get(IntakeTable, record["uid"]).status == "confirmed"
        assert session.query(CargoTable).count() == 2 and session.query(PackingListTable).count() == 1
        assert session.query(IntakePhotoTable).count() == 1
        assert session.query(PaperPhotoCleanupTable).count() == 0
    assert all(storage.file_size(path) for path in paths)


def test_delete_wins_before_confirmation_cas_and_confirmation_cannot_create_inventory(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    paths = photo_paths(factory, record["uid"])
    winner = []
    hook = when_source_loads(factory, record["uid"], lambda: winner.append(delete_upload(client, record)))
    try:
        response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(),
                               json={"version": record["version"], "reviewed": True})
    finally:
        event.remove(factory, "loaded_as_persistent", hook)
    assert winner[0].status_code == 200, winner[0].json
    assert response.status_code in (404, 409), response.json
    assert_removed(factory, record["uid"], paths)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_deletion_during_recognition_discards_late_result_without_inventory_or_source_revival(setup, monkeypatch, cleanup_fails):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    with factory() as session:
        job = session.get(IntakeTable, record["uid"]).recognition_job_uid
    if cleanup_fails:
        monkeypatch.setattr(storage, "delete_file", Mock(side_effect=PermissionError("temporary failure")))

    def recognize_then_delete(*args, **kwargs):
        response = delete_upload(client, record)
        assert response.status_code == (503 if cleanup_fails else 200), response.json
        return {"mark": "LATE", "operator_name": "测试1", "boxes": [{"box_number": 1}]}

    provider = Mock(side_effect=recognize_then_delete)
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    service.run_recognition(record["uid"], job, [], "")
    provider.assert_called_once()
    with factory() as session:
        source = session.get(IntakeTable, record["uid"])
        if cleanup_fails:
            assert source.status == "deleting" and source.recognition_job_uid is None
            assert source.recognition_result_json is None
        else:
            assert source is None
        assert session.query(CargoTable).count() == session.query(PackingListTable).count() == 0
    if not cleanup_fails:
        assert all(storage.file_size(path) is None for path in paths)


def test_delete_wins_after_recognition_loads_its_final_snapshot_and_late_cas_cannot_revive_source(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    paths = photo_paths(factory, record["uid"])
    with factory() as session:
        job = session.get(IntakeTable, record["uid"]).recognition_job_uid
    hooks = []
    deleted = []

    def recognize(*args, **kwargs):
        hooks.append(when_source_loads(factory, record["uid"], lambda: deleted.append(delete_upload(client, record))))
        return {"mark": "LATE", "operator_name": "测试1", "boxes": [{"box_number": 1}]}

    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=recognize))
    try:
        service.run_recognition(record["uid"], job, [], "")
    finally:
        for hook in hooks:
            event.remove(factory, "loaded_as_persistent", hook)
    assert deleted[0].status_code == 200, deleted[0].json
    assert_removed(factory, record["uid"], paths)

