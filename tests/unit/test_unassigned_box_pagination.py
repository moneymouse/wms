"""未分配装箱单分页测试。"""

from unittest.mock import patch

from sqlalchemy.orm import Session

from data.DB import CargoTable
from data.packing import box_model
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


def test_unassigned_boxes_are_paginated_by_packing_list(setup_test_database):
    session = setup_test_database
    operator = UserTable(
        id=31,
        phone="13800000031",
        name="分页测试员",
        password="test-password",
        status="approved",
    )
    session.add(operator)
    session.commit()

    for index in range(1, 4):
        packing_list = PackingListTable(
            uid=f"page-pl-{index}",
            list_number=f"PAGE-{index:03d}",
            creator_id=operator.id,
            status="completed",
            archive=False,
            create_date=f"2026-09-01 10:0{index}:00",
        )
        box = CargoTable(
            uid=f"page-box-{index}",
            packing_list_uid=packing_list.uid,
            box_number=1,
            item_name="测试货物",
            weight=index + 0.5,
            archive=False,
        )
        session.add_all([packing_list, box])
    session.commit()

    with patch(
        "data.packing.PackingList.SessionFactory",
        side_effect=lambda: Session(bind=session.get_bind()),
    ):
        first_page = box_model.get_unassigned(valid_only=True, page=1, page_size=2)
        second_page = box_model.get_unassigned(valid_only=True, page=2, page_size=2)
        searched = box_model.get_unassigned(
            valid_only=True,
            mark_search="002",
            page=1,
            page_size=2,
        )

    assert first_page["total"] == 3
    assert first_page["total_boxes"] == 3
    assert first_page["page"] == 1
    assert [row["list_number"] for row in first_page["items"]] == ["PAGE-003", "PAGE-002"]
    assert [row["list_number"] for row in second_page["items"]] == ["PAGE-001"]
    assert searched["total"] == 1
    assert searched["items"][0]["list_number"] == "PAGE-002"
