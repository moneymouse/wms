"""Storage controls run against a temporary database and private file root."""

import os
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from Auth import create_jwt
from controllers.intake_controller import intake_bp
from controllers.storage_management_controller import storage_management_bp
from data.database import Base
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable
from services import paper_photo_storage


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_PHOTO_ROOT", str(tmp_path / "paper-photos"))
    engine = create_engine(f"sqlite:///{tmp_path / 'storage.sqlite'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("data.database.SessionFactory", factory)
    monkeypatch.setattr("utils.log.SessionFactory", factory)
    monkeypatch.setattr("services.storage_management_service.current_time", lambda: datetime(2026, 10, 7, 12))
    with factory.begin() as session:
        session.add_all([
            UserTable(id=1, name="操作员", phone="10000000001", password="unused", status="approved"),
            UserTable(id=2, name="其他人员", phone="10000000002", password="unused", status="approved"),
        ])
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(storage_management_bp)
    app.register_blueprint(intake_bp)
    result = {"factory": factory, "client": app.test_client(), "tmp_path": tmp_path,
              "admin": {"x-token": create_jwt({"user_id": 1, "name": "管理员", "role": "admin"})}}

    def add_packing(uid="packing", dates=("2026-07-01 12:00:00",), statuses=None,
                    archive=False, box_archives=None, photo_data=(b"first-photo",),
                    source_status="confirmed", list_number=None):
        source_uid = uuid4().hex
        paths = []
        photos = []
        for index, data in enumerate(photo_data):
            photo_uid = uuid4().hex
            metadata = paper_photo_storage.save_bytes(source_uid, photo_uid, "image/png", data)
            paths.append(metadata["storage_path"])
            photos.append(IntakePhotoTable(uid=photo_uid, position=index, filename="paper.png",
                                           mime_type="image/png", **metadata))
        with factory.begin() as session:
            session.add(PackingListTable(uid=uid, list_number=list_number or uid.upper(), creator_id=1,
                                         status="completed", archive=archive, photos="[]", create_date="2026-06-01"))
            session.flush()
            for index, shipped_at in enumerate(dates):
                session.add(CargoTable(uid=f"{uid}-box-{index}", packing_list_uid=uid,
                                       status=statuses[index] if statuses is not None else 1,
                                       date=shipped_at, archive=box_archives[index] if box_archives is not None else archive,
                                       box_number=index + 1, weight=2))
            source = IntakeTable(uid=source_uid, submitted_by=1, submitted_by_name="操作员",
                                 created_at="2026-06-01", status=source_status, confirmed_by=1,
                                 confirmed_at="2026-06-01 13:00:00", packing_list_uid=uid,
                                 draft_json='{"mark":"原纸单","boxes":[]}', recognition_status="succeeded",
                                 photos=photos, version=3)
            session.add(source)
            session.flush()
            source.version = 3
        return {"uid": uid, "source_uid": source_uid, "paths": paths,
                "bytes": sum(len(data) for data in photo_data)}

    def add_intake(uid=None, mark_hint="", draft=None, candidate=None, source_status="pending",
                   photo_data=(b"pending-photo",)):
        uid = uid or uuid4().hex
        photos, paths = [], []
        for index, data in enumerate(photo_data):
            photo_uid = uuid4().hex
            metadata = paper_photo_storage.save_bytes(uid, photo_uid, "image/png", data)
            paths.append(metadata["storage_path"])
            photos.append(IntakePhotoTable(uid=photo_uid, position=index, filename="paper.png",
                                           mime_type="image/png", **metadata))
        with factory.begin() as session:
            session.add(IntakeTable(uid=uid, submitted_by=1, submitted_by_name="操作员",
                                   created_at="2026-10-07", status=source_status, mark_hint=mark_hint,
                                   draft_json=json.dumps(draft or {"mark": "", "boxes": []}),
                                   recognition_result_json=json.dumps(candidate) if candidate is not None else None,
                                   recognition_status="idle", photos=photos))
        return {"source_uid": uid, "paths": paths, "bytes": sum(len(data) for data in photo_data)}

    result["add_packing"] = add_packing
    result["add_intake"] = add_intake
    yield result
    engine.dispose()
