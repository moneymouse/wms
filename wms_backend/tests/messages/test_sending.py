"""Authenticated generic send API and live role enforcement."""

import pytest

from Auth import create_jwt
from data.message import MessageTable
from data.user.Role import RoleTable
from data.user.User import UserTable


def _headers(user_id=1, **claims):
    return {"x-token": create_jwt({"user_id": user_id, "role": "admin", **claims})}


def _body(**fields):
    return {
        "recipient_id": 2, "title": "待处理事务", "body": "请查看对应页面。",
        "event_key": "source:entity:version", "category": "custom_service",
        "action_path": "/orders/order-12?tab=tracking", "business_type": "order", "business_id": "order-12",
        **fields,
    }


def _role(database, user_id, name):
    with database() as session:
        role = session.query(RoleTable).filter_by(name=name).first()
        if role is None:
            role = RoleTable(name=name, label=name)
            session.add(role)
        session.get(UserTable, user_id).roles = [role]
        session.commit()


@pytest.mark.parametrize("role", ["admin", "store_manager", "finance", "clerk"])
def test_approved_authorized_roles_can_send_and_source_uses_live_employee_name(client, database, role):
    _role(database, 1, role)
    response = client.post("/api/messages", headers=_headers(name="伪造姓名", role="salesperson"), json=_body())
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["source_name"] == "员工1"
    assert data["recipient_id"] == 2
    assert data["category"] == "custom_service"
    assert data["action_path"] == "/orders/order-12?tab=tracking"
    assert not data["is_read"]
    assert client.get("/api/messages", headers=_headers(2)).get_json()["data"]["items"][0]["uid"] == data["uid"]


@pytest.mark.parametrize("role", ["salesperson", "worker", None])
def test_nonprivileged_employee_cannot_send_even_with_forged_admin_role_claim(client, database, role):
    if role:
        _role(database, 1, role)
    assert client.post("/api/messages", headers=_headers(), json=_body()).status_code == 403
    with database() as session:
        assert session.query(MessageTable).count() == 0


def test_rejected_or_missing_sender_and_unauthenticated_requests_cannot_send(client, database):
    _role(database, 3, "admin")
    for user_id in (3, 999):
        assert client.post("/api/messages", headers=_headers(user_id), json=_body()).status_code == 403
    assert client.post("/api/messages", json=_body()).status_code == 401
    assert client.post("/api/messages", headers={"x-token": "invalid"}, json=_body()).status_code == 401


def test_same_event_is_idempotent_and_changed_payload_is_conflict(client, database):
    _role(database, 1, "finance")
    first = client.post("/api/messages", headers=_headers(), json=_body())
    second = client.post("/api/messages", headers=_headers(), json=_body())
    assert first.get_json() == second.get_json()
    changed = client.post("/api/messages", headers=_headers(), json=_body(body="另一条事务"))
    assert changed.status_code == 409
    with database() as session:
        assert session.query(MessageTable).count() == 1


def test_http_event_keys_are_separate_for_each_authenticated_sender(client, database):
    _role(database, 1, "finance")
    _role(database, 2, "clerk")
    first = client.post("/api/messages", headers=_headers(), json=_body())
    second = client.post("/api/messages", headers=_headers(2), json=_body())
    assert first.status_code == second.status_code == 200
    assert first.get_json()["data"]["uid"] != second.get_json()["data"]["uid"]
    with database() as session:
        keys = [row.event_key for row in session.query(MessageTable).all()]
        assert len(keys) == len(set(keys)) == 2
        assert all(len(key) <= 128 for key in keys)


@pytest.mark.parametrize("recipient_id,status", [(3, 400), (999, 404), (True, 400), (None, 400), (2147483648, 400)])
def test_send_requires_one_approved_recipient(client, database, recipient_id, status):
    _role(database, 1, "admin")
    assert client.post("/api/messages", headers=_headers(), json=_body(recipient_id=recipient_id)).status_code == status


@pytest.mark.parametrize("json_body", [[], "plain text", None])
def test_send_rejects_non_object_json(client, database, json_body):
    _role(database, 1, "admin")
    assert client.post("/api/messages", headers=_headers(), json=json_body).status_code == 400


def test_send_rejects_malformed_json_and_untrusted_sender_fields(client, database):
    _role(database, 1, "admin")
    assert client.post("/api/messages", headers=_headers(), data="{bad-json", content_type="application/json").status_code == 400
    response = client.post("/api/messages", headers=_headers(), json=_body(source_name="财务主管"))
    assert response.status_code == 400
    assert "source_name" in response.get_json()["msg"]
    assert client.post("/api/messages", headers=_headers(), json=_body(sender_id=2)).status_code == 400


@pytest.mark.parametrize("fields", [
    {"event_key": None}, {"event_key": " "}, {"event_key": "a" * 129},
    {"title": "a" * 201}, {"body": "a" * 10001}, {"category": "a" * 65},
    {"business_type": "a" * 65}, {"business_id": "a" * 129},
    {"business_id": {"id": 1}}, {"business_id": [1]}, {"business_id": True},
    {"action_path": "https://example.com"}, {"action_path": "//example.com"}, {"action_path": "/\\example.com"},
    {"action_path": "/orders/raw space"}, {"action_path": "/orders/with\x7fcontrol"},
])
def test_send_rejects_invalid_fields_and_unsafe_paths(client, database, fields):
    _role(database, 1, "admin")
    assert client.post("/api/messages", headers=_headers(), json=_body(**fields)).status_code == 400


def test_minimal_payload_has_generic_defaults(client, database):
    _role(database, 1, "admin")
    response = client.post("/api/messages", headers=_headers(), json={
        "recipient_id": 2, "title": "提醒", "body": "正文", "event_key": "minimal",
    })
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["category"] == "system"
    assert data["business_type"] is data["business_id"] is data["action_path"] is None
