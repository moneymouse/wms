import base64
import hashlib
import re
import time
from types import SimpleNamespace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import Flask, g
from authlib.oauth2.rfc6749 import InvalidGrantError
import pytest
from sqlalchemy import select

from controllers.oauth_controller import init_oauth
from data.oauth import OAuthAuthorizationCodeTable, OAuthClientTable, OAuthTokenFamilyTable, OAuthTokenTable, credential_hash
from data.user.User import UserTable
from services.oauth_service import OAuthConfigurationError, SCOPES, load_oauth_settings, save_token, validate_access_token, validate_oauth_public_urls


VERIFIER = "a" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
CALLBACK = "https://client.example.test/callback"


def get(world, path):
    return world["client"].get(path, base_url=world["base"])


def post(world, path, **kwargs):
    return world["client"].post(path, base_url=world["base"], **kwargs)


def csrf(response):
    return re.search(r'name="csrf_token" value="([^\"]+)"', response.text).group(1)


def client_registration(world, method="none", **metadata):
    payload = {"client_name": "OAuth test", "redirect_uris": [CALLBACK],
               "token_endpoint_auth_method": method,
               "grant_types": ["authorization_code", "refresh_token"], **metadata}
    response = post(world, "/oauth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json


def authorization_url(world, client, **extra):
    params = {"client_id": client["client_id"], "response_type": "code", "redirect_uri": CALLBACK,
              "resource": world["resource"], "code_challenge": CHALLENGE,
              "code_challenge_method": "S256", "state": "client-csrf", **extra}
    return "/oauth/authorize?" + urlencode(params)


def authorize_code(world, client, scopes=None, **extra):
    path = authorization_url(world, client, **extra)
    response = get(world, path)
    if response.status_code == 302:
        login_url = response.location
        login_page = get(world, login_url)
        response = post(world, login_url, data={"csrf_token": csrf(login_page), "phone": world.get("phone", "13800138000"), "password": "Mcp-test-password"})
        assert response.status_code == 302
        response = get(world, path)
    assert response.status_code == 200, response.text
    response = post(world, path, data={"csrf_token": csrf(response), "decision": "approve", "approved_scope": scopes or list(SCOPES)})
    assert response.status_code == 302, response.text
    values = parse_qs(urlsplit(response.location).query)
    assert values["iss"] == [world["base"]]
    assert values["state"] == ["client-csrf"]
    return values["code"][0]


def exchange(world, client, code, **extra):
    payload = {"grant_type": "authorization_code", "client_id": client["client_id"], "code": code,
               "redirect_uri": CALLBACK, "code_verifier": VERIFIER, "resource": world["resource"], **extra}
    return post(world, "/oauth/token", data=payload)


def issue(world):
    client = client_registration(world)
    code = authorize_code(world, client)
    response = exchange(world, client, code)
    assert response.status_code == 200, response.text
    return client, response.json


def refresh(world, client, token, **extra):
    return post(world, "/oauth/token", data={"grant_type": "refresh_token", "client_id": client["client_id"],
               "refresh_token": token["refresh_token"], "resource": world["resource"], **extra})


def test_metadata_and_opaque_credentials(world):
    metadata = get(world, "/.well-known/oauth-authorization-server").json
    assert metadata["issuer"] == world["base"]
    assert metadata["client_id_metadata_document_supported"] is True
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["scopes_supported"] == list(SCOPES)
    client, token = issue(world)
    assert token["expires_in"] == 900
    identity = validate_access_token(token["access_token"], world["resource"])
    assert identity["client_id"] == client["client_id"]
    assert identity["operator_payload"]["user_id"] == 1
    assert identity["operator_payload"]["roles"] == ["admin"]
    with world["factory"]() as session:
        row = session.execute(select(OAuthTokenTable)).scalar_one()
        assert row.access_hash == credential_hash(token["access_token"])
        assert row.refresh_hash == credential_hash(token["refresh_token"])
        code = session.execute(select(OAuthAuthorizationCodeTable)).scalar_one()
        assert code.consumed_at is not None


@pytest.mark.parametrize("change", [
    {"code_challenge_method": "plain"}, {"code_challenge": ""},
    {"resource": "https://wrong.example/mcp"}, {"redirect_uri": "https://attacker.example/callback"},
    {"redirect_uri": "https://attacker.example/非法回调"},
    {"scope": "mcp unknown:scope"},
])
def test_authorization_rejects_invalid_parameters(world, change):
    client = client_registration(world)
    response = get(world, authorization_url(world, client, **change))
    assert response.status_code in (400, 302)
    if response.status_code == 302:
        assert "error=" in response.location
        assert "iss=" in response.location


def test_invalid_pkce_or_resource_cannot_consume_code(world):
    client = client_registration(world)
    code = authorize_code(world, client)
    assert exchange(world, client, code, code_verifier="b" * 64).status_code == 400
    assert exchange(world, client, code, resource="https://wrong.example/mcp").status_code == 400
    assert exchange(world, client, code).status_code == 200


def test_authorization_code_replay_revokes_issued_family(world):
    client = client_registration(world)
    code = authorize_code(world, client)
    response = exchange(world, client, code)
    assert response.status_code == 200
    assert exchange(world, client, code).status_code == 400
    assert validate_access_token(response.json["access_token"], world["resource"]) is None


def test_refresh_rotation_and_replay_revokes_all_descendants(world):
    client, token = issue(world)
    response = refresh(world, client, token)
    assert response.status_code == 200, response.text
    next_token = response.json
    assert next_token["refresh_token"] != token["refresh_token"]
    assert validate_access_token(token["access_token"], world["resource"]) is None
    assert validate_access_token(next_token["access_token"], world["resource"])
    assert refresh(world, client, token).status_code == 400
    assert validate_access_token(next_token["access_token"], world["resource"]) is None
    assert refresh(world, client, next_token).status_code == 400


def test_refresh_scope_cannot_expand(world):
    client = client_registration(world)
    code = authorize_code(world, client, scopes=["mcp", "orders:list"])
    token = exchange(world, client, code).json
    assert refresh(world, client, token, scope="mcp orders:create").status_code == 400
    response = refresh(world, client, token, scope="mcp")
    assert response.status_code == 200
    assert response.json["scope"] == "mcp"


def test_revocation_invalidates_entire_family(world):
    client, token = issue(world)
    response = post(world, "/oauth/revoke", data={"client_id": client["client_id"], "token": token["refresh_token"]})
    assert response.status_code == 200, response.text
    assert validate_access_token(token["access_token"], world["resource"]) is None
    assert refresh(world, client, token).status_code == 400


def test_rejected_deleted_expired_and_wrong_resource_are_invalid(world):
    client, token = issue(world)
    assert validate_access_token(token["access_token"], "https://wrong.example/mcp") is None
    with world["factory"]() as session:
        user = session.get(UserTable, 1)
        user.status = "rejected"
        session.commit()
    assert validate_access_token(token["access_token"], world["resource"]) is None
    assert refresh(world, client, token).status_code == 400


def test_role_changes_are_seen_without_reissuing_token(world):
    client, token = issue(world)
    with world["factory"]() as session:
        session.get(UserTable, 1).roles = []
        session.commit()
    assert validate_access_token(token["access_token"], world["resource"])["operator_payload"]["roles"] == []


@pytest.mark.parametrize("method", ["client_secret_basic", "client_secret_post"])
def test_confidential_clients_require_hashed_secret_and_pkce(world, method):
    client = client_registration(world, method=method)
    with world["factory"]() as session:
        row = session.get(OAuthClientTable, credential_hash(client["client_id"]))
        assert row.secret_hash == credential_hash(client["client_secret"])
    code = authorize_code(world, client)
    assert exchange(world, client, code).status_code == 401
    payload = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
               "code_verifier": VERIFIER, "resource": world["resource"]}
    headers = {}
    if method == "client_secret_basic":
        value = base64.b64encode((client["client_id"] + ":" + client["client_secret"]).encode()).decode()
        headers["Authorization"] = "Basic " + value
    else:
        payload.update(client_id=client["client_id"], client_secret=client["client_secret"])
    response = post(world, "/oauth/token", data=payload, headers=headers)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("redirect_uri", ["http://external.example/cb", "https://client.example/cb#fragment", "https://*.example/cb", "javascript:alert(1)"])
