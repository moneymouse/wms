"""Manual registration, atomic notice delivery, live ownership and retry history."""

import pytest

from Auth import create_jwt
from data.DB import CargoTable, OrderTable
from data.message import MessageTable
from data.order_exception import OrderExceptionHistoryTable, OrderExceptionTable
from data.user.User import UserTable
from services import order_exception_service as service


def _actor(user_id=1, **claims):
    return {"user_id": user_id, "role": "salesperson", **claims}


def _headers(user_id=1, **claims):
    return {"x-token": create_jwt(_actor(user_id, **claims))}


def _body(order_uid="order-a", event_key="registration-1", **values):
    return {"order_uid": order_uid, "reason": "收件人联系不上", "event_key": event_key, **values}


def _create(database, actor=None, **values):
    return service.create_exception(_body(**values), actor or _actor())


def _counts(database):
    with database() as session:
        return tuple(session.query(model).count() for model in (
            OrderExceptionTable, OrderExceptionHistoryTable, MessageTable,
        ))


@pytest.mark.parametrize("cargo_uid", [None, "cargo-a"])
def test_manual_registration_links_order_or_parcel_and_notifies_owner(client, database, cargo_uid):
    body = _body(**({"cargo_uid": cargo_uid} if cargo_uid else {}))
    response = client.post("/api/order-exceptions", headers=_headers(), json=body)
    assert response.status_code == 200
    result = response.get_json()["data"]
    assert result["order_uid"] == "order-a"
    assert result["cargo_uid"] == cargo_uid
    assert result["status"] == "open"
    assert result["salesman_id"] == 1
    assert result["transfer_id"] == ("ORIGINAL-A" if cargo_uid else None)
    detail = client.get(f"/api/order-exceptions/{result['uid']}", headers=_headers()).get_json()["data"]
    assert detail["transfer_id"] == result["transfer_id"]
    assert [(row["action"], row["note"]) for row in detail["history"]] == [("registered", body["reason"])]
    with database() as session:
        notice = session.query(MessageTable).one()
        assert notice.recipient_id == 1
        assert notice.action_path.startswith("/order-exceptions")
        assert result["uid"] in notice.action_path
        assert notice.business_id in {result["uid"], "order-a", cargo_uid}
        assert body["reason"] in notice.body
        if cargo_uid:
            assert "ORIGINAL-A" in notice.body
        assert session.get(CargoTable, "cargo-a").status == 1


def test_clerk_can_register_assigned_foreign_order_but_cannot_read_case(client, database):
    response = client.post("/api/order-exceptions", headers=_headers(4), json=_body(order_uid="order-b"))
    assert response.status_code == 200
    uid = response.get_json()["data"]["uid"]
    assert client.get("/api/order-exceptions", headers=_headers(4)).status_code == 403
    assert client.get(f"/api/order-exceptions/{uid}", headers=_headers(4)).status_code in {403, 404}
    with database() as session:
        assert session.query(MessageTable).one().recipient_id == 2


@pytest.mark.parametrize("also_salesperson", [False, True])
def test_clerk_registration_receipt_does_not_leak_existing_foreign_case_metadata(client, database, also_salesperson):
    first = _create(database, reason="private old reason")
    if also_salesperson:
        with database.begin() as session:
            clerk = session.get(UserTable, 4)
            clerk.roles.append(session.get(UserTable, 1).roles[0])
    response = client.post("/api/order-exceptions", headers=_headers(4),
                           json=_body(reason="文员追加登记的新理由", event_key="clerk-registration-2"))
    assert response.status_code == 200
    receipt = response.get_json()["data"]
    assert receipt == {"uid": first["uid"], "order_uid": "order-a", "cargo_uid": None}
    assert "private old reason" not in response.get_data(as_text=True)
    assert not set(receipt).intersection({
        "reason", "source", "created_at", "updated_at", "salesman_name", "history", "status",
    })
    assert _counts(database) == (1, 2, 2)


def test_registration_and_notice_rollback_with_caller_transaction(database):
    with database() as session:
        session.get(UserTable, 1).name = "未提交业务修改"
        service.register_exception(
            session, order_uid="order-a", reason="临时登记", source="manual",
            event_key="caller-rollback", actor=_actor(),
        )
        session.rollback()
    assert _counts(database) == (0, 0, 0)
    with database() as session:
        assert session.get(UserTable, 1).name == "员工1"


