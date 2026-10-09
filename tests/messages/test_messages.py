"""Recipient security, transactional delivery, and explicit reading semantics."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from Auth import create_jwt
from data.message import MessageTable
from data.user.User import UserTable
from services import message_service as service


def _headers(user_id=1, role="salesperson", **payload):
    return {"x-token": create_jwt({"user_id": user_id, "role": role, **payload})}


def _send(database, recipient_id=1, **values):
    with database() as session:
        message = service.send_message(
            session, recipient_id=recipient_id, title="账单被退回", body="请核对金额。", **values,
        )
        uid = message.uid
        session.commit()
        return uid


def test_delivery_commits_or_rolls_back_with_business_changes(database):
    with database() as session:
        user = session.get(UserTable, 1)
        user.name = "业务变更"
        service.send_message(session, recipient_id=1, title="待处理", body="业务事件", event_key="rollback")
        session.rollback()
    with database() as session:
        assert session.query(MessageTable).count() == 0
        assert session.get(UserTable, 1).name == "员工1"
        session.get(UserTable, 1).name = "已提交"
        service.send_message(session, recipient_id=1, title="待处理", body="业务事件", event_key="commit")
        session.commit()
    with database() as session:
        assert session.query(MessageTable).count() == 1
        assert session.get(UserTable, 1).name == "已提交"


def test_delivery_never_commits_even_without_pending_business_changes(database):
    with database() as session:
        service.send_message(session, recipient_id=1, title="待处理", body="业务事件")
        session.rollback()
    with database() as session:
        assert session.query(MessageTable).count() == 0


def test_event_deduplication_is_per_recipient_and_preserves_original_notice(database):
    first = _send(database, event_key="finance:return:12:2")
    retry = _send(database, event_key="finance:return:12:2")
    another = _send(database, recipient_id=2, event_key="finance:return:12:2")
    next_event = _send(database, event_key="finance:return:12:3")
    assert first == retry
    assert len({first, another, next_event}) == 3
    with database() as session:
        assert session.query(MessageTable).count() == 3
        assert session.get(MessageTable, first).category == "system"
        # Direct writes still cannot bypass deduplication.
        session.add(MessageTable(uid="duplicate", recipient_id=1, title="重复", body="正文",
                                 source_name="系统", category="system", created_at="2026-10-07",
                                 event_key="finance:return:12:2"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_conflict_uses_savepoint_and_keeps_business_change(database, monkeypatch):
    first = _send(database, event_key="race")
    with database() as session:
        original_query = session.query
        first_query = True

        def stale_query(*entities, **kwargs):
            nonlocal first_query
            query = original_query(*entities, **kwargs)
            if entities == (MessageTable,) and first_query:
                first_query = False
                original_filter = query.filter_by

                def stale_filter(**filters):
                    filtered = original_filter(**filters)
                    filtered.first = lambda: None
                    return filtered

                query.filter_by = stale_filter
            return query

        monkeypatch.setattr(session, "query", stale_query)
        session.get(UserTable, 1).name = "保留业务修改"
        retry = service.send_message(session, recipient_id=1, title="账单被退回", body="请核对金额。", event_key="race")
        assert retry.uid == first
        session.commit()
    with database() as session:
        assert session.query(MessageTable).count() == 1
        assert session.get(UserTable, 1).name == "保留业务修改"


@pytest.mark.parametrize("identity", ["user_id", "id", "uid"])
def test_inbox_resolves_only_authenticated_identity(client, database, identity):
    own = _send(database)
    _send(database, recipient_id=2)
    headers = {"x-token": create_jwt({identity: 1, "role": "admin"})}
    response = client.get("/api/messages?recipient_id=2&user_id=2", headers=headers)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["total"] == 1
    assert data["unread_count"] == 1
    assert [item["uid"] for item in data["items"]] == [own]


def test_admin_cannot_read_or_mark_another_employees_message(client, database):
    foreign = _send(database, recipient_id=2)
    headers = _headers(role="admin")
    for method, path in [("get", f"/api/messages/{foreign}"), ("post", f"/api/messages/{foreign}/read")]:
        response = getattr(client, method)(path, headers=headers)
        assert response.status_code == 404
        missing = getattr(client, method)(path.replace(foreign, "missing"), headers=headers)
        assert missing.get_json() == response.get_json()
    assert service.unread_count({"user_id": 2}) == {"unread_count": 1}


def test_list_and_detail_do_not_mark_read_and_read_is_idempotent(client, database):
    uid = _send(database, action_path="/finance/payments?payment_id=12", business_type="payment", business_id=12)
    for path in ("/api/messages", f"/api/messages/{uid}"):
        assert client.get(path, headers=_headers()).status_code == 200
    assert service.unread_count({"user_id": 1}) == {"unread_count": 1}
    first = client.post(f"/api/messages/{uid}/read", headers=_headers()).get_json()["data"]
    second = client.post(f"/api/messages/{uid}/read", headers=_headers()).get_json()["data"]
    assert first == second
    assert first["is_read"] is True
    assert first["read_at"]
    assert first["business_id"] == "12"
    assert client.get("/api/messages/unread-count", headers=_headers()).get_json()["data"] == {"unread_count": 0}


def test_mark_all_only_changes_current_recipient_and_preserves_first_read(client, database):
    first = _send(database)
    second = _send(database)
    foreign = _send(database, recipient_id=2)
    old_read = service.mark_read(first, {"user_id": 1})["read_at"]
    data = client.post("/api/messages/read-all", headers=_headers(), json={"recipient_id": 2}).get_json()["data"]
    assert data == {"updated_count": 1, "unread_count": 0}
    assert service.get_message(first, {"user_id": 1})["read_at"] == old_read
    assert service.get_message(second, {"user_id": 1})["is_read"]
    assert not service.get_message(foreign, {"user_id": 2})["is_read"]
    assert service.mark_all_read({"user_id": 1}) == {"updated_count": 0, "unread_count": 0}


def test_pagination_status_filters_and_deterministic_order(client, database):
    uids = [_send(database) for _ in range(5)]
    with database() as session:
        for index, uid in enumerate(uids):
            session.get(MessageTable, uid).created_at = (datetime(2026, 10, 7) + timedelta(minutes=index)).isoformat()
        session.commit()
    service.mark_read(uids[4], {"user_id": 1})
    data = client.get("/api/messages?page=2&page_size=2", headers=_headers()).get_json()["data"]
    assert [item["uid"] for item in data["items"]] == [uids[2], uids[1]]
    assert data["total"] == 5 and data["unread_count"] == 4
    data = client.get("/api/messages?p=1&s=2&status=unread", headers=_headers()).get_json()["data"]
    assert [item["uid"] for item in data["items"]] == [uids[3], uids[2]]
    assert data["total"] == 4
    data = service.list_messages({"user_id": 1}, status="read")
    assert [item["uid"] for item in data["items"]] == [uids[4]]
    assert service.list_messages({"user_id": 1}, page=99)["items"] == []
    assert service.list_messages({"user_id": 1}, page_size=1000)["page_size"] == 100


@pytest.mark.parametrize("query", ["page=0", "page=oops", "page_size=-1", "status=completed"])
def test_invalid_filters_fail_explicitly(client, database, query):
    assert client.get(f"/api/messages?{query}", headers=_headers()).status_code == 400


@pytest.mark.parametrize("path", ["/api/messages", "/api/messages/unread-count", "/api/messages/missing"])
def test_api_requires_authentication(client, database, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"x-token": "invalid"}).status_code == 401


@pytest.mark.parametrize("user_id", [3, 999, True])
def test_rejected_deleted_or_invalid_actor_cannot_access_inbox(client, database, user_id):
    assert client.get("/api/messages", headers=_headers(user_id)).status_code == 403


def test_same_event_with_different_content_is_a_conflict(database):
    _send(database, event_key="same-event")
    with pytest.raises(service.MessageConflictError):
        _send(database, event_key="same-event", category="changed")


@pytest.mark.parametrize("path", ["https://example.com", "//example.com", "/\\example.com", "javascript:alert(1)", "/order\n/12"])
def test_delivery_rejects_external_or_malformed_action_paths(database, path):
    with database() as session, pytest.raises(ValueError, match="站内路径"):
        service.send_message(session, recipient_id=1, title="提醒", body="正文", action_path=path)


def test_missing_recipient_and_empty_message_are_rejected(database):
    with database() as session:
        with pytest.raises(LookupError):
            service.send_message(session, recipient_id=99, title="提醒", body="正文")
        with pytest.raises(ValueError):
            service.send_message(session, recipient_id=1, title=" ", body="正文")


def test_employee_deletion_cascades_only_that_employees_inbox(database):
    _send(database, recipient_id=1)
    kept_uid = _send(database, recipient_id=2)
    with database() as session:
        session.delete(session.get(UserTable, 1))
        session.commit()
    with database() as session:
        assert [row.uid for row in session.query(MessageTable).all()] == [kept_uid]
