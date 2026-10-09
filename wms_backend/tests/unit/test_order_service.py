"""订单服务层测试"""

import pytest
from unittest.mock import Mock, patch

from services.order_service import filter_orders, sort_orders
from tests.base import BaseServiceTest
from tests.factories import OrderFactory, CargoFactory


@pytest.mark.unit
@pytest.mark.service
@pytest.mark.order
class TestOrderService(BaseServiceTest):
    """订单服务测试"""

    def test_filter_orders_empty_query(self):
        """测试空查询条件"""
        orders = [OrderFactory.create_order_data(), OrderFactory.create_order_data()]
        mock_cargo_model = Mock()

        result = filter_orders(orders, "", mock_cargo_model)

        assert result == orders
        assert len(result) == 2

    def test_filter_orders_by_order_field(self):
        """测试按订单字段过滤"""
        orders = [
            OrderFactory.create_order_data(customer_name="测试客户A"),
            OrderFactory.create_order_data(customer_name="测试客户B"),
            OrderFactory.create_order_data(customer_name="其他客户"),
        ]
        mock_cargo_model = Mock()

        result = filter_orders(orders, "测试客户", mock_cargo_model)

        assert len(result) == 2
        assert all("测试客户" in order["customer_name"] for order in result)

    def test_filter_orders_by_cargo_transfer_id(self):
        """测试按货物转运号过滤"""
        orders = [
            OrderFactory.create_order_data(cargo_uid_list=["cargo1", "cargo2"]),
            OrderFactory.create_order_data(cargo_uid_list=["cargo3"]),
        ]

        mock_cargo_model = Mock()
        mock_cargo_model.read.side_effect = [
            {"transfer_id": "TR001", "waybill_id": "WB001"},  # cargo1
            {"transfer_id": "TR002", "waybill_id": "WB002"},  # cargo2
            {"transfer_id": "TR003", "waybill_id": "WB003"},  # cargo3
        ]

        result = filter_orders(orders, "TR001", mock_cargo_model)

        assert len(result) == 1
        assert result[0]["cargo_uid_list"] == ["cargo1", "cargo2"]

    def test_filter_orders_by_cargo_waybill_id(self):
        """测试按货物运单号过滤"""
        orders = [
            OrderFactory.create_order_data(cargo_uid_list=["cargo1"]),
            OrderFactory.create_order_data(cargo_uid_list=["cargo2"]),
        ]

        mock_cargo_model = Mock()
        mock_cargo_model.read.side_effect = [
            {"transfer_id": "TR001", "waybill_id": "WB001"},  # cargo1
            {"transfer_id": "TR002", "waybill_id": "WB002"},  # cargo2
        ]

        result = filter_orders(orders, "WB002", mock_cargo_model)

        assert len(result) == 1
        assert result[0]["cargo_uid_list"] == ["cargo2"]

    def test_filter_orders_multiline_keywords(self):
        """测试多行关键词过滤"""
        orders = [
            OrderFactory.create_order_data(cargo_uid_list=["cargo1"]),
            OrderFactory.create_order_data(cargo_uid_list=["cargo2"]),
            OrderFactory.create_order_data(cargo_uid_list=["cargo3"]),
        ]

        mock_cargo_model = Mock()
        mock_cargo_model.read.side_effect = [
            {"transfer_id": "TR001", "waybill_id": "WB001"},  # cargo1
            {"transfer_id": "TR002", "waybill_id": "WB002"},  # cargo2
            {"transfer_id": "TR003", "waybill_id": "WB003"},  # cargo3
        ]

        # 多行关键词：TR001和WB002
        result = filter_orders(orders, "TR001\nWB002", mock_cargo_model)

        assert len(result) == 2

    def test_filter_orders_cargo_not_found(self):
        """测试货物不存在的情况"""
        orders = [OrderFactory.create_order_data(cargo_uid_list=["nonexistent_cargo"])]

        mock_cargo_model = Mock()
        mock_cargo_model.read.return_value = None

        result = filter_orders(orders, "TR001", mock_cargo_model)

        assert len(result) == 0

    def test_filter_orders_none_values(self):
        """测试None值的处理"""
        orders = [OrderFactory.create_order_data(cargo_uid_list=["cargo1"])]

        mock_cargo_model = Mock()
        mock_cargo_model.read.return_value = {"transfer_id": None, "waybill_id": None}

        result = filter_orders(orders, "TR001", mock_cargo_model)

        assert len(result) == 0

    def test_sort_orders_empty_field(self):
        """测试空排序字段"""
        orders = [OrderFactory.create_order_data(), OrderFactory.create_order_data()]

        result = sort_orders(orders, "", 1)

        assert result == orders

    def test_sort_orders_by_string_field_asc(self):
        """测试按字符串字段升序排序"""
        orders = [
            OrderFactory.create_order_data(customer_name="C客户"),
            OrderFactory.create_order_data(customer_name="A客户"),
            OrderFactory.create_order_data(customer_name="B客户"),
        ]

        result = sort_orders(orders, "customer_name", 0)

        assert result[0]["customer_name"] == "A客户"
        assert result[1]["customer_name"] == "B客户"
        assert result[2]["customer_name"] == "C客户"

    def test_sort_orders_by_string_field_desc(self):
        """测试按字符串字段降序排序"""
        orders = [
            OrderFactory.create_order_data(customer_name="A客户"),
            OrderFactory.create_order_data(customer_name="C客户"),
            OrderFactory.create_order_data(customer_name="B客户"),
        ]

        result = sort_orders(orders, "customer_name", 1)

        assert result[0]["customer_name"] == "C客户"
        assert result[1]["customer_name"] == "B客户"
        assert result[2]["customer_name"] == "A客户"

    def test_sort_orders_by_numeric_field(self):
        """测试按数字字段排序"""
        orders = [
            OrderFactory.create_order_data(cargo_count=5),
            OrderFactory.create_order_data(cargo_count=1),
            OrderFactory.create_order_data(cargo_count=3),
        ]

        # cargo_count is an Integer field in OrderTable, so no patch needed
        result = sort_orders(orders, "cargo_count", 0)  # 升序

        assert result[0]["cargo_count"] == 1
        assert result[1]["cargo_count"] == 3
        assert result[2]["cargo_count"] == 5

    def test_sort_orders_by_date_field(self):
        """测试按日期字段排序"""
        orders = [
            OrderFactory.create_order_data(order_date="2023-01-03 10:00"),
            OrderFactory.create_order_data(order_date="2023-01-01 10:00"),
            OrderFactory.create_order_data(order_date="2023-01-02 10:00"),
        ]

        result = sort_orders(orders, "order_date", 0)  # 升序

        assert result[0]["order_date"] == "2023-01-01 10:00"
        assert result[1]["order_date"] == "2023-01-02 10:00"
        assert result[2]["order_date"] == "2023-01-03 10:00"

    def test_sort_orders_by_date_field_different_formats(self):
        """测试按不同日期格式排序"""
        orders = [
            OrderFactory.create_order_data(create_date="2023-01-03"),
            OrderFactory.create_order_data(create_date="2023-01-01"),
            OrderFactory.create_order_data(create_date="2023-01-02"),
        ]

        result = sort_orders(orders, "create_date", 0)  # 升序

        assert result[0]["create_date"] == "2023-01-01"
        assert result[1]["create_date"] == "2023-01-02"
        assert result[2]["create_date"] == "2023-01-03"

    def test_sort_orders_with_none_values(self):
        """测试包含None值的排序"""
        orders = [
            OrderFactory.create_order_data(cargo_count=5),
            OrderFactory.create_order_data(cargo_count=None),
            OrderFactory.create_order_data(cargo_count=3),
        ]

        # cargo_count is an Integer field in OrderTable, so no patch needed
        result = sort_orders(orders, "cargo_count", 0)  # 升序

        # None值在升序时返回inf，排在最后
        assert result[0]["cargo_count"] == 3
        assert result[1]["cargo_count"] == 5
        assert result[2]["cargo_count"] is None

    def test_sort_orders_invalid_numeric_conversion(self):
        """测试无效数字转换的处理"""
        orders = [
            OrderFactory.create_order_data(cargo_count="invalid"),
            OrderFactory.create_order_data(cargo_count=5),
            OrderFactory.create_order_data(cargo_count=1),
        ]

        # cargo_count is an Integer field in OrderTable, so no patch needed
        result_asc = sort_orders(orders, "cargo_count", 0)  # 升序
        result_desc = sort_orders(orders, "cargo_count", 1)  # 降序

        # 无效值转换float失败，升序返回inf排在最后，降序返回-inf排在最后
        assert result_asc[0]["cargo_count"] == 1
        assert result_asc[1]["cargo_count"] == 5
        assert result_asc[2]["cargo_count"] == "invalid"

        assert result_desc[0]["cargo_count"] == 5
        assert result_desc[1]["cargo_count"] == 1
        assert result_desc[2]["cargo_count"] == "invalid"

    def test_sort_orders_invalid_date_format(self):
        """测试无效日期格式的处理"""
        orders = [
            OrderFactory.create_order_data(order_date="invalid_date"),
            OrderFactory.create_order_data(order_date="2023-01-01 10:00"),
            OrderFactory.create_order_data(order_date="2023-01-02 10:00"),
        ]

        result = sort_orders(orders, "order_date", 0)  # 升序

        # 无效日期应该被转换为0时间戳，排在最前面
        assert result[0]["order_date"] == "invalid_date"
        assert result[1]["order_date"] == "2023-01-01 10:00"
        assert result[2]["order_date"] == "2023-01-02 10:00"
