"""Step one: export legacy private photos without changing the database."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from services.paper_photo_transfer import PhotoTransferError, export_photos


def main(argv=None):
    parser = argparse.ArgumentParser(description="导出数据库原始照片到持久化目录，并生成核验清单")
    parser.add_argument("--manifest", type=Path, help="导出清单路径；三步必须使用同一清单")
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
            result = export_photos(connection, args.manifest)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except PhotoTransferError as exc:
        print(f"照片导出失败：{exc}", file=sys.stderr)
        return 1
    except Exception:
        print("照片导出失败：请检查数据库连接、照片文件及目录权限", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
