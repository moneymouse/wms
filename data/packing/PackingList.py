"""
Packing List and Box ORM Models

装箱单和箱子的数据模型，支持入库流程。
"""

import random
import time
import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, func, case, or_
from sqlalchemy.orm import relationship, selectinload, joinedload

from data.DB import (
    BoxCostRecordTable,
    CargoTable,
    OrderTable,
    TransportationModeTable,
)
from data.customer.Customer import CustomerTable
from data.database import Base, SessionFactory


CARGO_STATUS_PENDING_OUTBOUND = 0
CARGO_STATUS_OUTBOUND = 1


# ---------------------------------------------------------------------------
# ORM Table Definitions
# ---------------------------------------------------------------------------


class PackingListTable(Base):
    """装箱单表"""

    __tablename__ = "packing_lists"

    uid = Column(String(32), primary_key=True)
    list_number = Column(
        String(64), nullable=False, unique=True
    )  # 唛头（用户输入，重复时自动追加日期后缀）
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    photos = Column(Text)  # JSON数组存储照片路径
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(32), default="draft")  # draft / completed
    create_date = Column(String(32))
    update_date = Column(String(32))
    archive = Column(Boolean, default=False)

    # Relationships
    customer = relationship("CustomerTable", lazy="select")
    creator = relationship("UserTable", lazy="select")
    boxes = relationship(
        CargoTable,
        back_populates="packing_list",
        foreign_keys=[CargoTable.packing_list_uid],
        lazy="select",
    )


# Backward-compatible symbol export: legacy BoxTable now points to unified cargos table.
BoxTable = CargoTable


class BoxWorkerTable(Base):
    """箱子-工人关联表：记录打包工人（最多4人）"""

    __tablename__ = "box_workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    box_uid = Column(String(32), ForeignKey("cargos.uid"), nullable=False)
    worker_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    create_date = Column(String(32))

    # Relationships
    box = relationship(CargoTable, back_populates="workers")
    worker = relationship("UserTable", lazy="select")


# ---------------------------------------------------------------------------
# Model Classes
# ---------------------------------------------------------------------------


