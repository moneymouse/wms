"""Run independently: pytest --confcutdir=tests/intake tests/intake.

Uses a minimal Flask application, never imports app.py or runs startup backups.
"""
import importlib.util
import hashlib
import json
import os
import sys
from io import BytesIO
from datetime import datetime
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
from data.DB import CargoTable, GoodsNameTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import PackingListTable, PackingListModel, BoxWorkerTable
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
        role_records = {name: RoleTable(name=name, label=name) for name in ("worker", "employee", "salesperson", "finance", "clerk", "admin", "store_manager")}
        session.add_all(role_records.values())
        for uid, role in ((1, "worker"), (2, "salesperson"), (3, "worker"), (4, "finance"), (5, "clerk")):
            session.add(UserTable(id=uid, name=f"测试{uid}", phone=f"1380000000{uid}", status="approved", password="unused", roles=[role_records[role]]))
        session.commit()
    yield app.test_client(), factory
    engine.dispose()


@pytest.fixture
def packing_date(monkeypatch):
    import data.packing.PackingList as packing_data
    monkeypatch.setattr(packing_data, "datetime", SimpleNamespace(now=lambda: datetime(2026, 10, 7, 12)))


def headers(uid=1, role="worker"):
    return {"x-token": create_jwt({"user_id": uid, "name": f"测试{uid}", "role": role})}


def png():
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    output.seek(0)
    return output


def assert_stored_png(photo):
    assert not Path(photo.storage_path).is_absolute()
    data = (Path(os.environ["PAPER_PHOTO_ROOT"]) / photo.storage_path).read_bytes()
    assert data.startswith(b"\x89PNG")
    assert photo.size_bytes == len(data)
    assert photo.sha256 == hashlib.sha256(data).hexdigest()
    assert "data" not in IntakePhotoTable.__table__.columns
    return data


def submit(client, uid=1):
    response = client.post("/api/intakes", headers=headers(uid), data={"photos": (png(), "纸单.png")})
    assert response.status_code == 201, response.json
    return response.json["data"]


def save_complete(client, record, mark="TEST-MARK", boxes=None, worker_ids=None, recognition_complete=True):
    if recognition_complete:
        with database.SessionFactory() as session:
            row = session.query(IntakeTable).filter_by(uid=record["uid"]).one()
            if row.recognition_status == "running":
                row.recognition_status = "succeeded"
                row.recognition_job_uid = None
                session.commit()
        record = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    boxes = boxes or [{"box_number": 7, "item_name": "鞋", "count": 3, "weight": 1.5}, {"box_number": 9, "item_name": "衣服", "count": 4, "weight": 2.25}]
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(), json={"version": record["version"], "draft": {"mark": mark, "worker_ids": [1] if worker_ids is None else worker_ids, "boxes": boxes}})
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
        assert_stored_png(session.query(IntakePhotoTable).one())
    assert client.get(record["photos"][0]["url"], headers=headers()).status_code == 200
    assert client.get(record["photos"][0]["url"], headers=headers(3)).status_code == 403
    assert client.get(record["photos"][0]["url"]).status_code == 401
    assert client.get(f"/api/intakes/{record['uid']}", headers=headers(3)).status_code == 403
    assert client.get("/api/intakes", headers=headers(3)).status_code == 410
    assert client.get("/api/intakes", headers=headers(2, "salesperson")).status_code == 410
    assert client.get(f"/api/intakes/{record['uid']}", headers=headers(2, "salesperson")).status_code == 403
    assert client.get(record["photos"][0]["url"], headers=headers(2, "salesperson")).status_code == 403
    own = client.get("/api/intakes/my-packing-lists", headers=headers()).json["data"]
    assert own["total"] == 1 and own["items"][0]["status"] == "uploading"


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


def test_invalid_photo_and_finance_role_rejected(setup, paper_photo_root):
    client, factory = setup
    response = client.post("/api/intakes", headers=headers(), data={"photos": (BytesIO(b"not a photo"), "fake.jpg")})
    assert response.status_code == 400
    assert client.post("/api/intakes", headers=headers(4, "finance"), data={"photos": (png(), "photo.png")}).status_code == 403
    assert client.get("/api/intakes", headers=headers(4, "finance")).status_code == 403
    with factory() as session:
        assert session.query(IntakeTable).count() == 0
    assert not list(paper_photo_root.rglob("*"))


def test_failed_upload_database_commit_removes_written_photos(setup, monkeypatch, paper_photo_root):
    from werkzeug.datastructures import FileStorage
    _, factory = setup

    def failing_factory():
        session = factory()
        session.commit = Mock(side_effect=RuntimeError("injected commit failure"))
        return session

    monkeypatch.setattr(database, "SessionFactory", failing_factory)
    with pytest.raises(RuntimeError, match="injected commit failure"):
        service.create_intake({"user_id": 1, "role": "worker"}, [FileStorage(png(), filename="source.png")], {})
    with factory() as session:
        assert session.query(IntakeTable).count() == 0
        assert session.query(IntakePhotoTable).count() == 0
    assert not [path for path in paper_photo_root.rglob("*") if path.is_file()]


def test_successful_upload_commit_with_lost_acknowledgement_keeps_photo_and_record(setup, monkeypatch, paper_photo_root):
    from werkzeug.datastructures import FileStorage
    client, factory = setup
    first_session = True

    def lost_ack_factory():
        nonlocal first_session
        session = factory()
        if first_session:
            first_session = False
            commit = session.commit

            def commit_then_lose_ack():
                commit()
                raise RuntimeError("commit acknowledgement lost")

            session.commit = commit_then_lose_ack
        return session

    monkeypatch.setattr(database, "SessionFactory", lost_ack_factory)
    with pytest.raises(RuntimeError, match="commit acknowledgement lost"):
        service.create_intake({"user_id": 1, "role": "worker"}, [FileStorage(png(), filename="source.png")], {})
    with factory() as session:
        source = session.query(IntakeTable).one()
        assert source.status == "pending"
        assert_stored_png(source.photos[0])
        record = service.serialize(source)
    assert len([path for path in paper_photo_root.rglob("*") if path.is_file()]) == 1
    response = client.get(record["photos"][0]["url"], headers=headers())
    assert response.status_code == 200
    assert response.data == png().getvalue()


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_upload_with_uncertain_commit_and_unavailable_database_preserves_file_and_original_error(setup, monkeypatch, paper_photo_root, commit_before_error):
    from werkzeug.datastructures import FileStorage
    _, factory = setup
    first_session = True

    def unavailable_after_upload():
        nonlocal first_session
        if not first_session:
            raise RuntimeError("database unavailable during verification")
        first_session = False
        session = factory()
        commit = session.commit

        def uncertain_commit():
            if commit_before_error:
                commit()
            raise RuntimeError("original upload commit error")

        session.commit = uncertain_commit
        return session

    monkeypatch.setattr(database, "SessionFactory", unavailable_after_upload)
    with pytest.raises(RuntimeError, match="original upload commit error"):
        service.create_intake({"user_id": 1, "role": "worker"}, [FileStorage(png(), filename="source.png")], {})
    files = [path for path in paper_photo_root.rglob("*") if path.is_file()]
    assert len(files) == 1
    assert files[0].read_bytes() == png().getvalue()
    with factory() as session:
        assert session.query(IntakeTable).count() == int(commit_before_error)
        assert session.query(IntakePhotoTable).count() == int(commit_before_error)
        if commit_before_error:
            assert_stored_png(session.query(IntakePhotoTable).one())


