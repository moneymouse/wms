"""认证控制器测试"""

import pytest
import json
from unittest.mock import patch

from tests.base import BaseControllerTest, APITestMixin, DatabaseTestMixin
from tests.factories import AuthFactory, UserFactory, ResponseFactory


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.auth
class TestAuthController(BaseControllerTest, APITestMixin, DatabaseTestMixin):
    """认证控制器测试"""

    def __init__(self, client):
        super().__init__(client)
        self.base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client

    def test_register_success(self):
        """测试成功注册"""
        user_data = AuthFactory.create_register_data()

        with patch("services.auth_service.register_user") as mock_register:
            mock_user = {
                "id": 1,
                "phone": user_data["phone"],
                "name": user_data["name"],
            }
            mock_register.return_value = (mock_user, None)

            response = self.make_request(
                "POST", f"{self.base_url}/auth/register", user_data
            )

            json_data = self.assert_api_success(response)
            assert "注册成功" in json_data["msg"]
            mock_register.assert_called_once_with(
                user_data["phone"], user_data["name"], user_data["password"]
            )

    def test_register_phone_exists(self):
        """测试手机号已存在"""
        user_data = AuthFactory.create_register_data()

        with patch("services.auth_service.register_user") as mock_register:
            mock_register.return_value = (None, "该手机号已注册")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/register", user_data
            )

            self.assert_response_code(response, 409)
            json_data = self.assert_response_json(response, ["code", "msg"])
            assert json_data["code"] == 409
            assert "已注册" in json_data["msg"]

    def test_register_validation_error(self):
        """测试注册验证错误"""
        user_data = AuthFactory.create_register_data()

        with patch("services.auth_service.register_user") as mock_register:
            mock_register.return_value = (None, "手机号、姓名和密码不能为空")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/register", user_data
            )

            self.assert_response_code(response, 400)
            json_data = self.assert_response_json(response, ["code", "msg"])
            assert json_data["code"] == 400

    def test_login_success(self):
        """测试成功登录"""
        login_data = AuthFactory.create_login_data("13800000001")

        with patch("services.auth_service.login_user") as mock_login:
            mock_user = {
                "id": 1,
                "phone": "13800000001",
                "name": "测试用户",
                "role": "employee",
            }
            mock_login.return_value = ("test_token", mock_user, None)

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )

            json_data = self.assert_api_success(response, ["token", "user"])
            assert json_data["token"] == "test_token"
            assert json_data["user"]["id"] == 1

    def test_login_validation_error(self):
        """测试登录验证错误"""
        login_data = AuthFactory.create_login_data("")

        with patch("services.auth_service.login_user") as mock_login:
            mock_login.return_value = (None, None, "手机号和密码不能为空")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )

            self.assert_response_code(response, 400)
            json_data = self.assert_api_error(response, 400)

    def test_login_pending_user(self):
        """测试登录待审核用户"""
        login_data = AuthFactory.create_login_data("13800000001")

        with patch("services.auth_service.login_user") as mock_login:
            mock_login.return_value = (None, None, "账号尚未通过审核")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )

            self.assert_response_code(response, 403)
            json_data = self.assert_api_error(response, 403)
            assert "审核" in json_data["msg"]

    def test_login_wrong_credentials(self):
        """测试错误凭据登录"""
        login_data = AuthFactory.create_login_data("13800000001")

        with patch("services.auth_service.login_user") as mock_login:
            mock_login.return_value = (None, None, "手机号或密码错误")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )

            self.assert_response_code(response, 401)
            json_data = self.assert_api_error(response, 401)

    def test_get_pending_users_success(self, admin_token):
        """测试获取待审核用户列表"""
        with patch("data.user.user_model.get_by_status") as mock_get_pending:
            mock_users = [
                {"id": 1, "phone": "13800000001", "name": "用户1", "status": "pending"},
                {"id": 2, "phone": "13800000002", "name": "用户2", "status": "pending"},
            ]
            mock_get_pending.return_value = mock_users

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/auth/pending", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            mock_get_pending.assert_called_once_with("pending")

    def test_get_pending_users_requires_auth(self):
        """测试获取待审核用户需要认证"""
        self.test_endpoint_requires_auth("GET", f"{self.base_url}/auth/pending")

    def test_get_pending_users_permission_denied(self, employee_token):
        """测试获取待审核用户权限不足"""
        self.test_endpoint_permission_denied(
            "GET", f"{self.base_url}/auth/pending", employee_token
        )

    def test_approve_user_success(self, admin_token):
        """测试成功审核用户"""
        approve_data = AuthFactory.create_approve_data("employee")

        with patch("services.auth_service.approve_user") as mock_approve, patch(
            "Auth.get_token_payload"
        ) as mock_payload:

            mock_payload.return_value = {"role": "admin"}
            mock_user = {"id": 1, "role": "employee", "status": "approved"}
            mock_approve.return_value = (mock_user, None)

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/auth/approve/1", admin_token, approve_data
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"]["id"] == 1
            mock_approve.assert_called_once_with(1, "employee", "admin")

    def test_approve_user_not_found(self, admin_token):
        """测试审核不存在的用户"""
        approve_data = AuthFactory.create_approve_data("employee")

        with patch("services.auth_service.approve_user") as mock_approve, patch(
            "Auth.get_token_payload"
        ) as mock_payload:

            mock_payload.return_value = {"role": "admin"}
            mock_approve.return_value = (None, "用户不存在")

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/auth/approve/999", admin_token, approve_data
            )

            self.assert_response_code(response, 404)
            json_data = self.assert_api_error(response, 404)
            assert "不存在" in json_data["msg"]

    def test_approve_user_invalid_role(self, admin_token):
        """测试审核时使用无效角色"""
        approve_data = {"role": "invalid_role"}

        with patch("services.auth_service.approve_user") as mock_approve, patch(
            "Auth.get_token_payload"
        ) as mock_payload:

            mock_payload.return_value = {"role": "admin"}
            mock_approve.return_value = (None, "无效角色")

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/auth/approve/1", admin_token, approve_data
            )

            self.assert_response_code(response, 400)
            json_data = self.assert_api_error(response, 400)

    def test_approve_user_store_manager_cannot_assign_admin(self, store_manager_token):
        """测试店长不能分配管理员角色"""
        approve_data = AuthFactory.create_approve_data("admin")

        with patch("services.auth_service.approve_user") as mock_approve, patch(
            "Auth.get_token_payload"
        ) as mock_payload:

            mock_payload.return_value = {"role": "store_manager"}
            mock_approve.return_value = (None, "店长无法分配管理员角色")

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/auth/approve/1",
                store_manager_token,
                approve_data,
            )

            self.assert_response_code(response, 403)

    def test_reject_user_success(self, admin_token):
        """测试成功拒绝用户"""
        reject_data = AuthFactory.create_reject_data("不符合要求")

        with patch("services.auth_service.reject_user") as mock_reject:
            mock_user = {"id": 1, "status": "rejected", "remark": "不符合要求"}
            mock_reject.return_value = (mock_user, None)

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/auth/reject/1", admin_token, reject_data
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"]["status"] == "rejected"
            mock_reject.assert_called_once_with(1, "不符合要求")

    def test_reject_user_not_found(self, admin_token):
        """测试拒绝不存在的用户"""
        reject_data = AuthFactory.create_reject_data()

        with patch("services.auth_service.reject_user") as mock_reject:
            mock_reject.return_value = (None, "用户不存在")

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/auth/reject/999", admin_token, reject_data
            )

            self.assert_response_code(response, 404)

    def test_get_all_users_success(self, admin_token):
        """测试获取所有用户"""
        with patch("data.user.user_model.get_all") as mock_get_all:
            mock_users = [
                {"id": 1, "phone": "13800000001", "name": "用户1", "role": "admin"},
                {"id": 2, "phone": "13800000002", "name": "用户2", "role": "employee"},
            ]
            mock_get_all.return_value = mock_users

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/users", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            mock_get_all.assert_called_once()

    def test_get_all_users_admin_only(self, store_manager_token):
        """测试获取所有用户仅限管理员"""
        self.test_endpoint_permission_denied(
            "GET", f"{self.base_url}/users", store_manager_token
        )

    def test_update_user_role_success(self, admin_token):
        """测试成功更新用户角色"""
        role_data = {"role": "store_manager"}

        with patch("services.auth_service.change_user_role") as mock_change_role:
            mock_user = {"id": 1, "role": "store_manager"}
            mock_change_role.return_value = (mock_user, None)

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/users/1/role", admin_token, role_data
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"]["role"] == "store_manager"
            mock_change_role.assert_called_once_with(1, "store_manager")

    def test_update_user_role_invalid_role(self, admin_token):
        """测试更新为无效角色"""
        role_data = {"role": "invalid_role"}

        with patch("services.auth_service.change_user_role") as mock_change_role:
            mock_change_role.return_value = (None, "无效角色")

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/users/1/role", admin_token, role_data
            )

            self.assert_response_code(response, 400)

    def test_update_user_role_user_not_found(self, admin_token):
        """测试更新不存在用户的角色"""
        role_data = {"role": "employee"}

        with patch("services.auth_service.change_user_role") as mock_change_role:
            mock_change_role.return_value = (None, "用户不存在")

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/users/999/role", admin_token, role_data
            )

            self.assert_response_code(response, 404)

    def test_update_user_role_admin_only(self, employee_token):
        """测试更新用户角色仅限管理员"""
        role_data = {"role": "employee"}
        self.test_endpoint_permission_denied(
            "PUT", f"{self.base_url}/users/1/role", employee_token
        )

    def test_delete_user_success(self, admin_token):
        """测试成功删除用户"""
        with patch("controllers.auth_controller.delete_user") as mock_delete_user:
            mock_delete_user.return_value = (
                {"id": 1, "phone": "13800000001", "name": "用户1"},
                None,
            )

            response = self.make_authenticated_request(
                "DELETE", f"{self.base_url}/users/1", admin_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["msg"] == "用户已删除"
            assert json_data["data"]["id"] == 1
            mock_delete_user.assert_called_once_with(1)

    def test_delete_user_not_found(self, admin_token):
        """测试删除不存在用户"""
        with patch("controllers.auth_controller.delete_user") as mock_delete_user:
            mock_delete_user.return_value = (None, "用户不存在")

            response = self.make_authenticated_request(
                "DELETE", f"{self.base_url}/users/999", admin_token
            )

            self.assert_response_code(response, 404)
            json_data = self.assert_api_error(response, 404)
            assert "不存在" in json_data["msg"]

    def test_delete_user_self(self, admin_token):
        """测试禁止删除自己"""
        response = self.make_authenticated_request(
            "DELETE", f"{self.base_url}/users/1", admin_token
        )

        self.assert_response_code(response, 403)
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert json_data["code"] == 403
        assert "不能删除自己" in json_data["msg"]

    def test_delete_user_admin_only(self, employee_token):
        """测试删除用户仅限管理员"""
        self.test_endpoint_permission_denied(
            "DELETE", f"{self.base_url}/users/1", employee_token
        )
