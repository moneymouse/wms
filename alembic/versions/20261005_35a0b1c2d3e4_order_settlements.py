"""Explicit order receivables and allocation provenance.

Revision ID: 35a0b1c2d3e4
Revises: 249fa0b1c2d3
"""
from alembic import op
import sqlalchemy as sa

revision = "35a0b1c2d3e4"
down_revision = "249fa0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("finance_order_settlements",
        sa.Column("order_uid", sa.String(32), primary_key=True),
        sa.Column("order_number", sa.String(128), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("legacy_link_id", sa.Integer(), sa.ForeignKey("finance_legacy_links.id")),
        sa.Column("legacy_offset", sa.Numeric(18, 2), nullable=False),
        sa.Column("legacy_receipts_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False))
    op.create_table("finance_order_documents",
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("finance_documents.id"), primary_key=True),
        sa.Column("order_uid", sa.String(32), sa.ForeignKey("finance_order_settlements.order_uid"), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.Text(), nullable=False))
    op.create_index("ix_finance_order_documents_order_uid", "finance_order_documents", ["order_uid"])


def downgrade():
    op.drop_index("ix_finance_order_documents_order_uid", table_name="finance_order_documents")
    op.drop_table("finance_order_documents")
    op.drop_table("finance_order_settlements")
