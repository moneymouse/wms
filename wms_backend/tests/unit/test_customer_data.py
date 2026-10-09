"""测试客户数据层敏感信息管理功能"""

import pytest
from data.customer.Customer import (
    filter_sensitive_fields,
    SENSITIVE_FIELDS,
    ALLOWED_ROLES,
)


class TestFilterSensitiveFields:
    """测试敏感字段过滤功能"""

    def test_allowed_role_sees_all_fields(self):
        """测试允许的角色可以看到所有字段"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }

        # 测试所有允许的角色
        for role in ALLOWED_ROLES:
            result = filter_sensitive_fields(data, role)
            assert "phone" in result, f"角色{role}应该能看到phone字段"
            assert "wechat" in result, f"角色{role}应该能看到wechat字段"
            assert result["phone"] == "13912345678"
            assert result["wechat"] == "wx_test"

    def test_disallowed_role_filters_sensitive(self):
        """测试不允许的角色看不到敏感字段"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }

        # 测试不允许的角色
        for role in ["clerk", "finance", "employee"]:
            result = filter_sensitive_fields(data, role)
            assert "phone" not in result, f"角色{role}不应该能看到phone字段"
            assert "wechat" not in result, f"角色{role}不应该能看到wechat字段"
            assert "id" in result, f"角色{role}应该能看到普通字段id"
            assert "name" in result, f"角色{role}应该能看到普通字段name"

    def test_none_role_filters_sensitive(self):
        """测试None角色看不到敏感字段"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }
        result = filter_sensitive_fields(data, None)

        assert "phone" not in result, "None角色不应该能看到phone字段"
        assert "wechat" not in result, "None角色不应该能看到wechat字段"
        assert "id" in result
        assert "name" in result

    def test_empty_role_filters_sensitive(self):
        """测试空字符串角色看不到敏感字段"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }
        result = filter_sensitive_fields(data, "")

        assert "phone" not in result
        assert "wechat" not in result

    def test_filter_does_not_modify_original(self):
        """测试过滤不会修改原始数据"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }
        original_keys = set(data.keys())

        filter_sensitive_fields(data, "clerk")

        # 原始数据不应该被修改
        assert set(data.keys()) == original_keys
        assert "phone" in data
        assert "wechat" in data

    def test_sensitive_fields_constant(self):
        """测试敏感字段常量是否正确定义"""
        assert "phone" in SENSITIVE_FIELDS
        assert "wechat" in SENSITIVE_FIELDS

    def test_allowed_roles_constant(self):
        """测试允许的角色常量是否正确定义"""
        assert "admin" in ALLOWED_ROLES
        assert "store_manager" in ALLOWED_ROLES
        assert "salesperson" in ALLOWED_ROLES
        # clerk和finance不应该在允许的角色列表中
        assert "clerk" not in ALLOWED_ROLES
        assert "finance" not in ALLOWED_ROLES

    def test_filter_with_missing_sensitive_fields(self):
        """测试过滤不包含敏感字段的数据"""
        data = {"id": 1, "name": "测试客户"}

        # 即使数据中没有敏感字段，也不应该报错
        result_allowed = filter_sensitive_fields(data, "admin")
        result_denied = filter_sensitive_fields(data, "clerk")

        # 两种情况都应该只包含原有字段
        assert "id" in result_allowed
        assert "name" in result_allowed
        assert "id" in result_denied
        assert "name" in result_denied

    def test_filter_with_empty_data(self):
        """测试过滤空数据"""
        data = {}

        result = filter_sensitive_fields(data, "admin")
        assert result == {}

        result = filter_sensitive_fields(data, "clerk")
        assert result == {}

    def test_filter_preserves_non_sensitive_fields(self):
        """测试过滤保留非敏感字段"""
        data = {
            "id": 1,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
            "extra_field": "额外数据",
            "another_field": 123,
        }

        result = filter_sensitive_fields(data, "clerk")

        # 敏感字段被移除
        assert "phone" not in result
        assert "wechat" not in result
        # 其他字段保留
        assert result["id"] == 1
        assert result["name"] == "测试客户"
        assert result["extra_field"] == "额外数据"
        assert result["another_field"] == 123
