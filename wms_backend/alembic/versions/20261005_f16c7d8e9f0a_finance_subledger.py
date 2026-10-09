"""Independent finance documents, funds and reconciliation (no legacy backfill).

Revision ID: f16c7d8e9f0a
Revises: e05b6c7d8e9f
"""
from alembic import op
import sqlalchemy as sa

revision = "f16c7d8e9f0a"
down_revision = "e05b6c7d8e9f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_audit_logs_target_history", "audit_logs", ["target_type", "target_id", "id"])
    op.create_table("finance_vendors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False, unique=True),
        sa.Column("contact", sa.String(128), nullable=False),
        sa.Column("phone", sa.String(64), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False))
    op.create_table("finance_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False, unique=True),
        sa.Column("account_type", sa.String(16), nullable=False),
        sa.Column("account_number", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False))
    op.create_table("finance_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("document_type", sa.String(24), nullable=False),
        sa.Column("is_opening", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partner_type", sa.String(16), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("partner_name", sa.String(256), nullable=False),
        sa.Column("document_date", sa.String(10), nullable=False),
        sa.Column("due_date", sa.String(10), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(256), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("original_document_id", sa.Integer(), sa.ForeignKey("finance_documents.id")),
        sa.Column("reversed_by_id", sa.Integer(), sa.ForeignKey("finance_documents.id")),
        sa.Column("created_by_id", sa.Integer()),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("posted_at", sa.String(32)),
        sa.Column("cancelled_at", sa.String(32)),
        sa.Column("cancellation_reason", sa.Text()),
        sa.CheckConstraint("total_amount >= 0", name="ck_finance_documents_amount"))
    op.create_index("ix_finance_documents_partner", "finance_documents", ["partner_type", "partner_id", "status"])
    op.create_index("ix_finance_documents_due", "finance_documents", ["document_date", "due_date"])
    op.create_table("finance_document_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("finance_documents.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("order_uid", sa.String(32)),
        sa.Column("order_number", sa.String(128)),
        sa.UniqueConstraint("document_id", "sequence", name="uq_finance_line_sequence"))
    op.create_table("finance_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("is_opening", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partner_type", sa.String(16), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("partner_name", sa.String(256), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("finance_accounts.id"), nullable=False),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("payment_date", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(256), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer()),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("posted_at", sa.String(32)),
        sa.Column("cancelled_at", sa.String(32)),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("reversed_at", sa.String(32)),
        sa.Column("reversal_date", sa.String(10)),
        sa.Column("reversal_reason", sa.Text()),
        sa.CheckConstraint("amount > 0", name="ck_finance_payments_amount"))
    op.create_index("ix_finance_payments_partner", "finance_payments", ["partner_type", "partner_id", "status"])
    op.create_table("finance_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("finance_payments.id")),
        sa.Column("credit_document_id", sa.Integer(), sa.ForeignKey("finance_documents.id")),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("finance_documents.id"), nullable=False),
        sa.Column("document_number", sa.String(40), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("allocation_date", sa.String(10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Integer()),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("reversed_at", sa.String(32)),
        sa.Column("reversal_date", sa.String(10)),
        sa.Column("reversal_reason", sa.Text()),
        sa.CheckConstraint("amount > 0", name="ck_finance_allocations_amount"),
        sa.CheckConstraint("(payment_id IS NOT NULL AND credit_document_id IS NULL) OR (payment_id IS NULL AND credit_document_id IS NOT NULL)", name="ck_finance_allocations_source"))
    for field in ("document", "payment", "credit"):
        column = "credit_document_id" if field == "credit" else f"{field}_id"
        op.create_index(f"ix_finance_allocations_{field}", "finance_allocations", [column, "status"])
    op.create_table("finance_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("actor_id", "key", name="uq_finance_idempotency_actor_key"))


def downgrade():
    for name in ("finance_idempotency", "finance_allocations", "finance_payments", "finance_document_lines", "finance_documents", "finance_accounts", "finance_vendors"):
        op.drop_table(name)
    op.drop_index("ix_audit_logs_target_history", table_name="audit_logs")
