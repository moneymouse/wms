"""add bonus items and box bonus fields

Revision ID: b6f4d8a1c123
Revises: 750b5cb844d2
Create Date: 2026-04-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6f4d8a1c123"
down_revision: Union[str, None] = "750b5cb844d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bonus_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("base_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("worker_count_rule", sa.Integer(), nullable=False),
        sa.Column("weight_min", sa.Float(), nullable=False, server_default="0"),
        sa.Column("weight_max", sa.Float(), nullable=False, server_default="999999"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("update_date", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.UniqueConstraint("label", name="uq_bonus_items_label"),
    )

    op.add_column("boxes", sa.Column("bonus_item_id", sa.Integer(), nullable=True))
    op.add_column(
        "boxes",
        sa.Column(
            "bonus_assigned", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("boxes", sa.Column("bonus_assigned_by", sa.Integer(), nullable=True))
    op.add_column(
        "boxes", sa.Column("bonus_assigned_date", sa.String(length=32), nullable=True)
    )

    op.create_foreign_key(
        "fk_boxes_bonus_item_id",
        "boxes",
        "bonus_items",
        ["bonus_item_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_boxes_bonus_assigned_by",
        "boxes",
        "users",
        ["bonus_assigned_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_boxes_bonus_assigned_by", "boxes", type_="foreignkey")
    op.drop_constraint("fk_boxes_bonus_item_id", "boxes", type_="foreignkey")

    op.drop_column("boxes", "bonus_assigned_date")
    op.drop_column("boxes", "bonus_assigned_by")
    op.drop_column("boxes", "bonus_assigned")
    op.drop_column("boxes", "bonus_item_id")

    op.drop_table("bonus_items")
