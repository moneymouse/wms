import os
import time

from Auth import hash_password, check_password, create_jwt, normalize_roles
from data.user import user_model, ROLES, role_model
from data.user.User import UserTable, STATUS_APPROVED
from data.database import SessionFactory


def _primary_role(roles: list[str]) -> str | None:
    return roles[0] if roles else None


def register_user(phone: str, name: str, password: str):
    """
    注册新用户，状态默认为 pending。
    返回 (user_dict, error_msg)，成功时 error_msg 为 None。
    """
    if not phone or not name or not password:
        return None, "手机号、姓名和密码不能为空"
    if user_model.get_by_phone(phone):
        return None, "该手机号已注册"
    user = user_model.create(
        phone=phone, name=name, password_hash=hash_password(password)
    )
    return user, None


def authenticate_user(phone: str, password: str):
    """Validate existing WMS credentials without issuing a transport-specific token."""
    if not phone or not password:
        return None, "手机号和密码不能为空"

    user = user_model.get_by_phone(phone, include_password=True)
    if user is None or not check_password(password, user["password"]):
        return None, "手机号或密码错误"

    if user["status"] == "pending":
        return None, "账号尚未通过审核"
    if user["status"] == "rejected":
        remark = user.get("remark") or ""
        return None, f"账号审核未通过：{remark}"
    if user["status"] != STATUS_APPROVED:
        return None, "账号不可用"

    roles = normalize_roles(user.get("roles")) or normalize_roles(user.get("role"))
    primary_role = _primary_role(roles)

    safe_user = {k: user[k] for k in ("id", "phone", "name")}
    safe_user["role"] = primary_role
    safe_user["roles"] = roles
    return safe_user, None


def login_user(phone: str, password: str):
    """Validate WMS credentials and preserve the existing REST JWT response."""
    user, err = authenticate_user(phone, password)
    if err:
        return None, None, err
    token = create_jwt(
        {
            "user_id": user["id"],
            "phone": user["phone"],
            "name": user["name"],
            "role": user["role"],
            "roles": user["roles"],
        }
    )
    return token, user, None


def approve_user(user_id: int, role, operator_roles):
    """
    审核通过并分配角色。店长不可分配 admin 角色。
    返回 (updated_user, error_msg)。
    """
    roles = normalize_roles(role)
    if not roles:
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'
    if any(r not in ROLES for r in roles):
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'

    normalized_operator_roles = set(normalize_roles(operator_roles))
    if user_model.get_by_id(user_id) is None:
        return None, "用户不存在"
    if (
        "store_manager" in normalized_operator_roles
        and "admin" not in normalized_operator_roles
        and "admin" in roles
    ):
        return None, "店长无法分配管理员角色"

    role_objects = role_model.get_by_names(roles)
    if len(role_objects) != len(roles):
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'

    updated = user_model.approve(user_id=user_id, role_objects=role_objects)
    return updated, None


def reject_user(user_id: int, remark: str = None):
    """
    审核拒绝。
    返回 (updated_user, error_msg)。
    """
    if user_model.get_by_id(user_id) is None:
        return None, "用户不存在"
    updated = user_model.reject(user_id=user_id, remark=remark)
    return updated, None


def change_user_role(user_id: int, role):
    """
    直接修改已有用户的角色（管理员操作）。
    role 为 None 或空字符串时表示删除角色。
    返回 (updated_user, error_msg)。
    """
    roles = normalize_roles(role)
    if role is not None and roles and any(r not in ROLES for r in roles):
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'
    if role not in (None, "") and not roles:
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'
    if user_model.get_by_id(user_id) is None:
        return None, "用户不存在"

    role_objects = role_model.get_by_names(roles) if roles else []
    updated = user_model.update_role(user_id=user_id, role_objects=role_objects)
    return updated, None


def delete_user(user_id: int):
    """
    硬删除用户（管理员操作）。
    返回 (deleted_user, error_msg)。
    """
    existing = user_model.get_by_id(user_id)
    if existing is None:
        return None, "用户不存在"

    user_model.delete(user_id)
    return existing, None


def init_admin_user():
    """
    Initialize admin user from environment variables on first startup.
    This is typically used in Docker/container deployments.

    Environment variables:
      - ADMIN_PHONE: Admin user phone/username (required to create admin)
      - ADMIN_PASSWORD: Admin user password (required to create admin)
      - ADMIN_NAME: Admin user display name (optional, defaults to "Admin")

    Returns True if admin was created, False if skipped (already exists or env vars missing).
    """
    admin_phone = os.environ.get("ADMIN_PHONE")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_name = os.environ.get("ADMIN_NAME", "Admin")

    if not admin_phone or not admin_password:
        return False

    existing = user_model.get_by_phone(admin_phone)
    if existing:
        return False

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        from data.user.Role import RoleTable

        admin_role = session.query(RoleTable).filter_by(name="admin").first()
        if not admin_role:
            admin_role = RoleTable(name="admin", label="管理员")
            session.add(admin_role)
            session.flush()

        user = UserTable(
            phone=admin_phone,
            name=admin_name,
            password=hash_password(admin_password),
            status=STATUS_APPROVED,
            create_date=now,
            update_date=now,
        )
        user.roles = [admin_role]
        session.add(user)
        session.commit()

    print(f"[INIT] Created admin user: {admin_phone}")
    return True
