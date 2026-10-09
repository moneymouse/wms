"""Public order-package tracking contract, using isolated DB and mocked HTTP."""
import json

import jsonschema
import pytest
import requests
from starlette.testclient import TestClient

from data.DB import AuditLogTable, CargoTable, OrderTable
from data.mcp import McpIdempotencyTable
from tests.mcp.conftest import rpc


@pytest.fixture(autouse=True)
def no_external_tracking(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not call the real tracking service")

    monkeypatch.setattr("utils.l7track.requests.post", blocked)


def seed_order(mcp_db, *, with_packages=True):
    with mcp_db["factory"]() as session:
        session.add(OrderTable(uid="internal-order-uid", order_id="ORDER-001"))
        if with_packages:
            session.add_all([
                CargoTable(uid="package-1", target_order_uid="internal-order-uid", box_number=1,
                           item_name="Clothes", weight=5, transfer_id="ORIGINAL-001", waybill_id="000123", status=0),
                CargoTable(uid="package-2", target_order_uid="internal-order-uid", box_number=2,
                           waybill_id="000123", status=1),
                CargoTable(uid="package-3", target_order_uid="internal-order-uid", box_number=3,
                           waybill_id="", status=0),
            ])
        session.commit()


def tracking_response(status="Delivered", sub_status="Delivered_Other", track_info_is_null=False):
    track_info = None if track_info_is_null else {
        "latest_status": {"status": status, "sub_status": sub_status, "sub_status_descr": "Delivered"},
        "latest_event": {"time_utc": "2026-10-06T02:00:00Z", "description": "Delivered",
                         "location": "Shanghai", "address": {"street": "private-street"}},
        "tracking": {"providers": [{"events": [{"description": "private-long-history"}]}]},
    }
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"code": 0, "data": {
        "accepted": [{"number": "000123", "carrier": 100003, "tag": "unrelated-provider-tag", "track_info": track_info}],
        "rejected": [],
    }}).encode()
    return response


def tracking_schema(client):
    return next(tool["outputSchema"] for tool in rpc(client, "tools/list").json()["result"]["tools"]
                if tool["name"] == "get_tracking")


def call_tracking(client, arguments=None):
    return rpc(client, "tools/call", {"name": "get_tracking", "arguments": arguments or {
        "order_id": "ORDER-001",
    }}).json()["result"]


def test_tracking_discovery_describes_order_number_and_compact_packages(mcp_app):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        tool = next(item for item in rpc(client, "tools/list").json()["result"]["tools"]
                    if item["name"] == "get_tracking")
    assert tool["inputSchema"]["required"] == ["order_id"]
    assert set(tool["inputSchema"]["properties"]) == {"order_id"}
    assert tool["inputSchema"]["properties"]["order_id"]["maxLength"] == 128
    assert tool["_meta"]["required_scope"] == "tracking:read"
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["outputSchema"]["properties"]["data"]["type"] == "array"


def test_live_order_packages_include_waybills_and_do_not_cache_or_change_stock(mcp_app, mcp_db, monkeypatch):
    seed_order(mcp_db)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if len(calls) == 1:
            return tracking_response()
        return tracking_response(status="OutForDelivery", sub_status="OutForDelivery_Other")

    monkeypatch.setattr("utils.l7track.requests.post", post)
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        schema = tracking_schema(client)
        results = [call_tracking(client, {"order_id": " ORDER-001 "}) for _ in range(2)]
    for result in results:
        assert result["isError"] is False
        body = result["structuredContent"]
        jsonschema.validate(body, schema)
        assert body["order_id"] == "ORDER-001"
        assert body["order_uid"] == "internal-order-uid"
        assert body["total"] == 3
        assert body["tracking_complete"] is True
        assert len(body["data"]) == 3
        first, second, third = body["data"]
        assert first["transfer_id"] == "ORIGINAL-001"
        assert first["waybill_id"] == second["waybill_id"] == "000123"
        assert first["tracking"] == second["tracking"]
        assert first["warehouse_status"] == 0
        assert second["warehouse_status"] == 1
        assert third["tracking"] is None
        assert "private-street" not in json.dumps(body)
        assert "private-long-history" not in json.dumps(body)
        assert "unrelated-provider-tag" not in json.dumps(body)
    assert [result["structuredContent"]["data"][0]["tracking"]["status_text"] for result in results] == ["成功签收", "派送途中"]
    assert len(calls) == 2
    assert all(body == [{"number": "000123"}] for _, body in calls)
    with mcp_db["factory"]() as session:
        assert session.get(CargoTable, "package-1").status == 0
        assert session.query(McpIdempotencyTable).count() == 0
        audits = session.query(AuditLogTable).filter_by(action="get_tracking").all()
        assert len(audits) == 2
        assert all(row.target_type == "order" and row.target_id == "internal-order-uid" for row in audits)