def test_registration_rejects_unsafe_redirects(world, redirect_uri):
    assert post(world, "/oauth/register", json={"redirect_uris": [redirect_uri]}).status_code == 400


def test_login_and_consent_require_csrf(world):
    client = client_registration(world)
    path = authorization_url(world, client)
    login_url = get(world, path).location
    page = get(world, login_url)
    assert "Secure" in page.headers["Set-Cookie"]
    assert "HttpOnly" in page.headers["Set-Cookie"]
    assert "SameSite=Lax" in page.headers["Set-Cookie"]
    assert post(world, login_url, data={"phone": "13800138000", "password": "Mcp-test-password"}).status_code == 403
    assert post(world, login_url, data={"csrf_token": csrf(page), "phone": "13800138000", "password": "Mcp-test-password"}).status_code == 302
    assert post(world, path, data={"decision": "approve", "approved_scope": list(SCOPES)}).status_code == 403


def _browser_login(world, client, **authorization):
    """Return the actual login page and consent URL for a fresh browser login."""
    path = authorization_url(world, client, **authorization)
    login_url = get(world, path).location
    page = get(world, login_url)
    assert page.status_code == 200
    response = post(world, login_url, data={"csrf_token": csrf(page),
        "phone": "13800138000", "password": "Mcp-test-password"})
    assert response.status_code == 302
    return page, login_url, path


