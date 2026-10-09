"""Independent export/import tools preserve SQL rows and validate all files first."""

import hashlib
import json
import os
import subprocess
import sys

import pytest
import sqlalchemy as sa

from services import paper_photo_storage as storage
from services import paper_photo_transfer as transfer
from test_photo_storage_migration import (
    BACKEND_ROOT, export_sources, import_paths, migrated_photos, old_photos,
    original_blobs, run_migration,
)


def manifest():
    return json.loads(transfer.default_manifest_path().read_text())


def write_manifest(document):
    transfer.default_manifest_path().write_text(json.dumps(document, ensure_ascii=False))


def test_export_writes_complete_manifest_and_files_without_sql_mutations(old_photos, paper_photo_root):
    engine, _, originals = old_photos
    before = migrated_photos(engine)
    result = export_sources(engine)
    assert result["exported_files"] == len(originals)
    assert result["total_bytes"] == sum(map(len, originals.values()))
    assert result["manifest_path"] == str(transfer.default_manifest_path())
    assert transfer.default_manifest_path() == paper_photo_root / ".photo-migration-manifest.json"
    assert migrated_photos(engine) == before
    document = manifest()
    assert document["version"] == 1
    assert document["created_at"]
    assert {entry["uid"] for entry in document["photos"]} == set(originals)
    for row in before:
        entry = next(entry for entry in document["photos"] if entry["uid"] == row["uid"])
        for field in ("uid", "intake_uid", "position", "filename", "mime_type"):
            assert entry[field] == row[field]
        original = originals[entry["uid"]]
        assert entry["size_bytes"] == len(original)
        assert entry["sha256"] == hashlib.sha256(original).hexdigest()
        assert (paper_photo_root / entry["storage_path"]).read_bytes() == original
        assert "data" not in entry
    with engine.connect() as connection:
        assert transfer.validate_manifest(connection, verify_blobs=True) == document["photos"]


def test_export_retry_is_read_only_and_failed_retry_preserves_complete_manifest(old_photos, monkeypatch):
    engine, _, originals = old_photos
    export_sources(engine)
    export_sources(engine)
    valid_manifest_bytes = transfer.default_manifest_path().read_bytes()

    def fail_write(*args, **kwargs):
        raise OSError("injected photo export failure")

    monkeypatch.setattr(storage, "save_bytes", fail_write)
    with pytest.raises(OSError, match="injected photo export failure"):
        export_sources(engine)
    assert transfer.default_manifest_path().read_bytes() == valid_manifest_bytes
    assert original_blobs(engine) == originals


@pytest.mark.parametrize("change", ["missing_uid", "extra_uid", "duplicate_uid", "wrong_filename", "wrong_position", "wrong_mime", "wrong_intake"])
def test_manifest_must_match_entire_original_photo_snapshot(old_photos, change):
    engine, _, originals = old_photos
    export_sources(engine)
    document = manifest()
    if change == "missing_uid":
        document["photos"].pop()
    elif change == "extra_uid":
        document["photos"].append({**document["photos"][0], "uid": "unknown", "storage_path": "source/unknown.png"})
    elif change == "duplicate_uid":
        document["photos"].append(dict(document["photos"][0]))
    else:
        field, value = {"wrong_filename": ("filename", "changed.png"), "wrong_position": ("position", 99),
                        "wrong_mime": ("mime_type", "image/jpeg"), "wrong_intake": ("intake_uid", "other")}[change]
        document["photos"][0][field] = value
    write_manifest(document)
    with engine.connect() as connection:
        with pytest.raises((transfer.PhotoTransferError, OSError)):
            transfer.validate_manifest(connection, verify_blobs=True)
    assert original_blobs(engine) == originals


def test_import_requires_schema_migration_and_export_requires_old_binary_column(old_photos):
    engine, module, originals = old_photos
    export_sources(engine)
    with engine.begin() as connection:
        with pytest.raises(transfer.PhotoTransferError):
            transfer.import_photo_paths(connection)
    assert original_blobs(engine) == originals
    run_migration(engine, module)
    before = migrated_photos(engine)
    valid_manifest = transfer.default_manifest_path().read_bytes()
    with engine.connect() as connection:
        with pytest.raises(transfer.PhotoTransferError):
            transfer.export_photos(connection)
    assert migrated_photos(engine) == before
    assert transfer.default_manifest_path().read_bytes() == valid_manifest


def test_import_restores_all_paths_and_is_idempotent(old_photos, paper_photo_root):
    engine, module, originals = old_photos
    export_sources(engine)
    run_migration(engine, module)
    assert all(row["storage_path"] is None for row in migrated_photos(engine))
    first = import_paths(engine)
    assert first["updated_files"] == len(originals)
    assert first["total_bytes"] == sum(map(len, originals.values()))
    rows = migrated_photos(engine)
    second = import_paths(engine)
    assert second["updated_files"] == len(originals)
    assert migrated_photos(engine) == rows
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert "data" not in columns
    assert all(not columns[field]["nullable"] for field in ("storage_path", "size_bytes", "sha256"))
    for row in rows:
        assert (paper_photo_root / row["storage_path"]).read_bytes() == originals[row["uid"]]