@pytest.mark.parametrize("commit", [True, False])
def test_registration_preserves_pending_owner_and_waybill_changes_in_caller_transaction(database, commit):
    with database() as session:
        assert session.autoflush is False
        order = session.get(OrderTable, "order-a")
        cargo = session.get(CargoTable, "cargo-a")
        order.salesman_id = 2
        cargo.waybill_id = "CHANGED-WAYBILL"
        assert order in session.dirty and cargo in session.dirty
        case = service.register_exception(
            session, order_uid="order-a", cargo_uid="cargo-a", reason="新运单投递失败",
            source="17track", event_key="pending-business-change", tracking_status="DeliveryFailure",
            expected_waybill_id="CHANGED-WAYBILL",
        )
        uid = case.uid
        assert order.salesman_id == case.salesman_id == 2
        assert cargo.waybill_id == case.waybill_id == "CHANGED-WAYBILL"
        if commit:
            session.commit()
        else:
            session.rollback()
    with database() as session:
        assert session.get(OrderTable, "order-a").salesman_id == (2 if commit else 1)
        assert session.get(CargoTable, "cargo-a").waybill_id == ("CHANGED-WAYBILL" if commit else "WAYBILL-A")
        if not commit:
            assert session.get(OrderExceptionTable, uid) is None
            assert tuple(session.query(model).count() for model in (
                OrderExceptionTable, OrderExceptionHistoryTable, MessageTable,
            )) == (0, 0, 0)
            return
        case = session.get(OrderExceptionTable, uid)
        assert case.salesman_id == 2 and case.salesman_name == "员工2"
        assert case.transfer_id == "ORIGINAL-A"
        history = session.query(OrderExceptionHistoryTable).one()
        assert history.exception_uid == uid and history.action == "registered"
        assert history.source == "17track" and history.note == "新运单投递失败"
        notice = session.query(MessageTable).one()
        assert notice.recipient_id == 2 and "ORIGINAL-A" in notice.body
    assert _counts(database) == (1, 1, 1)


def test_registration_can_use_unflushed_order_created_by_caller(database):
    with database() as session:
        order = OrderTable(uid="pending-order", order_id="PENDING-ORDER", salesman_id=2, archive=False)
        session.add(order)
        assert order in session.new
        case = service.register_exception(
            session, order_uid="pending-order", reason="待确认地址", source="17track",
            event_key="pending-new-order", tracking_status="Alert",
        )
        uid = case.uid
        session.commit()
    with database() as session:
        assert session.get(OrderTable, "pending-order").salesman_id == 2
        assert session.get(OrderExceptionTable, uid).order_id == "PENDING-ORDER"
        assert session.query(MessageTable).one().recipient_id == 2
    assert _counts(database) == (1, 1, 1)


def test_notice_failure_rolls_back_case_and_retry_creates_exactly_once(database, monkeypatch):
    original = service.send_message

    def fail_delivery(*args, **kwargs):
        raise RuntimeError("simulated delivery failure")

    monkeypatch.setattr(service, "send_message", fail_delivery)
    with pytest.raises(RuntimeError, match="delivery failure"):
        _create(database)
    assert _counts(database) == (0, 0, 0)
    monkeypatch.setattr(service, "send_message", original)
    first = _create(database)
    retry = _create(database)
    assert first["uid"] == retry["uid"]
    assert _counts(database) == (1, 1, 1)


def test_persistent_event_constraint_handles_stale_replay_without_losing_business_change(database, monkeypatch):
    first = _create(database)
    original_replay = service._replay
    missed_once = False

    def stale_replay(session, key, digest):
        nonlocal missed_once
        if not missed_once:
            missed_once = True
            return None
        return original_replay(session, key, digest)

    monkeypatch.setattr(service, "_replay", stale_replay)
    with database() as session:
        session.get(UserTable, 1).name = "保留同事务业务修改"
        replay = service.register_exception(
            session, order_uid="order-a", reason="收件人联系不上", source="manual",
            event_key="registration-1", actor=_actor(),
        )
        assert replay.uid == first["uid"]
        session.commit()
    assert _counts(database) == (1, 1, 1)
    with database() as session:
        assert session.get(UserTable, 1).name == "保留同事务业务修改"


def test_tracking_registration_uses_same_scope_history_and_notice_transaction(database):
    manual = _create(database, cargo_uid="cargo-a")
    with database() as session:
        first = service.register_exception(
            session, order_uid="order-a", cargo_uid="cargo-a", reason="投递失败",
            source="17track", event_key="tracking-event-1", tracking_status="DeliveryFailure",
        )
        retry = service.register_exception(
            session, order_uid="order-a", cargo_uid="cargo-a", reason="投递失败",
            source="17track", event_key="tracking-event-1", tracking_status="DeliveryFailure",
        )
        assert first.uid == retry.uid == manual["uid"]
        session.commit()
    detail = service.get_exception(manual["uid"], _actor())
    assert [row["source"] for row in detail["history"]] == ["manual", "17track"]
    assert detail["history"][1]["tracking_status"] == "DeliveryFailure"
    assert _counts(database) == (1, 2, 2)
    with database() as session:
        assert session.get(CargoTable, "cargo-a").status == 1


