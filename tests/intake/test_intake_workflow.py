"""Run independently: pytest --confcutdir=tests/intake tests/intake.

Uses a minimal Flask application, never imports app.py or runs startup backups.
"""
import importlib.util
import os
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from Auth import create_jwt
from controllers.intake_controller import intake_bp
from controllers import packing_controller
from data import database
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import PackingListTable, BoxWorkerTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import intake_service as service


@pytest.fixture
def setup(monkeypatch):
    # Upload now starts recognition. Tests must never contact a real provider.
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: Mock())
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionFactory", factory)
    monkeypatch.setattr(packing_controller, "SessionFactory", factory)
    import data.packing.PackingList as packing_data
    monkeypatch.setattr(packing_data, "SessionFactory", factory)
    database.Base.metadata.create_all(engine)
    app = Flask(__name__)
    app.register_blueprint(intake_bp)
    app.register_blueprint(packing_controller.packing_bp)
    app.config["TESTING"] = True
    with factory() as session:
        role_records = {name: RoleTable(name=name, label=name) for name in ("worker", "employee", "salesperson", "finance", "clerk")}
        session.add_all(role_records.values())
        for uid, role in ((1, "worker"), (2, "salesperson"), (3, "worker"), (4, "finance"), (5, "clerk")):
            session.add(UserTable(id=uid, name=f"测试{uid}", phone=f"1380000000{uid}", status="approved", password="unused", roles=[role_records[role]]))
        session.commit()
    yield app.test_client(), factory
    engine.dispose()


def headers(uid=1, role="worker"):
    return {"x-token": create_jwt({"user_id": uid, "name": f"测试{uid}", "role": role})}


def png():
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    output.seek(0)
    return output


def submit(client, uid=1):
    response = client.post("/api/intakes", headers=headers(uid), data={"photos": (png(), "纸单.png")})
    assert response.status_code == 201, response.json
    return response.json["data"]


def save_complete(client, record, mark="TEST-MARK", boxes=None, worker_ids=None):
    boxes = boxes or [{"box_number": 7, "item_name": "鞋", "count": 3, "weight": 1.5}, {"box_number": 9, "item_name": "衣服", "count": 4, "weight": 2.25}]
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(2, "salesperson"), json={"version": record["version"], "draft": {"mark": mark, "worker_ids": [1] if worker_ids is None else worker_ids, "boxes": boxes}})
    assert response.status_code == 200, response.json
    return response.json["data"]


def test_photo_only_submit_persists_and_is_private(setup):
    client, factory = setup
    record = submit(client)
    assert record["draft"] == {"mark": "", "boxes": []}
    assert record["status"] == "pending"
    with factory() as session:
        assert session.query(IntakeTable).count() == 1
        assert session.query(CargoTable).count() == 0
        assert session.query(IntakePhotoTable).one().data.startswith(b"\x89PNG")
    assert client.get(record["photos"][0]["url"], headers=headers()).status_code == 200
    assert client.get(record["photos"][0]["url"], headers=headers(3)).status_code == 403
    assert client.get(record["photos"][0]["url"]).status_code == 401
    assert client.get(f"/api/intakes/{record['uid']}", headers=headers(3)).status_code == 403
    assert client.get("/api/intakes", headers=headers(3)).json["data"]["total"] == 0
    assert client.get("/api/intakes", headers=headers(2, "salesperson")).json["data"]["total"] == 1


def test_formal_blank_template_uses_normal_auth_and_is_a_real_pdf(setup):
    client, _ = setup
    assert client.get("/api/intakes/template").status_code == 401
    assert client.get("/api/intakes/template", headers=headers(4, "finance")).status_code == 403
    for identity in (headers(), headers(2, "salesperson")):
        response = client.get("/api/intakes/template", headers=identity)
        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF-")
        assert "paper-packing-list-a4.pdf" in response.headers["Content-Disposition"]
        assert response.headers["Cache-Control"] == "private, no-store"


def test_missing_formal_template_is_reported_without_a_fake_download(setup, monkeypatch, tmp_path):
    from controllers import intake_controller
    client, _ = setup
    monkeypatch.setattr(intake_controller, "TEMPLATE_PATH", tmp_path / "missing-template.pdf")
    response = client.get("/api/intakes/template", headers=headers())
    assert response.status_code == 503
    assert response.is_json and response.json["code"] == 503
    assert "Content-Disposition" not in response.headers