@pytest.mark.parametrize("fail_on_write", [1, 2])
def test_failed_upload_file_write_cleans_attempted_and_previously_written_photos(setup, monkeypatch, paper_photo_root, fail_on_write):
    from werkzeug.datastructures import FileStorage
    from services import paper_photo_storage
    _, factory = setup
    save_photo = paper_photo_storage.save_bytes
    written = 0

    def fail_after_write(*args, **kwargs):
        nonlocal written
        metadata = save_photo(*args, **kwargs)
        written += 1
        if written == fail_on_write:
            raise OSError("injected post-write failure")
        return metadata

    monkeypatch.setattr(paper_photo_storage, "save_bytes", fail_after_write)
    with pytest.raises(OSError, match="injected post-write failure"):
        service.create_intake({"user_id": 1, "role": "worker"}, [
            FileStorage(png(), filename="one.png"), FileStorage(png(), filename="two.png"),
        ], {})
    with factory() as session:
        assert session.query(IntakeTable).count() == 0
        assert session.query(IntakePhotoTable).count() == 0
    assert not [path for path in paper_photo_root.rglob("*") if path.is_file()]


def test_incomplete_draft_can_save_and_stale_write_is_rejected(setup):
    client, _ = setup
    record = submit(client)
    url = f"/api/intakes/{record['uid']}"
    draft = {"mark": "", "boxes": [{"box_number": None, "item_name": "", "count": None, "weight": None}]}
    response = client.put(url + "/draft", headers=headers(), json={"version": record["version"], "draft": draft})
    assert response.status_code == 200
    assert response.json["data"]["version"] == record["version"] + 1
    assert client.get(url, headers=headers()).json["data"]["draft"] == {**draft, "operator_name": "",
        "boxes": [{**draft["boxes"][0], "worker_ids": []}]}
    assert client.put(url + "/draft", headers=headers(), json={"version": record["version"], "draft": draft}).status_code == 409
    assert client.post(url + "/confirm", headers=headers(), json={"version": response.json["data"]["version"], "reviewed": True}).status_code == 409
    assert client.put(url + "/draft", headers=headers(2, "salesperson"), json={"version": 2, "draft": draft}).status_code == 403
    assert client.post(url + "/confirm", headers=headers(2, "salesperson"), json={"version": 2, "reviewed": True}).status_code == 403


def test_confirmation_creates_one_list_two_unassigned_boxes_and_retries(setup):
    client, factory = setup
    record = save_complete(client, submit(client))
    url = f"/api/intakes/{record['uid']}/confirm"
    response = client.post(url, headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    confirmed = response.json["data"]
    assert confirmed["status"] == "confirmed"
    source = client.get(f"/api/intakes?packing_list_uid={confirmed['packing_list_uid']}", headers=headers()).json["data"]
    assert source["total"] == 1 and source["items"][0]["uid"] == record["uid"]
    assert client.get(f"/api/intakes?packing_list_uid={confirmed['packing_list_uid']}", headers=headers(3)).status_code == 403
    assert client.get(f"/api/intakes/{record['uid']}", headers=headers(2, "salesperson")).status_code == 200
    assert client.get(confirmed["photos"][0]["url"], headers=headers(2, "salesperson")).status_code == 200
    assert client.post(url, headers=headers(2, "salesperson"), json={"version": confirmed["version"], "reviewed": True}).status_code == 403
    assert client.post(url, headers=headers(), json={"version": record["version"], "reviewed": True}).json["data"]["packing_list_uid"] == confirmed["packing_list_uid"]
    with factory() as session:
        assert session.query(PackingListTable).count() == 1
        assert session.query(PackingListTable).one().creator_id == 1
        assert session.query(IntakeTable).one().confirmed_by == 1
        assert_stored_png(session.query(IntakePhotoTable).one())
        boxes = session.query(CargoTable).order_by(CargoTable.box_number).all()
        assert [box.box_number for box in boxes] == [7, 9]
        assert [box.piece_count for box in boxes] == [3, 4]
        assert sum(box.weight for box in boxes) == 3.75
        assert all(box.status == 0 and box.target_order_uid is None and box.waybill_id == "" for box in boxes)
        assert {(row.box_uid, row.worker_id) for row in session.query(BoxWorkerTable)} == {(box.uid, 1) for box in boxes}
    assert client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(), json={"version": confirmed["version"], "draft": record["draft"]}).status_code == 409


