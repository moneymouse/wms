#!/usr/bin/env python3
"""WMS Streamable HTTP MCP client, Python 3.10+ standard library only.

Passwords are entered in the browser. OAuth credentials stay in a private local
cache; neither credentials nor callback parameters are printed. Each request
uses the server's current schemas, roles, scopes and visibility rules.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.server
import ipaddress
import json
import os
import secrets
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_SERVER = "https://8.166.137.88:8081/mcp"
READ_SCOPES = "mcp orders:list orders:read"
ALL_SCOPES = "mcp orders:create orders:list orders:read packing_lists:create"
PROTOCOL_VERSION = "2025-11-25"
MAX_RESPONSE = 8 * 1024 * 1024


class ClientError(Exception):
    """An error safe to show to the user."""


class HTTPFailure(ClientError):
    def __init__(self, status, error=None, required_scope=None):
        self.status, self.error = status, error
        message = f"HTTP {status}"
        if error and isinstance(error, str) and all(c.isalnum() or c in "_-" for c in error):
            message += f" ({error})"
        if required_scope:
            message += f"; required scope: {required_scope}"
        super().__init__(message)


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def checked_url(url):
    if not isinstance(url, str):
        raise ClientError("Expected an HTTPS URL.")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ClientError("Invalid server URL.") from exc
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or (port is not None and not 1 <= port <= 65535)):
        raise ClientError("URL must have a host and contain no credentials, query or fragment.")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and _loopback(parsed.hostname)):
        raise ClientError("HTTPS is required; HTTP is allowed only for loopback development.")
    return url


def _origin(url):
    parsed = urllib.parse.urlsplit(checked_url(url))
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect())

    def request(self, url, *, method="GET", json_body=None, form=None, headers=None):
        checked_url(url)
        outgoing = dict(headers or {})
        body = None
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode()
            outgoing["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode()
            outgoing["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, body, outgoing, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ClientError("Server response exceeds the size limit.")
                return response.status, response.headers, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read(65536)
            try:
                payload = json.loads(raw)
                error = payload.get("error") if isinstance(payload, dict) else None
            except (ValueError, UnicodeError):
                error = None
            scope = None
            if exc.code == 403:
                import re
                match = re.search(r'\bscope="([a-zA-Z0-9:_ -]+)"', exc.headers.get("WWW-Authenticate", ""))
                scope = match.group(1) if match else None
            raise HTTPFailure(exc.code, error, scope) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ClientError("Network or TLS verification failed; check connectivity and the certificate.") from None

    def json(self, url, **kwargs):
        _, _, raw = self.request(url, **kwargs)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ClientError("Server did not return valid JSON.") from None
        if not isinstance(result, dict):
            raise ClientError("Server JSON must be an object.")
        return result


def discover(transport, resource):
    parsed = urllib.parse.urlsplit(checked_url(resource))
    path = "/.well-known/oauth-protected-resource" + parsed.path.rstrip("/")
    metadata_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    protected = transport.json(metadata_url)
    if protected.get("resource") != resource:
        raise ClientError("Protected resource metadata does not match the exact MCP URL.")
    issuers = protected.get("authorization_servers")
    if not isinstance(issuers, list) or len(issuers) != 1:
        raise ClientError("Expected one WMS authorization server.")
    issuer = checked_url(issuers[0])
    issuer_parts = urllib.parse.urlsplit(issuer)
    if issuer_parts.path not in ("", "/") or _origin(issuer) != _origin(resource):
        raise ClientError("WMS issuer must be an origin on the same host as the MCP resource.")
    metadata = transport.json(issuer.rstrip("/") + "/.well-known/oauth-authorization-server")
    if metadata.get("issuer") != issuer:
        raise ClientError("Authorization server metadata issuer mismatch.")
    for field in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        endpoint = checked_url(metadata.get(field))
        if _origin(endpoint) != _origin(issuer):
            raise ClientError("WMS OAuth endpoints must use the discovered issuer origin.")
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise ClientError("OAuth server does not support PKCE S256.")
    if metadata.get("authorization_response_iss_parameter_supported") is not True:
        raise ClientError("OAuth server must return the authorization response issuer.")
    return metadata


def default_cache_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "wms-mcp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "wms-mcp"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "wms-mcp"


class Store:
    def __init__(self, directory, resource):
        self.directory = Path(directory).expanduser().absolute()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check(self.directory, directory=True)
        if os.name != "nt":
            os.chmod(self.directory, 0o700)
        key = hashlib.sha256(resource.encode()).hexdigest()[:24]
        self.path = self.directory / f"session-{key}.json"
        self.lock_path = self.directory / f"session-{key}.lock"

    @staticmethod
    def _check(path, *, directory=False):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode)):
            raise ClientError("Credential cache path must not be a symbolic link or special file.")
        if os.name != "nt" and info.st_uid != os.getuid():
            raise ClientError("Credential cache must belong to the current user.")

    @contextlib.contextmanager
    def lock(self, timeout=30):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError:
            raise ClientError("Unable to open the private credential lock.") from None
        stream = os.fdopen(descriptor, "r+b")
        self._check(self.lock_path)
        if os.name != "nt":
            os.chmod(self.lock_path, 0o600)
        # msvcrt permits locking a byte beyond EOF. Do not initialize the byte
        # by writing it: another process may already hold that byte's lock.
        deadline = time.monotonic() + timeout
        acquired = False
        try:
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ClientError("Another login or token refresh is running; try again when it finishes.") from None
                    time.sleep(0.1)
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    def load(self):
        if not self.path.exists():
            return None
        self._check(self.path)
        if os.name != "nt" and stat.S_IMODE(self.path.stat().st_mode) & 0o077:
            raise ClientError("Credential cache permissions are too broad; run chmod 600 on the session file.")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ClientError("Credential cache is unreadable; log out and log in again.") from None
        if not isinstance(payload, dict):
            raise ClientError("Credential cache is invalid; log out and log in again.")
        return payload

    def save(self, payload):
        descriptor, name = tempfile.mkstemp(prefix=".session-", dir=self.directory)
        temporary = Path(name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete(self):
        if self.path.exists():
            self._check(self.path)
            self.path.unlink()


def validate_callback(query, state, issuer):
    values = urllib.parse.parse_qs(query, keep_blank_values=True)
    def single(key):
        entries = values.get(key, [])
        return entries[0] if len(entries) == 1 and isinstance(entries[0], str) else None
    incoming_state = single("state")
    if incoming_state is None or not secrets.compare_digest(incoming_state, state):
        raise ClientError("OAuth callback state mismatch.")
    if single("iss") != issuer:
        raise ClientError("OAuth callback issuer mismatch.")
    if single("error"):
        raise ClientError("Authorization was declined or rejected; no token was saved.")
    code = single("code")
    if not code:
        raise ClientError("OAuth callback is missing an authorization code.")
    return code


class CallbackServer(http.server.HTTPServer):
    def __init__(self, state):
        self.expected_state = state
        self.expected_issuer = None
        self.result = None
        self.failure = None
        super().__init__(("127.0.0.1", 0), CallbackHandler)
        self.timeout = 0.5

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while self.result is None and self.failure is None:
            if time.monotonic() >= deadline:
                raise ClientError("Browser authorization timed out; run login again.")
            self.handle_request()
        if self.failure:
            raise self.failure
        return self.result


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        try:
            self.server.result = validate_callback(parsed.query, self.server.expected_state, self.server.expected_issuer)
            status, body = 200, "Authorization complete. You may close this window and return to WorkBuddy."
        except ClientError as exc:
            # Invalid local probes do not consume a pending legitimate callback.
            if str(exc).startswith("Authorization was declined"):
                self.server.failure = exc
            status, body = 400, "Authorization callback rejected. Return to WorkBuddy for details."
        raw = ("<!doctype html><meta charset=utf-8><title>WMS OAuth</title><p>" + body + "</p>").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass  # Callback URL contains a one-time secret.


def checked_token(payload, resource, requested_scope, *, previous=None):
    if payload.get("resource") != resource:
        raise ClientError("Token response resource mismatch; discard this authorization and log in again.")
    if str(payload.get("token_type", "")).lower() != "bearer" or not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        raise ClientError("OAuth server returned an invalid access token.")
    lifetime = payload.get("expires_in")
    if isinstance(lifetime, bool) or not isinstance(lifetime, int) or lifetime <= 0:
        raise ClientError("OAuth server returned an invalid token lifetime.")
    if not isinstance(payload.get("refresh_token"), str) or not payload["refresh_token"]:
        raise ClientError("OAuth server did not return a rotating refresh token.")
    if previous and payload["refresh_token"] == previous:
        raise ClientError("OAuth server did not rotate the refresh token.")
    granted = payload.get("scope", requested_scope)
    if not isinstance(granted, str) or "mcp" not in granted.split() or not set(granted.split()).issubset(requested_scope.split()):
        raise ClientError("OAuth server returned unexpected scopes.")
    return {"access_token": payload["access_token"], "refresh_token": payload["refresh_token"],
            "expires_at": time.time() + lifetime, "scope": " ".join(granted.split())}


def login(args, store, transport):
    metadata = discover(transport, args.server)
    scopes = args.scope or (ALL_SCOPES if args.all_scopes else READ_SCOPES)
    if "mcp" not in scopes.split() or not set(scopes.split()).issubset(metadata.get("scopes_supported", [])):
        raise ClientError("Requested scopes must include mcp and be supported by the server.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    with store.lock(timeout=args.timeout), CallbackServer(state) as callback:
        callback.expected_issuer = metadata["issuer"]
        redirect = f"http://127.0.0.1:{callback.server_port}/callback"
        client = transport.json(metadata["registration_endpoint"], method="POST", json_body={
            "client_name": "WorkBuddy WMS Skill", "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "scope": scopes,
        })
        client_id = client.get("client_id")
        if not isinstance(client_id, str) or not client_id or client.get("token_endpoint_auth_method") != "none":
            raise ClientError("Public client registration failed.")
        if client.get("redirect_uris") != [redirect]:
            raise ClientError("Registered callback URI mismatch.")
        query = urllib.parse.urlencode({"response_type": "code", "client_id": client_id,
            "redirect_uri": redirect, "scope": scopes, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256", "resource": args.server})
        authorization_url = metadata["authorization_endpoint"] + "?" + query
        print("Open this link on this computer; log in with your own WMS account and choose permissions:", flush=True)
        print(authorization_url, flush=True)
        if not args.no_browser:
            webbrowser.open(authorization_url)
        code = callback.wait(args.timeout)
        payload = transport.json(metadata["token_endpoint"], method="POST", form={
            "grant_type": "authorization_code", "client_id": client_id, "code": code,
            "redirect_uri": redirect, "code_verifier": verifier, "resource": args.server,
        })
        credentials = checked_token(payload, args.server, scopes)
        credentials.update(resource=args.server, issuer=metadata["issuer"], client_id=client_id,
                           token_endpoint=metadata["token_endpoint"], revocation_endpoint=metadata["revocation_endpoint"])
        previous = store.load()
        store.save(credentials)
        # Replacing a login also retires the previous token family when possible.
        if previous and previous.get("client_id") and previous.get("refresh_token"):
            try:
                _revoke(transport, previous, args.server)
            except ClientError:
                print("The new login is saved; revocation of the previous login was not confirmed.", file=sys.stderr)
    print(json.dumps({"logged_in": True, "resource": args.server, "scope": credentials["scope"]}, ensure_ascii=False))


def _session(loaded, resource):
    if not loaded or loaded.get("resource") != resource:
        raise ClientError("No login for this MCP URL; run login first.")
    issuer = loaded.get("issuer")
    if _origin(issuer) != _origin(resource):
        raise ClientError("Cached issuer mismatch; log out and log in again.")
    for field in ("token_endpoint", "revocation_endpoint"):
        if _origin(loaded.get(field)) != _origin(issuer):
            raise ClientError("Cached OAuth endpoint mismatch; log out and log in again.")
    return loaded


def access_token(store, transport, resource):
    with store.lock():
        session = _session(store.load(), resource)
        if session.get("refresh_in_progress"):
            raise ClientError("A previous refresh has an uncertain result; run login again. The old refresh token will not be retried.")
        try:
            expires_at = float(session["expires_at"])
        except (KeyError, TypeError, ValueError):
            raise ClientError("Cached token lifetime is invalid; log in again.") from None
        if expires_at > time.time() + 30:
            return session["access_token"]
        # Persist before sending. A crash or lost response must not replay a
        # consumed refresh token and revoke the entire family on the server.
        session["refresh_in_progress"] = True
        store.save(session)
        payload = transport.json(session["token_endpoint"], method="POST", form={
            "grant_type": "refresh_token", "client_id": session["client_id"],
            "refresh_token": session["refresh_token"], "resource": resource,
        })
        updated = checked_token(payload, resource, session["scope"], previous=session["refresh_token"])
        session.update(updated)
        session.pop("refresh_in_progress", None)
        store.save(session)
        return session["access_token"]


def _revoke(transport, session, resource):
    _session(session, resource)
    transport.request(session["revocation_endpoint"], method="POST", form={
        "client_id": session["client_id"], "token": session.get("refresh_token") or session["access_token"],
        "token_type_hint": "refresh_token" if session.get("refresh_token") else "access_token",
    })


def logout(args, store, transport):
    failure = None
    with store.lock():
        session = store.load()
        if session:
            try:
                _revoke(transport, session, args.server)
            except ClientError as exc:
                failure = exc
            finally:
                store.delete()
    print(json.dumps({"logged_in": False, "server_revocation": "unconfirmed" if failure else "complete"}))
    if failure:
        raise ClientError("Local credentials were removed; server revocation was not confirmed. " + str(failure))


def _rpc_payload(raw, content_type, request_id):
    try:
        if "text/event-stream" in content_type:
            candidates, data = [], []
            for line in raw.decode("utf-8").splitlines() + [""]:
                if not line and data:
                    candidates.append(json.loads("\n".join(data)))
                    data = []
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
            envelopes = [item for item in candidates if isinstance(item, dict) and item.get("id") == request_id]
            if len(envelopes) != 1:
                raise ClientError("Expected one matching MCP response in the event stream.")
            envelope = envelopes[0]
        else:
            envelope = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ClientError("MCP response is not valid JSON or a valid event stream.") from None
    if not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0" or envelope.get("id") != request_id:
        raise ClientError("MCP response identifier mismatch.")
    if "error" in envelope:
        error = envelope["error"]
        code = error.get("code") if isinstance(error, dict) else None
        raise ClientError(f"MCP JSON-RPC error ({code}); inspect the current tool schema and arguments.")
    if not isinstance(envelope.get("result"), dict):
        raise ClientError("MCP response is missing its result.")
    return envelope["result"]


class MCPClient:
    def __init__(self, transport, resource, token):
        self.transport, self.resource = transport, resource
        self.headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer " + token,
                        "MCP-Protocol-Version": PROTOCOL_VERSION}
        self.sequence = 0
        result = self.rpc("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                        "clientInfo": {"name": "WorkBuddy WMS Skill", "version": "1.0.0"}})
        version = result.get("protocolVersion")
        if version not in ("2024-11-05", "2025-03-26", "2025-06-18", PROTOCOL_VERSION):
            raise ClientError("Server selected an unsupported MCP protocol version.")
        self.headers["MCP-Protocol-Version"] = version
        self.rpc("notifications/initialized", notification=True)

    def rpc(self, method, params=None, *, notification=False):
        envelope = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            self.sequence += 1
            envelope["id"] = self.sequence
        status, headers, raw = self.transport.request(self.resource, method="POST", json_body=envelope, headers=self.headers)
        session_id = headers.get("Mcp-Session-Id")
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id
        if notification:
            if status not in (200, 202, 204):
                raise ClientError("MCP initialization notification was not accepted.")
            return None
        return _rpc_payload(raw, headers.get("Content-Type", ""), self.sequence)


def _arguments(args):
    if args.arguments_file:
        try:
            raw = Path(args.arguments_file).read_text(encoding="utf-8")
        except OSError:
            raise ClientError("Unable to read the tool arguments file.") from None
    else:
        raw = args.arguments or "{}"
    try:
        result = json.loads(raw)
    except ValueError:
        raise ClientError("Tool arguments must be valid JSON.") from None
    if not isinstance(result, dict):
        raise ClientError("Tool arguments must be a JSON object.")
    return result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Exact MCP resource URL (default: WMS preproduction)")
    parser.add_argument("--cache-dir", default=str(default_cache_dir()), help="Private local credential directory")
    parser.add_argument("--http-timeout", type=float, default=30, help="Per-request timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("login", help="Open browser OAuth authorization with PKCE S256")
    auth.add_argument("--no-browser", action="store_true", help="Print the link without launching a browser")
    auth.add_argument("--timeout", type=float, default=900, help="Browser authorization timeout in seconds")
    selection = auth.add_mutually_exclusive_group()
    selection.add_argument("--all-scopes", action="store_true", help="Request read and create permissions; user may narrow consent")
    selection.add_argument("--scope", help="Space-separated scopes, including mcp")
    status = commands.add_parser("status", help="Show local session status without printing credentials")
    status.add_argument("--online", action="store_true", help="Verify the current login through MCP tools/list")
    commands.add_parser("logout", help="Revoke this login and delete local credentials")
    commands.add_parser("tools-list", aliases=["tools/list"], help="Return live MCP tool descriptions and schemas")
    call = commands.add_parser("call", aliases=["tools/call"], help="Invoke a tool using its current input schema")
    call.add_argument("name", help="Tool name from tools-list")
    inputs = call.add_mutually_exclusive_group()
    inputs.add_argument("--arguments", help="JSON object; prefer a file for business data")
    inputs.add_argument("--arguments-file", help="UTF-8 JSON object file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        checked_url(args.server)
        if urllib.parse.urlsplit(args.server).path != "/mcp":
            raise ClientError("WMS MCP resource path must be exactly /mcp.")
        if args.http_timeout <= 0 or getattr(args, "timeout", 1) <= 0:
            raise ClientError("Timeouts must be positive.")
        store = Store(args.cache_dir, args.server)
        transport = Transport(args.http_timeout)
        if args.command == "login":
            login(args, store, transport)
        elif args.command == "logout":
            logout(args, store, transport)
        elif args.command == "status" and not args.online:
            with store.lock():
                session = store.load()
                payload = {"logged_in": bool(session), "resource": args.server, "verification": "local_cache_only"}
                if session:
                    _session(session, args.server)
                    payload.update(scope=session.get("scope", ""), expires_at=session.get("expires_at"),
                                   refresh_uncertain=bool(session.get("refresh_in_progress")))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            arguments = _arguments(args) if args.command in ("call", "tools/call") else None
            token = access_token(store, transport, args.server)
            client = MCPClient(transport, args.server, token)
            if args.command in ("call", "tools/call"):
                result = client.rpc("tools/call", {"name": args.name, "arguments": arguments})
            else:
                result = client.rpc("tools/list")
                if args.command == "status":
                    result = {"connected": True, "resource": args.server, "tools": [t.get("name") for t in result.get("tools", [])]}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("isError"):
                return 2
        return 0
    except (ClientError, OSError) as exc:
        print("WMS MCP: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("WMS MCP: Cancelled; no credentials were printed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
