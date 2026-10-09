"""The startup gate rejects incomplete migration without changing SQL or files."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from scripts import check_paper_photo_storage as readiness


BACKEND_ROOT = Path(__file__).resolve().parents[2]
NEXT_STEPS = "请先导出照片、执行迁移、回填文件路径后再启动"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "photo-readiness.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    yield engine, path
    engine.dispose()


def create_schema(engine, *, legacy=False, nullable=False, cleanup=True, missing=None):
    metadata = sa.MetaData()
    columns = [sa.Column("uid", sa.String(32), primary_key=True)]
    if legacy:
        columns.append(sa.Column("data", sa.LargeBinary()))
    else:
        columns.extend(column for column in [
            sa.Column("storage_path", sa.String(512), nullable=nullable),
            sa.Column("size_bytes", sa.BigInteger(), nullable=nullable),
            sa.Column("sha256", sa.String(64), nullable=nullable),
        ] if column.name != missing)
    photos = sa.Table("paper_intake_photos", metadata, *columns)
    if cleanup:
        sa.Table("paper_photo_cleanup", metadata, sa.Column("storage_path", sa.String(512), primary_key=True))
    metadata.create_all(engine)
    return photos


def valid_photo():
    return {"uid": "photo-1", "storage_path": "intake-1/photo-1.jpg", "size_bytes": 5,
            "sha256": hashlib.sha256(b"photo").hexdigest()}


def test_empty_database_is_not_ready(database):
    engine, _ = database
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady, match=NEXT_STEPS):
        readiness.assert_ready(connection)
    assert sa.inspect(engine).get_table_names() == []


@pytest.mark.parametrize("photo_count", [0, 2])
def test_old_binary_schema_cannot_start_even_when_empty(database, photo_count):
    engine, _ = database
    photos = create_schema(engine, legacy=True)
    with engine.begin() as connection:
        for number in range(photo_count):
            connection.execute(photos.insert(), {"uid": f"photo-{number}", "data": b"original"})
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady) as error:
        readiness.assert_ready(connection)
    assert error.value.pending_count == photo_count
    assert NEXT_STEPS in str(error.value)
    assert "缺少照片文件元数据列" in str(error.value)


def test_binary_column_is_rejected_even_if_metadata_was_already_backfilled(database):
    engine, _ = database
    photos = create_schema(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("ALTER TABLE paper_intake_photos ADD COLUMN data BLOB"))
        connection.execute(photos.insert(), valid_photo())
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady, match="data 尚未移除"):
        readiness.assert_ready(connection)


@pytest.mark.parametrize("missing", ["storage_path", "size_bytes", "sha256"])
def test_missing_metadata_column_is_not_ready(database, missing):
    engine, _ = database
    create_schema(engine, missing=missing)
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady, match=missing):
        readiness.assert_ready(connection)


def test_unfilled_metadata_reports_pending_count_and_remains_unchanged(database):
    engine, path = database
    photos = create_schema(engine, nullable=True)
    with engine.begin() as connection:
        connection.execute(photos.insert(), [{"uid": "unfilled-1"}, {"uid": "unfilled-2"}])
        connection.execute(photos.insert(), valid_photo())
    before = path.read_bytes()
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady) as error:
        readiness.assert_ready(connection)
    assert error.value.pending_count == 2
    assert "待回填照片数量：2" in str(error.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("storage_path", " "), ("sha256", ""), ("size_bytes", -1)])
def test_invalid_metadata_is_not_ready(database, field, value):
    engine, _ = database
    photos = create_schema(engine)
    with engine.begin() as connection:
        connection.execute(photos.insert(), {**valid_photo(), field: value})
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady) as error:
        readiness.assert_ready(connection)
    assert error.value.pending_count == 1


def test_backfilled_rows_require_final_not_null_constraints(database):
    engine, _ = database
    photos = create_schema(engine, nullable=True)
    with engine.begin() as connection:
        connection.execute(photos.insert(), valid_photo())
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady, match="NOT NULL"):
        readiness.assert_ready(connection)


def test_complete_metadata_requires_cleanup_table(database):
    engine, _ = database
    create_schema(engine, cleanup=False)
    with engine.connect() as connection, pytest.raises(readiness.PhotoStorageNotReady, match="paper_photo_cleanup"):
        readiness.assert_ready(connection)


@pytest.mark.parametrize("photo_count", [0, 1])
def test_ready_schema_and_rows_are_checked_with_read_only_sql(database, photo_count):
    engine, path = database
    photos = create_schema(engine)
    if photo_count:
        with engine.begin() as connection:
            connection.execute(photos.insert(), valid_photo())
    before = path.read_bytes()
    statements = []
    sa.event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement))
    with engine.connect() as connection:
        assert readiness.assert_ready(connection) is None
    assert statements
    assert all(statement.lstrip().upper().startswith(("SELECT", "PRAGMA")) for statement in statements)
    assert path.read_bytes() == before


def test_main_rejects_missing_database_url_without_trying_to_connect(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    create_engine = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(readiness.sa, "create_engine", create_engine)
    assert readiness.main() == 1
    assert "未设置 DATABASE_URL" in capsys.readouterr().err
    create_engine.assert_not_called()


@pytest.mark.parametrize("stage", ["create", "connect", "inspect"])
def test_main_masks_database_failures_and_credentials(monkeypatch, capsys, stage):
    secret_url = "mysql+pymysql://secret_user:secret_password@secret_host/private_db"
    monkeypatch.setenv("DATABASE_URL", secret_url)
    engine = Mock()
    if stage == "create":
        factory = Mock(side_effect=RuntimeError(secret_url))
    else:
        factory = Mock(return_value=engine)
        if stage == "connect":
            engine.connect.side_effect = RuntimeError(secret_url)
        else:
            engine.connect.return_value = engine
            engine.__enter__ = Mock(return_value=engine)
            engine.__exit__ = Mock(return_value=False)
            monkeypatch.setattr(readiness, "assert_ready", Mock(side_effect=RuntimeError(secret_url)))
    monkeypatch.setattr(readiness.sa, "create_engine", factory)
    assert readiness.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "数据库连接或读取失败" in output.err
    assert not any(secret in output.err for secret in [secret_url, "secret_user", "secret_password", "secret_host", "Traceback"])
    if stage != "create":
        engine.dispose.assert_called_once()


def test_main_does_not_create_a_missing_sqlite_database(monkeypatch, capsys, tmp_path):
    path = tmp_path / "missing.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    assert readiness.main() == 1
    assert "数据库连接或读取失败" in capsys.readouterr().err
    assert not path.exists()


def test_standalone_module_is_read_only_and_does_not_import_application(database):
    engine, path = database
    create_schema(engine)
    before = path.read_bytes()
    environment = {**os.environ, "DATABASE_URL": str(engine.url)}
    environment.pop("TESTING", None)
    result = subprocess.run([sys.executable, "-m", "scripts.check_paper_photo_storage"], cwd=BACKEND_ROOT,
                            env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "检查通过" in result.stdout
    assert path.read_bytes() == before
    assert not (path.parent / "log").exists()


def test_standalone_module_blocks_an_incomplete_import_without_writing(database):
    engine, path = database
    photos = create_schema(engine, nullable=True)
    with engine.begin() as connection:
        connection.execute(photos.insert(), {"uid": "not-yet-imported"})
    before = path.read_bytes()
    environment = {**os.environ, "DATABASE_URL": str(engine.url)}
    result = subprocess.run([sys.executable, "-m", "scripts.check_paper_photo_storage"], cwd=BACKEND_ROOT,
                            env=environment, capture_output=True, text=True)
    assert result.returncode == 1
    assert NEXT_STEPS in result.stderr
    assert "待回填照片数量：1" in result.stderr
    assert result.stdout == ""
    assert path.read_bytes() == before


def test_entrypoint_checks_readiness_after_migration_and_admin_before_gunicorn():
    entrypoint = (BACKEND_ROOT / "docker-entrypoint.sh").read_text()
    guard = entrypoint.index("python -m scripts.check_paper_photo_storage")
    assert entrypoint.index("alembic upgrade head") < guard
    assert entrypoint.index("python -m scripts.init_admin") < guard
    assert guard < entrypoint.index("exec gunicorn")
