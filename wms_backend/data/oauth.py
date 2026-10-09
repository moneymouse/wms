"""Persistent OAuth credentials. Raw codes, client secrets and tokens are never stored."""

import hashlib
import hmac
import ipaddress
from urllib.parse import urlsplit

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, JSON, String, Text

from data.database import Base


def credential_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _native_loopback_redirect_key(uri):
    """Remove only the port from a valid HTTP loopback redirect URI."""
    if (not isinstance(uri, str) or not uri.startswith("http://")
            or any(character in uri for character in "\r\n\t")):
        return None
    try:
        parsed = urlsplit(uri)
        port = parsed.port
        if parsed.username or parsed.password or parsed.fragment:
            return None
        if parsed.hostname != "localhost" and not ipaddress.ip_address(parsed.hostname).is_loopback:
            return None
        authority = parsed.netloc
        if port is not None:
            authority = authority.rsplit(":", 1)[0]
        elif authority.endswith(":"):
            return None
        # Preserve the original host spelling, path and query, including an
        # empty query delimiter. RFC 8252 permits changing only the port.
        return "http://" + authority + uri[len("http://") + len(parsed.netloc):]
    except (TypeError, ValueError):
        return None


class OAuthClientTable(Base):
    __tablename__ = "oauth_clients"

    # URL client identifiers can exceed MySQL's index size; index their digest.
    client_key = Column(String(64), primary_key=True)
    client_id = Column(Text, nullable=False)
    secret_hash = Column(String(64))
    metadata_json = Column(JSON, nullable=False)
    source = Column(String(16), nullable=False)
    issued_at = Column(BigInteger, nullable=False)
    metadata_expires_at = Column(BigInteger)

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        return self.metadata_json["redirect_uris"][0]

    def get_allowed_scope(self, scope):
        allowed = self.metadata_json["scope"].split()
        requested = scope.split() if scope is not None else allowed
        if not set(requested).issubset(allowed):
            return None
        return " ".join(dict.fromkeys(requested))

    def check_redirect_uri(self, redirect_uri):
        registered = self.metadata_json["redirect_uris"]
        if redirect_uri in registered:
            return True
        if self.metadata_json.get("application_type") != "native":
            return False
        # Native apps bind a fresh loopback port for each authorization. Other
        # components and all non-loopback redirects still match exactly.
        requested = _native_loopback_redirect_key(redirect_uri)
        return requested is not None and any(
            requested == _native_loopback_redirect_key(uri) for uri in registered
        )

    def check_client_secret(self, client_secret):
        return bool(self.secret_hash and client_secret and hmac.compare_digest(
            self.secret_hash, credential_hash(client_secret)
        ))

    def check_endpoint_auth_method(self, method, endpoint):
        return method == self.metadata_json["token_endpoint_auth_method"]

    def check_response_type(self, response_type):
        return response_type in self.metadata_json["response_types"]

    def check_grant_type(self, grant_type):
        return grant_type in self.metadata_json["grant_types"]


class OAuthAuthorizationCodeTable(Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash = Column(String(64), primary_key=True)
    client_key = Column(String(64), ForeignKey("oauth_clients.client_key", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    redirect_uri = Column(Text, nullable=False)
    scope = Column(Text, nullable=False)
    code_challenge = Column(String(128), nullable=False)
    code_challenge_method = Column(String(16), nullable=False)
    resource = Column(Text, nullable=False)
    issuer = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    consumed_at = Column(BigInteger)
    family_id = Column(String(64))

    def get_redirect_uri(self):
        return self.redirect_uri

    def get_scope(self):
        return self.scope


class OAuthTokenFamilyTable(Base):
    __tablename__ = "oauth_token_families"

    family_id = Column(String(64), primary_key=True)
    client_key = Column(String(64), ForeignKey("oauth_clients.client_key", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resource = Column(Text, nullable=False)
    issuer = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    revoked_at = Column(BigInteger)


class OAuthTokenTable(Base):
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    access_hash = Column(String(64), nullable=False, unique=True)
    refresh_hash = Column(String(64), unique=True)
    family_id = Column(String(64), ForeignKey("oauth_token_families.family_id", ondelete="CASCADE"), nullable=False, index=True)
    client_key = Column(String(64), nullable=False)
    scope = Column(Text, nullable=False)
    issued_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    refresh_expires_at = Column(BigInteger, nullable=False)
    consumed_at = Column(BigInteger)
    revoked_at = Column(BigInteger)

    def get_scope(self):
        return self.scope

    def check_client(self, client):
        return self.client_key == client.client_key
