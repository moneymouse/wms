"""Add re-quote price adjustments and outbound-lock lookup index.

Revision ID: ac1d2e3f4a5b
Revises: 9b0c1d2e3f4a
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ac1d2e3f4a5b"
down_revision: Union[str, None] = "9b0c1d2e3f4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_price_adjustments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_uid", sa.String(length=32), nullable=False),
        sa.Column("previous_quote_id", sa.Integer(), nullable=False),
        sa.Column("new_quote_id", sa.Integer(), nullable=False),
        sa.Column("old_receivable", sa.Numeric(14, 2), nullable=False),
        sa.Column("new_receivable", sa.Numeric(14, 2), nullable=False),
        sa.Column("delta_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("creator_name", sa.String(length=128), nullable=False),
        sa.Column("create_date", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["order_uid"], ["orders.uid"]),
        sa.ForeignKeyConstraint(["previous_quote_id"], ["order_quote_versions.id"]),
        sa.ForeignKeyConstraint(["new_quote_id"], ["order_quote_versions.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("new_quote_id", name="uq_order_price_adjustments_new_quote"),
    )
    op.create_index(
        "idx_order_price_adjustments_order_status",
        "order_price_adjustments",
        ["order_uid", "status"],
        unique=False,
    )
    op.create_index(
        "idx_order_price_adjustments_created",
        "order_price_adjustments",
        ["create_date", "id"],
        unique=False,
    )
    op.create_index(
        "idx_cargos_order_outbound_lock",
        "cargos",
        ["target_order_uid", "archive", "packing_list_uid", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_cargos_order_outbound_lock", table_name="cargos")
    op.drop_index(
        "idx_order_price_adjustments_created",
        table_name="order_price_adjustments",
    )
    op.drop_index(
        "idx_order_price_adjustments_order_status",
        table_name="order_price_adjustments",
    )
    op.drop_table("order_price_adjustments")