def test_tracking_registration_rechecks_locked_parcel_waybill_before_writing(database):
    with database() as session:
        with pytest.raises(service.ExceptionConflictError):
            service.register_exception(
                session, order_uid="order-a", cargo_uid="cargo-a", reason="投递失败",
                source="17track", event_key="tracking-old-waybill", tracking_status="DeliveryFailure",
                expected_waybill_id="OLD-WAYBILL",
            )
        session.rollback()
    assert _counts(database) == (0, 0, 0)
    with database.begin() as session:
        session.get(CargoTable, "cargo-a").waybill_id = " WAYBILL-A "
    with database() as session:
        service.register_exception(
            session, order_uid="order-a", cargo_uid="cargo-a", reason="投递失败",
            source="17track", event_key="tracking-current-waybill", tracking_status="DeliveryFailure",
            expected_waybill_id="WAYBILL-A",
        )
        session.commit()
    assert _counts(database) == (1, 1, 1)


def test_distinct_registration_events_share_open_scope_and_retain_each_fact(database):
    first = _create(database)
    second = _create(database, event_key="registration-2", reason="需要确认收件地址")
    parcel = _create(database, event_key="parcel-1", cargo_uid="cargo-a")
    assert first["uid"] == second["uid"]
    assert parcel["uid"] != first["uid"]
    detail = service.get_exception(first["uid"], _actor())
    assert [row["note"] for row in detail["history"]] == ["收件人联系不上", "需要确认收件地址"]
    assert _counts(database) == (2, 3, 3)


def test_duplicate_registration_does_not_reopen_resolved_case_but_new_event_does(database):
    first = _create(database)
    resolved = service.resolve_exception(first["uid"], {"event_key": "resolved-1"}, _actor())
    assert resolved["status"] == "resolved"
    retry = _create(database)
    assert retry["uid"] == first["uid"] and retry["status"] == "resolved"
    new = _create(database, event_key="registration-2")
    assert new["uid"] != first["uid"] and new["status"] == "open"
    assert _counts(database) == (2, 3, 2)


def test_same_registration_event_with_changed_content_conflicts(client, database):
    first = client.post("/api/order-exceptions", headers=_headers(), json=_body())
    assert first.status_code == 200
    changed = client.post("/api/order-exceptions", headers=_headers(), json=_body(reason="不同理由"))
    assert changed.status_code == 409
    assert _counts(database) == (1, 1, 1)


def test_followup_and_manual_resolve_are_ordered_idempotent_history(client, database):
    uid = _create(database)["uid"]
    path = f"/api/order-exceptions/{uid}"
    note = {"note": "已联系客户，等待新地址", "event_key": "followup-1"}
    for _ in range(2):
        assert client.post(f"{path}/followups", headers=_headers(), json=note).status_code == 200
    assert client.post(f"{path}/followups", headers=_headers(), json={**note, "note": "变更内容"}).status_code == 409
    resolved = {"note": "客户已收到包裹", "event_key": "resolve-1"}
    first = client.post(f"{path}/resolve", headers=_headers(), json=resolved)
    retry = client.post(f"{path}/resolve", headers=_headers(), json=resolved)
    assert first.status_code == retry.status_code == 200
    detail = client.get(path, headers=_headers()).get_json()["data"]
    assert detail["status"] == "resolved" and detail["resolved_at"]
    assert [row["action"] for row in detail["history"]] == ["registered", "followup", "resolved"]
    assert [row["note"] for row in detail["history"]] == ["收件人联系不上", note["note"], resolved["note"]]
    assert _counts(database) == (1, 3, 1)


def test_followup_and_resolve_reject_reused_event_content_or_scope(database):
    first = _create(database)
    other = _create(database, event_key="parcel-1", cargo_uid="cargo-a")
    service.add_followup(first["uid"], {"note": "确认地址", "event_key": "followup-1"}, _actor())
    with pytest.raises(service.ExceptionConflictError):
        service.add_followup(other["uid"], {"note": "确认地址", "event_key": "followup-1"}, _actor())
    service.resolve_exception(first["uid"], {"note": "完成", "event_key": "resolve-1"}, _actor())
    with pytest.raises(service.ExceptionConflictError):
        service.resolve_exception(first["uid"], {"note": "修改完成说明", "event_key": "resolve-1"}, _actor())
    assert _counts(database) == (2, 4, 2)