def test_box_remarks_survive_draft_restore_clearing_and_confirmation(setup):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[
        {"box_number": 1, "item_name": "鞋", "count": 3, "weight": 1.5, "remark": "  易碎\n请轻放  "},
        {"box_number": 2, "item_name": "鞋", "count": 3, "weight": 1.5, "remark": "待清空"},
        {"box_number": 3, "item_name": "鞋", "count": 3, "weight": 1.5, "remark": None},
        {"box_number": 4, "item_name": "鞋", "count": 3, "weight": 1.5},
        {"box_number": 5, "item_name": "鞋", "count": 3, "weight": 1.5, "remark": "备" * 512},
    ])
    url = f"/api/intakes/{record['uid']}"
    restored = client.get(url, headers=headers()).json["data"]
    assert [box.get("remark") for box in restored["draft"]["boxes"]] == ["易碎\n请轻放", "待清空", "", None, "备" * 512]
    assert "remark" not in restored["draft"]["boxes"][3]
    restored["draft"]["boxes"][1]["remark"] = " \n "
    saved = client.put(url + "/draft", headers=headers(), json={"version": restored["version"], "draft": restored["draft"]})
    assert saved.status_code == 200, saved.json
    assert saved.json["data"]["draft"]["boxes"][1]["remark"] == ""
    response = client.post(url + "/confirm", headers=headers(), json={"version": saved.json["data"]["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    with factory() as session:
        boxes = session.query(CargoTable).order_by(CargoTable.box_number).all()
        assert [box.remark for box in boxes] == ["易碎\n请轻放", None, None, None, "备" * 512]
        assert session.query(PackingListTable).count() == 1
    confirmed = client.get(url, headers=headers()).json["data"]
    assert confirmed["draft"]["boxes"] == saved.json["data"]["draft"]["boxes"]


@pytest.mark.parametrize("remark", ["备" * 513, 123, True, [], {}])
def test_invalid_box_remark_rejects_entire_draft_without_advancing_version(setup, remark):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[
        {"box_number": 1, "item_name": "鞋", "count": 3, "weight": 1.5, "remark": "原备注"},
        {"box_number": 2, "item_name": "鞋", "count": 3, "weight": 1.5},
    ])
    modified = json.loads(json.dumps(record["draft"]))
    modified["boxes"][0]["remark"] = "不应部分保存"
    modified["boxes"][1]["remark"] = remark
    url = f"/api/intakes/{record['uid']}"
    response = client.put(url + "/draft", headers=headers(), json={"version": record["version"], "draft": modified})
    assert response.status_code == 400
    assert "第2行备注" in response.json["msg"]
    restored = client.get(url, headers=headers()).json["data"]
    assert restored["version"] == record["version"]
    assert restored["draft"] == record["draft"]
    with factory() as session:
        assert session.query(CargoTable).count() == 0


def test_multiple_goods_survive_draft_restore_and_confirmation(setup):
    client, factory = setup
    details = [
        {"item_name": " 衣服 ", "piece_count": "2", "customs_code": "610910"},
        {"item_name": "鞋子", "piece_count": 5},
    ]
    record = save_complete(client, submit(client), boxes=[
        {"box_number": 1, "item_name": "旧品名", "count": 99, "weight": 3, "worker_ids": [1, 3], "item_details": details},
        {"box_number": 2, "item_name": "帽子", "count": 4, "weight": 2, "worker_ids": [3]},
    ])
    url = f"/api/intakes/{record['uid']}"
    restored = client.get(url, headers=headers()).json["data"]
    expected = [
        {"item_name": "衣服", "piece_count": 2, "customs_code": "610910"},
        {"item_name": "鞋子", "piece_count": 5, "customs_code": ""},
    ]
    multi = restored["draft"]["boxes"][0]
    assert multi["item_details"] == expected
    assert multi["item_name"] == "衣服、鞋子"
    assert multi["count"] == multi["piece_count"] == 7
    assert multi["worker_ids"] == [1, 3]
    # Existing single-name clients retain their original draft shape.
    assert "item_details" not in restored["draft"]["boxes"][1]
    response = client.post(url + "/confirm", headers=headers(), json={"version": restored["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    with factory() as session:
        boxes = session.query(CargoTable).order_by(CargoTable.box_number).all()
        assert len(boxes) == 2
        assert boxes[0].item_name == boxes[0].real_en_name == "衣服、鞋子"
        assert boxes[0].count == boxes[0].piece_count == 7
        assert json.loads(boxes[0].item_details) == expected
        assert json.loads(boxes[1].item_details) == [{"item_name": "帽子", "piece_count": 4, "customs_code": ""}]
        assert {(worker.box_uid, worker.worker_id) for worker in session.query(BoxWorkerTable)} == {
            (boxes[0].uid, 1), (boxes[0].uid, 3), (boxes[1].uid, 3),
        }


def test_parsed_recognition_candidate_confirms_as_one_box_with_independent_goods(setup, monkeypatch):
    from services import intake_recognition as recognition

    client, factory = setup
    record = submit(client)
    content = json.dumps({
        "mark": "MIXED-PAPER", "operator_name": "测试1",
        "boxes": [{
            "box_number": 1, "count": 7, "weight": 3,
            "item_details": [{"item_name": "衣服", "piece_count": "02"}, {"item_name": "鞋子", "piece_count": 5.0}],
        }],
    }, ensure_ascii=False)
    monkeypatch.setattr(recognition, "recognize_paper_photos", lambda *args, **kwargs: recognition._parse_result(content, "mock-model"))
    with factory() as session:
        job_uid = session.query(IntakeTable).filter_by(uid=record["uid"]).one().recognition_job_uid
    service.run_recognition(record["uid"], job_uid, [], "")
    record = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    assert record["recognition_status"] == "succeeded"
    assert record["draft"]["boxes"] == []
    expected = [
        {"item_name": "衣服", "piece_count": 2, "customs_code": ""},
        {"item_name": "鞋子", "piece_count": 5, "customs_code": ""},
    ]
    candidate = record["recognition_result"]
    assert candidate["boxes"][0]["item_details"] == expected
    record = save_complete(client, record, mark=candidate["mark"], boxes=candidate["boxes"])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    with factory() as session:
        box = session.query(CargoTable).one()
        assert box.count == box.piece_count == 7
        assert box.item_name == "衣服、鞋子"
        assert json.loads(box.item_details) == expected
        assert session.query(BoxWorkerTable).one().worker_id == 1


@pytest.mark.parametrize("paper_total", [None, 7])
def test_missing_per_item_quantity_saves_but_requires_correction_before_confirmation(setup, paper_total):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[{
        "box_number": 1, "count": paper_total, "weight": 3,
        "item_details": [{"item_name": "衣服", "piece_count": 2}, {"item_name": "鞋子"}],
    }])
    url = f"/api/intakes/{record['uid']}"
    restored = client.get(url, headers=headers()).json["data"]
    box = restored["draft"]["boxes"][0]
    assert box["item_name"] == "衣服、鞋子"
    assert box["count"] == box["piece_count"] == paper_total
    assert box["item_details"][1]["piece_count"] is None
    response = client.post(url + "/confirm", headers=headers(), json={"version": restored["version"], "reviewed": True})
    assert response.status_code == 400 and "第2个品名件数须为正整数" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0
        assert session.query(IntakeTable).one().status == "pending"
    box["item_details"][1]["piece_count"] = 5
    saved = client.put(url + "/draft", headers=headers(), json={"version": restored["version"], "draft": restored["draft"]})
    assert saved.status_code == 200, saved.json
    saved = saved.json["data"]
    assert saved["draft"]["boxes"][0]["count"] == 7
    response = client.post(url + "/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    with factory() as session:
        box = session.query(CargoTable).one()
        assert [detail["piece_count"] for detail in json.loads(box.item_details)] == [2, 5]


@pytest.mark.parametrize("separator", ["、", "，", ",", "；", ";", "\n"])
def test_legacy_multiple_names_keep_total_without_guessing_item_quantities(setup, separator):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[{
        "box_number": 1, "item_name": f"衣服{separator}鞋子", "count": 7, "weight": 3,
    }])
    box = record["draft"]["boxes"][0]
    assert box["item_name"] == "衣服、鞋子" and box["count"] == 7
    assert box["item_details"] == [
        {"item_name": "衣服", "piece_count": None, "customs_code": ""},
        {"item_name": "鞋子", "piece_count": None, "customs_code": ""},
    ]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400
    with factory() as session:
        assert session.query(CargoTable).count() == 0


def test_explicit_empty_item_details_never_falls_back_to_legacy_summary(setup):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[{
        "box_number": 1, "item_name": "鞋子", "count": 7, "weight": 3, "item_details": [],
    }])
    box = record["draft"]["boxes"][0]
    assert box["item_details"] == [] and box["item_name"] == ""
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400 and "至少填写一种品名" in response.json["msg"]
    with factory() as session:
        assert session.query(CargoTable).count() == 0


@pytest.mark.parametrize("details", [None, "[]", {}, ["鞋子"], [{"item_name": "鞋子", "piece_count": True}], [{"item_name": "鞋子", "piece_count": []}]])
def test_malformed_item_details_are_rejected_without_advancing_draft(setup, details):
    client, _ = setup
    record = submit(client)
    url = f"/api/intakes/{record['uid']}"
    response = client.put(url + "/draft", headers=headers(), json={"version": record["version"], "draft": {
        "mark": "TEST", "worker_ids": [1], "boxes": [{
            "box_number": 1, "item_name": "鞋子", "count": 7, "weight": 3, "item_details": details,
        }],
    }})
    assert response.status_code == 400
    restored = client.get(url, headers=headers()).json["data"]
    assert restored["version"] == record["version"] and restored["draft"] == record["draft"]


@pytest.mark.parametrize("detail", [
    {"item_name": "", "piece_count": 1}, {"item_name": "鞋子", "piece_count": 0},
    {"item_name": "鞋子", "piece_count": -1}, {"item_name": "鞋子", "piece_count": 1.5},
    {"item_name": "鞋子", "piece_count": "02"}, {"item_name": "鞋子", "piece_count": 2147483648},
])
def test_each_item_requires_a_name_and_positive_integer_quantity_before_confirmation(setup, detail):
    client, factory = setup
    record = save_complete(client, submit(client), boxes=[{
        "box_number": 1, "count": 9, "weight": 3, "item_details": [detail],
    }])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == 0


def test_item_details_preserve_existing_summary_and_total_bounds():
    box = {"box_number": 1, "weight": 3, "item_details": [
        {"item_name": "鞋子", "piece_count": 2147483647}, {"item_name": "衣服", "piece_count": 1},
    ]}
    with pytest.raises(service.IntakeError, match="件数须为正整数"):
        service.normalize_draft({"mark": "TEST", "boxes": [box]}, complete=True)
    box["item_details"] = [{"item_name": "鞋" * 128, "piece_count": 1}, {"item_name": "衣" * 128, "piece_count": 1}]
    with pytest.raises(service.IntakeError, match="不超过256字"):
        service.normalize_draft({"mark": "TEST", "boxes": [box]})


def test_draft_limits_each_box_to_one_hundred_item_details():
    details = [{"item_name": "鞋", "piece_count": 1}] * 100
    draft = {"mark": "TEST", "boxes": [{"box_number": 1, "weight": 3, "item_details": details}]}
    result = service.normalize_draft(draft)
    assert len(result["boxes"][0]["item_details"]) == 100
    assert result["boxes"][0]["count"] == 100
    draft["boxes"][0]["item_details"] = details + [{"item_name": "衣", "piece_count": 1}]
    with pytest.raises(service.IntakeError, match="每箱最多100个品名"):
        service.normalize_draft(draft)


@pytest.mark.parametrize("reviewed", [None, False, 1, "true", [], {}])
def test_confirm_requires_explicit_uploader_check_before_creating_inventory(setup, reviewed):
    client, factory = setup
    record = save_complete(client, submit(client))
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": reviewed})
    assert response.status_code == 400 and "检查" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == 0
        assert session.query(IntakeTable).one().status == "pending"


def test_running_recognition_must_finish_before_uploader_can_complete(setup):
    client, factory = setup
    record = save_complete(client, submit(client), recognition_complete=False)
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 409 and "识别尚未完成" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == 0


def test_failed_recognition_allows_checked_manual_completion(setup):
    client, factory = setup
    record = save_complete(client, submit(client), recognition_complete=False)
    with factory() as session:
        session.query(IntakeTable).one().recognition_status = "failed"
        session.commit()
    record = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200 and response.json["data"]["status"] == "confirmed"


@pytest.mark.parametrize("role", sorted(service.SUBMIT_ROLES))
def test_every_upload_role_can_check_and_complete_own_paper(setup, monkeypatch, role):
    client, factory = setup
    add_user(factory, 6, "上传人员", role=role)
    identity = headers(6, role)
    record = client.post("/api/intakes", headers=identity, data={"photos": (png(), "纸单.png")}).json["data"]
    assert client.get("/api/intakes/workers", headers=identity).status_code == 200
    with factory() as session:
        job_uid = session.query(IntakeTable).filter_by(uid=record["uid"]).one().recognition_job_uid
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=lambda *args, **kwargs: {"mark": "OWN", "boxes": []}))
    service.run_recognition(record["uid"], job_uid, [], "")
    record = client.get(f"/api/intakes/{record['uid']}", headers=identity).json["data"]
    draft = {"mark": "OWN", "worker_ids": [1], "boxes": [{"box_number": 1, "item_name": "衣服", "count": 2, "weight": 3}]}
    saved = client.put(f"/api/intakes/{record['uid']}/draft", headers=identity, json={"version": record["version"], "draft": draft})
    assert saved.status_code == 200
    confirmed = client.post(f"/api/intakes/{record['uid']}/confirm", headers=identity, json={"version": saved.json["data"]["version"], "reviewed": True})
    assert confirmed.status_code == 200
    assert confirmed.json["data"]["confirmed_by"] == 6
    with factory() as session:
        assert session.query(PackingListTable).one().creator_id == 6
        assert session.query(BoxWorkerTable).one().worker_id == 1


@pytest.mark.parametrize("role", sorted(service.SUBMIT_ROLES))
@pytest.mark.parametrize("confirmed", [False, True])
def test_other_users_never_edit_uploads_and_only_staff_read_completed_photos(setup, role, confirmed):
    client, factory = setup
    record = submit(client)
    if confirmed:
        record = save_complete(client, record)
        record = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True}).json["data"]
    add_user(factory, 6, "其他人员", role=role)
    identity = headers(6, role)
    readable = confirmed and role in service.STAFF_READ_ROLES
    assert client.get(f"/api/intakes/{record['uid']}", headers=identity).status_code == (200 if readable else 403)
    assert client.get(record["photos"][0]["url"], headers=identity).status_code == (200 if readable else 403)
    assert client.put(f"/api/intakes/{record['uid']}/draft", headers=identity, json={"version": record["version"], "draft": {"mark": "OTHER", "boxes": []}}).status_code == 403
    assert client.post(f"/api/intakes/{record['uid']}/recognize", headers=identity, json={"version": record["version"]}).status_code == 403
    assert client.post(f"/api/intakes/{record['uid']}/confirm", headers=identity, json={"version": record["version"], "reviewed": True}).status_code == 403


