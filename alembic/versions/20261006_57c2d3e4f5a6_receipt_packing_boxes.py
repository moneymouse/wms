"""Descriptive packing-box identities on customer payments.

Revision ID: 57c2d3e4f5a6
Revises: 46b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = "57c2d3e4f5a6"
down_revision = "46b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("finance_payments", sa.Column("reference_packing_boxes_json", sa.Text().with_variant(LONGTEXT(), "mysql"), nullable=True))


def downgrade():
    with op.batch_alter_table("finance_payments") as batch:
        batch.drop_column("reference_packing_boxes_json")
