"""Browser authorization and OAuth machine endpoints; separate from REST JWT authentication."""

from datetime import timedelta
from functools import wraps
import hmac
import ipaddress
import re
import secrets
from urllib.parse import urlencode, urlsplit

from authlib.oauth2.rfc6749 import OAuth2Error
from flask import (
    Blueprint, current_app, g, jsonify, redirect,
    render_template, request, session,
)

from data.database import SessionFactory
from services.auth_service import authenticate_user
from services.oauth_service import (
    SCOPES, SCOPE_LABELS, OAuthConfigurationError, WmsIssuerParameter, approved_user,
    authorization_server_metadata, create_authorization_server, load_oauth_settings,
)


oauth_bp = Blueprint("oauth", __name__)


def init_oauth(app):
    config_error = None
    try:
        conf = load_oauth_settings(app.config)
    except OAuthConfigurationError as error:
        # OAuth is optional for existing REST users. Invalid configuration must
        # disable authorization, rather than stop every Gunicorn worker.
        conf = None
        config_error = str(error)
        app.logger.error("MCP OAuth disabled due to invalid configuration: %s", config_error)
    state = {"settings": conf, "server": None, "config_error": config_error}
    app.extensions["wms_oauth"] = state
    if conf:
        app.config.update(
            SECRET_KEY=conf.session_secret,
            SESSION_COOKIE_NAME="wms_oauth_session",
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SECURE=conf.issuer.startswith("https://"),
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_PATH="/oauth",
            PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        )
        state["server"] = create_authorization_server(app)
    app.register_blueprint(oauth_bp)


def _server():
    return current_app.extensions["wms_oauth"]["server"]


def _error(code, message, status=400):
    return jsonify({"error": code, "error_description": message}), status