@pytest.mark.parametrize("changes", [{"box_number": 0}, {"box_number": "02"}, {"box_number": "A1"}, {"count": 1.5}, {"count": -1}, {"weight": 0}, {"weight": "nan"}, {"item_name": ""}])
def test_confirmation_validates_business_fields(setup, changes):
    client, factory = setup
    box = {"box_number": 1, "item_name": "鞋", "count": 1, "weight": 1}
    box.update(changes)
    record = save_complete(client, submit(client), boxes=[box])
    assert client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True}).status_code == 400
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(CargoTable).count() == 0
        assert session.query(BoxWorkerTable).count() == 0


def test_duplicate_box_numbers_remain_explicit_conflicts(setup):
    client, factory = setup
    box = {"box_number": 4, "item_name": "鞋", "count": 1, "weight": 1}
    record = save_complete(client, submit(client), boxes=[box, box])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400 and "重复" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == 0


@pytest.mark.parametrize("archived", [False, True])
def test_existing_mark_uses_manual_date_and_serial_suffix_including_archived_lists(setup, packing_date, archived):
    client, factory = setup
    for index, mark in enumerate(("TEST-MARK", "TEST-MARK-20261007", "TEST-MARK-20261007-2")):
        add_manual_list(factory, f"existing-{index}", mark, archived=archived)
    record = save_complete(client, submit(client), mark=" test-mark ")
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    final = response.json["data"]
    assert final["draft"]["mark"] == final["display_name"] == "TEST-MARK-20261007-3"
    assert final["photos"][0]["filename"].startswith("TEST-MARK-20261007-3-")
    with factory() as session:
        packing = session.query(PackingListTable).filter_by(uid=final["packing_list_uid"]).one()
        assert packing.list_number == final["draft"]["mark"]
        assert {box.tag for box in packing.boxes} == {"TEST-MARK-20261007-3_7", "TEST-MARK-20261007-3_9"}
        # Both entry points share the exact same allocation rule.
        manual = PackingListModel().create(creator_id=1, mark=" test-mark ", session=session)
        assert manual["mark"] == "TEST-MARK-20261007-4"


