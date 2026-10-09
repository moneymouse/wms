"""add box remark and item details

Revision ID: c3a8f1e2d9a4
Revises: b6f4d8a1c123
Create Date: 2026-04-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3a8f1e2d9a4"
down_revision: Union[str, None] = "b6f4d8a1c123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("boxes", sa.Column("item_details", sa.Text(), nullable=True))
    op.add_column("boxes", sa.Column("remark", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("boxes", "remark")
    op.drop_column("boxes", "item_details")
