"""Exception cases and append-only follow-up facts.

Business identifiers and names are snapshots so existing hard-delete paths do
not erase history. Services authorize every access against the live order.
"""

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from data.database import Base


class OrderExceptionTable(Base):
    __tablename__ = "order_exceptions"
    __table_args__ = (
        Index("ix_exception_order_scope_status", "order_uid", "cargo_uid", "status"),
        Index("ix_exception_created", "created_at", "uid"),
    )

    uid = Column(String(32), primary_key=True)
    order_uid = Column(String(32), nullable=False)
    order_id = Column(String(128))
    cargo_uid = Column(String(32))
    origin_id = Column(String(128))
    transfer_id = Column(String(256))
    waybill_id = Column(String(256))
    salesman_id = Column(Integer, nullable=False)
    salesman_name = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)
    source = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="open")
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    resolved_at = Column(String(32))
    resolved_by_id = Column(Integer)


class OrderExceptionHistoryTable(Base):
    __tablename__ = "order_exception_history"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_exception_history_event"),
        Index("ix_exception_history_case_created", "exception_uid", "created_at", "uid"),
    )

    uid = Column(String(32), primary_key=True)
    exception_uid = Column(String(32), ForeignKey("order_exceptions.uid", ondelete="CASCADE"), nullable=False)
    event_key = Column(String(128), nullable=False)
    request_digest = Column(String(64), nullable=False)
    action = Column(String(32), nullable=False)
    note = Column(Text, nullable=False)
    source = Column(String(32), nullable=False)
    actor_id = Column(Integer)
    actor_name = Column(String(128))
    tracking_status = Column(String(64))
    created_at = Column(String(32), nullable=False)

    def to_dict(self):
        return {
            "uid": self.uid,
            "action": self.action,
            "type": self.action,
            "note": self.note,
            "source": self.source,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "tracking_status": self.tracking_status,
            "created_at": self.created_at,
        }
