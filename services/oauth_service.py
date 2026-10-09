"""OAuth 2.1 authorization server callbacks and MCP resource-token verification."""

from dataclasses import dataclass
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import time
from urllib.parse import urlsplit

import certifi
import urllib3
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.integrations.flask_oauth2.requests import (
    FlaskJsonPayload, FlaskJsonRequest, FlaskOAuth2Payload, FlaskOAuth2Request,
)
from authlib.oauth2.rfc6749 import (
    InvalidClientError, InvalidGrantError, InvalidRequestError, JsonRequest,
    OAuth2Request,
)
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant, RefreshTokenGrant
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7591 import ClientRegistrationEndpoint
from authlib.oauth2.rfc7591.errors import InvalidClientMetadataError
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oauth2.rfc9207 import IssuerParameter
from flask import current_app, g, has_app_context, request
from sqlalchemy import or_, select, update

from Auth import normalize_roles
from data.database import SessionFactory
from data.oauth import (
    OAuthAuthorizationCodeTable, OAuthClientTable, OAuthTokenFamilyTable,
    OAuthTokenTable, credential_hash,
)
from data.user.User import STATUS_APPROVED, UserTable


SCOPES = ("mcp", "orders:create", "orders:list", "orders:read", "tracking:read", "packing_lists:create")
SCOPE_LABELS = {
    "mcp": "连接 MCP 并查看工具列表",
    "orders:create": "创建订单",
    "orders:list": "查询订单列表",
    "orders:read": "查询订单详情",
    "tracking:read": "查询订单下包裹及物流状态",
    "packing_lists:create": "创建装箱单",
}
CODE_SECONDS = 300
ACCESS_SECONDS = 900
REFRESH_SECONDS = 30 * 24 * 3600
CLIENT_METADATA_SECONDS = 300
CLIENT_METADATA_MAX_BYTES = 128 * 1024


@dataclass(frozen=True)
class OAuthSettings:
    issuer: str
    resource: str
    session_secret: str


class OAuthConfigurationError(ValueError):
    """Invalid deployment configuration; messages never include configured secrets."""


def _loopback(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host or "")
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


def _valid_public_url(value, allow_local_http=False):
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return bool(
            parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and (parsed.scheme == "https" or (allow_local_http and parsed.scheme == "http" and _loopback(parsed.hostname)))
        )
    except (ValueError, TypeError):
        return False


def validate_oauth_public_urls(issuer, resource, *, allow_local_http=False):
    """Shared Flask/MCP URL contract; never derive public URLs from request headers."""
    if not isinstance(issuer, str) or not isinstance(resource, str):
        raise OAuthConfigurationError("OAuth issuer and MCP resource URLs must be strings")
    issuer = issuer.rstrip("/")
    if not _valid_public_url(issuer, allow_local_http) or urlsplit(issuer).path:
        raise OAuthConfigurationError("OAUTH_ISSUER_URL must be an HTTPS origin (explicit HTTP mode is loopback-only)")
    if not _valid_public_url(resource, allow_local_http) or urlsplit(resource).path != "/mcp":
        raise OAuthConfigurationError("MCP_PUBLIC_URL must be the canonical HTTPS /mcp URL (explicit HTTP mode is loopback-only)")
    return issuer, resource


def load_oauth_settings(config=None):
    """Validate strictly; the Flask initializer isolates configuration failures from REST."""
    values = []
    for name in ("OAUTH_ISSUER_URL", "MCP_PUBLIC_URL", "OAUTH_SESSION_SECRET"):
        value = (config or {}).get(name) or os.environ.get(name, "")
        if not isinstance(value, str):
            raise OAuthConfigurationError(f"{name} must be a string")
        values.append(value.strip())
    if not any(values):
        return None
    if not all(values):
        raise OAuthConfigurationError("Configure OAUTH_ISSUER_URL, MCP_PUBLIC_URL and OAUTH_SESSION_SECRET together")
    issuer, resource, secret = values
    allow_http = (config or {}).get("OAUTH_ALLOW_LOCAL_HTTP", os.environ.get("OAUTH_ALLOW_LOCAL_HTTP", "false"))
    allow_http = allow_http is True or str(allow_http).lower() in {"1", "true", "yes"}
    issuer, resource = validate_oauth_public_urls(issuer, resource, allow_local_http=allow_http)
    if len(secret) < 32:
        raise OAuthConfigurationError("OAUTH_SESSION_SECRET must contain at least 32 characters")
    return OAuthSettings(issuer, resource, secret)


