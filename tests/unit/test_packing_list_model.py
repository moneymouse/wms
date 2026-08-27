"""装箱单模型测试"""

from unittest.mock import patch

import pytest

from data.DB import CargoTable
from data.customer.Customer import CustomerTable
from data.database import SessionFactory
from data.packing import box_model
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


@pytest.mark.unit
class TestPackingListModel:
    """装箱单模型测试"""

    def test_get_unassigned_excludes_draft_packing_lists(self):
        """测试未分配箱子列表会排除草稿装箱单"""
        session = SessionFactory()
        try:
            customer = CustomerTable(name="客户A")
            operator = UserTable(
                phone="13800000001",
                name="操作员A",
                password="hashed-password",
                role="worker",
                status="approved",
            )
            session.add_all([customer, operator])
            session.commit()

            draft_list = PackingListTable(
                uid="draft-pl",
                list_number="DRAFT-001",
                customer_id=customer.id,
                creator_id=operator.id,
                status="draft",
                create_date="2023-01-01 09:00",
            )
            completed_list = PackingListTable(
                uid="done-pl",
                list_number="DONE-001",
                customer_id=customer.id,
                creator_id=operator.id,
                status="completed",
                create_date="2023-01-01 10:00",
            )
            session.add_all([draft_list, completed_list])
            session.commit()

            session.add_all(
                [
                    CargoTable(
                        uid="draft-box",
                        origin_id="BOX-DRAFT-1",
                        tag="DRAFT-001_1",
                        count=1,
                        weight=1.2,
                        status=0,
                        packing_list_uid="draft-pl",
                        item_name="草稿箱",
                        real_en_name="草稿箱",
                        piece_count=1,
                        box_number=1,
                        create_date="2023-01-01 09:05",
                    ),
                    CargoTable(
                        uid="done-box",
                        origin_id="BOX-DONE-1",
                        tag="DONE-001_1",
                        count=1,
                        weight=1.5,
                        status=0,
                        packing_list_uid="done-pl",
                        item_name="已完成箱",
                        real_en_name="已完成箱",
                        piece_count=1,
                        box_number=1,
                        create_date="2023-01-01 10:05",
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        result = box_model.get_unassigned(valid_only=True)

        assert len(result) == 1
        assert result[0]["list_number"] == "DONE-001"
        assert all(group["list_number"] != "DRAFT-001" for group in result)

    def test_box_item_details_preserve_customs_code(self, setup_test_database):
        session = setup_test_database
        operator = UserTable(
            phone="13800000002",
            name="操作员B",
            password="hashed-password",
            status="approved",
        )
        session.add(operator)
        session.commit()
        session.add(
            PackingListTable(
                uid="customs-pl",
                list_number="CUSTOMS-001",
                creator_id=operator.id,
                status="draft",
                create_date="2026-07-14 10:00",
            )
        )
        session.commit()

        with patch(
            "data.packing.PackingList.SessionFactory", return_value=session
        ):
            created = box_model.create(
                "customs-pl",
                "SHOES",
                2,
                item_details=[
                    {
                        "item_name": "SHOES",
                        "customs_code": "6404199000",
                        "piece_count": 2,
                    }
                ],
            )
            assert created["item_details"][0]["customs_code"] == "6404199000"

            assert box_model.update(
                created["uid"],
                {
                    "item_details": [
                        {
                            "item_name": "SHOES",
                            "customs_code": "6404110000",
                            "piece_count": 2,
                        }
                    ]
                },
            )
            assert box_model.read(created["uid"])["item_details"][0][
                "customs_code"
            ] == "6404110000"
