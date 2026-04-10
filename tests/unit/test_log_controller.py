"""日志控制器测试"""

import pytest
from unittest.mock import patch

from tests.base import BaseControllerTest, APITestMixin


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.log
class TestLogController(BaseControllerTest, APITestMixin):
    """日志控制器测试"""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client
        self.base_url = "/api"

    def test_get_logs_success_admin(self, admin_token):
        """测试管理员成功获取日志"""
        mock_logs = [
            {
                "timestamp": "2023-01-01 10:00:00",
                "user": "admin",
                "action": "Create order",
                "details": "订单 TEST001 创建成功",
            },
            {
                "timestamp": "2023-01-01 11:00:00",
                "user": "employee1",
                "action": "Update cargo",
                "details": "货物 CARGO001 状态更新",
            },
            {
                "timestamp": "2023-01-01 12:00:00",
                "user": "store_manager",
                "action": "Approve user",
                "details": "用户 user123 审核通过",
            },
        ]

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 3
            assert json_data["data"][0]["action"] == "Create order"
            assert json_data["data"][1]["user"] == "employee1"
            assert json_data["data"][2]["details"] == "用户 user123 审核通过"

            # 验证load_log被调用
            mock_load_log.assert_called_once()

    def test_get_logs_empty_result_admin(self, admin_token):
        """测试管理员获取空日志"""
        mock_logs = []

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 0
            mock_load_log.assert_called_once()

    def test_get_logs_large_dataset_admin(self, admin_token):
        """测试管理员获取大量日志数据"""
        # 模拟大量日志数据
        mock_logs = []
        for i in range(100):
            mock_logs.append(
                {
                    "timestamp": f"2023-01-01 {i//4:02d}:{(i%4)*15:02d}:00",
                    "user": f"user{i%5}",
                    "action": f"Action {i%3}",
                    "details": f"操作详情 {i}",
                }
            )

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 100
            mock_load_log.assert_called_once()

    def test_get_logs_with_special_characters_admin(self, admin_token):
        """测试包含特殊字符的日志"""
        mock_logs = [
            {
                "timestamp": "2023-01-01 10:00:00",
                "user": "用户@测试",
                "action": "创建订单",
                "details": "订单包含特殊字符: <>&\"'",
            },
            {
                "timestamp": "2023-01-01 11:00:00",
                "user": "测试用户2",
                "action": "更新货物",
                "details": 'JSON数据: {"key": "value", "number": 123}',
            },
        ]

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2

            # 验证特殊字符被正确处理
            assert "用户@测试" in json_data["data"][0]["user"]
            assert "<>&\"'" in json_data["data"][0]["details"]
            assert '{"key": "value", "number": 123}' in json_data["data"][1]["details"]

    def test_get_logs_requires_auth(self):
        """测试获取日志需要认证"""
        self.assert_endpoint_requires_auth("GET", f"{self.base_url}/logs")

    def test_get_logs_invalid_token(self):
        """测试使用无效token获取日志"""
        self.assert_endpoint_rejects_invalid_token("GET", f"{self.base_url}/logs")

    def test_get_logs_store_manager_forbidden(self, store_manager_token):
        """测试店长无权限获取日志"""
        self.assert_endpoint_permission_denied(
            "GET", f"{self.base_url}/logs", store_manager_token
        )

    def test_get_logs_employee_forbidden(self, employee_token):
        """测试员工无权限获取日志"""
        self.assert_endpoint_permission_denied(
            "GET", f"{self.base_url}/logs", employee_token
        )

    def test_get_logs_admin_only_access(
        self, admin_token, store_manager_token, employee_token
    ):
        """测试只有管理员可以访问日志"""
        # 准备测试数据
        mock_logs = [
            {
                "timestamp": "2023-01-01",
                "user": "test",
                "action": "test",
                "details": "test",
            }
        ]

        with patch("controllers.log_controller.load_log", return_value=mock_logs):
            # 管理员应该可以访问
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )
            self.assert_api_success(response)

            # 店长应该被拒绝
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", store_manager_token
            )
            self.assert_response_code(response, 403)

            # 员工应该被拒绝
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", employee_token
            )
            self.assert_response_code(response, 403)

    def test_get_logs_load_function_error_admin(self, admin_token):
        """测试加载日志函数异常"""
        with patch(
            "controllers.log_controller.load_log",
            side_effect=Exception("读取日志文件失败"),
        ):
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            # 控制器没有异常处理，Flask 会返回 500
            assert response.status_code == 500

    def test_get_logs_with_none_values_admin(self, admin_token):
        """测试包含None值的日志数据"""
        mock_logs = [
            {
                "timestamp": "2023-01-01 10:00:00",
                "user": None,
                "action": "系统操作",
                "details": None,
            },
            {
                "timestamp": None,
                "user": "test_user",
                "action": None,
                "details": "正常详情",
            },
        ]

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2

            # 验证None值被正确处理
            assert json_data["data"][0]["user"] is None
            assert json_data["data"][0]["details"] is None
            assert json_data["data"][1]["timestamp"] is None
            assert json_data["data"][1]["action"] is None

    def test_get_logs_concurrent_access_admin(self, admin_token):
        """测试并发访问日志（模拟）"""
        mock_logs = [
            {
                "timestamp": "2023-01-01",
                "user": "concurrent_user",
                "action": "test",
                "details": "test",
            }
        ]

        with patch(
            "controllers.log_controller.load_log", return_value=mock_logs
        ) as mock_load_log:
            # 模拟多次并发请求
            responses = []
            for i in range(3):
                response = self.make_authenticated_request(
                    "GET", f"{self.base_url}/logs", admin_token
                )
                responses.append(response)

            # 所有请求都应该成功
            for response in responses:
                self.assert_api_success(response, ["data"])

            # load_log应该被调用3次
            assert mock_load_log.call_count == 3
