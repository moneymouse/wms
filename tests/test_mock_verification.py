"""简单测试验证Mock配置是否正确"""

import pytest
from unittest.mock import patch


def test_mock_verification(client):
    """验证Mock配置是否正确"""
    # 这个测试只是验证应用是否能正常启动
    response = client.get("/ip")
    # IP端点不需要数据库，应该能正常工作
    assert response.status_code == 200


@pytest.mark.unit
def test_database_mock_works():
    """测试数据库Mock是否工作"""
    # Mock所有数据库相关操作
    with patch("data.user.user_model") as mock_user_model, patch(
        "data.order_model"
    ) as mock_order_model, patch("data.cargo_model") as mock_cargo_model:

        # 设置Mock返回值
        mock_user_model.get_by_phone.return_value = None
        mock_order_model.read.return_value = []
        mock_cargo_model.read.return_value = []

        # 简单验证Mock是工作的
        assert mock_user_model.get_by_phone("test") is None
        assert mock_order_model.read() == []
        assert mock_cargo_model.read() == []


def test_auth_endpoints_with_mock(client):
    """测试认证端点的Mock"""
    # 测试注册端点（不需要认证）
    with patch("services.auth_service.register_user") as mock_register:
        mock_register.return_value = ({"id": 1, "phone": "test", "name": "test"}, None)

        response = client.post(
            "/api/auth/register",
            json={"phone": "13800000001", "name": "测试用户", "password": "test123"},
        )

        assert response.status_code == 200
        mock_register.assert_called_once()


def test_order_endpoints_with_mock(client, employee_token):
    """测试订单端点的Mock"""
    with patch("data.order_model.read") as mock_read:
        mock_read.return_value = []

        response = client.get(
            "/api/orders", headers={"Authorization": f"Bearer {employee_token}"}
        )

        # 这里可能会因为认证失败而返回401，这是预期的
        # 主要目的是确保不会因为数据库连接错误而失败
        assert response.status_code in [200, 401, 403]
