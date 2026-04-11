"""Bonus item model.

按奖金分项（标签）维护奖金基数与自动匹配规则：
- 人数规则：相等匹配
- 重量规则：区间匹配（闭区间）
"""

import time
from typing import List, Optional

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from data.database import Base, SessionFactory


class BonusItemTable(Base):
    """奖金分项配置表"""

    __tablename__ = "bonus_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(64), nullable=False, unique=True)
    base_amount = Column(Float, nullable=False, default=0.0)

    # 规则：人数精确匹配 + 重量区间匹配
    worker_count_rule = Column(Integer, nullable=False)
    weight_min = Column(Float, nullable=False, default=0.0)
    weight_max = Column(Float, nullable=False, default=999999.0)

    is_active = Column(Boolean, default=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    update_date = Column(String(32))

    updater = relationship("UserTable", lazy="select")


class BonusItemModel:
    """奖金分项数据操作"""

    def _to_dict(self, record: BonusItemTable) -> dict:
        return {
            "id": record.id,
            "label": record.label,
            "base_amount": float(record.base_amount or 0.0),
            "worker_count_rule": int(record.worker_count_rule or 0),
            "weight_min": float(record.weight_min or 0.0),
            "weight_max": float(record.weight_max or 0.0),
            "is_active": bool(record.is_active),
            "updated_by": record.updated_by,
            "updated_by_name": record.updater.name if record.updater else None,
            "update_date": record.update_date,
        }

    def list_items(self, active_only: bool = True) -> List[dict]:
        with SessionFactory() as session:
            q = session.query(BonusItemTable)
            if active_only:
                q = q.filter(BonusItemTable.is_active == True)

            records = q.order_by(
                BonusItemTable.worker_count_rule.asc(), BonusItemTable.id.asc()
            ).all()
            return [self._to_dict(record) for record in records]

    def get_item(self, item_id: int) -> Optional[dict]:
        with SessionFactory() as session:
            record = session.query(BonusItemTable).filter_by(id=item_id).first()
            if record is None:
                return None
            return self._to_dict(record)

    def create_item(
        self,
        label: str,
        base_amount: float,
        worker_count_rule: int,
        weight_min: float,
        weight_max: float,
        operator_id: Optional[int] = None,
    ) -> dict:
        now = time.strftime("%Y-%m-%d %H:%M")
        normalized_label = (label or "").strip()

        with SessionFactory() as session:
            exists = (
                session.query(BonusItemTable)
                .filter(BonusItemTable.label == normalized_label)
                .first()
            )
            if exists is not None:
                raise ValueError("label already exists")

            record = BonusItemTable(
                label=normalized_label,
                base_amount=float(base_amount),
                worker_count_rule=int(worker_count_rule),
                weight_min=float(weight_min),
                weight_max=float(weight_max),
                is_active=True,
                updated_by=operator_id,
                update_date=now,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._to_dict(record)

    def update_item(
        self,
        item_id: int,
        data: dict,
        operator_id: Optional[int] = None,
    ) -> Optional[dict]:
        now = time.strftime("%Y-%m-%d %H:%M")

        with SessionFactory() as session:
            record = session.query(BonusItemTable).filter_by(id=item_id).first()
            if record is None:
                return None

            next_label = (data.get("label") or record.label or "").strip()
            if next_label != record.label:
                exists = (
                    session.query(BonusItemTable)
                    .filter(
                        BonusItemTable.label == next_label, BonusItemTable.id != item_id
                    )
                    .first()
                )
                if exists is not None:
                    raise ValueError("label already exists")
                record.label = next_label

            if "base_amount" in data:
                record.base_amount = float(data.get("base_amount") or 0.0)
            if "worker_count_rule" in data:
                record.worker_count_rule = int(data.get("worker_count_rule") or 0)
            if "weight_min" in data:
                record.weight_min = float(data.get("weight_min") or 0.0)
            if "weight_max" in data:
                record.weight_max = float(data.get("weight_max") or 0.0)
            if "is_active" in data:
                record.is_active = bool(data.get("is_active"))

            record.updated_by = operator_id
            record.update_date = now

            session.commit()
            session.refresh(record)
            return self._to_dict(record)


bonus_item_model = BonusItemModel()
