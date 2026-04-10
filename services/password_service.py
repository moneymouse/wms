"""
密码管理服务
提供密码修改、忘记密码申请、密码重置审核等功能
"""

from Auth import hash_password, check_password
from data.user import user_model
from data.user.PasswordResetRequest import password_reset_request_model


def request_password_reset(phone: str, new_password: str):
    """
    忘记密码申请 - 提交新密码等待管理员审核
    返回 (request_dict, error_msg)
    """
    if not phone or not new_password:
        return None, "手机号和新密码不能为空"

    if len(new_password) < 6:
        return None, "密码长度不能少于6位"

    user = user_model.get_by_phone(phone)
    if user is None:
        return None, "该手机号未注册"

    # 创建密码重置申请
    new_password_hash = hash_password(new_password)
    request = password_reset_request_model.create(
        user_id=user["id"], new_password_hash=new_password_hash
    )

    return request, None


def change_password(user_id: int, old_password: str, new_password: str):
    """
    登录用户修改密码 - 需要验证旧密码
    返回 (success, error_msg)
    """
    if not old_password or not new_password:
        return False, "旧密码和新密码不能为空"

    if len(new_password) < 6:
        return False, "新密码长度不能少于6位"

    user = user_model.get_by_id_with_password(user_id)
    if user is None:
        return False, "用户不存在"

    if not check_password(old_password, user["password"]):
        return False, "旧密码错误"

    new_password_hash = hash_password(new_password)
    user_model.update_password(user_id, new_password_hash)

    return True, None


def get_pending_password_requests():
    """
    获取所有待审核的密码重置申请
    返回申请列表，包含用户信息
    """
    return password_reset_request_model.get_pending_with_user_info()


def approve_password_reset(request_id: int):
    """
    审核通过密码重置申请
    返回 (success, error_msg)
    """
    # 获取申请并标记为通过
    request = password_reset_request_model.approve(request_id)
    if request is None:
        return False, "申请不存在或已被处理"

    # 更新用户密码
    result = user_model.update_password(
        request["user_id"], request["new_password_hash"]
    )

    if result is None:
        return False, "用户不存在"

    return True, None


def reject_password_reset(request_id: int, remark: str = None):
    """
    拒绝密码重置申请
    返回 (success, error_msg)
    """
    result = password_reset_request_model.reject(request_id, remark)
    if result is None:
        return False, "申请不存在或已被处理"

    return True, None


def admin_reset_password(user_id: int, new_password: str):
    """
    管理员直接重置用户密码
    返回 (success, error_msg)
    """
    if not new_password:
        return False, "新密码不能为空"

    if len(new_password) < 6:
        return False, "密码长度不能少于6位"

    user = user_model.get_by_id(user_id)
    if user is None:
        return False, "用户不存在"

    new_password_hash = hash_password(new_password)
    user_model.update_password(user_id, new_password_hash)

    return True, None
