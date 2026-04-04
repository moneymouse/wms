"""pytest 配置和 fixtures"""

import os
import sys
import tempfile
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_root)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 测试环境变量设置 - 必须在导入任何模块之前设置
os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# 创建SQLAlchemy测试配置
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 创建测试用SQLite引擎
test_engine = create_engine("sqlite:///:memory:", echo=False)
TestSessionFactory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

# Mock SQLAlchemy组件，必须在导入应用之前
original_patches = []


def setup_sqlalchemy_mocks():
    """设置SQLAlchemy mocks"""
    global original_patches

    # Mock数据库引擎和SessionFactory
    engine_patch = patch("data.database.engine", test_engine)
    session_patch = patch("data.database.SessionFactory", TestSessionFactory)

    original_patches = [engine_patch, session_patch]

    for p in original_patches:
        p.start()


def cleanup_sqlalchemy_mocks():
    """清理SQLAlchemy mocks"""
    global original_patches
    for p in original_patches:
        try:
            p.stop()
        except:
            pass
    original_patches = []


# 设置mocks
setup_sqlalchemy_mocks()

try:
    from app import app as flask_app
    from tests.test_config import (
        TestConfig,
        TEST_USERS,
        TEST_ORDER_DATA,
        TEST_CARGO_DATA,
    )
    from Auth import hash_password, create_jwt
    from data.database import Base

    # Import OperationLogTable to register it with Base.metadata
    from utils.log import OperationLogTable  # noqa: F401

    # 创建所有表
    Base.metadata.create_all(bind=test_engine)

except Exception as e:
    print(f"导入模块时出错: {e}")
    # 如果导入失败，清理mocks
    cleanup_sqlalchemy_mocks()
    raise


@pytest.fixture(scope="session")
def app():
    """创建测试应用实例"""
    flask_app.config.from_object(TestConfig)
    flask_app.config["TESTING"] = True
    flask_app.config["DATABASE_URL"] = "sqlite:///:memory:"

    with flask_app.app_context():
        yield flask_app


@pytest.fixture(scope="function")
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture(scope="function", autouse=True)
def setup_test_database():
    """为每个测试设置独立的数据库会话"""
    # 创建新的测试session
    session = TestSessionFactory()

    # Mock SessionFactory 以返回我们的测试session
    def mock_session_factory():
        return session

    with patch("data.database.SessionFactory", mock_session_factory), patch(
        "data.user.User.SessionFactory", mock_session_factory
    ), patch("data.DB.SessionFactory", mock_session_factory):

        try:
            yield session
        finally:
            # 清理session
            try:
                session.rollback()
            except Exception:
                pass
            finally:
                session.close()

            # 清理所有表数据 (SQLAlchemy 2.x 兼容语法)
            with test_engine.connect() as conn:
                for table in reversed(Base.metadata.sorted_tables):
                    conn.execute(table.delete())
                conn.commit()


@pytest.fixture
def test_users_data():
    """测试用户数据"""
    return TEST_USERS.copy()


@pytest.fixture
def test_order_data():
    """测试订单数据"""
    return TEST_ORDER_DATA.copy()


@pytest.fixture
def test_cargo_data():
    """测试货物数据"""
    return TEST_CARGO_DATA.copy()


@pytest.fixture
def admin_user():
    """创建测试管理员用户"""
    # Mock user_model的方法，返回预定义的用户数据
    mock_user = {
        "id": 1,
        "phone": "13800000001",
        "name": "管理员测试",
        "role": "admin",
        "status": "approved",
    }
    return mock_user


@pytest.fixture
def store_manager_user():
    """创建测试店长用户"""
    mock_user = {
        "id": 2,
        "phone": "13800000002",
        "name": "店长测试",
        "role": "store_manager",
        "status": "approved",
    }
    return mock_user


@pytest.fixture
def salesperson_user():
    """创建测试业务员用户"""
    mock_user = {
        "id": 3,
        "phone": "13800000003",
        "name": "业务员测试",
        "role": "salesperson",
        "status": "approved",
    }
    return mock_user


@pytest.fixture
def clerk_user():
    """创建测试文员用户"""
    mock_user = {
        "id": 4,
        "phone": "13800000004",
        "name": "文员测试",
        "role": "clerk",
        "status": "approved",
    }
    return mock_user


