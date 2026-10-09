"""基础测试类"""

import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseTestCase(ABC):
    """基础测试类，提供通用的测试方法"""

    @abstractmethod
    def get_client(self):
        """获取测试客户端"""
        pass

    def make_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict] = None,
    ):
        """发起HTTP请求的通用方法"""
        client = self.get_client()

        if data and not files:
            data = json.dumps(data)
            if not headers:
                headers = {}
            headers.setdefault("Content-Type", "application/json")

        if method.upper() == "GET":
            return client.get(url, headers=headers)
        elif method.upper() == "POST":
            if files:
                return client.post(url, data=data, headers=headers, **files)
            return client.post(url, data=data, headers=headers)
        elif method.upper() == "PUT":
            return client.put(url, data=data, headers=headers)
        elif method.upper() == "DELETE":
            return client.delete(url, data=data, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

    def assert_response_code(self, response, expected_code: int):
        """断言响应状态码"""
        assert (
            response.status_code == expected_code
        ), f"Expected {expected_code}, got {response.status_code}. Response: {response.get_json()}"

    def assert_response_success(self, response):
        """断言响应成功(状态码200)"""
        self.assert_response_code(response, 200)

    def assert_response_json(self, response, expected_keys: list = None):
        """断言响应为JSON格式并包含指定键"""
        assert response.is_json, "Response is not JSON"
        json_data = response.get_json()
        assert json_data is not None, "Response JSON is None"

        if expected_keys:
            for key in expected_keys:
                assert key in json_data, f"Key '{key}' not found in response"

        return json_data

    def assert_api_success(self, response, expected_keys: list = None):
        """断言API成功响应（code=200）"""
        self.assert_response_success(response)
        json_data = self.assert_response_json(response, ["code"])
        assert json_data["code"] == 200, f"API response code is {json_data['code']}"

        if expected_keys:
            for key in expected_keys:
                assert key in json_data, f"Key '{key}' not found in API response"

        return json_data

    def assert_api_error(self, response, expected_code: int):
        """断言API错误响应"""
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert (
            json_data["code"] == expected_code
        ), f"Expected error code {expected_code}, got {json_data['code']}"

        return json_data

    def make_authenticated_request(
        self,
        method: str,
        url: str,
        token: str,
        data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        """发起认证请求"""
        headers = {"x-token": token}
        if extra_headers:
            headers.update(extra_headers)

        return self.make_request(method, url, data, headers)


class BaseControllerTest(BaseTestCase):
    """控制器测试基类"""

    def get_client(self):
        """获取测试客户端，子类应通过fixture设置self.client"""
        return getattr(self, "client", None)


class BaseServiceTest(BaseTestCase):
    """服务测试基类"""

    def get_client(self):
        # 服务层测试不需要HTTP客户端
        return None


class APITestMixin:
    """API测试混入类，提供常用的API测试方法"""

    def assert_endpoint_requires_auth(
        self, method: str, url: str, expected_code: int = 401
    ):
        """测试端点需要认证"""
        response = self.make_request(method, url)
        self.assert_response_code(response, expected_code)

    def assert_endpoint_rejects_invalid_token(self, method: str, url: str):
        """测试端点使用无效token"""
        headers = {"x-token": "invalid_token"}
        response = self.make_request(method, url, headers=headers)
        self.assert_response_code(response, 401)

    def assert_endpoint_permission_denied(
        self, method: str, url: str, token: str, expected_code: int = 403
    ):
        """测试端点权限不足"""
        response = self.make_authenticated_request(method, url, token)
        self.assert_response_code(response, expected_code)


class DatabaseTestMixin:
    """数据库测试混入类"""

    def assert_record_exists(self, model, identifier):
        """断言记录存在"""
        record = model.read(identifier)
        assert record is not None, f"Record with identifier {identifier} not found"
        return record

    def assert_record_not_exists(self, model, identifier):
        """断言记录不存在"""
        record = model.read(identifier)
        assert record is None, f"Record with identifier {identifier} should not exist"

    def assert_record_field_equals(self, model, identifier, field: str, expected_value):
        """断言记录字段值"""
        record = self.assert_record_exists(model, identifier)
        actual_value = record.get(field)
        assert (
            actual_value == expected_value
        ), f"Field '{field}' expected {expected_value}, got {actual_value}"


class FileTestMixin:
    """文件测试混入类"""

    def create_test_file(self, content: bytes, filename: str = "test.txt"):
        """创建测试文件"""
        from io import BytesIO

        file_obj = BytesIO(content)
        file_obj.name = filename
        return file_obj

    def create_test_excel_file(self, data: list, filename: str = "test.xlsx"):
        """创建测试Excel文件"""
        import pandas as pd
        from io import BytesIO

        df = pd.DataFrame(data)
        buffer = BytesIO()
        df.to_excel(buffer, index=False)
        buffer.seek(0)
        buffer.name = filename
        return buffer

    def create_test_txt_file(self, lines: list, filename: str = "test.txt"):
        """创建测试文本文件"""
        content = "\n".join(lines).encode("utf-8")
        return self.create_test_file(content, filename)