def _callback_code(response):
    assert response.status_code == 302, response.text
    parameters = parse_qs(urlsplit(response.location).query)
    assert "code" in parameters and "error" not in parameters
    return parameters["code"][0]


def _form_action(response):
    policy = response.headers["Content-Security-Policy"]
    directives = [part.strip().split() for part in policy.split(";") if part.strip()]
    values = [items[1:] for items in directives if items[0] == "form-action"]
    assert len(values) == 1, policy
    return values[0]


class _CheckedScopes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.checked = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if (tag == "input" and attributes.get("name") == "approved_scope"
                and "checked" in attributes):
            self.checked.append(attributes["value"])


def _checked_scopes(response):
    parser = _CheckedScopes()
    parser.feed(response.text)
    return parser.checked


def test_concurrent_browser_consent_pages_both_issue_usable_codes(world):
    registered = client_registration(world)
    _, _, path_a = _browser_login(world, registered, state="browser-tab-a")
    path_b = authorization_url(world, registered, state="browser-tab-b")
    page_a, page_b = get(world, path_a), get(world, path_b)
    response_a = post(world, path_a, data={"csrf_token": csrf(page_a),
        "decision": "approve", "approved_scope": ["mcp", "orders:list"]})
    response_b = post(world, path_b, data={"csrf_token": csrf(page_b),
        "decision": "approve", "approved_scope": ["mcp", "orders:read"]})
    code_a, code_b = _callback_code(response_a), _callback_code(response_b)
    assert code_a != code_b
    token_a, token_b = exchange(world, registered, code_a), exchange(world, registered, code_b)
    assert token_a.status_code == token_b.status_code == 200
    assert set(token_a.json["scope"].split()) == {"mcp", "orders:list"}
    assert set(token_b.json["scope"].split()) == {"mcp", "orders:read"}


def test_login_csrf_failure_returns_retryable_form_without_authenticating(world):
    registered = client_registration(world)
    path = authorization_url(world, registered)
    login_url = get(world, path).location
    get(world, login_url)
    response = post(world, login_url, data={"csrf_token": "incorrect", "phone": "13800138000",
        "password": "Mcp-test-password"})
    assert response.status_code == 403
    replacement = csrf(response)
    assert get(world, path).status_code == 302  # Bad CSRF never logs the user in.
    recovered = post(world, login_url, data={"csrf_token": replacement,
        "phone": "13800138000", "password": "Mcp-test-password"})
    assert recovered.status_code == 302
    assert get(world, path).status_code == 200


