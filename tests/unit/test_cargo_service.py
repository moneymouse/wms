"""货物服务层测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
import pandas as pd

from data import cargo_model
from data.DB import CargoTable
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
        """测试成功获取货物追踪信息"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1", "cargo2"])
        mock_cargos = [
            CargoFactory.create_cargo_data(waybill_id="WB001"),
            CargoFactory.create_cargo_data(waybill_id="WB002"),
        ]

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.side_effect = mock_cargos

        with patch("services.cargo_service.getTrackInfo") as mock_track:
            mock_track.return_value = [
                {
                    "tag": "cargo1",
                    "track_info": {
                        "latest_status": {
                            "status": "Delivered",
                            "sub_status": "delivered",
                            "sub_status_descr": "已送达",
                        },
                        "tracking": {
                            "providers": [
                                {
                                    "events": [
                                        {"date": "2023-01-01", "description": "已送达"}
                                    ]
                                }
                            ]
                        },
                    },
                }
            ]

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 2
            # 验证第一个货物包含追踪信息
            assert cargo_list[0]["status"] == "delivered"
            assert cargo_list[0]["desc"] == "已送达"
            assert "events" in cargo_list[0]

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
        mock_cargo = CargoFactory.create_cargo_data(waybill_id=None)

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch("services.cargo_service.getTrackInfo") as mock_track:
            mock_track.return_value = []

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 1
            # 验证没有运单号的货物不会查询追踪信息
            mock_track.assert_called_once_with([])

    def test_get_cargo_with_tracking_api_error(self):
        """测试追踪API错误"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1"])
        mock_cargo = CargoFactory.create_cargo_data(waybill_id="WB001")

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch(
            "services.cargo_service.getTrackInfo", side_effect=Exception("API Error")
        ):
            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error == "Get Track Error"
            assert len(cargo_list) == 1  # 仍然返回本地数据

    def test_get_cargo_with_tracking_not_found_status(self):
        """测试追踪状态为NotFound"""
        mock_order = OrderFactory.create_order_data(cargo_uid_list=["cargo1"])
        mock_cargo = CargoFactory.create_cargo_data(waybill_id="WB001")

        mock_order_model = Mock()
        mock_cargo_model = Mock()
        mock_order_model.read.return_value = mock_order
        mock_cargo_model.read.return_value = mock_cargo

        with patch("services.cargo_service.getTrackInfo") as mock_track:
            mock_track.return_value = [
                {
                    "tag": "cargo1",
                    "track_info": {"latest_status": {"status": "NotFound"}},
                }
            ]

            cargo_list, error = get_cargo_with_tracking(
                "test_uid", mock_order_model, mock_cargo_model
            )

            assert error is None
            assert len(cargo_list) == 1
            # 验证NotFound状态不会更新货物信息
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

    def test_apply_waybill_table_success(self):
        """测试成功应用转运单"""
        transfer_map = {"TR001": "WB001", "TR002": "WB002"}

        mock_cargo_model = Mock()
        mock_cargo_model.data_point = {
            "cargo1": {"transfer_id": "TR001"},
            "cargo2": {"transfer_id": "TR002"},
            "cargo3": {"transfer_id": "TR003"},  # 不在转运单中
        }

        with patch("services.cargo_service.registerTrack") as mock_register, patch(
            "datetime.datetime"
        ) as mock_datetime:

            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 10:00"

            register_list, error = apply_waybill_table(mock_cargo_model, transfer_map)

            assert error is None
            assert len(register_list) == 2
            assert ("cargo1", "WB001") in register_list
            assert ("cargo2", "WB002") in register_list

            # 验证货物更新调用
            assert mock_cargo_model.update.call_count == 2
            mock_register.assert_called_once_with(register_list)

    def test_apply_waybill_table_marks_box_as_shipped(self):
        """测试箱子上传转单号后自动变为已出货"""
        transfer_map = {"TR001": "WB001"}

        mock_cargo_model = Mock()
        mock_cargo_model.data_point = {
            "box1": {
                "transfer_id": "TR001",
                "packing_list_uid": "pl1",
                "target_order_uid": "order1",
                "status": 0,
            }
        }

        with patch("services.cargo_service.registerTrack") as mock_register, patch(
            "datetime.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 10:00"

            register_list, error = apply_waybill_table(mock_cargo_model, transfer_map)

            assert error is None
            assert register_list == [("box1", "WB001")]
            mock_cargo_model.update.assert_called_once_with(
                "box1",
                {
                    "waybill_id": "WB001",
                    "status": 1,
                    "date": "2023-01-01 10:00",
                },
            )
            mock_register.assert_called_once_with(register_list)

    def test_cargo_model_update_marks_box_as_shipped(self):
        """测试箱子直接更新运单号后自动变为已出货"""
        session = SessionFactory()
        try:
            session.add(
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
                )
            )
            session.commit()
        finally:
            session.close()

        cargo_model.update("box1", {"waybill_id": "WB001"})
        updated = cargo_model.read("box1")

        assert updated["waybill_id"] == "WB001"
        assert updated["status"] == 1
        assert updated["date"] is not None

    def test_apply_waybill_table_register_error(self):
        """测试17track注册失败"""
        transfer_map = {"TR001": "WB001"}

        mock_cargo_model = Mock()
        mock_cargo_model.data_point = {"cargo1": {"transfer_id": "TR001"}}

        with patch(
            "services.cargo_service.registerTrack", side_effect=Exception("API Error")
        ) as mock_register, patch("datetime.datetime") as mock_datetime:

            mock_datetime.now.return_value.strftime.return_value = "2023-01-01 10:00"

            register_list, error = apply_waybill_table(mock_cargo_model, transfer_map)

            assert error is not None
            assert len(register_list) == 1  # 货物仍然更新了
            assert ("cargo1", "WB001") in register_list

            # 验证仍然尝试了注册
            mock_register.assert_called_once_with(register_list)

    def test_apply_waybill_table_empty_map(self):
        """测试空转运单映射"""
        transfer_map = {}

        mock_cargo_model = Mock()
        mock_cargo_model.data_point = {"cargo1": {"transfer_id": "TR001"}}

        with patch("services.cargo_service.registerTrack") as mock_register:
            register_list, error = apply_waybill_table(mock_cargo_model, transfer_map)

            assert error is None
            assert len(register_list) == 0
            mock_register.assert_called_once_with([])

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