def test_recognition_previews_renamed_mark_and_confirmation_rechecks_new_collision(setup, monkeypatch, packing_date):
    client, factory = setup
    add_manual_list(factory, "existing", "PAPER-MARK")
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": " paper-mark ", "operator_name": "测试1", "boxes": []})
    assert fresh["recognition_result"]["mark"] == fresh["display_name"] == "PAPER-MARK-20261007"
    assert fresh["recognition_result"]["original_mark"] == "PAPER-MARK"
    assert any("已自动改为PAPER-MARK-20261007" in warning for warning in fresh["recognition_result"]["warnings"])
    assert fresh["draft"] == {"mark": "", "boxes": []}
    with factory() as session:
        assert session.query(CargoTable).count() == 0
    add_manual_list(factory, "new-collision", fresh["recognition_result"]["mark"])
    saved = save_complete(client, fresh, mark=fresh["recognition_result"]["mark"])
    response = client.post(f"/api/intakes/{fresh['uid']}/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    assert response.json["data"]["draft"]["mark"] == "PAPER-MARK-20261007-2"


def test_confirmation_respects_user_mark_correction_after_automatic_rename(setup, monkeypatch, packing_date):
    client, factory = setup
    add_manual_list(factory, "existing", "PAPER-MARK")
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "PAPER-MARK", "boxes": []})
    add_manual_list(factory, "corrected-existing", "CORRECTED")
    saved = save_complete(client, fresh, mark="corrected")
    response = client.post(f"/api/intakes/{fresh['uid']}/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    assert response.json["data"]["draft"]["mark"] == "CORRECTED-20261007"


def test_renamed_recognition_preserves_an_available_preview_after_day_changes(setup, monkeypatch, packing_date):
    client, factory = setup
    add_manual_list(factory, "existing", "PAPER-MARK")
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "PAPER-MARK", "boxes": []})
    saved = save_complete(client, fresh, mark=fresh["recognition_result"]["mark"])
    import data.packing.PackingList as packing_data
    monkeypatch.setattr(packing_data, "datetime", SimpleNamespace(now=lambda: datetime(2026, 10, 8, 12)))
    response = client.post(f"/api/intakes/{fresh['uid']}/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    assert response.json["data"]["draft"]["mark"] == "PAPER-MARK-20261007"


def test_renamed_long_mark_fits_the_same_limit_as_manual_creation(setup, monkeypatch, packing_date):
    client, factory = setup
    original = "M" * 64
    add_manual_list(factory, "existing", original)
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": original, "boxes": []})
    candidate_mark = fresh["recognition_result"]["mark"]
    assert candidate_mark == "M" * 55 + "-20261007"
    add_manual_list(factory, "existing-date", candidate_mark, archived=True)
    saved = save_complete(client, fresh, mark=candidate_mark)
    response = client.post(f"/api/intakes/{fresh['uid']}/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    assert response.json["data"]["draft"]["mark"] == "M" * 53 + "-20261007-2"


def test_simultaneous_mark_claim_retries_without_partial_boxes(setup, monkeypatch, packing_date):
    client, factory = setup
    saved = save_complete(client, submit(client))
    original = PackingListModel._generate_unique_list_number
    calls = []

    def claim_after_lookup(self, mark, session):
        candidate = original(self, mark, session)
        calls.append(candidate)
        if len(calls) == 1:
            add_manual_list(factory, "concurrent", candidate)
        return candidate

    monkeypatch.setattr(PackingListModel, "_generate_unique_list_number", claim_after_lookup)
    response = client.post(f"/api/intakes/{saved['uid']}/confirm", headers=headers(), json={"version": saved["version"], "reviewed": True})
    assert response.status_code == 200, response.json
    assert calls == ["TEST-MARK", "TEST-MARK-20261007"]
    assert response.json["data"]["draft"]["mark"] == "TEST-MARK-20261007"
    with factory() as session:
        assert session.query(PackingListTable).count() == 2
        assert session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 2


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
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
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
    response = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": record["version"]})
    assert response.status_code == 202
    running = response.json["data"]
    assert running["recognition_status"] == "running"
    record = save_complete(client, running, recognition_complete=False)
    with database.SessionFactory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    candidate = {"mark": "AI", "boxes": [{"box_number": 99, "item_name": "AI", "count": 1, "weight": 1}]}
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=lambda *args, **kwargs: candidate))
    service.run_recognition(record["uid"], job, [], "")
    refreshed = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    assert refreshed["draft"] == record["draft"]
    assert refreshed["recognition_result"]["mark"] == candidate["mark"]
    assert refreshed["recognition_result"]["boxes"] == [{**candidate["boxes"][0], "worker_ids": []}]
    assert refreshed["recognition_result"]["worker_ids"] == []
    assert refreshed["recognition_status"] == "succeeded"


def test_recognition_failure_and_restart_timeout_allow_retry(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: Mock())
    started = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": record["version"]}).json["data"]
    with factory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    def unavailable(*args, **kwargs):
        raise ValueError("DeepSeek密钥未配置")
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=unavailable))
    service.run_recognition(record["uid"], job, [], "")
    failed = service.get_intake({"user_id": 1, "role": "worker"}, record["uid"])
    assert failed["recognition_status"] == "failed"
    assert "未配置" in failed["recognition_error"]
    retry = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": failed["version"]})
    assert retry.status_code == 202
    with factory() as session:
        session.query(IntakeTable).one().recognition_started_at = "2000-01-01T00:00:00"
        session.commit()
    assert service.get_intake({"user_id": 1, "role": "worker"}, record["uid"])["recognition_status"] == "failed"


def test_recognition_uses_current_chinese_and_english_goods_names_on_each_attempt(setup, monkeypatch):
    client, factory = setup
    with factory() as session:
        session.add_all([
            GoodsNameTable(name="Laser pointer", lang="en"),
            GoodsNameTable(name="激光笔", lang="cn"),
            GoodsNameTable(name="Ignored", lang="fr"),
            GoodsNameTable(name="防水背包", lang="cn"),
        ])
        session.commit()
    provider = Mock(return_value={"mark": "TEST", "operator_name": "测试1", "boxes": []})
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    record = submit(client)
    with factory() as session:
        job_uid = session.query(IntakeTable).one().recognition_job_uid
    service.run_recognition(record["uid"], job_uid, [], "")
    assert provider.call_args.kwargs["goods_name_hints"] == ["激光笔", "防水背包", "Laser pointer"]
    finished = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    with factory() as session:
        session.add(GoodsNameTable(name="保温饭盒", lang="cn"))
        session.commit()
    response = client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": finished["version"]})
    assert response.status_code == 202
    with factory() as session:
        job_uid = session.query(IntakeTable).one().recognition_job_uid
    service.run_recognition(record["uid"], job_uid, [], "")
    assert provider.call_count == 2
    assert provider.call_args.kwargs["goods_name_hints"] == ["激光笔", "防水背包", "保温饭盒", "Laser pointer"]


