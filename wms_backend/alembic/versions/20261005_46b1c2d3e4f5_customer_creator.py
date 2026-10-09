"""Track the authenticated creator of customer records.

Revision ID: 46b1c2d3e4f5
Revises: 35a0b1c2d3e4
"""

from alembic import op
import sqlalchemy as sa

revision = "46b1c2d3e4f5"
down_revision = "35a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    # Existing records retain NULL: an order's salesman is not its customer's creator.
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("created_by_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_customers_created_by_id_users", "users", ["created_by_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_customers_created_by_id", ["created_by_id"])


def downgrade():
    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_created_by_id")
        batch.drop_constraint("fk_customers_created_by_id_users", type_="foreignkey")
        batch.drop_column("created_by_id")
