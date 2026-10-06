"""Accounting journals, periods and bank matching.

Revision ID: 027d8e9f0a1b
Revises: f16c7d8e9f0a
"""
from alembic import op
import sqlalchemy as sa

revision = "027d8e9f0a1b"
down_revision = "f16c7d8e9f0a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("finance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("revenue_policy", sa.String(20), nullable=False),
        sa.Column("opening_date", sa.String(10), nullable=False),
        sa.Column("opening_confirmed", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False))
    op.create_table("finance_gl_accounts",
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("system", sa.Boolean(), nullable=False))
    op.create_table("finance_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("date_from", sa.String(10), nullable=False),
        sa.Column("date_to", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.String(32)),
        sa.Column("closed_by", sa.String(128)),
        sa.Column("remark", sa.Text()),
        sa.UniqueConstraint("date_from", "date_to", name="uq_finance_period_dates"))
    op.create_table("finance_journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(50), nullable=False, unique=True),
        sa.Column("entry_date", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_id", sa.String(64)),
        sa.Column("source_action", sa.String(24)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("finance_journal_entries.id"), unique=True),
        sa.Column("cashflow_activity", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.Integer()),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("posted_at", sa.String(32)),
        sa.UniqueConstraint("source_type", "source_id", "source_action", name="uq_finance_entry_source"))
    op.create_index("ix_finance_journal_entries_entry_date", "finance_journal_entries", ["entry_date"])
    op.create_table("finance_journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("finance_journal_entries.id"), nullable=False),
        sa.Column("account_code", sa.String(20), sa.ForeignKey("finance_gl_accounts.code"), nullable=False),
        sa.Column("account_name", sa.String(120), nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False),
        sa.Column("partner_type", sa.String(16)),
        sa.Column("partner_id", sa.Integer()),
        sa.Column("partner_name", sa.String(200)),
        sa.Column("fund_account_id", sa.Integer(), sa.ForeignKey("finance_accounts.id")),
        sa.Column("memo", sa.String(500)))
    op.create_index("ix_finance_journal_lines_entry_id", "finance_journal_lines", ["entry_id"])
    op.create_index("ix_finance_journal_lines_account_code", "finance_journal_lines", ["account_code"])
    op.create_table("finance_bank_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("finance_accounts.id"), nullable=False),
        sa.Column("transaction_date", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("finance_payments.id"), unique=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("matched_at", sa.String(32)))
    op.create_index("ix_finance_bank_transactions_account_id", "finance_bank_transactions", ["account_id"])


def downgrade():
    op.drop_table("finance_bank_transactions")
    op.drop_table("finance_journal_lines")
    op.drop_table("finance_journal_entries")
    op.drop_table("finance_periods")
    op.drop_table("finance_gl_accounts")
    op.drop_table("finance_settings")
