"""Shipping confirmation export selection, agent lookup and HTTP contract."""

from unittest.mock import patch

import pytest

from data.DB import CargoTable, OrderTable, TransportationModeTable
from services.shipping_confirmation_service import (
    ShippingConfirmationError,
    load_shipping_confirmation_details,
)


def _add_order(session, uid="order-a", **fields):
    order = OrderTable(
        uid=uid,
        order_id=f"ORDER-{uid}",
        customer_name="测试客户",
        archive=False,
        **fields,
    )
    session.add(order)
    return order


def _add_box(session, uid="box-a", order_uid="order-a", **fields):
    box = CargoTable(
        uid=uid,
        target_order_uid=order_uid,
        tag=f"MARK-{uid}",
        transfer_id=f"ORIGINAL-{uid}",
        archive=False,
        **fields,
    )
    session.add(box)
    return box


@pytest.mark.parametrize(
    "group, expected",
    [("极飞", "JF"), ("统仓", "TC"), ("YX", "YX"),
     ("JF", "JF"), ("TC", "TC"), (" 自营 ", "自营"), ("", "")],
)
def test_agent_comes_from_exact_channel_group(setup_test_database, group, expected):
    session = setup_test_database
    session.add(TransportationModeTable(name="配置渠道", channel_group=group))
    _add_order(session, transportation="配置渠道")
    _add_box(session)
    session.commit()

    detail = load_shipping_confirmation_details(["order-a"])[0]

    assert detail["agent_name"] == expected
    assert detail["customer_name"] == "测试客户"
    assert detail["boxes"] == [{
        "uid": "box-a", "tag": "MARK-box-a", "transfer_id": "ORIGINAL-box-a"
    }]


def test_hand_entered_channel_does_not_infer_agent_from_prefix(setup_test_database):
    session = setup_test_database
    session.add(TransportationModeTable(name="极飞已配置", channel_group="极飞"))
    _add_order(session, transportation="极飞手工渠道")
    _add_box(session)
    session.commit()

    assert load_shipping_confirmation_details(["order-a"])[0]["agent_name"] == ""


def test_existing_order_keeps_archived_channel_group(setup_test_database):
    session = setup_test_database
    session.add(TransportationModeTable(
        name="已归档渠道", channel_group="统仓", archive=True
    ))
    _add_order(session, transportation="已归档渠道")
    _add_box(session)
    session.commit()

    assert load_shipping_confirmation_details(["order-a"])[0]["agent_name"] == "TC"


@pytest.fixture
def orders_with_boxes(setup_test_database):
    session = setup_test_database
    _add_order(session)
    _add_order(session, "order-b")
    _add_order(session, "empty-order")
    _add_order(session, "outside-order")
    _add_box(session, "a-1", create_date="2026-10-05 10:01")
    _add_box(session, "a-2", create_date="2026-10-05 10:02")
    archived_box = _add_box(session, "a-archived")
    archived_box.archive = True
    _add_box(session, "b-1", "order-b")
    _add_box(session, "outside-box", "outside-order")
    session.commit()
    return session


@pytest.mark.parametrize("cargo_list", [None, []])
def test_full_export_keeps_order_order_and_all_active_boxes(orders_with_boxes, cargo_list):
    details = load_shipping_confirmation_details(
        ["order-b", "empty-order", "order-a", "order-b"], cargo_list
    )

    assert [detail["uid"] for detail in details] == ["order-b", "empty-order", "order-a"]
    assert details[1]["boxes"] == []
    assert [box["uid"] for box in details[2]["boxes"]] == ["a-1", "a-2"]


def test_box_selection_is_limited_to_active_boxes_in_selected_orders(orders_with_boxes):
    details = load_shipping_confirmation_details(
        ["order-b", "empty-order", "order-a"],
        ["outside-box", "a-2", "a-archived", "a-1", "a-2"],
    )

    assert [detail["uid"] for detail in details] == ["order-a"]
    assert [box["uid"] for box in details[0]["boxes"]] == ["a-2", "a-1"]


@pytest.mark.parametrize("uid_list,cargo_list", [
    (None, None), ([], None), ("order-a", None), ([""], None),
    ([1], None), (["order-a"], "box-a"), (["order-a"], [None]),
])
def test_selection_validation(uid_list, cargo_list):
    with pytest.raises(ShippingConfirmationError) as error:
        load_shipping_confirmation_details(uid_list, cargo_list)
    assert error.value.status == 400


@pytest.mark.parametrize("order_uid", ["missing-order", "archived-order"])
def test_missing_or_archived_order_rejects_whole_export(setup_test_database, order_uid):
    session = setup_test_database
    _add_order(session)
    archived_order = _add_order(session, "archived-order")
    archived_order.archive = True
    _add_box(session)
    session.commit()

    with pytest.raises(ShippingConfirmationError) as error:
        load_shipping_confirmation_details(["order-a", order_uid])
    assert error.value.status == 404
    assert order_uid in str(error.value)


@pytest.mark.parametrize("uid_list,cargo_list", [
    (["empty-order"], None), (["order-a"], ["outside-box", "a-archived"]),
])
def test_export_without_matching_boxes_is_rejected(orders_with_boxes, uid_list, cargo_list):
    with pytest.raises(ShippingConfirmationError, match="没有可导出的箱子"):
        load_shipping_confirmation_details(uid_list, cargo_list)


def test_pdf_endpoint_returns_attachment(client, employee_token, orders_with_boxes):
    response = client.post(
        "/api/orders/shipping-confirmation/pdf",
        headers={"x-token": employee_token},
        json={"uid_list": ["order-a"], "cargo_list": ["a-2"]},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "shipping-confirmation.pdf" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_pdf_endpoint_requires_auth(client):
    response = client.post(
        "/api/orders/shipping-confirmation/pdf", json={"uid_list": ["order-a"]}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("data,status", [
    ([], 400), ({}, 400), ({"uid_list": "order-a"}, 400),
    ({"uid_list": ["missing-order"]}, 404),
])
def test_pdf_endpoint_errors_are_json(client, employee_token, data, status):
    response = client.post(
        "/api/orders/shipping-confirmation/pdf",
        headers={"x-token": employee_token}, json=data,
    )

    assert response.status_code == status
    assert response.get_json()["code"] == status
    assert response.get_json()["msg"]


def test_pdf_endpoint_handles_renderer_failure(client, employee_token, orders_with_boxes):
    with patch(
        "controllers.order_controller.build_shipping_confirmation_pdf",
        side_effect=RuntimeError("renderer details"),
    ):
        response = client.post(
            "/api/orders/shipping-confirmation/pdf",
            headers={"x-token": employee_token}, json={"uid_list": ["order-a"]},
        )

    assert response.status_code == 500
    assert response.get_json() == {"code": 500, "msg": "出货确认单生成失败，请稍后重试"}