class PackingListModel:
    """装箱单数据操作类"""

    def __init__(self):
        self.table_class = PackingListTable

    def _normalize_mark(self, mark: str) -> str:
        """规范化唛头：去首尾空格并转大写。"""
        return (mark or "").strip().upper()

    def _generate_unique_list_number(self, mark: str, session) -> str:
        """生成唯一唛头，冲突时自动追加日期后缀。"""
        normalized_mark = self._normalize_mark(mark)
        if not normalized_mark:
            raise ValueError("mark is required")

        existing = (
            session.query(PackingListTable)
            .filter(
                PackingListTable.list_number == normalized_mark,
                # PackingListTable.archive == False,
            )
            .first()
        )
        if existing is None:
            return normalized_mark

        date_suffix = datetime.now().strftime("%Y%m%d")
        base = f"{normalized_mark}-{date_suffix}"
        candidate = base
        serial = 2

        while (
            session.query(PackingListTable)
            .filter(
                PackingListTable.list_number == candidate,
                PackingListTable.archive == False,
            )
            .first()
            is not None
        ):
            candidate = f"{base}-{serial}"
            serial += 1

        return candidate

    def create(
        self,
        creator_id: int,
        mark: str,
        customer_id: Optional[int] = None,
        photos: str = "[]",
        *,
        session=None,
    ) -> dict:
        """创建装箱单"""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))

        owns_session = session is None
        s = SessionFactory() if owns_session else session
        try:
            customer_name = None
            if customer_id is not None:
                from data.customer.Customer import CustomerTable

                customer = s.query(CustomerTable).filter_by(id=customer_id).first()
                if customer is None:
                    raise ValueError(f"Customer {customer_id} not found")
                customer_name = customer.name

            list_number = self._generate_unique_list_number(mark, s)

            record = PackingListTable(
                uid=uid,
                list_number=list_number,
                customer_id=customer_id,
                photos=photos,
                creator_id=creator_id,
                status="draft",
                create_date=time.strftime("%Y-%m-%d %H:%M"),
            )
            s.add(record)
            s.flush()
            if owns_session:
                s.commit()

            return {
                "uid": uid,
                "list_number": list_number,
                "mark": list_number,
                "customer_id": customer_id,
                "customer_name": customer_name,
            }
        except Exception:
            if owns_session:
                s.rollback()
            raise
        finally:
            if owns_session:
                s.close()

    def read(self, uid: str = None) -> Optional[dict] | List[dict]:
        """读取装箱单"""
        s = SessionFactory()
        try:
            q = s.query(PackingListTable).filter(PackingListTable.archive == False)

            if uid:
                record = q.filter(PackingListTable.uid == uid).first()
                if record is None:
                    return None
                return self._to_dict(record)
            else:
                records = q.order_by(PackingListTable.create_date.desc()).all()
                return [self._to_dict(r) for r in records]
        finally:
            s.close()

    def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        customer_id: int = None,
        status: str = None,
        search: str = None,
        box_status: str = None,
        exclude_box_status: bool = False,
        creator_id: int = None,
    ) -> dict:
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 20), 1), 200)
        target_statuses = [s.strip() for s in (box_status or "").split(",") if s.strip()]
        status_level_map = {
            "pending_assign": 0,
            "pending_outbound": 1,
            "outbound": 2,
        }

        s = SessionFactory()
        try:
            box_level = case(
                (BoxTable.uid.is_(None), 0),
                (BoxTable.status == CARGO_STATUS_OUTBOUND, 2),
                (BoxTable.target_order_uid.isnot(None), 1),
                else_=0,
            )
            min_level = func.coalesce(func.min(box_level), 0)

            query = (
                s.query(PackingListTable.uid, min_level.label("display_level"))
                .outerjoin(
                    BoxTable,
                    (BoxTable.packing_list_uid == PackingListTable.uid)
                    & (BoxTable.archive == False),  # noqa: E712
                )
                .filter(PackingListTable.archive == False)  # noqa: E712
                .group_by(PackingListTable.uid, PackingListTable.create_date, PackingListTable.status)
            )

            if customer_id:
                query = query.filter(PackingListTable.customer_id == customer_id)
            if creator_id is not None:
                query = query.filter(PackingListTable.creator_id == creator_id)
            if status:
                query = query.filter(PackingListTable.status == status)
            if search:
                like = f"%{search}%"
                query = query.outerjoin(CustomerTable, CustomerTable.id == PackingListTable.customer_id).filter(
                    or_(
                        PackingListTable.list_number.ilike(like),
                        CustomerTable.name.ilike(like),
                    )
                )

            if target_statuses:
                conditions = []
                if "draft" in target_statuses:
                    conditions.append(PackingListTable.status == "draft")
                levels = [
                    status_level_map[item]
                    for item in target_statuses
                    if item in status_level_map
                ]
                if levels:
                    conditions.append(
                        (PackingListTable.status != "draft") & min_level.in_(levels)
                    )
                if conditions:
                    condition = or_(*conditions)
                    query = query.having(~condition if exclude_box_status else condition)

            total = s.query(func.count()).select_from(query.subquery()).scalar() or 0
            rows = (
                query.order_by(PackingListTable.create_date.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            uid_list = [row.uid for row in rows]
            if not uid_list:
                return {"items": [], "total": total, "page": page, "page_size": page_size}

            records = (
                s.query(PackingListTable)
                .options(
                    joinedload(PackingListTable.customer),
                    joinedload(PackingListTable.creator),
                    selectinload(PackingListTable.boxes).selectinload(BoxTable.workers),
                    selectinload(PackingListTable.boxes).joinedload(BoxTable.order),
                )
                .filter(PackingListTable.uid.in_(uid_list))
                .all()
            )
            record_map = {record.uid: record for record in records}
            items = [self._to_dict(record_map[uid]) for uid in uid_list if uid in record_map]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
        finally:
            s.close()

    def update(self, uid: str, data: dict) -> bool:
        """更新装箱单"""
        s = SessionFactory()
        try:
            record = s.query(PackingListTable).filter_by(uid=uid).first()
            if record is None:
                return False
            original_mark = record.list_number

            assigned_order_uids = []
            before_by_order = {}
            mark_requested = "list_number" in data or "mark" in data
            requested_mark = data.get("list_number")
            if requested_mark is None:
                requested_mark = data.get("mark")
            mark_will_change = bool(
                mark_requested
                and self._normalize_mark(str(requested_mark or ""))
                != record.list_number
            )
            if mark_will_change:
                assigned_order_uids = sorted(
                    {
                        row[0]
                        for row in s.query(BoxTable.target_order_uid)
                        .filter(
                            BoxTable.packing_list_uid == uid,
                            BoxTable.target_order_uid.isnot(None),
                        )
                        .all()
                    }
                )
                if assigned_order_uids:
                    (
                        s.query(OrderTable.uid)
                        .filter(OrderTable.uid.in_(assigned_order_uids))
                        .order_by(OrderTable.uid.asc())
                        .with_for_update()
                        .all()
                    )
                    from data.order_version import snapshot_order

                    for order_uid in assigned_order_uids:
                        before_by_order[order_uid] = snapshot_order(s, order_uid)
                locked_boxes = (
                    s.query(BoxTable)
                    .filter(BoxTable.packing_list_uid == uid)
                    .order_by(BoxTable.uid.asc())
                    .populate_existing()
                    .with_for_update()
                    .all()
                )
                current_order_uids = sorted(
                    {box.target_order_uid for box in locked_boxes if box.target_order_uid}
                )
                if current_order_uids != assigned_order_uids:
                    from services.order_edit_policy import OrderEditConflictError

                    raise OrderEditConflictError("箱子归属已变化，请刷新后重试")
                record = (
                    s.query(PackingListTable)
                    .filter_by(uid=uid)
                    .populate_existing()
                    .with_for_update()
                    .first()
                )
                if record is None or record.list_number != original_mark:
                    from services.order_edit_policy import OrderEditConflictError

                    raise OrderEditConflictError("装箱单已变化，请刷新后重试")

            if "list_number" in data or "mark" in data:
                next_mark = data.get("list_number")
                if next_mark is None:
                    next_mark = data.get("mark")

                normalized_mark = self._normalize_mark(str(next_mark or ""))
                if not normalized_mark:
                    raise ValueError("mark is required")

                existing = (
                    s.query(PackingListTable)
                    .filter(
                        PackingListTable.archive == False,
                        PackingListTable.list_number == normalized_mark,
                        PackingListTable.uid != uid,
                    )
                    .first()
                )
                if existing is not None:
                    raise ValueError("mark already exists")

                record.list_number = normalized_mark

            allowed_fields = ["photos", "status"]
            for k, v in data.items():
                if k in allowed_fields and v is not None:
                    if k == "photos" and isinstance(v, list):
                        v = json.dumps(v, ensure_ascii=False)
                    setattr(record, k, v)

            if "customer_id" in data:
                raw_customer_id = data.get("customer_id")
                if raw_customer_id in [None, "", 0, "0"]:
                    record.customer_id = None
                else:
                    try:
                        customer_id = int(raw_customer_id)
                    except (TypeError, ValueError):
                        raise ValueError("customer_id must be an integer")

                    from data.customer.Customer import CustomerTable

                    customer = (
                        s.query(CustomerTable)
                        .filter(CustomerTable.id == customer_id)
                        .first()
                    )
                    if customer is None:
                        raise ValueError(f"Customer {customer_id} not found")
                    record.customer_id = customer_id

            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            if mark_will_change and assigned_order_uids:
                from data.order_version import (
                    new_correlation_id,
                    record_mutation,
                    snapshot_order,
                )

                correlation_id = new_correlation_id()
                for order_uid in assigned_order_uids:
                    record_mutation(
                        s,
                        order_uid,
                        before=before_by_order[order_uid],
                        after=snapshot_order(s, order_uid),
                        action="box_mark_updated",
                        summary="修改箱子唛头",
                        correlation_id=correlation_id,
                    )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def archive(self, uid: str) -> bool:
        """归档装箱单"""
        s = SessionFactory()
        try:
            record = s.query(PackingListTable).filter_by(uid=uid).first()
            if record is None:
                return False
            record.archive = True
            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str) -> bool:
        """删除装箱单；存在成本历史时保留归档记录及箱子。"""
        s = SessionFactory()
        try:
            record = s.query(PackingListTable).filter_by(uid=uid).first()
            if record is None:
                return False
            order_uids = sorted(
                {
                    box.target_order_uid
                    for box in record.boxes
                    if box.target_order_uid
                }
            )
            if order_uids:
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid.in_(order_uids))
                    .order_by(OrderTable.uid.asc())
                    .with_for_update()
                    .all()
                )
            locked_boxes = (
                s.query(BoxTable)
                .filter(BoxTable.packing_list_uid == uid)
                .order_by(BoxTable.uid.asc())
                .populate_existing()
                .with_for_update()
                .all()
            )
            current_order_uids = sorted(
                {box.target_order_uid for box in locked_boxes if box.target_order_uid}
            )
            if current_order_uids != order_uids:
                from services.order_edit_policy import OrderEditConflictError

                raise OrderEditConflictError("箱子归属已变化，请刷新后重试")
            from services.order_edit_policy import ensure_cargo_removable

            for box in locked_boxes:
                ensure_cargo_removable(box)
            record = (
                s.query(PackingListTable)
                .filter(PackingListTable.uid == uid)
                .populate_existing()
                .with_for_update()
                .first()
            )
            if record is None:
                return False
            from data.intake import IntakeTable

            if s.query(IntakeTable.uid).filter(IntakeTable.packing_list_uid == uid).first() is not None:
                from services.order_edit_policy import OrderEditConflictError

                raise OrderEditConflictError("装箱单存在纸单回传来源，不能硬删除，请归档并保留原始记录")
            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )
            before = {order_uid: snapshot_order(s, order_uid) for order_uid in order_uids}
            has_cost_history = (
                s.query(BoxCostRecordTable.id)
                .filter(BoxCostRecordTable.packing_list_uid == uid)
                .first()
                is not None
            )
            if has_cost_history:
                now = time.strftime("%Y-%m-%d %H:%M")
                record.archive = True
                record.update_date = now
                for box in locked_boxes:
                    box.archive = True
                    box.update_date = now
            else:
                s.delete(record)
            s.flush()
            correlation_id = new_correlation_id()
            for order_uid in order_uids:
                record_mutation(
                    s,
                    order_uid,
                    before=before[order_uid],
                    after=snapshot_order(s, order_uid),
                    action="packing_list_deleted",
                    summary="删除装箱单" if has_cost_history else "删除装箱单并解除箱子属性",
                    correlation_id=correlation_id,
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _to_dict(self, record: PackingListTable) -> dict:
        """转换为字典"""
        import json

        return {
            "uid": record.uid,
            "list_number": record.list_number,
            "mark": record.list_number,
            "customer_id": record.customer_id,
            "customer_name": record.customer.name if record.customer else None,
            "photos": json.loads(record.photos) if record.photos else [],
            "creator_id": record.creator_id,
            "creator_name": record.creator.name if record.creator else None,
            "status": record.status,
            "create_date": record.create_date,
            "update_date": record.update_date,
            "boxes": [self._box_to_dict(b) for b in record.boxes if not b.archive],
        }

    def _box_to_dict(self, box: "BoxTable") -> dict:
        """箱子简要信息"""
        from sqlalchemy.orm import object_session
        from services.order_edit_policy import (
            box_identity_editable,
            cargo_original_number_editable,
        )

        return {
            "uid": box.uid,
            "identity_editable": box_identity_editable(object_session(box), box),
            "original_number_editable": cargo_original_number_editable(box),
            "box_number": box.box_number,
            "item_name": box.item_name,
            "item_details": json.loads(box.item_details) if box.item_details else [],
            "remark": box.remark,
            "piece_count": box.piece_count,
            "weight": box.weight,
            "bonus_item_id": box.bonus_item_id,
            "bonus_assigned": bool(box.bonus_assigned),
            "bonus_assigned_date": box.bonus_assigned_date,
            "target_order_uid": box.target_order_uid,
            "target_order_id": box.order.order_id if box.order else None,
            "transfer_id": box.transfer_id,
            "waybill_id": box.waybill_id,
            "workers": [
                {
                    "worker_id": w.worker_id,
                    "worker_name": w.worker.name if w.worker else None,
                }
                for w in box.workers
            ],
            "status": box.status,
        }


class BoxModel:
    """箱子数据操作类"""

    MAX_WORKERS = 4  # 每个箱子最多4个工人

    def __init__(self):
        self.table_class = BoxTable

    def _lock_after_order(self, session, uid: str):
        """Resolve ownership first, then consistently lock order before box."""
        candidate = (
            session.query(BoxTable.uid, BoxTable.target_order_uid)
            .filter(BoxTable.uid == uid)
            .first()
        )
        if candidate is None:
            return None
        candidate_order_uid = candidate.target_order_uid
        if candidate_order_uid:
            (
                session.query(OrderTable.uid)
                .filter(OrderTable.uid == candidate_order_uid)
                .with_for_update()
                .first()
            )
        record = (
            session.query(BoxTable)
            .filter(BoxTable.uid == uid)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if record is not None and record.target_order_uid != candidate_order_uid:
            raise ValueError("箱子归属已变化，请刷新后重试")
        return record

    def _build_box_tag(self, list_number: str, box_number: int) -> str:
        mark = (list_number or "").strip()
        if mark and box_number:
            return f"{mark}_{box_number}"
        if mark:
            return mark
        if box_number:
            return f"BOX_{box_number}"
        return "BOX"

    def _lock_box_cost(self, session, box, now: str) -> None:
        """Compatibility delegate to the single outbound cost implementation."""
        from services.outbound_service import freeze_box_cost
        return freeze_box_cost(session, box, now)

    def create(
        self,
        packing_list_uid: str,
        item_name: str,
        piece_count: int,
        weight: float = None,
        item_details: Optional[List[dict]] = None,
        remark: Optional[str] = None,
    ) -> dict:
        """创建箱子"""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))

        s = SessionFactory()
        try:
            # 验证装箱单存在
            packing_list = (
                s.query(PackingListTable).filter_by(uid=packing_list_uid).first()
            )
            if packing_list is None:
                raise ValueError(f"PackingList {packing_list_uid} not found")

            # 每个装箱单内维护单调递增箱号，不复用已删除箱号
            max_box_number = (
                s.query(func.max(BoxTable.box_number))
                .filter(BoxTable.packing_list_uid == packing_list_uid)
                .scalar()
            )
            next_box_number = (max_box_number or 0) + 1

            normalized_details: List[dict] = []
            if item_details:
                for row in item_details:
                    name = str((row or {}).get("item_name") or "").strip()
                    customs_code = str((row or {}).get("customs_code") or "").strip()
                    if len(customs_code) > 64:
                        raise ValueError("customs_code cannot exceed 64 characters")
                    raw_piece = (row or {}).get("piece_count")
                    if not name:
                        continue
                    try:
                        piece = int(raw_piece)
                    except (TypeError, ValueError):
                        raise ValueError("piece_count in item_details must be integer")
                    if piece <= 0:
                        raise ValueError(
                            "piece_count in item_details must be greater than 0"
                        )
                    normalized_details.append(
                        {
                            "item_name": name,
                            "customs_code": customs_code,
                            "piece_count": piece,
                        }
                    )

            if normalized_details:
                final_item_name = "、".join(
                    [row["item_name"] for row in normalized_details]
                )
                final_piece_count = sum(
                    [row["piece_count"] for row in normalized_details]
                )
            else:
                final_item_name = (item_name or "").strip()
                try:
                    final_piece_count = int(piece_count)
                except (TypeError, ValueError):
                    raise ValueError("piece_count must be integer")

                if final_piece_count <= 0:
                    raise ValueError("piece_count must be greater than 0")

                if final_item_name:
                    normalized_details = [
                        {
                            "item_name": final_item_name,
                            "customs_code": "",
                            "piece_count": final_piece_count,
                        }
                    ]

            record = BoxTable(
                uid=uid,
                origin_id=f"BOX-{uid}",
                transfer_id="",
                tag=self._build_box_tag(packing_list.list_number, next_box_number),
                count=final_piece_count,
                real_en_name=final_item_name,
                price=0.0,
                status=0,
                waybill_id="",
                packing_list_uid=packing_list_uid,
                item_name=final_item_name,
                item_details=(
                    json.dumps(normalized_details, ensure_ascii=False)
                    if normalized_details
                    else None
                ),
                remark=(str(remark).strip() if remark is not None else None),
                box_number=next_box_number,
                piece_count=final_piece_count,
                weight=weight,
                create_date=time.strftime("%Y-%m-%d %H:%M"),
            )
            s.add(record)
            s.commit()

            return {
                "uid": uid,
                "packing_list_uid": packing_list_uid,
                "item_name": final_item_name,
                "item_details": normalized_details,
                "remark": (str(remark).strip() if remark is not None else None),
                "box_number": next_box_number,
                "piece_count": final_piece_count,
                "weight": weight,
                "status": CARGO_STATUS_PENDING_OUTBOUND,
            }
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def read(self, uid: str = None) -> Optional[dict] | List[dict]:
        """读取箱子"""
        s = SessionFactory()
        try:
            q = s.query(BoxTable).filter(BoxTable.archive == False)
            q = q.filter(BoxTable.packing_list_uid.isnot(None))

            if uid:
                record = q.filter(BoxTable.uid == uid).first()
                if record is None:
                    return None
                return self._to_dict(record)
            else:
                records = q.all()
                return [self._to_dict(r) for r in records]
        finally:
            s.close()

    def update(self, uid: str, data: dict, *, return_details: bool = False, session=None, record_version=True):
        """更新箱子信息"""
        owned_session = session is None
        s = SessionFactory() if owned_session else session
        try:
            record = self._lock_after_order(s, uid)
            if record is None:
                return False
            if record.packing_list_uid is None:
                return False
            if not isinstance(data, dict):
                raise ValueError("invalid payload")
            if set(data).intersection({"status", "date"}):
                raise ValueError("出库状态和时间必须通过确认出库服务写入")

            worker_ids_supplied = "worker_ids" in data
            worker_ids = data.get("worker_ids") if worker_ids_supplied else None
            if worker_ids_supplied:
                worker_ids = self._normalize_worker_ids(worker_ids)

            old_waybill_id = str(record.waybill_id or "").strip()

            before = None
            current_worker_ids = [
                row[0]
                for row in s.query(BoxWorkerTable.worker_id)
                .filter(BoxWorkerTable.box_uid == uid)
                .order_by(BoxWorkerTable.worker_id.asc())
                .all()
            ]
            policy_fields = set()
            for field in (
                "item_name",
                "item_details",
                "piece_count",
                "weight",
                "price",
                "box_number",
                "remark",
                "transfer_id",
                "waybill_id",
            ):
                if field not in data:
                    continue
                current_value = getattr(record, field, None)
                next_value = data.get(field)
                if field == "item_details":
                    try:
                        current_value = json.loads(current_value) if current_value else []
                    except (TypeError, ValueError):
                        current_value = []
                    if isinstance(next_value, str):
                        try:
                            next_value = json.loads(next_value)
                        except (TypeError, ValueError):
                            pass
                elif field in {"transfer_id", "waybill_id", "remark", "item_name"}:
                    current_value = str(current_value or "").strip()
                    next_value = str(next_value or "").strip()
                elif field == "weight":
                    try:
                        current_value = None if current_value is None else float(current_value)
                        next_value = None if next_value in [None, ""] else float(next_value)
                    except (TypeError, ValueError):
                        pass
                elif field in {"piece_count", "box_number"}:
                    try:
                        current_value = int(current_value)
                        next_value = int(next_value)
                    except (TypeError, ValueError):
                        pass
                elif field == "price":
                    try:
                        current_value = None if current_value is None else float(current_value)
                        next_value = None if next_value in [None, ""] else float(next_value)
                    except (TypeError, ValueError):
                        pass
                if current_value != next_value:
                    policy_fields.add(field)
            if worker_ids_supplied and sorted(worker_ids) != current_worker_ids:
                policy_fields.add("workers")

            from services.order_edit_policy import ensure_box_identity_editable

            ensure_box_identity_editable(
                s, record, {field: data[field] for field in policy_fields if field in data}
            )

            if record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == record.target_order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, record.target_order_uid)

            if "weight" in policy_fields:
                from services.order_edit_policy import ensure_outbound_weight_editable

                ensure_outbound_weight_editable(
                    record.status,
                    current_weight=record.weight,
                    next_weight=data.get("weight"),
                )

            now = time.strftime("%Y-%m-%d %H:%M")

            has_item_details = "item_details" in data
            if has_item_details:
                raw_details = data.get("item_details")
                if raw_details is None:
                    normalized_details = []
                elif isinstance(raw_details, str):
                    try:
                        normalized_details = json.loads(raw_details)
                    except Exception:
                        raise ValueError("item_details must be valid JSON array")
                elif isinstance(raw_details, list):
                    normalized_details = raw_details
                else:
                    raise ValueError("item_details must be a list")

                normalized_rows: List[dict] = []
                for row in normalized_details:
                    name = str((row or {}).get("item_name") or "").strip()
                    customs_code = str((row or {}).get("customs_code") or "").strip()
                    if len(customs_code) > 64:
                        raise ValueError("customs_code cannot exceed 64 characters")
                    if not name:
                        continue
                    raw_piece = (row or {}).get("piece_count")
                    try:
                        piece = int(raw_piece)
                    except (TypeError, ValueError):
                        raise ValueError("piece_count in item_details must be integer")
                    if piece <= 0:
                        raise ValueError(
                            "piece_count in item_details must be greater than 0"
                        )
                    normalized_rows.append(
                        {
                            "item_name": name,
                            "customs_code": customs_code,
                            "piece_count": piece,
                        }
                    )

                if len(normalized_rows) == 0:
                    raise ValueError("item_details requires at least one valid row")

                merged_name = "、".join([row["item_name"] for row in normalized_rows])
                merged_piece_count = sum(
                    [row["piece_count"] for row in normalized_rows]
                )

                record.item_details = json.dumps(normalized_rows, ensure_ascii=False)
                record.item_name = merged_name
                record.real_en_name = merged_name
                record.piece_count = merged_piece_count
                record.count = merged_piece_count
            else:
                if "item_name" in data:
                    name = str(data.get("item_name") or "").strip()
                    if not name:
                        raise ValueError("item_name is required")
                    record.item_name = name
                    record.real_en_name = name

                if "piece_count" in data:
                    try:
                        piece = int(data.get("piece_count"))
                    except (TypeError, ValueError):
                        raise ValueError("piece_count must be integer")
                    if piece <= 0:
                        raise ValueError("piece_count must be greater than 0")
                    record.piece_count = piece
                    record.count = piece

            if "weight" in data:
                raw_weight = data.get("weight")
                if raw_weight in [None, ""]:
                    record.weight = None
                else:
                    try:
                        weight = float(raw_weight)
                    except (TypeError, ValueError):
                        raise ValueError("weight must be a number")
                    if weight <= 0:
                        raise ValueError("weight must be greater than 0")
                    record.weight = weight

            if "price" in data:
                raw_price = data.get("price")
                if raw_price in [None, ""]:
                    record.price = None
                else:
                    try:
                        price = float(raw_price)
                    except (TypeError, ValueError):
                        raise ValueError("price must be a number")
                    if price < 0:
                        raise ValueError("price cannot be negative")
                    record.price = price

            if "box_number" in data:
                try:
                    box_number = int(data.get("box_number"))
                except (TypeError, ValueError):
                    raise ValueError("box_number must be integer")
                if box_number <= 0:
                    raise ValueError("box_number must be greater than 0")

                duplicated = (
                    s.query(BoxTable)
                    .filter(
                        BoxTable.archive == False,
                        BoxTable.packing_list_uid == record.packing_list_uid,
                        BoxTable.box_number == box_number,
                        BoxTable.uid != record.uid,
                    )
                    .first()
                )
                if duplicated is not None:
                    raise ValueError("box_number already exists in this packing list")

                record.box_number = box_number
                record.tag = self._build_box_tag(
                    record.packing_list.list_number if record.packing_list else "",
                    box_number,
                )

            if "remark" in data:
                raw_remark = data.get("remark")
                record.remark = (
                    str(raw_remark).strip()
                    if raw_remark is not None and str(raw_remark).strip()
                    else None
                )

            if "transfer_id" in policy_fields:
                record.transfer_id = str(data.get("transfer_id") or "").strip()

            if "waybill_id" in policy_fields:
                next_waybill_id = str(data.get("waybill_id") or "").strip()
                if (
                    int(record.status or 0) == CARGO_STATUS_OUTBOUND
                    and not next_waybill_id
                ):
                    raise ValueError("已出库箱不能清空转单号；如需撤销出库请使用撤销出库操作")
                record.waybill_id = next_waybill_id

            if worker_ids_supplied and sorted(worker_ids) != current_worker_ids:
                self._set_workers_in_session(s, uid, worker_ids, now)

            if policy_fields:
                record.update_date = now
            s.flush()
            if record.target_order_uid and record_version:
                record_mutation(
                    s,
                    record.target_order_uid,
                    before=before,
                    after=snapshot_order(s, record.target_order_uid),
                    action="box_updated",
                    summary="修改箱子内容和操作员",
                )
            if owned_session:
                s.commit()
            if return_details:
                new_waybill_id = str(record.waybill_id or "").strip()
                return {
                    "updated": True,
                    "changed": bool(policy_fields),
                    "old_waybill_id": old_waybill_id,
                    "new_waybill_id": new_waybill_id,
                    "waybill_changed": old_waybill_id != new_waybill_id,
                }
            return True
        except Exception:
            if owned_session:
                s.rollback()
            raise
        finally:
            if owned_session:
                s.close()

    def _normalize_worker_ids(self, worker_ids: List[int]) -> List[int]:
        if not isinstance(worker_ids, list):
            raise ValueError("worker_ids must be a list")
        normalized = []
        for worker_id in worker_ids:
            try:
                parsed = int(worker_id)
            except (TypeError, ValueError):
                raise ValueError("worker_ids must be integers")
            if parsed <= 0:
                raise ValueError("worker_ids must be positive integers")
            if parsed not in normalized:
                normalized.append(parsed)
        if len(normalized) > self.MAX_WORKERS:
            raise ValueError(f"Maximum {self.MAX_WORKERS} workers allowed per box")
        return sorted(normalized)

    def _set_workers_in_session(
        self, session, box_uid: str, worker_ids: List[int], now: str
    ) -> None:
        session.query(BoxWorkerTable).filter_by(box_uid=box_uid).delete(
            synchronize_session=False
        )
        for worker_id in worker_ids:
            session.add(
                BoxWorkerTable(
                    box_uid=box_uid,
                    worker_id=worker_id,
                    create_date=now,
                )
            )

    def archive(self, uid: str) -> bool:
        """归档箱子"""
        s = SessionFactory()
        try:
            record = self._lock_after_order(s, uid)
            if record is None:
                return False
            if record.packing_list_uid is None:
                return False
            from services.order_edit_policy import ensure_cargo_removable

            ensure_cargo_removable(record)
            if record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == record.target_order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, record.target_order_uid)
            else:
                before = None
            record.archive = True
            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            if record.target_order_uid:
                record_mutation(
                    s,
                    record.target_order_uid,
                    before=before,
                    after=snapshot_order(s, record.target_order_uid),
                    action="box_archived",
                    summary="归档箱子",
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str) -> bool:
        """删除箱子；存在历史引用时保留归档记录。"""
        s = SessionFactory()
        try:
            record = self._lock_after_order(s, uid)
            if record is None:
                return False
            if record.packing_list_uid is None:
                return False
            from services.order_edit_policy import ensure_cargo_removable

            ensure_cargo_removable(record)
            if record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == record.target_order_uid)
                    .with_for_update()
                    .first()
                )
                order_uid = record.target_order_uid
                before = snapshot_order(s, order_uid)
            else:
                order_uid, before = None, None
            from data.DB import cargo_requires_archival

            if cargo_requires_archival(s, uid):
                record.archive = True
                record.update_date = time.strftime("%Y-%m-%d %H:%M")
            else:
                s.query(BoxWorkerTable).filter_by(box_uid=uid).delete(
                    synchronize_session=False
                )
                s.delete(record)
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="box_deleted",
                    summary="删除箱子",
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def set_workers(self, box_uid: str, worker_ids: List[int]) -> bool:
        """设置箱子的打包工人（最多4人）"""
        worker_ids = self._normalize_worker_ids(worker_ids)

        s = SessionFactory()
        try:
            # 验证箱子存在
            box = self._lock_after_order(s, box_uid)
            if box is None:
                return False
            if box.packing_list_uid is None:
                return False
            current_ids = sorted(
                row[0]
                for row in s.query(BoxWorkerTable.worker_id)
                .filter(BoxWorkerTable.box_uid == box_uid)
                .all()
            )
            before = None
            if box.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == box.target_order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, box.target_order_uid)
            if current_ids != worker_ids:
                self._set_workers_in_session(
                    s, box_uid, worker_ids, time.strftime("%Y-%m-%d %H:%M")
                )
                box.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            if box.target_order_uid:
                record_mutation(
                    s,
                    box.target_order_uid,
                    before=before,
                    after=snapshot_order(s, box.target_order_uid),
                    action="box_workers_updated",
                    summary="修改箱子操作员",
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def add_workers_if_empty(self, box_uid: str, worker_ids: List[int]) -> bool:
        """仅在箱子未设置工人时，新增工人（最多4人）"""
        if not isinstance(worker_ids, list) or len(worker_ids) == 0:
            raise ValueError("worker_ids is required")

        normalized_worker_ids = self._normalize_worker_ids(worker_ids)

        s = SessionFactory()
        try:
            box = self._lock_after_order(s, box_uid)
            if box is None:
                return False
            if box.packing_list_uid is None:
                return False

            before = None
            if box.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == box.target_order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, box.target_order_uid)

            existing_worker = (
                s.query(BoxWorkerTable.id).filter_by(box_uid=box_uid).first()
            )
            if existing_worker is not None:
                raise ValueError("workers already set for this box")

            for worker_id in normalized_worker_ids:
                worker_record = BoxWorkerTable(
                    box_uid=box_uid,
                    worker_id=worker_id,
                    create_date=time.strftime("%Y-%m-%d %H:%M"),
                )
                s.add(worker_record)

            box.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            if box.target_order_uid:
                record_mutation(
                    s,
                    box.target_order_uid,
                    before=before,
                    after=snapshot_order(s, box.target_order_uid),
                    action="box_workers_updated",
                    summary="新增箱子操作员",
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_workers(self, box_uid: str) -> List[dict]:
        """获取箱子的打包工人列表"""
        s = SessionFactory()
        try:
            workers = s.query(BoxWorkerTable).filter_by(box_uid=box_uid).all()
            return [
                {
                    "worker_id": w.worker_id,
                    "worker_name": w.worker.name if w.worker else None,
                    "create_date": w.create_date,
                }
                for w in workers
            ]
        finally:
            s.close()

    def assign_to_order(self, box_uid: str, order_uid: str) -> bool:
        """将箱子分配到订单"""
        s = SessionFactory()
        try:
            box = s.query(BoxTable).filter_by(uid=box_uid).first()
            if box is None:
                return False
            if box.packing_list_uid is None:
                return False

            if box.target_order_uid:
                raise ValueError(f"Box {box_uid} is already assigned")

            from data.order_version import record_mutation, snapshot_order

            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                raise ValueError("Target order not found")
            box = (
                s.query(BoxTable)
                .filter_by(uid=box_uid)
                .populate_existing()
                .with_for_update()
                .first()
            )
            if box is None or box.target_order_uid:
                raise ValueError(f"Box {box_uid} is already assigned")
            from services.order_edit_policy import ensure_cargo_removable

            ensure_cargo_removable(box)
            before = snapshot_order(s, order_uid)

            box.target_order_uid = order_uid
            box.tag = self._build_box_tag(
                box.packing_list.list_number if box.packing_list else "",
                box.box_number or 0,
            )
            # 兼容旧系统：status=0 代表未出库。
            box.status = CARGO_STATUS_PENDING_OUTBOUND
            box.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            record_mutation(
                s,
                order_uid,
                before=before,
                after=snapshot_order(s, order_uid),
                action="box_assigned",
                summary="分配箱子到订单",
            )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def batch_assign(self, box_uids: List[str], order_uid: str) -> dict:
        """批量分配箱子到订单"""
        results = {"success": [], "failed": []}
        s = SessionFactory()
        try:
            from data.order_version import record_mutation, snapshot_order

            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                raise ValueError("Target order not found")
            before = snapshot_order(s, order_uid)
            boxes = (
                s.query(BoxTable)
                .filter(BoxTable.uid.in_(box_uids))
                .order_by(BoxTable.uid.asc())
                .populate_existing()
                .with_for_update()
                .all()
            )
            box_map = {box.uid: box for box in boxes}
            now = time.strftime("%Y-%m-%d %H:%M")
            for box_uid in box_uids:
                box = box_map.get(box_uid)
                if box is None or box.packing_list_uid is None:
                    results["failed"].append({"uid": box_uid, "error": "Box not found"})
                    continue
                from services.order_edit_policy import cargo_currently_outbound

                if cargo_currently_outbound(box):
                    results["failed"].append({"uid": box_uid, "error": "Box is already outbound"})
                    continue
                if box.target_order_uid:
                    results["failed"].append({"uid": box_uid, "error": "Box is already assigned"})
                    continue
                box.target_order_uid = order_uid
                box.tag = self._build_box_tag(
                    box.packing_list.list_number if box.packing_list else "",
                    box.box_number or 0,
                )
                box.status = CARGO_STATUS_PENDING_OUTBOUND
                box.update_date = now
                results["success"].append(box_uid)
            s.flush()
            record_mutation(
                s,
                order_uid,
                before=before,
                after=snapshot_order(s, order_uid),
                action="boxes_assigned",
                summary=f"分配 {len(results['success'])} 个箱子到订单",
            )
            s.commit()
            return results
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_unassigned_by_customer(
        self, customer_id: int, valid_only: bool = True
    ) -> List[dict]:
        """获取客户所有未分配的箱子，按唛头分组"""
        return self.get_unassigned(valid_only=valid_only, customer_id=customer_id)

    def get_unassigned(
        self,
        valid_only: bool = True,
        customer_id: Optional[int] = None,
        mark_search: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> List[dict] | dict:
        """获取未分配箱子，可按客户、唛头和装箱单分页过滤。"""
        from services.box_validator import default_validator

        s = SessionFactory()
        try:
            box_conditions = [
                BoxTable.archive == False,  # noqa: E712
                BoxTable.target_order_uid.is_(None),
            ]
            if valid_only:
                box_conditions.extend([
                    BoxTable.weight.isnot(None),
                    BoxTable.weight > 0,
                ])

            query = (
                s.query(PackingListTable)
                .join(
                    BoxTable,
                    (BoxTable.packing_list_uid == PackingListTable.uid)
                    & (BoxTable.archive == False),  # noqa: E712
                )
                .filter(
                    PackingListTable.archive == False,  # noqa: E712
                    PackingListTable.status != "draft",
                    *box_conditions[1:],
                )
            )
            if customer_id is not None:
                query = query.filter(PackingListTable.customer_id == customer_id)

            if mark_search:
                query = query.filter(
                    PackingListTable.list_number.ilike(f"%{mark_search.strip()}%")
                )

            total = (
                query.with_entities(func.count(func.distinct(PackingListTable.uid)))
                .order_by(None)
                .scalar()
                or 0
            )
            total_boxes = (
                query.with_entities(func.count(BoxTable.uid))
                .order_by(None)
                .scalar()
                or 0
            )
            paginated = page is not None or page_size is not None
            page = max(int(page or 1), 1)
            page_size = min(max(int(page_size or 10), 1), 100)
            page_query = (
                query.options(selectinload(PackingListTable.boxes))
                .order_by(PackingListTable.create_date.desc(), PackingListTable.uid.desc())
                .distinct()
            )
            if paginated:
                page_query = page_query.offset((page - 1) * page_size).limit(page_size)
            packing_lists = page_query.all()

            result = []
            for pl in packing_lists:
                boxes = [
                    self._to_dict(b)
                    for b in pl.boxes
                    if not b.archive and not b.target_order_uid
                ]

                # 过滤有效箱子
                if valid_only:
                    boxes = default_validator.filter_valid_boxes(boxes)

                if boxes:
                    result.append(
                        {
                            "list_number": pl.list_number,
                            "mark": pl.list_number,
                            "packing_list_uid": pl.uid,
                            "boxes": boxes,
                        }
                    )

            if not paginated:
                return result
            return {
                "items": result,
                "total": total,
                "total_boxes": total_boxes,
                "page": page,
                "page_size": page_size,
            }
        finally:
            s.close()

    def batch_ship(self, packing_list_uid: str, box_uids: List[str]) -> dict:
        """显式出货已停用，保留方法仅兼容旧调用。"""
        raise ValueError("旧批量出库方法已停用，请调用统一出库服务或 /api/cargo/<uid>/outbound")

    def undo_ship(self, uid: str, *, operator=None) -> bool:
        """重新入库箱子，保留原出库、成本、收款和奖金历史。"""
        from flask import has_request_context
        from data.order_version import normalize_operator, record_mutation, snapshot_order
        from services.order_edit_policy import OrderEditConflictError, cargo_is_outbound_or_later

        actor = normalize_operator(operator)
        if (operator is not None or has_request_context()) and not set(actor["roles"]).intersection({"admin", "store_manager"}):
            raise PermissionError("Permission denied")

        s = SessionFactory()
        try:
            candidate = (
                s.query(BoxTable)
                .filter(
                    BoxTable.archive == False,
                    BoxTable.uid == uid,
                    BoxTable.packing_list_uid.isnot(None),
                )
                .first()
            )
            if candidate is None:
                return False

            order_uid = candidate.target_order_uid
            before = None
            if order_uid:
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, order_uid)
            box = (
                s.query(BoxTable)
                .filter(
                    BoxTable.archive == False,
                    BoxTable.uid == uid,
                    BoxTable.packing_list_uid.isnot(None),
                )
                .populate_existing()
                .with_for_update()
                .first()
            )
            if box is None:
                return False
            if box.target_order_uid != order_uid:
                raise OrderEditConflictError("箱子归属已变化，请刷新后重试")

            if not cargo_is_outbound_or_later(box.status):
                raise ValueError("Box is not outbound")

            now = time.strftime("%Y-%m-%d %H:%M")
            old_status = box.status
            # FOR UPDATE serializes MySQL; the conditional write also detects
            # a changed box on SQLite, where row locking is not supported.
            changed = s.query(BoxTable).filter(
                BoxTable.uid == box.uid,
                BoxTable.status == old_status,
                BoxTable.target_order_uid == order_uid,
                BoxTable.archive == False,  # noqa: E712
                BoxTable.packing_list_uid == box.packing_list_uid,
            ).update({
                "waybill_id": "",
                "status": CARGO_STATUS_PENDING_OUTBOUND,
                "date": None,
                "update_date": now,
            }, synchronize_session=False)
            if changed != 1:
                raise OrderEditConflictError("箱子出库状态已变化，请刷新后重试")
            box.waybill_id = ""
            box.status = CARGO_STATUS_PENDING_OUTBOUND
            box.date = None
            box.update_date = now
            s.query(BoxCostRecordTable).filter(
                BoxCostRecordTable.box_uid == box.uid,
                BoxCostRecordTable.archive == False,  # noqa: E712
            ).update({"archive": True}, synchronize_session=False)
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="box_shipment_undone",
                    summary="撤销箱子出库",
                    operator_payload=operator,
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_by_order_uid(self, order_uid: str) -> List[dict]:
        """获取已分配到指定订单的箱子列表。"""
        s = SessionFactory()
        try:
            records = (
                s.query(BoxTable)
                .filter(
                    BoxTable.archive == False,
                    BoxTable.packing_list_uid.isnot(None),
                    BoxTable.target_order_uid == order_uid,
                )
                .order_by(BoxTable.create_date.desc(), BoxTable.box_number.asc())
                .all()
            )
            return [self._to_dict(record) for record in records]
        finally:
            s.close()

    def _to_dict(self, record: BoxTable) -> dict:
        """转换为字典"""
        from sqlalchemy.orm import object_session
        from services.order_edit_policy import (
            box_identity_editable,
            cargo_original_number_editable,
        )

        return {
            "uid": record.uid,
            "identity_editable": box_identity_editable(object_session(record), record),
            "original_number_editable": cargo_original_number_editable(record),
            "packing_list_uid": record.packing_list_uid,
            "list_number": (
                record.packing_list.list_number if record.packing_list else None
            ),
            "mark": (record.packing_list.list_number if record.packing_list else None),
            "box_number": record.box_number,
            "item_name": record.item_name,
            "item_details": (
                json.loads(record.item_details) if record.item_details else []
            ),
            "remark": record.remark,
            "piece_count": record.piece_count,
            "weight": record.weight,
            "bonus_item_id": record.bonus_item_id,
            "bonus_assigned": bool(record.bonus_assigned),
            "bonus_assigned_by": record.bonus_assigned_by,
            "bonus_assigned_date": record.bonus_assigned_date,
            "target_order_uid": record.target_order_uid,
            "target_order_id": record.order.order_id if record.order else None,
            "transfer_id": record.transfer_id,
            "waybill_id": record.waybill_id,
            "status": record.status,
            "create_date": record.create_date,
            "update_date": record.update_date,
            "workers": (
                [
                    {
                        "worker_id": w.worker_id,
                        "worker_name": w.worker.name if w.worker else None,
                    }
                    for w in record.workers
                ]
                if record.workers
                else []
            ),
        }


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

packing_list_model = PackingListModel()
box_model = BoxModel()
