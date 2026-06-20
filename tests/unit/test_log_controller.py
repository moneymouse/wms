"""日志控制器测试"""

from unittest.mock import patch

import pytest

from data.DB import AuditLogTable
from tests.base import APITestMixin, BaseControllerTest
from utils.audit import load_audit_logs
from utils.log import OperationLogTable, load_log


def paginated_result(items, total=None, page=1, page_size=10):
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "page": page,
        "page_size": page_size,
    }


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
        """测试管理员成功分页获取操作日志"""
        mock_logs = [
            {
                "id": 3,
                "log_date": "2023-01-01 12:00:00",
                "user_name": "admin",
                "desc": "Create order",
                "kwargs": {},
                "json": {},
            },
            {
                "id": 2,
                "log_date": "2023-01-01 11:00:00",
                "user_name": "employee1",
                "desc": "Update cargo",
                "kwargs": {},
                "json": {},
            },
        ]

        with patch(
            "controllers.log_controller.load_log",
            return_value=paginated_result(mock_logs, total=20, page=1, page_size=10),
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert len(json_data["data"]) == 2
            assert json_data["total"] == 20
            assert json_data["page"] == 1
            assert json_data["page_size"] == 10
            assert json_data["data"][0]["id"] == 3
            assert json_data["data"][1]["user_name"] == "employee1"
            mock_load_log.assert_called_once_with(
                page=1,
                page_size=10,
                sort_field="log_date",
                sort_desc=True,
            )

    def test_get_logs_second_page_admin(self, admin_token):
        """测试操作日志分页参数会传给读取函数"""
        mock_logs = [
            {
                "id": i,
                "log_date": f"2023-01-01 10:{i:02d}:00",
                "desc": f"Action {i}",
                "kwargs": {},
                "json": {},
            }
            for i in range(10)
        ]

        with patch(
            "controllers.log_controller.load_log",
            return_value=paginated_result(mock_logs, total=100, page=2, page_size=10),
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs?p=2&s=10", admin_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert len(json_data["data"]) == 10
            assert json_data["total"] == 100
            assert json_data["page"] == 2
            mock_load_log.assert_called_once_with(
                page=2,
                page_size=10,
                sort_field="log_date",
                sort_desc=True,
            )

    def test_get_logs_sort_and_page_size_are_normalized(self, admin_token):
        """测试分页参数规范化和正序排序"""
        with patch(
            "controllers.log_controller.load_log",
            return_value=paginated_result([], total=0, page=1, page_size=200),
        ) as mock_load_log:
            response = self.make_authenticated_request(
                "GET",
                f"{self.base_url}/logs?p=-2&s=999&sf=pc_name&so=0",
                admin_token,
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert json_data["data"] == []
            mock_load_log.assert_called_once_with(
                page=1,
                page_size=200,
                sort_field="pc_name",
                sort_desc=False,
            )

    def test_get_audit_logs_success_admin(self, admin_token):
        """测试管理员成功分页获取审计日志"""
        mock_logs = [
            {
                "id": 1,
                "event_type": "order_quote",
                "target_type": "order",
                "target_id": "ORDER001",
                "action": "quote_submit",
                "operator_name": "admin",
                "before_data": None,
                "after_data": {},
                "create_date": "2023-01-01 10:00:00",
            }
        ]

        with patch(
            "controllers.log_controller.load_audit_logs",
            return_value=paginated_result(mock_logs, total=1, page=1, page_size=10),
        ) as mock_load_audit_logs:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/audit-logs?p=1&s=10", admin_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert json_data["data"][0]["event_type"] == "order_quote"
            assert json_data["total"] == 1
            mock_load_audit_logs.assert_called_once_with(
                page=1,
                page_size=10,
                sort_field="create_date",
                sort_desc=True,
            )

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
        with patch(
            "controllers.log_controller.load_log",
            return_value=paginated_result([{"id": 1}], total=1),
        ):
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )
            self.assert_api_success(response)

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", store_manager_token
            )
            self.assert_response_code(response, 403)

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", employee_token
            )
            self.assert_response_code(response, 403)

    def test_get_logs_load_function_error_admin(self, admin_token):
        """测试加载日志函数异常"""
        with patch(
            "controllers.log_controller.load_log",
            side_effect=Exception("读取日志失败"),
        ):
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )

            self.assert_response_code(response, 500)

    def test_get_logs_concurrent_access_admin(self, admin_token):
        """测试并发访问日志（模拟）"""
        with patch(
            "controllers.log_controller.load_log",
            return_value=paginated_result([{"id": 1}], total=1),
        ) as mock_load_log:
            responses = []
            for _ in range(3):
                response = self.make_authenticated_request(
                    "GET", f"{self.base_url}/logs", admin_token
                )
                responses.append(response)

            for response in responses:
                self.assert_api_success(response, ["data"])

            assert mock_load_log.call_count == 3


@pytest.mark.unit
@pytest.mark.log
class TestLogReaders:
    """日志读取函数测试"""

    def test_load_log_uses_sql_pagination(self, setup_test_database):
        """测试操作日志读取只返回当前页并保留总数"""
        session = setup_test_database
        for i in range(1, 26):
            session.add(
                OperationLogTable(
                    ip="127.0.0.1",
                    pc_name="WMS-PC",
                    user_name="admin",
                    user_role="admin",
                    desc=f"Action {i}",
                    kwargs="{}",
                    json_body="{}",
                    method="POST",
                    log_date=f"2023-01-01 10:{i:02d}:00",
                )
            )
        session.commit()

        result = load_log(
            page=2,
            page_size=10,
            sort_field="log_date",
            sort_desc=True,
        )

        assert result["total"] == 25
        assert result["page"] == 2
        assert result["page_size"] == 10
        assert len(result["items"]) == 10
        assert result["items"][0]["desc"] == "Action 15"
        assert result["items"][-1]["desc"] == "Action 6"

    def test_load_audit_logs_uses_sql_pagination(self, setup_test_database):
        """测试审计日志读取只返回当前页并保留总数"""
        session = setup_test_database
        for i in range(1, 13):
            session.add(
                AuditLogTable(
                    event_type="order_quote",
                    target_type="order",
                    target_id=f"ORDER{i:03d}",
                    action="quote_submit",
                    operator_name="admin",
                    operator_role="admin",
                    before_data=None,
                    after_data="{}",
                    remark=f"Audit {i}",
                    ip="127.0.0.1",
                    create_date=f"2023-01-01 10:{i:02d}:00",
                )
            )
        session.commit()

        result = load_audit_logs(
            page=1,
            page_size=5,
            sort_field="create_date",
            sort_desc=True,
        )

        assert result["total"] == 12
        assert result["page"] == 1
        assert result["page_size"] == 5
        assert len(result["items"]) == 5
        assert result["items"][0]["remark"] == "Audit 12"
        assert result["items"][-1]["remark"] == "Audit 8"