def test_login_cookie_missing_remains_forbidden_with_correct_form_nonce(world):
    registered = client_registration(world)
    path = authorization_url(world, registered)
    login_url = get(world, path).location
    page = get(world, login_url)
    separate_browser = world["app"].test_client()
    response = separate_browser.post(login_url, base_url=world["base"], data={
        "csrf_token": csrf(page), "phone": "13800138000", "password": "Mcp-test-password"})
    assert response.status_code == 403
    assert separate_browser.get(path, base_url=world["base"]).status_code == 302
    with world["factory"]() as db:
        assert not db.execute(select(OAuthAuthorizationCodeTable)).all()


def test_consent_cookie_missing_cannot_use_another_browsers_valid_nonce(world):
    registered = client_registration(world)
    _, _, path = _browser_login(world, registered)
    consent = get(world, path)
    separate_browser = world["app"].test_client()
    response = separate_browser.post(path, base_url=world["base"], data={
        "csrf_token": csrf(consent), "decision": "approve", "approved_scope": ["mcp", "orders:read"]})
    assert response.status_code == 401
    with world["factory"]() as db:
        assert not db.execute(select(OAuthAuthorizationCodeTable)).all()


def test_login_rotates_session_so_pre_login_csrf_cannot_authorize(world):
    registered = client_registration(world)
    login_page, _, path = _browser_login(world, registered)
    consent = get(world, path)
    assert csrf(login_page) != csrf(consent)
    response = post(world, path, data={"csrf_token": csrf(login_page),
        "decision": "approve", "approved_scope": ["mcp", "orders:list"]})
    assert response.status_code == 403
    with world["factory"]() as db:
        assert not db.execute(select(OAuthAuthorizationCodeTable)).all()


@pytest.mark.parametrize("form_nonce", ["incorrect", ""])
def test_consent_csrf_failure_preserves_selection_and_retry_does_not_widen_scope(world, form_nonce):
    registered = client_registration(world)
    _, _, path = _browser_login(world, registered)
    get(world, path)
    selected = ["mcp", "orders:read"]
    response = post(world, path, data={"csrf_token": form_nonce,
        "decision": "approve", "approved_scope": selected})
    assert response.status_code == 403
    assert set(_checked_scopes(response)) == set(selected)
    with world["factory"]() as db:
        assert not db.execute(select(OAuthAuthorizationCodeTable)).all()
    recovered = post(world, path, data={"csrf_token": csrf(response),
        "decision": "approve", "approved_scope": _checked_scopes(response)})
    token = exchange(world, registered, _callback_code(recovered))
    assert token.status_code == 200
    assert set(token.json["scope"].split()) == set(selected)


def test_csrf_recovery_cannot_select_scopes_outside_the_authorization_request(world):
    registered = client_registration(world)
    _, _, path = _browser_login(world, registered, scope="mcp orders:read")
    response = post(world, path, data={"csrf_token": "incorrect", "decision": "approve",
        "approved_scope": ["mcp", "orders:read", "orders:create", "unrecognized"]})
    assert response.status_code == 403
    assert set(_checked_scopes(response)) == {"mcp", "orders:read"}
    recovered = post(world, path, data={"csrf_token": csrf(response), "decision": "approve",
        "approved_scope": _checked_scopes(response)})
    token = exchange(world, registered, _callback_code(recovered))
    assert token.status_code == 200
    assert set(token.json["scope"].split()) == {"mcp", "orders:read"}


