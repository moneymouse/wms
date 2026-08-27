"""Worker/finance service.

新奖金体系：
- 按奖金分项（标签）统计
- 按规则（人数精确 + 重量区间）自动建议分项
- 财务可对未分配装箱单进行二次分配（工人 + 分项）
"""

import time
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func

from data.database import SessionFactory
from data.DB import CargoTable, OrderQuoteVersionTable, OrderTable
from data.finance import bonus_item_model
from data.finance.BonusItem import BonusItemTable
from data.packing.PackingList import BoxTable, BoxWorkerTable, PackingListTable
from data.user.User import UserTable
from data.user.Role import RoleTable, user_roles
from services import receivable_service


def normalize_month(month: Optional[str] = None) -> str:
    """规范化月份参数，格式 YYYY-MM。"""
    if not month:
        return datetime.now().strftime("%Y-%m")

    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise ValueError("month must be YYYY-MM") from exc

    return month


def get_workers(role_names: Optional[List[str]] = None) -> List[dict]:
    """获取已审核通过的人员列表，默认仅返回操作人员。"""
    if not role_names:
        role_names = ["worker"]

    with SessionFactory() as session:
        records = (
            session.query(UserTable)
            .join(user_roles, UserTable.id == user_roles.c.user_id)
            .join(RoleTable, RoleTable.id == user_roles.c.role_id)
            .filter(UserTable.status == "approved", RoleTable.name.in_(role_names))
            .order_by(UserTable.name.asc())
            .distinct()
            .all()
        )

        return [
            {
                "id": record.id,
                "name": record.name,
                "phone": record.phone,
                "roles": [role.name for role in record.roles],
            }
            for record in records
        ]


def _validate_bonus_item_payload(payload: dict, partial: bool = False) -> dict:
    normalized = {}

    if not partial or "label" in payload:
        label = (payload.get("label") or "").strip()
        if not label:
            raise ValueError("label is required")
        normalized["label"] = label

    if not partial or "base_amount" in payload:
        try:
            base_amount = float(payload.get("base_amount"))
        except (TypeError, ValueError) as exc:
            raise ValueError("base_amount must be numeric") from exc
        if base_amount < 0:
            raise ValueError("base_amount must be >= 0")
        normalized["base_amount"] = base_amount

    if not partial or "worker_count_rule" in payload:
        try:
            worker_count_rule = int(payload.get("worker_count_rule"))
        except (TypeError, ValueError) as exc:
            raise ValueError("worker_count_rule must be integer") from exc
        if worker_count_rule <= 0:
            raise ValueError("worker_count_rule must be > 0")
        normalized["worker_count_rule"] = worker_count_rule

    if not partial or "weight_min" in payload:
        try:
            weight_min = float(payload.get("weight_min"))
        except (TypeError, ValueError) as exc:
            raise ValueError("weight_min must be numeric") from exc
        if weight_min < 0:
            raise ValueError("weight_min must be >= 0")
        normalized["weight_min"] = weight_min

    if not partial or "weight_max" in payload:
        try:
            weight_max = float(payload.get("weight_max"))
        except (TypeError, ValueError) as exc:
            raise ValueError("weight_max must be numeric") from exc
        if weight_max < 0:
            raise ValueError("weight_max must be >= 0")
        normalized["weight_max"] = weight_max

    if "weight_min" in normalized and "weight_max" in normalized:
        if normalized["weight_max"] < normalized["weight_min"]:
            raise ValueError("weight_max must be >= weight_min")

    if "is_active" in payload:
        normalized["is_active"] = bool(payload.get("is_active"))

    return normalized


def get_bonus_items(active_only: bool = True) -> List[dict]:
    return bonus_item_model.list_items(active_only=active_only)


def create_bonus_item(payload: dict, operator_id: Optional[int] = None) -> dict:
    data = _validate_bonus_item_payload(payload, partial=False)
    return bonus_item_model.create_item(
        label=data["label"],
        base_amount=data["base_amount"],
        worker_count_rule=data["worker_count_rule"],
        weight_min=data["weight_min"],
        weight_max=data["weight_max"],
        operator_id=operator_id,
    )


