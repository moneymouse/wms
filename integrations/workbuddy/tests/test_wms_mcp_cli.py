"""Exercise the distributed standard-library client against a local OAuth/MCP peer.

The peer is an isolated fixture; no WMS account, public endpoint or business data
is used. Run with ``python -m unittest discover -s integrations/workbuddy/tests``.
"""
import base64
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "wms-mcp" / "scripts" / "wms_mcp.py"
SPEC = importlib.util.spec_from_file_location("wms_mcp_client", SCRIPT)
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


class Peer(http.server.ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), PeerHandler)
        self.issuer = f"http://127.0.0.1:{self.server_port}"
        self.resource = self.issuer + "/mcp"
        self.registration = None
        self.authorization = None
        self.tokens = {"access_token": "access-private", "refresh_token": "refresh-private",
                       "token_type": "Bearer", "expires_in": 900, "scope": client.READ_SCOPES,
                       "resource": self.resource}
        self.refresh_count = 0
        self.revocation_count = 0
        self.calls = []
        self.refresh_fail = False
        self.token_resource_override = None
        self.denied = False
        self.sse = False
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def finish(self):
        self.shutdown()
        self.server_close()
        self.thread.join()


class PeerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, payload, status=200, *, headers=None, content_type="application/json"):
        raw = json.dumps(payload).encode() if content_type == "application/json" else payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        issuer = self.server.issuer
        if parsed.path == "/.well-known/oauth-protected-resource/mcp":
            return self.respond({"resource": self.server.resource, "authorization_servers": [issuer]})
        if parsed.path == "/.well-known/oauth-authorization-server":
            return self.respond({"issuer": issuer, "authorization_endpoint": issuer + "/oauth/authorize",
                "token_endpoint": issuer + "/oauth/token", "registration_endpoint": issuer + "/oauth/register",
                "revocation_endpoint": issuer + "/oauth/revoke", "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True, "scopes_supported": client.ALL_SCOPES.split()})
        if parsed.path == "/oauth/authorize":
            values = {key: vals[0] for key, vals in urllib.parse.parse_qs(parsed.query).items()}
            self.server.authorization = values
            assert values["resource"] == self.server.resource
            assert values["code_challenge_method"] == "S256"
            assert values["redirect_uri"] == self.server.registration["redirect_uris"][0]
            callback = {"state": values["state"], "iss": issuer}
            callback.update(error="access_denied" if self.server.denied else None)
            if not self.server.denied:
                callback.pop("error")
                callback["code"] = "one-time-private-code"
            url = values["redirect_uri"] + "?" + urllib.parse.urlencode(callback)
            # The browser is the only actor following a redirect to loopback.
            try:
                urllib.request.urlopen(url, timeout=3).read()
            except urllib.error.HTTPError:
                pass
            return self.respond({"browser": "returned"})
        return self.respond({}, 404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.headers.get("Content-Type") == "application/json":
            data = json.loads(raw)
        else:
            data = {key: vals[0] for key, vals in urllib.parse.parse_qs(raw.decode()).items()}
        if self.path == "/oauth/register":
            assert data["token_endpoint_auth_method"] == "none"
            assert data["grant_types"] == ["authorization_code", "refresh_token"]
            self.server.registration = data
            return self.respond({**data, "client_id": "public-client"}, 201)
        if self.path == "/oauth/token":
            assert data["resource"] == self.server.resource
            assert data["client_id"] == "public-client"
            if data["grant_type"] == "authorization_code":
                assert data["code"] == "one-time-private-code"
                assert data["redirect_uri"] == self.server.authorization["redirect_uri"]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                assert challenge == self.server.authorization["code_challenge"]
            else:
                self.server.refresh_count += 1
                time.sleep(0.1)
                if self.server.refresh_fail:
                    return self.respond({"error": "invalid_grant", "error_description": "NEVER SHOW refresh-private"}, 400)
                assert data["refresh_token"] == "refresh-private"
                self.server.tokens.update(access_token="access-rotated", refresh_token="refresh-rotated")
            tokens = dict(self.server.tokens)
            if self.server.token_resource_override:
                tokens["resource"] = self.server.token_resource_override
            return self.respond(tokens)
        if self.path == "/oauth/revoke":
            assert data["client_id"] == "public-client"
            assert data["token"] in ("refresh-private", "refresh-rotated")
            self.server.revocation_count += 1
            return self.respond({})
        if self.path == "/mcp":
            assert self.headers["Authorization"] == "Bearer " + self.server.tokens["access_token"]
            method = data["method"]
            if method == "initialize":
                assert data["params"]["protocolVersion"] == client.PROTOCOL_VERSION
                result = {"protocolVersion": client.PROTOCOL_VERSION, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "Fixture WMS", "version": "1"}}
                extra = {"Mcp-Session-Id": "fixture-session"}
            else:
                assert self.headers["Mcp-Session-Id"] == "fixture-session"
                extra = {}
                if method == "notifications/initialized":
                    return self.respond({}, 202)
                if method == "tools/list":
                    result = {"tools": [{"name": "list_orders", "inputSchema": {"type": "object"}}]}
                elif method == "tools/call":
                    self.server.calls.append(data["params"])
                    result = {"structuredContent": {"code": 200, "data": []}, "isError": False,
                              "content": [{"type": "text", "text": "ok"}]}
                else:
                    return self.respond({}, 400)
            response = {"jsonrpc": "2.0", "id": data["id"], "result": result}
            if self.server.sse:
                return self.respond("event: message\ndata: " + json.dumps(response) + "\n\n", headers=extra,
                                    content_type="text/event-stream")
            return self.respond(response, headers=extra)
        return self.respond({}, 404)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.peer = Peer()
        self.directory = Path(self.temp.name) / "credentials"
        self.store = client.Store(self.directory, self.peer.resource)
        self.transport = client.Transport(3)

    def tearDown(self):
        self.peer.finish()
        self.temp.cleanup()

    def args(self, command):
        return ["--server", self.peer.resource, "--cache-dir", str(self.directory), *command]

    def run_cli(self, command):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = client.main(self.args(command))
        return code, output.getvalue(), errors.getvalue()

    def browser(self, url):
        # Background fixture browser lets the real callback HTTP server wait.
        def visit():
            urllib.request.urlopen(url, timeout=5).read()
        threading.Thread(target=visit, daemon=True).start()
        return True

    def login(self, extras=None):
        with patch.object(client.webbrowser, "open", self.browser):
            result = self.run_cli(["login", "--timeout", "4", *(extras or [])])
        self.assertEqual(result[0], 0, result[2])
        return result

    def test_full_login_discovery_pkce_rpc_and_logout(self):
        result = self.login()
        for secret in ("access-private", "refresh-private", "one-time-private-code", "code_verifier"):
            self.assertNotIn(secret, result[1] + result[2])
        session = self.store.load()
        self.assertEqual(session["resource"], self.peer.resource)
        self.assertEqual(session["scope"], client.READ_SCOPES)
        code, text, errors = self.run_cli(["tools-list"])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(text)["tools"][0]["name"], "list_orders")
        code, text, errors = self.run_cli(["call", "list_orders", "--arguments", '{"p":1,"s":2}'])
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.peer.calls, [{"name": "list_orders", "arguments": {"p": 1, "s": 2}}])
        code, text, errors = self.run_cli(["status", "--online"])
        self.assertEqual(code, 0, errors)
        self.assertTrue(json.loads(text)["connected"])
        code, text, errors = self.run_cli(["logout"])
        self.assertEqual(code, 0, errors)
        self.assertFalse(json.loads(text)["logged_in"])
        self.assertIsNone(self.store.load())
        self.assertEqual(self.peer.revocation_count, 1)

    def test_callback_state_issuer_and_duplicates_are_rejected(self):
        base = {"state": "expected", "iss": self.peer.issuer, "code": "private"}
        for change in ({"state": "wrong"}, {"iss": "https://attacker.example"}, {"code": ""}):
            with self.assertRaises(client.ClientError):
                client.validate_callback(urllib.parse.urlencode({**base, **change}), "expected", self.peer.issuer)
        with self.assertRaises(client.ClientError):
            client.validate_callback(urllib.parse.urlencode(base) + "&state=expected", "expected", self.peer.issuer)

    def test_denied_consent_saves_no_tokens(self):
        self.peer.denied = True
        with patch.object(client.webbrowser, "open", self.browser):
            code, text, errors = self.run_cli(["login", "--timeout", "4"])
        self.assertEqual(code, 1)
        self.assertIn("declined", errors)
        self.assertIsNone(self.store.load())

    def test_token_resource_mismatch_saves_no_tokens(self):
        self.peer.token_resource_override = "https://different.example/mcp"
        with patch.object(client.webbrowser, "open", self.browser):
            code, text, errors = self.run_cli(["login", "--timeout", "4"])
        self.assertEqual(code, 1)
        self.assertIn("resource mismatch", errors)
        self.assertIsNone(self.store.load())

    def test_consent_can_narrow_all_requested_scopes(self):
        self.login(["--all-scopes"])
        self.assertEqual(self.peer.registration["scope"], client.ALL_SCOPES)
        self.assertEqual(self.store.load()["scope"], client.READ_SCOPES)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_private_storage_and_broad_permissions_rejected(self):
        self.login()
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.lock_path.stat().st_mode), 0o600)
        os.chmod(self.store.path, 0o644)
        with self.assertRaises(client.ClientError):
            self.store.load()

    @unittest.skipIf(os.name == "nt", "Symlink privileges vary on Windows")
    def test_symlink_storage_rejected(self):
        destination = Path(self.temp.name) / "actual"
        destination.mkdir()
        symbolic = Path(self.temp.name) / "link"
        symbolic.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(client.ClientError):
            client.Store(symbolic, self.peer.resource)

    def test_refresh_rotation_and_ambiguous_failure_not_replayed(self):
        self.login()
        session = self.store.load()
        session["expires_at"] = time.time() - 1
        self.store.save(session)
        token = client.access_token(self.store, self.transport, self.peer.resource)
        self.assertEqual(token, "access-rotated")
        self.assertEqual(self.store.load()["refresh_token"], "refresh-rotated")
        self.assertEqual(self.peer.refresh_count, 1)
        session = self.store.load()
        session["expires_at"] = time.time() - 1
        self.store.save(session)
        self.peer.refresh_fail = True
        with self.assertRaises(client.HTTPFailure):
            client.access_token(self.store, self.transport, self.peer.resource)
        self.assertTrue(self.store.load()["refresh_in_progress"])
        with self.assertRaises(client.ClientError):
            client.access_token(self.store, self.transport, self.peer.resource)
        self.assertEqual(self.peer.refresh_count, 2)
        code, text, errors = self.run_cli(["tools-list"])
        self.assertEqual(code, 1)
        self.assertNotIn("refresh-private", errors)

    def test_cross_process_concurrent_refresh_only_once(self):
        self.login()
        session = self.store.load()
        session["expires_at"] = time.time() - 1
        self.store.save(session)
        command = [sys.executable, str(SCRIPT), *self.args(["tools-list"])]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["tools"][0]["name"], "list_orders")
        self.assertEqual(self.peer.refresh_count, 1)
        self.assertEqual(self.store.load()["refresh_token"], "refresh-rotated")

    def test_sse_response_and_identifier_validation(self):
        self.login()
        self.peer.sse = True
        code, text, errors = self.run_cli(["tools-list"])
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(text)["tools"][0]["name"], "list_orders")
        with self.assertRaises(client.ClientError):
            client._rpc_payload(b'{"jsonrpc":"2.0","id":2,"result":{}}', "application/json", 1)

    def test_https_enforced_and_no_access_before_login(self):
        with self.assertRaises(client.ClientError):
            client.checked_url("http://8.166.137.88:8081/mcp")
        with self.assertRaises(client.ClientError):
            client.checked_url("https://user:secret@example.com/mcp")
        code, text, errors = self.run_cli(["tools-list"])
        self.assertEqual(code, 1)
        self.assertIn("run login", errors)
        self.assertEqual(self.peer.calls, [])

    def test_nonobject_arguments_fail_before_contacting_mcp(self):
        code, text, errors = self.run_cli(["call", "create_order", "--arguments", '[]'])
        self.assertEqual(code, 1)
        self.assertIn("JSON object", errors)
        self.assertEqual(self.peer.calls, [])


if __name__ == "__main__":
    unittest.main()