def test_recognition_goods_name_hints_prioritize_chinese_with_a_bounded_query(setup, monkeypatch):
    client, factory = setup
    with factory() as session:
        session.add(GoodsNameTable(name="English goods", lang="en"))
        session.add_all(GoodsNameTable(name=f"商品{index}", lang="cn") for index in range(401))
        session.commit()
    provider = Mock(return_value={"mark": "TEST", "boxes": []})
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    record = submit(client)
    with factory() as session:
        job_uid = session.query(IntakeTable).one().recognition_job_uid
    service.run_recognition(record["uid"], job_uid, [], "")
    assert provider.call_args.kwargs["goods_name_hints"] == [f"商品{index}" for index in range(400)]


def test_goods_catalogue_query_failure_records_failed_recognition(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        job_uid = session.query(IntakeTable).one().recognition_job_uid
    first_session = True

    def fail_catalogue_query_once():
        nonlocal first_session
        session = factory()
        if first_session:
            first_session = False
            query = session.query

            def query_with_unavailable_catalogue(*entities, **kwargs):
                if entities and entities[0] is GoodsNameTable.name:
                    raise RuntimeError("goods catalogue unavailable")
                return query(*entities, **kwargs)

            session.query = query_with_unavailable_catalogue
        return session

    provider = Mock()
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    monkeypatch.setattr(database, "SessionFactory", fail_catalogue_query_once)
    service.run_recognition(record["uid"], job_uid, [], "")
    provider.assert_not_called()
    with factory() as session:
        row = session.query(IntakeTable).one()
        assert row.recognition_status == "failed"
        assert row.recognition_error == "goods catalogue unavailable"
        assert row.recognition_result_json is None


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
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 409
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(CargoTable).count() == 0
        assert session.query(IntakeTable).one().version == newer["version"]


def test_metadata_serialization_does_not_read_photo_bytes(setup, monkeypatch):
    from services import paper_photo_storage
    client, factory = setup
    record = submit(client)
    read_photo = Mock(side_effect=AssertionError("Metadata must not read the photograph"))
    monkeypatch.setattr(paper_photo_storage, "read_bytes", read_photo)
    with factory() as session:
        intake = session.query(IntakeTable).filter_by(uid=record["uid"]).one()
        assert service.serialize(intake)["photos"][0]["uid"] == record["photos"][0]["uid"]
    read_photo.assert_not_called()


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


def test_multiple_roles_can_check_only_their_own_upload(setup):
    client, _ = setup
    record = submit(client, uid=5)
    token = create_jwt({"user_id": 5, "name": "文员", "role": "worker", "roles": ["clerk"]})
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers={"x-token": token}, json={"version": record["version"], "draft": {"mark": "", "boxes": []}})
    assert response.status_code == 200


def test_worker_upload_starts_recognition_and_can_resume_own_check(setup, monkeypatch):
    client, factory = setup
    calls = []
    thread = Mock()
    def capture_thread(**kwargs):
        # Photos and job metadata are durable before the thread starts.
        with factory() as session:
            row = session.query(IntakeTable).one()
            assert row.recognition_status == "running"
            assert row.recognition_job_uid == kwargs["args"][1]
            assert_stored_png(row.photos[0])
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
    assert client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": record["version"]}).status_code == 202
    with factory() as session:
        assert session.query(CargoTable).count() == 0


def test_thread_start_failure_does_not_lose_uploaded_photo(setup, monkeypatch):
    client, factory = setup
    thread = Mock()
    thread.start.side_effect = RuntimeError("injected start failure")
    monkeypatch.setattr(service.threading, "Thread", lambda **kwargs: thread)
    record = submit(client)
    assert record["recognition_status"] == "failed"
    assert "照片已暂存" in record["recognition_error"]
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
    fresh = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    assert fresh["display_name"] == "ABC-2026"
    assert fresh["operator_name"] == "张三"
    assert fresh["submitted_by_name"] == "测试1"
    assert fresh["photos"][0]["filename"] == "ABC-2026-01.png"
    assert fresh["photos"][0]["original_filename"] == "纸单.png"
    assert fresh["draft"] == record["draft"]
    found = client.get("/api/intakes/my-packing-lists?mark=abc-2026", headers=headers()).json["data"]
    assert found["total"] == 1
    assert client.get("/api/intakes/my-packing-lists?mark=ABC-2026", headers=headers(3)).json["data"]["total"] == 0
    image = client.get(fresh["photos"][0]["url"], headers=headers())
    assert "ABC-2026-01.png" in image.headers["Content-Disposition"]
    # A corrected saved mark and operator override the AI candidate.
    updated = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(), json={"version": fresh["version"], "draft": {"mark": "FIXED", "operator_name": "李四", "boxes": []}}).json["data"]
    assert updated["display_name"] == "FIXED"
    assert updated["operator_name"] == "李四"
    assert updated["photos"][0]["filename"] == "FIXED-01.png"
    assert client.get("/api/intakes/my-packing-lists?mark=FIXED", headers=headers()).json["data"]["total"] == 1
    confirmed = save_complete(client, updated, mark="FIXED")
    assert confirmed["draft"]["operator_name"] == ""
    assert confirmed["operator_name"] == ""


def test_mark_search_escapes_wildcards_and_filenames_are_safe(setup):
    client, _ = setup
    first = save_complete(client, submit(client), mark="AB%_C/仓库")
    save_complete(client, submit(client), mark="ABXYC")
    found = client.get("/api/intakes/my-packing-lists", query_string={"mark": "%_"}, headers=headers()).json["data"]
    assert found["total"] == 1 and found["items"][0]["uid"] == first["uid"]
    assert "/" not in first["photos"][0]["filename"]
    assert first["photos"][0]["filename"].endswith("-01.png")


def test_own_detail_expires_abandoned_recognition_and_allows_uploader_retry(setup):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        session.query(IntakeTable).one().recognition_started_at = "2000-01-01T00:00:00"
        session.commit()
    fresh = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    assert fresh["recognition_status"] == "failed"
    assert client.post(f"/api/intakes/{record['uid']}/recognize", headers=headers(), json={"version": fresh["version"]}).status_code == 202


def test_upload_total_limit_matches_recognition_limit(setup, monkeypatch, paper_photo_root):
    from werkzeug.datastructures import FileStorage
    client, factory = setup
    monkeypatch.setattr(service, "MAX_TOTAL_PHOTO_BYTES", len(png().getvalue()))
    with pytest.raises(service.IntakeError, match="24MB"):
        service.create_intake({"user_id": 1, "role": "worker"}, [FileStorage(png(), filename="one.png"), FileStorage(png(), filename="two.png")], {})
    with factory() as session:
        assert session.query(IntakeTable).count() == 0
    assert not [path for path in paper_photo_root.rglob("*") if path.is_file()]


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
    return client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]


def add_manual_list(factory, uid, mark, creator=1, status="draft", created_at="2026-10-02 10:00", archived=False):
    with factory() as session:
        session.add(PackingListTable(uid=uid, list_number=mark, creator_id=creator, status=status, create_date=created_at, archive=archived, photos="[]"))
        session.commit()


def test_workers_endpoint_returns_only_approved_worker_accounts_to_uploaders(setup):
    client, factory = setup
    add_user(factory, 6, "员工甲", role="employee")
    add_user(factory, 7, "待批准", status="pending")
    add_user(factory, 8, "已拒绝", status="rejected")
    response = client.get("/api/intakes/workers", headers=headers())
    assert response.status_code == 200
    assert {worker["id"] for worker in response.json["data"]} == {1, 3, 6}
    assert all(set(worker) == {"id", "name"} for worker in response.json["data"])
    assert client.get("/api/intakes/workers", headers=headers()).status_code == 200
    assert client.get("/api/intakes/workers", headers=headers(4, "finance")).status_code == 403


