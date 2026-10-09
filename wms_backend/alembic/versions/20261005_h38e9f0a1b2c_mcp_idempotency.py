"""Durable MCP mutation idempotency receipts.

Revision ID: h38e9f0a1b2c
Revises: g27d8e9f0a1b
"""
from alembic import op
import sqlalchemy as sa

revision = "h38e9f0a1b2c"
down_revision = "g27d8e9f0a1b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_id_hash", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "client_id_hash", "tool_name", "key_hash",
            name="uq_mcp_idempotency_identity",
        ),
    )


def downgrade():
    op.drop_table("mcp_idempotency")
