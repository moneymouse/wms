"""认证服务层测试"""

import pytest
from unittest.mock import patch, Mock

from services.auth_service import (
    register_user,
    login_user,
    approve_user,
    reject_user,
    change_user_role,
    delete_user,
)
from data.user import ROLES
from tests.base import BaseServiceTest, DatabaseTestMixin
from tests.factories import UserFactory, AuthFactory


@pytest.mark.unit
@pytest.mark.service
@pytest.mark.auth
class TestAuthService(BaseServiceTest, DatabaseTestMixin):
    """认证服务测试"""

    def test_register_user_success(self):
        """测试成功注册用户"""
        user_data = UserFactory.create_user_data()

        with patch("data.user.user_model.get_by_phone", return_value=None), patch(
            "data.user.user_model.create"
        ) as mock_create:

            mock_user = {
                "id": 1,
                "phone": user_data["phone"],
                "name": user_data["name"],
                "status": "pending",
            }
            mock_create.return_value = mock_user

            user, error = register_user(
                user_data["phone"], user_data["name"], user_data["password"]
            )

            assert error is None
            assert user == mock_user
            mock_create.assert_called_once()

    def test_register_user_empty_fields(self):
        """测试注册时字段为空"""
        # 测试手机号为空
        user, error = register_user("", "测试用户", "password")
        assert user is None
        assert "不能为空" in error

        # 测试姓名为空
        user, error = register_user("13800000001", "", "password")
        assert user is None
        assert "不能为空" in error

        # 测试密码为空
        user, error = register_user("13800000001", "测试用户", "")
        assert user is None
        assert "不能为空" in error

    def test_register_user_phone_exists(self):
        """测试手机号已注册"""
        user_data = UserFactory.create_user_data()

        with patch("data.user.user_model.get_by_phone", return_value={"id": 1}):
            user, error = register_user(
                user_data["phone"], user_data["name"], user_data["password"]
            )

            assert user is None
            assert "已注册" in error

    def test_login_user_success(self):
        """测试成功登录"""
        user_data = UserFactory.create_user_data()
        mock_user = {
            "id": 1,
            "phone": user_data["phone"],
            "name": user_data["name"],
            "password": "hashed_password",
            "role": "salesperson",
            "roles": ["salesperson"],
            "status": "approved",
        }

        with patch(
            "services.auth_service.user_model.get_by_phone", return_value=mock_user
        ), patch("services.auth_service.check_password", return_value=True), patch(
            "services.auth_service.create_jwt", return_value="test_token"
        ):

            token, safe_user, error = login_user(
                user_data["phone"], user_data["password"]
            )

            assert error is None
            assert token == "test_token"
            assert safe_user["id"] == 1
            assert "password" not in safe_user

    def test_login_user_with_multiple_roles(self):
        """测试多角色登录载荷"""
        user_data = UserFactory.create_user_data()
        mock_user = {
            "id": 1,
            "phone": user_data["phone"],
            "name": user_data["name"],
            "password": "hashed_password",
            "role": "salesperson",
            "roles": ["salesperson", "clerk"],
            "status": "approved",
        }

        with patch(
            "services.auth_service.user_model.get_by_phone", return_value=mock_user
        ), patch("services.auth_service.check_password", return_value=True), patch(
            "services.auth_service.create_jwt", return_value="test_token"
        ) as mock_create_jwt:
            token, safe_user, error = login_user(
                user_data["phone"], user_data["password"]
            )

            assert error is None
            assert token == "test_token"
            assert safe_user["role"] == "salesperson"
            assert safe_user["roles"] == ["salesperson", "clerk"]
            jwt_payload = mock_create_jwt.call_args.args[0]
            assert jwt_payload["role"] == "salesperson"
            assert jwt_payload["roles"] == ["salesperson", "clerk"]

    def test_login_user_empty_credentials(self):
        """测试登录时凭据为空"""
        # 测试手机号为空
        token, user, error = login_user("", "password")
        assert token is None
        assert user is None
        assert "不能为空" in error

        # 测试密码为空
        token, user, error = login_user("13800000001", "")
        assert token is None
        assert user is None
        assert "不能为空" in error

    def test_login_user_wrong_credentials(self):
        """测试错误的登录凭据"""
        # 用户不存在
        with patch("data.user.user_model.get_by_phone", return_value=None):
            token, user, error = login_user("13800000001", "password")
            assert token is None
            assert user is None
            assert "密码错误" in error

        # 密码错误
        mock_user = {"password": "hashed_password"}
        with patch("data.user.user_model.get_by_phone", return_value=mock_user), patch(
            "Auth.check_password", return_value=False
        ):
            token, user, error = login_user("13800000001", "wrong_password")
            assert token is None
            assert user is None
            assert "密码错误" in error

    def test_login_user_pending_status(self):
        """测试登录待审核用户"""
        mock_user = {"password": "hashed_password", "status": "pending"}

        with patch(
            "services.auth_service.user_model.get_by_phone", return_value=mock_user
        ), patch("services.auth_service.check_password", return_value=True):
            token, user, error = login_user("13800000001", "password")
            assert token is None
            assert user is None
            assert "审核" in error

    def test_login_user_rejected_status(self):
        """测试登录被拒绝用户"""
        mock_user = {
            "password": "hashed_password",
            "status": "rejected",
            "remark": "不符合要求",
        }

        with patch(
            "services.auth_service.user_model.get_by_phone", return_value=mock_user
        ), patch("services.auth_service.check_password", return_value=True):
            token, user, error = login_user("13800000001", "password")
            assert token is None
            assert user is None
            assert "审核未通过" in error
            assert "不符合要求" in error

    def test_approve_user_success(self):
        """测试成功审核用户"""
        mock_role = Mock()
        mock_role.name = "salesperson"
        mock_updated_user = {"id": 1, "role": "salesperson", "status": "approved"}

        with patch(
            "services.auth_service.user_model.get_by_id", return_value={"id": 1}
        ), patch(
            "services.auth_service.role_model.get_by_names", return_value=[mock_role]
        ), patch(
            "services.auth_service.user_model.approve", return_value=mock_updated_user
        ) as mock_approve:

            updated, error = approve_user(1, "salesperson", "admin")

            assert error is None
            assert updated == mock_updated_user
            mock_approve.assert_called_once_with(user_id=1, role_objects=[mock_role])

    def test_approve_user_invalid_role(self):
        """测试审核时使用无效角色"""
        updated, error = approve_user(1, "invalid_role", "admin")

        assert updated is None
        assert "无效角色" in error

    def test_approve_user_not_found(self):
        """测试审核不存在的用户"""
        with patch("services.auth_service.user_model.get_by_id", return_value=None):
            updated, error = approve_user(999, "salesperson", "admin")

            assert updated is None
            assert "不存在" in error

    def test_approve_user_store_manager_cannot_assign_admin(self):
        """测试店长不能分配管理员角色"""
        with patch(
            "services.auth_service.user_model.get_by_id", return_value={"id": 1}
        ):
            updated, error = approve_user(1, "admin", "store_manager")

            assert updated is None
            assert "无法分配管理员角色" in error

    def test_approve_user_with_multiple_roles(self):
        """测试审核用户分配多角色"""
        mock_role1 = Mock()
        mock_role1.name = "salesperson"
        mock_role2 = Mock()
        mock_role2.name = "clerk"
        mock_updated_user = {
            "id": 1,
            "role": "salesperson",
            "roles": ["salesperson", "clerk"],
            "status": "approved",
        }
        with patch(
            "services.auth_service.user_model.get_by_id", return_value={"id": 1}
        ), patch(
            "services.auth_service.role_model.get_by_names",
            return_value=[mock_role1, mock_role2],
        ), patch(
            "services.auth_service.user_model.approve", return_value=mock_updated_user
        ) as mock_approve:
            updated, error = approve_user(1, ["salesperson", "clerk"], ["admin"])

            assert error is None
            assert updated == mock_updated_user
            mock_approve.assert_called_once_with(
                user_id=1, role_objects=[mock_role1, mock_role2]
            )

    def test_reject_user_success(self):
        """测试成功拒绝用户"""
        mock_updated_user = {"id": 1, "status": "rejected", "remark": "不符合要求"}

        with patch(
            "services.auth_service.user_model.get_by_id", return_value={"id": 1}
        ), patch(
            "services.auth_service.user_model.reject", return_value=mock_updated_user
        ):

            updated, error = reject_user(1, "不符合要求")

            assert error is None
            assert updated == mock_updated_user

    def test_reject_user_not_found(self):
        """测试拒绝不存在的用户"""
        with patch("services.auth_service.user_model.get_by_id", return_value=None):
            updated, error = reject_user(999, "不符合要求")

            assert updated is None
            assert "不存在" in error

    def test_change_user_role_success(self):
        """测试成功修改用户角色"""
        mock_role = Mock()
        mock_role.name = "store_manager"
        mock_updated_user = {"id": 1, "role": "store_manager"}

        with patch(
            "services.auth_service.user_model.get_by_id", return_value={"id": 1}
        ), patch(
            "services.auth_service.role_model.get_by_names", return_value=[mock_role]
        ), patch(
            "services.auth_service.user_model.update_role",
            return_value=mock_updated_user,
        ) as mock_update_role:

            updated, error = change_user_role(1, "store_manager")

            assert error is None
            assert updated == mock_updated_user
            mock_update_role.assert_called_once_with(user_id=1, role_objects=[mock_role])

    def test_change_user_role_invalid_role(self):
        """测试修改为无效角色"""
        updated, error = change_user_role(1, "invalid_role")

        assert updated is None
        assert "无效角色" in error

    def test_change_user_role_user_not_found(self):
        """测试修改不存在用户的角色"""
        with patch("services.auth_service.user_model.get_by_id", return_value=None):
            updated, error = change_user_role(999, "salesperson")

            assert updated is None
            assert "不存在" in error

    def test_delete_user_success(self):
        """测试成功删除用户"""
        mock_user = {"id": 1, "phone": "13800000001", "name": "测试用户"}
        with patch(
            "services.auth_service.user_model.get_by_id", return_value=mock_user
        ), patch("services.auth_service.user_model.delete") as mock_delete:
            deleted, error = delete_user(1)

            assert error is None
            assert deleted == mock_user
            mock_delete.assert_called_once_with(1)

    def test_delete_user_not_found(self):
        """测试删除不存在用户"""
        with patch("services.auth_service.user_model.get_by_id", return_value=None):
            deleted, error = delete_user(999)

            assert deleted is None
            assert "不存在" in error