def test_invalid_photo_and_finance_role_rejected(setup):
    client, factory = setup
    response = client.post("/api/intakes", headers=headers(), data={"photos": (BytesIO(b"not a photo"), "fake.jpg")})
    assert response.status_code == 400
    assert client.post("/api/intakes", headers=headers(4, "finance"), data={"photos": (png(), "photo.png")}).status_code == 403
    assert client.get("/api/intakes", headers=headers(4, "finance")).status_code == 403
    with factory() as session:
        assert session.query(IntakeTable).count() == 0


def test_incomplete_draft_can_save_and_stale_write_is_rejected(setup):
    client, _ = setup
    record = submit(client)
    url = f"/api/intakes/{record['uid']}"
    draft = {"mark": "", "boxes": [{"box_number": None, "item_name": "", "count": None, "weight": None}]}
    response = client.put(url + "/draft", headers=headers(5, "clerk"), json={"version": record["version"], "draft": draft})
    assert response.status_code == 200
    assert response.json["data"]["version"] == record["version"] + 1
    assert client.get(url, headers=headers()).json["data"]["draft"] == {**draft, "operator_name": "", "worker_ids": []}
    assert client.put(url + "/draft", headers=headers(2, "salesperson"), json={"version": record["version"], "draft": draft}).status_code == 409
    assert client.post(url + "/confirm", headers=headers(2, "salesperson"), json={"version": response.json["data"]["version"]}).status_code == 400
    assert client.put(url + "/draft", headers=headers(), json={"version": 2, "draft": draft}).status_code == 403
    assert client.post(url + "/confirm", headers=headers(), json={"version": 2}).status_code == 403


def test_confirmation_creates_one_list_two_unassigned_boxes_and_retries(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    url = f"/api/intakes/{record['uid']}/confirm"
    response = client.post(url, headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 200, response.json
    confirmed = response.json["data"]
    assert confirmed["status"] == "confirmed"
    source = client.get(f"/api/intakes?packing_list_uid={confirmed['packing_list_uid']}", headers=headers(2, "salesperson")).json["data"]
    assert source["total"] == 1 and source["items"][0]["uid"] == record["uid"]
    assert client.get(f"/api/intakes?packing_list_uid={confirmed['packing_list_uid']}", headers=headers(3)).json["data"]["total"] == 0
    assert client.post(url, headers=headers(2, "salesperson"), json={"version": record["version"]}).json["data"]["packing_list_uid"] == confirmed["packing_list_uid"]
    with factory() as session:
        assert session.query(PackingListTable).count() == 1
        assert session.query(PackingListTable).one().creator_id == 1
        assert session.query(IntakeTable).one().confirmed_by == 2
        boxes = session.query(CargoTable).order_by(CargoTable.box_number).all()
        assert [box.box_number for box in boxes] == [7, 9]
        assert [box.piece_count for box in boxes] == [3, 4]
        assert sum(box.weight for box in boxes) == 3.75
        assert all(box.status == 0 and box.target_order_uid is None and box.waybill_id == "" for box in boxes)
        assert {(row.box_uid, row.worker_id) for row in session.query(BoxWorkerTable)} == {(box.uid, 1) for box in boxes}
    assert client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(2, "salesperson"), json={"version": confirmed["version"], "draft": record["draft"]}).status_code == 409


@pytest.mark.parametrize("changes", [{"box_number": 0}, {"box_number": "02"}, {"box_number": "A1"}, {"count": 1.5}, {"count": -1}, {"weight": 0}, {"weight": "nan"}, {"item_name": ""}])
def test_confirmation_validates_business_fields(setup, changes):
    client, factory = setup
    box = {"box_number": 1, "item_name": "鞋", "count": 1, "weight": 1}
    box.update(changes)
    record = save_complete(client, submit(client), boxes=[box])
    assert client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(2, "salesperson"), json={"version": record["version"]}).status_code == 400
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(CargoTable).count() == 0
        assert session.query(BoxWorkerTable).count() == 0


