"""Explicit, verifiable transfer of legacy photo bytes before schema migration."""

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from services import paper_photo_storage as storage


ORIGINAL_FIELDS = ("uid", "intake_uid", "position", "filename", "mime_type")
FILE_FIELDS = ("storage_path", "size_bytes", "sha256")
MANIFEST_FIELDS = set(ORIGINAL_FIELDS + FILE_FIELDS)


class PhotoTransferError(ValueError):
    pass


def default_manifest_path():
    configured = os.environ.get("PAPER_PHOTO_MANIFEST")
    return Path(configured).expanduser().absolute() if configured else storage.root_path() / ".photo-migration-manifest.json"


def _manifest_path(value=None):
    return Path(value).expanduser().absolute() if value is not None else default_manifest_path()


def _check_manifest_parent(path):
    if path.parent.resolve() != path.parent:
        raise PhotoTransferError("照片清单目录不能包含符号链接")
    if path.is_symlink():
        raise PhotoTransferError("照片清单文件不能为符号链接")


def _table(connection):
    return sa.Table("paper_intake_photos", sa.MetaData(), autoload_with=connection)


def _require_columns(table, names):
    if any(name not in table.c for name in names):
        raise PhotoTransferError("照片表缺少当前步骤所需字段，请确认数据库迁移阶段")


def _rows(connection, table, fields):
    previous = None
    while True:
        query = sa.select(*(table.c[name] for name in fields)).order_by(table.c.uid).limit(1)
        if previous is not None:
            query = query.where(table.c.uid > previous)
        row = connection.execute(query).mappings().first()
        if row is None:
            return
        previous = row["uid"]
        yield dict(row)


def _original_metadata(row):
    return {name: row[name] for name in ORIGINAL_FIELDS}


def _validate_entry(entry):
    if not isinstance(entry, dict) or set(entry) != MANIFEST_FIELDS:
        raise PhotoTransferError("照片清单条目字段不完整或格式错误")
    if any(not isinstance(entry[name], str) or not storage.IDENTIFIER.fullmatch(entry[name])
           for name in ("uid", "intake_uid")):
        raise PhotoTransferError("照片清单包含无效的记录编号")
    if isinstance(entry["position"], bool) or not isinstance(entry["position"], int) or entry["position"] < 0:
        raise PhotoTransferError("照片清单包含无效的页序号")
    if not isinstance(entry["filename"], str) or not isinstance(entry["mime_type"], str) or entry["mime_type"] not in storage.EXTENSIONS:
        raise PhotoTransferError("照片清单包含无效的文件元数据")
    expected_path = f"{entry['intake_uid']}/{entry['uid']}.{storage.EXTENSIONS[entry['mime_type']]}"
    if entry["storage_path"] != expected_path:
        raise PhotoTransferError("照片清单中的文件路径与照片编号不一致")
    if isinstance(entry["size_bytes"], bool) or not isinstance(entry["size_bytes"], int) or entry["size_bytes"] < 0:
        raise PhotoTransferError("照片清单包含无效的文件大小")
    if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
        raise PhotoTransferError("照片清单包含无效的SHA256摘要")


def _read_manifest(path):
    _check_manifest_parent(path)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PhotoTransferError("照片清单须为普通文件")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            manifest = json.load(stream)
    except (OSError, ValueError) as exc:
        raise PhotoTransferError("照片清单不存在、不可读取或JSON格式错误，请先完成导出") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(manifest, dict) or set(manifest) != {"version", "photos", "created_at"}:
        raise PhotoTransferError("照片清单格式错误")
    if type(manifest["version"]) is not int or manifest["version"] != 1 or not isinstance(manifest["photos"], list):
        raise PhotoTransferError("照片清单版本或照片列表格式错误")
    try:
        if not isinstance(manifest["created_at"], str):
            raise ValueError()
        datetime.fromisoformat(manifest["created_at"])
    except ValueError as exc:
        raise PhotoTransferError("照片清单导出时间格式错误") from exc
    uids, paths = set(), set()
    for entry in manifest["photos"]:
        _validate_entry(entry)
        if entry["uid"] in uids or entry["storage_path"] in paths:
            raise PhotoTransferError("照片清单包含重复记录编号或重复文件路径")
        uids.add(entry["uid"])
        paths.add(entry["storage_path"])
    return manifest["photos"]


def _verify_snapshot(rows, entries):
    by_uid = {entry["uid"]: entry for entry in entries}
    if len(rows) != len(entries) or {row["uid"] for row in rows} != set(by_uid):
        raise PhotoTransferError("数据库照片记录集合已变化或导出清单漏项，请停止迁移并重新导出")
    for row in rows:
        if _original_metadata(row) != _original_metadata(by_uid[row["uid"]]):
            raise PhotoTransferError("数据库照片元数据与导出清单不一致，请停止迁移并重新导出")