def settings():
    if has_app_context() and "wms_oauth" in current_app.extensions:
        return current_app.extensions["wms_oauth"]["settings"]
    return load_oauth_settings()


def db():
    return g.oauth_db


def operator_payload(user):
    roles = normalize_roles([role.name for role in user.roles])
    return {"user_id": user.id, "name": user.name, "phone": user.phone,
            "roles": roles, "role": roles[0] if roles else None}


def approved_user(user_id, session=None):
    user = (session or db()).get(UserTable, user_id)
    return user if user is not None and user.status == STATUS_APPROVED else None


def validate_access_token(raw_token, resource):
    """Return a current WMS identity, or None; database failures deliberately propagate."""
    conf = settings()
    if not conf or not isinstance(raw_token, str) or not raw_token or len(raw_token) > 4096:
        return None
    if resource != conf.resource:
        return None
    now = int(time.time())
    with SessionFactory() as session:
        row = session.execute(
            select(OAuthTokenTable, OAuthTokenFamilyTable, OAuthClientTable)
            .join(OAuthTokenFamilyTable, OAuthTokenTable.family_id == OAuthTokenFamilyTable.family_id)
            .join(OAuthClientTable, OAuthTokenFamilyTable.client_key == OAuthClientTable.client_key)
            .where(OAuthTokenTable.access_hash == credential_hash(raw_token))
        ).first()
        if not row:
            return None
        token, family, client = row
        if (token.revoked_at is not None or family.revoked_at is not None
                or token.expires_at <= now or family.expires_at <= now
                or family.resource != resource or family.issuer != conf.issuer):
            return None
        user = approved_user(family.user_id, session)
        if user is None:
            return None
        return {"user_id": user.id, "client_id": client.client_id,
                "scopes": token.scope.split(), "expires_at": token.expires_at,
                "resource": family.resource, "issuer": family.issuer,
                "operator_payload": operator_payload(user)}


def require_resource(oauth_request):
    values = oauth_request.payload.datalist.get("resource", [])
    if len(values) != 1 or values[0] != settings().resource:
        raise InvalidRequestError("A single canonical MCP 'resource' is required.")
    return values[0]


def _validate_redirect(uri):
    if not isinstance(uri, str) or len(uri) > 2048:
        return False
    try:
        parsed = urlsplit(uri)
        _ = parsed.port
        return bool(parsed.hostname and not parsed.username and not parsed.password
                    and not parsed.fragment and "*" not in uri
                    and (parsed.scheme == "https" or
                         (parsed.scheme == "http" and _loopback(parsed.hostname))))
    except ValueError:
        return False


