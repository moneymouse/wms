"""finance audit quote versions

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-05-05 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transportation_cost_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transportation_mode_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("channel_group", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("change_type", sa.String(length=32), nullable=False, server_default="update"),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transportation_mode_id"], ["transportation_modes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_transportation_cost_versions_mode_version",
        "transportation_cost_versions",
        ["transportation_mode_id", "version_no"],
        unique=False,
    )

    op.create_table(
        "order_quote_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_uid", sa.String(length=32), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("transportation_mode_id", sa.Integer(), nullable=True),
        sa.Column("transportation_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("channel_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("quoted_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="adopted"),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quote_remark", sa.String(length=512), nullable=True),
        sa.Column("review_remark", sa.String(length=512), nullable=True),
        sa.Column("quoter_id", sa.Integer(), nullable=True),
        sa.Column("quoter_name", sa.String(length=128), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_name", sa.String(length=128), nullable=True),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.Column("review_date", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["order_uid"], ["orders.uid"]),
        sa.ForeignKeyConstraint(["quoter_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transportation_mode_id"], ["transportation_modes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_order_quote_versions_order_version",
        "order_quote_versions",
        ["order_uid", "version_no"],
        unique=False,
    )
    op.create_index(
        "idx_order_quote_versions_order_final",
        "order_quote_versions",
        ["order_uid", "is_final"],
        unique=False,
    )
    op.create_index("idx_order_quote_versions_status", "order_quote_versions", ["status"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=True),
        sa.Column("operator_role", sa.String(length=128), nullable=True),
        sa.Column("before_data", sa.Text(), nullable=True),
        sa.Column("after_data", sa.Text(), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_logs_event_type", "audit_logs", ["event_type"], unique=False)
    op.create_index("idx_audit_logs_create_date", "audit_logs", ["create_date"], unique=False)
    op.create_index("idx_orders_archive_create_date", "orders", ["archive", "create_date"], unique=False)
    op.create_index("idx_orders_archive_order_date", "orders", ["archive", "order_date"], unique=False)
    op.create_index("idx_orders_order_id", "orders", ["order_id"], unique=False)
    op.create_index("idx_orders_customer_name", "orders", ["customer_name"], unique=False)
    op.create_index("idx_cargos_target_order_uid", "cargos", ["target_order_uid"], unique=False)
    op.create_index("idx_cargos_transfer_id", "cargos", ["transfer_id"], unique=False)
    op.create_index("idx_cargos_waybill_id", "cargos", ["waybill_id"], unique=False)
    op.create_index("idx_packing_lists_archive_create_date", "packing_lists", ["archive", "create_date"], unique=False)
    op.create_index("idx_packing_lists_archive_status", "packing_lists", ["archive", "status"], unique=False)
    op.create_index("idx_packing_lists_customer_id", "packing_lists", ["customer_id"], unique=False)
    op.create_index("idx_packing_lists_list_number", "packing_lists", ["list_number"], unique=False)
    op.create_index("idx_cargos_packing_list_status", "cargos", ["packing_list_uid", "archive", "status"], unique=False)
    op.create_table(
        "box_cost_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("box_uid", sa.String(length=32), nullable=False),
        sa.Column("packing_list_uid", sa.String(length=32), nullable=True),
        sa.Column("order_uid", sa.String(length=32), nullable=True),
        sa.Column("transportation_mode_id", sa.Integer(), nullable=True),
        sa.Column("transportation_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("waybill_id", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["box_uid"], ["cargos.uid"]),
        sa.ForeignKeyConstraint(["packing_list_uid"], ["packing_lists.uid"]),
        sa.ForeignKeyConstraint(["order_uid"], ["orders.uid"]),
        sa.ForeignKeyConstraint(["transportation_mode_id"], ["transportation_modes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_box_cost_records_box_uid", "box_cost_records", ["box_uid"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_audit_logs_create_date", table_name="audit_logs")
    op.drop_index("idx_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("idx_cargos_waybill_id", table_name="cargos")
    op.drop_index("idx_box_cost_records_box_uid", table_name="box_cost_records")
    op.drop_table("box_cost_records")
    op.drop_index("idx_cargos_packing_list_status", table_name="cargos")
    op.drop_index("idx_packing_lists_list_number", table_name="packing_lists")
    op.drop_index("idx_packing_lists_customer_id", table_name="packing_lists")
    op.drop_index("idx_packing_lists_archive_status", table_name="packing_lists")
    op.drop_index("idx_packing_lists_archive_create_date", table_name="packing_lists")
    op.drop_index("idx_cargos_transfer_id", table_name="cargos")
    op.drop_index("idx_cargos_target_order_uid", table_name="cargos")
    op.drop_index("idx_orders_customer_name", table_name="orders")
    op.drop_index("idx_orders_order_id", table_name="orders")
    op.drop_index("idx_orders_archive_order_date", table_name="orders")
    op.drop_index("idx_orders_archive_create_date", table_name="orders")
    op.drop_table("audit_logs")
    op.drop_index("idx_order_quote_versions_status", table_name="order_quote_versions")
    op.drop_index("idx_order_quote_versions_order_final", table_name="order_quote_versions")
    op.drop_index("idx_order_quote_versions_order_version", table_name="order_quote_versions")
    op.drop_table("order_quote_versions")
    op.drop_index(
        "idx_transportation_cost_versions_mode_version",
        table_name="transportation_cost_versions",
    )
    op.drop_table("transportation_cost_versions")
