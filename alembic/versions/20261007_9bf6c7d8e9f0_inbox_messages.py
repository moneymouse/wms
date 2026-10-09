"""Add recipient-owned business notification inbox.

Revision ID: 9bf6c7d8e9f0
Revises: 8af5b6c7d8e9
"""

from alembic import op
import sqlalchemy as sa


revision = "9bf6c7d8e9f0"
down_revision = "8af5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inbox_messages",
        sa.Column("uid", sa.String(32), primary_key=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(128), nullable=False),
        sa.Column("action_path", sa.String(1024)),
        sa.Column("business_type", sa.String(64)),
        sa.Column("business_id", sa.String(128)),
        sa.Column("event_key", sa.String(128)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("read_at", sa.String(32)),
        sa.UniqueConstraint("recipient_id", "event_key", name="uq_inbox_recipient_event"),
    )
    op.create_index("ix_inbox_recipient_created", "inbox_messages", ["recipient_id", "created_at", "uid"])
    op.create_index("ix_inbox_recipient_read", "inbox_messages", ["recipient_id", "read_at"])


def downgrade():
    op.drop_table("inbox_messages")
