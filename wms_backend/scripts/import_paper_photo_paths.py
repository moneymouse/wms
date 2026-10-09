"""Step three: explicitly backfill verified paths after the schema migration."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from services.paper_photo_transfer import PhotoTransferError, import_photo_paths


def main(argv=None):
    parser = argparse.ArgumentParser(description="核验导出清单后，手动回填照片路径、大小和SHA256")
    parser.add_argument("--manifest", type=Path, help="第一步生成的导出清单路径")
    parser.add_argument("--storage-root", type=Path, help="持久化照片目录（设置PAPER_PHOTO_ROOT）")
    args = parser.parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("请显式设置DATABASE_URL；脚本不会猜测数据库连接")
    if args.storage_root is not None:
        os.environ["PAPER_PHOTO_ROOT"] = str(args.storage_root.expanduser().absolute())
    engine = None
    try:
        engine = create_engine(database_url, echo=False)
        with engine.begin() as connection:
            result = import_photo_paths(connection, args.manifest)
        print(json.dumps({**result, "msg": f"已核对并回填/确认 {result['updated_files']} 条照片"}, ensure_ascii=False))
        return 0
    except PhotoTransferError as exc:
        print(f"照片路径回填失败：{exc}", file=sys.stderr)
        return 1
    except Exception:
        print("照片路径回填失败：请检查数据库迁移阶段、照片清单及目录权限", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
