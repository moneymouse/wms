"""Link supplemental receipts to re-quote price adjustments.

Revision ID: ce3f4a5b6c7d
Revises: bd2e3f4a5b6c
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "ce3f4a5b6c7d"
down_revision = "bd2e3f4a5b6c"
branch_labels = None
depends_on = None


def upgrade():
    # NULL preserves the purpose of existing ordinary receipt items.
    with op.batch_alter_table("payment_receipt_items") as batch_op:
        batch_op.add_column(sa.Column("adjustment_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_payment_receipt_items_adjustment",
            "order_price_adjustments",
            ["adjustment_id"],
            ["id"],
        )
        batch_op.create_index("idx_payment_receipt_items_adjustment", ["adjustment_id"])


def downgrade():
    with op.batch_alter_table("payment_receipt_items") as batch_op:
        batch_op.drop_index("idx_payment_receipt_items_adjustment")
        batch_op.drop_constraint("fk_payment_receipt_items_adjustment", type_="foreignkey")
        batch_op.drop_column("adjustment_id")