def test_duplicate_numbers_and_existing_mark_are_explicit_conflicts(setup):
    client, factory = setup
    box = {"box_number": 4, "item_name": "鞋", "count": 1, "weight": 1}
    record = save_complete(client, submit(client), boxes=[box, box])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 400 and "重复" in response.json["msg"]
    record = save_complete(client, record, boxes=[box])
    with factory() as session:
        session.add(PackingListTable(uid="existing", list_number="TEST-MARK", creator_id=2))
        session.commit()
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 409 and "不会自动改名" in response.json["msg"]


def test_failure_on_second_box_rolls_back_everything(setup, monkeypatch):
    client, factory = setup
    record = save_complete(client, submit(client))
    original = service._new_box
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("injected box failure")
        return original(*args)
    monkeypatch.setattr(service, "_new_box", fail_second)
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 500
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(CargoTable).count() == 0
        assert session.query(IntakeTable).one().status == "pending"
        assert session.query(IntakeTable).one().packing_list_uid is None


def test_recognition_candidate_never_overwrites_late_human_edit(setup, monkeypatch):
    client, _ = setup
    record = submit(client)
    thread = Mock()
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: thread)
    response = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 202
    running = response.json["data"]
    assert running["recognition_status"] == "running"
    record = save_complete(client, running)
    with database.SessionFactory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    candidate = {"mark": "AI", "boxes": [{"box_number": 99, "item_name": "AI", "count": 1, "weight": 1}]}
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=lambda *args, **kwargs: candidate))
    service.run_recognition(record["uid"], job, [], "")
    refreshed = client.get(f"/api/intakes/{record['uid']}", headers=headers(2, "salesperson")).json["data"]
    assert refreshed["draft"] == record["draft"]
    assert {key: refreshed["recognition_result"][key] for key in candidate} == candidate
    assert refreshed["recognition_result"]["worker_ids"] == []
    assert refreshed["recognition_status"] == "succeeded"


def test_recognition_failure_and_restart_timeout_allow_retry(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: Mock())
    started = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(2, "salesperson"), json={"version": record["version"]}).json["data"]
    with factory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    def unavailable(*args, **kwargs):
        raise ValueError("DeepSeek密钥未配置")
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=unavailable))
    service.run_recognition(record["uid"], job, [], "")
    failed = service.get_intake({"user_id": 2, "role": "salesperson"}, record["uid"])
    assert failed["recognition_status"] == "failed"
    assert "未配置" in failed["recognition_error"]
    retry = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(2, "salesperson"), json={"version": failed["version"]})
    assert retry.status_code == 202
    with factory() as session:
        session.query(IntakeTable).one().recognition_started_at = "2000-01-01T00:00:00"
        session.commit()
    assert service.get_intake({"user_id": 2, "role": "salesperson"}, record["uid"])["recognition_status"] == "failed"


def test_new_migration_creates_and_removes_intake_tables():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261001_df4a5b6c7d8e_paper_intakes.py"
    spec = importlib.util.spec_from_file_location("paper_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert {"paper_intakes", "paper_intake_photos"}.issubset(inspect(connection).get_table_names())
        module.downgrade()
        assert "paper_intakes" not in inspect(connection).get_table_names()
    engine.dispose()


def test_stale_confirm_is_rejected_before_inventory_creation(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    newer = save_complete(client, record, mark="UPDATED")
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(2, "salesperson"), json={"version": record["version"]})
    assert response.status_code == 409
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(CargoTable).count() == 0
        assert session.query(IntakeTable).one().version == newer["version"]


def test_metadata_serialization_does_not_read_photo_bytes(setup):
    from sqlalchemy import inspect
    client, factory = setup
    record = submit(client)
    with factory() as session:
        intake = session.query(IntakeTable).filter_by(uid=record["uid"]).one()
        assert "data" in inspect(intake.photos[0]).unloaded
        service.serialize(intake)
        assert "data" in inspect(intake.photos[0]).unloaded


def test_optimistic_version_prevents_two_sessions_overwriting_each_other(setup):
    from sqlalchemy.orm.exc import StaleDataError
    client, factory = setup
    record = submit(client)
    with factory() as first, factory() as second:
        first_record = first.query(IntakeTable).filter_by(uid=record["uid"]).one()
        second_record = second.query(IntakeTable).filter_by(uid=record["uid"]).one()
        first_record.draft_json = '{"mark":"FIRST","boxes":[]}'
        first.commit()
        second_record.draft_json = '{"mark":"SECOND","boxes":[]}'
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    assert service.get_intake({"user_id": 1, "role": "worker"}, record["uid"])["draft"]["mark"] == "FIRST"


def test_late_previous_recognition_job_cannot_replace_new_candidate(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        row = session.query(IntakeTable).one()
        row.recognition_status = "running"
        row.recognition_job_uid = "current-job"
        row.recognition_started_at = service.now()
        session.commit()
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=lambda *args, **kwargs: {"mark": "OLD", "boxes": []}))
    service.run_recognition(record["uid"], "old-job", [], "")
    fresh = service.get_intake({"user_id": 1, "role": "worker"}, record["uid"])
    assert fresh["recognition_status"] == "running"
    assert fresh["recognition_result"] is None


