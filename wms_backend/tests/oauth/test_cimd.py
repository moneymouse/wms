import json
from urllib.parse import urlencode

from authlib.oauth2.rfc6749 import InvalidClientError
import pytest
from sqlalchemy import select

from data.oauth import OAuthClientTable
from services.oauth_service import CLIENT_METADATA_MAX_BYTES, fetch_client_metadata
from test_oauth import (
    _browser_login, _callback_code, _form_action, authorization_url, csrf,
    exchange, get, post,
)


CLIENT_ID = "https://client.example.test/oauth/metadata.json"
DOCUMENT = {"client_id": CLIENT_ID, "client_name": "CIMD test client",
            "redirect_uris": ["https://client.example.test/callback"],
            "token_endpoint_auth_method": "none"}
CODEX_CLIENT_ID = "https://chatgpt.com/oauth/codex/client.json"
CODEX_DOCUMENT = {
    "client_id": CODEX_CLIENT_ID,
    "client_uri": "https://chatgpt.com/codex",
    "application_type": "native",
    "redirect_uris": ["http://127.0.0.1/callback", "http://localhost/callback"],
    "token_endpoint_auth_method": "none",
    "token_endpoint_auth_methods_supported": ["none"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "client_name": "Codex",
    "logo_uri": "https://persistent.oaistatic.com/sonic/misc/openai-logo.png",
}


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.body = body
        self.closed = False

    def read(self, amount, decode_content):
        assert decode_content is False
        return self.body[:amount]

    def close(self):
        self.closed = True


def mock_fetch(monkeypatch, *, document=None, status=200, headers=None, body=None, addresses=("93.184.216.34",)):
    records = []
    response = FakeResponse(body if body is not None else json.dumps(document or DOCUMENT).encode(), status=status, headers=headers)
    monkeypatch.setattr("services.oauth_service.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443)) for ip in addresses])

    class FakePool:
        def __init__(self, host, **kwargs):
            records.append((host, kwargs))

        def request(self, method, target, **kwargs):
            records.append((method, target, kwargs))
            return response

        def close(self):
            pass

    monkeypatch.setattr("services.oauth_service.urllib3.HTTPSConnectionPool", FakePool)
    return response, records


def test_cimd_fetch_pins_dns_and_preserves_tls_hostname(monkeypatch):
    response, records = mock_fetch(monkeypatch)
    metadata = fetch_client_metadata(CLIENT_ID)
    assert metadata["client_name"] == DOCUMENT["client_name"]
    host, kwargs = records[0]
    assert host == "93.184.216.34"
    assert kwargs["server_hostname"] == "client.example.test"
    assert kwargs["assert_hostname"] == "client.example.test"
    assert records[1][2]["headers"]["Host"] == "client.example.test"
    assert records[1][2]["redirect"] is False
    assert records[1][2]["retries"] is False
    assert response.closed is True


@pytest.mark.parametrize("addresses", [
    ("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",), ("::1",),
    ("93.184.216.34", "192.168.0.1"), ("224.0.0.1",), ("100.64.0.1",),
])
def test_private_link_local_mixed_and_multicast_dns_are_blocked(monkeypatch, addresses):
    _, records = mock_fetch(monkeypatch, addresses=addresses)
    with pytest.raises(InvalidClientError):
        fetch_client_metadata(CLIENT_ID)
    assert records == []


@pytest.mark.parametrize("client_id", [
    "http://client.example.test/client.json", "https://client.example.test/",
    "https://user:password@client.example.test/client.json", "https://client.example.test:8443/client.json",
    "https://client.example.test/client.json#fragment",
])
def test_cimd_url_shape_is_restricted(monkeypatch, client_id):
    _, records = mock_fetch(monkeypatch)
    with pytest.raises(InvalidClientError):
        fetch_client_metadata(client_id)
    assert records == []


@pytest.mark.parametrize("changes", [
    {"status": 302}, {"headers": {"Content-Type": "text/html"}},
    {"headers": {"Content-Type": "application/json", "Content-Length": str(CLIENT_METADATA_MAX_BYTES + 1)}},
    {"body": b"x" * (CLIENT_METADATA_MAX_BYTES + 1)}, {"body": b"[]"},
    {"document": {**DOCUMENT, "client_id": "https://different.example/client.json"}},
    {"document": {"client_id": CLIENT_ID, "redirect_uris": DOCUMENT["redirect_uris"]}},
    {"document": {**DOCUMENT, "token_endpoint_auth_method": "client_secret_basic"}},
])
def test_cimd_redirect_content_size_identity_and_required_fields(monkeypatch, changes):
    mock_fetch(monkeypatch, **changes)
    with pytest.raises(InvalidClientError):
        fetch_client_metadata(CLIENT_ID)


def test_cimd_authorization_auto_registers_and_caches(world, monkeypatch):
    _, records = mock_fetch(monkeypatch)
    path = "/oauth/authorize?" + urlencode({"client_id": CLIENT_ID, "response_type": "code",
        "redirect_uri": DOCUMENT["redirect_uris"][0], "resource": world["resource"],
        "code_challenge": "a" * 43, "code_challenge_method": "S256"})
    for _ in range(2):
        response = world["client"].get(path, base_url=world["base"])
        assert response.status_code == 302
        assert response.location.startswith("/oauth/login?")
    assert len(records) == 2
    with world["factory"]() as session:
        row = session.execute(select(OAuthClientTable)).scalar_one()
        assert row.source == "cimd"
        assert row.client_id == CLIENT_ID
        assert row.secret_hash is None


def test_codex_cimd_fetch_preserves_native_client_type(monkeypatch):
    mock_fetch(monkeypatch, document=CODEX_DOCUMENT)
    metadata = fetch_client_metadata(CODEX_CLIENT_ID)
    assert metadata["application_type"] == "native"
    assert metadata["redirect_uris"] == CODEX_DOCUMENT["redirect_uris"]
    assert metadata["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize("callback", [
    "http://127.0.0.1:49183/callback", "http://localhost:49184/callback",
    "http://[::1]:49185/callback",
])
def test_codex_native_loopback_authorization_binds_token_to_actual_callback(world, monkeypatch, callback):
    document = {**CODEX_DOCUMENT, "redirect_uris": [*CODEX_DOCUMENT["redirect_uris"], "http://[::1]/callback"]}
    mock_fetch(monkeypatch, document=document)
    client = {"client_id": CODEX_CLIENT_ID}
    _, _, path = _browser_login(world, client, redirect_uri=callback)
    consent = get(world, path)
    assert consent.status_code == 200, consent.text
    assert _form_action(consent) == ["'self'", callback.rsplit("/", 1)[0]]
    response = post(world, path, data={"csrf_token": csrf(consent),
        "decision": "approve", "approved_scope": ["mcp"]})
    code = _callback_code(response)
    # The port exception applies during registration matching only. Token
    # exchange must retain the complete callback used to issue this code.
    assert exchange(world, client, code, redirect_uri=callback.replace(":4918", ":4928")).status_code == 400
    token = exchange(world, client, code, redirect_uri=callback)
    assert token.status_code == 200, token.text


@pytest.mark.parametrize("callback", [
    "http://127.0.0.1:49183/other", "http://127.0.0.1:49183/callback/",
    "http://127.0.0.1:49183/callback?other=1", "http://127.0.0.1:49183/callback?",
    "http://127.0.0.2:49183/callback", "http://[::1]:49183/callback",
    "https://127.0.0.1:49183/callback", "http://user@127.0.0.1:49183/callback",
    "http://127.0.0.1:99999/callback", "http://127.0.0.1:/callback",
    "http://127.0.0.1\t:49183/callback",
    "https://client.example.test:9443/callback",
])
def test_native_loopback_exception_keeps_other_redirect_components_exact(world, monkeypatch, callback):
    document = {**CODEX_DOCUMENT,
        "redirect_uris": [*CODEX_DOCUMENT["redirect_uris"], "http://127.0.0.13/callback",
                          "https://client.example.test/callback"]}
    mock_fetch(monkeypatch, document=document)
    response = get(world, authorization_url(world, {"client_id": CODEX_CLIENT_ID}, redirect_uri=callback))
    assert response.status_code == 400
    assert response.json["error"] == "invalid_request"
    assert _form_action(response) == ["'self'"]


@pytest.mark.parametrize("application_type", [None, "web"])
def test_loopback_port_exception_requires_native_client_type(world, monkeypatch, application_type):
    document = {key: value for key, value in CODEX_DOCUMENT.items() if key != "application_type"}
    if application_type is not None:
        document["application_type"] = application_type
    mock_fetch(monkeypatch, document=document)
    response = get(world, authorization_url(world, {"client_id": CODEX_CLIENT_ID},
        redirect_uri="http://127.0.0.1:49183/callback"))
    assert response.status_code == 400
    assert response.json["error"] == "invalid_request"


@pytest.mark.parametrize("application_type", [None, "", "unknown", 1, {}])
def test_cimd_rejects_invalid_application_type(monkeypatch, application_type):
    mock_fetch(monkeypatch, document={**CODEX_DOCUMENT, "application_type": application_type})
    with pytest.raises(InvalidClientError):
        fetch_client_metadata(CODEX_CLIENT_ID)
