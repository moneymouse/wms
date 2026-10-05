"""Append-only outbound registration facts (no historical backfill).

Revision ID: e05b6c7d8e9f
Revises: df4a5b6c7d8e
"""
from alembic import op
import sqlalchemy as sa

revision = "e05b6c7d8e9f"
down_revision = "df4a5b6c7d8e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cargo_outbound_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Historical identifiers survive existing delete/archive behavior.
        sa.Column("cargo_uid", sa.String(32), nullable=False),
        sa.Column("order_uid", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.String(32), nullable=True),
        sa.Column("recorded_at", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(128), nullable=True),
    )
    op.create_index("ix_cargo_outbound_records_cargo_uid", "cargo_outbound_records", ["cargo_uid"])


def downgrade():
    op.drop_index("ix_cargo_outbound_records_cargo_uid", table_name="cargo_outbound_records")
    op.drop_table("cargo_outbound_records")