def test_multiple_roles_follow_server_review_policy(setup):
    client, _ = setup
    record = submit(client)
    token = create_jwt({"user_id": 5, "name": "文员", "role": "worker", "roles": ["clerk"]})
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers={"x-token": token}, json={"version": record["version"], "draft": {"mark": "", "boxes": []}})
    assert response.status_code == 200


def test_worker_upload_starts_recognition_without_review_permission(setup, monkeypatch):
    client, factory = setup
    calls = []
    thread = Mock()
    def capture_thread(**kwargs):
        # Photos and job metadata are durable before the thread starts.
        with factory() as session:
            row = session.query(IntakeTable).one()
            assert row.recognition_status == "running"
            assert row.recognition_job_uid == kwargs["args"][1]
            assert row.photos[0].data.startswith(b"\x89PNG")
        calls.append(kwargs)
        return thread
    monkeypatch.setattr(service.threading, "Thread", capture_thread)
    record = submit(client)
    assert record["recognition_status"] == "running"
    assert record["status"] == "pending"
    assert record["recognition_result"] is None
    assert len(calls) == 1
    thread.start.assert_called_once()
    assert calls[0]["target"] is service.run_recognition
    assert calls[0]["args"][0] == record["uid"]
    assert len(calls[0]["args"][2]) == 1
    assert client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": record["version"]}).status_code == 403
    with factory() as session:
        assert session.query(CargoTable).count() == 0


def test_thread_start_failure_does_not_lose_uploaded_photo(setup, monkeypatch):
    client, factory = setup
    thread = Mock()
    thread.start.side_effect = RuntimeError("injected start failure")
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: thread)
    record = submit(client)
    assert record["recognition_status"] == "failed"
    assert "照片已回传" in record["recognition_error"]
    assert client.get(record["photos"][0]["url"], headers=headers()).status_code == 200
    with factory() as session:
        assert session.query(IntakeTable).count() == 1
        assert session.query(CargoTable).count() == 0


def test_recognized_mark_names_photos_and_is_searchable_before_draft_adoption(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    candidate = {"mark": "ABC-2026", "operator_name": "张三", "boxes": []}
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=lambda *args, **kwargs: candidate))
    service.run_recognition(record["uid"], job, [], "")
    fresh = client.get(f"/api/intakes/{record['uid']}", headers=headers(2, "salesperson")).json["data"]
    assert fresh["display_name"] == "ABC-2026"
    assert fresh["operator_name"] == "张三"
    assert fresh["submitted_by_name"] == "测试1"
    assert fresh["photos"][0]["filename"] == "ABC-2026-01.png"
    assert fresh["photos"][0]["original_filename"] == "纸单.png"
    assert fresh["draft"] == record["draft"]
    found = client.get("/api/intakes?mark=abc-2026", headers=headers(2, "salesperson")).json["data"]
    assert found["total"] == 1
    assert client.get("/api/intakes?mark=ABC-2026", headers=headers(3)).json["data"]["total"] == 0
    image = client.get(fresh["photos"][0]["url"], headers=headers())
    assert "ABC-2026-01.png" in image.headers["Content-Disposition"]
    # A corrected saved mark and operator override the AI candidate.
    updated = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(2, "salesperson"), json={"version": fresh["version"], "draft": {"mark": "FIXED", "operator_name": "李四", "boxes": []}}).json["data"]
    assert updated["display_name"] == "FIXED"
    assert updated["operator_name"] == "李四"
    assert updated["photos"][0]["filename"] == "FIXED-01.png"
    assert client.get("/api/intakes?mark=FIXED", headers=headers(2, "salesperson")).json["data"]["total"] == 1
    confirmed = save_complete(client, updated, mark="FIXED")
    assert confirmed["draft"]["operator_name"] == ""
    assert confirmed["operator_name"] == ""


