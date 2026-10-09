"""Store receipt settlement choices and approved settlement differences.

Revision ID: 7f8a9b0c1d2e
Revises: 6e7f8a9b0c1d
Create Date: 2026-09-09
"""

from alembic import op
import sqlalchemy as sa


revision = "7f8a9b0c1d2e"
down_revision = "6e7f8a9b0c1d"
branch_labels = None
depends_on = None


def upgrade():
    # NULL deliberately preserves existing receipts without reinterpreting
    # historical small balances as waived income.
    op.add_column(
        "payment_receipts",
        sa.Column("settlement_status", sa.String(16), nullable=True),
    )
    op.add_column(
        "payment_receipt_items",
        sa.Column("settlement_difference", sa.Numeric(14, 2), nullable=True),
    )


def downgrade():
    with op.batch_alter_table("payment_receipt_items") as batch_op:
        batch_op.drop_column("settlement_difference")
    with op.batch_alter_table("payment_receipts") as batch_op:
        batch_op.drop_column("settlement_status")
