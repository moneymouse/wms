"""Opt-in real database locking tests; MCP_CONCURRENCY_DATABASE_URL must name a test DB."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier
import uuid

from flask import Flask
import pytest
from sqlalchemy import create_engine, delete, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from Auth import hash_password
from controllers.oauth_controller import init_oauth
from data.oauth import OAuthAuthorizationCodeTable, OAuthClientTable, OAuthTokenFamilyTable, OAuthTokenTable
from data.user.User import UserTable
from services.oauth_service import validate_access_token
from test_oauth import authorize_code, client_registration, exchange, refresh


@pytest.fixture
def mysql_world(monkeypatch):
    dsn = os.environ.get("MCP_CONCURRENCY_DATABASE_URL")
    if not dsn:
        pytest.skip("MCP_CONCURRENCY_DATABASE_URL is not configured")
    url = make_url(dsn)
    if url.get_backend_name() not in {"mysql", "mariadb"} or "test" not in (url.database or "").lower():
        pytest.fail("OAuth concurrency requires a dedicated MySQL/MariaDB database whose name contains test")
    engine = create_engine(url, pool_pre_ping=True, isolation_level="REPEATABLE READ")
    required = {"users", "roles", "user_roles", "oauth_clients", "oauth_authorization_codes", "oauth_token_families", "oauth_tokens"}
    missing = required - set(inspect(engine).get_table_names())
    if missing:
        engine.dispose()
        pytest.fail(f"Apply migrations before OAuth concurrency tests: {sorted(missing)}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in ("services.oauth_service", "controllers.oauth_controller", "data.user.User"):
        monkeypatch.setattr(module + ".SessionFactory", factory)
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    app.config.update(TESTING=True, OAUTH_ISSUER_URL="https://wms.example.test",
        MCP_PUBLIC_URL="https://wms.example.test/mcp", OAUTH_SESSION_SECRET="oauth-concurrency-test-session-secret")
    init_oauth(app)
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://wms.example.test")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://wms.example.test/mcp")
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "oauth-concurrency-test-session-secret")
    phone = "oc" + uuid.uuid4().hex[:20]
    with factory() as session:
        user = UserTable(phone=phone, name="OAuth concurrency test", status="approved",
                         password=hash_password("Mcp-test-password"))
        session.add(user)
        session.commit()
        user_id = user.id
    world = {"app": app, "client": app.test_client(), "factory": factory,
             "base": "https://wms.example.test", "resource": "https://wms.example.test/mcp", "phone": phone}
    try:
        yield world
    finally:
        with factory() as session:
            families = list(session.scalars(select(OAuthTokenFamilyTable.family_id).where(OAuthTokenFamilyTable.user_id == user_id)))
            keys = list(session.scalars(select(OAuthAuthorizationCodeTable.client_key).where(OAuthAuthorizationCodeTable.user_id == user_id)))
            if families:
                session.execute(delete(OAuthTokenTable).where(OAuthTokenTable.family_id.in_(families)))
            session.execute(delete(OAuthAuthorizationCodeTable).where(OAuthAuthorizationCodeTable.user_id == user_id))
            session.execute(delete(OAuthTokenFamilyTable).where(OAuthTokenFamilyTable.user_id == user_id))
            if keys:
                session.execute(delete(OAuthClientTable).where(OAuthClientTable.client_key.in_(keys)))
            session.execute(delete(UserTable).where(UserTable.id == user_id))
            session.commit()
        engine.dispose()


def concurrent(world, actions):
    barrier = Barrier(len(actions))
    def invoke(action):
        local_world = {**world, "client": world["app"].test_client()}
        barrier.wait(timeout=10)
        response = action(local_world)
        return response.status_code, response.json
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_code_exchange_only_one_wins_and_replay_revokes_family(mysql_world):
    world = mysql_world
    client = client_registration(world)
    code = authorize_code(world, client)
    results = concurrent(world, [lambda w: exchange(w, client, code)] * 2)
    assert sorted(status for status, _ in results) == [200, 400]
    winner = next(body for status, body in results if status == 200)
    assert validate_access_token(winner["access_token"], world["resource"]) is None


def test_refresh_only_one_wins_and_family_is_revoked_on_replay(mysql_world):
    world = mysql_world
    client = client_registration(world)
    code = authorize_code(world, client)
    original = exchange(world, client, code).json
    results = concurrent(world, [lambda w: refresh(w, client, original)] * 2)
    assert sorted(status for status, _ in results) == [200, 400]
    winner = next(body for status, body in results if status == 200)
    assert validate_access_token(winner["access_token"], world["resource"]) is None


def test_parent_replay_serializes_with_descendant_rotation(mysql_world):
    world = mysql_world
    client = client_registration(world)
    code = authorize_code(world, client)
    parent = exchange(world, client, code).json
    child = refresh(world, client, parent).json
    results = concurrent(world, [lambda w: refresh(w, client, parent), lambda w: refresh(w, client, child)])
    assert results[0][0] == 400
    assert results[1][0] in (200, 400)
    assert validate_access_token(child["access_token"], world["resource"]) is None
    if results[1][0] == 200:
        assert validate_access_token(results[1][1]["access_token"], world["resource"]) is None
