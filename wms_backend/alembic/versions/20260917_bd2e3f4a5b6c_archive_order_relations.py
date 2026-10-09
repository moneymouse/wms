"""Add archive markers for order-owned financial records.

Revision ID: bd2e3f4a5b6c
Revises: ac1d2e3f4a5b
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bd2e3f4a5b6c"
down_revision: Union[str, None] = "ac1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in (
        "box_cost_records",
        "order_quote_versions",
        "order_price_adjustments",
        "payment_receipt_items",
    ):
        op.add_column(
            table_name,
            sa.Column(
                "archive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    op.create_index(
        "idx_box_cost_records_order_archive",
        "box_cost_records",
        ["order_uid", "archive"],
        unique=False,
    )
    op.create_index(
        "idx_order_quote_versions_order_archive",
        "order_quote_versions",
        ["order_uid", "archive"],
        unique=False,
    )
    op.create_index(
        "idx_order_price_adjustments_order_archive",
        "order_price_adjustments",
        ["order_uid", "archive"],
        unique=False,
    )
    op.create_index(
        "idx_payment_receipt_items_order_archive",
        "payment_receipt_items",
        ["order_uid", "archive"],
        unique=False,
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("idx_payment_receipt_items_order_archive", "payment_receipt_items"),
        ("idx_order_price_adjustments_order_archive", "order_price_adjustments"),
        ("idx_order_quote_versions_order_archive", "order_quote_versions"),
        ("idx_box_cost_records_order_archive", "box_cost_records"),
    ):
        op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "payment_receipt_items",
        "order_price_adjustments",
        "order_quote_versions",
        "box_cost_records",
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("archive")
