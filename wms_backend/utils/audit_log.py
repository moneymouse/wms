"""审计日志模块 - 记录敏感数据访问"""

import logging
import os
from datetime import datetime
from typing import Optional


# 确保log目录存在
LOG_DIR = "log"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 配置审计日志记录器
audit_logger = logging.getLogger("audit.sensitive_access")
audit_logger.setLevel(logging.INFO)

# 如果还没有handler，添加文件handler
if not audit_logger.handlers:
    # 创建文件handler
    handler = logging.FileHandler(os.path.join(LOG_DIR, "audit_sensitive_access.log"))

    # 设置日志格式
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    # 添加handler到logger
    audit_logger.addHandler(handler)

    # 防止日志向上传播到root logger
    audit_logger.propagate = False


def log_sensitive_access(
    user_id: int,
    user_role: str,
    user_name: str,
    action: str,
    customer_name: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """记录敏感字段访问日志

    Args:
        user_id: 用户ID
        user_role: 用户角色（admin, store_manager, salesperson等）
        user_name: 用户姓名
        action: 操作类型，可选值：
            - view_all_customers: 查看所有客户详情
            - view_customer_detail: 查看单个客户详情
            - update_customer_contact: 更新客户联系信息
        customer_name: 客户名称（对于单个客户操作时必填）
        ip_address: 客户端IP地址（可选）

    Examples:
        >>> log_sensitive_access(
        ...     user_id=1,
        ...     user_role="admin",
        ...     user_name="张三",
        ...     action="view_all_customers",
        ...     ip_address="127.0.0.1"
        ... )

        >>> log_sensitive_access(
        ...     user_id=2,
        ...     user_role="salesperson",
        ...     user_name="李四",
        ...     action="update_customer_contact",
        ...     customer_name="测试公司",
        ...     ip_address="192.168.1.100"
        ... )
    """
    # 构建日志消息
    log_message = (
        f"User[ID={user_id}, Role={user_role}, Name={user_name}] "
        f"performed '{action}'"
    )

    # 添加客户名称（如果提供）
    if customer_name:
        log_message += f" on Customer[{customer_name}]"

    # 添加IP地址（如果提供）
    if ip_address:
        log_message += f" from IP[{ip_address}]"

    # 记录日志
    audit_logger.info(log_message)


def get_audit_logs(limit: int = 100) -> list:
    """获取最近的审计日志记录

    Args:
        limit: 返回的日志条数，默认100条

    Returns:
        list: 审计日志列表，每条日志是一个字符串

    Note:
        此函数用于查看审计记录，仅管理员可调用
    """
    log_file = os.path.join(LOG_DIR, "audit_sensitive_access.log")

    if not os.path.exists(log_file):
        return []

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            # 读取所有行
            all_lines = f.readlines()
            # 返回最后limit条
            return [line.strip() for line in all_lines[-limit:]]
    except Exception as e:
        logging.error(f"Failed to read audit log: {e}")
        return []


# 操作类型常量
ACTION_VIEW_ALL = "view_all_customers"
ACTION_VIEW_SINGLE = "view_customer_detail"
ACTION_UPDATE = "update_customer_contact"
ACTION_CREATE = "create_customer"
ACTION_DELETE = "delete_customer"