def test_mark_search_escapes_wildcards_and_filenames_are_safe(setup):
    client, _ = setup
    first = save_complete(client, submit(client), mark="AB%_C/仓库")
    save_complete(client, submit(client), mark="ABXYC")
    found = client.get("/api/intakes", query_string={"mark": "%_"}, headers=headers(2, "salesperson")).json["data"]
    assert found["total"] == 1 and found["items"][0]["uid"] == first["uid"]
    assert "/" not in first["photos"][0]["filename"]
    assert first["photos"][0]["filename"].endswith("-01.png")


def test_list_expires_abandoned_recognition_and_allows_reviewer_retry(setup):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        session.query(IntakeTable).one().recognition_started_at = "2000-01-01T00:00:00"
        session.commit()
    fresh = client.get("/api/intakes", headers=headers(2, "salesperson")).json["data"]["items"][0]
    assert fresh["recognition_status"] == "failed"
    assert client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(2, "salesperson"), json={"version": fresh["version"]}).status_code == 202


def test_upload_total_limit_matches_recognition_limit(setup, monkeypatch):
    from werkzeug.datastructures import FileStorage
    client, factory = setup
    monkeypatch.setattr(service, "MAX_TOTAL_PHOTO_BYTES", len(png().getvalue()))
    with pytest.raises(service.IntakeError, match="24MB"):
        service.create_intake({"user_id": 1, "role": "worker"}, [FileStorage(png(), filename="one.png"), FileStorage(png(), filename="two.png")], {})
    with factory() as session:
        assert session.query(IntakeTable).count() == 0


def test_candidate_survives_simultaneous_human_save_without_repeating_provider(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    candidate = {"mark": "AI", "operator_name": "张三", "boxes": []}
    provider = Mock(return_value=candidate)
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    human_draft = {"mark": "HUMAN", "operator_name": "李四", "boxes": []}
    saved = False
    def colliding_factory():
        session = factory()
        original_commit = session.commit
        def commit():
            nonlocal saved
            if not saved:
                saved = True
                with factory() as reviewer:
                    reviewer.query(IntakeTable).one().draft_json = service.json.dumps(human_draft)
                    reviewer.commit()
            return original_commit()
        session.commit = commit
        return session
    monkeypatch.setattr(database, "SessionFactory", colliding_factory)
    service.run_recognition(record["uid"], job, [], "")
    provider.assert_called_once()
    fresh = service.get_intake({"user_id": 1, "role": "worker"}, record["uid"])
    assert fresh["recognition_status"] == "succeeded"
    assert {key: fresh["recognition_result"][key] for key in candidate} == candidate
    assert fresh["recognition_result"]["worker_ids"] == []
    assert fresh["draft"] == human_draft
    assert fresh["display_name"] == "HUMAN" and fresh["operator_name"] == "李四"


def add_user(factory, uid, name, role="worker", status="approved"):
    with factory() as session:
        worker_role = session.query(RoleTable).filter_by(name=role).one()
        session.add(UserTable(id=uid, name=name, phone=f"13900000{uid:03}", password="unused", status=status, roles=[worker_role]))
        session.commit()


def finish_recognition(client, factory, monkeypatch, candidate):
    record = submit(client)
    with factory() as session:
        job = session.query(IntakeTable).filter_by(uid=record["uid"]).one().recognition_job_uid
    provider = Mock(return_value=candidate)
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    service.run_recognition(record["uid"], job, [], "")
    provider.assert_called_once()
    return client.get(f"/api/intakes/{record['uid']}", headers=headers(2, "salesperson")).json["data"]


def add_manual_list(factory, uid, mark, creator=1, status="draft", created_at="2026-10-02 10:00", archived=False):
    with factory() as session:
        session.add(PackingListTable(uid=uid, list_number=mark, creator_id=creator, status=status, create_date=created_at, archive=archived, photos="[]"))
        session.commit()


def test_workers_endpoint_returns_only_approved_worker_accounts_to_reviewers(setup):
    client, factory = setup
    add_user(factory, 6, "员工甲", role="employee")
    add_user(factory, 7, "待批准", status="pending")
    add_user(factory, 8, "已拒绝", status="rejected")
    response = client.get("/api/intakes/workers", headers=headers(5, "clerk"))
    assert response.status_code == 200
    assert {worker["id"] for worker in response.json["data"]} == {1, 3, 6}
    assert all(set(worker) == {"id", "name"} for worker in response.json["data"])
    assert client.get("/api/intakes/workers", headers=headers()).status_code == 403
    assert client.get("/api/intakes/workers", headers=headers(4, "finance")).status_code == 403


@pytest.mark.parametrize("worker_ids", [[2], [4], [999], [True], ["1"], [0], [-1], [10 ** 30], None, {"id": 1}, [1, 3, 6, 7, 8]])
def test_draft_rejects_non_worker_or_invalid_worker_bindings(setup, worker_ids):
    client, factory = setup
    record = submit(client)
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(5, "clerk"), json={
        "version": record["version"], "draft": {"mark": "ABC", "boxes": [], "worker_ids": worker_ids},
    })
    assert response.status_code == 400
    with factory() as session:
        assert "worker_ids" not in service.json.loads(session.query(IntakeTable).one().draft_json)


