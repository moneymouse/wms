"""Explicit, reviewed legacy balance cutover; no automatic historical backfill.

Revision ID: 138e9f0a1b2c
Revises: h38e9f0a1b2c
"""
from alembic import op
import sqlalchemy as sa

revision = "138e9f0a1b2c"
down_revision = "h38e9f0a1b2c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("finance_legacy_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_uid", sa.String(32), nullable=False, unique=True),
        sa.Column("order_number", sa.String(128), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(256), nullable=False),
        sa.Column("cutoff_date", sa.String(10), nullable=False),
        sa.Column("import_kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("finance_documents.id")),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("finance_payments.id")),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("revoked_at", sa.String(32)),
        sa.Column("revoke_reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.String(32), nullable=False),
        sa.Column("last_reconciled_at", sa.String(32), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False))
    op.create_table("finance_legacy_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("finance_legacy_links.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("finance_documents.id"), unique=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("finance_payments.id"), unique=True),
        sa.Column("effect_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.CheckConstraint("(document_id IS NOT NULL AND payment_id IS NULL) OR (document_id IS NULL AND payment_id IS NOT NULL)", name="ck_finance_legacy_evidence_source"))


def downgrade():
    op.drop_table("finance_legacy_evidence")
    op.drop_table("finance_legacy_links")
