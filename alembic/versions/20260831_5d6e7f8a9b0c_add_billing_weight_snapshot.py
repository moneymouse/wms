"""Add per-package billing weight snapshot

Revision ID: 5d6e7f8a9b0c
Revises: 4c5d6e7f8a9b
Create Date: 2026-08-31 23:30:00.000000
"""

from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d6e7f8a9b0c"
down_revision: Union[str, None] = "4c5d6e7f8a9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "order_quote_versions",
        sa.Column("billing_weight_snapshot", sa.Numeric(14, 3), nullable=True),
    )

    connection = op.get_bind()
    cargos = sa.table(
        "cargos",
        sa.column("target_order_uid", sa.String(32)),
        sa.column("weight", sa.Float()),
        sa.column("archive", sa.Boolean()),
    )
    quotes = sa.table(
        "order_quote_versions",
        sa.column("id", sa.Integer()),
        sa.column("order_uid", sa.String(32)),
        sa.column("billing_weight_snapshot", sa.Numeric(14, 3)),
    )

    totals = defaultdict(lambda: Decimal("0"))
    cargo_rows = connection.execute(
        sa.select(cargos.c.target_order_uid, cargos.c.weight).where(
            cargos.c.archive == sa.false(),  # noqa: E712
            cargos.c.target_order_uid.is_not(None),
        )
    )
    for order_uid, cargo_weight in cargo_rows:
        totals[order_uid] += Decimal(str(cargo_weight or 0)).to_integral_value(
            rounding=ROUND_CEILING
        )

    quote_rows = connection.execute(sa.select(quotes.c.id, quotes.c.order_uid))
    for quote_id, order_uid in quote_rows:
        connection.execute(
            quotes.update()
            .where(quotes.c.id == quote_id)
            .values(billing_weight_snapshot=totals[order_uid])
        )

    with op.batch_alter_table("order_quote_versions") as batch_op:
        batch_op.alter_column(
            "billing_weight_snapshot",
            existing_type=sa.Numeric(14, 3),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_column("order_quote_versions", "billing_weight_snapshot")
