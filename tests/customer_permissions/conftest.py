"""Isolated permission tests: pytest --confcutdir=tests/customer_permissions.

Use a minimal app and generated SQLite data without unrelated app startup tasks.
"""

import os
import sys
from pathlib import Path

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from controllers.customer_controller import customer_bp
from controllers.order_controller import order_bp
from data.database import Base
from data.user.PasswordResetRequest import PasswordResetRequestTable  # noqa: F401


@pytest.fixture
def setup_test_database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (
        "data.database", "data.DB", "data.customer.Customer", "data.user.User",
        "data.order_version", "data.packing.PackingList", "services.order_service",
        "services.receivable_service", "utils.audit", "utils.log",
        "controllers.order_controller",
    ):
        monkeypatch.setattr(f"{module}.SessionFactory", factory)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(customer_bp)
    app.register_blueprint(order_bp)
    return app.test_client()