@pytest.mark.parametrize("worker_ids", [[2], [4], [999], [True], ["1"], [0], [-1], [10 ** 30], None, {"id": 1}, [1, 3, 6, 7, 8]])
def test_draft_rejects_non_worker_or_invalid_worker_bindings(setup, worker_ids):
    client, factory = setup
    record = submit(client)
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(), json={
        "version": record["version"], "draft": {"mark": "ABC", "boxes": [], "worker_ids": worker_ids},
    })
    assert response.status_code == 400
    with factory() as session:
        assert "worker_ids" not in service.json.loads(session.query(IntakeTable).one().draft_json)


def test_legacy_global_workers_are_deduplicated_and_seed_only_missing_box_assignments(setup):
    client, factory = setup
    record = save_complete(client, submit(client), worker_ids=[3, 1, 3])
    assert "worker_ids" not in record["draft"]
    assert all(box["worker_ids"] == [3, 1] for box in record["draft"]["boxes"])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200
    with factory() as session:
        boxes = session.query(CargoTable).all()
        assert {(worker.box_uid, worker.worker_id) for worker in session.query(BoxWorkerTable)} == {(box.uid, uid) for box in boxes for uid in (1, 3)}
        assert session.query(PackingListTable).one().creator_id == 1
        assert session.query(IntakeTable).one().confirmed_by == 1


def test_empty_worker_selection_can_save_but_cannot_confirm(setup):
    client, factory = setup
    record = save_complete(client, submit(client), worker_ids=[])
    assert all(box["worker_ids"] == [] for box in record["draft"]["boxes"])
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400 and "至少选择" in response.json["msg"]
    with factory() as session:
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0


def test_each_box_binds_its_own_workers_without_global_overwrite(setup):
    client, factory = setup
    boxes = [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5, "worker_ids": [3, 3]},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": [1]},
    ]
    record = save_complete(client, submit(client), boxes=boxes, worker_ids=[2])
    assert "worker_ids" not in record["draft"]
    assert [box["worker_ids"] for box in record["draft"]["boxes"]] == [[3], [1]]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(),
        json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200
    with factory() as session:
        assigned = {box.box_number: sorted(worker.worker_id for worker in session.query(BoxWorkerTable).filter_by(box_uid=box.uid))
            for box in session.query(CargoTable)}
        assert assigned == {1: [3], 2: [1]}
        assert session.query(PackingListTable).one().creator_id == 1
        assert session.query(IntakeTable).one().confirmed_by == 1


def test_missing_box_workers_inherit_legacy_but_explicit_empty_selection_blocks_confirmation(setup):
    client, factory = setup
    boxes = [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": []},
    ]
    record = save_complete(client, submit(client), boxes=boxes, worker_ids=[3])
    assert [box["worker_ids"] for box in record["draft"]["boxes"]] == [[3], []]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(),
        json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400 and "第2行" in response.json["msg"]
    with factory() as session:
        assert session.query(IntakeTable).one().status == "pending"
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0


@pytest.mark.parametrize("worker_ids", [[2], [4], [999], [True], ["1"], [0], [-1], None, {"id": 1}, [1, 3, 6, 7, 8]])
def test_invalid_worker_assignment_in_one_box_rejects_entire_draft_without_partial_update(setup, worker_ids):
    client, factory = setup
    record = submit(client)
    boxes = [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5, "worker_ids": [1]},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": worker_ids},
    ]
    response = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(),
        json={"version": record["version"], "draft": {"mark": "BOX-WORKERS", "worker_ids": [1], "boxes": boxes}})
    assert response.status_code == 400 and "第2行" in response.json["msg"]
    with factory() as session:
        source = session.query(IntakeTable).one()
        assert source.version == record["version"]
        assert service.json.loads(source.draft_json) == record["draft"]
        assert session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0


def test_four_workers_limit_is_per_box_instead_of_entire_paper(setup):
    client, factory = setup
    for uid in (6, 7, 8):
        add_user(factory, uid, f"测试{uid}")
    boxes = [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5, "worker_ids": [1, 3, 6, 7]},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": [8]},
    ]
    record = save_complete(client, submit(client), boxes=boxes)
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200
    with factory() as session:
        assert session.query(BoxWorkerTable).count() == 5


def test_revoked_worker_in_second_box_prevents_any_inventory_creation(setup):
    client, factory = setup
    boxes = [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5, "worker_ids": [1]},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": [3]},
    ]
    record = save_complete(client, submit(client), boxes=boxes)
    with factory() as session:
        session.get(UserTable, 3).status = "rejected"
        session.commit()
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 400 and "第2行" in response.json["msg"]
    with factory() as session:
        assert session.query(IntakeTable).one().status == "pending"
        assert session.query(PackingListTable).count() == session.query(CargoTable).count() == session.query(BoxWorkerTable).count() == 0


def test_legacy_stored_draft_confirms_without_rewriting_its_historical_evidence(setup):
    client, factory = setup
    record = submit(client)
    legacy = {"mark": "LEGACY-WORKERS", "worker_ids": [3], "boxes": [
        {"box_number": 1, "item_name": "鞋", "count": 2, "weight": 1.5},
        {"box_number": 2, "item_name": "衣服", "count": 3, "weight": 2, "worker_ids": [1]},
    ]}
    with factory() as session:
        source = session.query(IntakeTable).one()
        source.draft_json = service.json.dumps(legacy)
        source.recognition_status = "succeeded"
        session.commit()
    record = client.get(f"/api/intakes/{record['uid']}", headers=headers()).json["data"]
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
    assert response.status_code == 200 and response.json["data"]["draft"] == legacy
    with factory() as session:
        assert service.json.loads(session.query(IntakeTable).one().draft_json) == legacy
        assignments = {box.box_number: [worker.worker_id for worker in session.query(BoxWorkerTable).filter_by(box_uid=box.uid)] for box in session.query(CargoTable)}
        assert assignments == {1: [3], 2: [1]}


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
    response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=headers(), json={"version": record["version"], "reviewed": True})
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


def test_recognition_binds_different_named_workers_for_each_box(setup, monkeypatch):
    client, factory = setup
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "boxes": [
        {"box_number": 1, "operator_name": "测试1"}, {"box_number": 2, "operator_name": "测试3"},
    ]})
    candidate = fresh["recognition_result"]
    assert [box["worker_ids"] for box in candidate["boxes"]] == [[1], [3]]
    assert candidate["warnings"] == []
    assert fresh["draft"] == {"mark": "", "boxes": []}
    with factory() as session:
        assert session.query(BoxWorkerTable).count() == session.query(CargoTable).count() == 0


def test_paper_signature_seeds_only_missing_rows_and_preserves_explicit_worker_choices(setup, monkeypatch):
    client, factory = setup
    source_boxes = [
        {"box_number": 1, "worker_ids": [1], "operator_name": "测试3"},
        {"box_number": 2, "worker_ids": [], "operator_name": "测试3"},
        {"box_number": 3, "operator_name": "测试1"},
        {"box_number": 4}, {"box_number": 5, "operator_name": ""},
    ]
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": "测试3", "boxes": source_boxes})
    candidate = fresh["recognition_result"]
    assert [box["worker_ids"] for box in candidate["boxes"]] == [[1], [], [1], [3], []]
    assert source_boxes[3] == {"box_number": 4}  # Binding must not mutate the provider evidence.
    assert any("第5箱" in warning for warning in candidate["warnings"])


