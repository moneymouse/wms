"""Add append-only incremental order versions.

Revision ID: 8a9b0c1d2e3f
Revises: 7f8a9b0c1d2e
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "8a9b0c1d2e3f"
down_revision: Union[str, None] = "7f8a9b0c1d2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


json_text = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "order_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_uid", sa.String(length=32), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        sa.Column("operator_roles", json_text, nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("customer_name", sa.String(length=256), nullable=True),
        sa.Column("deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_uid", "version_no", name="uq_order_versions_uid_no"
        ),
    )
    op.create_index(
        "idx_order_versions_uid_created",
        "order_versions",
        ["order_uid", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_order_versions_deleted",
        "order_versions",
        ["deleted", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_order_versions_correlation",
        "order_versions",
        ["correlation_id"],
        unique=False,
    )
    op.create_table(
        "order_version_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_uid", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("before_data", json_text, nullable=True),
        sa.Column("after_data", json_text, nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"], ["order_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id", "sequence_no", name="uq_order_version_changes_seq"
        ),
    )
    op.create_index(
        "idx_order_version_changes_entity",
        "order_version_changes",
        ["entity_type", "entity_uid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_order_version_changes_entity", table_name="order_version_changes"
    )
    op.drop_table("order_version_changes")
    op.drop_index("idx_order_versions_correlation", table_name="order_versions")
    op.drop_index("idx_order_versions_deleted", table_name="order_versions")
    op.drop_index("idx_order_versions_uid_created", table_name="order_versions")
    op.drop_table("order_versions")
