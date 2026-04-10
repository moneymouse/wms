"""
Finance bonus rate model.

管理 1-4 人合打的奖金基数。
"""

import time
from typing import Dict, List

from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from data.database import Base, SessionFactory


class BonusRateTable(Base):
    """奖金基数配置表"""

    __tablename__ = "bonus_rates"

    team_size = Column(Integer, primary_key=True)  # 1~4
    base_amount = Column(Float, nullable=False, default=0.0)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    update_date = Column(String(32))

    updater = relationship("UserTable", lazy="select")


class BonusRateModel:
    """奖金基数数据操作"""

    MIN_TEAM_SIZE = 1
    MAX_TEAM_SIZE = 4

    def _ensure_default_rows(self, session) -> None:
        """确保 1~4 人合打的配置行存在。"""
        for team_size in range(self.MIN_TEAM_SIZE, self.MAX_TEAM_SIZE + 1):
            record = (
                session.query(BonusRateTable).filter_by(team_size=team_size).first()
            )
            if record is None:
                session.add(BonusRateTable(team_size=team_size, base_amount=0.0))

    def _to_dict(self, record: BonusRateTable) -> dict:
        return {
            "team_size": record.team_size,
            "base_amount": float(record.base_amount or 0.0),
            "updated_by": record.updated_by,
            "updated_by_name": record.updater.name if record.updater else None,
            "update_date": record.update_date,
        }

    def get_all(self) -> List[dict]:
        """获取全部奖金基数配置（1~4）。"""
        with SessionFactory() as session:
            self._ensure_default_rows(session)
            session.commit()

            records = (
                session.query(BonusRateTable)
                .order_by(BonusRateTable.team_size.asc())
                .all()
            )
            return [self._to_dict(record) for record in records]

    def get_rate_map(self) -> Dict[str, float]:
        """获取 {"1": x, ..., "4": x} 结构的基数映射。"""
        records = self.get_all()
        return {str(record["team_size"]): record["base_amount"] for record in records}

    def set_rates(self, rates: Dict[int, float], operator_id: int = None) -> List[dict]:
        """批量更新 1~4 人合打奖金基数。"""
        now = time.strftime("%Y-%m-%d %H:%M")

        with SessionFactory() as session:
            self._ensure_default_rows(session)

            for team_size in range(self.MIN_TEAM_SIZE, self.MAX_TEAM_SIZE + 1):
                if team_size not in rates:
                    continue

                record = (
                    session.query(BonusRateTable).filter_by(team_size=team_size).first()
                )
                record.base_amount = float(rates[team_size])
                record.updated_by = operator_id
                record.update_date = now

            session.commit()

            records = (
                session.query(BonusRateTable)
                .order_by(BonusRateTable.team_size.asc())
                .all()
            )
            return [self._to_dict(record) for record in records]


bonus_rate_model = BonusRateModel()
