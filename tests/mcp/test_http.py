import jsonschema
import pytest
from starlette.testclient import TestClient

from data.DB import AuditLogTable, OrderTable
from data.mcp import McpIdempotencyTable
from data.packing.PackingList import PackingListTable
from tests.mcp.conftest import rpc


def test_auth_discovery_and_fixed_catalog(mcp_app):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        response = rpc(client, "tools/list", token=None)
        assert response.status_code == 401
        assert "resource_metadata=" in response.headers["WWW-Authenticate"]
        assert rpc(client, "tools/list", token="invalid").status_code == 401
        metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert metadata["resource"] == "https://wms.example/mcp"
        assert metadata["authorization_servers"] == ["https://wms.example"]
        assert set(metadata["scopes_supported"]) == {"mcp", "orders:create", "orders:list", "orders:read", "tracking:read", "packing_lists:create"}
        response = rpc(client, "tools/list")
        assert response.status_code == 200
        tools = response.json()["result"]["tools"]
        assert {tool["name"] for tool in tools} == {"create_order", "list_orders", "get_order", "get_tracking", "create_packing_list"}
        for tool in tools:
            assert tool["inputSchema"]["additionalProperties"] is False
            assert tool["outputSchema"]["required"] == ["code"]


def test_new_and_legacy_protocols(mcp_app):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        discover = rpc(client, "server/discover")
        assert discover.status_code == 200
        assert "error" not in discover.json()
        assert "mcp-session-id" not in discover.headers
        legacy = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                              "clientInfo": {"name": "legacy", "version": "1"}}, version="2025-11-25")
        assert legacy.status_code == 200
        assert legacy.json()["result"]["protocolVersion"] == "2025-11-25"
        assert rpc(client, "tools/list", version="2025-11-25").status_code == 200


def test_step_up_prevents_mutation_and_keeps_catalog(mcp_app, mcp_db):
    mcp_db["principal"]["scopes"] = ["mcp"]
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        assert len(rpc(client, "tools/list").json()["result"]["tools"]) == 5
        response = rpc(client, "tools/call", {"name": "create_order", "arguments": {
            "order": {"customer_id": mcp_db["customer_id"]}, "idempotency_key": "scope-test"}})
        assert response.status_code == 403
        assert 'error="insufficient_scope"' in response.headers["WWW-Authenticate"]
        assert 'scope="mcp orders:create"' in response.headers["WWW-Authenticate"]
    with mcp_db["factory"]() as session:
        assert session.query(OrderTable).count() == 0
        assert session.query(McpIdempotencyTable).count() == 0


def test_order_and_packing_tools_and_structured_envelope(mcp_app, mcp_db):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        schemas = {tool["name"]: tool["outputSchema"] for tool in rpc(client, "tools/list").json()["result"]["tools"]}
        created = rpc(client, "tools/call", {"name": "create_order", "arguments": {
            "order": {"customer_id": mcp_db["customer_id"], "order_id": "MCP-ORDER", "receiver": "收件人"},
            "idempotency_key": "order-key"}}).json()["result"]
        assert created["isError"] is False
        body = created["structuredContent"]
        assert body["code"] == 200
        uid = body["uid"]
        jsonschema.validate(body, schemas["create_order"])
        for name, arguments in [("list_orders", {"q": "MCP-ORDER"}), ("get_order", {"uid": uid}),
                                ("create_packing_list", {"mark": "lower", "list_number": "  preferred  ",
                                 "customer_id": mcp_db["customer_id"], "idempotency_key": "packing-key"})]:
            result = rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
            assert result["isError"] is False
            jsonschema.validate(result["structuredContent"], schemas[name])
            if name == "get_order":
                assert result["structuredContent"]["data"]["uid"] == uid
            if name == "list_orders":
                assert result["structuredContent"]["total"] == 1
            if name == "create_packing_list":
                assert result["structuredContent"]["data"]["list_number"] == "PREFERRED"
    with mcp_db["factory"]() as session:
        assert session.query(OrderTable).one().salesman_id == mcp_db["user_id"]
        assert session.query(PackingListTable).one().creator_id == mcp_db["user_id"]
        audit = session.query(AuditLogTable).filter_by(event_type="order_created").one()
        assert audit.operator_id == mcp_db["user_id"]
        assert '"client_id"' in audit.after_data and '"tool_name"' in audit.after_data


def test_role_and_forbidden_identity_inputs(mcp_app, mcp_db):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        response = rpc(client, "tools/call", {"name": "create_order", "arguments": {
            "order": {"customer_id": mcp_db["customer_id"], "archive": True, "user_id": 999},
            "idempotency_key": "forbidden"}}).json()["result"]
        assert response["isError"] is True
        assert response["structuredContent"]["code"] == 400
        response = rpc(client, "tools/call", {"name": "create_packing_list", "arguments": {
            "mark": "FAKE", "creator_id": 999, "idempotency_key": "fake"}}).json()["result"]
        assert response["structuredContent"]["code"] == 400
        mcp_db["principal"]["operator_payload"].update(role="finance", roles=["finance"])
        result = rpc(client, "tools/call", {"name": "list_orders", "arguments": {}}).json()["result"]
        assert result["isError"] is True
        assert result["structuredContent"]["code"] == 403
    with mcp_db["factory"]() as session:
        assert session.query(McpIdempotencyTable).count() == 0


def test_http_rejects_expired_or_wrong_resource_tokens(mcp_app, mcp_db):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        mcp_db["principal"]["expires_at"] = 1
        assert rpc(client, "tools/list").status_code == 401
        mcp_db["principal"]["expires_at"] = 9999999999
        mcp_db["principal"]["resource"] = "https://other.example/mcp"
        assert rpc(client, "tools/list").status_code == 401


def test_routing_header_tampering_never_runs_tool(mcp_app, mcp_db):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        params = {"name": "create_order", "arguments": {"order": {}, "idempotency_key": "tampered"},
                  "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientCapabilities": {}}}
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
                               headers={"Authorization": "Bearer test-token", "Accept": "application/json, text/event-stream",
                                        "Mcp-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "get_order"})
        assert response.status_code == 400
    with mcp_db["factory"]() as session:
        assert session.query(OrderTable).count() == 0
        assert session.query(McpIdempotencyTable).count() == 0


@pytest.mark.parametrize("name", [["create_order"], {"tool": "create_order"}])
def test_malformed_tool_name_uses_sdk_error(mcp_app, mcp_db, name):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        response = rpc(client, "tools/call", {"name": name, "arguments": {}},
                       extra_headers={"Mcp-Name": "create_order"})
        assert response.status_code == 400
    with mcp_db["factory"]() as session:
        assert session.query(OrderTable).count() == 0


@pytest.mark.parametrize("headers,status", [({"Origin": "https://evil.example"}, 403),
                                             ({"Host": "evil.example"}, 421),
                                             ({"Mcp-Method": "tools/list"}, 400)])
def test_sdk_transport_checks_reject_before_mutation(mcp_app, mcp_db, headers, status):
    with TestClient(mcp_app, base_url="https://wms.example") as client:
        response = rpc(client, "tools/call", {"name": "create_order", "arguments": {
            "order": {}, "idempotency_key": "transport-guard"}}, extra_headers=headers)
        assert response.status_code == status
    with mcp_db["factory"]() as session:
        assert session.query(OrderTable).count() == 0
        assert session.query(McpIdempotencyTable).count() == 0
