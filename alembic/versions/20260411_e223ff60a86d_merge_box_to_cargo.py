"""merge box to cargo

Revision ID: e223ff60a86d
Revises: c3a8f1e2d9a4
Create Date: 2026-04-11 12:22:38.902036
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "e223ff60a86d"
down_revision: Union[str, None] = "c3a8f1e2d9a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND index_name = :index_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).first()
    return row is not None


def _fk_exists(table_name: str, fk_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND constraint_type = 'FOREIGN KEY'
              AND constraint_name = :fk_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "fk_name": fk_name},
    ).first()
    return row is not None


def _drop_box_workers_box_uid_fk() -> None:
    """Drop existing FK on box_workers.box_uid regardless of generated name."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'box_workers'
              AND COLUMN_NAME = 'box_uid'
              AND REFERENCED_TABLE_NAME IS NOT NULL
            """
        )
    ).fetchall()

    for row in rows:
        op.execute(sa.text(f"ALTER TABLE box_workers DROP FOREIGN KEY `{row[0]}`"))


def _create_boxes_table_if_missing() -> None:
    if _table_exists("boxes"):
        return

    op.create_table(
        "boxes",
        sa.Column("uid", mysql.VARCHAR(length=32), nullable=False),
        sa.Column("packing_list_uid", mysql.VARCHAR(length=32), nullable=False),
        sa.Column("item_name", mysql.VARCHAR(length=256), nullable=True),
        sa.Column("weight", mysql.FLOAT(), nullable=True),
        sa.Column("target_order_uid", mysql.VARCHAR(length=32), nullable=True),
        sa.Column("status", mysql.VARCHAR(length=32), nullable=True),
        sa.Column("create_date", mysql.VARCHAR(length=32), nullable=True),
        sa.Column("update_date", mysql.VARCHAR(length=32), nullable=True),
        sa.Column(
            "archive",
            mysql.TINYINT(display_width=1),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column("box_number", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("piece_count", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("bonus_item_id", mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column(
            "bonus_assigned",
            mysql.TINYINT(display_width=1),
            server_default=sa.text("'0'"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "bonus_assigned_by", mysql.INTEGER(), autoincrement=False, nullable=True
        ),
        sa.Column("bonus_assigned_date", mysql.VARCHAR(length=32), nullable=True),
        sa.Column("item_details", mysql.TEXT(), nullable=True),
        sa.Column("remark", mysql.VARCHAR(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["bonus_assigned_by"], ["users.id"], name=op.f("fk_boxes_bonus_assigned_by")
        ),
        sa.ForeignKeyConstraint(
            ["bonus_item_id"], ["bonus_items.id"], name=op.f("fk_boxes_bonus_item_id")
        ),
        sa.ForeignKeyConstraint(
            ["packing_list_uid"], ["packing_lists.uid"], name=op.f("boxes_ibfk_1")
        ),
        sa.ForeignKeyConstraint(
            ["target_order_uid"], ["orders.uid"], name=op.f("boxes_ibfk_2")
        ),
        sa.PrimaryKeyConstraint("uid"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )


def upgrade() -> None:
    # Ensure unified box fields exist on cargos.
    if not _column_exists("cargos", "packing_list_uid"):
        op.add_column(
            "cargos", sa.Column("packing_list_uid", sa.String(length=32), nullable=True)
        )
    if not _column_exists("cargos", "item_name"):
        op.add_column(
            "cargos", sa.Column("item_name", sa.String(length=256), nullable=True)
        )
    if not _column_exists("cargos", "item_details"):
        op.add_column("cargos", sa.Column("item_details", sa.Text(), nullable=True))
    if not _column_exists("cargos", "remark"):
        op.add_column(
            "cargos", sa.Column("remark", sa.String(length=512), nullable=True)
        )
    if not _column_exists("cargos", "box_number"):
        op.add_column("cargos", sa.Column("box_number", sa.Integer(), nullable=True))
    if not _column_exists("cargos", "piece_count"):
        op.add_column("cargos", sa.Column("piece_count", sa.Integer(), nullable=True))
    if not _column_exists("cargos", "bonus_item_id"):
        op.add_column("cargos", sa.Column("bonus_item_id", sa.Integer(), nullable=True))
    if not _column_exists("cargos", "bonus_assigned"):
        op.add_column(
            "cargos",
            sa.Column(
                "bonus_assigned", sa.Boolean(), nullable=True, server_default=sa.false()
            ),
        )
    if not _column_exists("cargos", "bonus_assigned_by"):
        op.add_column(
            "cargos", sa.Column("bonus_assigned_by", sa.Integer(), nullable=True)
        )
    if not _column_exists("cargos", "bonus_assigned_date"):
        op.add_column(
            "cargos",
            sa.Column("bonus_assigned_date", sa.String(length=32), nullable=True),
        )
    if not _column_exists("cargos", "box_status"):
        op.add_column(
            "cargos",
            sa.Column(
                "box_status",
                sa.String(length=32),
                nullable=True,
                server_default="pending",
            ),
        )

    # Add indexes and foreign keys for merged fields.
    if not _index_exists("cargos", "idx_cargos_packing_list_uid"):
        op.create_index(
            "idx_cargos_packing_list_uid", "cargos", ["packing_list_uid"], unique=False
        )
    if not _index_exists("cargos", "idx_cargos_box_status"):
        op.create_index("idx_cargos_box_status", "cargos", ["box_status"], unique=False)
    if not _index_exists("cargos", "uq_cargos_packing_box_number"):
        op.create_index(
            "uq_cargos_packing_box_number",
            "cargos",
            ["packing_list_uid", "box_number"],
            unique=True,
        )

    if not _fk_exists("cargos", "fk_cargos_packing_list_uid"):
        op.create_foreign_key(
            "fk_cargos_packing_list_uid",
            "cargos",
            "packing_lists",
            ["packing_list_uid"],
            ["uid"],
        )
    if not _fk_exists("cargos", "fk_cargos_bonus_item_id"):
        op.create_foreign_key(
            "fk_cargos_bonus_item_id",
            "cargos",
            "bonus_items",
            ["bonus_item_id"],
            ["id"],
        )
    if not _fk_exists("cargos", "fk_cargos_bonus_assigned_by"):
        op.create_foreign_key(
            "fk_cargos_bonus_assigned_by",
            "cargos",
            "users",
            ["bonus_assigned_by"],
            ["id"],
        )

    # Migrate legacy boxes rows into cargos (if boxes still exists).
    if _table_exists("boxes"):
        op.execute(
            sa.text(
                """
                INSERT INTO cargos (
                    uid, origin_id, transfer_id, tag, count, weight,
                    real_en_name, price, status, archive, date, waybill_id,
                    target_order_uid, packing_list_uid, item_name, item_details,
                    remark, box_number, piece_count, bonus_item_id, bonus_assigned,
                    bonus_assigned_by, bonus_assigned_date, box_status, create_date, update_date
                )
                SELECT
                    b.uid,
                    CONCAT('BOX-', b.uid),
                    '',
                    CASE
                        WHEN pl.list_number IS NOT NULL AND b.box_number IS NOT NULL THEN CONCAT(pl.list_number, '_', b.box_number)
                        WHEN pl.list_number IS NOT NULL THEN pl.list_number
                        WHEN b.box_number IS NOT NULL THEN CONCAT('BOX_', b.box_number)
                        ELSE CONCAT('BOX_', b.uid)
                    END,
                    COALESCE(b.piece_count, 0),
                    COALESCE(b.weight, 0),
                    COALESCE(b.item_name, ''),
                    0,
                    0,
                    COALESCE(b.archive, 0),
                    NULL,
                    '',
                    b.target_order_uid,
                    b.packing_list_uid,
                    b.item_name,
                    b.item_details,
                    b.remark,
                    b.box_number,
                    b.piece_count,
                    b.bonus_item_id,
                    b.bonus_assigned,
                    b.bonus_assigned_by,
                    b.bonus_assigned_date,
                    COALESCE(b.status, 'pending'),
                    b.create_date,
                    b.update_date
                FROM boxes b
                LEFT JOIN packing_lists pl ON pl.uid = b.packing_list_uid
                LEFT JOIN cargos c ON c.uid = b.uid
                WHERE c.uid IS NULL
                """
            )
        )

    # Repoint box_workers FK and then drop boxes.
    _drop_box_workers_box_uid_fk()
    if not _fk_exists("box_workers", "fk_box_workers_box_uid_cargos"):
        op.create_foreign_key(
            "fk_box_workers_box_uid_cargos",
            "box_workers",
            "cargos",
            ["box_uid"],
            ["uid"],
        )

    if _table_exists("boxes"):
        op.drop_table("boxes")


def downgrade() -> None:
    # Best-effort downgrade: recreate boxes, copy data back, and repoint FK.
    _create_boxes_table_if_missing()

    op.execute(
        sa.text(
            """
            INSERT INTO boxes (
                uid, packing_list_uid, item_name, weight, target_order_uid, status,
                create_date, update_date, archive, box_number, piece_count,
                bonus_item_id, bonus_assigned, bonus_assigned_by, bonus_assigned_date,
                item_details, remark
            )
            SELECT
                c.uid,
                c.packing_list_uid,
                c.item_name,
                c.weight,
                c.target_order_uid,
                c.box_status,
                c.create_date,
                c.update_date,
                c.archive,
                c.box_number,
                COALESCE(c.piece_count, c.count),
                c.bonus_item_id,
                COALESCE(c.bonus_assigned, 0),
                c.bonus_assigned_by,
                c.bonus_assigned_date,
                c.item_details,
                c.remark
            FROM cargos c
            LEFT JOIN boxes b ON b.uid = c.uid
            WHERE c.packing_list_uid IS NOT NULL AND b.uid IS NULL
            """
        )
    )

    _drop_box_workers_box_uid_fk()
    if not _fk_exists("box_workers", "box_workers_ibfk_1"):
        op.create_foreign_key(
            "box_workers_ibfk_1", "box_workers", "boxes", ["box_uid"], ["uid"]
        )
