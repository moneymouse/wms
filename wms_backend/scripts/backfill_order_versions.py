#!/usr/bin/env python3
"""Idempotently create V1 baselines for all live and archived orders."""

from __future__ import annotations

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data.database import SessionFactory  # noqa: E402
from data.DB import OrderTable  # noqa: E402
from data.order_version import (  # noqa: E402
    OrderVersionTable,
    ensure_baseline,
    snapshot_order,
)


def backfill(batch_size: int = 100) -> dict:
    with SessionFactory() as session:
        order_uids = [
            row[0]
            for row in session.query(OrderTable.uid)
            .order_by(OrderTable.uid.asc())
            .all()
        ]

    created = 0
    skipped = 0
    for offset in range(0, len(order_uids), batch_size):
        for order_uid in order_uids[offset : offset + batch_size]:
            with SessionFactory() as session:
                try:
                    snapshot = snapshot_order(session, order_uid, lock=True)
                    if snapshot is None:
                        skipped += 1
                    elif ensure_baseline(session, order_uid, snapshot) is not None:
                        created += 1
                    else:
                        skipped += 1
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

    with SessionFactory() as session:
        current_order_uids = [row[0] for row in session.query(OrderTable.uid).all()]
        baseline_count = (
            session.query(OrderVersionTable.order_uid)
            .filter(
                OrderVersionTable.order_uid.in_(current_order_uids),
                OrderVersionTable.version_no == 1,
                OrderVersionTable.action == "baseline_import",
            )
            .distinct()
            .count()
        )
        v1_coverage = (
            session.query(OrderVersionTable.order_uid)
            .filter(
                OrderVersionTable.order_uid.in_(current_order_uids),
                OrderVersionTable.version_no == 1,
            )
            .distinct()
            .count()
        )
        order_count = len(current_order_uids)
    return {
        "orders": order_count,
        "baseline_imports": baseline_count,
        "v1_coverage": v1_coverage,
        "created": created,
        "skipped": skipped,
        "verified": order_count == v1_coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    result = backfill(args.batch_size)
    print(
        "orders={orders} baseline_imports={baseline_imports} "
        "v1_coverage={v1_coverage} created={created} "
        "skipped={skipped} verified={verified}".format(**result)
    )
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
