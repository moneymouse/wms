"""Explicit cutover baselines and evidence; operational orders remain untouched."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Numeric, String, Text
from data.database import Base


class FinanceLegacyLink(Base):
    __tablename__ = "finance_legacy_links"
    id = Column(Integer, primary_key=True)
    order_uid = Column(String(32), nullable=False, unique=True)
    order_number = Column(String(128), nullable=False)
    customer_id = Column(Integer, nullable=False)
    customer_name = Column(String(256), nullable=False)
    cutoff_date = Column(String(10), nullable=False)
    import_kind = Column(String(16), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    document_id = Column(Integer, ForeignKey("finance_documents.id"))
    payment_id = Column(Integer, ForeignKey("finance_payments.id"))
    source_hash = Column(String(64), nullable=False)
    source_snapshot = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    revoked_at = Column(String(32))
    revoke_reason = Column(Text)
    version = Column(Integer, nullable=False, default=1)
    imported_at = Column(String(32), nullable=False)
    last_reconciled_at = Column(String(32), nullable=False)
    created_by_id = Column(Integer, nullable=False)
    created_by_name = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False)


class FinanceLegacyEvidence(Base):
    __tablename__ = "finance_legacy_evidence"
    __table_args__ = (CheckConstraint("(document_id IS NOT NULL AND payment_id IS NULL) OR (document_id IS NULL AND payment_id IS NOT NULL)", name="ck_finance_legacy_evidence_source"),)
    id = Column(Integer, primary_key=True)
    link_id = Column(Integer, ForeignKey("finance_legacy_links.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("finance_documents.id"), unique=True)
    payment_id = Column(Integer, ForeignKey("finance_payments.id"), unique=True)
    effect_amount = Column(Numeric(18, 2), nullable=False)
    snapshot = Column(Text, nullable=False)
    created_at = Column(String(32), nullable=False)
