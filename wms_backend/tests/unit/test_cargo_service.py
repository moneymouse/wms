"""货物服务层测试"""

import pytest
from data.packing.PackingList import PackingListTable
from services.outbound_service import WaybillImportResult, update_cargo_details
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
import pandas as pd

from data import cargo_model
from data.DB import BoxCostRecordTable, CargoTable, OrderTable
from data.database import SessionFactory
from services.cargo_service import (
    get_cargo_with_tracking,
    generate_excel,
    parse_waybill_file,
    apply_waybill_table,
    background_register,
)
from tests.base import BaseServiceTest, FileTestMixin
from tests.factories import OrderFactory, CargoFactory, FileFactory


@pytest.mark.unit
@pytest.mark.service
@pytest.mark.cargo
class TestCargoService(BaseServiceTest, FileTestMixin):
    """货物服务测试"""

    def test_get_cargo_with_tracking_success(self):
        """本地缓存返回物流信息，仓库业务状态保持整数。"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1", "cargo2"])
        mock_cargos = [
            CargoFactory.create_cargo_data(uid="cargo1", target_order_uid="test_uid", waybill_id="WB001", status=1),
            CargoFactory.create_cargo_data(uid="cargo2", target_order_uid="test_uid", waybill_id="WB002", status=0),
        ]

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.side_effect = mock_cargos

        with patch("services.cargo_service.cached_tracking_for_cargos") as mock_cache:
            mock_cache.return_value = {
                "cargo1": {
                    "track_status": "Delivered_Other", "desc": "已送达",
                    "events": [{"time_utc": "2026-10-11T10:00:00Z", "description": "已送达"}],
                    "track_info": {"latest_status": {"status": "Delivered"}},
                    "tracking_received_at": "2026-10-11T10:00:01Z", "tracking_pending": False,
                },
                "cargo2": {"track_status": None, "desc": None, "events": [], "track_info": None,
                           "tracking_received_at": None, "tracking_pending": True},
            }

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 2
            assert cargo_list[0]["status"] == 1
            assert cargo_list[0]["track_status"] == "Delivered_Other"
            assert cargo_list[0]["desc"] == "已送达"
            assert len(cargo_list[0]["events"]) == 1
            assert cargo_list[0]["tracking_pending"] is False
            assert cargo_list[1]["status"] == 0
            assert cargo_list[1]["tracking_pending"] is True
            mock_cache.assert_called_once_with(mock_cargos)
            mock_cargo_model.update.assert_not_called()

    def test_get_cargo_with_tracking_order_not_found(self):
        """测试订单不存在"""
        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = None

        cargo_list, error = get_cargo_with_tracking(
            "nonexistent_uid", mock_order_model, mock_cargo_model
        )

        assert cargo_list is None
        assert error == "Order Not Found"

    def test_get_cargo_with_tracking_no_waybill(self):
        """测试货物没有运单号"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1"])
        mock_cargo = CargoFactory.create_cargo_data(uid="cargo1", target_order_uid="test_uid", waybill_id=None)

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch("services.cargo_service.cached_tracking_for_cargos") as mock_cache, patch(
            "requests.sessions.Session.request", side_effect=AssertionError("outbound HTTP")
        ) as mock_network:
            mock_cache.return_value = {"cargo1": {"track_status": None, "desc": None, "events": [],
                                                  "track_info": None, "tracking_received_at": None,
                                                  "tracking_pending": True}}

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 1
            assert cargo_list[0]["tracking_pending"] is True
            assert cargo_list[0]["status"] == 0
            mock_network.assert_not_called()

    def test_get_cargo_with_tracking_cache_error(self):
        """缓存读取错误交由调用者处理，不能伪装成无物流数据。"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1"])
        mock_cargo = CargoFactory.create_cargo_data(uid="cargo1", target_order_uid="test_uid", waybill_id="WB001")

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch(
            "services.cargo_service.cached_tracking_for_cargos", side_effect=Exception("Cache Error")
        ):
            with pytest.raises(Exception, match="Cache Error"):
                get_cargo_with_tracking("test_uid", mock_order_model, mock_cargo_model)

            assert mock_cargo["status"] == 0
            mock_cargo_model.update.assert_not_called()

    def test_get_cargo_with_tracking_not_found_status(self):
        """未找到物流的缓存也不会写入或覆盖仓库业务状态。"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1"])
        mock_cargo = CargoFactory.create_cargo_data(uid="cargo1", target_order_uid="test_uid", waybill_id="WB001")

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch("services.cargo_service.cached_tracking_for_cargos") as mock_cache:
            mock_cache.return_value = {"cargo1": {
                "track_status": "NotFound", "desc": "查询不到", "events": [],
                "track_info": {"latest_status": {"status": "NotFound"}},
                "tracking_received_at": "2026-10-11T10:00:01Z", "tracking_pending": False,
            }}

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 1
            assert cargo_list[0]["status"] == 0
            assert cargo_list[0]["track_status"] == "NotFound"
            mock_cargo_model.update.assert_not_called()

    def _mock_template(self, mode_key, template_type, config, single_order_only=False, template_file=None):
        """辅助方法：创建 mock 模板对象"""
        mock = Mock()
        mock.mode_key = mode_key
        mock.label = "极飞" if mode_key == "jifei" else "金飞"
        mock.template_type = template_type
        mock.config = __import__('json').dumps(config)
        mock.single_order_only = single_order_only
        mock.template_file = template_file
        return mock

    def test_generate_excel_single_order_mode(self):
        """测试单订单模式Excel生成"""
        mock_order = OrderFactory.create_order_data(
            country="美国", zip_code="12345", order_id="TEST001"
        )
        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order

        mock_template = self._mock_template(
            "jinfeiqi", "cell",
            {"cell_mappings": [{"cell": "B3", "field": "order_id"}]},
            single_order_only=True,
            template_file="jinfeiqi_template.xlsx"
        )

        with patch("services.cargo_service.load_workbook") as mock_load_wb, patch(
            "services.cargo_service._get_template"
        ) as mock_get_template:
            mock_wb = MagicMock()
            mock_ws = MagicMock()
            mock_wb.active = mock_ws
            mock_load_wb.return_value = mock_wb
            mock_get_template.return_value = mock_template

            result, error, is_plain_text = generate_excel(
                "jinfeiqi", ["test_uid"], None, mock_order_model, mock_cargo_model
            )

            assert error is None
            assert not is_plain_text
            assert "金飞美国12345(001)" in result
            mock_wb.save.assert_called_once()

    def test_generate_excel_single_order_exceed_limit(self):
        """测试单订单模式超出数量限制"""
        mock_template = self._mock_template(
            "jinfeiqi", "cell", {}, single_order_only=True
        )

        mock_order_model = Mock()
        mock_cargo_model = Mock()

        with patch("services.cargo_service._get_template") as mock_get_template:
            mock_get_template.return_value = mock_template
            result, error, is_plain_text = generate_excel(
                "jinfeiqi", ["uid1", "uid2"], None, mock_order_model, mock_cargo_model
            )

            assert result is None
            assert error == "Exceed Order Count Limitation"
            assert not is_plain_text

    def test_generate_excel_kehu_mode(self):
        """测试客户模式Excel生成"""
        mock_order = OrderFactory.create_order_data(
            receiver="张三", customer_name="测试公司", cargo_uid_list=["cargo1"]
        )
        mock_cargo = CargoFactory.create_cargo_data(waybill_id="WB001")

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        result, error, is_plain_text = generate_excel(
            "kehu", ["test_uid"], None, mock_order_model, mock_cargo_model
        )

        assert error is None
        assert is_plain_text
        assert "张三(测试公司)" in result
        assert "WB001" in result

    def test_generate_excel_kehu_mode_no_waybill(self):
        """测试客户模式无运单号"""
        mock_order = OrderFactory.create_order_data(
            receiver="张三", customer_name="测试公司", cargo_uid_list=["cargo1"]
        )
        mock_cargo = CargoFactory.create_cargo_data(waybill_id=None)

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        result, error, is_plain_text = generate_excel(
            "kehu", ["test_uid"], None, mock_order_model, mock_cargo_model
        )

        assert error is None
        assert is_plain_text
        # 无运单号的货物会被跳过，结果为空
        assert result == ""

    def test_generate_excel_general_mode(self):
        """测试通用模式Excel生成"""
        mock_order = OrderFactory.create_order_data(
            country="美国",
            zip_code="12345",
            order_id="TEST001",
            cargo_uid_list=["cargo1"],
        )
        mock_cargo = CargoFactory.create_cargo_data(weight=2.5)

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        mock_template = self._mock_template(
            "jifei", "column",
            {
                "columns": ["转运号", "重量"],
                "reference_table": {"转运号": "transfer_id", "重量": "weight"},
            }
        )

        with patch(
            "services.cargo_service._get_template"
        ) as mock_get_template, patch("pandas.DataFrame.to_excel") as mock_to_excel:
            mock_get_template.return_value = mock_template
            result, error, is_plain_text = generate_excel(
                "jifei", ["test_uid"], None, mock_order_model, mock_cargo_model
            )

            assert error is None
            assert not is_plain_text
            assert "极飞美国12345(001)" in result
            mock_to_excel.assert_called_once()

    def test_generate_excel_with_cargo_filter(self):
        """测试使用货物过滤器"""
        mock_order = OrderFactory.create_order_data(
            country="美国",
            zip_code="12345",
            order_id="TEST001",
            cargo_uid_list=["cargo1", "cargo2"],
        )
        mock_cargo1 = CargoFactory.create_cargo_data(transfer_id="TR001", weight=1.5)
        mock_cargo2 = CargoFactory.create_cargo_data(transfer_id="TR002", weight=2.0)

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.side_effect = [mock_cargo1, mock_cargo2]

        # 只要第一个货物
        request_cargo_list = ["cargo1"]

        mock_template = self._mock_template(
            "jifei", "column",
            {
                "columns": ["转运号", "重量"],
                "reference_table": {"转运号": "transfer_id", "重量": "weight"},
            }
        )

        with patch(
            "services.cargo_service._get_template"
        ) as mock_get_template, patch("pandas.DataFrame.to_excel") as mock_to_excel:
            mock_get_template.return_value = mock_template
            result, error, is_plain_text = generate_excel(
                "jifei",
                ["test_uid"],
                request_cargo_list,
                mock_order_model,
                mock_cargo_model,
            )

            # 验证返回了正确的结果
            assert error is None
            assert not is_plain_text
            # 验证读取了所有货物
            assert mock_cargo_model.read.call_count == 2
            mock_to_excel.assert_called_once()

    def test_parse_waybill_file_txt(self):
        """测试解析txt格式转运单文件"""
        txt_content = b"TR001,WB001\nTR002,WB002\nTR003,WB003\n"
        mock_file = BytesIO(txt_content)
        mock_file.stream = BytesIO(txt_content)

        result = parse_waybill_file(mock_file, "test.txt")

        expected = {"TR001": "WB001", "TR002": "WB002", "TR003": "WB003"}
        assert result == expected

    def test_parse_waybill_file_excel(self):
        """测试解析Excel格式转运单文件"""
        mock_file = BytesIO()
        waybill_data = FileFactory.create_waybill_data(3)
        excel_data = FileFactory.create_waybill_excel_data(waybill_data)

        with patch("pandas.read_excel") as mock_read_excel:
            mock_df = pd.DataFrame(excel_data)
            mock_read_excel.return_value = mock_df

            result = parse_waybill_file(mock_file, "test.xlsx")

            expected = {
                waybill_data[0]["transfer_id"]: waybill_data[0]["waybill_id"],
                waybill_data[1]["transfer_id"]: waybill_data[1]["waybill_id"],
                waybill_data[2]["transfer_id"]: waybill_data[2]["waybill_id"],
            }
            assert result == expected

    def test_apply_waybill_table_success(self, setup_test_database):
        """测试成功应用转运单"""
        session = setup_test_database
        transfer_map = {"TR001": "WB001", "TR002": "WB002"}
        session.add(OrderTable(uid="import-order", order_id="IMPORT", archive=False))
        session.add_all(
            [
                CargoTable(
                    uid=f"cargo{index}",
                    origin_id=f"CARGO-{index}",
                    transfer_id=transfer_id,
                    waybill_id="",
                    status=0, weight=1, target_order_uid="import-order",
                    archive=False,
                    create_date="2023-01-01 09:00",
                )
                for index, transfer_id in enumerate(
                    ("TR001", "TR002", "TR003"), start=1
                )
            ]
        )
        session.commit()

        with patch("services.cargo_service.registerTrack") as mock_register:
            register_list, error = apply_waybill_table(cargo_model, transfer_map)

            assert error is None
            assert len(register_list) == 2
            assert ("cargo1", "WB001") in register_list
            assert ("cargo2", "WB002") in register_list
            mock_register.assert_called_once_with(register_list)
            session.expire_all()
            persisted = {
                row.uid: row.waybill_id
                for row in session.query(CargoTable)
                .filter(CargoTable.uid.in_(["cargo1", "cargo2", "cargo3"]))
                .all()
            }
            assert persisted == {
                "cargo1": "WB001",
                "cargo2": "WB002",
                "cargo3": "",
            }

    def test_apply_waybill_table_delegates_atomic_shipping_to_service(
        self, setup_test_database
    ):
        """批量上传由统一出库服务在同事务处理状态和成本。"""
        session = setup_test_database
        transfer_map = {"TR001": "WB001"}
        session.add(PackingListTable(uid="pl1", list_number="PL1", creator_id=1, archive=False))
        session.add_all(
            [
                OrderTable(
                    uid="order1",
                    order_id="ORDER001",
                    transportation="",
                    archive=False,
                    create_date="2023-01-01 09:00",
                ),
                CargoTable(
                    uid="box1",
                    origin_id="BOX001",
                    transfer_id="TR001",
                    waybill_id="",
                    packing_list_uid="pl1",
                    target_order_uid="order1",
                    status=0,
                    weight=1,
                    archive=False,
                    create_date="2023-01-01 09:00",
                ),
            ]
        )
        session.commit()
        mock_cargo_model = Mock()

        with patch("services.cargo_service.registerTrack") as mock_register:

            register_list, error = apply_waybill_table(mock_cargo_model, transfer_map)

            assert error is None
            assert register_list == [("box1", "WB001")]
            assert session.query(BoxCostRecordTable).filter_by(box_uid="box1").count() == 1
            mock_register.assert_called_once_with(register_list)
            session.expire_all()
            box = session.query(CargoTable).filter_by(uid="box1").one()
            assert box.waybill_id == "WB001"
            assert box.status == 1
            assert box.date is not None

    def test_application_update_marks_box_as_shipped(self):
        """测试应用组合更新号码和确认出库"""
        session = SessionFactory()
        try:
            session.add(PackingListTable(uid="pl1", list_number="PL1", creator_id=1, archive=False))
            session.add_all(
                [
                    OrderTable(
                        uid="order1",
                        order_id="ORDER001",
                        customer_name="客户A",
                        transportation="",
                        archive=False,
                        create_date="2023-01-01 09:00",
                    ),
                    CargoTable(
                        uid="box1",
                        origin_id="ORD001-1",
                        transfer_id="TR001",
                        tag="TAG1",
                        count=1,
                        weight=1.0,
                        status=0,
                        packing_list_uid="pl1",
                        target_order_uid="order1",
                        waybill_id="",
                        create_date="2023-01-01 09:00",
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        update_cargo_details("box1", {"waybill_id": "WB001"}, confirm_outbound=True)
        updated = cargo_model.read("box1")

        assert updated["waybill_id"] == "WB001"
        assert updated["status"] == 1
        assert updated["date"] is not None

    def test_application_update_locks_box_cost_without_transportation(self):
        """测试订单无运输方式时上传转单号也能锁单，成本记录渠道留空"""
        session = SessionFactory()
        try:
            session.add(PackingListTable(uid="pl1", list_number="PL1", creator_id=1, archive=False))
            session.add_all(
                [
                    OrderTable(
                        uid="order-no-transport",
                        order_id="ORDER-NO-TRANSPORT",
                        customer_name="客户A",
                        transportation="",
                        archive=False,
                        create_date="2023-01-01 09:00",
                    ),
                    CargoTable(
                        uid="box-no-transport",
                        origin_id="ORD002-1",
                        transfer_id="TR002",
                        tag="TAG2",
                        count=1,
                        weight=2.5,
                        status=0,
                        packing_list_uid="pl1",
                        target_order_uid="order-no-transport",
                        waybill_id="",
                        create_date="2023-01-01 09:00",
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        update_cargo_details("box-no-transport", {"waybill_id": "WB002"}, confirm_outbound=True)

        session = SessionFactory()
        try:
            box = session.query(CargoTable).filter_by(uid="box-no-transport").first()
            cost_record = (
                session.query(BoxCostRecordTable)
                .filter_by(box_uid="box-no-transport")
                .first()
            )
            assert box.status == 1
            assert cost_record is not None
            assert cost_record.transportation_mode_id is None
            assert cost_record.transportation_name == ""
            assert cost_record.unit_cost == 0
            assert cost_record.total_cost == 0
        finally:
            session.close()

    def test_apply_waybill_table_register_error(self, setup_test_database):
        """测试17track注册失败"""
        session = setup_test_database
        transfer_map = {"TR001": "WB001"}
        session.add(OrderTable(uid="import-order", order_id="IMPORT", archive=False))
        session.add(
            CargoTable(
                uid="cargo1",
                origin_id="CARGO-1",
                transfer_id="TR001",
                waybill_id="",
                status=0, weight=1, target_order_uid="import-order",
                archive=False,
                create_date="2023-01-01 09:00",
            )
        )
        session.commit()

        with patch(
            "services.cargo_service.registerTrack", side_effect=Exception("API Error")
        ) as mock_register:
            register_list, error = apply_waybill_table(cargo_model, transfer_map)

            assert error is not None
            assert len(register_list) == 1  # 货物仍然更新了
            assert ("cargo1", "WB001") in register_list
            mock_register.assert_called_once_with(register_list)
            session.expire_all()
            assert (
                session.query(CargoTable).filter_by(uid="cargo1").one().waybill_id
                == "WB001"
            )

    def test_apply_waybill_table_returns_details_and_registers_only_changes(self):
        """详细协议保留全部成功/失败项，追踪只登记实际变更。"""
        from services import cargo_service

        pairs = [("cargo1", "WB001")]
        result = WaybillImportResult(
            registered=pairs,
            successful=[{"uid": "cargo1", "waybill_id": "WB001"},
                        {"uid": "cargo2", "waybill_id": "WB002"}],
            failed=[{"uid": "cargo3", "code": 400, "reason": "归属不一致"}],
        )
        transfer_map = {"TR001": "WB001", "TR002": "WB002", "TR003": "WB003"}
        operator = {"user_id": 1, "role": "clerk"}
        with patch("services.outbound_service.update_waybill_table", return_value=result) as mock_update, patch(
            "services.cargo_service.registerTrack"
        ) as mock_register:
            returned, error = apply_waybill_table(
                cargo_model, transfer_map, confirm_outbound=False,
                operator=operator, return_details=True,
            )
        assert returned is result
        assert error is None
        mock_register.assert_called_once_with(pairs)
        mock_update.assert_called_once_with(
            cargo_service.SessionFactory, transfer_map, confirm_outbound=False,
            operator=operator, return_details=True,
        )

    def test_apply_waybill_table_unchanged_success_skips_tracking(self):
        result = WaybillImportResult(successful=[{"uid": "cargo1", "waybill_id": "WB001"}])
        with patch("services.outbound_service.update_waybill_table", return_value=result), patch(
            "services.cargo_service.registerTrack"
        ) as mock_register:
            returned, error = apply_waybill_table(
                cargo_model, {"TR001": "WB001"}, return_details=True,
            )
        assert returned is result
        assert error is None
        mock_register.assert_not_called()

    def test_apply_waybill_table_tracking_error_keeps_details(self):
        result = WaybillImportResult(
            registered=[("cargo1", "WB001")],
            successful=[{"uid": "cargo1", "waybill_id": "WB001"}],
            failed=[{"uid": "cargo2", "code": 400, "reason": "归属不一致"}],
        )
        tracking_error = RuntimeError("API Error")
        with patch("services.outbound_service.update_waybill_table", return_value=result), patch(
            "services.cargo_service.registerTrack", side_effect=tracking_error
        ):
            returned, error = apply_waybill_table(
                cargo_model, {"TR001": "WB001"}, return_details=True,
            )
        assert returned is result
        assert error is tracking_error

    def test_apply_waybill_table_empty_map(self):
        """测试空转运单映射"""
        transfer_map = {}

        with patch("services.cargo_service.registerTrack") as mock_register:
            register_list, error = apply_waybill_table(cargo_model, transfer_map)

            assert error is None
            assert len(register_list) == 0
            mock_register.assert_not_called()

    def test_background_register_success(self):
        """测试后台注册成功"""
        with patch("services.cargo_service.registerTrack") as mock_register, patch(
            "services.cargo_service.Thread"
        ) as mock_thread:

            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance

            background_register("cargo_uid", "WB001")

            # 验证创建了后台线程
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()

            # 验证线程函数
            thread_target = mock_thread.call_args[1]["target"]
            thread_target()  # 执行线程函数
            mock_register.assert_called_once_with([("cargo_uid", "WB001")])

    def test_background_register_error(self):
        """测试后台注册错误处理"""
        with patch(
            "services.cargo_service.registerTrack", side_effect=Exception("API Error")
        ), patch("services.cargo_service.Thread") as mock_thread, patch(
            "services.cargo_service.logger"
        ) as mock_logger:

            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance

            background_register("cargo_uid", "WB001")

            # 执行线程函数验证错误日志
            thread_target = mock_thread.call_args[1]["target"]
            thread_target()  # 执行线程函数
            mock_logger.error.assert_called_once()
