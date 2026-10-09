"""货物控制器测试 - 第二部分（Excel和文件上传功能）"""

import pytest
import json
from unittest.mock import patch, Mock, MagicMock, mock_open
from io import BytesIO
from werkzeug.datastructures import FileStorage

from tests.base import BaseControllerTest, APITestMixin, FileTestMixin
from tests.factories import FileFactory
from services.outbound_service import WaybillImportResult


def _waybill_result(pairs):
    return WaybillImportResult(
        registered=pairs,
        successful=[
            {"uid": uid, "order_uid": "order1", "order_id": "ORDER001",
             "transfer_id": f"TR{index:03}", "waybill_id": waybill_id}
            for index, (uid, waybill_id) in enumerate(pairs, start=1)
        ],
    )


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.cargo
class TestCargoControllerPart2(BaseControllerTest, APITestMixin, FileTestMixin):
    """货物控制器测试 - Excel和文件上传功能"""

    def __init__(self, client):
        super().__init__(client)
        self.base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client

    def test_download_excel_success(self, employee_token):
        """测试成功下载Excel文件"""
        document_id = "test_document"

        with patch("flask.send_file") as mock_send_file:
            mock_send_file.return_value = "fake_file_response"

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/cargo/excel/{document_id}", employee_token
            )

            # 由于我们mock了send_file，实际上不会返回文件
            mock_send_file.assert_called_once_with(
                f"excels/{document_id}.xlsx", mimetype="application/vnd.ms-excel"
            )

    def test_generate_excel_jifei_mode_success(self, employee_token):
        """测试生成极飞模式Excel"""
        request_data = {
            "uid_list": ["uid1", "uid2"],
            "cargo_list": ["cargo1", "cargo2"],
        }

        with patch("services.cargo_service.generate_excel") as mock_generate:
            mock_generate.return_value = ("document_123", None, False)

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/excel/jifei",
                employee_token,
                request_data,
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"]["document_id"] == "document_123"
            mock_generate.assert_called_once()

    def test_generate_excel_kehu_mode_plain_text(self, employee_token):
        """测试生成客户模式返回纯文本"""
        request_data = {"uid_list": ["uid1"], "cargo_list": None}

        with patch("services.cargo_service.generate_excel") as mock_generate:
            mock_generate.return_value = ("张三(测试公司)\nWB001\nWB002", None, True)

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/excel/kehu",
                employee_token,
                request_data,
            )

            # kehu模式返回纯文本，不是JSON
            self.assert_response_code(response, 200)
            assert "张三(测试公司)" in response.get_data(as_text=True)

    def test_generate_excel_invalid_mode(self, employee_token):
        """测试无效的Excel模式"""
        request_data = {"uid_list": ["uid1"]}

        response = self.make_authenticated_request(
            "POST",
            f"{self.base_url}/cargo/excel/invalid_mode",
            employee_token,
            request_data,
        )

        self.assert_response_code(response, 200)
        json_data = self.assert_response_json(response, ["code", "reason"])
        assert json_data["code"] == 404
        assert "mode not found" in json_data["reason"]

    def test_generate_excel_empty_uid_list(self, employee_token):
        """测试空的UID列表"""
        request_data = {"uid_list": []}

        response = self.make_authenticated_request(
            "POST", f"{self.base_url}/cargo/excel/jifei", employee_token, request_data
        )

        json_data = self.assert_api_success(response)
        assert json_data["code"] == 200

    def test_generate_excel_service_error(self, employee_token):
        """测试Excel生成服务错误"""
        request_data = {"uid_list": ["uid1"]}

        with patch("services.cargo_service.generate_excel") as mock_generate:
            mock_generate.return_value = (None, "生成Excel文件失败", False)

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/excel/jifei",
                employee_token,
                request_data,
            )

            self.assert_response_code(response, 200)
            json_data = self.assert_response_json(response, ["code", "msg"])
            assert json_data["code"] == 500
            assert "生成Excel文件失败" in json_data["msg"]

    def test_generate_excel_all_valid_modes(self, employee_token):
        """测试所有有效的Excel模式"""
        valid_modes = [
            "jifei",
            "tongcang",
            "huanshitong",
            "jinfeiqi",
            "jinlong",
            "xinghang",
            "tongcangups",
            "yaxuan",
            "kehu",
            "jinlong_kuaidi",
            "WE",
        ]

        request_data = {"uid_list": ["uid1"]}

        for mode in valid_modes:
            with patch("services.cargo_service.generate_excel") as mock_generate:
                mock_generate.return_value = (f"document_{mode}", None, False)

                response = self.make_authenticated_request(
                    "POST",
                    f"{self.base_url}/cargo/excel/{mode}",
                    employee_token,
                    request_data,
                )

                if mode == "kehu":
                    # kehu模式特殊处理
                    continue
                else:
                    json_data = self.assert_api_success(response, ["data"])
                    assert "document_id" in json_data["data"]

    def test_upload_waybill_txt_success(self, clerk_token):
        """测试成功上传txt格式转运单"""
        waybill_data = FileFactory.create_waybill_data(3)
        txt_content = FileFactory.create_waybill_txt_content(waybill_data)

        # 创建文件对象
        file_obj = BytesIO(txt_content.encode("utf-8"))
        file_storage = FileStorage(
            stream=file_obj, filename="waybill.txt", content_type="text/plain"
        )

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply:

            transfer_map = {
                item["transfer_id"]: item["waybill_id"] for item in waybill_data
            }
            mock_parse.return_value = transfer_map
            mock_apply.return_value = (
                _waybill_result([("cargo1", "WB001"), ("cargo2", "WB002")]), None
            )

            # 使用client直接发送multipart/form-data请求
            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": file_storage, "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            json_data = self.assert_api_success(
                response, ["cargo_count", "cargo_list", "success_list"]
            )
            assert json_data["msg"] == "success"
            assert json_data["cargo_count"] == 2
            assert json_data["cargo_list"] == transfer_map
            assert json_data["success_list"] == [["cargo1", "WB001"], ["cargo2", "WB002"]]
            assert json_data["success_items"] == mock_apply.return_value[0].successful
            assert json_data["failed_list"] == []
            assert json_data["tracking_error"] is None
            assert mock_apply.call_args.kwargs["return_details"] is True

    def test_upload_waybill_excel_success(self, clerk_token):
        """测试成功上传Excel格式转运单"""
        waybill_data = FileFactory.create_waybill_data(2)

        # 创建Excel文件对象
        excel_data = FileFactory.create_waybill_excel_data(waybill_data)
        file_obj = self.create_test_excel_file(excel_data, "waybill.xlsx")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply:

            transfer_map = {
                item["transfer_id"]: item["waybill_id"] for item in waybill_data
            }
            mock_parse.return_value = transfer_map
            mock_apply.return_value = (_waybill_result([("cargo1", "WB001")]), None)

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.xlsx"), "filename": "waybill.xlsx"},
                headers={"x-token": clerk_token},
            )

            json_data = self.assert_api_success(
                response, ["cargo_count", "cargo_list", "success_list"]
            )

    def test_upload_waybill_17track_error(self, clerk_token):
        """测试上传转运单时17track错误"""
        file_obj = BytesIO(b"TR001,WB001")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply:

            mock_parse.return_value = {"TR001": "WB001"}
            # 模拟17track 502错误
            error = Exception()
            error.args = [{"code": 502, "data": ["rejected_item"]}]
            mock_apply.return_value = (_waybill_result([("cargo1", "WB001")]), error)

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            self.assert_response_code(response, 200)
            json_data = self.assert_response_json(response, ["code", "msg", "rejected"])
            assert json_data["code"] == 502
            assert "17track rejected" in json_data["msg"]
            assert "rejected_item" in json_data["rejected"]
            assert json_data["cargo_count"] == 1
            assert json_data["success_items"] == mock_apply.return_value[0].successful
            assert json_data["failed_list"] == []
            assert json_data["tracking_error"] == {"code": 502, "reason": "17track rejected"}

    def test_upload_waybill_general_error(self, clerk_token):
        """测试上传转运单时一般错误"""
        file_obj = BytesIO(b"TR001,WB001")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply:

            mock_parse.return_value = {"TR001": "WB001"}
            # 模拟一般错误
            mock_apply.return_value = (
                _waybill_result([("cargo1", "WB001")]),
                Exception("General Error"),
            )

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            self.assert_response_code(response, 200)
            json_data = self.assert_response_json(response, ["code", "msg"])
            assert json_data["code"] == 500
            assert "Register Error" in json_data["msg"]
            assert json_data["cargo_count"] == 1
            assert json_data["success_items"] == mock_apply.return_value[0].successful
            assert json_data["failed_list"] == []
            assert json_data["tracking_error"] == {"code": 500, "reason": "Register Error"}

    def test_upload_waybill_parse_value_error_returns_standard_json(self, clerk_token):
        """测试解析格式错误时返回标准接口错误"""
        file_obj = BytesIO(b"bad content")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse:
            mock_parse.side_effect = ValueError("文件格式不正确")

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            self.assert_response_code(response, 400)
            json_data = self.assert_response_json(
                response, ["code", "msg", "cargo_count", "success_list", "cargo_list"]
            )
            assert json_data["code"] == 400
            assert json_data["msg"] == "文件格式不正确"
            assert json_data["cargo_count"] == 0
            assert json_data["success_list"] == []
            assert json_data["cargo_list"] == {}

    def test_upload_waybill_missing_filename_returns_standard_json(self, clerk_token):
        """测试缺少filename字段时返回标准接口错误"""
        file_obj = BytesIO(b"TR001,WB001")

        response = self.client.post(
            f"{self.base_url}/order/upload/transfer_table",
            data={"file": (file_obj, "waybill.txt")},
            headers={"x-token": clerk_token},
        )

        self.assert_response_code(response, 400)
        json_data = self.assert_response_json(
            response, ["code", "msg", "cargo_count", "success_list", "cargo_list"]
        )
        assert json_data["code"] == 400
        assert json_data["msg"] == "文件名不能为空"
        assert json_data["cargo_count"] == 0
        assert json_data["success_list"] == []
        assert json_data["cargo_list"] == {}

    def test_upload_waybill_db_value_error_returns_standard_json(self, clerk_token):
        """测试DB/Service层业务错误时返回标准接口错误"""
        file_obj = BytesIO(b"TR001,WB001")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply:
            mock_parse.return_value = {"TR001": "WB001"}
            mock_apply.side_effect = ValueError("Outbound box waybill cannot be modified")

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            self.assert_response_code(response, 400)
            json_data = self.assert_response_json(
                response, ["code", "msg", "cargo_count", "success_list", "cargo_list"]
            )
            assert json_data["code"] == 400
            assert "Outbound box waybill cannot be modified" in json_data["msg"]
            assert json_data["cargo_count"] == 0
            assert json_data["success_list"] == []
            assert json_data["cargo_list"] == {"TR001": "WB001"}

    def test_upload_waybill_unexpected_error_returns_standard_json(self, clerk_token):
        """测试未知异常时返回标准接口错误"""
        file_obj = BytesIO(b"TR001,WB001")

        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse:
            mock_parse.side_effect = RuntimeError("unexpected failure")

            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            self.assert_response_code(response, 500)
            json_data = self.assert_response_json(
                response, ["code", "msg", "cargo_count", "success_list", "cargo_list"]
            )
            assert json_data["code"] == 500
            assert "上传转单号失败" in json_data["msg"]
            assert json_data["cargo_count"] == 0
            assert json_data["success_list"] == []
            assert json_data["cargo_list"] == {}

    def test_upload_waybill_invalid_mode(self, clerk_token):
        """测试无效的上传模式"""
        file_obj = BytesIO(b"test content")

        response = self.client.post(
            f"{self.base_url}/order/upload/invalid_mode",
            data={"file": (file_obj, "test.txt"), "filename": "test.txt"},
            headers={"x-token": clerk_token},
        )

        self.assert_response_code(response, 404)

    def test_cargo_endpoints_require_auth(self):
        """测试所有货物端点都需要认证"""
        endpoints = [
            ("GET", f"{self.base_url}/orders/test_uid/cargo"),
            ("GET", f"{self.base_url}/cargo"),
            ("DELETE", f"{self.base_url}/cargo"),
            ("PUT", f"{self.base_url}/cargo/test_uid"),
            ("POST", f"{self.base_url}/cargo/test_uid/input"),
            ("GET", f"{self.base_url}/cargo/excel/test_doc"),
            ("POST", f"{self.base_url}/cargo/excel/jifei"),
            ("POST", f"{self.base_url}/order/upload/transfer_table"),
        ]

        # 不需要认证的端点
        no_auth_endpoints = [
            ("POST", f"{self.base_url}/cargo/test_uid/output"),
            ("GET", f"{self.base_url}/cargo/pdf/cargo1_cargo2"),
        ]

        for method, url in endpoints:
            with self.client:
                if method == "POST" and "upload" in url:
                    # 文件上传端点需要特殊处理
                    response = self.client.post(
                        url, data={"file": (BytesIO(b"test"), "test.txt")}
                    )
                elif method in ["POST", "PUT", "DELETE"]:
                    response = self.make_request(method, url, {"test": "data"})
                else:
                    response = self.make_request(method, url)

                if method == "POST" and "upload" in url:
                    # 文件上传可能返回不同的错误码
                    assert response.status_code in [401, 403, 422]
                else:
                    self.assert_response_code(response, 401)

        # 测试不需要认证的端点
        for method, url in no_auth_endpoints:
            with self.client:
                if method == "POST":
                    response = self.make_request(method, url, {"test": "data"})
                else:
                    response = self.make_request(method, url)

                # 这些端点应该返回200或其他非401状态码
                assert response.status_code != 401


