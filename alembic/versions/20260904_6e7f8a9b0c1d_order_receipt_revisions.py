"""Add controlled order receipt revision windows.

Revision ID: 6e7f8a9b0c1d
Revises: 5d6e7f8a9b0c
Create Date: 2026-09-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6e7f8a9b0c1d"
down_revision: Union[str, None] = "5d6e7f8a9b0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_receipt_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_uid", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="open"
        ),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("opened_by_id", sa.Integer(), nullable=True),
        sa.Column("opened_by_name", sa.String(length=128), nullable=False),
        sa.Column("opened_at", sa.String(length=32), nullable=False),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.Column("closed_by_name", sa.String(length=128), nullable=True),
        sa.Column("closed_at", sa.String(length=32), nullable=True),
        sa.Column("close_type", sa.String(length=32), nullable=True),
        sa.Column("close_remark", sa.String(length=512), nullable=True),
        sa.Column("closing_receipt_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["closing_receipt_id"], ["payment_receipts.id"]
        ),
        sa.ForeignKeyConstraint(["opened_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_uid"], ["orders.uid"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_order_receipt_revisions_order_status",
        "order_receipt_revisions",
        ["order_uid", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_order_receipt_revisions_order_status",
        table_name="order_receipt_revisions",
    )
    op.drop_table("order_receipt_revisions")