def test_confirmation_deduplicates_and_binds_selected_real_workers_to_every_box(setup):
    client, factory = setup
    record = save_complete(client, submit(client), worker_ids=[3, 1, 3])
    assert record["draft"]["worker_ids"] == [3, 1]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(5, "clerk"), json={"version": record["version"]})
    assert response.status_code == 200
    with factory() as session:
        boxes = session.query(CargoTable).all()
        assert {(worker.box_uid, worker.worker_id) for worker in session.query(BoxWorkerTable)} == {(box.uid, uid) for box in boxes for uid in (1, 3)}
        assert session.query(PackingListTable).one().creator_id == 1
        assert session.query(IntakeTable).one().confirmed_by == 5


def test_empty_worker_selection_can_save_but_cannot_confirm(setup):
    client, factory = setup
    record = save_complete(client, submit(client), worker_ids=[])
    assert record["draft"]["worker_ids"] == []
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(5, "clerk"), json={"version": record["version"]})
    assert response.status_code == 400 and "至少选择" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0


@pytest.mark.parametrize("revoke", ["approval", "worker_role"])
def test_confirmation_revalidates_workers_after_saved_draft(setup, revoke):
    client, factory = setup
    record = save_complete(client, submit(client), worker_ids=[3])
    with factory() as session:
        user = session.query(UserTable).filter_by(id=3).one()
        if revoke == "approval":
            user.status = "rejected"
        else:
            user.roles = []
        session.commit()
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(5, "clerk"), json={"version": record["version"]})
    assert response.status_code == 400
    with factory() as session:
        assert session.query(CargoTable).count() == 0


def test_recognized_operator_names_bind_exact_unique_accounts_without_using_uploader(setup, monkeypatch):
    client, factory = setup
    candidate = {"mark": "AI", "operator_name": "测试3", "worker_ids": [2], "boxes": [], "warnings": []}
    fresh = finish_recognition(client, factory, monkeypatch, candidate)
    assert fresh["recognition_result"]["worker_ids"] == [3]
    assert fresh["recognition_result"]["warnings"] == []
    assert "worker_ids" not in fresh["draft"]
    assert fresh["draft_is_manual"] is False
    with factory() as session:
        assert session.query(BoxWorkerTable).count() == session.query(CargoTable).count() == 0


def test_multiple_exact_operator_names_bind_only_when_all_names_are_unique(setup, monkeypatch):
    client, factory = setup
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": "测试1、测试3", "boxes": []})
    assert fresh["recognition_result"]["worker_ids"] == [1, 3]


def test_duplicate_operator_name_never_picks_an_arbitrary_account(setup, monkeypatch):
    client, factory = setup
    add_user(factory, 6, "测试1")
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": "测试1", "boxes": []})
    assert fresh["recognition_result"]["worker_ids"] == []
    assert any("同名工人" in warning for warning in fresh["recognition_result"]["warnings"])


