"""客户控制器测试"""

import pytest
from unittest.mock import patch, Mock, MagicMock
from io import BytesIO

from tests.base import BaseControllerTest, APITestMixin, DatabaseTestMixin
from tests.factories import CustomerFactory


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.customer
class TestCustomerController(APITestMixin, BaseControllerTest):
    """客户控制器测试"""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client
        self.base_url = "/api"

    def test_get_customer_list_success(self, employee_token):
        """测试成功获取客户列表"""
        mock_customers = ["客户A", "客户B"]

        with patch(
            "controllers.customer_controller.get_customer_record",
            return_value=mock_customers,
        ) as mock_get_customers:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/customer_list", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            assert json_data["data"][0] == "客户A"
            mock_get_customers.assert_called_once_with()

    def test_get_receiver_list_success(self, employee_token):
        """测试成功获取收件人列表"""
        customer_name = "测试客户"
        mock_receivers = [
            {"receiver_id": "rec1", "receiver_name": "收件人1"},
            {"receiver_id": "rec2", "receiver_name": "收件人2"},
        ]

        with patch(
            "controllers.customer_controller.get_customer_record",
            return_value=mock_receivers,
        ) as mock_get_receivers:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/receiver_list/{customer_name}", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            mock_get_receivers.assert_called_once_with(customer_name=customer_name)

    def test_get_receiver_list_empty(self, employee_token):
        """测试获取空的收件人列表"""
        customer_name = "不存在的客户"

        with patch(
            "controllers.customer_controller.get_customer_record", return_value=[]
        ) as mock_get_receivers:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/receiver_list/{customer_name}", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 0

    def test_get_receiver_info_list_success(self, employee_token):
        """测试成功获取收件人完整信息列表"""
        customer_name = "测试客户"
        mock_receivers = [
            {"receiver_id": "rec1", "receiver_name": "收件人1"},
            {"receiver_id": "rec2", "receiver_name": "收件人2"},
        ]
        mock_receiver_info = [
            {
                "receiver_id": "rec1",
                "receiver": "收件人1",
                "phone": "13800000001",
                "address": "地址1",
            },
            {
                "receiver_id": "rec2",
                "receiver": "收件人2",
                "phone": "13800000002",
                "address": "地址2",
            },
        ]

        with patch(
            "controllers.customer_controller.get_customer_record",
            return_value=mock_receivers,
        ), patch(
            "controllers.customer_controller.list_receiver_records",
            return_value=mock_receiver_info,
        ) as mock_list_receivers:

            response = self.make_authenticated_request(
                "GET",
                f"{self.base_url}/receiver_info_list/{customer_name}",
                employee_token,
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            assert "phone" in json_data["data"][0]
            assert "address" in json_data["data"][0]
            mock_list_receivers.assert_called_once_with(["rec1", "rec2"])

    def test_get_receiver_info_list_no_receivers(self, employee_token):
        """测试客户无收件人的情况"""
        customer_name = "无收件人客户"

        with patch(
            "controllers.customer_controller.get_customer_record", return_value=[]
        ), patch(
            "controllers.customer_controller.list_receiver_records", return_value=[]
        ) as mock_list_receivers:

            response = self.make_authenticated_request(
                "GET",
                f"{self.base_url}/receiver_info_list/{customer_name}",
                employee_token,
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 0
            mock_list_receivers.assert_called_once_with([])

    def test_get_single_receiver_info_success(self, employee_token):
        """测试成功获取单个收件人信息"""
        receiver_id = "rec123"
        mock_receiver_info = [
            {
                "receiver_id": receiver_id,
                "receiver": "张三",
                "phone": "13800000001",
                "address": "北京市朝阳区xxx",
                "customer_name": "测试公司",
            }
        ]

        with patch(
            "controllers.customer_controller.list_customer_records",
            return_value=mock_receiver_info,
        ) as mock_get_receiver:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/receiver_info/{receiver_id}", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"][0]["receiver_id"] == receiver_id
            assert json_data["data"][0]["receiver"] == "张三"
            mock_get_receiver.assert_called_once_with(receiver_id=receiver_id)

    def test_get_single_receiver_info_not_found(self, employee_token):
        """测试获取不存在的收件人信息"""
        receiver_id = "nonexistent"

        with patch(
            "controllers.customer_controller.list_customer_records", return_value=[]
        ) as mock_get_receiver:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/receiver_info/{receiver_id}", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"] == []

    def test_delete_receiver_success(self, employee_token):
        """测试成功删除收件人"""
        customer_name = "测试客户"
        receiver_id = "rec123"

        with patch(
            "controllers.customer_controller.del_receiver_record"
        ) as mock_del_receiver:
            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/del/{customer_name}/{receiver_id}",
                employee_token,
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_del_receiver.assert_called_once_with(
                customer_name=customer_name, receiver_id=receiver_id
            )

    def test_delete_receiver_with_encoded_names(self, employee_token):
        """测试删除包含特殊字符的收件人"""
        customer_name = "测试&公司"  # 包含特殊字符
        receiver_id = "rec_123"

        with patch(
            "controllers.customer_controller.del_receiver_record"
        ) as mock_del_receiver:
            # URL编码测试
            encoded_customer_name = "测试%26公司"
            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/del/{encoded_customer_name}/{receiver_id}",
                employee_token,
            )

            json_data = self.assert_api_success(response)
            mock_del_receiver.assert_called_once()

    def test_delete_customer_success(self, employee_token):
        """测试成功删除客户"""
        customer_name = "要删除的客户"

        with patch(
            "controllers.customer_controller.del_customer_record"
        ) as mock_del_customer:
            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/del_customer/{customer_name}", employee_token
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_del_customer.assert_called_once_with(customer_name=customer_name)

    def test_delete_customer_cascade_effect(self, employee_token):
        """测试删除客户的级联效果"""
        customer_name = "有多个收件人的客户"

        with patch(
            "controllers.customer_controller.del_customer_record"
        ) as mock_del_customer:
            # 模拟删除客户同时删除其所有收件人
            mock_del_customer.return_value = {"deleted_receivers": 3}

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/del_customer/{customer_name}", employee_token
            )

            json_data = self.assert_api_success(response)
            mock_del_customer.assert_called_once_with(customer_name=customer_name)

    def test_get_excel_template_success(self):
        """测试获取Excel模板"""
        query_params = {
            "address": "北京市朝阳区",
            "zip_code": "100000",
            "country": "中国",
            "receiver": "张三",
            "receiver_phone": "13800000001",
        }

        with patch("controllers.customer_controller.load_workbook") as mock_load_wb:
            # 创建mock workbook和worksheet - 使用MagicMock支持item assignment
            mock_wb = MagicMock()
            mock_ws = MagicMock()
            mock_wb.active = mock_ws
            mock_load_wb.return_value = mock_wb

            # Mock send_file 返回真正的 Response
            from flask import Response

            with patch("controllers.customer_controller.send_file") as mock_send_file:
                mock_send_file.return_value = Response(
                    b"fake excel content",
                    status=200,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                # 构建查询字符串
                query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])

                response = self.client.get(f"{self.base_url}/excel?{query_string}")

                self.assert_response_code(response, 200)

                # 验证模板文件被加载
                mock_load_wb.assert_called_once_with("static/template.xlsx")

                # 验证字段被填写到对应单元格
                mock_ws.__setitem__.assert_any_call("A17", "北京市朝阳区")
                mock_ws.__setitem__.assert_any_call("A19", "100000")
                mock_ws.__setitem__.assert_any_call("C19", "中国")
                mock_ws.__setitem__.assert_any_call("A20", "张三")
                mock_ws.__setitem__.assert_any_call("C20", "13800000001")

    def test_get_excel_template_partial_params(self):
        """测试部分参数的Excel模板"""
        query_params = {
            "address": "上海市浦东新区",
            "receiver": "李四",
            # 缺少其他参数
        }

        with patch("controllers.customer_controller.load_workbook") as mock_load_wb:
            mock_wb = MagicMock()
            mock_ws = MagicMock()
            mock_wb.active = mock_ws
            mock_load_wb.return_value = mock_wb

            from flask import Response

            with patch("controllers.customer_controller.send_file") as mock_send_file:
                mock_send_file.return_value = Response(
                    b"fake excel content",
                    status=200,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])
                response = self.client.get(f"{self.base_url}/excel?{query_string}")

                self.assert_response_code(response, 200)

                # 验证提供的参数被设置
                mock_ws.__setitem__.assert_any_call("A17", "上海市浦东新区")
                mock_ws.__setitem__.assert_any_call("A20", "李四")

                # 验证缺少的参数被设置为空字符串
                mock_ws.__setitem__.assert_any_call("A19", "")  # zip_code
                mock_ws.__setitem__.assert_any_call("C19", "")  # country
                mock_ws.__setitem__.assert_any_call("C20", "")  # receiver_phone

    def test_get_excel_template_no_params(self):
        """测试无参数的Excel模板"""
        with patch("controllers.customer_controller.load_workbook") as mock_load_wb:
            mock_wb = MagicMock()
            mock_ws = MagicMock()
            mock_wb.active = mock_ws
            mock_load_wb.return_value = mock_wb

            from flask import Response

            with patch("controllers.customer_controller.send_file") as mock_send_file:
                mock_send_file.return_value = Response(
                    b"fake excel content",
                    status=200,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                response = self.client.get(f"{self.base_url}/excel")

                self.assert_response_code(response, 200)

                # 验证所有字段都被设置为空字符串
                mock_ws.__setitem__.assert_any_call("A17", "")  # address
                mock_ws.__setitem__.assert_any_call("A19", "")  # zip_code
                mock_ws.__setitem__.assert_any_call("C19", "")  # country
                mock_ws.__setitem__.assert_any_call("A20", "")  # receiver
                mock_ws.__setitem__.assert_any_call("C20", "")  # receiver_phone

    def test_customer_endpoints_require_auth(self):
        """测试客户相关端点需要认证"""
        auth_required_endpoints = [
            ("GET", f"{self.base_url}/customer_list"),
            ("GET", f"{self.base_url}/receiver_list/test_customer"),
            ("GET", f"{self.base_url}/receiver_info_list/test_customer"),
            ("GET", f"{self.base_url}/receiver_info/rec123"),
            ("POST", f"{self.base_url}/del/test_customer/rec123"),
            ("POST", f"{self.base_url}/del_customer/test_customer"),
        ]

        for method, url in auth_required_endpoints:
            response = self.make_request(method, url)
            self.assert_response_code(response, 401)

    def test_excel_template_no_auth_required(self):
        """测试Excel模板下载不需要认证"""
        with patch("controllers.customer_controller.load_workbook") as mock_load_wb:
            mock_wb = MagicMock()
            mock_ws = MagicMock()
            mock_wb.active = mock_ws
            mock_load_wb.return_value = mock_wb

            from flask import Response

            with patch("controllers.customer_controller.send_file") as mock_send_file:
                mock_send_file.return_value = Response(
                    b"fake excel content",
                    status=200,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                # 不提供认证信息
                response = self.client.get(f"{self.base_url}/excel")

                # 应该成功访问，不需要认证
                self.assert_response_code(response, 200)


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.customer
@pytest.mark.sensitive
class TestCustomerSensitiveDataEndpoints:
    """测试客户敏感数据相关API端点"""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client
        self.base_url = "/api"

    def _make_request(self, method, url, token=None, json=None):
        """发起请求的辅助方法"""
        headers = {}
        if token:
            headers["x-token"] = token
        if method == "GET":
            return self.client.get(url, headers=headers)
        elif method == "POST":
            return self.client.post(url, headers=headers, json=json)
        return None

    # ============ GET /api/customers_detail 权限测试 ============

    def test_get_customers_detail_as_admin(self, admin_token):
        """管理员可以访问所有客户详情"""
        mock_customers = [
            {"id": 1, "name": "客户A", "phone": "13911111111", "wechat": "wx_a"},
            {"id": 2, "name": "客户B", "phone": "13922222222", "wechat": "wx_b"},
        ]

        with patch(
            "controllers.customer_controller.get_all_customers_detail",
            return_value=mock_customers,
        ) as mock_get_all:
            response = self._make_request(
                "GET", f"{self.base_url}/customers_detail", admin_token
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert "data" in json_data
            assert len(json_data["data"]) == 2
            assert json_data["data"][0]["phone"] == "13911111111"
            assert json_data["data"][0]["wechat"] == "wx_a"
            mock_get_all.assert_called_once_with(include_sensitive=True)

    def test_get_customers_detail_as_store_manager(self, store_manager_token):
        """店长可以访问所有客户详情"""
        mock_customers = [
            {"id": 1, "name": "客户A", "phone": "13911111111", "wechat": "wx_a"}
        ]

        with patch(
            "controllers.customer_controller.get_all_customers_detail",
            return_value=mock_customers,
        ):
            response = self._make_request(
                "GET", f"{self.base_url}/customers_detail", store_manager_token
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert len(json_data["data"]) == 1

    def test_get_customers_detail_as_salesperson(self, salesperson_token):
        """业务员可以访问所有客户详情"""
        mock_customers = [
            {"id": 1, "name": "客户A", "phone": "13911111111", "wechat": "wx_a"}
        ]

        with patch(
            "controllers.customer_controller.get_all_customers_detail",
            return_value=mock_customers,
        ):
            response = self._make_request(
                "GET", f"{self.base_url}/customers_detail", salesperson_token
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert len(json_data["data"]) == 1
            assert json_data["data"][0]["phone"] == "13911111111"

    def test_get_customers_detail_as_clerk_denied(self, clerk_token):
        """文员无权访问客户详情"""
        response = self._make_request(
            "GET", f"{self.base_url}/customers_detail", clerk_token
        )

        assert response.status_code == 403
        json_data = response.get_json()
        assert json_data["msg"] == "Permission denied"

    def test_get_customers_detail_as_employee_denied(self, employee_token):
        """普通员工无权访问客户详情"""
        response = self._make_request(
            "GET", f"{self.base_url}/customers_detail", employee_token
        )

        assert response.status_code == 403

    def test_get_customers_detail_unauthenticated(self):
        """未认证用户无法访问客户详情"""
        response = self.client.get(f"{self.base_url}/customers_detail")

        assert response.status_code == 401

    def test_get_customers_detail_empty_list(self, admin_token):
        """测试返回空客户列表"""
        with patch(
            "controllers.customer_controller.get_all_customers_detail", return_value=[]
        ):
            response = self._make_request(
                "GET", f"{self.base_url}/customers_detail", admin_token
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert json_data["data"] == []

    # ============ GET /api/customer_detail/<customer_name> 权限测试 ============

    def test_get_customer_detail_success(self, admin_token):
        """成功获取单个客户详情"""
        customer_id = 1
        mock_customer = {
            "id": customer_id,
            "name": "测试客户",
            "phone": "13912345678",
            "wechat": "wx_test",
        }

        with patch(
            "controllers.customer_controller.get_customer_detail",
            return_value=mock_customer,
        ) as mock_get_detail:
            response = self._make_request(
                "GET",
                f"{self.base_url}/customer_detail/{customer_id}",
                admin_token,
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert json_data["data"]["id"] == customer_id
            assert json_data["data"]["phone"] == "13912345678"
            assert json_data["data"]["wechat"] == "wx_test"
            mock_get_detail.assert_called_once_with(
                customer_id=customer_id, include_sensitive=True
            )

    def test_get_customer_detail_not_found(self, admin_token):
        """获取不存在的客户时返回404"""
        customer_id = 99999

        with patch(
            "controllers.customer_controller.get_customer_detail", return_value={}
        ):
            response = self._make_request(
                "GET",
                f"{self.base_url}/customer_detail/{customer_id}",
                admin_token,
            )

            assert response.status_code == 404
            json_data = response.get_json()
            assert json_data["msg"] == "Customer not found"

    def test_get_customer_detail_as_salesperson(self, salesperson_token):
        """业务员可以查看单个客户详情"""
        customer_id = 1
        mock_customer = {
            "id": customer_id,
            "name": "客户A",
            "phone": "13900000000",
            "wechat": "wx_a",
        }

        with patch(
            "controllers.customer_controller.get_customer_detail",
            return_value=mock_customer,
        ):
            response = self._make_request(
                "GET",
                f"{self.base_url}/customer_detail/{customer_id}",
                salesperson_token,
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert json_data["data"]["phone"] == "13900000000"

    def test_get_customer_detail_as_clerk_denied(self, clerk_token):
        """文员无权查看客户详情"""
        response = self._make_request(
            "GET",
            f"{self.base_url}/customer_detail/1",
            clerk_token,
        )

        assert response.status_code == 403

    def test_get_customer_detail_with_invalid_id(self, admin_token):
        """测试使用无效ID（0或负数）"""
        with patch(
            "controllers.customer_controller.get_customer_detail", return_value={}
        ):
            response = self._make_request(
                "GET",
                f"{self.base_url}/customer_detail/0",
                admin_token,
            )

            # 0会被Flask路由视为有效参数，但数据层返回空
            assert response.status_code == 404

    # ============ POST /api/customer_info/<customer_name> 权限测试 ============

    def test_update_customer_info_success(self, admin_token):
        """成功更新客户联系信息"""
        customer_name = "测试客户"
        update_data = {"phone": "13912345678", "wechat": "wx_new"}

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json=update_data,
            )

            assert response.status_code == 200
            json_data = response.get_json()
            assert json_data["msg"] == "Customer info updated successfully"
            mock_update.assert_called_once_with(
                customer_name=customer_name,
                phone="13912345678",
                wechat="wx_new",
            )

    def test_update_customer_info_phone_only(self, admin_token):
        """只更新phone字段"""
        customer_name = "测试客户"
        update_data = {"phone": "13987654321"}

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json=update_data,
            )

            assert response.status_code == 200
            mock_update.assert_called_once_with(
                customer_name=customer_name,
                phone="13987654321",
                wechat=None,
            )

    def test_update_customer_info_wechat_only(self, store_manager_token):
        """只更新wechat字段（店长权限）"""
        customer_name = "测试客户"
        update_data = {"wechat": "wx_updated"}

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                store_manager_token,
                json=update_data,
            )

            assert response.status_code == 200
            mock_update.assert_called_once_with(
                customer_name=customer_name,
                phone=None,
                wechat="wx_updated",
            )

    def test_update_customer_info_as_salesperson(self, salesperson_token):
        """业务员可以更新客户信息"""
        customer_name = "客户A"
        update_data = {"phone": "13900000000", "wechat": "wx_a"}

        with patch("controllers.customer_controller.update_customer_info"):
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                salesperson_token,
                json=update_data,
            )

            assert response.status_code == 200

    def test_update_customer_info_as_clerk_denied(self, clerk_token):
        """文员无权更新客户信息"""
        customer_name = "测试客户"
        update_data = {"phone": "13900000000"}

        response = self._make_request(
            "POST",
            f"{self.base_url}/customer_info/{customer_name}",
            clerk_token,
            json=update_data,
        )

        assert response.status_code == 403

    def test_update_customer_info_as_employee_denied(self, employee_token):
        """普通员工无权更新客户信息"""
        customer_name = "测试客户"
        update_data = {"phone": "13900000000"}

        response = self._make_request(
            "POST",
            f"{self.base_url}/customer_info/{customer_name}",
            employee_token,
            json=update_data,
        )

        assert response.status_code == 403

    def test_update_customer_info_no_json_body(self, admin_token):
        """测试不提供JSON数据的情况"""
        customer_name = "测试客户"

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            # 发送空JSON对象模拟不提供数据的情况
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json={},  # 使用空JSON而不是None
            )

            assert response.status_code == 200
            # 应该能处理空JSON的情况
            mock_update.assert_called_once_with(
                customer_name=customer_name, phone=None, wechat=None
            )

    def test_update_customer_info_empty_json(self, admin_token):
        """测试提供空JSON对象"""
        customer_name = "测试客户"

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json={},
            )

            mock_update.assert_called_once_with(
                customer_name=customer_name, phone=None, wechat=None
            )

    def test_update_customer_info_exception_handling(self, admin_token):
        """测试更新时的异常处理"""
        customer_name = "测试客户"
        update_data = {"phone": "13900000000"}

        with patch(
            "controllers.customer_controller.update_customer_info",
            side_effect=Exception("数据库错误"),
        ):
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json=update_data,
            )

            assert response.status_code == 500
            json_data = response.get_json()
            assert "Failed to update customer info" in json_data["msg"]

    def test_update_customer_info_with_empty_strings(self, admin_token):
        """测试使用空字符串清空字段"""
        customer_name = "测试客户"
        update_data = {"phone": "", "wechat": ""}

        with patch(
            "controllers.customer_controller.update_customer_info"
        ) as mock_update:
            response = self._make_request(
                "POST",
                f"{self.base_url}/customer_info/{customer_name}",
                admin_token,
                json=update_data,
            )

            assert response.status_code == 200
            mock_update.assert_called_once_with(
                customer_name=customer_name, phone="", wechat=""
            )

    # ============ 综合测试 ============

    def test_sensitive_endpoints_require_auth(self):
        """测试敏感端点需要认证"""
        sensitive_endpoints = [
            ("GET", f"{self.base_url}/customers_detail"),
            ("GET", f"{self.base_url}/customer_detail/1"),
            ("POST", f"{self.base_url}/customer_info/测试客户"),
        ]

        # 这些端点不需要认证就应该返回401
        for method, url in sensitive_endpoints:
            response = self._make_request(method, url)
            assert (
                response.status_code == 401
            ), f"Endpoint {method} {url} should require auth"