def update_bonus_item(
    item_id: int,
    payload: dict,
    operator_id: Optional[int] = None,
) -> Optional[dict]:
    data = _validate_bonus_item_payload(payload, partial=True)
    return bonus_item_model.update_item(
        item_id=item_id, data=data, operator_id=operator_id
    )


def disable_bonus_item(
    item_id: int, operator_id: Optional[int] = None
) -> Optional[dict]:
    return bonus_item_model.update_item(
        item_id=item_id,
        data={"is_active": False},
        operator_id=operator_id,
    )


def _pick_bonus_item(
    session, worker_count: int, weight: Optional[float]
) -> Optional[BonusItemTable]:
    if worker_count <= 0:
        return None

    box_weight = float(weight or 0.0)
    candidates = (
        session.query(BonusItemTable)
        .filter(
            BonusItemTable.is_active == True,
            BonusItemTable.worker_count_rule == worker_count,
            BonusItemTable.weight_min <= box_weight,
            BonusItemTable.weight_max >= box_weight,
        )
        .all()
    )
    if not candidates:
        return None

    # 区间越窄优先，区间相同按 ID 升序稳定选择
    candidates.sort(key=lambda item: ((item.weight_max - item.weight_min), item.id))
    return candidates[0]


def get_worker_work_details(worker_id: int, month: Optional[str] = None) -> dict:
    """获取某个员工的工作详情（打包工作 + 业务员订单）。"""
    month = normalize_month(month)

    with SessionFactory() as session:
        worker = session.query(UserTable).filter_by(id=worker_id).first()
        if worker is None:
            raise ValueError("user not found")
        worker_roles = [role.name for role in worker.roles]

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
                BoxTable.box_status.label("box_status"),
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
            .order_by(
                BoxTable.create_date.desc(),
                PackingListTable.list_number.asc(),
                BoxTable.box_number.asc(),
            )
            .all()
        )

        items: List[dict] = []
        counts_by_team_size = {str(i): 0 for i in range(1, 5)}
        groups_map: Dict[str, dict] = {}

        for row in rows:
            worker_count = int(row.worker_count or 0)
            team_key = str(worker_count)
            if team_key in counts_by_team_size:
                counts_by_team_size[team_key] += 1

            item = {
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
            items.append(item)

            group = groups_map.get(row.packing_list_uid)
            if group is None:
                group = {
                    "packing_list_uid": row.packing_list_uid,
                    "mark": row.mark,
                    "create_date": row.create_date,
                    "box_count": 0,
                    "total_weight": 0.0,
                    "boxes": [],
                }
                groups_map[row.packing_list_uid] = group

            group["box_count"] += 1
            group["total_weight"] += float(row.weight or 0.0)
            group["boxes"].append(
                {
                    "box_uid": row.box_uid,
                    "box_number": row.box_number,
                    "item_name": row.item_name,
                    "weight": float(row.weight or 0.0),
                    "worker_count": worker_count,
                    "create_date": row.create_date,
                }
            )

        groups = list(groups_map.values())
        for group in groups:
            group["total_weight"] = round(group["total_weight"], 2)
            group["boxes"] = sorted(
                group["boxes"],
                key=lambda box: (box.get("box_number") or 0, box.get("box_uid") or ""),
            )

        groups.sort(
            key=lambda group: (group.get("create_date") or "", group.get("mark") or ""),
            reverse=True,
        )

        order_rows = (
            session.query(OrderQuoteVersionTable, OrderTable)
            .join(OrderTable, OrderTable.uid == OrderQuoteVersionTable.order_uid)
            .filter(
                OrderTable.archive == False,  # noqa: E712
                OrderQuoteVersionTable.quoter_id == worker_id,
                OrderQuoteVersionTable.is_final == True,  # noqa: E712
                OrderQuoteVersionTable.status.in_(["adopted", "approved"]),
                OrderQuoteVersionTable.effective_date.like(f"{month}-%"),
            )
            .order_by(OrderQuoteVersionTable.effective_date.desc(), OrderTable.order_id.asc())
            .all()
        )
        orders = []
        for quote, order in order_rows:
            if not receivable_service.quote_is_fresh(session, quote):
                continue
            orders.append({
                "uid": order.uid,
                "order_id": order.order_id,
                "total_weight": float(quote.weight_snapshot or 0.0),
                "transportation": order.transportation,
                "create_date": order.create_date,
                "quote_effective_date": quote.effective_date,
                "quoter_name": quote.quoter_name,
            })

        return {
            "month": month,
            "worker": {
                "id": worker.id,
                "name": worker.name,
                "phone": worker.phone,
                "roles": worker_roles,
            },
            "groups": groups,
            "items": items,
            "orders": orders,
            "counts_by_team_size": counts_by_team_size,
            "total_boxes": len(items),
            "total_orders": len(orders),
            "followup_order_count": len(orders),
            "followup_total_weight": round(
                sum(float(order.get("total_weight") or 0.0) for order in orders), 3
            ),
            "total_piece_count": sum(
                int(item.get("piece_count") or 0) for item in items
            ),
            "total_weight": round(
                sum(float(item.get("weight") or 0.0) for item in items), 2
            ),
        }


def get_pending_bonus_allocation_packing_lists(
    month: Optional[str] = None,
    mark_search: Optional[str] = None,
) -> dict:
    """获取未进行奖金分配的装箱单及其箱子。允许 draft 和 completed 状态。"""
    if month:
        month = normalize_month(month)

    with SessionFactory() as session:
        q = session.query(PackingListTable).filter(
            PackingListTable.archive == False,
            PackingListTable.status.in_(["draft", "completed"]),
        )

        if month:
            q = q.filter(PackingListTable.create_date.like(f"{month}-%"))

        if mark_search:
            mark_search = mark_search.strip().upper()
            q = q.filter(PackingListTable.list_number.like(f"%{mark_search}%"))

        packing_lists = q.order_by(PackingListTable.create_date.desc()).all()
        items = []

        for packing_list in packing_lists:
            all_boxes = sorted(
                [box for box in packing_list.boxes if not box.archive],
                key=lambda box: (box.box_number or 0),
            )
            if not all_boxes:
                continue

            pending_boxes = [box for box in all_boxes if not box.bonus_assigned]
            if not pending_boxes:
                continue

            row_boxes = []
            for box in pending_boxes:
                workers = sorted(
                    [
                        {
                            "worker_id": worker.worker_id,
                            "worker_name": worker.worker.name if worker.worker else "",
                        }
                        for worker in box.workers
                    ],
                    key=lambda worker: worker["worker_id"],
                )

                worker_ids = [worker["worker_id"] for worker in workers]
                worker_count = len(worker_ids)
                suggested_item = _pick_bonus_item(session, worker_count, box.weight)

                row_boxes.append(
                    {
                        "box_uid": box.uid,
                        "box_number": box.box_number,
                        "item_name": box.item_name,
                        "piece_count": int(box.piece_count or 0),
                        "weight": float(box.weight or 0.0),
                        "worker_ids": worker_ids,
                        "workers": workers,
                        "worker_count": worker_count,
                        "bonus_item_id": box.bonus_item_id,
                        "suggested_bonus_item_id": (
                            suggested_item.id if suggested_item else None
                        ),
                        "suggested_bonus_item_label": (
                            suggested_item.label if suggested_item else None
                        ),
                    }
                )

            items.append(
                {
                    "packing_list_uid": packing_list.uid,
                    "mark": packing_list.list_number,
                    "status": packing_list.status,
                    "customer_name": (
                        packing_list.customer.name if packing_list.customer else None
                    ),
                    "create_date": packing_list.create_date,
                    "box_count": len(all_boxes),
                    "pending_box_count": len(row_boxes),
                    "total_weight": round(
                        sum(float(box.weight or 0.0) for box in all_boxes), 2
                    ),
                    "boxes": row_boxes,
                }
            )

        return {
            "month": month,
            "items": items,
            "total": len(items),
        }


def assign_bonus_for_packing_list(
    packing_list_uid: str,
    assignments: List[dict],
    operator_id: Optional[int] = None,
) -> dict:
    """对某装箱单进行奖金分配。"""
    now = time.strftime("%Y-%m-%d %H:%M")

    with SessionFactory() as session:
        packing_list = (
            session.query(PackingListTable)
            .filter(
                PackingListTable.uid == packing_list_uid,
                PackingListTable.archive == False,
            )
            .first()
        )
        if packing_list is None:
            raise ValueError("packing list not found")

        # if packing_list.status != "completed":
        #     raise ValueError("only completed packing list can be allocated")

        if not assignments:
            raise ValueError("assignments is required")

        active_item_ids = {
            item.id
            for item in session.query(BonusItemTable)
            .filter(BonusItemTable.is_active == True)
            .all()
        }
        if not active_item_ids:
            raise ValueError("no active bonus items configured")

        box_map = {box.uid: box for box in packing_list.boxes if not box.archive}

        for row in assignments:
            box_uid = row.get("box_uid")
            if not box_uid:
                raise ValueError("box_uid is required in assignments")

            box = box_map.get(box_uid)
            if box is None:
                raise ValueError(f"box {box_uid} not found in packing list")

            worker_ids = row.get("worker_ids")
            if worker_ids is None:
                worker_ids = [worker.worker_id for worker in box.workers]

            worker_ids = [int(worker_id) for worker_id in worker_ids]
            worker_ids = list(dict.fromkeys(worker_ids))

            if len(worker_ids) == 0:
                raise ValueError(f"box {box_uid} must have at least one worker")
            if len(worker_ids) > 4:
                raise ValueError(f"box {box_uid} supports at most 4 workers")

            valid_workers = (
                session.query(UserTable)
                .join(user_roles, UserTable.id == user_roles.c.user_id)
                .join(RoleTable, RoleTable.id == user_roles.c.role_id)
                .filter(
                    UserTable.id.in_(worker_ids),
                    UserTable.status == "approved",
                    RoleTable.name == "worker",
                )
                .all()
            )
            if len(valid_workers) != len(worker_ids):
                raise ValueError(f"box {box_uid} has invalid worker_ids")

            bonus_item_id = row.get("bonus_item_id")
            if bonus_item_id is None:
                suggested_item = _pick_bonus_item(session, len(worker_ids), box.weight)
                if suggested_item is None:
                    raise ValueError(
                        f"box {box_uid} has no matched bonus item, please select manually"
                    )
                bonus_item_id = suggested_item.id

            bonus_item_id = int(bonus_item_id)
            if bonus_item_id not in active_item_ids:
                raise ValueError(f"box {box_uid} selected inactive bonus item")

            session.query(BoxWorkerTable).filter(
                BoxWorkerTable.box_uid == box_uid
            ).delete()
            for worker_id in worker_ids:
                session.add(
                    BoxWorkerTable(
                        box_uid=box_uid,
                        worker_id=worker_id,
                        create_date=now,
                    )
                )

            box.bonus_item_id = bonus_item_id
            box.bonus_assigned = True
            box.bonus_assigned_by = operator_id
            box.bonus_assigned_date = now
            box.update_date = now

        session.commit()

        remaining_unassigned = (
            session.query(BoxTable)
            .filter(
                BoxTable.packing_list_uid == packing_list_uid,
                BoxTable.archive == False,
                BoxTable.bonus_assigned == False,
            )
            .count()
        )

        return {
            "packing_list_uid": packing_list_uid,
            "assigned_box_count": len(assignments),
            "remaining_unassigned_box_count": remaining_unassigned,
        }


def get_worker_bonus_summary(worker_id: int, month: Optional[str] = None) -> dict:
    """获取某工人的当月奖金统计（按天、按奖金分项）。"""
    month = normalize_month(month)

    with SessionFactory() as session:
        worker = session.query(UserTable).filter_by(id=worker_id).first()
        if worker is None:
            raise ValueError("worker not found")
        worker_roles = [role.name for role in worker.roles]

        active_items = (
            session.query(BonusItemTable)
            .filter(BonusItemTable.is_active == True)
            .order_by(BonusItemTable.worker_count_rule.asc(), BonusItemTable.id.asc())
            .all()
        )
        item_map = {item.id: item for item in active_items}

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
                BoxTable.piece_count,
                BoxTable.weight,
                BoxTable.bonus_item_id,
                BoxTable.create_date,
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
            .order_by(BoxTable.create_date.asc(), BoxTable.box_number.asc())
            .all()
        )

        daily_map: Dict[str, dict] = {}
        totals = {
            "by_item": {},
            "total_boxes": 0,
            "total_piece_count": 0,
            "estimated_bonus": 0.0,
        }

        def ensure_item_bucket(target: dict, item_key: str) -> None:
            if item_key not in target:
                target[item_key] = {
                    "label": "",
                    "base_amount": 0.0,
                    "box_count": 0,
                    "piece_count": 0,
                    "estimated_bonus": 0.0,
                }

        for row in rows:
            create_date = row.create_date or ""
            day = create_date[:10] if len(create_date) >= 10 else create_date
            if day not in daily_map:
                daily_map[day] = {
                    "date": day,
                    "by_item": {},
                    "total_boxes": 0,
                    "total_piece_count": 0,
                    "estimated_bonus": 0.0,
                }

            worker_count = int(row.worker_count or 0)
            bonus_item = item_map.get(row.bonus_item_id)
            if bonus_item is None:
                bonus_item = _pick_bonus_item(session, worker_count, row.weight)

            if bonus_item is None:
                item_key = "unmatched"
                item_label = "未匹配分项"
                base_amount = 0.0
            else:
                item_key = str(bonus_item.id)
                item_label = bonus_item.label
                base_amount = float(bonus_item.base_amount or 0.0)

            piece_count = int(row.piece_count or 0)
            box_bonus = base_amount

            ensure_item_bucket(daily_map[day]["by_item"], item_key)
            ensure_item_bucket(totals["by_item"], item_key)

            daily_map[day]["by_item"][item_key]["label"] = item_label
            daily_map[day]["by_item"][item_key]["base_amount"] = base_amount
            daily_map[day]["by_item"][item_key]["box_count"] += 1
            daily_map[day]["by_item"][item_key]["piece_count"] += piece_count
            daily_map[day]["by_item"][item_key]["estimated_bonus"] += box_bonus

            daily_map[day]["total_boxes"] += 1
            daily_map[day]["total_piece_count"] += piece_count
            daily_map[day]["estimated_bonus"] += box_bonus

            totals["by_item"][item_key]["label"] = item_label
            totals["by_item"][item_key]["base_amount"] = base_amount
            totals["by_item"][item_key]["box_count"] += 1
            totals["by_item"][item_key]["piece_count"] += piece_count
            totals["by_item"][item_key]["estimated_bonus"] += box_bonus

            totals["total_boxes"] += 1
            totals["total_piece_count"] += piece_count
            totals["estimated_bonus"] += box_bonus

        followup = (
            receivable_service.salesperson_followup_bonus(worker_id, month)
            if "salesperson" in worker_roles
            else {
                "order_count": 0,
                "total_weight": 0.0,
                "estimated_bonus": 0.0,
                "orders": [],
                "rate_configured": True,
            }
        )
        operation_bonus = round(float(totals["estimated_bonus"]), 2)
        for order_row in followup["orders"]:
            day = (order_row.get("effective_date") or "")[:10]
            if day not in daily_map:
                daily_map[day] = {
                    "date": day,
                    "by_item": {},
                    "total_boxes": 0,
                    "total_piece_count": 0,
                    "estimated_bonus": 0.0,
                }
            daily_map[day]["followup_weight"] = round(
                float(daily_map[day].get("followup_weight") or 0)
                + float(order_row.get("weight") or 0),
                3,
            )
            daily_map[day]["followup_bonus"] = round(
                float(daily_map[day].get("followup_bonus") or 0)
                + float(order_row.get("estimated_bonus") or 0),
                2,
            )
            daily_map[day]["estimated_bonus"] += float(order_row.get("estimated_bonus") or 0)

        totals["operation_estimated_bonus"] = operation_bonus
        totals["followup_weight"] = followup["total_weight"]
        totals["followup_order_count"] = followup["order_count"]
        totals["followup_estimated_bonus"] = followup["estimated_bonus"]
        totals["estimated_bonus"] += float(followup["estimated_bonus"] or 0)

        daily = [daily_map[key] for key in sorted(daily_map.keys())]

        for row in daily:
            row["estimated_bonus"] = round(float(row["estimated_bonus"]), 2)
            for item_key, item_row in row["by_item"].items():
                row["by_item"][item_key]["estimated_bonus"] = round(
                    float(item_row["estimated_bonus"]), 2
                )

        totals["estimated_bonus"] = round(float(totals["estimated_bonus"]), 2)
        for item_key, item_row in totals["by_item"].items():
            totals["by_item"][item_key]["estimated_bonus"] = round(
                float(item_row["estimated_bonus"]), 2
            )

        return {
            "month": month,
            "worker": {
                "id": worker.id,
                "name": worker.name,
                "phone": worker.phone,
                "roles": worker_roles,
            },
            "bonus_items": [
                {
                    "id": item.id,
                    "label": item.label,
                    "base_amount": float(item.base_amount or 0.0),
                    "worker_count_rule": item.worker_count_rule,
                    "weight_min": float(item.weight_min or 0.0),
                    "weight_max": float(item.weight_max or 0.0),
                }
                for item in active_items
            ],
            "daily": daily,
            "totals": totals,
            "followup": followup,
        }


