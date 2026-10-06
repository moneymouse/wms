"""Isolated OAuth tests: run with --confcutdir=tests/oauth; never import app.py."""

import os
from pathlib import Path
import sys

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from Auth import hash_password
from controllers.oauth_controller import init_oauth
from data.database import Base
from data.user.Role import RoleTable
from data.user.User import UserTable


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in ("services.oauth_service", "controllers.oauth_controller", "data.user.User"):
        monkeypatch.setattr(module + ".SessionFactory", factory)
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://wms.example.test")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://wms.example.test/mcp")
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "oauth-test-session-secret-with-32-characters")
    monkeypatch.delenv("OAUTH_ALLOW_LOCAL_HTTP", raising=False)
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    app.config["TESTING"] = True
    init_oauth(app)
    with factory() as session:
        role = RoleTable(name="admin", label="管理员")
        user = UserTable(id=1, phone="13800138000", name="OAuth 用户", status="approved",
                         password=hash_password("Mcp-test-password"))
        user.roles = [role]
        session.add(user)
        session.commit()
    yield {"app": app, "client": app.test_client(), "factory": factory,
           "base": "https://wms.example.test", "resource": "https://wms.example.test/mcp"}
    engine.dispose()
