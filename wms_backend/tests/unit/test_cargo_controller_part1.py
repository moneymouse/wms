"""货物控制器测试 - 第一部分"""

import pytest
import json
from unittest.mock import patch, Mock, MagicMock
from io import BytesIO

from tests.base import (
    BaseControllerTest,
    APITestMixin,
    DatabaseTestMixin,
    FileTestMixin,
)
from tests.factories import OrderFactory, CargoFactory, FileFactory


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.cargo
class TestCargoController(
    BaseControllerTest, APITestMixin, DatabaseTestMixin, FileTestMixin
):
    """货物控制器测试"""

    def __init__(self, client):
        super().__init__(client)
        self.base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client

    def test_get_cargo_list_success(self, employee_token):
        """测试成功获取货物列表"""
        mock_cargo_list = [
            CargoFactory.create_cargo_data(),
            CargoFactory.create_cargo_data(),
        ]

        with patch("services.cargo_service.get_cargo_with_tracking") as mock_get_cargo:
            mock_get_cargo.return_value = (mock_cargo_list, None)

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/test_uid/cargo", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2
            mock_get_cargo.assert_called_once()

    def test_get_cargo_list_order_not_found(self, employee_token):
        """测试订单不存在"""
        with patch("services.cargo_service.get_cargo_with_tracking") as mock_get_cargo:
            mock_get_cargo.return_value = (None, "Order Not Found")

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/nonexistent_uid/cargo", employee_token
            )

            self.assert_response_code(response, 404)
            json_data = self.assert_api_error(response, 404)
            assert "Order Not Found" in json_data["msg"]

    def test_get_cargo_list_tracking_error(self, employee_token):
        """测试追踪查询错误"""
        mock_cargo_list = [CargoFactory.create_cargo_data()]

        with patch("services.cargo_service.get_cargo_with_tracking") as mock_get_cargo:
            mock_get_cargo.return_value = (mock_cargo_list, "Get Track Error")

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/test_uid/cargo", employee_token
            )

            self.assert_response_code(response, 200)
            json_data = self.assert_response_json(response, ["code", "msg", "data"])
            assert json_data["code"] == 500
            assert "Get Track Error" in json_data["msg"]
            assert len(json_data["data"]) == 1

    def test_get_all_cargo_ids_success(self, employee_token):
        """测试获取所有货物ID"""
        mock_orders = [
            OrderFactory.create_order_data(
                uid="uid1", cargo_uid_list=["cargo1", "cargo2"]
            ),
            OrderFactory.create_order_data(uid="uid2", cargo_uid_list=["cargo3"]),
        ]
        mock_cargos = [
            {"transfer_id": "TR001", "waybill_id": "WB001"},
            {"transfer_id": "TR002", "waybill_id": "WB002"},
            {"transfer_id": "TR003", "waybill_id": "WB003"},
        ]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "data.cargo_model.read", side_effect=mock_cargos
        ):

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/cargo", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            assert "uid1" in json_data["data"]
            assert "uid2" in json_data["data"]
            assert len(json_data["data"]["uid1"]) == 2
            assert len(json_data["data"]["uid2"]) == 1

    def test_get_all_cargo_ids_with_none_cargo(self, employee_token):
        """测试包含不存在货物的情况"""
        mock_orders = [
            OrderFactory.create_order_data(cargo_uid_list=["cargo1", "nonexistent"])
        ]

        with patch("data.order_model.read", return_value=mock_orders), patch(
            "data.cargo_model.read",
            side_effect=[
                {"transfer_id": "TR001", "waybill_id": "WB001"},
                None,  # nonexistent cargo
            ],
        ):

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/cargo", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            # 应该跳过不存在的货物
            assert len(json_data["data"][mock_orders[0]["uid"]]) == 1

    def test_delete_cargo_success(self, employee_token):
        """测试成功删除货物"""
        delete_data = {"cargo_id_list": ["cargo1", "cargo2", "cargo3"]}

        with patch("data.cargo_model.delete") as mock_delete:
            response = self.make_authenticated_request(
                "DELETE", f"{self.base_url}/cargo", employee_token, delete_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"

            # 验证每个货物都被删除
            assert mock_delete.call_count == 3
            mock_delete.assert_any_call("cargo1")
            mock_delete.assert_any_call("cargo2")
            mock_delete.assert_any_call("cargo3")

    def test_update_cargo_success(self, employee_token):
        """测试成功更新货物"""
        update_data = {"transfer_id": "TR002", "weight": 2.5}
        mock_old_cargo = {"waybill_id": "WB001"}

        with patch("data.cargo_model.read", return_value=mock_old_cargo), patch(
            "data.cargo_model.update"
        ) as mock_update, patch(
            "services.cargo_service.background_register"
        ) as mock_bg_register:

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/cargo/test_uid", employee_token, update_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_update.assert_called_once_with("test_uid", update_data)
            # 运单号没有变化，不应该触发后台注册
            mock_bg_register.assert_not_called()

    def test_update_cargo_with_new_waybill(self, employee_token):
        """测试更新货物运单号"""
        update_data = {"waybill_id": "WB002"}
        mock_old_cargo = {"waybill_id": "WB001"}

        with patch("data.cargo_model.read", return_value=mock_old_cargo), patch(
            "data.cargo_model.update"
        ) as mock_update, patch(
            "services.cargo_service.background_register"
        ) as mock_bg_register:

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/cargo/test_uid", employee_token, update_data
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_update.assert_called_once_with("test_uid", update_data)
            # 运单号变化了，应该触发后台注册
            mock_bg_register.assert_called_once_with("test_uid", "WB002")

    def test_update_cargo_new_waybill_same_as_old(self, employee_token):
        """测试更新相同运单号"""
        update_data = {"waybill_id": "WB001"}
        mock_old_cargo = {"waybill_id": "WB001"}

        with patch("data.cargo_model.read", return_value=mock_old_cargo), patch(
            "data.cargo_model.update"
        ) as mock_update, patch(
            "services.cargo_service.background_register"
        ) as mock_bg_register:

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/cargo/test_uid", employee_token, update_data
            )

            json_data = self.assert_api_success(response)
            mock_bg_register.assert_not_called()  # 运单号相同，不触发注册

    def test_output_cargo_success(self, employee_token):
        """测试货物出货"""
        mock_cargo = CargoFactory.create_cargo_data(origin_id="TEST001-1")
        mock_order = {"customer_name": "测试客户"}

        with patch("data.cargo_model.update") as mock_update, patch(
            "data.cargo_model.read", return_value=mock_cargo
        ), patch("data.order_model.read", return_value=mock_order), patch(
            "time.strftime", return_value="2023-01-01 10:00"
        ):

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/cargo/test_uid/output", employee_token
            )

            json_data = self.assert_api_success(response, ["data"])
            # 验证状态更新为已发货
            mock_update.assert_called_once()
            update_args = mock_update.call_args[0][1]
            assert update_args["status"] == 1
            assert update_args["date"] == "2023-01-01 10:00"

            # 验证返回数据包含客户名
            assert "customer_name" in json_data["data"]

    def test_record_cargo_input_success(self, employee_token):
        """测试成功录入货物属性"""
        input_data = {"weight": 2.5, "count": 3}

        with patch("data.cargo_model.update") as mock_update:
            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/test_uid/input",
                employee_token,
                input_data,
            )

            json_data = self.assert_api_success(response)
            assert json_data["msg"] == "success"
            mock_update.assert_called_once_with("test_uid", input_data)

    def test_record_cargo_input_missing_params(self, employee_token):
        """测试录入货物属性缺少参数"""
        # 缺少重量
        input_data = {"count": 3}

        response = self.make_authenticated_request(
            "POST", f"{self.base_url}/cargo/test_uid/input", employee_token, input_data
        )

        self.assert_response_code(response, 200)
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert json_data["code"] == 404
        assert "lack param" in json_data["msg"]

        # 缺少件数
        input_data = {"weight": 2.5}

        response = self.make_authenticated_request(
            "POST", f"{self.base_url}/cargo/test_uid/input", employee_token, input_data
        )

        self.assert_response_code(response, 200)
        json_data = self.assert_response_json(response, ["code", "msg"])
        assert json_data["code"] == 404

    def test_download_cargo_pdf_success(self, employee_token):
        """测试下载货物PDF"""
        mock_cargo = CargoFactory.create_cargo_data(origin_id="TEST001-1", tag="TEST_1")
        mock_order = OrderFactory.create_order_data(receiver="测试收件人")

        with patch("data.cargo_model.read", return_value=mock_cargo), patch(
            "data.order_model.read", return_value=mock_order
        ), patch("PDF.PDF") as mock_pdf_class:

            mock_pdf = Mock()
            mock_pdf.get_bytes_io.return_value = BytesIO(b"fake pdf content")
            mock_pdf_class.return_value = mock_pdf

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/cargo/pdf/cargo1_cargo2", employee_token
            )

            self.assert_response_code(response, 200)
            assert response.mimetype == "application/pdf"

            # 验证PDF渲染调用
            assert mock_pdf.render.called

    def test_download_cargo_pdf_with_none_cargo(self, employee_token):
        """测试下载PDF时包含不存在的货物"""
        mock_cargo = CargoFactory.create_cargo_data()
        mock_order = OrderFactory.create_order_data()

        with patch("data.cargo_model.read", side_effect=[mock_cargo, None]), patch(
            "data.order_model.read", return_value=mock_order
        ), patch("PDF.PDF") as mock_pdf_class:

            mock_pdf = Mock()
            mock_pdf.get_bytes_io.return_value = BytesIO(b"fake pdf content")
            mock_pdf_class.return_value = mock_pdf

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/cargo/pdf/cargo1_nonexistent", employee_token
            )

            self.assert_response_code(response, 200)
            # 应该只渲染存在的货物
            assert mock_pdf.render.call_count == 1
