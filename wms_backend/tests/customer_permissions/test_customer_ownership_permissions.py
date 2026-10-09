"""Regression coverage for creator scope and current-order contact permissions."""

from unittest.mock import patch

import pytest

from Auth import create_jwt
from data.DB import OrderTable
from data.customer.Customer import CustomerTable
from data.user.User import UserTable, user_model


def _headers(**payload):
    return {"x-token": create_jwt({"name": "权限测试", **payload})}


@pytest.fixture
def customer_permissions(setup_test_database):
    session = setup_test_database
    for user_id in (1, 2, 3, 8):
        session.add(UserTable(
            id=user_id, phone=f"138000000{user_id:02d}", name=f"用户{user_id}",
            password="test", status="approved",
        ))
    own = CustomerTable(id=101, name="自己创建", phone="13900000101", wechat="wx_own", created_by_id=3)
    other = CustomerTable(id=102, name="他人创建", phone="13900000102", wechat="wx_other", created_by_id=8)
    legacy = CustomerTable(id=103, name="历史客户", phone="13900000103", wechat="wx_legacy")
    assigned = OrderTable(uid="assigned", order_id="OWN-ORDER", salesman_id=3, customers=[other])
    foreign = OrderTable(uid="foreign", order_id="OTHER-ORDER", salesman_id=8, customers=[own])
    unassigned = OrderTable(uid="unassigned", order_id="UNASSIGNED", customers=[own])
    empty = OrderTable(uid="empty", order_id="NO-CUSTOMER", salesman_id=3)
    session.add_all([own, other, legacy, assigned, foreign, unassigned, empty])
    session.commit()
    with patch("data.customer.Customer.SessionFactory", return_value=session), patch(
        "services.order_service.SessionFactory", return_value=session
    ):
        yield session


def test_salesperson_management_lists_only_created_customers(client, customer_permissions):
    response = client.get("/api/customers_detail", headers=_headers(user_id=3, role="salesperson"))
    assert response.status_code == 200
    assert response.get_json()["data"] == [{
        "id": 101, "name": "自己创建", "phone": "13900000101", "wechat": "wx_own",
    }]


@pytest.mark.parametrize("payload", [
    {"user_id": 1, "role": "admin"},
    {"user_id": 2, "role": "store_manager"},
    {"user_id": 3, "role": "salesperson", "roles": ["admin"]},
    {"user_id": 3, "role": "store_manager", "roles": ["salesperson"]},
    {"user_id": 3, "roles": ["salesperson", "store_manager"]},
])
def test_managers_keep_global_management_and_order_contact_access(client, customer_permissions, payload):
    response = client.get("/api/customers_detail", headers=_headers(**payload))
    assert response.status_code == 200
    assert {row["id"] for row in response.get_json()["data"]} == {101, 102, 103}
    for url in ("/api/customer_detail/102", "/api/orders/foreign/customer-contact"):
        response = client.get(url, headers=_headers(**payload))
        assert response.status_code == 200
        assert "phone" in response.get_json()["data"]


@pytest.mark.parametrize("identity", [
    {"user_id": 3}, {"id": 3}, {"uid": 3}, {"user_id": "3"},
])
def test_authenticated_creator_is_recorded_and_request_cannot_spoof_it(client, customer_permissions, identity):
    response = client.post(
        "/api/customer", headers=_headers(role="salesperson", **identity),
        json={"name": "新客户", "phone": "13999990000", "wechat": "wx_new", "created_by_id": 8, "user_id": 8},
    )
    assert response.status_code == 200
    customer_id = response.get_json()["data"]["customer_id"]
    customer = customer_permissions.get(CustomerTable, customer_id)
    assert customer.created_by_id == 3
    response = client.get("/api/customers_detail", headers=_headers(role="salesperson", **identity))
    assert {row["id"] for row in response.get_json()["data"]} == {101, customer_id}


@pytest.mark.parametrize("customer_id", [102, 103])
def test_direct_customer_read_update_delete_cannot_bypass_creator_scope(client, customer_permissions, customer_id):
    headers = _headers(user_id=3, role="salesperson")
    requests = [
        client.get(f"/api/customer_detail/{customer_id}?order_uid=assigned", headers=headers),
        client.put(f"/api/customer/{customer_id}", headers=headers, json={"phone": "spoof", "created_by_id": 3}),
        client.post(f"/api/del_customer/{customer_id}", headers=headers),
    ]
    for response in requests:
        assert response.status_code == 403
        assert "data" not in response.get_json()
    customer = customer_permissions.get(CustomerTable, customer_id)
    assert customer is not None
    assert customer.phone != "spoof"


