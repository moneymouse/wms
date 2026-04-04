import os
import time

from Auth import hash_password, check_password, create_jwt
from data.user import user_model, ROLES
from data.user.User import UserTable, STATUS_APPROVED
from data.database import SessionFactory


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


def login_user(phone: str, password: str):
    """
    验证用户凭据，通过后签发 JWT。
    返回 (token, safe_user_dict, error_msg)，成功时 error_msg 为 None。
    """
    if not phone or not password:
        return None, None, "手机号和密码不能为空"

    user = user_model.get_by_phone(phone, include_password=True)
    if user is None or not check_password(password, user["password"]):
        return None, None, "手机号或密码错误"

    if user["status"] == "pending":
        return None, None, "账号尚未通过审核"
    if user["status"] == "rejected":
        remark = user.get("remark") or ""
        return None, None, f"账号审核未通过：{remark}"

    token = create_jwt(
        {
            "user_id": user["id"],
            "phone": user["phone"],
            "name": user["name"],
            "role": user["role"],
        }
    )
    safe_user = {k: user[k] for k in ("id", "phone", "name", "role")}
    return token, safe_user, None


def approve_user(user_id: int, role: str, operator_role: str):
    """
    审核通过并分配角色。店长不可分配 admin 角色。
    返回 (updated_user, error_msg)。
    """
    if role not in ROLES:
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'
    if user_model.get_by_id(user_id) is None:
        return None, "用户不存在"
    if operator_role == "store_manager" and role == "admin":
        return None, "店长无法分配管理员角色"
    updated = user_model.approve(user_id=user_id, role=role)
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


def change_user_role(user_id: int, role: str | None):
    """
    直接修改已有用户的角色（管理员操作）。
    role 为 None 或空字符串时表示删除角色。
    返回 (updated_user, error_msg)。
    """
    # Allow None or empty string to remove role
    if role is not None and role != "" and role not in ROLES:
        return None, f'无效角色，可选角色: {", ".join(ROLES)}'
    if user_model.get_by_id(user_id) is None:
        return None, "用户不存在"
    # Normalize empty string to None
    actual_role = None if role == "" else role
    updated = user_model.update_role(user_id=user_id, role=actual_role)
    return updated, None


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
        user = UserTable(
            phone=admin_phone,
            name=admin_name,
            password=hash_password(admin_password),
            role="admin",
            status=STATUS_APPROVED,
            create_date=now,
            update_date=now,
        )
        session.add(user)
        session.commit()

    print(f"[INIT] Created admin user: {admin_phone}")
    return True
