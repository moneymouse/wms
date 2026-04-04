import json

from flask import Blueprint, jsonify, request

from Auth import verify, allow, get_token_payload
from data.user import user_model, ROLES
from services.auth_service import (
    register_user,
    login_user,
    approve_user,
    reject_user,
    change_user_role,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


# 注册（无需登录，提交后等待审核）
@auth_bp.post("/auth/register")
def register():
    body = json.loads(request.data)
    phone = body.get("phone", "").strip()
    name = body.get("name", "").strip()
    password = body.get("password", "")

    user, err = register_user(phone, name, password)
    if err:
        status = 409 if "已注册" in err else 400
        return jsonify({"code": status, "msg": err}), status
    return jsonify({"code": 200, "msg": "注册成功，请等待审核"})


# 登录
@auth_bp.post("/auth/login")
def login():
    body = json.loads(request.data)
    phone = body.get("phone", "").strip()
    password = body.get("password", "")

    token, safe_user, err = login_user(phone, password)
    if err:
        status = 400 if "不能为空" in err else 403 if "审核" in err else 401
        return jsonify({"code": status, "msg": err}), status
    return jsonify({"code": 200, "token": token, "user": safe_user})


# 获取待审核用户列表（管理员 / 店长）
@auth_bp.get("/auth/pending")
@verify
@allow(role=["admin", "store_manager"])
def get_pending_users():
    return jsonify({"code": 200, "data": user_model.get_by_status("pending")})


# 审核通过并分配角色（管理员 / 店长）
@auth_bp.post("/auth/approve/<int:user_id>")
@verify
@allow(role=["admin", "store_manager"])
def approve(user_id):
    body = json.loads(request.data)
    role = body.get("role", "").strip()
    payload = get_token_payload()
    operator_role = payload.get("role") if payload else None

    updated, err = approve_user(user_id, role, operator_role)
    if err:
        if "不存在" in err:
            return jsonify({"code": 404, "msg": err}), 404
        status = 403 if "无法" in err else 400
        return jsonify({"code": status, "msg": err}), status
    return jsonify({"code": 200, "msg": "审核通过", "data": updated})


# 审核拒绝（管理员 / 店长）
@auth_bp.post("/auth/reject/<int:user_id>")
@verify
@allow(role=["admin", "store_manager"])
def reject(user_id):
    body = json.loads(request.data)
    remark = body.get("remark", "")

    updated, err = reject_user(user_id, remark)
    if err:
        return jsonify({"code": 404, "msg": err}), 404
    return jsonify({"code": 200, "msg": "已拒绝", "data": updated})


# 获取全部用户（管理员）
@auth_bp.get("/users")
@verify
@allow(role="admin")
def get_all_users():
    return jsonify({"code": 200, "data": user_model.get_all()})


# 获取用户简要列表（所有已登录用户）
@auth_bp.get("/users/list")
@verify
def get_user_list():
    """
    Get simplified user list (id, name, phone only).
    Only approved users are returned.
    Available to all authenticated users.
    """
    users = user_model.get_by_status("approved")
    # Filter to only include id, name, phone
    simplified_users = [
        {"id": user["id"], "name": user["name"], "phone": user["phone"]}
        for user in users
    ]
    return jsonify({"code": 200, "data": simplified_users})


# 修改用户角色（管理员）
@auth_bp.put("/users/<int:user_id>/role")
@verify
@allow(role="admin")
def update_role(user_id):
    """
    Update user role.
    Request body: {"role": "salesperson"} to set role
                  {"role": null} or {"role": ""} to remove role
    """
    body = json.loads(request.data)
    role = body.get("role")
    # Handle string role - strip whitespace
    if isinstance(role, str):
        role = role.strip() if role else None

    updated, err = change_user_role(user_id, role)
    if err:
        status = 404 if "不存在" in err else 400
        return jsonify({"code": status, "msg": err}), status
    msg = "角色已更新" if updated.get("role") else "角色已删除"
    return jsonify({"code": 200, "msg": msg, "data": updated})
