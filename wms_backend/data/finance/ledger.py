"""Independent financial subledger. Posted facts never follow live order values."""

from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import LONGTEXT

from data.database import Base


class FinanceVendor(Base):
    __tablename__ = "finance_vendors"
    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False, unique=True)
    contact = Column(String(128), nullable=False, default="")
    phone = Column(String(64), nullable=False, default="")
    memo = Column(Text, nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)


class FinanceAccount(Base):
    __tablename__ = "finance_accounts"
    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False, unique=True)
    account_type = Column(String(16), nullable=False)
    account_number = Column(String(128), nullable=False, default="")
    currency = Column(String(3), nullable=False, default="CNY")
    memo = Column(Text, nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)


class FinanceDocument(Base):
    __tablename__ = "finance_documents"
    __table_args__ = (
        Index("ix_finance_documents_partner", "partner_type", "partner_id", "status"),
        Index("ix_finance_documents_due", "document_date", "due_date"),
        CheckConstraint("total_amount >= 0", name="ck_finance_documents_amount"),
    )
    id = Column(Integer, primary_key=True)
    number = Column(String(40), nullable=False, unique=True)
    document_type = Column(String(24), nullable=False)
    is_opening = Column(Boolean, nullable=False, default=False)
    partner_type = Column(String(16), nullable=False)
    partner_id = Column(Integer, nullable=False)
    partner_name = Column(String(256), nullable=False)
    document_date = Column(String(10), nullable=False)
    due_date = Column(String(10), nullable=False)
    currency = Column(String(3), nullable=False, default="CNY")
    reference = Column(String(256), nullable=False, default="")
    memo = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    subtotal = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), nullable=False)
    total_amount = Column(Numeric(18, 2), nullable=False)
    original_document_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=True)
    reversed_by_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    posted_at = Column(String(32), nullable=True)
    cancelled_at = Column(String(32), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    lines = relationship("FinanceDocumentLine", back_populates="document", cascade="all, delete-orphan", order_by="FinanceDocumentLine.sequence")


class FinanceDocumentLine(Base):
    __tablename__ = "finance_document_lines"
    __table_args__ = (UniqueConstraint("document_id", "sequence", name="uq_finance_line_sequence"),)
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    description = Column(String(512), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False)
    unit_price = Column(Numeric(18, 4), nullable=False)
    tax_rate = Column(Numeric(7, 4), nullable=False, default=0)
    subtotal = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), nullable=False)
    total_amount = Column(Numeric(18, 2), nullable=False)
    # Snapshots deliberately survive deletion/archive of the operational order.
    order_uid = Column(String(32), nullable=True)
    order_number = Column(String(128), nullable=True)
    document = relationship("FinanceDocument", back_populates="lines", foreign_keys=[document_id])


class FinancePayment(Base):
    __tablename__ = "finance_payments"
    __table_args__ = (
        Index("ix_finance_payments_partner", "partner_type", "partner_id", "status"),
        Index("ix_finance_payments_creator_status", "created_by_id", "status"),
        CheckConstraint("amount > 0", name="ck_finance_payments_amount"),
    )
    id = Column(Integer, primary_key=True)
    number = Column(String(40), nullable=False, unique=True)
    direction = Column(String(16), nullable=False)
    is_opening = Column(Boolean, nullable=False, default=False)
    partner_type = Column(String(16), nullable=False)
    partner_id = Column(Integer, nullable=False)
    partner_name = Column(String(256), nullable=False)
    account_id = Column(Integer, ForeignKey("finance_accounts.id"), nullable=False)
    account_name = Column(String(256), nullable=False)
    payment_date = Column(String(10), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="CNY")
    reference = Column(String(256), nullable=False, default="")
    memo = Column(Text, nullable=False, default="")
    reference_orders_json = Column(Text, nullable=True)
    reference_packing_boxes_json = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    requires_submission = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    posted_at = Column(String(32), nullable=True)
    submitted_at = Column(String(32), nullable=True)
    submitted_by_id = Column(Integer, nullable=True)
    submitted_by_name = Column(String(128), nullable=True)
    reviewed_at = Column(String(32), nullable=True)
    reviewed_by_id = Column(Integer, nullable=True)
    reviewed_by_name = Column(String(128), nullable=True)
    review_remark = Column(Text, nullable=True)
    cancelled_at = Column(String(32), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    reversed_at = Column(String(32), nullable=True)
    reversal_date = Column(String(10), nullable=True)
    reversal_reason = Column(Text, nullable=True)


class FinanceAllocation(Base):
    __tablename__ = "finance_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_finance_allocations_amount"),
        CheckConstraint("(payment_id IS NOT NULL AND credit_document_id IS NULL) OR (payment_id IS NULL AND credit_document_id IS NOT NULL)", name="ck_finance_allocations_source"),
        Index("ix_finance_allocations_document", "document_id", "status"),
        Index("ix_finance_allocations_payment", "payment_id", "status"),
        Index("ix_finance_allocations_credit", "credit_document_id", "status"),
    )
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("finance_payments.id"), nullable=True)
    credit_document_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=True)
    document_id = Column(Integer, ForeignKey("finance_documents.id"), nullable=False)
    document_number = Column(String(40), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    version = Column(Integer, nullable=False, default=1)
    allocation_date = Column(String(10), nullable=False)
    reason = Column(Text, nullable=False, default="")
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    reversed_at = Column(String(32), nullable=True)
    reversal_date = Column(String(10), nullable=True)
    reversal_reason = Column(Text, nullable=True)


class FinanceIdempotency(Base):
    __tablename__ = "finance_idempotency"
    __table_args__ = (UniqueConstraint("actor_id", "key", name="uq_finance_idempotency_actor_key"),)
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=False)
    key = Column(String(128), nullable=False)
    operation = Column(String(128), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    response_json = Column(Text, nullable=False)
    created_at = Column(String(32), nullable=False)
