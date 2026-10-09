"""migrate receivers to customer_id

Revision ID: d4e5f6a7b8c9
Revises: c7d8e9f0a1b2
Create Date: 2026-05-08 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_foreign_keys_for_column(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(table_name):
        constrained_columns = fk.get("constrained_columns") or []
        if constrained_columns == [column_name] and fk.get("name"):
            op.drop_constraint(fk["name"], table_name, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("receivers", sa.Column("customer_id", sa.Integer(), nullable=True))
    bind.execute(
        sa.text(
            """
            UPDATE receivers r
            JOIN customers c ON r.customer_name = c.name
            SET r.customer_id = c.id
            """
        )
    )

    missing_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM receivers WHERE customer_id IS NULL")
    ).scalar()
    if missing_count:
        raise RuntimeError(
            f"Cannot migrate receivers.customer_name: {missing_count} rows do not match customers.name"
        )

    _drop_foreign_keys_for_column("receivers", "customer_name")
    op.alter_column(
        "receivers",
        "customer_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "idx_receivers_customer_id", "receivers", ["customer_id"], unique=False
    )
    op.create_foreign_key(
        "fk_receivers_customer_id_customers",
        "receivers",
        "customers",
        ["customer_id"],
        ["id"],
    )
    op.drop_column("receivers", "customer_name")


def downgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "receivers", sa.Column("customer_name", sa.String(length=256), nullable=True)
    )
    bind.execute(
        sa.text(
            """
            UPDATE receivers r
            JOIN customers c ON r.customer_id = c.id
            SET r.customer_name = c.name
            """
        )
    )

    missing_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM receivers WHERE customer_name IS NULL")
    ).scalar()
    if missing_count:
        raise RuntimeError(
            f"Cannot downgrade receivers.customer_id: {missing_count} rows do not match customers.id"
        )

    _drop_foreign_keys_for_column("receivers", "customer_id")
    op.drop_index("idx_receivers_customer_id", table_name="receivers")
    op.alter_column(
        "receivers",
        "customer_name",
        existing_type=sa.String(length=256),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_receivers_customer_name_customers",
        "receivers",
        "customers",
        ["customer_name"],
        ["name"],
    )
    op.drop_column("receivers", "customer_id")
