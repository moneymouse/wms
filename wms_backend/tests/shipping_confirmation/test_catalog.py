"""The draft catalog excludes fully shipped lists in SQL before pagination."""

import pytest

from Auth import create_jwt
from data.DB import CargoTable
from data.packing.PackingList import PackingListTable


@pytest.fixture
def catalog(world, monkeypatch):
    monkeypatch.setattr("data.packing.PackingList.SessionFactory", world["factory"])
    with world["factory"].begin() as session:
        shipped = session.get(PackingListTable, "packing-a")
        shipped.status = "completed"
        shipped.list_number = "SHIPPED"
        shipped.create_date = "2026-10-23 12:00"
        session.get(CargoTable, "box-a").status = 1
        session.get(CargoTable, "box-c").status = 1
        # The archived, unshipped box in packing-a must not make it selectable.
        pending = session.get(PackingListTable, "packing-b")
        pending.status = "completed"
        pending.list_number = "PENDING"
        pending.create_date = "2026-10-23 11:00"
        session.add_all([
            PackingListTable(uid="partial", list_number="PARTIAL", creator_id=1,
                             customer_id=1, status="completed", create_date="2026-10-23 10:00"),
            PackingListTable(uid="draft", list_number="DRAFT", creator_id=1,
                             customer_id=1, status="draft", create_date="2026-10-23 09:00"),
            PackingListTable(uid="returned", list_number="RETURNED", creator_id=1,
                             customer_id=1, status="completed", create_date="2026-10-23 08:00"),
            CargoTable(uid="partial-shipped", packing_list_uid="partial", status=1),
            CargoTable(uid="partial-pending", packing_list_uid="partial", status=0),
            CargoTable(uid="draft-box", packing_list_uid="draft", status=0),
            CargoTable(uid="returned-box", packing_list_uid="returned", status=0, date=None),
        ])
    return world["client"]


def search(client, **params):
    response = client.get("/api/packing-lists", query_string=params, headers={
        "x-token": create_jwt({"user_id": 1, "role": "salesperson", "name": "业务员"}),
    })
    assert response.status_code == 200, response.json
    return response.json["data"]


def test_draft_catalog_filters_before_count_and_pagination(catalog):
    params = {"box_status": "outbound", "exclude_box_status": "true", "s": 2}
    first = search(catalog, p=1, **params)
    second = search(catalog, p=2, **params)
    assert first["total"] == second["total"] == 4
    assert [item["uid"] for item in first["items"]] == ["packing-b", "partial"]
    assert [item["uid"] for item in second["items"]] == ["draft", "returned"]
    assert search(catalog, p=3, **params)["items"] == []


def test_draft_catalog_search_excludes_shipped_without_changing_regular_list(catalog):
    params = {"box_status": "outbound", "exclude_box_status": "true"}
    assert search(catalog, q="SHIPPED", **params)["total"] == 0
    assert search(catalog, q="测试客户", **params)["total"] == 4
    regular = search(catalog, q="SHIPPED")
    assert regular["total"] == 1
    assert [item["uid"] for item in regular["items"]] == ["packing-a"]
