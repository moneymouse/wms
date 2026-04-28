"""add goods_names table

Revision ID: 8f7e6d5c4b3a
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-28 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8f7e6d5c4b3a"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goods_names",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("lang", sa.String(length=16), nullable=False),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.Column("update_date", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("goods_names")
