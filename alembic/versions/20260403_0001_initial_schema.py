"""Initial schema - all tables

Revision ID: 0001
Revises:
Create Date: 2026-04-03

This migration creates all initial tables matching the existing schema.sql.
For existing databases, use `alembic stamp 0001` to mark as current without running.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table first (referenced by orders)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("password", sa.String(512), nullable=False),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("remark", sa.String(256), nullable=True),
        sa.Column("create_date", sa.String(32), nullable=True),
        sa.Column("update_date", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index("idx_users_status", "users", ["status"])

    # Create customers table (referenced by receivers)
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("wechat", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_customers_name"),
    )

    # Create orders table
    op.create_table(
        "orders",
        sa.Column("uid", sa.String(32), nullable=False),
        sa.Column("order_id", sa.String(128), nullable=True),
        sa.Column("customer_name", sa.String(256), nullable=True),
        sa.Column("transportation", sa.String(128), nullable=True),
        sa.Column("receiver", sa.String(256), nullable=True),
        sa.Column("receiver_phone", sa.String(64), nullable=True),
        sa.Column("mail", sa.String(256), nullable=True),
        sa.Column("country", sa.String(128), nullable=True),
        sa.Column("province", sa.String(128), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("en_name", sa.String(256), nullable=True),
        sa.Column("cn_name", sa.String(256), nullable=True),
        sa.Column("total_weight", sa.Float(), nullable=True),
        sa.Column("cargo_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("archive", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("post_code", sa.String(64), nullable=True),
        sa.Column("zip_code", sa.String(64), nullable=True),
        sa.Column("order_date", sa.String(32), nullable=True),
        sa.Column("tag_all", sa.String(256), nullable=True),
        sa.Column("create_date", sa.String(32), nullable=True),
        sa.Column("update_date", sa.String(32), nullable=True),
        sa.Column("salesman_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("uid"),
        sa.ForeignKeyConstraint(
            ["salesman_id"],
            ["users.id"],
            name="fk_order_salesman",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
    )

    # Create cargos table
    op.create_table(
        "cargos",
        sa.Column("uid", sa.String(32), nullable=False),
        sa.Column("origin_id", sa.String(128), nullable=True),
        sa.Column("transfer_id", sa.String(256), server_default="", nullable=True),
        sa.Column("tag", sa.String(128), server_default="init", nullable=True),
        sa.Column("count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("weight", sa.Float(), server_default="0", nullable=True),
        sa.Column("real_en_name", sa.String(256), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("status", sa.Integer(), server_default="0", nullable=True),
        sa.Column("archive", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("date", sa.String(32), nullable=True),
        sa.Column("waybill_id", sa.String(256), server_default="", nullable=True),
        sa.Column("target_order_uid", sa.String(32), nullable=True),
        sa.Column("create_date", sa.String(32), nullable=True),
        sa.Column("update_date", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("uid"),
        sa.ForeignKeyConstraint(
            ["target_order_uid"],
            ["orders.uid"],
            name="fk_cargo_order",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
    )
    op.create_index("idx_cargos_order", "cargos", ["target_order_uid"])
    op.create_index("idx_cargos_transfer", "cargos", ["transfer_id"])
    op.create_index("idx_cargos_waybill", "cargos", ["waybill_id"])

    # Create receivers table
    op.create_table(
        "receivers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_name", sa.String(256), nullable=False),
        sa.Column("receiver", sa.String(256), nullable=True),
        sa.Column("receiver_phone", sa.String(64), nullable=True),
        sa.Column("mail", sa.String(256), nullable=True),
        sa.Column("country", sa.String(128), nullable=True),
        sa.Column("province", sa.String(128), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("zip_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["customer_name"],
            ["customers.name"],
            name="fk_receiver_customer",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
    )
    op.create_index("idx_receivers_customer", "receivers", ["customer_name"])

    # Create operation_logs table
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("pc_name", sa.String(256), nullable=True),
        sa.Column("desc", sa.String(512), nullable=True),
        sa.Column("kwargs", sa.Text(), nullable=True),
        sa.Column("json_body", sa.Text(), nullable=True),
        sa.Column("method", sa.String(16), nullable=True),
        sa.Column("log_date", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_logs_date", "operation_logs", ["log_date"])


def downgrade() -> None:
    op.drop_table("operation_logs")
    op.drop_table("receivers")
    op.drop_table("cargos")
    op.drop_table("orders")
    op.drop_table("customers")
    op.drop_table("users")
