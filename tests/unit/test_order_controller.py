"""订单控制器测试"""

import pytest
import json
from unittest.mock import patch, Mock

from tests.base import BaseControllerTest, APITestMixin, DatabaseTestMixin
from tests.factories import OrderFactory, CargoFactory
from data import RecordExist
from data.database import SessionFactory
from data.DB import OrderQuoteVersionTable, OrderTable
from utils.log import OperationLogTable, SessionFactory as LogSessionFactory


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.order
class TestOrderController(BaseControllerTest, APITestMixin, DatabaseTestMixin):
    """订单控制器测试"""

    def __init__(self, client):
        super().__init__(client)
        self.base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client

    def test_create_order_success(self, employee_token):
        """测试成功创建订单"""
        order_data = OrderFactory.create_test_order_data()

        with patch("data.add_customer_record") as mock_add_customer, patch(
            "data.order_model.create"
        ) as mock_create, patch("time.strftime", return_value="2023-01-01 10:00"):

            mock_create.return_value = "order_uid"

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/create", employee_token, order_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"

            # 验证调用
            mock_add_customer.assert_called_once_with(order_data)
            expected_data = order_data.copy()
            expected_data["order_date"] = "2023-01-01 10:00"
            mock_create.assert_called_once_with(expected_data)

    def test_create_order_logs_operator_identity(self, employee_token):
        """测试创建订单时会记录操作者姓名和角色"""
        order_data = OrderFactory.create_test_order_data()

        with patch("data.add_customer_record"), patch(
            "data.order_model.create"
        ) as mock_create, patch("time.strftime", return_value="2023-01-01 10:00"):
            mock_create.return_value = "order_uid"

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/create", employee_token, order_data
            )

            self.assert_api_success(response)

        session = LogSessionFactory()
        try:
            log_entry = (
                session.query(OperationLogTable)
                .order_by(OperationLogTable.id.desc())
                .first()
            )
            assert log_entry is not None
            assert log_entry.user_name == "员工测试"
            assert log_entry.user_role == "employee"
            assert log_entry.desc == "Create order."
        finally:
            session.close()

    def test_create_order_record_exists(self, employee_token):
        """测试创建重复订单"""
        order_data = OrderFactory.create_test_order_data()

        with patch("data.add_customer_record"), patch(
            "data.order_model.create", side_effect=RecordExist()
        ):

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/create", employee_token, order_data
            )

            self.assert_response_code(response, 200)
            json_data = self.assert_response_json(response, ["code", "msg"])
            assert json_data["code"] == 500
            assert json_data["msg"] == "Record Existed"

    def test_create_order_requires_auth(self):
        """测试创建订单需要认证"""
        order_data = OrderFactory.create_test_order_data()
        self.test_endpoint_requires_auth("POST", f"{self.base_url}/create")

    def test_get_order_list_success(self, employee_token):
        """测试获取订单列表"""
        mock_orders = [
            OrderFactory.create_order_data(order_id="ORD001"),
            OrderFactory.create_order_data(order_id="ORD002"),
        ]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "services.order_service.filter_orders", return_value=mock_orders
        ), patch("services.order_service.sort_orders", return_value=mock_orders):

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders", employee_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert len(json_data["data"]) == 2
            assert json_data["total"] == 2

    def test_get_order_list_with_pagination(self, employee_token):
        """测试分页获取订单列表"""
        mock_orders = [OrderFactory.create_order_data() for _ in range(5)]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "services.order_service.filter_orders", return_value=mock_orders
        ), patch("services.order_service.sort_orders", return_value=mock_orders):

            # 第2页，每页2条
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders?p=2&s=2", employee_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            assert len(json_data["data"]) == 2  # 第2页应该有2条记录
            assert json_data["total"] == 5

    def test_get_order_list_with_query(self, employee_token):
        """测试带查询条件的订单列表"""
        mock_orders = [OrderFactory.create_order_data()]
        filtered_orders = [mock_orders[0]]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "services.order_service.filter_orders", return_value=filtered_orders
        ) as mock_filter, patch(
            "services.order_service.sort_orders", return_value=filtered_orders
        ):

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders?q=测试", employee_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            mock_filter.assert_called_once()
            filter_args = mock_filter.call_args[0]
            assert filter_args[1] == "测试"  # 查询参数

    def test_get_order_list_with_sorting(self, employee_token):
        """测试带排序的订单列表"""
        mock_orders = [OrderFactory.create_order_data()]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "services.order_service.filter_orders", return_value=mock_orders
        ), patch(
            "services.order_service.sort_orders", return_value=mock_orders
        ) as mock_sort:

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders?sf=order_id&so=1", employee_token
            )

            json_data = self.assert_api_success(response, ["data", "total"])
            mock_sort.assert_called_once()
            sort_args = mock_sort.call_args[0]
            assert sort_args[1] == "order_id"  # 排序字段
            assert sort_args[2] == 1  # 排序顺序

    def test_get_single_order_success(self, employee_token):
        """测试获取单个订单"""
        mock_order = OrderFactory.create_order_data()

        with patch("data.order_model.read", return_value=mock_order) as mock_read:
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/test_uid", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"] == mock_order
            mock_read.assert_called_once_with("test_uid")

    def test_update_order_success(self, employee_token):
        """测试成功更新订单"""
        update_data = {"receiver": "新收件人", "address": "新地址"}

        with patch("data.order_model.update") as mock_update:
            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/orders/test_uid", employee_token, update_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_update.assert_called_once_with("test_uid", update_data)

    def test_create_quote_without_configured_transportation_uses_zero_min_price(
        self, salesperson_token
    ):
        """测试未维护渠道成本时仍可按最低报价0提交报价"""
        session = SessionFactory()
        try:
            order = OrderTable(
                uid="quote-order-no-mode",
                order_id="ORDER-NO-MODE",
                customer_name="测试客户",
                transportation="未维护渠道",
                salesman_id=3,
                archive=False,
                create_date="2023-01-01 10:00",
            )
            session.add(order)
            session.commit()
        finally:
            session.close()

        response = self.make_authenticated_request(
            "POST",
            f"{self.base_url}/orders/quote-order-no-mode/quotes",
            salesperson_token,
            {"quoted_price": 12.5, "quote_remark": "测试报价"},
        )

        json_data = self.assert_api_success(response, ["data"])
        assert json_data["msg"] == "报价已采纳"
        assert json_data["data"]["transportation_mode_id"] is None
        assert json_data["data"]["transportation_name"] == "未维护渠道"
        assert json_data["data"]["channel_cost"] == 0
        assert json_data["data"]["min_price"] == 0
        assert json_data["data"]["quoted_price"] == 12.5
        assert json_data["data"]["status"] == "adopted"
        assert json_data["data"]["is_final"] is True

        session = SessionFactory()
        try:
            quote = (
                session.query(OrderQuoteVersionTable)
                .filter(OrderQuoteVersionTable.order_uid == "quote-order-no-mode")
                .first()
            )
            assert quote is not None
            assert quote.transportation_mode_id is None
            assert quote.min_price == 0
        finally:
            session.close()

    def test_delete_single_order_success(self, employee_token):
        """测试成功删除单个订单"""
        with patch("data.order_model.delete") as mock_delete:
            response = self.make_authenticated_request(
                "DELETE", f"{self.base_url}/orders/test_uid", employee_token
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_delete.assert_called_once_with("test_uid")

    def test_delete_multiple_orders_success(self, employee_token):
        """测试成功批量删除订单"""
        delete_data = {"uid_list": ["uid1", "uid2", "uid3"]}

        with patch("data.order_model.delete") as mock_delete:
            response = self.make_authenticated_request(
                "DELETE", f"{self.base_url}/orders", employee_token, delete_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"

            # 验证每个UID都被删除
            assert mock_delete.call_count == 3
            mock_delete.assert_any_call("uid1")
            mock_delete.assert_any_call("uid2")
            mock_delete.assert_any_call("uid3")

    def test_add_cargo_to_order_success(self, employee_token):
        """测试成功为订单添加包裹"""
        mock_order = OrderFactory.create_order_data(
            cargo_count=2, cargo_uid_list=["cargo1", "cargo2"]
        )
        mock_new_cargo = CargoFactory.create_cargo_data()
        add_cargo_data = {"cargo_count": 2}

        with patch(
            "data.order_model.read", return_value=mock_order
        ) as mock_read, patch("data.order_model.update") as mock_update, patch(
            "data.cargo_model.create", return_value="new_cargo_uid"
        ) as mock_create_cargo, patch(
            "data.cargo_model.read", return_value=mock_new_cargo
        ) as mock_read_cargo:

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/orders/test_uid/add_cargo",
                employee_token,
                add_cargo_data,
            )

            json_data = self.assert_api_success(response, ["data", "cargo_id_list"])
            assert len(json_data["data"]) == 2  # 添加了2个包裹
            assert len(json_data["cargo_id_list"]) == 4  # 总共4个包裹

            # 验证订单货物数量更新
            update_calls = mock_update.call_args_list
            assert any(
                call_args[0][1]["cargo_count"] == 4 for call_args in update_calls
            )

    def test_add_cargo_invalid_count(self, employee_token):
        """测试添加无效数量的包裹"""
        add_cargo_data = {"cargo_count": 0}

        response = self.make_authenticated_request(
            "POST",
            f"{self.base_url}/orders/test_uid/add_cargo",
            employee_token,
            add_cargo_data,
        )

        self.assert_response_code(response, 200)
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert json_data["code"] == 404
        assert "should larger than 0" in json_data["msg"]

    def test_add_cargo_negative_count(self, employee_token):
        """测试添加负数包裹"""
        add_cargo_data = {"cargo_count": -1}

        response = self.make_authenticated_request(
            "POST",
            f"{self.base_url}/orders/test_uid/add_cargo",
            employee_token,
            add_cargo_data,
        )

        self.assert_response_code(response, 200)
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert json_data["code"] == 404

    def test_add_cargo_with_existing_cargo(self, employee_token):
        """测试为已有包裹的订单添加包裹"""
        mock_order = OrderFactory.create_order_data(
            cargo_count=1,
            cargo_uid_list=["existing_cargo"],
            order_id="TEST001",
            tag_all="TEST",
        )
        mock_new_cargo = CargoFactory.create_cargo_data()
        add_cargo_data = {"cargo_count": 1}

        with patch("data.order_model.read", return_value=mock_order), patch(
            "data.order_model.update"
        ), patch("data.cargo_model.create", return_value="new_cargo_uid"), patch(
            "data.cargo_model.read", return_value=mock_new_cargo
        ):

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/orders/test_uid/add_cargo",
                employee_token,
                add_cargo_data,
            )

            json_data = self.assert_api_success(response, ["data", "cargo_id_list"])
            # 新包裹的origin_id应该是TEST001-2（因为已有1个包裹）
            # 新包裹的tag应该是TEST_2

    def test_order_endpoints_require_auth(self):
        """测试所有订单端点都需要认证"""
        endpoints = [
            ("POST", f"{self.base_url}/create"),
            ("GET", f"{self.base_url}/orders"),
            ("GET", f"{self.base_url}/orders/test_uid"),
            ("PUT", f"{self.base_url}/orders/test_uid"),
            ("DELETE", f"{self.base_url}/orders/test_uid"),
            ("DELETE", f"{self.base_url}/orders"),
            ("POST", f"{self.base_url}/orders/test_uid/add_cargo"),
        ]

        for method, url in endpoints:
            with self.client:  # 确保每个测试都有独立的请求上下文
                self.test_endpoint_requires_auth(method, url)