@pytest.mark.parametrize("callback,origin", [
    ("http://127.0.0.1:43117/callback", "http://127.0.0.1:43117"),
    ("https://client.example.test:9443/oauth/callback", "https://client.example.test:9443"),
    ("https://client.example.test/callback?opaque=%3B%20form-action%20%2A", "https://client.example.test"),
])
def test_consent_csp_allows_only_the_validated_callback_origin(world, callback, origin):
    registered = client_registration(world, redirect_uris=[callback])
    login_page, _, path = _browser_login(world, registered, redirect_uri=callback)
    assert _form_action(login_page) == ["'self'"]
    consent = get(world, path)
    assert _form_action(consent) == ["'self'", origin]
    assert "opaque=" not in consent.headers["Content-Security-Policy"]
    assert "/callback" not in consent.headers["Content-Security-Policy"]
    response = post(world, path, data={"csrf_token": csrf(consent),
        "decision": "approve", "approved_scope": ["mcp", "orders:read"]})
    code = _callback_code(response)
    token = exchange(world, registered, code, redirect_uri=callback)
    assert token.status_code == 200
    assert _form_action(get(world, "/.well-known/oauth-authorization-server")) == ["'self'"]


def test_consent_csp_does_not_allow_other_registered_callback_origins(world):
    selected = "http://127.0.0.1:43117/callback"
    other = "https://other-client.example.test/callback"
    registered = client_registration(world, redirect_uris=[selected, other])
    _, _, path = _browser_login(world, registered, redirect_uri=selected)
    consent = get(world, path)
    assert _form_action(consent) == ["'self'", "http://127.0.0.1:43117"]
    assert "other-client.example.test" not in consent.headers["Content-Security-Policy"]


@pytest.mark.parametrize("unregistered", [
    "https://attacker.example/callback",
    "https://attacker.example/callback?inject=%3Bform-action%20%2A",
    "https://attacker.example'; form-action */callback",
])
def test_unvalidated_callback_cannot_expand_form_action_policy(world, unregistered):
    registered = client_registration(world)
    _browser_login(world, registered)
    response = get(world, authorization_url(world, registered, redirect_uri=unregistered))
    assert response.status_code == 400
    assert _form_action(response) == ["'self'"]
    assert "attacker.example" not in response.headers["Content-Security-Policy"]
    assert "*" not in response.headers["Content-Security-Policy"]
    with world["factory"]() as db:
        assert not db.execute(select(OAuthAuthorizationCodeTable)).all()


def test_denial_returns_issuer_and_no_code(world):
    client = client_registration(world)
    path = authorization_url(world, client)
    login_url = get(world, path).location
    page = get(world, login_url)
    post(world, login_url, data={"csrf_token": csrf(page), "phone": "13800138000", "password": "Mcp-test-password"})
    consent = get(world, path)
    response = post(world, path, data={"csrf_token": csrf(consent), "decision": "deny"})
    values = parse_qs(urlsplit(response.location).query)
    assert values["error"] == ["access_denied"]
    assert values["iss"] == [world["base"]]
    assert "code" not in values