def get_bonus_estimate(worker_id: int, month: Optional[str] = None) -> dict:
    """兼容旧接口，返回新奖金汇总结构。"""
    return get_worker_bonus_summary(worker_id=worker_id, month=month)


def get_bonus_overview(
    month: Optional[str] = None, worker_id: Optional[int] = None
) -> dict:
    """财务视角：按工人汇总当月奖金。"""
    month = normalize_month(month)
    workers = get_workers(role_names=["worker", "salesperson"])

    if worker_id is not None:
        workers = [worker for worker in workers if worker["id"] == worker_id]

    items = []
    totals = {
        "total_boxes": 0,
        "total_piece_count": 0,
        "estimated_bonus": 0.0,
    }

    for worker in workers:
        summary = get_worker_bonus_summary(worker_id=worker["id"], month=month)
        item = {
            "worker_id": worker["id"],
            "worker_name": worker["name"],
            "worker_phone": worker["phone"],
            "total_boxes": int(summary["totals"].get("total_boxes") or 0),
            "total_piece_count": int(summary["totals"].get("total_piece_count") or 0),
            "estimated_bonus": float(summary["totals"].get("estimated_bonus") or 0.0),
            "followup_weight": float(summary["totals"].get("followup_weight") or 0.0),
            "followup_estimated_bonus": float(summary["totals"].get("followup_estimated_bonus") or 0.0),
        }
        items.append(item)

        totals["total_boxes"] += item["total_boxes"]
        totals["total_piece_count"] += item["total_piece_count"]
        totals["estimated_bonus"] += item["estimated_bonus"]

    totals["estimated_bonus"] = round(float(totals["estimated_bonus"]), 2)

    return {
        "month": month,
        "items": items,
        "totals": totals,
    }
