import hashlib
import hmac
import base64
import json
import os
import time
from functools import wraps

from flask import request, jsonify

secret_key = "SAFE_HISTORY_VALUE"

# Token valid duration in seconds (7 days)
TOKEN_EXPIRE_SECONDS = 7 * 24 * 3600


def base64url_encode(data):
    """Base64Url编码"""
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def base64url_decode(data):
    """Base64Url解码"""
    return base64.urlsafe_b64decode(data + b"==")


def create_signature(header, payload, _secret_key):
    """创建JWT签名"""
    header_b64 = base64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    data = header_b64 + b"." + payload_b64
    signature = hmac.new(_secret_key.encode(), data, hashlib.sha256).digest()
    return base64url_encode(signature)


def create_jwt(payload: dict) -> str:
    """创建JWT token，payload中若未含exp则自动补充过期时间"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(payload)
    if "exp" not in payload:
        payload["exp"] = int(time.time()) + TOKEN_EXPIRE_SECONDS
    header_b64 = base64url_encode(
        json.dumps(header, separators=(",", ":")).encode()
    ).decode()
    payload_b64 = base64url_encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    sig_b64 = create_signature(header, payload, secret_key).decode()
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_jwt(token, _secret_key):
    """验证JWT的有效性，返回 (True, payload) 或 (False, error_message)"""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        return False, "Invalid token format"

    try:
        header = json.loads(base64url_decode(header_b64.encode()).decode())
        payload = json.loads(base64url_decode(payload_b64.encode()).decode())
    except Exception:
        return False, "Invalid token encoding"

    expected_signature = create_signature(header, payload, _secret_key)
    if not hmac.compare_digest(expected_signature, signature_b64.encode()):
        return False, "Invalid signature"

    exp = payload.get("exp")
    if exp and int(time.time()) > exp:
        return False, "Token expired"

    return True, payload


def hash_password(password: str) -> str:
    """使用PBKDF2-SHA256对密码进行哈希，返回 salt:dk 格式的字符串"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return base64url_encode(salt).decode() + ":" + base64url_encode(dk).decode()


def check_password(password: str, hashed: str) -> bool:
    """验证密码是否与哈希值匹配"""
    try:
        salt_b64, dk_b64 = hashed.split(":")
        salt = base64url_decode(salt_b64.encode())
        expected_dk = base64url_decode(dk_b64.encode())
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(dk, expected_dk)
    except Exception:
        return False


def get_token_payload():
    """从请求Header中解析并验证token，返回payload dict或None"""
    x_token = request.headers.get("x-token")
    if not x_token:
        return None
    valid, result = verify_jwt(x_token, secret_key)
    return result if valid else None


def verify(func):
    """装饰器：验证JWT token有效性，无效则返回401"""

    @wraps(func)
    def wrap_func(**kwargs):
        x_token = request.headers.get("x-token")
        if x_token is None:
            return jsonify({"msg": "Missing authorization token"}), 401
        valid, result = verify_jwt(x_token, secret_key)
        if not valid:
            return jsonify({"msg": result}), 401
        return func(**kwargs)

    return wrap_func


def allow(ip_addr: list = None, role=None):
    """
    装饰器：可选IP白名单检查与角色权限检查。

    :param ip_addr: 允许的IP地址列表，None表示不限制
    :param role:    允许的角色，可以是单个字符串或字符串列表，None表示不限制
    """

    def allow_decorator(func):
        @wraps(func)
        def wrap_func(**kwargs):
            if ip_addr is not None and request.remote_addr not in ip_addr:
                return jsonify({"msg": "IP Deny"}), 403

            if role is not None:
                x_token = request.headers.get("x-token")
                if x_token is None:
                    return jsonify({"msg": "Missing authorization token"}), 401
                valid, payload = verify_jwt(x_token, secret_key)
                if not valid:
                    return jsonify({"msg": payload}), 401
                user_role = payload.get("role")
                allowed_roles = role if isinstance(role, list) else [role]
                if user_role not in allowed_roles:
                    return jsonify({"msg": "Permission denied"}), 403

            return func(**kwargs)

        return wrap_func

    return allow_decorator