@pytest.mark.parametrize("operator_name", ["测试", "测试1、不存在", "测试2", ""])
def test_unmatched_partial_or_non_worker_operator_name_requires_manual_binding(setup, monkeypatch, operator_name):
    client, factory = setup
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": operator_name, "boxes": []})
    assert fresh["recognition_result"]["worker_ids"] == []
    assert fresh["recognition_result"]["warnings"]


def test_initial_mark_hint_does_not_make_draft_manual_but_review_save_does(setup):
    client, _ = setup
    response = client.post("/api/intakes", headers=headers(), data={"mark_hint": "ABC", "photos": (png(), "纸单.png")})
    record = response.json["data"]
    assert record["draft_is_manual"] is False
    updated = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(5, "clerk"), json={
        "version": record["version"], "draft": {"mark": "ABC", "boxes": [], "worker_ids": []},
    }).json["data"]
    assert updated["draft_is_manual"] is True


def test_unified_my_lists_include_manual_and_paper_once_with_private_paginated_metadata(setup):
    client, factory = setup
    pending = submit(client)
    submit(client, uid=3)
    confirmed = save_complete(client, submit(client), mark="OWN-PAPER", worker_ids=[3])
    confirmed = client.post(f"/api/intakes/{confirmed['uid']}/confirm", headers=headers(5, "clerk"), json={"version": confirmed["version"]}).json["data"]
    add_manual_list(factory, "own-manual", "MANUAL%_X")
    add_manual_list(factory, "other-manual", "OTHER", creator=3)
    add_manual_list(factory, "archived-manual", "ARCHIVED", archived=True)
    with factory() as session:
        row = session.query(IntakeTable).filter_by(uid=pending["uid"]).one()
        row.created_at = "2026-10-02T11:00:00"
        row.recognition_result_json = service.json.dumps({"mark": "AI-PENDING", "boxes": [{"box_number": 1}], "warnings": ["private"], "operator_name": "private"})
        session.query(PackingListTable).filter_by(uid=confirmed["packing_list_uid"]).one().create_date = "2026-10-02 09:00"
        session.commit()
    result = client.get("/api/intakes/my-packing-lists", headers=headers()).json["data"]
    assert result["total"] == 3
    assert [item["uid"] for item in result["items"]] == [pending["uid"], "own-manual", confirmed["uid"]]
    expected_keys = {"uid", "mark", "source", "status", "created_at", "box_count", "packing_list_uid"}
    assert all(set(item) == expected_keys for item in result["items"])
    assert result["items"][0]["status"] == "pending_review" and result["items"][0]["packing_list_uid"] is None
    assert result["items"][1]["source"] == "manual" and result["items"][1]["status"] == "draft"
    assert result["items"][2]["source"] == "paper" and result["items"][2]["box_count"] == 2
    assert client.get("/api/intakes/my-packing-lists?page=2&page_size=1", headers=headers()).json["data"]["items"][0]["uid"] == "own-manual"
    assert client.get("/api/intakes/my-packing-lists?mark=ai-pending", headers=headers()).json["data"]["total"] == 1
    literal = client.get("/api/intakes/my-packing-lists", query_string={"mark": "%_"}, headers=headers()).json["data"]
    assert literal["total"] == 1 and literal["items"][0]["uid"] == "own-manual"
    # A worker assigned to the boxes does not gain creator ownership.
    others = client.get("/api/intakes/my-packing-lists", headers=headers(3)).json["data"]
    assert confirmed["uid"] not in {item["uid"] for item in others["items"]}
    assert client.get("/api/intakes/my-packing-lists", headers=headers(4, "finance")).status_code == 403


def test_unified_my_lists_never_query_photo_metadata_or_bytes(setup):
    from sqlalchemy import event
    client, factory = setup
    submit(client)
    statements = []
    engine = factory.kw["bind"]
    def capture_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        assert client.get("/api/intakes/my-packing-lists", headers=headers()).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)
    assert not any("paper_intake_photos" in statement.lower() for statement in statements)


