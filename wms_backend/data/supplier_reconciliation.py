"""Immutable uploaded supplier evidence and links to draft payable lines."""
from sqlalchemy import Column, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT
from sqlalchemy.orm import relationship

from data.database import Base

JSON_TEXT = Text().with_variant(LONGTEXT(), "mysql")


class SupplierReconciliationBatch(Base):
    __tablename__ = "supplier_reconciliation_batches"
    __table_args__ = (
        UniqueConstraint("vendor_id", "period", "file_hash", name="uq_supplier_reconciliation_file"),
        Index("ix_supplier_reconciliation_vendor_period", "vendor_id", "period"),
    )
    id = Column(Integer, primary_key=True)
    number = Column(String(40), nullable=False, unique=True)
    vendor_id = Column(Integer, ForeignKey("finance_vendors.id"), nullable=False)
    vendor_name = Column(String(256), nullable=False)
    period = Column(String(7), nullable=False)
    filename = Column(String(256), nullable=False)
    file_hash = Column(String(64), nullable=False)
    file_bytes = Column(LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False)
    status = Column(String(24), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    total_rows = Column(Integer, nullable=False, default=0)
    passed_rows = Column(Integer, nullable=False, default=0)
    exception_rows = Column(Integer, nullable=False, default=0)
    passed_amount = Column(Numeric(18, 2), nullable=False, default=0)
    total_valid_amount = Column(Numeric(18, 2), nullable=False, default=0)
    created_by_id = Column(Integer, nullable=False)
    created_by_name = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    rows = relationship("SupplierReconciliationRow", back_populates="batch", order_by="SupplierReconciliationRow.source_row")


class SupplierReconciliationRow(Base):
    __tablename__ = "supplier_reconciliation_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_row", name="uq_supplier_reconciliation_source_row"),
        Index("ix_supplier_reconciliation_fingerprint", "fingerprint"),
        Index("ix_supplier_reconciliation_batch_status", "batch_id", "status"),
        Index("ix_supplier_reconciliation_document", "finance_document_id"),
        Index("ix_supplier_reconciliation_cargo", "cargo_uid", "system_waybill"),
    )
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("supplier_reconciliation_batches.id"), nullable=False)
    source_row = Column(Integer, nullable=False)
    raw_json = Column(JSON_TEXT, nullable=False)
    original_number = Column(String(256), nullable=False, default="")
    waybill_number = Column(String(256), nullable=False, default="")
    weight = Column(Numeric(18, 3), nullable=True)
    final_fee = Column(Numeric(18, 2), nullable=True)
    description = Column(String(512), nullable=False, default="")
    status = Column(String(16), nullable=False)
    parse_issues_json = Column(JSON_TEXT, nullable=False, default="[]")
    issues_json = Column(JSON_TEXT, nullable=False, default="[]")
    fingerprint = Column(String(64), nullable=True)
    # Operational identity and names are snapshots and survive order deletion.
    cargo_uid = Column(String(32), nullable=True)
    order_uid = Column(String(32), nullable=True)
    order_number = Column(String(128), nullable=True)
    system_weight = Column(Numeric(18, 3), nullable=True)
    system_waybill = Column(String(256), nullable=True)
    weight_difference = Column(Numeric(18, 3), nullable=True)
    match_snapshot_json = Column(JSON_TEXT, nullable=True)
    finance_document_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=True)
    finance_document_line_id = Column(Integer, ForeignKey("finance_document_lines.id"), nullable=True, unique=True)
    batch = relationship("SupplierReconciliationBatch", back_populates="rows")
