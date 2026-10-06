import json
from unittest.mock import Mock

import pytest

import data
from Auth import create_jwt
from data.DB import AuditLogTable, CargoTable, OrderQuoteVersionTable, OrderTable
from data.customer.Customer import ReceiverTable
from data.order_version import OrderVersionTable
from data.packing.PackingList import PackingListTable
from services import order_service, packing_list_service, receivable_service


ACTOR = {"user_id": 1, "name": "操作员", "roles": ["clerk"]}


def draft(**changes):
    return {
        "order_id": "ATOMIC-ORDER", "customer_id": 1,
        "customer_name": "不应保存的客户名", "salesman_id": 2,
        "receiver": "测试收件人", "address": "测试地址",
        "transportation": "未维护渠道",
        "quote": {"unit_price": 12.5, "surcharge": 8},
        **changes,
    }


def headers(role="clerk"):
    return {"x-token": create_jwt({**ACTOR, "role": role, "roles": [role]})}


def test_caller_owned_create_preserves_identity_quote_attribution_and_rolls_back(world, monkeypatch):
    factory = world["factory"]
    with factory() as session:
        original_commit = session.commit
        commit = Mock(wraps=original_commit)
        monkeypatch.setattr(session, "commit", commit)
        result = order_service.create_order(draft(), ACTOR, session=session)
        commit.assert_not_called()
        order = session.query(OrderTable).one()
        quote = session.query(OrderQuoteVersionTable).one()
        version = session.query(OrderVersionTable).filter_by(version_no=1).one()
        audit = session.query(AuditLogTable).one()
        assert order.uid == result["uid"]
        assert order.customer_name == "事务测试客户"
        assert [customer.id for customer in order.customers] == [1]
        assert quote.quoter_id == 2
        assert quote.quoter_name == "业务员"
        assert quote.status == "adopted"
        assert version.operator_id == 1
        assert version.operator_name == "操作员"
        assert json.loads(version.operator_roles) == ["clerk"]
        assert audit.operator_id == 1
        assert session.query(ReceiverTable).count() == 1
        session.rollback()
    with factory() as session:
        for model in (OrderTable, ReceiverTable, OrderVersionTable, OrderQuoteVersionTable, AuditLogTable):
            assert session.query(model).count() == 0


def test_business_and_quote_audit_failure_roll_back_all_writes(world, monkeypatch):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(receivable_service, "record_audit", fail_audit)
    factory = world["factory"]
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        with factory.begin() as session:
            order_service.create_order(draft(), ACTOR, session=session)
    with factory() as session:
        for model in (OrderTable, ReceiverTable, OrderVersionTable, OrderQuoteVersionTable, AuditLogTable):
            assert session.query(model).count() == 0


def test_invalid_initial_quote_fails_before_receiver_or_order_write(world):
    with world["factory"]() as session:
        with pytest.raises(order_service.BusinessError) as error:
            order_service.create_order(draft(quote={"surcharge": 8}), ACTOR, session=session)
        assert error.value.code == 400
        assert error.value.uid is None
        assert session.query(OrderTable).count() == 0
        assert session.query(ReceiverTable).count() == 0


def test_standalone_shared_create_records_supplied_actor_without_flask_request(world):
    result = order_service.create_order(draft(quote=None), ACTOR)
    with world["factory"]() as session:
        version = session.query(OrderVersionTable).filter_by(order_uid=result["uid"]).one()
        assert version.operator_id == 1
        assert version.operator_name == "操作员"
        assert json.loads(version.operator_roles) == ["clerk"]


def test_atomic_quote_business_failure_does_not_expose_uncommitted_uid(world, monkeypatch):
    def fail_quote(**kwargs):
        raise LookupError("simulated quote failure")

    monkeypatch.setattr(receivable_service, "create_order_quote", fail_quote)
    with pytest.raises(order_service.BusinessError) as error:
        with world["factory"].begin() as session:
            order_service.create_order(draft(), ACTOR, session=session)
    assert error.value.uid is None
    assert "订单已创建" not in error.value.msg
    with world["factory"]() as session:
        assert session.query(OrderTable).count() == 0
        assert session.query(ReceiverTable).count() == 0


def test_rest_still_reports_committed_order_when_quote_creation_fails(world, monkeypatch):
    def fail_quote(**kwargs):
        raise LookupError("simulated quote failure")

    monkeypatch.setattr(receivable_service, "create_order_quote", fail_quote)
    response = world["client"].post("/api/create", headers=headers(), json=draft())
    assert response.status_code == 500
    result = response.get_json()
    assert result["code"] == 500
    assert "订单已创建" in result["msg"]
    with world["factory"]() as session:
        assert session.query(OrderTable).one().uid == result["uid"]
        assert session.query(ReceiverTable).count() == 1
        assert session.query(OrderVersionTable).one().operator_id == 1
        assert session.query(OrderQuoteVersionTable).count() == 0