def _transaction(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if _server() is None:
            return _error("oauth_not_configured", "MCP OAuth has not been configured.", 503)
        request.max_content_length = 64 * 1024
        with SessionFactory() as db_session:
            g.oauth_db = db_session
            try:
                response = func(*args, **kwargs)
                # A replay error may revoke a family. Commit the request's
                # mutations atomically, including these fail-closed revocations.
                db_session.commit()
                return response
            except Exception:
                db_session.rollback()
                raise
            finally:
                g.pop("oauth_db", None)
    return wrapped


@oauth_bp.after_request
def _response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # Chromium checks POST redirects against the submitting page's form-action.
    # Consent may return to an HTTPS client or its registered loopback listener.
    # Only a redirect validated by Authlib's consent grant can add a CSP source.
    form_action = "'self'"
    callback_source = getattr(g, "oauth_callback_source", None)
    if callback_source:
        form_action += " " + callback_source
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; form-action " + form_action
        + "; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


def _callback_csp_source(redirect_uri):
    """Build a header-safe origin from an already validated redirect URI."""
    parsed = urlsplit(redirect_uri)
    host = parsed.hostname
    if parsed.scheme not in {"https", "http"} or not host:
        return None
    try:
        address = ipaddress.ip_address(host)
        host = "[" + address.compressed + "]" if address.version == 6 else str(address)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
            return None
    return parsed.scheme + "://" + host + ((":" + str(parsed.port)) if parsed.port else "")


def _csrf_token():
    if "oauth_csrf" not in session:
        session["oauth_csrf"] = secrets.token_urlsafe(32)
    return session["oauth_csrf"]


def _valid_csrf():
    actual = request.form.get("csrf_token", "")
    expected = session.get("oauth_csrf", "")
    return bool(actual and expected and hmac.compare_digest(actual, expected))


def _next_url(value):
    if not isinstance(value, str) or len(value) > 8192 or "\\" in value or "\r" in value or "\n" in value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != "/oauth/authorize":
        return None
    return value


def _reject_duplicate_machine_params():
    fields = ("grant_type", "client_id", "client_secret", "code", "redirect_uri", "scope",
              "resource", "refresh_token", "code_verifier", "token", "token_type_hint")
    if any(len(request.values.getlist(field)) > 1 for field in fields):
        return _error("invalid_request", "OAuth parameters must occur only once.")
    return None


@oauth_bp.get("/.well-known/oauth-authorization-server")
@_transaction
def metadata():
    return jsonify(authorization_server_metadata())


@oauth_bp.route("/oauth/login", methods=["GET", "POST"])
@_transaction
def login():
    target = _next_url(request.args.get("next", ""))
    if not target:
        return _error("invalid_request", "Start login from the MCP authorization request.")
    error = None
    if request.method == "POST":
        if not _valid_csrf():
            return render_template(
                "oauth/login.html", csrf_token=_csrf_token(),
                error="页面会话已更新或已过期，请重新登录。若重复出现，请在系统浏览器中打开授权链接。",
            ), 403
        user, error = authenticate_user(request.form.get("phone", "").strip(), request.form.get("password", ""))
        if user:
            session.clear()
            session.permanent = True
            session["oauth_user_id"] = user["id"]
            _csrf_token()
            return redirect(target)
    return render_template("oauth/login.html", csrf_token=_csrf_token(), error=error), (401 if error else 200)


@oauth_bp.route("/oauth/authorize", methods=["GET", "POST"])
@_transaction
def authorize():
    server = _server()
    user_id = session.get("oauth_user_id")
    user = approved_user(user_id) if isinstance(user_id, int) else None
    try:
        grant = server.get_consent_grant(end_user=user)
    except OAuth2Error as error:
        response = server.handle_error_response(server.create_oauth2_request(None), error)
        WmsIssuerParameter().add_issuer_parameter(server, response)
        return response
    g.oauth_callback_source = _callback_csp_source(grant.request.payload.redirect_uri)
    if request.method == "POST":
        if not user:
            return _error("access_denied", "Login is required.", 401)
        if not _valid_csrf():
            return _consent_page(
                grant, user, error="页面会话已更新或已过期，请确认所选权限后重新提交。",
                selected_scopes=request.form.getlist("approved_scope"),
            ), 403
        if request.form.get("decision") == "deny":
            return server.create_authorization_response(grant_user=None, grant=grant)
        if request.form.get("decision") != "approve":
            return _error("invalid_request", "Choose whether to authorize this client.")
        selected = request.form.getlist("approved_scope")
        requested = grant.request.scope.split()
        if "mcp" not in selected or not set(selected).issubset(requested):
            return _error("invalid_scope", "Approve only requested permissions and include mcp.")
        g.oauth_consent_scope = " ".join(scope for scope in SCOPES if scope in selected)
        response = server.create_authorization_response(grant_user=user, grant=grant)
        # The session nonce stays stable across consent tabs. Login still
        # rebuilds the session, invalidating every pre-login form token.
        return response
    if not user:
        session.pop("oauth_user_id", None)
        target = request.full_path if request.query_string else request.path
        return redirect("/oauth/login?" + urlencode({"next": target}))
    return _consent_page(grant, user)


def _consent_page(grant, user, *, error=None, selected_scopes=None):
    client = grant.request.client
    redirect_uri = grant.request.payload.redirect_uri
    source = urlsplit(client.client_id).netloc if client.source == "cimd" else "动态注册客户端"
    requested = grant.request.scope.split()
    selected = requested if selected_scopes is None else [scope for scope in selected_scopes if scope in requested]
    return render_template(
        "oauth/consent.html", client_name=client.metadata_json["client_name"],
        client_source=source, callback_host=urlsplit(redirect_uri).netloc,
        user_name=user.name, csrf_token=_csrf_token(),
        scopes=[(scope, SCOPE_LABELS[scope]) for scope in requested],
        error=error, selected_scopes=selected,
    )


@oauth_bp.post("/oauth/token")
@_transaction
def token():
    invalid = _reject_duplicate_machine_params()
    return invalid if invalid else _server().create_token_response()


@oauth_bp.post("/oauth/register")
@_transaction
def register():
    if not request.is_json:
        return _error("invalid_client_metadata", "Send JSON client metadata.")
    return _server().create_endpoint_response("client_registration")


@oauth_bp.post("/oauth/revoke")
@_transaction
def revoke():
    invalid = _reject_duplicate_machine_params()
    return invalid if invalid else _server().create_endpoint_response("revocation")
