"""Index currently open order revision windows for the admin list.

Revision ID: 9b0c1d2e3f4a
Revises: 8a9b0c1d2e3f
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "9b0c1d2e3f4a"
down_revision: Union[str, None] = "8a9b0c1d2e3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_order_receipt_revisions_opened",
        "order_receipt_revisions",
        ["status", "opened_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_order_receipt_revisions_opened",
        table_name="order_receipt_revisions",
    )
