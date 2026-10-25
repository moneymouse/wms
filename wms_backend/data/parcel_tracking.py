"""Durable webhook snapshots, retaining business identifiers after deletion."""

from sqlalchemy import Boolean, Column, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from data.database import Base


class ParcelTrackingUpdateTable(Base):
    __tablename__ = "parcel_tracking_updates"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_parcel_tracking_event"),
        Index("ix_parcel_tracking_scope_current", "cargo_uid", "order_uid", "waybill_id", "is_current"),
        Index("ix_parcel_tracking_received", "received_at", "uid"),
    )

    uid = Column(String(32), primary_key=True)
    cargo_uid = Column(String(32), nullable=False)
    order_uid = Column(String(32), nullable=False)
    waybill_id = Column(String(256), nullable=False)
    event_key = Column(String(128), nullable=False)
    row_json = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False)
    received_at = Column(String(32), nullable=False)
    source_updated_at = Column(String(32))
    is_current = Column(Boolean, nullable=False, default=False)
    exception_uid = Column(String(32))
