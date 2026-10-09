"""Packing photo deletion uses only a temporary FK-enabled SQLite database."""

import json
import os
import sys
from pathlib import Path

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from Auth import create_jwt
from controllers.intake_controller import intake_bp
from controllers.packing_controller import packing_bp
from data.database import Base
from data.DB import CargoTable, OrderTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import BoxWorkerTable, PackingListTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services.paper_photo_storage import save_bytes


@pytest.fixture
def world(monkeypatch, tmp_path):
    paper_folder = tmp_path / "paper_intakes"
    monkeypatch.setenv("PAPER_PHOTO_ROOT", str(paper_folder))
    engine = create_engine(f"sqlite:///{tmp_path / 'deletion.sqlite'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in ("data.database", "data.DB", "data.packing.PackingList",
                   "data.order_version", "utils.log", "utils.audit", "controllers.packing_controller"):
        monkeypatch.setattr(module + ".SessionFactory", factory)
    folder = tmp_path / "static/uploads/photos"
    folder.mkdir(parents=True)
    monkeypatch.setattr("services.packing_list_service.UPLOAD_FOLDER", str(folder))
    app = Flask(__name__, static_folder=str(tmp_path / "static"), static_url_path="/static")
    app.config["TESTING"] = True
    app.register_blueprint(packing_bp)
    app.register_blueprint(intake_bp)
    draft = {"mark": "MARK", "operator_name": "工人", "worker_ids": [1],
             "boxes": [{"box_number": 1, "item_name": "鞋", "count": 1, "weight": 2}]}
    with factory.begin() as session:
        roles = {name: RoleTable(name=name, label=name) for name in ("worker", "admin")}
        session.add_all(roles.values())
        session.add_all([
            UserTable(id=1, name="工人", phone="10000000001", password="unused", status="approved", roles=[roles["worker"]]),
            UserTable(id=2, name="管理员", phone="10000000002", password="unused", status="approved", roles=[roles["admin"]]),
            OrderTable(uid="order", order_id="ORDER", archive=False),
            PackingListTable(uid="packing", list_number="MARK", creator_id=1, status="completed", archive=False, photos="[]"),
        ])
        session.flush()
        session.add(CargoTable(uid="box", packing_list_uid="packing", target_order_uid="order", status=0,
                               archive=False, weight=2, box_number=1, transfer_id="D800000001L", item_name="鞋"))
        source = IntakeTable(uid="source", submitted_by=1, submitted_by_name="工人", created_at="2026-10-06",
                             status="confirmed", confirmed_by=1, confirmed_at="2026-10-06", packing_list_uid="packing",
                             recognition_status="succeeded", draft_json=json.dumps(draft), version=3,
                             photos=[IntakePhotoTable(uid="source-photo", position=0, filename="source.png", mime_type="image/png",
                                                      **save_bytes("source", "source-photo", "image/png", b"source-photo-binary"))])
        session.add(source)
        session.flush()
        source.version = 3
        session.add(BoxWorkerTable(box_uid="box", worker_id=1))
        source_photo_path = paper_folder / source.photos[0].storage_path
    yield {"factory": factory, "client": app.test_client(), "folder": folder, "paper_folder": paper_folder,
           "source_photo_path": source_photo_path, "draft": draft, "engine": engine}
    engine.dispose()


@pytest.fixture
def admin():
    return {"x-token": create_jwt({"user_id": 2, "name": "管理员", "role": "admin"})}


@pytest.fixture
def worker():
    return {"x-token": create_jwt({"user_id": 1, "name": "工人", "role": "worker"})}