@pytest.mark.unit
@pytest.mark.controller
@pytest.mark.cargo
class TestWaybillImportResponses(BaseControllerTest):
    base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client

    @pytest.mark.parametrize("has_success", [True, False])
    def test_upload_waybill_reports_failed_orders(self, clerk_token, has_success):
        """部分成功保留成功明细，全部失败则返回HTTP 400。"""
        result = _waybill_result([("cargo1", "WB001")] if has_success else [])
        result.failed = [{
            "uid": "cargo2", "order_uid": "order2", "order_id": "ORDER002",
            "transfer_id": "TR002", "waybill_id": "WB002", "code": 400,
            "reason": "箱子与订单的客户归属不一致",
        }]
        transfer_map = {"TR001": "WB001", "TR002": "WB002"}
        with patch("controllers.cargo_controller.parse_waybill_file", return_value=transfer_map), patch(
            "controllers.cargo_controller.apply_waybill_table", return_value=(result, None)
        ):
            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (BytesIO(b"TR001,WB001"), "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )
        self.assert_response_code(response, 200 if has_success else 400)
        body = self.assert_response_json(response)
        assert body["code"] == (207 if has_success else 400)
        assert body["cargo_count"] == int(has_success)
        assert body["success_list"] == ([["cargo1", "WB001"]] if has_success else [])
        assert body["success_items"] == result.successful
        assert body["failed_list"] == result.failed
        assert body["cargo_list"] == transfer_map
        assert body["tracking_error"] is None

    def test_upload_waybill_counts_unchanged_successes(self, clerk_token):
        """同号重复上传计入成功，但无须重新登记追踪。"""
        result = _waybill_result([("cargo1", "WB001")])
        result.registered = []
        with patch("controllers.cargo_controller.parse_waybill_file", return_value={"TR001": "WB001"}), patch(
            "controllers.cargo_controller.apply_waybill_table", return_value=(result, None)
        ):
            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (BytesIO(b"TR001,WB001"), "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )
        body = self.assert_api_success(response)
        assert body["cargo_count"] == 1
        assert body["success_list"] == [["cargo1", "WB001"]]
        assert body["success_items"] == result.successful
        assert body["failed_list"] == []

    @pytest.mark.parametrize("error_code", [502, 500])
    def test_partial_import_preserves_failures_when_tracking_fails(self, clerk_token, error_code):
        result = _waybill_result([("cargo1", "WB001")])
        result.failed = [{
            "uid": "cargo2", "order_uid": "order2", "order_id": "ORDER002",
            "transfer_id": "TR002", "waybill_id": "WB002", "code": 400,
            "reason": "箱子与订单的客户归属不一致",
        }]
        error = Exception({"code": 502, "data": ["rejected_item"]}) if error_code == 502 else Exception("API Error")
        with patch("controllers.cargo_controller.parse_waybill_file", return_value={"TR001": "WB001", "TR002": "WB002"}), patch(
            "controllers.cargo_controller.apply_waybill_table", return_value=(result, error)
        ):
            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (BytesIO(b"TR001,WB001"), "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )
        self.assert_response_code(response, 200)
        body = self.assert_response_json(response)
        assert body["code"] == error_code
        assert body["cargo_count"] == 1
        assert body["success_list"] == [["cargo1", "WB001"]]
        assert body["success_items"] == result.successful
        assert body["failed_list"] == result.failed
        assert body["tracking_error"] == {
            "code": error_code, "reason": "17track rejected" if error_code == 502 else "Register Error",
        }
