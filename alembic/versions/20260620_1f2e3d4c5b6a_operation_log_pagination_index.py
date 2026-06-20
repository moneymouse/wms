"""operation log pagination index

Revision ID: 1f2e3d4c5b6a
Revises: d4e5f6a7b8c9
Create Date: 2026-06-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_operation_logs_log_date_id",
        "operation_logs",
        ["log_date", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_operation_logs_log_date_id", table_name="operation_logs")
