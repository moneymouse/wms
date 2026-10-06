"""Unified customer payment entry, review and descriptive order snapshots.

Revision ID: 249fa0b1c2d3
Revises: 138e9f0a1b2c
"""
from alembic import op
import sqlalchemy as sa

revision = "249fa0b1c2d3"
down_revision = "138e9f0a1b2c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("finance_payments", sa.Column("requires_submission", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("finance_payments", sa.Column("reference_orders_json", sa.Text(), nullable=True))
    op.add_column("finance_payments", sa.Column("submitted_at", sa.String(32), nullable=True))
    op.add_column("finance_payments", sa.Column("submitted_by_id", sa.Integer(), nullable=True))
    op.add_column("finance_payments", sa.Column("submitted_by_name", sa.String(128), nullable=True))
    op.add_column("finance_payments", sa.Column("reviewed_at", sa.String(32), nullable=True))
    op.add_column("finance_payments", sa.Column("reviewed_by_id", sa.Integer(), nullable=True))
    op.add_column("finance_payments", sa.Column("reviewed_by_name", sa.String(128), nullable=True))
    op.add_column("finance_payments", sa.Column("review_remark", sa.Text(), nullable=True))
    op.create_index("ix_finance_payments_creator_status", "finance_payments", ["created_by_id", "status"])


def downgrade():
    op.drop_index("ix_finance_payments_creator_status", table_name="finance_payments")
    with op.batch_alter_table("finance_payments") as batch:
        for name in ("review_remark", "reviewed_by_name", "reviewed_by_id", "reviewed_at", "submitted_by_name", "submitted_by_id", "submitted_at", "reference_orders_json", "requires_submission"):
            batch.drop_column(name)
