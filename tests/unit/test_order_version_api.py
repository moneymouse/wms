"""HTTP contract tests for order history and unrestricted order edits."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from Auth import create_jwt
from data.DB import (
    BoxCostRecordTable,
    CargoTable,
    OrderTable,
    PaymentReceiptItemTable,
    PaymentReceiptTable,
    order_model,
)
from data.customer.Customer import CustomerTable
from data.order_version import (
    OrderVersionTable,
    ensure_baseline,
    snapshot_order,
)
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable
from services.order_edit_policy import BOX_IDENTITY_IMMUTABLE_MESSAGE


NOW = "2026-09-16 10:00:00"
ADMIN = {"user_id": 1, "name": "管理员测试", "role": "admin"}


@pytest.fixture(autouse=True)
def _use_test_session_for_history_queries(setup_test_database):
    """Keep history read helpers on the per-test in-memory SQLite connection."""
    with patch(
        "data.order_version.SessionFactory", return_value=setup_test_database
    ):
        yield


def _headers(token):
    return {"x-token": token, "Content-Type": "application/json"}


def _page_data(response):
    """Accept the repository's two existing pagination response conventions."""
    body = response.get_json()
    data = body.get("data")
    if isinstance(data, dict):
        return data
    return {
        "items": data or [],
        "total": body.get("total", 0),
        "page": body.get("page"),
        "page_size": body.get("page_size"),
    }


def _seed_versioned_order(session, uid="api-version-order"):
    order = OrderTable(
        uid=uid,
        order_id="API-VERSION-001",
        customer_name="API历史客户",
        receiver="A",
        archive=False,
        cargo_count=0,
        create_date=NOW,
    )
    session.add(order)
    session.flush()
    ensure_baseline(session, uid, snapshot_order(session, uid))
    session.commit()
    return order


def _seed_outbound_box_world(session):
    admin = UserTable(
        id=1,
        phone="13890002001",
        name="管理员测试",
        password="unused",
        status="approved",
    )
    customer = CustomerTable(name="锁单测试客户")
    session.add_all([admin, customer])
    session.flush()
    order = OrderTable(
        uid="locked-api-order",
        order_id="LOCKED-API-001",
        customer_name=customer.name,
        receiver="旧收件人",
        transportation="测试渠道",
        total_weight=5.0,
        cargo_count=1,
        archive=False,
        create_date=NOW,
    )
    order.customers = [customer]
    packing_list = PackingListTable(
        uid="locked-api-packing",
        list_number="LOCKED-MARK-001",
        customer_id=customer.id,
        creator=admin,
        status="completed",
        archive=False,
        create_date=NOW,
    )
    assigned_box = CargoTable(
        uid="locked-api-box",
        origin_id="LOCKED-BOX-001",
        tag="LOCKED-MARK-001_1",
        target_order_uid=order.uid,
        packing_list_uid=packing_list.uid,
        transfer_id="ORIGINAL-A",
        waybill_id="WAYBILL-A",
        item_name="测试商品",
        real_en_name="测试商品",
        count=1,
        piece_count=1,
        box_number=1,
        weight=5.0,
        status=1,
        date=NOW,
        archive=False,
        create_date=NOW,
    )
    unassigned_box = CargoTable(
        uid="unassigned-api-box",
        origin_id="UNASSIGNED-BOX-001",
        tag="LOCKED-MARK-001_2",
        target_order_uid=None,
        packing_list_uid=packing_list.uid,
        transfer_id="",
        waybill_id="",
        item_name="待分配商品",
        real_en_name="待分配商品",
        count=1,
        piece_count=1,
        box_number=2,
        weight=2.0,
        status=0,
        archive=False,
        create_date=NOW,
    )
    session.add_all([order, packing_list, assigned_box, unassigned_box])
    session.flush()
    cost = BoxCostRecordTable(
        box_uid=assigned_box.uid,
        packing_list_uid=packing_list.uid,
        order_uid=order.uid,
        transportation_name="测试渠道",
        waybill_id="WAYBILL-A",
        weight=5.0,
        unit_cost=Decimal("10.00"),
        total_cost=Decimal("50.00"),
        create_date=NOW,
    )
    receipt = PaymentReceiptTable(
        receipt_no="RCPT-LOCKED-001",
        customer_id=customer.id,
        customer_name=customer.name,
        receipt_date="2026-09-16",
        payment_method="bank_transfer",
        status="approved",
        settlement_status="unsettled",
        creator_id=admin.id,
        creator_name=admin.name,
        reviewer_name="财务测试",
        review_date=NOW,
        create_date=NOW,
        update_date=NOW,
    )
    session.add_all([cost, receipt])
    session.flush()
    session.add(
        PaymentReceiptItemTable(
            receipt_id=receipt.id,
            order_uid=order.uid,
            order_id=order.order_id,
            receivable_snapshot=Decimal("100.00"),
            received_before=Decimal("0.00"),
            amount=Decimal("50.00"),
            remaining_after=Decimal("50.00"),
        )
    )
    ensure_baseline(session, order.uid, snapshot_order(session, order.uid))
    session.commit()
    return {
        "order_uid": order.uid,
        "box_uid": assigned_box.uid,
        "unassigned_box_uid": unassigned_box.uid,
        "cost_id": cost.id,
    }