def normalize_client_metadata(metadata, *, cimd=False):
    if not isinstance(metadata, dict):
        raise InvalidClientMetadataError("Client metadata must be a JSON object.")
    redirects = metadata.get("redirect_uris")
    if not isinstance(redirects, list) or not 1 <= len(redirects) <= 20 or not all(map(_validate_redirect, redirects)):
        raise InvalidClientMetadataError("Register 1-20 exact HTTPS or HTTP loopback redirect URIs.")
    name = metadata.get("client_name", "MCP client")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise InvalidClientMetadataError("Invalid client_name.")
    if cimd and "client_name" not in metadata:
        raise InvalidClientMetadataError("CIMD requires client_name.")
    method = metadata.get("token_endpoint_auth_method", "none" if cimd else "client_secret_basic")
    if not isinstance(method, str) or method not in ({"none"} if cimd else {"none", "client_secret_basic", "client_secret_post"}):
        raise InvalidClientMetadataError("Unsupported token_endpoint_auth_method.")
    grant_types = metadata.get("grant_types", ["authorization_code", "refresh_token"])
    response_types = metadata.get("response_types", ["code"])
    if (not isinstance(grant_types, list) or not all(isinstance(grant, str) for grant in grant_types) or "authorization_code" not in grant_types
            or not set(grant_types).issubset({"authorization_code", "refresh_token"})
            or response_types != ["code"]):
        raise InvalidClientMetadataError("Only authorization_code/refresh_token and response type code are supported.")
    scope = metadata.get("scope", " ".join(SCOPES))
    if not isinstance(scope, str) or not set(scope.split()).issubset(SCOPES):
        raise InvalidClientMetadataError("Unsupported scopes.")
    normalized = {"client_name": name.strip(), "redirect_uris": list(dict.fromkeys(redirects)),
                  "token_endpoint_auth_method": method, "grant_types": grant_types,
                  "response_types": response_types, "scope": " ".join(dict.fromkeys(scope.split()))}
    if "application_type" in metadata:
        application_type = metadata["application_type"]
        if not isinstance(application_type, str) or application_type not in {"native", "web"}:
            raise InvalidClientMetadataError("Unsupported application_type.")
        normalized["application_type"] = application_type
    return normalized


def fetch_client_metadata(client_id):
    """Fetch CIMD over TLS to a DNS-pinned public IP, preserving certificate/SNI checks."""
    try:
        parsed = urlsplit(client_id)
        if (len(client_id) > 2048 or parsed.scheme != "https" or not parsed.hostname
                or parsed.path in ("", "/") or parsed.fragment or parsed.username
                or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("CIMD client_id must be an HTTPS URL with a non-root path and port 443.")
        hostname = parsed.hostname.encode("idna").decode("ascii")
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
        def public_address(value):
            address = ipaddress.ip_address(value)
            return address.is_global and not (address.is_multicast or address.is_reserved
                    or address.is_loopback or address.is_link_local or address.is_unspecified)
        if not addresses or not all(public_address(address) for address in addresses):
            raise ValueError("CIMD metadata must resolve only to public addresses.")
        address = sorted(addresses)[0]
        pool = urllib3.HTTPSConnectionPool(
            address, port=443, server_hostname=hostname, assert_hostname=hostname,
            cert_reqs=ssl.CERT_REQUIRED, ca_certs=certifi.where(),
            timeout=urllib3.Timeout(connect=3, read=5), maxsize=1,
        )
        response = None
        try:
            target = parsed.path + (("?" + parsed.query) if parsed.query else "")
            response = pool.request("GET", target,
                                    headers={"Host": parsed.netloc, "Accept": "application/json", "Accept-Encoding": "identity"},
                                    redirect=False, retries=False, preload_content=False)
            if response.status != 200:
                raise ValueError("CIMD metadata fetch did not return HTTP 200; redirects are not followed.")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise ValueError("CIMD metadata must use application/json.")
            length = response.headers.get("Content-Length")
            if length and int(length) > CLIENT_METADATA_MAX_BYTES:
                raise ValueError("CIMD metadata is too large.")
            body = response.read(CLIENT_METADATA_MAX_BYTES + 1, decode_content=False)
            if len(body) > CLIENT_METADATA_MAX_BYTES:
                raise ValueError("CIMD metadata is too large.")
            metadata = json.loads(body.decode("utf-8"))
        finally:
            if response is not None:
                response.close()
            pool.close()
        if not isinstance(metadata, dict) or metadata.get("client_id") != client_id:
            raise ValueError("CIMD client_id must match its URL exactly.")
        return normalize_client_metadata(metadata, cimd=True)
    except (ValueError, TypeError, OSError, UnicodeError, urllib3.exceptions.HTTPError, InvalidClientMetadataError) as exc:
        raise InvalidClientError(description="Unable to validate the client metadata document.") from exc


def query_client(client_id):
    if not isinstance(client_id, str) or not client_id or len(client_id) > 2048:
        return None
    key = credential_hash(client_id)
    row = db().get(OAuthClientTable, key)
    if row and row.client_id != client_id:
        return None
    if client_id.startswith(("https://", "http://")):
        now = int(time.time())
        if row and row.source == "cimd" and row.metadata_expires_at > now:
            return row
        metadata = fetch_client_metadata(client_id)
        if row is None:
            row = OAuthClientTable(client_key=key, client_id=client_id, source="cimd", issued_at=now)
            db().add(row)
        row.metadata_json = metadata
        row.metadata_expires_at = now + CLIENT_METADATA_SECONDS
        db().flush()
    return row


def revoke_family(family_id):
    db().execute(update(OAuthTokenFamilyTable).where(
        OAuthTokenFamilyTable.family_id == family_id,
        OAuthTokenFamilyTable.revoked_at.is_(None),
    ).values(revoked_at=int(time.time())))


class S256CodeChallenge(CodeChallenge):
    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]

    def validate_code_challenge(self, grant, redirect_uri):
        payload = grant.request.payload.data
        if payload.get("code_challenge_method") != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", payload.get("code_challenge", "")):
            raise InvalidRequestError("PKCE S256 is required for every client.")
        return super().validate_code_challenge(grant, redirect_uri)


