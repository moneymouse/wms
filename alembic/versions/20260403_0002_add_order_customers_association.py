"""Add order_customers association table for many-to-many relationship

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-03

This migration creates the order_customers association table to establish
a many-to-many relationship between orders and customers.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the order_customers association table
    op.create_table(
        "order_customers",
        sa.Column("order_uid", sa.String(32), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("order_uid", "customer_id"),
        sa.ForeignKeyConstraint(
            ["order_uid"],
            ["orders.uid"],
            name="fk_oc_order",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_oc_customer",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
    )
    # Add index for customer_id for better query performance
    op.create_index("idx_oc_customer", "order_customers", ["customer_id"])


def downgrade() -> None:
    op.drop_index("idx_oc_customer", table_name="order_customers")
    op.drop_table("order_customers")
