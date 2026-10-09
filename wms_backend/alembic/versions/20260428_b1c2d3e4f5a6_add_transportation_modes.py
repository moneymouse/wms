"""add transportation_modes table

Revision ID: b1c2d3e4f5a6
Revises: 9a8b7c6d5e4f
Create Date: 2026-04-28 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "9a8b7c6d5e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transportation_modes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("channel_group", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("archive", sa.Boolean(), default=False),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.Column("update_date", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # 迁移旧的静态运输方式数据
    now = "2026-04-28 15:00"
    old_transportations = [
        ("TC", "TC"),
        ("英国皇邮特快", "TC"),
        ("欧盟DPD特快", "TC"),
        ("欧盟DHL特快W", "TC"),
        ("欧盟DPD敏感", "TC"),
        ("欧盟DHL敏感W", "TC"),
        ("JF", "JF"),
        ("七国小包专线", "JF"),
        ("欧洲DPD-KX", "JF"),
        ("W-欧洲DHL小包(KX)", "JF"),
        ("W-欧洲DHL小包", "JF"),
        ("欧洲DPD-M", "JF"),
        ("欧洲DPD-带电", "JF"),
        ("YX", "YX"),
        ("德国DPD快线", "YX"),
        ("德国DHL快线", "YX"),
    ]

    transportation_modes_table = sa.table(
        "transportation_modes",
        sa.column("name", sa.String(length=128)),
        sa.column("channel_group", sa.String(length=64)),
        sa.column("cost", sa.Float()),
        sa.column("min_price", sa.Float()),
        sa.column("archive", sa.Boolean()),
        sa.column("create_date", sa.String(length=32)),
        sa.column("update_date", sa.String(length=32)),
    )

    op.bulk_insert(
        transportation_modes_table,
        [
            {
                "name": name,
                "channel_group": group,
                "cost": 0,
                "min_price": 0,
                "archive": False,
                "create_date": now,
                "update_date": now,
            }
            for name, group in old_transportations
        ],
    )


def downgrade() -> None:
    op.drop_table("transportation_modes")