def test_tracking_requires_its_scope_before_loading_order_or_querying_provider(mcp_app, mcp_db):
    mcp_db["principal"]["scopes"] = ["mcp", "orders:read"]
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        response = rpc(client, "tools/call", {"name": "get_tracking", "arguments": {"order_id": "ORDER-001"}})
    assert response.status_code == 403
    assert 'scope="mcp tracking:read"' in response.headers["WWW-Authenticate"]


@pytest.mark.parametrize("arguments", [
    {}, {"order_id": ""}, {"order_id": " \t "}, {"order_id": "X" * 129}, {"order_id": 123},
    {"waybill_id": "000123"}, {"order_id": "ORDER-001", "carrier": 100003},
    {"order_id": "ORDER-001", "uid": "internal-order-uid"},
])
def test_invalid_and_old_arguments_are_rejected(mcp_app, arguments):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        result = rpc(client, "tools/call", {"name": "get_tracking", "arguments": arguments}).json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["code"] == 400


def test_tracking_timeout_preserves_packages_with_explicit_errors(mcp_app, mcp_db, monkeypatch):
    seed_order(mcp_db)

    def timeout(*args, **kwargs):
        raise requests.Timeout("private-provider-details")

    monkeypatch.setattr("utils.l7track.requests.post", timeout)
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        schema = tracking_schema(client)
        result = call_tracking(client)
    assert result["isError"] is False
    body = result["structuredContent"]
    jsonschema.validate(body, schema)
    assert body["tracking_complete"] is False
    assert len(body["data"]) == 3
    assert body["data"][0]["tracking"]["error"]["code"] == 504
    assert body["data"][2]["tracking"] is None
    assert "private-provider-details" not in json.dumps(result)


@pytest.mark.parametrize("track_info_is_null", [False, True])
def test_not_found_tracking_is_distinct_from_warehouse_state(mcp_app, mcp_db, monkeypatch, track_info_is_null):
    seed_order(mcp_db)
    monkeypatch.setattr("utils.l7track.requests.post", lambda *args, **kwargs:
                        tracking_response("NotFound", "NotFound_Other", track_info_is_null))
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        schema = tracking_schema(client)
        result = call_tracking(client)
    body = result["structuredContent"]
    jsonschema.validate(body, schema)
    assert body["tracking_complete"] is True
    assert body["data"][0]["tracking"]["status"] == "NotFound"
    assert body["data"][0]["tracking"]["status_text"] == "暂无物流轨迹"
    assert body["data"][0]["warehouse_status"] == 0


@pytest.mark.parametrize("order_id,code", [("DOES-NOT-EXIST", 404), ("internal-order-uid", 404), ("ORDER", 404)])
def test_order_number_lookup_does_not_use_uid_or_fuzzy_search(mcp_app, mcp_db, order_id, code):
    seed_order(mcp_db)
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        result = call_tracking(client, {"order_id": order_id})
    assert result["isError"] is True
    assert result["structuredContent"]["code"] == code


def test_empty_order_returns_empty_package_list_without_tracking_request(mcp_app, mcp_db):
    seed_order(mcp_db, with_packages=False)
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        schema = tracking_schema(client)
        result = call_tracking(client)
    body = result["structuredContent"]
    jsonschema.validate(body, schema)
    assert body["data"] == []
    assert body["total"] == 0
    assert body["tracking_complete"] is True


def test_order_detail_remains_a_local_read(mcp_app, mcp_db):
    seed_order(mcp_db)
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        result = rpc(client, "tools/call", {"name": "get_order", "arguments": {
            "uid": "internal-order-uid",
        }}).json()["result"]
    assert result["isError"] is False
