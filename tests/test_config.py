"""测试配置和设置"""

import os
import tempfile
import pytest
from faker import Faker

# 全局测试配置
TEST_DATABASE_PATH = ":memory:"  # 使用内存数据库进行测试
fake = Faker("zh_CN")

# 测试用户数据
TEST_USERS = {
    "admin": {
        "phone": "13800000001",
        "name": "管理员测试",
        "password": "admin123",
        "role": "admin",
    },
    "store_manager": {
        "phone": "13800000002",
        "name": "店长测试",
        "password": "manager123",
        "role": "store_manager",
    },
    "employee": {
        "phone": "13800000003",
        "name": "员工测试",
        "password": "employee123",
        "role": "employee",
    },
    "pending": {
        "phone": "13800000004",
        "name": "待审核用户",
        "password": "pending123",
        "role": None,
    },
}

# 测试订单数据
TEST_ORDER_DATA = {
    "order_id": "TEST001",
    "customer_name": "测试客户",
    "receiver": "测试收件人",
    "receiver_phone": "13900000001",
    "address": "测试地址123号",
    "city": "北京",
    "province": "北京",
    "country": "中国",
    "zip_code": "100001",
    "cargo_count": 2,
    "tag_all": "TEST",
}

# 测试货物数据
TEST_CARGO_DATA = {
    "transfer_id": "TR001",
    "waybill_id": "WB001",
    "weight": 1.5,
    "count": 1,
    "status": 0,
}

# API测试基础URL
API_BASE_URL = "/api"


class TestConfig:
    """测试配置类"""

    TESTING = True
    DATABASE_PATH = TEST_DATABASE_PATH
    SECRET_KEY = "test-secret-key"
    JWT_SECRET_KEY = "test-jwt-secret"

    # 日志配置
    LOGGING_LEVEL = "ERROR"

    # 外部服务Mock
    MOCK_EXTERNAL_SERVICES = True

    # 文件上传配置
    UPLOAD_FOLDER = tempfile.mkdtemp()
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
