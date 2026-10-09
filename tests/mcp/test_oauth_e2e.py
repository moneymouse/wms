"""Real Flask OAuth authorization followed by authenticated MCP HTTP calls."""
import base64
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import Flask
from starlette.testclient import TestClient

from controllers import oauth_controller
from data.DB import OrderTable
from data.packing.PackingList import PackingListTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from mcp_server import create_mcp_app
from tests.mcp.conftest import ALL_SCOPES, rpc


ORIGIN = "https://wms.example"
RESOURCE = ORIGIN + "/mcp"


def _csrf(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)
    return match.group(1)


def _authorize(mcp_db, monkeypatch, selected_scopes):
    monkeypatch.setenv("OAUTH_ISSUER_URL", ORIGIN)
    monkeypatch.setenv("MCP_PUBLIC_URL", RESOURCE)
    monkeypatch.setattr(oauth_controller, "SessionFactory", mcp_db["factory"])
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    app.config.update(TESTING=True, OAUTH_ISSUER_URL=ORIGIN, MCP_PUBLIC_URL=RESOURCE,
                      OAUTH_SESSION_SECRET="oauth-e2e-session-secret-at-least-32-characters")
    oauth_controller.init_oauth(app)
    browser = app.test_client()
    discovery = browser.get("/.well-known/oauth-authorization-server", base_url=ORIGIN)
    assert discovery.status_code == 200
    assert discovery.json["issuer"] == ORIGIN
    registered = browser.post("/oauth/register", base_url=ORIGIN, json={
        "client_name": "OAuth MCP 闭环测试", "redirect_uris": ["https://client.example/callback"],
        "token_endpoint_auth_method": "none",
    })
    assert registered.status_code == 201, registered.get_data(as_text=True)
    client_id = registered.json["client_id"]
    verifier = "oauth-e2e-verifier-with-at-least-43-characters-1234567890"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    authorize_url = "/oauth/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code",
        "redirect_uri": "https://client.example/callback", "resource": RESOURCE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "e2e-state",
        "scope": " ".join(ALL_SCOPES),
    })
    response = browser.get(authorize_url, base_url=ORIGIN)
    assert response.status_code == 302
    login_url = response.headers["Location"]
    login_page = browser.get(login_url, base_url=ORIGIN)
    assert login_page.status_code == 200
    logged_in = browser.post(login_url, base_url=ORIGIN, data={
        "csrf_token": _csrf(login_page), "phone": "13800138000", "password": "Mcp-test-password",
    })
    assert logged_in.status_code == 302
    consent_page = browser.get(logged_in.headers["Location"], base_url=ORIGIN)
    assert consent_page.status_code == 200
    assert "client.example" in consent_page.get_data(as_text=True)
    consent = browser.post(authorize_url, base_url=ORIGIN, data={
        "csrf_token": _csrf(consent_page), "decision": "approve", "approved_scope": selected_scopes,
    })
    assert consent.status_code == 302
    callback = parse_qs(urlsplit(consent.headers["Location"]).query)
    assert callback["state"] == ["e2e-state"]
    assert callback["iss"] == [ORIGIN]
    token_response = browser.post("/oauth/token", base_url=ORIGIN, data={
        "grant_type": "authorization_code", "code": callback["code"][0], "client_id": client_id,
        "code_verifier": verifier, "redirect_uri": "https://client.example/callback", "resource": RESOURCE,
    })
    assert token_response.status_code == 200, token_response.get_data(as_text=True)
    assert set(token_response.json["scope"].split()) == set(selected_scopes)
    return browser, client_id, token_response.json


def test_real_oauth_to_order_and_packing_tools_and_live_permissions(mcp_db, monkeypatch):
    browser, client_id, credentials = _authorize(mcp_db, monkeypatch, ALL_SCOPES)
    token = credentials["access_token"]
    with TestClient(create_mcp_app(), base_url=ORIGIN) as client:
        assert len(rpc(client, "tools/list", token=token).json()["result"]["tools"]) == 5
        args = {"order": {"customer_id": mcp_db["customer_id"], "order_id": "OAUTH-E2E"},
                "idempotency_key": "oauth-e2e-order"}
        created = rpc(client, "tools/call", {"name": "create_order", "arguments": args}, token=token).json()["result"]
        assert created["isError"] is False
        uid = created["structuredContent"]["uid"]
        replay = rpc(client, "tools/call", {"name": "create_order", "arguments": args}, token=token).json()["result"]
        assert replay["structuredContent"] == created["structuredContent"]
        for name, arguments in [("get_order", {"uid": uid}), ("list_orders", {"q": "OAUTH-E2E"}),
                                ("create_packing_list", {"mark": "oauth-e2e", "idempotency_key": "oauth-e2e-list"})]:
            result = rpc(client, "tools/call", {"name": name, "arguments": arguments}, token=token).json()["result"]
            assert result["isError"] is False
        with mcp_db["factory"]() as db:
            assert db.query(OrderTable).count() == 1
            assert db.query(PackingListTable).one().creator_id == mcp_db["user_id"]
            finance = RoleTable(name="finance", label="财务")
            db.add(finance)
            db.get(UserTable, mcp_db["user_id"]).roles = [finance]
            db.commit()
        denied = rpc(client, "tools/call", {"name": "list_orders", "arguments": {}}, token=token).json()["result"]
        assert denied["isError"] is True
        assert denied["structuredContent"]["code"] == 403
        revoked = browser.post("/oauth/revoke", base_url=ORIGIN, data={"client_id": client_id, "token": token})
        assert revoked.status_code == 200
        assert rpc(client, "tools/list", token=token).status_code == 401


def test_real_consent_narrowing_produces_http_scope_challenge(mcp_db, monkeypatch):
    _, _, credentials = _authorize(mcp_db, monkeypatch, ["mcp"])
    with TestClient(create_mcp_app(), base_url=ORIGIN) as client:
        assert rpc(client, "tools/list", token=credentials["access_token"]).status_code == 200
        response = rpc(client, "tools/call", {"name": "create_order", "arguments": {
            "order": {}, "idempotency_key": "narrowed-permissions"}}, token=credentials["access_token"])
        assert response.status_code == 403
        assert 'scope="mcp orders:create"' in response.headers["WWW-Authenticate"]
    with mcp_db["factory"]() as db:
        assert db.query(OrderTable).count() == 0


def test_tracking_only_consent_can_query_tracking_but_not_order_details(mcp_db, monkeypatch):
    _, _, credentials = _authorize(mcp_db, monkeypatch, ["mcp", "tracking:read"])
    calls = []

    def get_tracking(order_id):
        calls.append(order_id)
        return {"code": 200, "order_id": order_id, "order_uid": "order-uid",
                "data": [], "total": 0, "tracking_complete": True,
                "queried_at": "2026-10-07T00:00:00Z"}

    monkeypatch.setattr("services.tracking_service.get_tracking", get_tracking)
    with TestClient(create_mcp_app(), base_url=ORIGIN) as client:
        result = rpc(client, "tools/call", {"name": "get_tracking", "arguments": {
            "order_id": "ORDER-001",
        }}, token=credentials["access_token"]).json()["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["order_id"] == "ORDER-001"
        denied = rpc(client, "tools/call", {"name": "get_order", "arguments": {
            "uid": "unavailable-order",
        }}, token=credentials["access_token"])
    assert calls == ["ORDER-001"]
    assert denied.status_code == 403
    assert 'scope="mcp orders:read"' in denied.headers["WWW-Authenticate"]