@pytest.fixture
def employee_user():
    """创建测试员工用户"""
    mock_user = {
        "id": 5,
        "phone": "13800000005",
        "name": "员工测试",
        "role": "employee",
        "status": "approved",
    }
    return mock_user


@pytest.fixture
def pending_user():
    """创建待审核用户"""
    mock_user = {
        "id": 6,
        "phone": "13800000006",
        "name": "待审核用户",
        "role": None,
        "status": "pending",
    }
    return mock_user


@pytest.fixture
def admin_token(admin_user):
    """管理员JWT Token"""
    return create_jwt(
        {
            "user_id": admin_user["id"],
            "phone": admin_user["phone"],
            "name": admin_user["name"],
            "role": admin_user["role"],
        }
    )


@pytest.fixture
def store_manager_token(store_manager_user):
    """店长JWT Token"""
    return create_jwt(
        {
            "user_id": store_manager_user["id"],
            "phone": store_manager_user["phone"],
            "name": store_manager_user["name"],
            "role": store_manager_user["role"],
        }
    )


@pytest.fixture
def salesperson_token(salesperson_user):
    """业务员JWT Token"""
    return create_jwt(
        {
            "user_id": salesperson_user["id"],
            "phone": salesperson_user["phone"],
            "name": salesperson_user["name"],
            "role": salesperson_user["role"],
        }
    )


@pytest.fixture
def clerk_token(clerk_user):
    """文员JWT Token"""
    return create_jwt(
        {
            "user_id": clerk_user["id"],
            "phone": clerk_user["phone"],
            "name": clerk_user["name"],
            "role": clerk_user["role"],
        }
    )


@pytest.fixture
def employee_token(employee_user):
    """员工JWT Token"""
    return create_jwt(
        {
            "user_id": employee_user["id"],
            "phone": employee_user["phone"],
            "name": employee_user["name"],
            "role": employee_user["role"],
        }
    )


@pytest.fixture
def test_order():
    """创建测试订单"""
    mock_order = {
        "uid": "test_order_uid",
        "order_id": "TEST001",
        "customer_name": "测试客户",
        "receiver": "测试收件人",
        "cargo_uid_list": [],
        "cargo_count": 0,
    }
    return mock_order


@pytest.fixture
def test_cargo():
    """创建测试货物"""
    mock_cargo = {
        "uid": "test_cargo_uid",
        "transfer_id": "TR001",
        "waybill_id": "WB001",
        "weight": 1.5,
        "count": 1,
        "status": 0,
    }
    return mock_cargo


@pytest.fixture
def auth_headers():
    """认证头部工厂函数"""

    def _make_headers(token):
        return {"Authorization": f"Bearer {token}"}

    return _make_headers


@pytest.fixture
def json_headers():
    """JSON Content-Type 头部"""
    return {"Content-Type": "application/json"}


@pytest.fixture
def mock_file_upload():
    """Mock文件上传"""
    file_content = b"transfer_id,waybill_id\nTR001,WB001\nTR002,WB002\n"
    return BytesIO(file_content)


@pytest.fixture(autouse=True)
def mock_external_services():
    """Mock外部服务"""
    with patch("utils.l7track.getTrackInfo") as mock_track_info, patch(
        "utils.l7track.registerTrack"
    ) as mock_register_track, patch(
        "services.cargo_service.background_register"
    ) as mock_bg_register:

        # Mock 17track 服务
        mock_track_info.return_value = [
            {
                "tag": "test_cargo_uid",
                "track_info": {
                    "latest_status": {
                        "status": "Delivered",
                        "sub_status": "delivered",
                        "sub_status_descr": "已送达",
                    },
                    "tracking": {
                        "providers": [
                            {
                                "events": [
                                    {"date": "2023-01-01", "description": "包裹已送达"}
                                ]
                            }
                        ]
                    },
                },
            }
        ]

        mock_register_track.return_value = True
        mock_bg_register.return_value = None

        yield {
            "track_info": mock_track_info,
            "register_track": mock_register_track,
            "bg_register": mock_bg_register,
        }


# pytest会话结束时的清理工作
def pytest_sessionfinish(session, exitstatus):
    """pytest会话结束时清理"""
    cleanup_sqlalchemy_mocks()
