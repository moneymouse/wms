"""Persist reusable shipping confirmation drafts.

Revision ID: 68d3e4f5a6b7
Revises: 57c2d3e4f5a6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "68d3e4f5a6b7"
down_revision = "57c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shipping_confirmation_drafts",
        sa.Column("uid", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("entries_json", sa.Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("archive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_shipping_confirmation_drafts_creator_id", "shipping_confirmation_drafts", ["creator_id"])
    # Full draft/payment snapshots can exceed MySQL's 64 KiB TEXT capacity.
    if op.get_bind().dialect.name == "mysql":
        for field in ("before_data", "after_data"):
            op.alter_column("audit_logs", field, existing_type=sa.Text(),
                            type_=mysql.LONGTEXT(), existing_nullable=True)


def downgrade():
    op.drop_index("ix_shipping_confirmation_drafts_creator_id", table_name="shipping_confirmation_drafts")
    op.drop_table("shipping_confirmation_drafts")
    # Keep the expanded append-only audit storage: receipts created after the
    # upgrade can retain large snapshots even when draft support is removed.
