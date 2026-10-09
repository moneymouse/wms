"""Order receivable snapshots; payment references never create these links."""
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text
from data.database import Base


class FinanceOrderSettlement(Base):
    __tablename__ = "finance_order_settlements"
    order_uid = Column(String(32), primary_key=True)
    order_number = Column(String(128), nullable=False)
    customer_id = Column(Integer, nullable=False)
    legacy_link_id = Column(Integer, ForeignKey("finance_legacy_links.id"))
    legacy_offset = Column(Numeric(18, 2), nullable=False, default=0)
    legacy_receipts_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)


class FinanceOrderDocument(Base):
    __tablename__ = "finance_order_documents"
    document_id = Column(Integer, ForeignKey("finance_documents.id"), primary_key=True)
    order_uid = Column(String(32), ForeignKey("finance_order_settlements.order_uid"), nullable=False, index=True)
    source_hash = Column(String(64), nullable=False)
    source_snapshot = Column(Text, nullable=False)