def test_salesperson_can_read_and_edit_created_customer_without_reassigning_creator(client, customer_permissions):
    headers = _headers(user_id=3, role="salesperson")
    response = client.get("/api/customer_detail/101", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["wechat"] == "wx_own"
    response = client.put("/api/customer/101", headers=headers, json={"phone": "new-phone", "created_by_id": 8})
    assert response.status_code == 200
    assert response.get_json()["data"]["phone"] == "new-phone"
    assert customer_permissions.get(CustomerTable, 101).created_by_id == 3


def test_salesperson_can_delete_an_unreferenced_created_customer(client, customer_permissions):
    customer_permissions.add(CustomerTable(id=104, name="可删除客户", created_by_id=3))
    customer_permissions.commit()
    response = client.post("/api/del_customer/104", headers=_headers(user_id=3, role="salesperson"))
    assert response.status_code == 200
    assert customer_permissions.get(CustomerTable, 104) is None


def test_order_contacts_depend_on_current_salesman_instead_of_customer_creator(client, customer_permissions):
    headers = _headers(user_id=3, role="salesperson")
    response = client.get("/api/orders/assigned/customer-contact?customer_id=101", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "id": 102, "name": "他人创建", "phone": "13900000102", "wechat": "wx_other",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    for uid in ("foreign", "unassigned"):
        response = client.get(f"/api/orders/{uid}/customer-contact?user_id=8", headers=headers)
        assert response.status_code == 403
        assert "data" not in response.get_json()


def test_reassigned_order_immediately_revokes_old_salesman_contact_access(client, customer_permissions):
    customer_permissions.get(OrderTable, "assigned").salesman_id = 8
    customer_permissions.commit()
    response = client.get("/api/orders/assigned/customer-contact", headers=_headers(user_id=3, role="salesperson"))
    assert response.status_code == 403
    response = client.get("/api/orders/assigned/customer-contact", headers=_headers(user_id=8, role="salesperson"))
    assert response.status_code == 200
    assert response.get_json()["data"]["id"] == 102


@pytest.mark.parametrize("payload", [{"role": "clerk"}, {"role": "finance"}, {"roles": ["worker"]}])
def test_other_roles_cannot_get_sensitive_contacts(client, customer_permissions, payload):
    for url in ("/api/customers_detail", "/api/customer_detail/101", "/api/orders/assigned/customer-contact"):
        assert client.get(url, headers=_headers(user_id=3, **payload)).status_code == 403


@pytest.mark.parametrize("identity", [{}, {"user_id": "invalid"}, {"user_id": True}, {"user_id": 0}])
def test_missing_or_invalid_salesperson_identity_fails_closed(client, customer_permissions, identity):
    headers = _headers(role="salesperson", **identity)
    response = client.get("/api/customers_detail", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"] == []
    assert client.get("/api/customer_detail/101", headers=headers).status_code == 403
    assert client.get("/api/orders/assigned/customer-contact", headers=headers).status_code == 403
    assert client.post("/api/customer", headers=headers, json={"name": "无身份创建"}).status_code == 403


def test_order_contact_missing_order_empty_customer_and_auth_contract(client, customer_permissions):
    headers = _headers(user_id=3, role="salesperson")
    response = client.get("/api/orders/missing/customer-contact", headers=headers)
    assert response.status_code == 404
    response = client.get("/api/orders/empty/customer-contact", headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {"code": 200, "data": None}
    assert client.get("/api/orders/assigned/customer-contact").status_code == 401


def test_archived_order_does_not_expose_contact_even_to_its_salesman(client, customer_permissions):
    customer_permissions.get(OrderTable, "assigned").archive = True
    customer_permissions.commit()
    for headers in (_headers(user_id=3, role="salesperson"), _headers(user_id=1, role="admin")):
        response = client.get("/api/orders/assigned/customer-contact", headers=headers)
        assert response.status_code == 404
        assert "data" not in response.get_json()


def test_regular_customer_picker_keeps_names_and_excludes_contacts(client, customer_permissions):
    response = client.get("/api/customer_list", headers=_headers(user_id=3, role="salesperson"))
    assert response.status_code == 200
    rows = response.get_json()["data"]
    assert {row["id"] for row in rows} == {101, 102, 103}
    assert all(set(row) == {"id", "name"} for row in rows)


def test_sensitive_access_audit_uses_real_authenticated_id(client, customer_permissions):
    with patch("controllers.customer_controller.log_sensitive_access") as log_access:
        client.get("/api/customers_detail", headers=_headers(user_id=3, role="salesperson"))
    assert log_access.call_args.kwargs["user_id"] == 3
    assert log_access.call_args.kwargs["user_role"] == ["salesperson"]
    with patch("utils.audit_log.log_sensitive_access") as log_access:
        client.get("/api/orders/assigned/customer-contact", headers=_headers(user_id=3, role="salesperson"))
    assert log_access.call_args.kwargs["user_id"] == 3


def test_deleting_creator_retains_customer_and_clears_creator_reference(customer_permissions):
    customer_permissions.add(UserTable(id=77, phone="13800000077", name="待删用户", password="test", status="approved"))
    customer_permissions.add(CustomerTable(id=177, name="保留客户", created_by_id=77))
    customer_permissions.commit()
    assert user_model.delete(77) is True
    customer_permissions.expire_all()
    assert customer_permissions.get(CustomerTable, 177).created_by_id is None
