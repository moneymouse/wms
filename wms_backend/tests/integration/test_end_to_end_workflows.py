"""端到端集成测试 - 完整工作流程"""

import pytest
import json
from unittest.mock import patch
from io import BytesIO

from tests.base import BaseControllerTest
from tests.factories import AuthFactory, OrderFactory, CargoFactory, FileFactory
from services.outbound_service import WaybillImportResult


@pytest.mark.integration
class TestEndToEndWorkflows(BaseControllerTest):
    """端到端集成测试"""

    def __init__(self, client):
        super().__init__(client)
        self.base_url = "/api"

    @pytest.fixture(autouse=True)
    def setup(self, client):
        """设置测试客户端"""
        self.client = client

    def test_complete_user_registration_and_approval_workflow(self):
        """测试完整的用户注册和审核流程"""
        # 1. 用户注册
        register_data = AuthFactory.create_register_data(
            phone="13900000001", name="新用户", password="newuser123"
        )

        with patch("services.auth_service.register_user") as mock_register, patch(
            "services.auth_service.login_user"
        ) as mock_login, patch(
            "services.auth_service.approve_user"
        ) as mock_approve, patch(
            "data.user.user_model.get_by_status"
        ) as mock_get_pending:

            # Mock注册成功
            mock_user = {
                "id": 1,
                "phone": "13900000001",
                "name": "新用户",
                "status": "pending",
            }
            mock_register.return_value = (mock_user, None)

            response = self.make_request(
                "POST", f"{self.base_url}/auth/register", register_data
            )
            self.assert_api_success(response)

            # 2. 尝试登录（应该失败 - 待审核）
            login_data = AuthFactory.create_login_data("13900000001", "newuser123")
            mock_login.return_value = (None, None, "账号尚未通过审核")

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )
            self.assert_response_code(response, 403)

            # 3. 管理员获取待审核用户列表
            admin_token = "admin_token"
            mock_get_pending.return_value = [mock_user]

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/auth/pending", admin_token
            )
            self.assert_api_success(response, ["data"])

            # 4. 管理员审核通过用户
            approve_data = {"role": "employee"}
            approved_user = {
                "id": 1,
                "phone": "13900000001",
                "name": "新用户",
                "role": "employee",
                "status": "approved",
            }
            mock_approve.return_value = (approved_user, None)

            with patch("Auth.get_token_payload", return_value={"role": "admin"}):
                response = self.make_authenticated_request(
                    "POST", f"{self.base_url}/auth/approve/1", admin_token, approve_data
                )
                self.assert_api_success(response, ["data"])

            # 5. 用户再次登录（应该成功）
            mock_login.return_value = ("user_token", approved_user, None)

            response = self.make_request(
                "POST", f"{self.base_url}/auth/login", login_data
            )
            self.assert_api_success(response, ["token", "user"])

    def test_complete_order_management_workflow(self, employee_token):
        """测试完整的订单管理流程"""
        with patch("data.add_customer_record"), patch(
            "data.order_model.create"
        ) as mock_create_order, patch(
            "data.order_model.read"
        ) as mock_read_order, patch(
            "data.order_model.update"
        ) as mock_update_order, patch(
            "data.cargo_model.create"
        ) as mock_create_cargo, patch(
            "data.cargo_model.read"
        ) as mock_read_cargo, patch(
            "time.strftime", return_value="2023-01-01 10:00"
        ):

            # 1. 创建订单
            order_data = OrderFactory.create_test_order_data()
            mock_order = order_data.copy()
            mock_order["uid"] = "order_uid_123"
            mock_order["cargo_uid_list"] = []
            mock_create_order.return_value = mock_order["uid"]

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/create", employee_token, order_data
            )
            self.assert_api_success(response)

            # 2. 查询订单
            mock_read_order.return_value = mock_order

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/{mock_order['uid']}", employee_token
            )
            self.assert_api_success(response, ["data"])

            # 3. 为订单添加货物
            mock_order_with_cargo = mock_order.copy()
            mock_order_with_cargo["cargo_count"] = 2
            mock_order_with_cargo["cargo_uid_list"] = ["cargo1", "cargo2"]

            mock_read_order.return_value = mock_order_with_cargo
            mock_create_cargo.side_effect = ["cargo1", "cargo2"]
            mock_cargo = CargoFactory.create_cargo_data()
            mock_read_cargo.return_value = mock_cargo

            add_cargo_data = {"cargo_count": 2}

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/orders/{mock_order['uid']}/add_cargo",
                employee_token,
                add_cargo_data,
            )
            self.assert_api_success(response, ["data", "cargo_id_list"])

            # 4. 更新订单信息
            update_data = {"receiver": "新收件人", "address": "新地址"}

            response = self.make_authenticated_request(
                "PUT",
                f"{self.base_url}/orders/{mock_order['uid']}",
                employee_token,
                update_data,
            )
            self.assert_api_success(response)

    def test_complete_cargo_tracking_workflow(self, employee_token):
        """测试完整的货物追踪流程"""
        order_uid = "test_order_uid"
        cargo_uid = "test_cargo_uid"

        with patch(
            "services.cargo_service.get_cargo_with_tracking"
        ) as mock_get_tracking, patch(
            "data.cargo_model.update"
        ) as mock_update_cargo, patch(
            "data.cargo_model.read"
        ) as mock_read_cargo, patch(
            "data.order_model.read"
        ) as mock_read_order, patch(
            "services.cargo_service.background_register"
        ), patch(
            "time.strftime", return_value="2023-01-01 15:00"
        ):

            # 1. 获取货物追踪信息
            mock_cargo_list = [
                CargoFactory.create_cargo_data(
                    waybill_id="WB001", status="in_transit", desc="运输中"
                )
            ]
            mock_get_tracking.return_value = (mock_cargo_list, None)

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/{order_uid}/cargo", employee_token
            )
            self.assert_api_success(response, ["data"])

            # 2. 更新货物运单号
            update_data = {"waybill_id": "WB002", "weight": 2.5}
            mock_old_cargo = {"waybill_id": "WB001"}
            mock_read_cargo.return_value = mock_old_cargo

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/cargo/{cargo_uid}", employee_token, update_data
            )
            self.assert_api_success(response)

            # 3. 录入货物重量和件数
            input_data = {"weight": 3.0, "count": 2}

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/{cargo_uid}/input",
                employee_token,
                input_data,
            )
            self.assert_api_success(response)

            # 4. 货物出货
            mock_cargo = CargoFactory.create_cargo_data(origin_id="TEST001-1")
            mock_order = {"customer_name": "测试客户"}
            mock_read_cargo.return_value = mock_cargo
            mock_read_order.return_value = mock_order

            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/cargo/{cargo_uid}/output", employee_token
            )
            self.assert_api_success(response, ["data"])

    def test_complete_batch_waybill_upload_workflow(self, clerk_token):
        """测试完整的批量运单上传流程"""
        with patch("controllers.cargo_controller.parse_waybill_file") as mock_parse, patch(
            "controllers.cargo_controller.apply_waybill_table"
        ) as mock_apply, patch(
            "controllers.cargo_controller.generate_excel"
        ) as mock_generate_excel, patch(
            "controllers.cargo_controller._get_valid_excel_modes", return_value={"jifei"}
        ):

            # 1. 准备转运单数据
            waybill_data = FileFactory.create_waybill_data(3)
            transfer_map = {
                item["transfer_id"]: item["waybill_id"] for item in waybill_data
            }
            txt_content = FileFactory.create_waybill_txt_content(waybill_data)

            # 2. 上传转运单文件
            mock_parse.return_value = transfer_map
            mock_apply.return_value = (
                WaybillImportResult(
                    registered=[("cargo1", "WB001"), ("cargo2", "WB002")],
                    successful=[
                        {"uid": "cargo1", "order_uid": "order1", "order_id": "ORDER001",
                         "transfer_id": "TR001", "waybill_id": "WB001"},
                        {"uid": "cargo2", "order_uid": "order2", "order_id": "ORDER002",
                         "transfer_id": "TR002", "waybill_id": "WB002"},
                    ],
                ),
                None,
            )

            file_obj = BytesIO(txt_content.encode("utf-8"))
            response = self.client.post(
                f"{self.base_url}/order/upload/transfer_table",
                data={"file": (file_obj, "waybill.txt"), "filename": "waybill.txt"},
                headers={"x-token": clerk_token},
            )

            json_data = self.assert_api_success(
                response, ["cargo_count", "cargo_list", "success_list"]
            )
            assert json_data["cargo_count"] == 2
            assert json_data["success_items"] == mock_apply.return_value[0].successful
            assert json_data["failed_list"] == []
            assert mock_apply.call_args.kwargs["return_details"] is True

            # 3. 生成Excel导出文件
            mock_generate_excel.return_value = ("export_document_123", None, False)

            excel_request = {
                "uid_list": ["order1", "order2"],
                "cargo_list": ["cargo1", "cargo2"],
            }

            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/cargo/excel/jifei",
                clerk_token,
                excel_request,
            )

            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"]["document_id"] == "export_document_123"

    def test_complete_customer_management_workflow(self, employee_token):
        """测试完整的客户管理流程"""
        with patch("data.get_customer_record") as mock_get_customer, patch(
            "data.list_receiver_records"
        ) as mock_list_receivers, patch(
            "data.list_customer_records"
        ) as mock_list_customer_records, patch(
            "data.del_receiver_record"
        ) as mock_del_receiver, patch(
            "data.customer.Customer.del_customer_record"
        ) as mock_del_customer:

            customer_name = "测试公司"
            receiver_id = "rec123"

            # 1. 获取客户列表
            mock_customers = [
                {"customer_name": "测试公司", "receiver_count": 2},
                {"customer_name": "其他公司", "receiver_count": 1},
            ]
            mock_get_customer.return_value = mock_customers

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/customer_list", employee_token
            )
            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2

            # 2. 获取特定客户的收件人列表
            mock_receivers = [
                {"receiver_id": "rec123", "receiver": "张三"},
                {"receiver_id": "rec124", "receiver": "李四"},
            ]
            mock_get_customer.return_value = mock_receivers

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/receiver_list/{customer_name}", employee_token
            )
            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2

            # 3. 获取收件人详细信息
            mock_receiver_details = [
                {
                    "receiver_id": "rec123",
                    "receiver": "张三",
                    "phone": "13800000001",
                    "address": "北京市朝阳区",
                }
            ]
            mock_list_receivers.return_value = mock_receiver_details

            response = self.make_authenticated_request(
                "GET",
                f"{self.base_url}/receiver_info_list/{customer_name}",
                employee_token,
            )
            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 1

            # 4. 删除收件人
            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/del/{customer_name}/{receiver_id}",
                employee_token,
            )
            self.assert_api_success(response)

            # 5. 删除整个客户（级联删除所有收件人）
            response = self.make_authenticated_request(
                "POST", f"{self.base_url}/del_customer/{customer_name}", employee_token
            )
            self.assert_api_success(response)

    def test_complete_admin_operations_workflow(self, admin_token):
        """测试完整的管理员操作流程"""
        with patch("data.user.user_model.get_all") as mock_get_all_users, patch(
            "services.auth_service.change_user_role"
        ) as mock_change_role, patch("utils.log.load_log") as mock_load_log:

            # 1. 获取所有用户
            mock_users = [
                {"id": 1, "phone": "13800000001", "name": "用户1", "role": "employee"},
                {
                    "id": 2,
                    "phone": "13800000002",
                    "name": "用户2",
                    "role": "store_manager",
                },
                {"id": 3, "phone": "13800000003", "name": "用户3", "role": "employee"},
            ]
            mock_get_all_users.return_value = mock_users

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/users", admin_token
            )
            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 3

            # 2. 修改用户角色
            role_data = {"role": "store_manager"}
            updated_user = {"id": 1, "role": "store_manager"}
            mock_change_role.return_value = (updated_user, None)

            response = self.make_authenticated_request(
                "PUT", f"{self.base_url}/users/1/role", admin_token, role_data
            )
            self.assert_api_success(response, ["data"])

            # 3. 查看系统日志
            mock_logs = [
                {
                    "timestamp": "2023-01-01 10:00:00",
                    "user": "admin",
                    "action": "Change user role",
                    "details": "用户1角色从employee更改为store_manager",
                },
                {
                    "timestamp": "2023-01-01 09:00:00",
                    "user": "employee1",
                    "action": "Create order",
                    "details": "创建订单TEST001",
                },
            ]
            mock_load_log.return_value = mock_logs

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/logs", admin_token
            )
            json_data = self.assert_api_success(response, ["data"])
            assert len(json_data["data"]) == 2

    def test_error_handling_workflow(self, employee_token):
        """测试错误处理工作流程"""
        # 1. 尝试访问不存在的订单
        with patch("data.order_model.read", return_value=None):
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/nonexistent_uid", employee_token
            )
            # 根据实现，可能返回null或404错误
            json_data = self.assert_api_success(response, ["data"])
            assert json_data["data"] is None

        # 2. 尝试为不存在的订单添加货物
        with patch("data.order_model.read", return_value=None):
            add_cargo_data = {"cargo_count": 1}
            response = self.make_authenticated_request(
                "POST",
                f"{self.base_url}/orders/nonexistent_uid/add_cargo",
                employee_token,
                add_cargo_data,
            )
            # 这个操作应该失败，因为订单不存在

        # 3. 尝试获取不存在订单的货物
        with patch("services.cargo_service.get_cargo_with_tracking") as mock_get_cargo:
            mock_get_cargo.return_value = (None, "Order Not Found")

            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/orders/nonexistent_uid/cargo", employee_token
            )
            self.assert_response_code(response, 404)

    def test_permission_workflow(
        self, admin_token, store_manager_token, employee_token
    ):
        """测试权限控制工作流程"""
        # 1. 测试管理员权限
        with patch("data.user.user_model.get_all", return_value=[]):
            response = self.make_authenticated_request(
                "GET", f"{self.base_url}/users", admin_token
            )
            self.assert_api_success(response)

        # 2. 测试店长权限（不能访问用户管理）
        response = self.make_authenticated_request(
            "GET", f"{self.base_url}/users", store_manager_token
        )
        self.assert_response_code(response, 403)

        # 3. 测试员工权限（不能访问审核功能）
        response = self.make_authenticated_request(
            "GET", f"{self.base_url}/auth/pending", employee_token
        )
        self.assert_response_code(response, 403)

        # 4. 测试所有角色都能访问基本功能
        with patch("data.order_model.read", return_value=[]):
            for token in [admin_token, store_manager_token, employee_token]:
                response = self.make_authenticated_request(
                    "GET", f"{self.base_url}/orders", token
                )
                self.assert_api_success(response)