class WmsAuthorizationCodeGrant(AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["none", "client_secret_basic", "client_secret_post"]

    @staticmethod
    def validate_authorization_redirect_uri(oauth_request, client):
        redirect_uri = oauth_request.payload.redirect_uri
        if not redirect_uri or not client.check_redirect_uri(redirect_uri):
            # OAuth error descriptions are ASCII; do not interpolate a URI
            # supplied by an untrusted client into the library's error text.
            raise InvalidRequestError("An exact registered redirect_uri is required.")
        return redirect_uri

    def validate_authorization_request(self):
        require_resource(self.request)
        if not self.request.payload.redirect_uri:
            raise InvalidRequestError("An explicit redirect_uri is required.")
        return super().validate_authorization_request()

    def validate_token_request(self):
        require_resource(self.request)
        return super().validate_token_request()

    def save_authorization_code(self, code, oauth_request):
        now = int(time.time())
        conf = settings()
        db().add(OAuthAuthorizationCodeTable(
            code_hash=credential_hash(code), client_key=oauth_request.client.client_key,
            user_id=oauth_request.user.id, redirect_uri=oauth_request.payload.redirect_uri,
            scope=getattr(g, "oauth_consent_scope", oauth_request.scope),
            code_challenge=oauth_request.payload.data["code_challenge"], code_challenge_method="S256",
            resource=conf.resource, issuer=conf.issuer, created_at=now, expires_at=now + CODE_SECONDS,
        ))
        db().flush()

    def query_authorization_code(self, code, client):
        row = db().execute(select(OAuthAuthorizationCodeTable).where(
            OAuthAuthorizationCodeTable.code_hash == credential_hash(code),
            OAuthAuthorizationCodeTable.client_key == client.client_key,
        ).with_for_update()).scalar_one_or_none()
        conf = settings()
        if not row or row.resource != conf.resource or row.issuer != conf.issuer or row.expires_at <= int(time.time()):
            return None
        if row.consumed_at is not None:
            verifier = self.request.form.get("code_verifier", "")
            from authlib.oauth2.rfc7636.challenge import create_s256_code_challenge
            if (row.family_id and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                    and create_s256_code_challenge(verifier) == row.code_challenge
                    and self.request.payload.redirect_uri == row.redirect_uri):
                revoke_family(row.family_id)
            return None
        return row

    def authenticate_user(self, authorization_code):
        return approved_user(authorization_code.user_id)

    def delete_authorization_code(self, authorization_code):
        authorization_code.consumed_at = int(time.time())


class WmsRefreshTokenGrant(RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["none", "client_secret_basic", "client_secret_post"]
    INCLUDE_NEW_REFRESH_TOKEN = True

    def validate_token_request(self):
        require_resource(self.request)
        return super().validate_token_request()

    def authenticate_refresh_token(self, raw_token):
        # Lock the family first. Every rotation/revocation shares this lock,
        # including replay of a consumed parent while its descendant rotates.
        token = db().execute(select(OAuthTokenTable).where(
            OAuthTokenTable.refresh_hash == credential_hash(raw_token),
        )).scalar_one_or_none()
        if not token or token.client_key != self.request.client.client_key:
            return None
        family = db().execute(select(OAuthTokenFamilyTable).where(
            OAuthTokenFamilyTable.family_id == token.family_id,
        ).with_for_update()).scalar_one_or_none()
        db().refresh(token, with_for_update=True)
        conf = settings()
        now = int(time.time())
        if not family or family.resource != conf.resource or family.issuer != conf.issuer:
            return None
        if token.consumed_at is not None:
            revoke_family(token.family_id)
            return None
        if (family.revoked_at is not None or family.expires_at <= now
                or token.revoked_at is not None or token.refresh_expires_at <= now):
            return None
        self.request.token_family = family
        return token

    def authenticate_user(self, refresh_token):
        user = approved_user(self.request.token_family.user_id)
        if not user:
            revoke_family(refresh_token.family_id)
            raise InvalidGrantError("The WMS account is unavailable.")
        return user

    def revoke_old_credential(self, refresh_token):
        refresh_token.consumed_at = int(time.time())
        refresh_token.revoked_at = int(time.time())


def save_token(token, oauth_request):
    now = int(time.time())
    conf = settings()
    family = getattr(oauth_request, "token_family", None)
    # Conditional writes also protect one-time consumption on databases whose
    # SELECT FOR UPDATE is ineffective (SQLite) or when a stale row is observed.
    if family is None:
        code = oauth_request.authorization_code
        consumed = db().execute(update(OAuthAuthorizationCodeTable).where(
            OAuthAuthorizationCodeTable.code_hash == code.code_hash,
            OAuthAuthorizationCodeTable.consumed_at.is_(None),
        ).values(consumed_at=now).execution_options(synchronize_session=False))
        if consumed.rowcount != 1:
            winner = db().execute(select(OAuthAuthorizationCodeTable).where(
                OAuthAuthorizationCodeTable.code_hash == code.code_hash,
            ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if winner and winner.family_id:
                revoke_family(winner.family_id)
            raise InvalidGrantError("The authorization code has already been consumed.")
    else:
        previous = oauth_request.refresh_token
        consumed = db().execute(update(OAuthTokenTable).where(
            OAuthTokenTable.id == previous.id, OAuthTokenTable.consumed_at.is_(None),
        ).values(consumed_at=now, revoked_at=now).execution_options(synchronize_session=False))
        if consumed.rowcount != 1:
            revoke_family(family.family_id)
            raise InvalidGrantError("The refresh token has already been consumed.")
    if family is None:
        family = OAuthTokenFamilyTable(
            family_id=secrets.token_urlsafe(32), client_key=oauth_request.client.client_key,
            user_id=oauth_request.user.id, resource=conf.resource, issuer=conf.issuer,
            created_at=now, expires_at=now + REFRESH_SECONDS,
        )
        db().add(family)
        db().flush()
        oauth_request.authorization_code.family_id = family.family_id
    token["expires_in"] = min(token["expires_in"], family.expires_at - now)
    db().add(OAuthTokenTable(
        access_hash=credential_hash(token["access_token"]),
        refresh_hash=credential_hash(token["refresh_token"]) if token.get("refresh_token") else None,
        family_id=family.family_id, client_key=oauth_request.client.client_key,
        scope=token.get("scope", ""), issued_at=now, expires_at=now + token["expires_in"],
        refresh_expires_at=family.expires_at,
    ))
    token["resource"] = family.resource
    db().flush()


def authorization_server_metadata():
    conf = settings()
    return {
        "issuer": conf.issuer,
        "authorization_endpoint": conf.issuer + "/oauth/authorize",
        "token_endpoint": conf.issuer + "/oauth/token",
        "registration_endpoint": conf.issuer + "/oauth/register",
        "revocation_endpoint": conf.issuer + "/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "scopes_supported": list(SCOPES), "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
    }


class WmsClientRegistrationEndpoint(ClientRegistrationEndpoint):
    def authenticate_token(self, oauth_request):
        # Automatic public registration is part of the approved MCP client flow.
        return True

    def get_server_metadata(self):
        return authorization_server_metadata()

    def extract_client_metadata(self, oauth_request):
        if not isinstance(oauth_request.payload.data, dict):
            raise InvalidClientMetadataError("Client metadata must be an object.")
        if "software_statement" in oauth_request.payload.data:
            raise InvalidClientMetadataError("Software statements are not supported.")
        original = oauth_request.payload.data
        # Authlib validates standard claims first; apply our exact redirect,
        # grant, scope and authentication-method policy to the resulting claims.
        normalized = normalize_client_metadata(original)
        try:
            super().extract_client_metadata(oauth_request)
        except (TypeError, ValueError, AttributeError) as exc:
            raise InvalidClientMetadataError("Malformed client metadata.") from exc
        return normalized

    def generate_client_secret(self, oauth_request):
        method = oauth_request.payload.data.get("token_endpoint_auth_method", "client_secret_basic")
        return secrets.token_urlsafe(48) if method != "none" else ""

    def save_client(self, client_info, client_metadata, oauth_request):
        row = OAuthClientTable(
            client_key=credential_hash(client_info["client_id"]), client_id=client_info["client_id"],
            secret_hash=credential_hash(client_info["client_secret"]) if client_info["client_secret"] else None,
            metadata_json=client_metadata, source="dcr", issued_at=client_info["client_id_issued_at"],
        )
        db().add(row)
        db().flush()
        return row


class WmsRevocationEndpoint(RevocationEndpoint):
    CLIENT_AUTH_METHODS = ["none", "client_secret_basic", "client_secret_post"]

    def query_token(self, raw_token, token_type_hint):
        digest = credential_hash(raw_token)
        return db().execute(select(OAuthTokenTable).where(or_(
            OAuthTokenTable.access_hash == digest, OAuthTokenTable.refresh_hash == digest,
        ))).scalar_one_or_none()

    def revoke_token(self, token, oauth_request):
        # Serialize revocation with descendant refreshes.
        db().execute(select(OAuthTokenFamilyTable).where(
            OAuthTokenFamilyTable.family_id == token.family_id,
        ).with_for_update()).scalar_one()
        revoke_family(token.family_id)


class WmsIssuerParameter(IssuerParameter):
    def get_issuer(self):
        return settings().issuer


class CanonicalOAuthRequest(FlaskOAuth2Request):
    def __init__(self, flask_request):
        uri = settings().issuer + flask_request.path
        if flask_request.query_string:
            uri += "?" + flask_request.query_string.decode("ascii")
        OAuth2Request.__init__(self, method=flask_request.method, uri=uri, headers=flask_request.headers)
        self._request = flask_request
        self.payload = FlaskOAuth2Payload(flask_request)


class CanonicalJsonRequest(FlaskJsonRequest):
    def __init__(self, flask_request):
        JsonRequest.__init__(self, flask_request.method, settings().issuer + flask_request.path, flask_request.headers)
        self._request = flask_request
        self.payload = FlaskJsonPayload(flask_request)


class WmsAuthorizationServer(AuthorizationServer):
    def create_oauth2_request(self, ignored_request):
        return CanonicalOAuthRequest(request)

    def create_json_request(self, ignored_request):
        return CanonicalJsonRequest(request)


def create_authorization_server(app):
    app.config.update(OAUTH2_SCOPES_SUPPORTED=list(SCOPES),
                      OAUTH2_REFRESH_TOKEN_GENERATOR=True,
                      OAUTH2_TOKEN_EXPIRES_IN={"authorization_code": ACCESS_SECONDS, "refresh_token": ACCESS_SECONDS})
    server = WmsAuthorizationServer(app, query_client=query_client, save_token=save_token)
    server.register_grant(WmsAuthorizationCodeGrant, [S256CodeChallenge(required=True)])
    server.register_grant(WmsRefreshTokenGrant)
    server.register_endpoint(WmsClientRegistrationEndpoint)
    server.register_endpoint(WmsRevocationEndpoint)
    server.register_extension(WmsIssuerParameter())
    return server