def test_cross_salesperson_case_read_does_not_reveal_foreign_identity(client, database):
    uid = _create(database, actor=_actor(2), order_uid="order-b")["uid"]
    foreign = client.get(f"/api/order-exceptions/{uid}", headers=_headers())
    missing = client.get("/api/order-exceptions/missing", headers=_headers())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.get_json() == missing.get_json()
    assert service.list_exceptions(_actor())["items"] == []
    for action in ("followups", "resolve"):
        response = client.post(f"/api/order-exceptions/{uid}/{action}", headers=_headers(),
                               json={"note": "不能跨员工写入", "event_key": f"foreign-{action}"})
        assert response.status_code in {403, 404}
    assert _counts(database) == (1, 1, 1)


def test_salesperson_cannot_register_or_filter_another_owner(client, database):
    assert client.post("/api/order-exceptions", headers=_headers(), json=_body(order_uid="order-b")).status_code == 403
    response = client.get("/api/order-exceptions?salesman_id=2", headers=_headers())
    assert response.status_code == 403
    assert _counts(database) == (0, 0, 0)


def test_admin_defaults_to_self_can_filter_and_read_others_but_cannot_follow_for_them(client, database):
    own = _create(database, actor=_actor(3), order_uid="order-admin", event_key="admin-case")
    foreign = _create(database, actor=_actor(2), order_uid="order-b", event_key="other-case")
    default = client.get("/api/order-exceptions", headers=_headers(3)).get_json()["data"]
    assert [row["uid"] for row in default["items"]] == [own["uid"]]
    filtered = client.get("/api/order-exceptions?salesman_id=2", headers=_headers(3)).get_json()["data"]
    assert [row["uid"] for row in filtered["items"]] == [foreign["uid"]]
    assert client.get(f"/api/order-exceptions/{foreign['uid']}", headers=_headers(3)).status_code == 200
    for action in ("followups", "resolve"):
        response = client.post(f"/api/order-exceptions/{foreign['uid']}/{action}", headers=_headers(3),
                               json={"note": "代写", "event_key": f"admin-{action}"})
        assert response.status_code == 403
    assert client.post(f"/api/order-exceptions/{own['uid']}/resolve", headers=_headers(3),
                       json={"event_key": "admin-self-resolve"}).status_code == 200


def test_admin_business_identity_choices_come_from_approved_live_roles(database):
    assert {row["id"] for row in service.salespeople(_actor(3))} == {1, 2, 3}
    with pytest.raises(PermissionError):
        service.salespeople(_actor(role="admin", roles=["admin"]))


@pytest.mark.parametrize("user_id", [5, 6, 7, 999, True])
def test_invalid_or_unapproved_live_actor_cannot_forge_admin_authority(client, database, user_id):
    headers = _headers(user_id, role="admin", roles=["admin", "salesperson", "clerk"])
    assert client.get("/api/order-exceptions?salesman_id=2", headers=headers).status_code == 403
    assert client.post("/api/order-exceptions", headers=headers, json=_body()).status_code == 403
    assert _counts(database) == (0, 0, 0)


def test_approved_salesperson_forged_admin_claim_does_not_expand_access(client, database):
    headers = _headers(role="admin", roles=["admin"])
    assert client.get("/api/order-exceptions?salesman_id=2", headers=headers).status_code == 403
    assert client.post("/api/order-exceptions", headers=headers, json=_body(order_uid="order-b")).status_code == 403


def test_live_role_and_approval_changes_apply_despite_old_jwt(client, database):
    uid = _create(database)["uid"]
    headers = _headers()
    with database.begin() as session:
        session.get(UserTable, 1).roles = []
    assert client.get(f"/api/order-exceptions/{uid}", headers=headers).status_code == 403
    with database.begin() as session:
        session.get(UserTable, 1).status = "rejected"
    assert client.post(f"/api/order-exceptions/{uid}/resolve", headers=headers,
                       json={"event_key": "revoked"}).status_code == 403


def test_live_order_reassignment_changes_visibility_without_rewriting_snapshot(database):
    uid = _create(database)["uid"]
    with database.begin() as session:
        session.get(OrderTable, "order-a").salesman_id = 2
    with pytest.raises(LookupError):
        service.get_exception(uid, _actor())
    detail = service.get_exception(uid, _actor(2))
    assert detail["salesman_id"] == 2
    with database() as session:
        assert session.get(OrderExceptionTable, uid).salesman_id == 1
        assert session.query(MessageTable).one().recipient_id == 1