@pytest.mark.parametrize("field,value", [("storage_path", "source/other.png"), ("size_bytes", 999), ("sha256", "0" * 64)])
def test_import_rejects_different_existing_metadata_before_any_updates(old_photos, field, value):
    engine, module, _ = old_photos
    export_sources(engine)
    run_migration(engine, module)
    with engine.begin() as connection:
        connection.execute(sa.text(f"UPDATE paper_intake_photos SET {field}=:value WHERE uid='c'"), {"value": value})
    before = migrated_photos(engine)
    with engine.begin() as connection:
        with pytest.raises(transfer.PhotoTransferError):
            transfer.import_photo_paths(connection)
    assert migrated_photos(engine) == before
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert all(columns[field]["nullable"] for field in ("storage_path", "size_bytes", "sha256"))


def test_import_can_resume_partial_matching_metadata(old_photos):
    engine, module, _ = old_photos
    export_sources(engine)
    run_migration(engine, module)
    entry = next(entry for entry in manifest()["photos"] if entry["uid"] == "a")
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE paper_intake_photos SET size_bytes=:size WHERE uid='a'"), {"size": entry["size_bytes"]})
    import_paths(engine)
    for row in migrated_photos(engine):
        expected = next(entry for entry in manifest()["photos"] if entry["uid"] == row["uid"])
        assert all(row[field] == expected[field] for field in ("storage_path", "size_bytes", "sha256"))


@pytest.mark.parametrize("change", ["missing", "corrupt"])
def test_import_validates_every_file_before_changing_any_database_rows(old_photos, paper_photo_root, change):
    engine, module, _ = old_photos
    export_sources(engine)
    run_migration(engine, module)
    last_photo = manifest()["photos"][-1]
    path = paper_photo_root / last_photo["storage_path"]
    if change == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupted file")
    before = migrated_photos(engine)
    with engine.begin() as connection:
        with pytest.raises((transfer.PhotoTransferError, OSError)):
            transfer.import_photo_paths(connection)
    assert migrated_photos(engine) == before
    columns = {column["name"]: column for column in sa.inspect(engine).get_columns("paper_intake_photos")}
    assert all(columns[field]["nullable"] for field in ("storage_path", "size_bytes", "sha256"))


@pytest.mark.parametrize("reference", ["../outside.png", "/tmp/outside.png", "source/../../outside.png"])
def test_manifest_rejects_unsafe_file_paths(old_photos, reference, tmp_path):
    engine, _, _ = old_photos
    export_sources(engine)
    document = manifest()
    document["photos"][0]["storage_path"] = reference
    write_manifest(document)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"unrelated")
    with engine.connect() as connection:
        with pytest.raises((transfer.PhotoTransferError, OSError)):
            transfer.validate_manifest(connection)
    assert outside.read_bytes() == b"unrelated"


def test_manifest_environment_override_is_used(old_photos, monkeypatch, tmp_path):
    engine, _, _ = old_photos
    destination = tmp_path / "specified-manifest.json"
    monkeypatch.setenv("PAPER_PHOTO_MANIFEST", str(destination))
    assert transfer.default_manifest_path() == destination
    export_sources(engine)
    assert destination.exists()


def test_empty_photo_table_can_import_without_manifest(old_photos):
    engine, module, _ = old_photos
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM paper_intake_photos"))
    run_migration(engine, module)
    assert import_paths(engine) == {"updated_files": 0, "total_bytes": 0}
    assert not transfer.default_manifest_path().exists()


def test_existing_nonempty_manifest_cannot_be_applied_to_empty_database(old_photos):
    engine, _, _ = old_photos
    export_sources(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM paper_intake_photos"))
    with engine.connect() as connection:
        with pytest.raises(transfer.PhotoTransferError):
            transfer.validate_manifest(connection)


@pytest.mark.parametrize("script", ["export_paper_photos.py", "import_paper_photo_paths.py"])
def test_photo_transfer_cli_refuses_unconfigured_database(script, paper_photo_root):
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    result = subprocess.run([sys.executable, str(BACKEND_ROOT / "scripts" / script), "--storage-root", str(paper_photo_root)],
                            cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
    assert not transfer.default_manifest_path().exists()


def test_independent_cli_export_and_import_complete_real_three_stage_transfer(old_photos, paper_photo_root):
    engine, module, originals = old_photos
    environment = {**os.environ, "DATABASE_URL": str(engine.url)}
    export = subprocess.run([sys.executable, str(BACKEND_ROOT / "scripts/export_paper_photos.py"), "--storage-root", str(paper_photo_root)],
                            cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=15)
    assert export.returncode == 0, export.stderr
    assert json.loads(export.stdout)["exported_files"] == len(originals)
    assert original_blobs(engine) == originals
    run_migration(engine, module)
    imported = subprocess.run([sys.executable, str(BACKEND_ROOT / "scripts/import_paper_photo_paths.py"), "--storage-root", str(paper_photo_root)],
                              cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, timeout=15)
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout)["updated_files"] == len(originals)
    for row in migrated_photos(engine):
        assert (paper_photo_root / row["storage_path"]).read_bytes() == originals[row["uid"]]