@pytest.mark.parametrize("role", ["worker", "employee"])
def test_legacy_packing_list_reads_are_scoped_to_worker_creator(setup, role):
    client, factory = setup
    add_manual_list(factory, "own", "OWN")
    add_manual_list(factory, "other", "OTHER", creator=3)
    own_headers = headers(1, role)
    result = client.get("/api/packing-lists?creator_id=3", headers=own_headers).json["data"]
    assert result["total"] == 1 and result["items"][0]["uid"] == "own"
    assert client.get("/api/packing-lists?q=OTHER", headers=own_headers).json["data"]["total"] == 0
    assert client.get("/api/packing-list/own", headers=own_headers).status_code == 200
    assert client.get("/api/packing-list/other", headers=own_headers).status_code == 403


def test_reviewer_multi_role_keeps_full_legacy_scope_while_my_lists_remain_own(setup):
    client, factory = setup
    add_manual_list(factory, "own", "OWN", creator=5)
    add_manual_list(factory, "other", "OTHER", creator=3)
    token = create_jwt({"user_id": 5, "role": "worker", "roles": ["clerk"]})
    reviewer_headers = {"x-token": token}
    assert client.get("/api/packing-lists", headers=reviewer_headers).json["data"]["total"] == 2
    assert client.get("/api/packing-list/other", headers=reviewer_headers).status_code == 200
    assert client.get("/api/intakes/my-packing-lists", headers=reviewer_headers).json["data"]["total"] == 1
    assert client.get("/api/packing-lists", headers=headers(4, "finance")).json["data"]["total"] == 2


def test_finance_worker_multi_role_keeps_existing_full_legacy_scope(setup):
    client, factory = setup
    add_manual_list(factory, "own", "OWN", creator=4)
    add_manual_list(factory, "other", "OTHER", creator=3)
    token = create_jwt({"user_id": 4, "role": "worker", "roles": ["finance"]})
    mixed_headers = {"x-token": token}
    assert client.get("/api/packing-lists", headers=mixed_headers).json["data"]["total"] == 2
    assert client.get("/api/packing-list/other", headers=mixed_headers).status_code == 200


def test_worker_pdf_exports_cannot_bypass_packing_list_ownership(setup, monkeypatch):
    client, factory = setup
    add_manual_list(factory, "other", "OTHER", creator=3)
    single_pdf = Mock()
    multi_pdf = Mock()
    monkeypatch.setattr(packing_controller, "build_packing_list_pdf", single_pdf)
    monkeypatch.setattr(packing_controller, "build_packing_lists_pdf", multi_pdf)
    assert client.get("/api/packing-list/other/pdf", headers=headers()).status_code == 403
    assert client.post("/api/packing-lists/pdf", headers=headers(), json={"selections": [{"packing_list_uid": "other"}]}).status_code == 403
    single_pdf.assert_not_called()
    multi_pdf.assert_not_called()


def test_malformed_worker_identity_cannot_disable_legacy_owner_filter(setup):
    client, factory = setup
    add_manual_list(factory, "other", "OTHER", creator=3)
    malformed_headers = {"x-token": create_jwt({"role": "worker"})}
    assert client.get("/api/packing-lists", headers=malformed_headers).json["data"]["total"] == 0
    assert client.get("/api/packing-list/other", headers=malformed_headers).status_code == 403


def test_authenticated_employee_can_create_manual_list_as_own_creator(setup, monkeypatch):
    client, factory = setup
    add_user(factory, 6, "员工甲", role="employee")
    # Keep the creation audit in the same isolated database as this test.
    monkeypatch.setattr(sys.modules["utils.log"], "SessionFactory", factory)
    response = client.post("/api/packing-list", headers=headers(6, "employee"), json={"mark": "employee-manual", "creator_id": 3})
    assert response.status_code == 200, response.json
    uid = response.json["data"]["uid"]
    with factory() as session:
        packing_list = session.query(PackingListTable).filter_by(uid=uid).one()
        assert packing_list.creator_id == 6
        assert packing_list.list_number == "EMPLOYEE-MANUAL"
        assert packing_list.status == "draft"
    assert client.get(f"/api/packing-list/{uid}", headers=headers(6, "employee")).status_code == 200
    assert client.post("/api/packing-list", json={"mark": "anonymous"}).status_code == 401
    assert client.post("/api/packing-list", headers=headers(4, "finance"), json={"mark": "finance"}).status_code == 403
