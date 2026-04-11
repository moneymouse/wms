"""
Packing List and Box ORM Models

装箱单和箱子的数据模型，支持入库流程。
"""

import random
import time
import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import relationship

from data.DB import CargoTable
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
                PackingListTable.archive == False,
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
    ) -> dict:
        """创建装箱单"""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))

        s = SessionFactory()
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
            s.commit()

            return {
                "uid": uid,
                "list_number": list_number,
                "mark": list_number,
                "customer_id": customer_id,
                "customer_name": customer_name,
            }
        except Exception:
            s.rollback()
            raise
        finally:
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

    def update(self, uid: str, data: dict) -> bool:
        """更新装箱单"""
        s = SessionFactory()
        try:
            record = s.query(PackingListTable).filter_by(uid=uid).first()
            if record is None:
                return False

            allowed_fields = ["photos", "status"]
            for k, v in data.items():
                if k in allowed_fields and v is not None:
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
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str) -> bool:
        """软删除装箱单"""
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
        return {
            "uid": box.uid,
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
            "status": box.status,
        }


class BoxModel:
    """箱子数据操作类"""

    MAX_WORKERS = 4  # 每个箱子最多4个工人

    def __init__(self):
        self.table_class = BoxTable

    def _build_box_tag(self, list_number: str, box_number: int) -> str:
        mark = (list_number or "").strip()
        if mark and box_number:
            return f"{mark}_{box_number}"
        if mark:
            return mark
        if box_number:
            return f"BOX_{box_number}"
        return "BOX"

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
                    normalized_details.append({"item_name": name, "piece_count": piece})

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
                        {"item_name": final_item_name, "piece_count": final_piece_count}
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

    def update(self, uid: str, data: dict) -> bool:
        """更新箱子信息"""
        s = SessionFactory()
        try:
            record = s.query(BoxTable).filter_by(uid=uid).first()
            if record is None:
                return False
            if record.packing_list_uid is None:
                return False

            allowed_fields = [
                "item_name",
                "weight",
                "piece_count",
                "remark",
                "item_details",
            ]
            for k, v in data.items():
                if k in allowed_fields:
                    if k == "item_details" and v is not None and not isinstance(v, str):
                        v = json.dumps(v, ensure_ascii=False)
                    setattr(record, k, v)

            if "piece_count" in data and data.get("piece_count") is not None:
                record.count = int(data.get("piece_count"))
            if "item_name" in data and data.get("item_name") is not None:
                record.real_en_name = data.get("item_name")

            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str) -> bool:
        """软删除箱子"""
        s = SessionFactory()
        try:
            record = s.query(BoxTable).filter_by(uid=uid).first()
            if record is None:
                return False
            if record.packing_list_uid is None:
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

    def set_workers(self, box_uid: str, worker_ids: List[int]) -> bool:
        """设置箱子的打包工人（最多4人）"""
        if len(worker_ids) > self.MAX_WORKERS:
            raise ValueError(f"Maximum {self.MAX_WORKERS} workers allowed per box")

        s = SessionFactory()
        try:
            # 验证箱子存在
            box = s.query(BoxTable).filter_by(uid=box_uid).first()
            if box is None:
                return False
            if box.packing_list_uid is None:
                return False

            # 清除现有工人关联
            s.query(BoxWorkerTable).filter_by(box_uid=box_uid).delete()

            # 添加新工人关联
            for worker_id in worker_ids:
                worker_record = BoxWorkerTable(
                    box_uid=box_uid,
                    worker_id=worker_id,
                    create_date=time.strftime("%Y-%m-%d %H:%M"),
                )
                s.add(worker_record)

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

            if int(box.status or 0) == CARGO_STATUS_OUTBOUND:
                raise ValueError(f"Box {box_uid} is already outbound")
            if box.target_order_uid:
                raise ValueError(f"Box {box_uid} is already assigned")

            # 验证订单存在
            from data.DB import OrderTable

            order = s.query(OrderTable).filter_by(uid=order_uid).first()
            if order is None:
                raise ValueError(f"Order {order_uid} not found")

            box.target_order_uid = order_uid
            box.tag = self._build_box_tag(
                box.packing_list.list_number if box.packing_list else "",
                box.box_number or 0,
            )
            # 兼容旧系统：status=0 代表未出库。
            box.status = CARGO_STATUS_PENDING_OUTBOUND
            box.update_date = time.strftime("%Y-%m-%d %H:%M")
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

        for box_uid in box_uids:
            try:
                self.assign_to_order(box_uid, order_uid)
                results["success"].append(box_uid)
            except Exception as e:
                results["failed"].append({"uid": box_uid, "error": str(e)})

        return results

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
    ) -> List[dict]:
        """获取未分配箱子，可按客户和唛头过滤。"""
        from services.box_validator import default_validator

        s = SessionFactory()
        try:
            query = s.query(PackingListTable).filter(PackingListTable.archive == False)
            if customer_id is not None:
                query = query.filter(PackingListTable.customer_id == customer_id)

            if mark_search:
                query = query.filter(
                    PackingListTable.list_number.like(
                        f"%{mark_search.strip().upper()}%"
                    )
                )

            packing_lists = query.order_by(PackingListTable.create_date.desc()).all()

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

            return result
        finally:
            s.close()

    def batch_ship(self, packing_list_uid: str, box_uids: List[str]) -> dict:
        """批量出货：仅允许已分配且已有转单号、且status=0的箱子出货。"""
        results = {"success": [], "failed": []}
        if not box_uids:
            return results

        s = SessionFactory()
        try:
            records = (
                s.query(BoxTable)
                .filter(
                    BoxTable.archive == False,
                    BoxTable.packing_list_uid == packing_list_uid,
                    BoxTable.uid.in_(box_uids),
                )
                .all()
            )
            record_map = {r.uid: r for r in records}

            now = time.strftime("%Y-%m-%d %H:%M")
            for uid in box_uids:
                box = record_map.get(uid)
                if box is None:
                    results["failed"].append({"uid": uid, "error": "Box not found"})
                    continue

                if int(box.status or 0) == CARGO_STATUS_OUTBOUND:
                    results["failed"].append(
                        {
                            "uid": uid,
                            "error": "Box is already outbound",
                        }
                    )
                    continue

                if not box.target_order_uid:
                    results["failed"].append(
                        {
                            "uid": uid,
                            "error": "Box is not assigned to order",
                        }
                    )
                    continue

                if not str(box.waybill_id or "").strip():
                    results["failed"].append(
                        {
                            "uid": uid,
                            "error": "Box has no waybill yet",
                        }
                    )
                    continue

                box.status = CARGO_STATUS_OUTBOUND
                box.date = now
                box.update_date = now
                results["success"].append(uid)

            s.commit()
            return results
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
        return {
            "uid": record.uid,
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
