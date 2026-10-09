"""add roles table and user_roles association

Revision ID: 1a2b3c4d5e6f
Revises: a9c08d614478
Create Date: 2026-04-28 10:00:00.000000
"""

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, String, Integer

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "a9c08d614478"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES = [
    ("admin", "管理员"),
    ("store_manager", "店长"),
    ("salesperson", "业务员"),
    ("clerk", "文员"),
    ("finance", "财务"),
    ("worker", "操作人员"),
]


def _normalize_roles(role_value):
    if role_value is None:
        return []
    if isinstance(role_value, str):
        text = role_value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return _normalize_roles(parsed)
            except Exception:
                pass
        roles = [part.strip() for part in text.split(",") if part.strip()]
    elif isinstance(role_value, (list, tuple, set)):
        roles = []
        for item in role_value:
            roles.extend(_normalize_roles(item))
    else:
        return []
    deduped = []
    seen = set()
    for role in roles:
        if role not in seen:
            seen.add(role)
            deduped.append(role)
    return deduped


def upgrade() -> None:
    # 1. Create roles table
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # 2. Insert default roles
    roles_table = table("roles", column("name", String), column("label", String))
    op.bulk_insert(roles_table, [{"name": name, "label": label} for name, label in ROLES])

    # 3. Create user_roles association table
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # 4. Migrate existing user roles from users.role string to user_roles
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, role FROM users WHERE role IS NOT NULL AND role != ''")).fetchall()

    if users:
        # Build name -> id mapping
        role_rows = conn.execute(sa.text("SELECT id, name FROM roles")).fetchall()
        name_to_id = {name: rid for rid, name in role_rows}

        inserts = []
        for user_id, role_str in users:
            role_names = _normalize_roles(role_str)
            for rname in role_names:
                rid = name_to_id.get(rname)
                if rid is not None:
                    inserts.append({"user_id": user_id, "role_id": rid})

        if inserts:
            user_roles_table = table(
                "user_roles",
                column("user_id", Integer),
                column("role_id", Integer),
            )
            op.bulk_insert(user_roles_table, inserts)

    # 5. Drop the old users.role column
    op.drop_column("users", "role")


def downgrade() -> None:
    # 1. Add back users.role column
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=True))

    # 2. Migrate data back from user_roles to users.role
    conn = op.get_bind()
    user_roles = conn.execute(
        sa.text(
            """
            SELECT ur.user_id, GROUP_CONCAT(r.name ORDER BY r.name SEPARATOR ',') as role_names
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            GROUP BY ur.user_id
            """
        )
    ).fetchall()

    for user_id, role_names in user_roles:
        conn.execute(
            sa.text("UPDATE users SET role = :role WHERE id = :uid"),
            {"role": role_names, "uid": user_id},
        )

    # 3. Drop user_roles and roles
    op.drop_table("user_roles")
    op.drop_table("roles")
