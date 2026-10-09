"""Isolated, real database fixtures shared by MCP and OAuth/MCP end-to-end tests."""
import importlib
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from Auth import hash_password
from data.database import Base
from data.customer.Customer import CustomerTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from mcp.server.auth.provider import AccessToken, TokenVerifier

from mcp_server import create_mcp_app


ALL_SCOPES = ["mcp", "orders:create", "orders:list", "orders:read", "tracking:read", "packing_lists:create"]


@pytest.fixture
def mcp_db(tmp_path, monkeypatch):
    # File SQLite gives the ASGI thread pool its own connections to the same data.
    engine = create_engine(f"sqlite:///{tmp_path / 'mcp-test.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    import data.mcp  # noqa: F401
    import data.oauth  # noqa: F401

    Base.metadata.create_all(engine)
    modules = ["data.database", "data.DB", "data.order_version",
               "data.customer.Customer", "data.user.User", "data.user.Role",
               "data.packing.PackingList", "services.order_service",
               "services.receivable_service", "services.packing_list_service",
               "services.mcp_service", "services.tracking_service", "utils.audit", "services.oauth_service"]
    for name in modules:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        if hasattr(module, "SessionFactory"):
            monkeypatch.setattr(module, "SessionFactory", factory)
    with factory() as session:
        role = RoleTable(name="admin", label="管理员")
        user = UserTable(phone="13800138000", name="MCP管理员", status="approved",
                         password=hash_password("Mcp-test-password"), roles=[role])
        customer = CustomerTable(name="MCP测试客户")
        session.add_all([user, customer])
        session.commit()
        operator = {"user_id": user.id, "name": user.name, "phone": user.phone,
                    "role": "admin", "roles": ["admin"]}
        principal = {"user_id": user.id, "client_id": "https://client.example/oauth/client.json",
                     "scopes": ALL_SCOPES.copy(), "expires_at": int(time.time()) + 900,
                     "resource": "https://wms.example/mcp", "issuer": "https://wms.example",
                     "operator_payload": operator}
        scope = {"factory": factory, "engine": engine, "user_id": user.id,
                 "customer_id": customer.id, "principal": principal}
    monkeypatch.setenv("OAUTH_ISSUER_URL", scope["principal"]["issuer"])
    monkeypatch.setenv("MCP_PUBLIC_URL", scope["principal"]["resource"])
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "mcp-test-session-secret-at-least-32-chars")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "wms.example")
    yield scope
    engine.dispose()


class StaticVerifier(TokenVerifier):
    def __init__(self, principal):
        self.principal = principal

    async def verify_token(self, token):
        if token != "test-token":
            return None
        p = self.principal
        return AccessToken(token=token, client_id=p["client_id"], scopes=p["scopes"],
                           expires_at=p["expires_at"], subject=str(p["user_id"]),
                           resource=p["resource"], claims={"iss": p["issuer"], "wms_principal": p})


@pytest.fixture
def mcp_app(mcp_db):
    return create_mcp_app(resource_url=mcp_db["principal"]["resource"],
                          issuer_url=mcp_db["principal"]["issuer"],
                          verifier=StaticVerifier(mcp_db["principal"]))


def rpc(client, method, params=None, *, token="test-token", version="2026-07-28", extra_headers=None):
    params = dict(params or {})
    if version == "2026-07-28":
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": version,
                           "io.modelcontextprotocol/clientCapabilities": {},
                           "io.modelcontextprotocol/clientInfo": {"name": "WMS test", "version": "1"}}
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": version}
    if version == "2026-07-28":
        headers["Mcp-Method"] = method
        if method == "tools/call" and isinstance(params.get("name"), str):
            headers["Mcp-Name"] = params["name"]
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra_headers or {})
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, headers=headers)