@pytest.mark.parametrize("token_fixture", ["admin_token", "store_manager_token"])
def test_version_list_is_role_protected_and_paginated(
    client, setup_test_database, request, token_fixture
):
    session = setup_test_database
    order = _seed_versioned_order(session)
    order_uid = order.uid
    for receiver in ("B", "C", "D"):
        order_model.update(order_uid, {"receiver": receiver})

    response = client.get(
        f"/api/orders/{order_uid}/versions?p=1&s=2",
        headers=_headers(request.getfixturevalue(token_fixture)),
    )

    assert response.status_code == 200
    page = _page_data(response)
    assert page["total"] == 4
    assert [row["version_no"] for row in page["items"]] == [4, 3]
    assert page["page"] == 1
    assert page["page_size"] == 2


def test_history_endpoints_reject_non_privileged_role(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    order = _seed_versioned_order(session)
    order_uid = order.uid

    for url in (
        f"/api/orders/{order_uid}/versions",
        f"/api/orders/{order_uid}/versions/1",
        "/api/order-history?deleted_only=1",
    ):
        response = client.get(url, headers=_headers(salesperson_token))
        assert response.status_code == 403


def test_version_detail_reconstructs_requested_snapshot(
    client, setup_test_database, admin_token
):
    session = setup_test_database
    order = _seed_versioned_order(session)
    order_uid = order.uid
    order_model.update(order_uid, {"receiver": "B"})

    response = client.get(
        f"/api/orders/{order_uid}/versions/2",
        headers=_headers(admin_token),
    )

    assert response.status_code == 200
    detail = response.get_json()["data"]
    assert detail["version_no"] == 2
    assert detail["snapshot"]["order"]["receiver"] == "B"
    assert detail["changes"][0]["before_data"]["receiver"] == "A"
    assert detail["changes"][0]["after_data"]["receiver"] == "B"


def test_deleted_history_search_uses_tombstone_metadata(
    client, setup_test_database, store_manager_token
):
    session = setup_test_database
    order = _seed_versioned_order(session, uid="deleted-api-order")
    order_uid = order.uid
    order_model.delete(order_uid)

    response = client.get(
        "/api/order-history?deleted_only=1&q=API-VERSION-001&p=1&s=10",
        headers=_headers(store_manager_token),
    )

    assert response.status_code == 200
    page = _page_data(response)
    assert page["total"] == 1
    assert page["items"][0]["order_uid"] == "deleted-api-order"
    assert page["items"][0]["deleted"] is True


def test_outbound_order_allows_business_content_edits(
    client, setup_test_database, admin_token
):
    world = _seed_outbound_box_world(setup_test_database)

    response = client.put(
        f"/api/orders/{world['order_uid']}",
        headers=_headers(admin_token),
        json={"receiver": "允许写入的新收件人"},
    )

    assert response.status_code == 200
    setup_test_database.expire_all()
    assert (
        setup_test_database.query(OrderTable)
        .filter_by(uid=world["order_uid"])
        .one()
        .receiver
        == "允许写入的新收件人"
    )


def test_order_detail_exposes_role_policy_without_lock_state(
    client, setup_test_database, admin_token
):
    world = _seed_outbound_box_world(setup_test_database)
    response = client.get(f"/api/orders/{world['order_uid']}", headers=_headers(admin_token))
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["current_version"] == 1
    assert not {"receipt_locked", "receipt_lock", "business_lock", "financial_lock", "lock_warnings"} & data.keys()
    policy = data["edit_policy"]
    for field in ("order_fields", "transportation", "order_weight", "box_content", "tracking_numbers", "box_membership", "customer_assignment"):
        assert policy[field] is True
    assert not {"lock_status", "revision_open", "financial_locked", "has_receipt_history"} & policy.keys()


def test_outbound_box_identity_is_fixed_while_waybill_can_be_corrected(
    client, setup_test_database, admin_token
):
    world = _seed_outbound_box_world(setup_test_database)

    for payload, expected_status in (
        ({"transfer_id": "ORIGINAL-B"}, 409),
        ({"waybill_id": "WAYBILL-B"}, 200),
    ):
        response = client.put(
            f"/api/cargo/{world['box_uid']}",
            headers=_headers(admin_token),
            json=payload,
        )
        assert response.status_code == expected_status
        if expected_status == 409:
            assert response.get_json()["msg"] == BOX_IDENTITY_IMMUTABLE_MESSAGE


def test_receipt_history_allows_order_weight_and_membership_edits(
    client, setup_test_database, admin_token
):
    world = _seed_outbound_box_world(setup_test_database)

    responses = [
        client.put(
            f"/api/orders/{world['order_uid']}",
            headers=_headers(admin_token),
            json={"total_weight": 9.0},
        ),
        client.put(
            f"/api/box/{world['box_uid']}/weigh",
            headers=_headers(admin_token),
            json={"weight": 9.0},
        ),
        client.post(
            "/api/cargo/unbind",
            headers=_headers(admin_token),
            json={"cargo_id_list": [world["box_uid"]]},
        ),
        client.post(
            "/api/boxes/assign",
            headers=_headers(admin_token),
            json={
                "box_uids": [world["unassigned_box_uid"]],
                "order_uid": world["order_uid"],
            },
        ),
    ]

    assert [response.status_code for response in responses] == [200, 409, 200, 200]


def test_outbound_waybill_can_change_without_cost_rewrite(
    client, setup_test_database, admin_token
):
    session = setup_test_database
    world = _seed_outbound_box_world(session)
    session.expire_all()
    cost_before = session.query(BoxCostRecordTable).filter_by(id=world["cost_id"]).one()
    before_values = {
        "id": cost_before.id,
        "waybill_id": cost_before.waybill_id,
        "weight": float(cost_before.weight),
        "unit_cost": float(cost_before.unit_cost),
        "total_cost": float(cost_before.total_cost),
    }

    response = client.put(
        f"/api/box/{world['box_uid']}",
        headers=_headers(admin_token),
        json={"waybill_id": "WAYBILL-B"},
    )

    assert response.status_code == 200
    session.expire_all()
    box = session.query(CargoTable).filter_by(uid=world["box_uid"]).one()
    assert box.transfer_id == "ORIGINAL-A"
    assert box.waybill_id == "WAYBILL-B"
    assert box.status == 1
    costs = session.query(BoxCostRecordTable).filter_by(box_uid=box.uid).all()
    assert len(costs) == 1
    assert {
        "id": costs[0].id,
        "waybill_id": costs[0].waybill_id,
        "weight": float(costs[0].weight),
        "unit_cost": float(costs[0].unit_cost),
        "total_cost": float(costs[0].total_cost),
    } == before_values
    latest = (
        session.query(OrderVersionTable)
        .filter(OrderVersionTable.order_uid == world["order_uid"])
        .order_by(OrderVersionTable.version_no.desc())
        .first()
    )
    box_change = next(
        change
        for change in latest.changes
        if change.entity_type == "box" and change.entity_uid == box.uid
    )
    assert "WAYBILL-A" in box_change.before_data
    assert "WAYBILL-B" in box_change.after_data


def test_generic_cargo_routes_cannot_bypass_box_role_permissions(
    client, setup_test_database
):
    world = _seed_outbound_box_world(setup_test_database)
    finance_token = create_jwt(
        {
            "user_id": 99,
            "name": "财务测试",
            "role": "finance",
            "roles": ["finance"],
        }
    )

    responses = [
        client.post(
            "/api/cargo/archive",
            headers=_headers(finance_token),
            json={"cargo_id_list": [world["box_uid"]]},
        ),
        client.delete(
            "/api/cargo",
            headers=_headers(finance_token),
            json={"cargo_id_list": [world["box_uid"]]},
        ),
        client.post(
            "/api/cargo/unbind",
            headers=_headers(finance_token),
            json={"cargo_id_list": [world["box_uid"]]},
        ),
        client.post(
            f"/api/cargo/{world['box_uid']}/input",
            headers=_headers(finance_token),
            json={"weight": 6, "count": 2},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


def test_open_revision_index_route_is_removed(client, admin_token):
    response = client.get("/api/admin/order-revisions/open", headers=_headers(admin_token))
    assert response.status_code == 404