def _write_manifest(path, entries):
    _check_manifest_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".photo-manifest-", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            json.dump({"version": 1, "photos": entries,
                       "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                      stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def export_photos(connection, manifest_path=None):
    """Read the original table only; publish the manifest after every verification."""
    table = _table(connection)
    _require_columns(table, ORIGINAL_FIELDS + ("data",))
    entries = []
    for row in _rows(connection, table, ORIGINAL_FIELDS + ("data",)):
        source = row.pop("data")
        if not isinstance(source, (bytes, bytearray, memoryview)):
            raise PhotoTransferError("数据库照片缺少有效原始字节，导出已停止")
        metadata = storage.save_bytes(row["intake_uid"], row["uid"], row["mime_type"], bytes(source))
        entry = {**row, **metadata}
        _validate_entry(entry)
        entries.append(entry)
    # Recheck the complete snapshot and files before replacing an earlier manifest.
    _verify_snapshot(list(_rows(connection, table, ORIGINAL_FIELDS)), entries)
    for entry in entries:
        storage.read_bytes(SimpleNamespace(**entry))
    path = _manifest_path(manifest_path)
    _write_manifest(path, entries)
    return {"exported_files": len(entries), "total_bytes": sum(entry["size_bytes"] for entry in entries),
            "manifest_path": str(path)}


def validate_manifest(connection, manifest_path=None, verify_blobs=False):
    table = _table(connection)
    fields = ORIGINAL_FIELDS + (("data",) if verify_blobs else ())
    _require_columns(table, fields)
    rows = list(_rows(connection, table, ORIGINAL_FIELDS))
    path = _manifest_path(manifest_path)
    _check_manifest_parent(path)
    if not rows and not path.exists():
        return []
    entries = _read_manifest(path)
    _verify_snapshot(rows, entries)
    by_uid = {entry["uid"]: entry for entry in entries}
    verified_uids = set()
    # Keep source BLOB memory bounded to one photograph even for a large archive.
    for row in _rows(connection, table, fields):
        if row["uid"] not in by_uid or _original_metadata(row) != _original_metadata(by_uid[row["uid"]]):
            raise PhotoTransferError("数据库照片记录在核验期间发生变化，请停止迁移并重新导出")
        entry = by_uid[row["uid"]]
        storage.read_bytes(SimpleNamespace(**entry))
        if verify_blobs:
            data = row["data"]
            if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) != entry["size_bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise PhotoTransferError("数据库照片内容与导出文件不一致，请停止迁移并重新导出")
        verified_uids.add(row["uid"])
    if verified_uids != set(by_uid):
        raise PhotoTransferError("数据库照片记录在核验期间发生变化，请停止迁移并重新导出")
    return entries


def import_photo_paths(connection, manifest_path=None):
    """Validate all entries before updating; the caller owns the SQL transaction."""
    table = _table(connection)
    _require_columns(table, ORIGINAL_FIELDS + FILE_FIELDS)
    if "data" in table.c:
        raise PhotoTransferError("数据库仍含照片二进制字段，请先执行schema迁移再回填路径")
    entries = validate_manifest(connection, manifest_path)
    by_uid = {entry["uid"]: entry for entry in entries}
    existing = list(_rows(connection, table, ORIGINAL_FIELDS + FILE_FIELDS))
    _verify_snapshot(existing, entries)
    for row in existing:
        entry = by_uid[row["uid"]]
        if any(row[name] is not None and row[name] != entry[name] for name in FILE_FIELDS):
            raise PhotoTransferError("数据库已有不同的照片路径或校验信息，回填已停止")
    for entry in entries:
        conditions = [table.c[name] == entry[name] for name in ORIGINAL_FIELDS]
        conditions.extend(sa.or_(table.c[name].is_(None), table.c[name] == entry[name]) for name in FILE_FIELDS)
        result = connection.execute(table.update().where(sa.and_(*conditions)).values(
            **{name: entry[name] for name in FILE_FIELDS},
        ))
        if result.rowcount != 1:
            raise PhotoTransferError("照片记录在回填期间发生变化，回填已停止")
    columns = {column["name"]: column for column in sa.inspect(connection).get_columns("paper_intake_photos")}
    operations = Operations(MigrationContext.configure(connection))
    with operations.batch_alter_table("paper_intake_photos") as batch:
        for name, column_type in (("storage_path", sa.String(512)), ("size_bytes", sa.BigInteger()), ("sha256", sa.String(64))):
            if columns[name]["nullable"]:
                batch.alter_column(name, existing_type=column_type, nullable=False)
    return {"updated_files": len(entries), "total_bytes": sum(entry["size_bytes"] for entry in entries)}
