"""Read-only startup gate for the three-step paper photo storage migration.

This module deliberately uses SQLAlchemy Core without importing the application
or ORM models. It never exports photos, changes schema, or backfills records.
"""

import os
import sys
from urllib.parse import quote

import sqlalchemy as sa


_METADATA_COLUMNS = ("storage_path", "size_bytes", "sha256")
_NEXT_STEPS = "请先导出照片、执行迁移、回填文件路径后再启动"


class PhotoStorageNotReady(RuntimeError):
    """The new application must not start against incomplete photo storage."""

    def __init__(self, reason, pending_count=None):
        count = "未知" if pending_count is None else str(pending_count)
        super().__init__(f"{reason}；{_NEXT_STEPS}。待回填照片数量：{count}。")
        self.pending_count = pending_count


def assert_ready(connection) -> None:
    """Raise PhotoStorageNotReady unless photo metadata and schema are ready."""
    inspector = sa.inspect(connection)
    if not inspector.has_table("paper_intake_photos"):
        raise PhotoStorageNotReady("缺少纸单照片表 paper_intake_photos")

    columns = {column["name"]: column for column in inspector.get_columns("paper_intake_photos")}
    photos = sa.table("paper_intake_photos", *(sa.column(name) for name in _METADATA_COLUMNS if name in columns))
    missing = [name for name in _METADATA_COLUMNS if name not in columns]
    if missing:
        count = connection.execute(sa.select(sa.func.count()).select_from(photos)).scalar_one()
        raise PhotoStorageNotReady("缺少照片文件元数据列 " + ", ".join(missing), count)

    incomplete = sa.or_(
        photos.c.storage_path.is_(None),
        sa.func.trim(photos.c.storage_path) == "",
        photos.c.size_bytes.is_(None),
        photos.c.size_bytes < 0,
        photos.c.sha256.is_(None),
        sa.func.trim(photos.c.sha256) == "",
    )
    count = connection.execute(sa.select(sa.func.count()).select_from(photos).where(incomplete)).scalar_one()
    if "data" in columns:
        raise PhotoStorageNotReady("旧照片二进制列 data 尚未移除", count)
    if count:
        raise PhotoStorageNotReady("照片文件路径、大小或 SHA-256 尚未完整回填", count)

    nullable = [name for name in _METADATA_COLUMNS if columns[name]["nullable"]]
    if nullable:
        raise PhotoStorageNotReady("照片元数据 NOT NULL 约束尚未完成：" + ", ".join(nullable), count)
    if not inspector.has_table("paper_photo_cleanup"):
        raise PhotoStorageNotReady("缺少照片清理队列表 paper_photo_cleanup", count)


def _create_readonly_engine(database_url):
    url = sa.engine.make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        database = url.database if url.database.startswith("file:") else "file:" + quote(url.database, safe="/:")
        url = url.set(database=database, query={**url.query, "uri": "true", "mode": "ro"})
    return sa.create_engine(url, echo=False, hide_parameters=True)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("照片存储就绪检查失败：未设置 DATABASE_URL。", file=sys.stderr)
        return 1
    engine = None
    try:
        engine = _create_readonly_engine(database_url)
        with engine.connect() as connection:
            assert_ready(connection)
    except PhotoStorageNotReady as error:
        print(f"照片存储就绪检查失败：{error}", file=sys.stderr)
        return 1
    except Exception:
        # Database exceptions can contain passwords, hostnames and full URLs.
        print("照片存储就绪检查失败：数据库连接或读取失败。", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
    print("纸单照片文件存储就绪检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