def test_unconfigured_and_partial_config(monkeypatch):
    for name in ("OAUTH_ISSUER_URL", "MCP_PUBLIC_URL", "OAUTH_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    app = Flask(__name__)
    init_oauth(app)
    response = app.test_client().get("/.well-known/oauth-authorization-server")
    assert response.status_code == 503
    assert response.json["error"] == "oauth_not_configured"
    with pytest.raises(OAuthConfigurationError):
        load_oauth_settings({"OAUTH_ISSUER_URL": "https://wms.example.test"})


@pytest.mark.parametrize("overrides", [
    {"MCP_PUBLIC_URL": ""},
    {"OAUTH_ISSUER_URL": "http://8.166.137.88:8081/", "MCP_PUBLIC_URL": "http://8.166.137.88:8081/mcp", "OAUTH_ALLOW_LOCAL_HTTP": True},
    {"MCP_PUBLIC_URL": "http://8.166.137.88:8081/mcp", "OAUTH_ALLOW_LOCAL_HTTP": True},
    {"MCP_PUBLIC_URL": "https://wms.example.test/other"},
    {"OAUTH_SESSION_SECRET": "too-short"},
    {"OAUTH_ISSUER_URL": 123},
])
def test_invalid_oauth_configuration_keeps_rest_available_and_oauth_closed(monkeypatch, caplog, overrides):
    for name in ("OAUTH_ISSUER_URL", "MCP_PUBLIC_URL", "OAUTH_SESSION_SECRET", "OAUTH_ALLOW_LOCAL_HTTP"):
        monkeypatch.delenv(name, raising=False)
    config = {
        "OAUTH_ISSUER_URL": "https://wms.example.test",
        "MCP_PUBLIC_URL": "https://wms.example.test/mcp",
        "OAUTH_SESSION_SECRET": "configuration-secret-must-never-appear-in-logs",
        **overrides,
    }
    with pytest.raises(OAuthConfigurationError):
        load_oauth_settings(config)
    app = Flask(__name__)
    app.config.update(config, SECRET_KEY="existing-rest-session-secret")
    app.add_url_rule("/api/probe", view_func=lambda: {"code": 200})
    def unexpected_initialization(*args, **kwargs):
        pytest.fail("Disabled OAuth must not initialize its server or open a database transaction")
    monkeypatch.setattr("controllers.oauth_controller.create_authorization_server", unexpected_initialization)
    monkeypatch.setattr("controllers.oauth_controller.SessionFactory", unexpected_initialization)
    init_oauth(app)
    state = app.extensions["wms_oauth"]
    assert state["settings"] is None
    assert state["server"] is None
    assert state["config_error"]
    assert app.secret_key == "existing-rest-session-secret"
    assert app.config["SESSION_COOKIE_NAME"] == "session"
    assert "MCP OAuth disabled due to invalid configuration" in caplog.text
    assert "configuration-secret-must-never-appear-in-logs" not in caplog.text
    assert "too-short" not in caplog.text
    client = app.test_client()
    assert client.get("/api/probe").status_code == 200
    for method, path in (
        ("GET", "/.well-known/oauth-authorization-server"),
        ("GET", "/oauth/login"), ("POST", "/oauth/login"),
        ("GET", "/oauth/authorize"), ("POST", "/oauth/authorize"),
        ("POST", "/oauth/token"), ("POST", "/oauth/register"),
        ("POST", "/oauth/revoke"),
    ):
        response = client.open(path, method=method)
        assert response.status_code == 503
        assert response.json["error"] == "oauth_not_configured"
        assert "Set-Cookie" not in response.headers
        assert response.headers["Cache-Control"] == "no-store"


def test_oauth_initializer_does_not_hide_unexpected_errors(monkeypatch):
    def broken_loader(config):
        raise RuntimeError("unexpected implementation failure")
    monkeypatch.setattr("controllers.oauth_controller.load_oauth_settings", broken_loader)
    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        init_oauth(Flask(__name__))


def test_public_urls_require_https_or_explicit_loopback_http():
    with pytest.raises(OAuthConfigurationError):
        validate_oauth_public_urls("http://localhost:5000", "http://localhost:5000/mcp")
    assert validate_oauth_public_urls("http://localhost:5000", "http://localhost:5000/mcp", allow_local_http=True)
    with pytest.raises(OAuthConfigurationError):
        validate_oauth_public_urls("http://external.example", "http://external.example/mcp", allow_local_http=True)


def test_mcp_factory_keeps_rejecting_public_http_configuration(monkeypatch):
    from mcp_server import create_mcp_app
    monkeypatch.setenv("OAUTH_ALLOW_LOCAL_HTTP", "true")
    with pytest.raises(OAuthConfigurationError):
        create_mcp_app(issuer_url="http://8.166.137.88:8081/", resource_url="http://8.166.137.88:8081/mcp")


def test_canonical_issuer_ignores_request_host(world):
    client = client_registration(world)
    # Canonical requests continue to work behind an HTTP/TLS-offloading proxy;
    # neither Host nor X-Forwarded-Proto changes issuer/resource identity.
    response = world["client"].post("/oauth/register", base_url="http://untrusted.example",
        headers={"X-Forwarded-Proto": "http"}, json={"redirect_uris": [CALLBACK]})
    assert response.status_code == 201
    metadata = world["client"].get("/.well-known/oauth-authorization-server", base_url="http://untrusted.example").json
    assert metadata["issuer"] == world["base"]


def test_stale_authorization_code_cas_failure_revokes_winner(world):
    client, token = issue(world)
    with world["app"].test_request_context("/oauth/token", base_url=world["base"]):
        with world["factory"]() as session:
            g.oauth_db = session
            used = session.execute(select(OAuthAuthorizationCodeTable)).scalar_one()
            stale = SimpleNamespace(code_hash=used.code_hash, family_id=None, consumed_at=None)
            request = SimpleNamespace(authorization_code=stale)
            with pytest.raises(InvalidGrantError):
                save_token({"access_token": "unused-token", "expires_in": 900}, request)
            session.commit()
    assert validate_access_token(token["access_token"], world["resource"]) is None


def test_token_save_failure_rolls_back_code_consumption(world, monkeypatch):
    client = client_registration(world)
    code = authorize_code(world, client)
    original = OAuthTokenTable.__init__
    def fail_token(*args, **kwargs):
        raise RuntimeError("Token persistence failed")
    monkeypatch.setattr(OAuthTokenTable, "__init__", fail_token)
    with pytest.raises(RuntimeError, match="Token persistence failed"):
        exchange(world, client, code)
    with world["factory"]() as session:
        saved = session.get(OAuthAuthorizationCodeTable, credential_hash(code))
        assert saved.consumed_at is None
        assert saved.family_id is None
        assert not session.execute(select(OAuthTokenFamilyTable)).all()
    monkeypatch.setattr(OAuthTokenTable, "__init__", original)
    assert exchange(world, client, code).status_code == 200


def test_token_expiration_and_deletion_fail_closed(world):
    client, token = issue(world)
    with world["factory"]() as session:
        session.execute(select(OAuthTokenTable)).scalar_one().expires_at = int(time.time()) - 1
        session.commit()
    assert validate_access_token(token["access_token"], world["resource"]) is None
    rotated = refresh(world, client, token).json
    with world["factory"]() as session:
        user = session.get(UserTable, 1)
        session.delete(user)
        session.commit()
    assert validate_access_token(rotated["access_token"], world["resource"]) is None
    assert refresh(world, client, rotated).status_code == 400


def test_code_expiration_wrong_client_and_redirect_do_not_issue_tokens(world):
    client = client_registration(world)
    other = client_registration(world)
    code = authorize_code(world, client)
    assert exchange(world, other, code).status_code == 400
    assert exchange(world, client, code, redirect_uri="https://wrong.example/cb").status_code == 400
    with world["factory"]() as session:
        session.get(OAuthAuthorizationCodeTable, credential_hash(code)).expires_at = int(time.time()) - 1
        session.commit()
    assert exchange(world, client, code).status_code == 400


def test_dcr_omitted_auth_method_uses_rfc7591_confidential_default(world):
    response = post(world, "/oauth/register", json={"redirect_uris": [CALLBACK]})
    assert response.status_code == 201
    assert response.json["token_endpoint_auth_method"] == "client_secret_basic"
    assert response.json["client_secret"]


@pytest.mark.parametrize("metadata", [
    {"redirect_uris": [1]}, {"redirect_uris": "https://client.example/cb"},
    {"grant_types": [{}]}, {"scope": ["mcp"]}, {"token_endpoint_auth_method": []},
    {"client_uri": 123}, {"jwks": []},
])
def test_malformed_registration_is_an_oauth_error(world, metadata):
    payload = {"redirect_uris": [CALLBACK], **metadata}
    response = post(world, "/oauth/register", json=payload)
    assert response.status_code == 400, response.text
    assert response.json["error"] == "invalid_client_metadata"