def test_rest_facade_mocks_keep_legacy_call_signatures(world, monkeypatch):
    create = Mock(return_value="legacy-mock-uid")
    add_receiver = Mock()
    monkeypatch.setattr(data.order_model, "create", create)
    monkeypatch.setattr(data, "add_customer_record", add_receiver)
    response = world["client"].post(
        "/api/create", headers=headers(), json={"order_id": "MOCK-ORDER"}
    )
    assert response.status_code == 200
    assert response.json == {"code": 200, "msg": "success", "uid": "legacy-mock-uid"}
    assert create.call_count == add_receiver.call_count == 1
    assert create.call_args.kwargs == add_receiver.call_args.kwargs == {}
    assert create.call_args.args[0]["salesman_id"] == 1


def test_shared_list_retains_search_sort_pagination_and_archival(world):
    with world["factory"].begin() as session:
        session.add_all([
            OrderTable(uid="a", order_id="AAA", salesman_id=2, receiver="测试", archive=False),
            OrderTable(uid="b", order_id="BBB", salesman_id=1, receiver="测试", archive=False),
            OrderTable(uid="archived", order_id="CCC", receiver="测试", archive=True),
        ])
        session.add(CargoTable(uid="search-cargo", target_order_uid="b", transfer_id="TRANSFER-123", archive=False))
    result = order_service.list_orders(p=2, s=1, sf="order_id", so=0, q="测试")
    assert result["total"] == 2
    assert [row["uid"] for row in result["data"]] == ["b"]
    assert not set(order_service.ORDER_LIST_EXCLUDED_FIELDS).intersection(result["data"][0])
    assert order_service.list_orders(q="业务员")["data"][0]["uid"] == "a"
    assert order_service.list_orders(q="TRANSFER-123")["data"][0]["uid"] == "b"
    assert len(order_service.list_orders(p=0, s=1000)["data"]) == 2
    client = world["client"]
    assert client.get("/api/orders", headers=headers("employee")).status_code == 403
    assert client.get("/api/orders", headers=headers()).json["total"] == 2


def test_shared_detail_uses_explicit_actor_and_retains_missing_order_contract(world):
    with world["factory"].begin() as session:
        result = order_service.create_order(draft(quote=None), ACTOR, session=session)
    uid = result["uid"]
    detail = order_service.get_order(uid, ACTOR)["data"]
    assert detail["customer_ids"] == [1]
    assert detail["current_version"] == 1
    assert detail["salesman"]["id"] == 2
    assert detail["edit_policy"]["salesman"] is False
    assigned = order_service.get_order(uid, {"user_id": 2, "roles": ["salesperson"]})["data"]
    assert assigned["edit_policy"]["salesman"] is True
    assert order_service.get_order("missing", ACTOR) == {"code": 200, "data": None}
    assert world["client"].get("/api/orders/missing", headers=headers("employee")).json == {"code": 200, "data": None}


def test_packing_list_joins_caller_transaction_and_creates_only_draft_header(world, monkeypatch):
    with world["factory"]() as session:
        commit = Mock(wraps=session.commit)
        monkeypatch.setattr(session, "commit", commit)
        result = packing_list_service.create_packing_list(
            creator_id=1, mark=" mcp-mark ", customer_id=1,
            photos=["/static/uploads/photos/test.jpg"], session=session,
        )
        commit.assert_not_called()
        record = session.query(PackingListTable).one()
        assert result["list_number"] == record.list_number == "MCP-MARK"
        assert record.creator_id == 1
        assert record.status == "draft"
        assert json.loads(record.photos) == ["/static/uploads/photos/test.jpg"]
        assert session.query(CargoTable).count() == 0
        session.rollback()
    with world["factory"]() as session:
        assert session.query(PackingListTable).count() == 0


def test_rest_packing_list_keeps_creator_role_and_mark_contract(world):
    client = world["client"]
    response = client.post(
        "/api/packing-list", headers=headers("employee"),
        json={"mark": "rest-mark", "creator_id": 2},
    )
    assert response.status_code == 200
    with world["factory"]() as session:
        record = session.query(PackingListTable).one()
        assert record.creator_id == 1
        assert record.status == "draft"
        assert record.list_number == "REST-MARK"
    assert client.post("/api/packing-list", headers=headers("finance"), json={"mark": "denied"}).status_code == 403