def test_deleted_order_preserves_facts_but_live_access_returns_not_found(database):
    uid = _create(database)["uid"]
    with database.begin() as session:
        session.query(CargoTable).filter_by(target_order_uid="order-a").delete(synchronize_session=False)
        session.delete(session.get(OrderTable, "order-a"))
    for actor in (_actor(), _actor(3)):
        with pytest.raises(LookupError):
            service.get_exception(uid, actor)
    assert _counts(database) == (1, 1, 1)
    assert service.list_exceptions(_actor())["items"] == []


@pytest.mark.parametrize("order_uid", ["unassigned", "invalid-owner", "rejected-owner"])
def test_registration_requires_approved_salesperson_or_admin_owner(client, database, order_uid):
    response = client.post("/api/order-exceptions", headers=_headers(4), json=_body(order_uid=order_uid))
    assert response.status_code == 409
    assert _counts(database) == (0, 0, 0)


@pytest.mark.parametrize("cargo_uid", ["cargo-b", "archived-cargo", "missing"])
def test_parcel_must_be_active_and_belong_to_order(client, database, cargo_uid):
    response = client.post("/api/order-exceptions", headers=_headers(), json=_body(cargo_uid=cargo_uid))
    assert response.status_code in {400, 404, 409}
    assert _counts(database) == (0, 0, 0)


@pytest.mark.parametrize("changed", [
    {"reason": " "}, {"reason": "字" * 2001}, {"reason": True}, {"event_key": " "},
    {"order_uid": None}, {"actor_id": 2}, {"salesman_id": 2}, {"source": "17track"},
])
def test_manual_body_rejects_invalid_content_and_client_authority_fields(client, database, changed):
    response = client.post("/api/order-exceptions", headers=_headers(), json=_body(**changed))
    assert response.status_code == 400
    assert _counts(database) == (0, 0, 0)


@pytest.mark.parametrize("changed", [{"note": " "}, {"note": "字" * 2001}, {"note": []}, {"actor_id": 2}])
def test_followup_rejects_invalid_note_or_actor_override(client, database, changed):
    uid = _create(database)["uid"]
    response = client.post(f"/api/order-exceptions/{uid}/followups", headers=_headers(),
                           json={"note": "正常跟进", "event_key": "followup-invalid", **changed})
    assert response.status_code == 400
    assert _counts(database) == (1, 1, 1)


@pytest.mark.parametrize("query", ["page=0", "page=oops", "page_size=-1", "status=unknown", "salesman_id=oops"])
def test_invalid_list_filters_fail_explicitly(client, database, query):
    assert client.get(f"/api/order-exceptions?{query}", headers=_headers(3)).status_code == 400


def test_status_filters_and_pagination_expose_only_current_salesperson(database):
    order_case = _create(database)
    parcel_case = _create(database, cargo_uid="cargo-a", event_key="parcel-case")
    _create(database, actor=_actor(2), order_uid="order-b", event_key="foreign-case")
    service.resolve_exception(order_case["uid"], {"event_key": "resolve-order"}, _actor())
    assert [row["uid"] for row in service.list_exceptions(_actor(), status="open")["items"]] == [parcel_case["uid"]]
    assert [row["uid"] for row in service.list_exceptions(_actor(), status="resolved")["items"]] == [order_case["uid"]]
    page = service.list_exceptions(_actor(), page=1, page_size=1)
    assert page["total"] == 2 and page["page_size"] == 1 and len(page["items"]) == 1
    assert service.list_exceptions(_actor(), page=99)["items"] == []


def test_resolved_case_rejects_new_followup_or_second_resolution_event(database):
    uid = _create(database)["uid"]
    service.resolve_exception(uid, {"event_key": "resolve-1"}, _actor())
    with pytest.raises(service.ExceptionConflictError):
        service.add_followup(uid, {"note": "新跟进", "event_key": "late-followup"}, _actor())
    with pytest.raises(service.ExceptionConflictError):
        service.resolve_exception(uid, {"event_key": "resolve-2"}, _actor())
    assert _counts(database) == (1, 2, 1)


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/order-exceptions", None),
    ("get", "/api/order-exceptions/missing", None),
    ("post", "/api/order-exceptions", _body()),
    ("post", "/api/order-exceptions/missing/followups", {"note": "跟进", "event_key": "1"}),
    ("post", "/api/order-exceptions/missing/resolve", {"event_key": "1"}),
])
def test_api_requires_valid_authentication(client, database, method, path, body):
    for headers in ({}, {"x-token": "invalid"}):
        response = getattr(client, method)(path, headers=headers, json=body)
        assert response.status_code == 401
