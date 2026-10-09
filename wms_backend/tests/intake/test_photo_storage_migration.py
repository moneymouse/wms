"""Three-stage paper photo transfer against isolated SQLite and private files."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from services import paper_photo_storage as storage
from services import paper_photo_transfer as transfer


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def migration_module(filename):
    path = BACKEND_ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(engine, module, direction="upgrade"):
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        getattr(module, direction)()


def export_sources(engine):
    with engine.connect() as connection:
        return transfer.export_photos(connection)


def import_paths(engine):
    with engine.begin() as connection:
        return transfer.import_photo_paths(connection)


def complete_transfer(engine, module):
    export_sources(engine)
    run_migration(engine, module)
    import_paths(engine)


@pytest.fixture
def old_photos(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE packing_lists (uid VARCHAR(32) PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        connection.execute(sa.text("INSERT INTO packing_lists (uid) VALUES ('packing')"))
    original_migration = migration_module("20261001_df4a5b6c7d8e_paper_intakes.py")
    run_migration(engine, original_migration)
    originals = {"a": b"\x89PNG\x00\xff-original", "b": b"\xff\xd8\x00jpeg-original", "c": b"RIFF\x00webp-original"}
    formats = {"a": "image/png", "b": "image/jpeg", "c": "image/webp"}
    with engine.begin() as connection:
        connection.execute(sa.text("""INSERT INTO paper_intakes
            (uid, submitted_by, submitted_by_name, created_at, mark_hint, note, status,
             draft_json, version, packing_list_uid, recognition_status)
            VALUES ('source', 1, '上传人员', '2026-10-01', '旧唛头', '保留备注', 'confirmed',
                    '{"mark":"旧唛头","boxes":[]}', 3, 'packing', 'succeeded')"""))
        for position, (uid, data) in enumerate(originals.items()):
            connection.execute(sa.text("""INSERT INTO paper_intake_photos
                (uid, intake_uid, position, filename, mime_type, data)
                VALUES (:uid, 'source', :position, :filename, :mime_type, :data)"""),
                {"uid": uid, "position": position, "filename": f"原图-{uid}", "mime_type": formats[uid], "data": data})
    module = migration_module("20261007_8af5b6c7d8e9_paper_photo_files.py")
    yield engine, module, originals
    engine.dispose()


def original_blobs(engine):
    with engine.connect() as connection:
        return dict(connection.execute(sa.text("SELECT uid, data FROM paper_intake_photos ORDER BY uid")).all())


def migrated_photos(engine):
    with engine.connect() as connection:
        return connection.execute(sa.text("SELECT * FROM paper_intake_photos ORDER BY uid")).mappings().all()


def test_three_stage_transfer_exports_then_only_changes_schema_then_imports_paths(old_photos, paper_photo_root):
    engine, module, originals = old_photos
    export_sources(engine)
    assert original_blobs(engine) == originals
    assert "storage_path" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    run_migration(engine, module)
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert "data" not in columns
    assert all(columns[name]["nullable"] for name in ("storage_path", "size_bytes", "sha256"))
    rows = migrated_photos(engine)
    assert len(rows) == len(originals)
    assert all(row[name] is None for row in rows for name in ("storage_path", "size_bytes", "sha256"))
    import_paths(engine)
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert all(not columns[name]["nullable"] for name in ("storage_path", "size_bytes", "sha256"))
    assert "paper_photo_cleanup" in sa.inspect(engine).get_table_names()
    assert any(constraint["column_names"] == ["storage_path"] for constraint in sa.inspect(engine).get_unique_constraints("paper_intake_photos"))
    for position, row in enumerate(migrated_photos(engine)):
        original = originals[row["uid"]]
        assert (paper_photo_root / row["storage_path"]).read_bytes() == original
        assert row["size_bytes"] == len(original)
        assert row["sha256"] == hashlib.sha256(original).hexdigest()
        assert (row["intake_uid"], row["position"], row["filename"]) == ("source", position, f"原图-{row['uid']}")
        assert storage.read_bytes(SimpleNamespace(**row)) == original
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT * FROM paper_intakes")).mappings().one()
        assert (row["packing_list_uid"], row["submitted_by"], row["version"], row["note"]) == ("packing", 1, 3, "保留备注")
    run_migration(engine, module, "downgrade")
    assert original_blobs(engine) == originals
    assert "storage_path" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}


def test_interrupted_export_keeps_all_mysql_bytes_and_retries_existing_verified_files(old_photos, monkeypatch, paper_photo_root):
    engine, module, originals = old_photos
    save_bytes = storage.save_bytes

    def fail_second_photo(intake_uid, photo_uid, mime_type, data):
        if photo_uid == "b":
            raise OSError("injected export failure")
        return save_bytes(intake_uid, photo_uid, mime_type, data)

    monkeypatch.setattr(storage, "save_bytes", fail_second_photo)
    with pytest.raises(OSError, match="injected export failure"):
        export_sources(engine)
    assert original_blobs(engine) == originals
    assert not transfer.default_manifest_path().exists()
    with pytest.raises((RuntimeError, OSError, ValueError)):
        run_migration(engine, module)
    assert original_blobs(engine) == originals
    first_path = paper_photo_root / "source/a.png"
    assert first_path.read_bytes() == originals["a"]
    monkeypatch.setattr(storage, "save_bytes", save_bytes)
    complete_transfer(engine, module)
    assert first_path.read_bytes() == originals["a"]
    assert len(migrated_photos(engine)) == len(originals)
    assert "data" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}


def test_conflicting_existing_file_stops_export_without_overwriting_or_dropping_source(old_photos, paper_photo_root):
    engine, module, originals = old_photos
    conflicting = storage.save_bytes("source", "a", "image/png", b"unrelated existing bytes")
    with pytest.raises(storage.PhotoStorageError, match="differs"):
        export_sources(engine)
    assert original_blobs(engine) == originals
    assert (paper_photo_root / conflicting["storage_path"]).read_bytes() == b"unrelated existing bytes"


@pytest.mark.parametrize("paths_imported", [False, True])
def test_downgrade_refuses_missing_files_without_removing_file_metadata(old_photos, paper_photo_root, paths_imported):
    engine, module, _ = old_photos
    export_sources(engine)
    run_migration(engine, module)
    if paths_imported:
        import_paths(engine)
    rows = migrated_photos(engine)
    entry = json.loads(transfer.default_manifest_path().read_text())["photos"][0]
    (paper_photo_root / entry["storage_path"]).unlink()
    with pytest.raises((RuntimeError, OSError, ValueError)):
        run_migration(engine, module, "downgrade")
    assert migrated_photos(engine) == rows
    assert "data" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}


def restore_blob_before_interrupted_downgrade(connection, originals):
    operations = Operations(MigrationContext.configure(connection))
    operations.add_column("paper_intake_photos", sa.Column("data", sa.LargeBinary(length=16777216), nullable=True))
    for uid, original in originals.items():
        connection.execute(sa.text("UPDATE paper_intake_photos SET data=:data WHERE uid=:uid"), {"uid": uid, "data": original})
    return operations


def test_downgrade_retry_after_unique_constraint_drop_preserves_restored_originals(old_photos):
    engine, module, originals = old_photos
    complete_transfer(engine, module)
    with engine.begin() as connection:
        operations = restore_blob_before_interrupted_downgrade(connection, originals)
        with operations.batch_alter_table("paper_intake_photos") as batch:
            batch.drop_constraint("uq_paper_intake_photo_storage_path", type_="unique")
    assert original_blobs(engine) == originals
    run_migration(engine, module, "downgrade")
    assert original_blobs(engine) == originals
    assert "storage_path" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert "paper_photo_cleanup" not in sa.inspect(engine).get_table_names()


def test_downgrade_retry_after_partial_metadata_drop_keeps_restored_originals(old_photos):
    engine, module, originals = old_photos
    complete_transfer(engine, module)
    with engine.begin() as connection:
        operations = restore_blob_before_interrupted_downgrade(connection, originals)
        with operations.batch_alter_table("paper_intake_photos") as batch:
            batch.drop_constraint("uq_paper_intake_photo_storage_path", type_="unique")
            batch.drop_column("sha256")
    assert original_blobs(engine) == originals
    run_migration(engine, module, "downgrade")
    assert original_blobs(engine) == originals
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert not {"storage_path", "size_bytes", "sha256"}.intersection(columns)
    assert columns["data"]["nullable"] is False


def test_upgrade_retry_recreates_missing_cleanup_index_without_touching_original_files(old_photos, paper_photo_root):
    engine, module, originals = old_photos
    complete_transfer(engine, module)
    rows = migrated_photos(engine)
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        operations.drop_index("ix_paper_photo_cleanup_packing_list_uid", table_name="paper_photo_cleanup")
    run_migration(engine, module)
    assert migrated_photos(engine) == rows
    assert any(index["name"] == "ix_paper_photo_cleanup_packing_list_uid" for index in sa.inspect(engine).get_indexes("paper_photo_cleanup"))
    assert "data" not in {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    for row in rows:
        assert (paper_photo_root / row["storage_path"]).read_bytes() == originals[row["uid"]]


@pytest.mark.parametrize("failure", ["missing_manifest", "malformed_manifest", "missing_file", "changed_blob"])
def test_schema_migration_requires_complete_export_matching_current_source(old_photos, paper_photo_root, failure):
    engine, module, originals = old_photos
    expected = dict(originals)
    if failure != "missing_manifest":
        export_sources(engine)
    if failure == "malformed_manifest":
        transfer.default_manifest_path().write_text("{invalid json")
    elif failure == "missing_file":
        (paper_photo_root / "source/a.png").unlink()
    elif failure == "changed_blob":
        expected["b"] = b"source changed after export"
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE paper_intake_photos SET data=:data WHERE uid='b'"), {"data": expected["b"]})
    old_columns = {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    before = migrated_photos(engine)
    with pytest.raises((RuntimeError, OSError, ValueError)):
        run_migration(engine, module)
    assert original_blobs(engine) == expected
    assert migrated_photos(engine) == before
    assert {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")} == old_columns


def test_empty_schema_upgrade_does_not_require_export_manifest(old_photos):
    engine, module, _ = old_photos
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM paper_intake_photos"))
    assert not transfer.default_manifest_path().exists()
    run_migration(engine, module)
    columns = {column["name"] for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert {"storage_path", "size_bytes", "sha256"}.issubset(columns)
    assert "data" not in columns
    assert migrated_photos(engine) == []
    assert not transfer.default_manifest_path().exists()


def test_downgrade_before_path_import_restores_originals_from_export_manifest(old_photos):
    engine, module, originals = old_photos
    export_sources(engine)
    run_migration(engine, module)
    assert all(row["storage_path"] is None for row in migrated_photos(engine))
    run_migration(engine, module, "downgrade")
    assert original_blobs(engine) == originals


def test_photo_export_requires_online_database_access():
    module = migration_module("20261007_8af5b6c7d8e9_paper_photo_files.py")
    module.op = Operations(MigrationContext.configure(url="mysql+pymysql://unused:unused@invalid/wms", opts={"as_sql": True}))
    with pytest.raises(RuntimeError, match="online database"):
        module.upgrade()
