"""ERP quotation, receipts and receivables

Revision ID: 4c5d6e7f8a9b
Revises: 3b4c5d6e7f8a
Create Date: 2026-08-27 22:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c5d6e7f8a9b"
down_revision: Union[str, None] = "3b4c5d6e7f8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "excel_templates",
        sa.Column("requires_valid_quote", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.add_column("order_quote_versions", sa.Column("unit_price", sa.Numeric(14, 4), nullable=True))
    op.add_column("order_quote_versions", sa.Column("surcharge", sa.Numeric(14, 2), nullable=True))
    op.add_column("order_quote_versions", sa.Column("weight_snapshot", sa.Numeric(14, 3), nullable=True))
    op.add_column("order_quote_versions", sa.Column("receivable_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("order_quote_versions", sa.Column("effective_date", sa.String(32), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE order_quote_versions
            SET unit_price = COALESCE(quoted_price, 0),
                surcharge = 0,
                weight_snapshot = COALESCE((
                    SELECT ROUND(SUM(COALESCE(c.weight, 0)), 3)
                    FROM cargos c
                    WHERE c.target_order_uid = order_quote_versions.order_uid AND c.archive = 0
                ), 0),
                effective_date = CASE
                    WHEN status IN ('adopted', 'approved') THEN COALESCE(review_date, create_date)
                    ELSE NULL
                END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE order_quote_versions
            SET receivable_amount = ROUND(
                COALESCE(weight_snapshot, 0) * COALESCE(unit_price, 0) + COALESCE(surcharge, 0),
                2
            )
            """
        )
    )
    with op.batch_alter_table("order_quote_versions") as batch_op:
        for column_name, column_type in (
            ("unit_price", sa.Numeric(14, 4)),
            ("surcharge", sa.Numeric(14, 2)),
            ("weight_snapshot", sa.Numeric(14, 3)),
            ("receivable_amount", sa.Numeric(14, 2)),
        ):
            batch_op.alter_column(column_name, existing_type=column_type, nullable=False)

    op.create_index("idx_order_quotes_effective_date", "order_quote_versions", ["effective_date"], unique=False)
    op.create_index("idx_order_quotes_quoter_effective", "order_quote_versions", ["quoter_id", "effective_date"], unique=False)

    op.create_table(
        "payment_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_no", sa.String(32), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(256), nullable=False),
        sa.Column("receipt_date", sa.String(10), nullable=False),
        sa.Column("payment_method", sa.String(32), nullable=False),
        sa.Column("remark", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("creator_name", sa.String(128), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_name", sa.String(128), nullable=True),
        sa.Column("review_remark", sa.String(512), nullable=True),
        sa.Column("review_date", sa.String(32), nullable=True),
        sa.Column("create_date", sa.String(32), nullable=False),
        sa.Column("update_date", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_no"),
    )
    op.create_index("idx_payment_receipts_status_date", "payment_receipts", ["status", "receipt_date"], unique=False)
    op.create_index("idx_payment_receipts_customer", "payment_receipts", ["customer_id"], unique=False)
    op.create_index("idx_payment_receipts_creator", "payment_receipts", ["creator_id"], unique=False)

    op.create_table(
        "payment_receipt_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("order_uid", sa.String(32), nullable=False),
        sa.Column("order_id", sa.String(128), nullable=False),
        sa.Column("receivable_snapshot", sa.Numeric(14, 2), nullable=False),
        sa.Column("received_before", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("remaining_after", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["payment_receipts.id"]),
        sa.ForeignKeyConstraint(["order_uid"], ["orders.uid"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", "order_uid", name="uq_receipt_order"),
    )
    op.create_index("idx_receipt_items_order", "payment_receipt_items", ["order_uid"], unique=False)

    op.create_table(
        "sales_followup_bonus_rates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rate_per_kg", sa.Numeric(14, 4), nullable=False),
        sa.Column("effective_from", sa.String(10), nullable=False),
        sa.Column("remark", sa.String(512), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("creator_name", sa.String(128), nullable=True),
        sa.Column("create_date", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("effective_from"),
    )
    op.create_index("idx_sales_bonus_rate_effective", "sales_followup_bonus_rates", ["effective_from"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_sales_bonus_rate_effective", table_name="sales_followup_bonus_rates")
    op.drop_table("sales_followup_bonus_rates")
    op.drop_index("idx_receipt_items_order", table_name="payment_receipt_items")
    op.drop_table("payment_receipt_items")
    op.drop_index("idx_payment_receipts_creator", table_name="payment_receipts")
    op.drop_index("idx_payment_receipts_customer", table_name="payment_receipts")
    op.drop_index("idx_payment_receipts_status_date", table_name="payment_receipts")
    op.drop_table("payment_receipts")
    op.drop_index("idx_order_quotes_quoter_effective", table_name="order_quote_versions")
    op.drop_index("idx_order_quotes_effective_date", table_name="order_quote_versions")
    op.drop_column("order_quote_versions", "effective_date")
    op.drop_column("order_quote_versions", "receivable_amount")
    op.drop_column("order_quote_versions", "weight_snapshot")
    op.drop_column("order_quote_versions", "surcharge")
    op.drop_column("order_quote_versions", "unit_price")
    op.drop_column("excel_templates", "requires_valid_quote")