def test_duplicate_or_partial_per_box_names_do_not_inherit_global_workers(setup, monkeypatch):
    client, factory = setup
    add_user(factory, 6, "测试1")
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": "测试3", "boxes": [
        {"box_number": 1, "operator_name": "测试1"},
        {"box_number": 2, "operator_name": "测试3、不存在"},
        {"box_number": 3, "operator_name": "测试3"},
    ]})
    candidate = fresh["recognition_result"]
    assert [box["worker_ids"] for box in candidate["boxes"]] == [[], [], [3]]
    assert any("第1箱" in warning and "同名工人" in warning for warning in candidate["warnings"])
    assert any("第2箱" in warning and "未匹配" in warning for warning in candidate["warnings"])


@pytest.mark.parametrize("worker_ids", [[2], [999], [True], None, [1, 3, 6, 7, 8]])
def test_invalid_recognized_box_worker_ids_become_empty_with_warning_without_global_substitution(setup, monkeypatch, worker_ids):
    client, factory = setup
    fresh = finish_recognition(client, factory, monkeypatch, {"mark": "AI", "operator_name": "测试3", "boxes": [
        {"box_number": 1, "worker_ids": worker_ids}, {"box_number": 2},
    ]})
    candidate = fresh["recognition_result"]
    assert [box["worker_ids"] for box in candidate["boxes"]] == [[], [3]]
    assert any("第1箱" in warning and "ID无效" in warning for warning in candidate["warnings"])


def test_deleted_source_cannot_be_read_edited_confirmed_or_recognized_again(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        source = session.query(IntakeTable).one()
        job = source.recognition_job_uid
        source.status = "deleted"
        session.commit()
    url = f"/api/intakes/{record['uid']}"
    assert client.get(url, headers=headers()).status_code == 404
    assert client.get(record["photos"][0]["url"], headers=headers()).status_code == 404
    assert client.put(url + "/draft", headers=headers(), json={"version": record["version"], "draft": {"mark": "RECREATE", "boxes": []}}).status_code == 404
    assert client.post(url + "/confirm", headers=headers(), json={"version": record["version"], "reviewed": True}).status_code == 404
    assert client.post(url + "/recognize", headers=headers(), json={"version": record["version"]}).status_code == 404
    assert client.get("/api/intakes/my-packing-lists", headers=headers()).json["data"]["items"] == []
    provider = Mock(return_value={"mark": "LATE", "boxes": []})
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=provider))
    service.run_recognition(record["uid"], job, [], "")
    provider.assert_not_called()
    with factory() as session:
        assert session.query(IntakeTable).one().recognition_result_json is None
        assert session.query(CargoTable).count() == session.query(PackingListTable).count() == 0


def test_deletion_during_provider_call_prevents_late_candidate_persistence(setup, monkeypatch):
    client, factory = setup
    record = submit(client)
    with factory() as session:
        job = session.query(IntakeTable).one().recognition_job_uid
    def recognize_then_delete(*args, **kwargs):
        with factory() as session:
            session.query(IntakeTable).one().status = "deleted"
            session.commit()
        return {"mark": "LATE", "operator_name": "测试1", "boxes": [{"box_number": 1}]}
    monkeypatch.setitem(sys.modules, "services.intake_recognition", SimpleNamespace(recognize_paper_photos=recognize_then_delete))
    service.run_recognition(record["uid"], job, [], "")
    with factory() as session:
        source = session.query(IntakeTable).one()
        assert source.status == "deleted" and source.recognition_result_json is None
        assert session.query(CargoTable).count() == session.query(PackingListTable).count() == 0


def test_initial_mark_hint_does_not_make_draft_manual_but_review_save_does(setup):
    client, _ = setup
    response = client.post("/api/intakes", headers=headers(), data={"mark_hint": "ABC", "photos": (png(), "纸单.png")})
    record = response.json["data"]
    assert record["draft_is_manual"] is False
    updated = client.put(f"/api/intakes/{record['uid']}/draft", headers=headers(), json={
        "version": record["version"], "draft": {"mark": "ABC", "boxes": [], "worker_ids": []},
    }).json["data"]
    assert updated["draft_is_manual"] is True


def test_unified_my_lists_include_manual_and_paper_once_with_private_paginated_metadata(setup):
    client, factory = setup
    pending = submit(client)
    submit(client, uid=3)
    confirmed = save_complete(client, submit(client), mark="OWN-PAPER", worker_ids=[3])
    confirmed = client.post(f"/api/intakes/{confirmed['uid']}/confirm", headers=headers(), json={"version": confirmed["version"], "reviewed": True}).json["data"]
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
    delete_keys = {"version", "can_delete", "photo_cleanup_pending"}
    assert all(set(item) == expected_keys | (delete_keys if item["status"] == "uploading" else set()) for item in result["items"])
    assert result["items"][0]["can_delete"] is True
    assert result["items"][0]["photo_cleanup_pending"] is False
    assert result["items"][0]["status"] == "uploading" and result["items"][0]["packing_list_uid"] is None
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


def test_uploading_status_filter_is_private_and_applies_before_pagination(setup):
    client, factory = setup
    pending = submit(client)
    submit(client, uid=3)
    add_manual_list(factory, "newest-draft", "DRAFT", created_at="2099-01-01 10:00")
    add_manual_list(factory, "newest-completed", "DONE", status="completed", created_at="2099-01-01 11:00")
    result = client.get("/api/intakes/my-packing-lists?status=uploading&page_size=1", headers=headers()).json["data"]
    assert result["total"] == 1 and len(result["items"]) == 1
    assert result["items"][0]["uid"] == pending["uid"] and result["items"][0]["status"] == "uploading"
    assert client.get("/api/intakes/my-packing-lists?status=uploading&page=2&page_size=1", headers=headers()).json["data"]["items"] == []
    assert client.get("/api/intakes/my-packing-lists?status=draft", headers=headers()).json["data"]["items"][0]["uid"] == "newest-draft"
    assert client.get("/api/intakes/my-packing-lists?status=completed", headers=headers()).json["data"]["items"][0]["uid"] == "newest-completed"
    assert client.get("/api/intakes/my-packing-lists?status=pending_review", headers=headers()).status_code == 400


def test_formal_source_lookup_never_returns_pending_or_other_worker_photos(setup):
    client, factory = setup
    pending = submit(client)
    add_manual_list(factory, "formal-own", "FORMAL-OWN")
    with factory() as session:
        session.query(IntakeTable).filter_by(uid=pending["uid"]).one().packing_list_uid = "formal-own"
        session.commit()
    for identity in (headers(), headers(2, "salesperson")):
        result = client.get("/api/intakes?packing_list_uid=formal-own&status=pending", headers=identity)
        assert result.status_code == 200 and result.json["data"]["total"] == 0
    assert client.get("/api/intakes?packing_list_uid=formal-own", headers=headers(3)).status_code == 403
    for query in ("", "?status=pending", "?mark=FORMAL-OWN", "?page=1", "?packing_list_uid="):
        assert client.get("/api/intakes" + query, headers=headers(2, "salesperson")).status_code == 410


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
