"""
Worker/finance service.

提供工作详情、预计奖金和财务汇总计算。
"""

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func

from data.database import SessionFactory
from data.finance import bonus_rate_model
from data.packing.PackingList import BoxTable, BoxWorkerTable, PackingListTable
from data.user.User import UserTable


def normalize_month(month: Optional[str] = None) -> str:
    """规范化月份参数，格式 YYYY-MM。"""
    if not month:
        return datetime.now().strftime("%Y-%m")

    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError("month must be YYYY-MM") from exc

    return month


def get_workers() -> List[dict]:
    """获取已审核通过的操作人员列表。"""
    with SessionFactory() as session:
        records = (
            session.query(UserTable)
            .filter(UserTable.status == "approved", UserTable.role == "worker")
            .order_by(UserTable.name.asc())
            .all()
        )

        return [
            {
                "id": record.id,
                "name": record.name,
                "phone": record.phone,
            }
            for record in records
        ]


def get_bonus_rates() -> Dict[str, float]:
    """获取 1~4 人合打的奖金基数。"""
    return bonus_rate_model.get_rate_map()


def set_bonus_rates(
    rates: Dict[int, float], operator_id: Optional[int] = None
) -> Dict[str, float]:
    """设置奖金基数。"""
    bonus_rate_model.set_rates(rates, operator_id=operator_id)
    return bonus_rate_model.get_rate_map()


def get_worker_work_details(worker_id: int, month: Optional[str] = None) -> dict:
    """获取某个工人的工作详情。"""
    month = normalize_month(month)

    with SessionFactory() as session:
        worker = session.query(UserTable).filter_by(id=worker_id).first()
        if worker is None:
            raise ValueError("worker not found")

        worker_count_subq = (
            session.query(
                BoxWorkerTable.box_uid.label("box_uid"),
                func.count(BoxWorkerTable.worker_id).label("worker_count"),
            )
            .group_by(BoxWorkerTable.box_uid)
            .subquery()
        )

        rows = (
            session.query(
                BoxTable.uid.label("box_uid"),
                BoxTable.box_number,
                BoxTable.item_name,
                BoxTable.piece_count,
                BoxTable.weight,
                BoxTable.status.label("box_status"),
                BoxTable.create_date,
                PackingListTable.uid.label("packing_list_uid"),
                PackingListTable.list_number.label("mark"),
                PackingListTable.status.label("packing_status"),
                worker_count_subq.c.worker_count,
            )
            .join(BoxWorkerTable, BoxWorkerTable.box_uid == BoxTable.uid)
            .join(PackingListTable, PackingListTable.uid == BoxTable.packing_list_uid)
            .join(worker_count_subq, worker_count_subq.c.box_uid == BoxTable.uid)
            .filter(
                BoxWorkerTable.worker_id == worker_id,
                BoxTable.archive == False,
                PackingListTable.archive == False,
                BoxTable.create_date.like(f"{month}-%"),
            )
            .order_by(BoxTable.create_date.desc(), BoxTable.box_number.desc())
            .all()
        )

        items = []
        counts_by_team_size = {str(i): 0 for i in range(1, 5)}

        for row in rows:
            worker_count = int(row.worker_count or 0)
            key = str(worker_count)
            if key in counts_by_team_size:
                counts_by_team_size[key] += 1

            items.append(
                {
                    "box_uid": row.box_uid,
                    "packing_list_uid": row.packing_list_uid,
                    "mark": row.mark,
                    "box_number": row.box_number,
                    "item_name": row.item_name,
                    "piece_count": row.piece_count,
                    "weight": row.weight,
                    "box_status": row.box_status,
                    "packing_status": row.packing_status,
                    "worker_count": worker_count,
                    "create_date": row.create_date,
                }
            )

        return {
            "month": month,
            "worker": {
                "id": worker.id,
                "name": worker.name,
                "phone": worker.phone,
            },
            "items": items,
            "counts_by_team_size": counts_by_team_size,
            "total_boxes": len(items),
            "total_piece_count": sum(
                int(item.get("piece_count") or 0) for item in items
            ),
        }


def get_bonus_estimate(worker_id: int, month: Optional[str] = None) -> dict:
    """获取某工人的预计奖金。"""
    details = get_worker_work_details(worker_id=worker_id, month=month)
    rates = get_bonus_rates()

    estimated_bonus = 0.0
    for size in range(1, 5):
        key = str(size)
        estimated_bonus += details["counts_by_team_size"][key] * float(
            rates.get(key, 0.0)
        )

    return {
        **details,
        "rates": rates,
        "estimated_bonus": round(estimated_bonus, 2),
    }


def get_bonus_overview(
    month: Optional[str] = None, worker_id: Optional[int] = None
) -> dict:
    """获取工人预计奖金汇总（财务视角）。"""
    month = normalize_month(month)
    workers = get_workers()

    if worker_id is not None:
        workers = [worker for worker in workers if worker["id"] == worker_id]

    rates = get_bonus_rates()
    items = []

    totals = {
        "counts_by_team_size": {str(i): 0 for i in range(1, 5)},
        "total_boxes": 0,
        "total_piece_count": 0,
        "estimated_bonus": 0.0,
    }

    for worker in workers:
        estimate = get_bonus_estimate(worker_id=worker["id"], month=month)

        item = {
            "worker_id": worker["id"],
            "worker_name": worker["name"],
            "worker_phone": worker["phone"],
            "counts_by_team_size": estimate["counts_by_team_size"],
            "total_boxes": estimate["total_boxes"],
            "total_piece_count": estimate["total_piece_count"],
            "estimated_bonus": estimate["estimated_bonus"],
        }
        items.append(item)

        totals["total_boxes"] += item["total_boxes"]
        totals["total_piece_count"] += item["total_piece_count"]
        totals["estimated_bonus"] += item["estimated_bonus"]

        for size in range(1, 5):
            key = str(size)
            totals["counts_by_team_size"][key] += item["counts_by_team_size"][key]

    totals["estimated_bonus"] = round(totals["estimated_bonus"], 2)

    return {
        "month": month,
        "rates": rates,
        "items": items,
        "totals": totals,
    }
