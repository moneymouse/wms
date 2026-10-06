"""Accounting records independent from operational order lifecycles."""
from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from data.database import Base


class FinanceSettings(Base):
    __tablename__ = "finance_settings"
    id = Column(Integer, primary_key=True)
    company_name = Column(String(200), nullable=False)
    currency = Column(String(3), nullable=False, default="CNY")
    revenue_policy = Column(String(20), nullable=False, default="deferred")
    opening_date = Column(String(10), nullable=False)
    opening_confirmed = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)


class FinanceGLAccount(Base):
    __tablename__ = "finance_gl_accounts"
    code = Column(String(20), primary_key=True)
    name = Column(String(120), nullable=False)
    account_type = Column(String(20), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    system = Column(Boolean, nullable=False, default=False)


class FinancePeriod(Base):
    __tablename__ = "finance_periods"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(40), nullable=False)
    date_from = Column(String(10), nullable=False)
    date_to = Column(String(10), nullable=False)
    status = Column(String(16), nullable=False, default="open")
    version = Column(Integer, nullable=False, default=1)
    closed_at = Column(String(32))
    closed_by = Column(String(128))
    remark = Column(Text)
    __table_args__ = (UniqueConstraint("date_from", "date_to", name="uq_finance_period_dates"),)


class FinanceJournalEntry(Base):
    __tablename__ = "finance_journal_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(String(50), nullable=False, unique=True)
    entry_date = Column(String(10), nullable=False, index=True)
    kind = Column(String(24), nullable=False)
    source_type = Column(String(40))
    source_id = Column(String(64))
    source_action = Column(String(24))
    description = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    reversal_of_id = Column(Integer, ForeignKey("finance_journal_entries.id"), unique=True)
    cashflow_activity = Column(String(16), nullable=False, default="operating")
    created_at = Column(String(32), nullable=False)
    created_by_id = Column(Integer)
    created_by_name = Column(String(128), nullable=False)
    posted_at = Column(String(32))
    lines = relationship("FinanceJournalLine", cascade="all, delete-orphan", order_by="FinanceJournalLine.id")
    __table_args__ = (UniqueConstraint("source_type", "source_id", "source_action", name="uq_finance_entry_source"),)


class FinanceJournalLine(Base):
    __tablename__ = "finance_journal_lines"
    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("finance_journal_entries.id"), nullable=False, index=True)
    account_code = Column(String(20), ForeignKey("finance_gl_accounts.code"), nullable=False, index=True)
    account_name = Column(String(120), nullable=False)
    debit = Column(Numeric(18, 2), nullable=False, default=0)
    credit = Column(Numeric(18, 2), nullable=False, default=0)
    partner_type = Column(String(16))
    partner_id = Column(Integer)
    partner_name = Column(String(200))
    fund_account_id = Column(Integer, ForeignKey("finance_accounts.id"))
    memo = Column(String(500))


class FinanceBankTransaction(Base):
    __tablename__ = "finance_bank_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("finance_accounts.id"), nullable=False, index=True)
    transaction_date = Column(String(10), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    reference = Column(String(200), nullable=False)
    description = Column(String(500))
    fingerprint = Column(String(64), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="unmatched")
    payment_id = Column(Integer, ForeignKey("finance_payments.id"), unique=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String(32), nullable=False)
    matched_at = Column(String(32))
