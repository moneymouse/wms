"""Formal Flask and Alembic integration without production startup or databases.

Run with pytest --confcutdir=tests/intake tests/intake.
"""
import importlib.util
import logging
import os
import subprocess
import sys
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import Mock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from PIL import Image
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from Auth import hash_password
from data import database
import data as data_package
import data.packing.PackingList as packing_data
import data.user.User as user_data
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import BoxWorkerTable, PackingListTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import auth_service, intake_service


@pytest.fixture
def formal_app(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionFactory", factory)
    monkeypatch.setattr(user_data, "SessionFactory", factory)
    monkeypatch.setattr(packing_data, "SessionFactory", factory)
    monkeypatch.setattr(auth_service, "SessionFactory", factory)
    monkeypatch.setattr(sys.modules["utils.log"], "SessionFactory", factory)
    monkeypatch.setattr(intake_service.threading, "Thread", lambda **kwargs: Mock())
    backup = Mock()
    init_admin = Mock()
    monkeypatch.setattr(data_package, "backup", backup)
    monkeypatch.setattr(auth_service, "init_admin_user", init_admin)
    monkeypatch.setattr(logging, "FileHandler", lambda *args, **kwargs: logging.NullHandler())
    # Legacy tracking imports read this file relative to cwd; use no real key.
    (tmp_path / "env.toml").write_text('17track_token="test-only"\n17track_endpoint="https://example.invalid"\n')
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("wms_formal_app_under_test", BACKEND_ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    from controllers import packing_controller
    monkeypatch.setattr(packing_controller, "SessionFactory", factory)
    module.app.config["TESTING"] = True
    database.Base.metadata.create_all(engine)
    with factory() as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        roles = {name: RoleTable(name=name, label=name) for name in ("worker", "clerk", "finance", "admin")}
        session.add_all(roles.values())
        for uid, name, role in ((17, "正式工人A", "worker"), (18, "正式工人B", "worker"), (19, "正式文员", "clerk"), (20, "正式财务", "finance"), (22, "正式管理员", "admin")):
            session.add(UserTable(id=uid, name=name, phone=f"188000000{uid}", password=hash_password("test-password"), status="approved", roles=[roles[role]]))
        session.commit()
    yield module.app.test_client(), factory, module.app, backup, init_admin
    engine.dispose()


def login(client, uid):
    response = client.post("/api/auth/login", json={"phone": f"188000000{uid}", "password": "test-password"})
    assert response.status_code == 200, response.json
    assert response.json["user"]["id"] == uid
    return {"x-token": response.json["token"]}


def photo():
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    output.seek(0)
    return output


def test_formal_app_exposes_intake_routes_with_existing_jwt_authentication(formal_app):
    client, _, app, backup, init_admin = formal_app
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert {"/api/intakes", "/api/intakes/workers", "/api/intakes/template", "/api/intakes/my-packing-lists", "/api/intakes/<uid>/draft", "/api/intakes/<uid>/confirm", "/api/intakes/<uid>/recognize"}.issubset(routes)
    backup.assert_called_once_with()
    init_admin.assert_called_once_with()
    assert client.get("/api/intakes").status_code == 401
    assert client.get("/api/intakes", headers={"x-token": "invalid-token"}).status_code == 401
    worker = login(client, 17)
    assert client.get("/api/intakes", headers=worker).status_code == 200
    assert client.get("/api/intakes/workers", headers=worker).status_code == 403
    template = client.get("/api/intakes/template", headers=worker)
    assert template.status_code == 200 and template.mimetype == "application/pdf"
    assert template.data.startswith(b"%PDF-")
    assert client.get("/api/intakes/template").status_code == 401
    assert not any("preview" in route for route in routes)
    preview = client.get("/api/preview/health")
    assert preview.status_code == 404 and preview.json["code"] == 404
    assert client.post("/api/auth/login", json={"phone": "18800000017", "password": "wrong-password"}).status_code == 401


def test_real_formal_login_upload_review_and_ownership_flow(formal_app):
    client, factory, _, _, _ = formal_app
    worker, other_worker, clerk, finance = [login(client, uid) for uid in (17, 18, 19, 20)]
    assert client.post("/api/intakes", headers=finance, data={"photos": (photo(), "拒绝.png")}).status_code == 403
    uploaded = client.post("/api/intakes", headers=worker, data={"photos": (photo(), "正式纸单.png")})
    assert uploaded.status_code == 201, uploaded.json
    record = uploaded.json["data"]
    assert record["submitted_by"] == 17 and record["submitted_by_name"] == "正式工人A"
    assert record["status"] == "pending"
    assert client.get(record["photos"][0]["url"], headers=other_worker).status_code == 403
    assert client.post(f"/api/intakes/{record['uid']}/confirm", headers=worker, json={"version": record["version"]}).status_code == 403
    workers = client.get("/api/intakes/workers", headers=clerk).json["data"]
    assert {item["id"] for item in workers} == {17, 18}
    saved = client.put(f"/api/intakes/{record['uid']}/draft", headers=clerk, json={
        "version": record["version"],
        "draft": {"mark": "FORMAL-PAPER", "operator_name": "正式工人A", "worker_ids": [17], "boxes": [{"box_number": 12, "item_name": "衣服", "count": 7, "weight": 2.5}]},
    })
    assert saved.status_code == 200, saved.json
    confirmed = client.post(f"/api/intakes/{record['uid']}/confirm", headers=clerk, json={"version": saved.json["data"]["version"]})
    assert confirmed.status_code == 200, confirmed.json
    packing_uid = confirmed.json["data"]["packing_list_uid"]
    with factory() as session:
        assert session.query(PackingListTable).filter_by(uid=packing_uid).one().creator_id == 17
        assert session.query(IntakeTable).one().confirmed_by == 19
        assert session.query(BoxWorkerTable).one().worker_id == 17
    my_lists = client.get("/api/intakes/my-packing-lists", headers=worker).json["data"]
    assert my_lists["total"] == 1
    assert my_lists["items"][0]["source"] == "paper" and my_lists["items"][0]["status"] == "completed"
    assert my_lists["items"][0]["packing_list_uid"] == packing_uid
    assert client.get(f"/api/packing-list/{packing_uid}", headers=worker).status_code == 200
    assert client.get(f"/api/packing-list/{packing_uid}", headers=other_worker).status_code == 403


def create_paper_record(client, confirmed):
    worker = login(client, 17)
    record = client.post("/api/intakes", headers=worker, data={"photos": (photo(), "删除保护.png")}).json["data"]
    if confirmed:
        clerk = login(client, 19)
        record = client.put(f"/api/intakes/{record['uid']}/draft", headers=clerk, json={
            "version": record["version"], "draft": {"mark": "PROTECTED-PAPER", "worker_ids": [17], "boxes": [{"box_number": 1, "item_name": "衣服", "count": 3, "weight": 2}]},
        }).json["data"]
        response = client.post(f"/api/intakes/{record['uid']}/confirm", headers=clerk, json={"version": record["version"]})
        assert response.status_code == 200, response.json
        record = response.json["data"]
    return record


@pytest.mark.parametrize("confirmed,user_id", [(False, 17), (True, 17), (True, 19), (True, 18)])
def test_formal_hard_delete_keeps_paper_upload_review_and_source_creator_identities(formal_app, confirmed, user_id):
    client, factory, _, _, _ = formal_app
    record = create_paper_record(client, confirmed)
    if user_id == 18:
        # A pre-existing source list may have a creator different from the uploader.
        with factory() as session:
            session.query(PackingListTable).filter_by(uid=record["packing_list_uid"]).one().creator_id = 18
            session.commit()
    response = client.delete(f"/api/users/{user_id}", headers=login(client, 22))
    assert response.status_code == 409 and "保留操作人员身份" in response.json["msg"]
    with factory() as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert session.query(UserTable).filter_by(id=user_id).one().status == "approved"
        assert session.query(IntakeTable).one().uid == record["uid"]
        assert session.query(IntakePhotoTable).one().data.startswith(b"\x89PNG")
        assert session.query(PackingListTable).count() == int(confirmed)
        assert session.query(CargoTable).count() == int(confirmed)
        assert session.query(BoxWorkerTable).count() == int(confirmed)


def test_formal_source_packing_list_hard_delete_returns_conflict_and_archive_preserves_paper(formal_app):
    client, factory, _, _, _ = formal_app
    record = create_paper_record(client, confirmed=True)
    uid = record["packing_list_uid"]
    admin = login(client, 22)
    response = client.delete(f"/api/packing-list/{uid}", headers=admin)
    assert response.status_code == 409 and "归档" in response.json["msg"]
    assert client.post(f"/api/packing-list/{uid}/archive", headers=admin).status_code == 200
    with factory() as session:
        assert session.query(PackingListTable).filter_by(uid=uid).one().archive is True
        assert session.query(IntakeTable).one().packing_list_uid == uid
        assert session.query(IntakePhotoTable).one().data.startswith(b"\x89PNG")
        assert session.query(CargoTable).one().packing_list_uid == uid
        assert session.query(BoxWorkerTable).one().worker_id == 17


def test_formal_hard_delete_remains_available_without_paper_references(formal_app):
    client, factory, _, _, _ = formal_app
    admin = login(client, 22)
    with factory() as session:
        session.add(PackingListTable(uid="manual-deletable", list_number="MANUAL", creator_id=17, photos="[]", status="draft"))
        session.commit()
    assert client.delete("/api/packing-list/manual-deletable", headers=admin).status_code == 200
    assert client.delete("/api/users/18", headers=admin).status_code == 200
    with factory() as session:
        assert session.query(PackingListTable).count() == 0
        assert session.query(UserTable).filter_by(id=18).first() is None


def migration_config():
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # Do not replace pytest's logging while exercising the real env.py.
    config.config_file_name = None
    return config


def test_formal_alembic_upgrade_creates_intake_schema_and_preserves_existing_data(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'formal-migration.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    existing_tables = [table for name, table in database.Base.metadata.tables.items() if name not in {"paper_intakes", "paper_intake_photos"}]
    database.Base.metadata.create_all(engine, tables=existing_tables)
    with engine.begin() as connection:
        connection.execute(UserTable.__table__.insert().values(id=70, phone="existing-user", name="保留用户", password="unused", status="approved"))
    config = migration_config()
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("df4a5b6c7d8e").down_revision == "ce3f4a5b6c7d"
    assert script.get_heads() == ["df4a5b6c7d8e"]
    command.stamp(config, "ce3f4a5b6c7d")
    command.upgrade(config, "head")
    schema = inspect(engine)
    assert {"paper_intakes", "paper_intake_photos"}.issubset(schema.get_table_names())
    assert {column["name"] for column in schema.get_columns("paper_intakes")} == set(IntakeTable.__table__.columns.keys())
    assert {key["referred_table"] for key in schema.get_foreign_keys("paper_intakes")} == {"users", "packing_lists"}
    assert schema.get_foreign_keys("paper_intake_photos")[0]["referred_table"] == "paper_intakes"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "df4a5b6c7d8e"
        assert connection.execute(text("SELECT name FROM users WHERE id=70")).scalar() == "保留用户"
    command.downgrade(config, "ce3f4a5b6c7d")
    assert "paper_intakes" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM users WHERE id=70")).scalar() == "保留用户"
    engine.dispose()


def test_intake_migration_compiles_for_production_mysql_without_connection(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://unused:unused@invalid/wms")
    config = migration_config()
    output = StringIO()
    config.output_buffer = output
    command.upgrade(config, "ce3f4a5b6c7d:df4a5b6c7d8e", sql=True)
    ddl = output.getvalue()
    assert "CREATE TABLE paper_intakes" in ddl and "CREATE TABLE paper_intake_photos" in ddl
    assert "FOREIGN KEY(submitted_by) REFERENCES users (id)" in ddl
    assert "FOREIGN KEY(intake_uid) REFERENCES paper_intakes (uid)" in ddl
    assert "BLOB(16777216)" in ddl


@pytest.mark.parametrize("has_version,has_tables,baseline,expected_commands,success", [
    ("no", "yes", "", [], False),
    ("no", "yes", "head", [], False),
    ("no", "yes", "ce3f4a5b6c7d", ["stamp ce3f4a5b6c7d", "upgrade head"], True),
    ("yes", "yes", "", ["upgrade head"], True),
    ("no", "no", "", ["upgrade head"], True),
])
def test_container_migration_bootstrap_never_stamps_unknown_existing_schema_at_head(tmp_path, has_version, has_tables, baseline, expected_commands, success):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    actions = tmp_path / "actions.txt"
    scripts = {
        "python": '#!/bin/sh\ncase "$2" in\n*main_tables*) printf "%s\\n" "$TEST_HAS_TABLES";;\n*alembic_version*) printf "%s\\n" "$TEST_HAS_VERSION";;\n*) exit 0;;\nesac\n',
        "alembic": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_ACTIONS"\n',
        "gunicorn": '#!/bin/sh\nexit 0\n',
    }
    for name, content in scripts.items():
        executable = binaries / name
        executable.write_text(content)
        executable.chmod(0o755)
    env = dict(os.environ)
    env.update(PATH=f"{binaries}:/usr/bin:/bin", RUN_MIGRATIONS="true", FLASK_ENV="production", TEST_HAS_VERSION=has_version, TEST_HAS_TABLES=has_tables, TEST_ACTIONS=str(actions), ALEMBIC_BASELINE_REVISION=baseline)
    env.pop("ADMIN_PHONE", None)
    env.pop("ADMIN_PASSWORD", None)
    result = subprocess.run(["/bin/bash", str(BACKEND_ROOT / "docker-entrypoint.sh")], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) is success
    assert (actions.read_text().splitlines() if actions.exists() else []) == expected_commands
    if not success:
        assert "ALEMBIC_BASELINE_REVISION" in result.stdout
