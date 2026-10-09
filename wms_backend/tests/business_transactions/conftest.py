"""Isolated shared-business tests: pytest --confcutdir=tests/business_transactions.

Use only generated SQLite data and a minimal app, without importing app.py.
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

from controllers.order_controller import order_bp
from controllers.packing_controller import packing_bp
from data.database import Base
from data.customer.Customer import CustomerTable
from data.user.User import UserTable


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    for module in (
        "data.database", "data.DB", "data.customer.Customer", "data.user.User",
        "data.order_version", "data.packing.PackingList", "services.order_service",
        "services.receivable_service", "utils.audit", "utils.log",
        "controllers.order_controller", "controllers.packing_controller",
    ):
        monkeypatch.setattr(f"{module}.SessionFactory", factory)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(order_bp)
    app.register_blueprint(packing_bp)
    with factory.begin() as session:
        session.add_all([
            CustomerTable(id=1, name="事务测试客户"),
            UserTable(id=1, name="操作员", phone="10000000001", password="unused", status="approved"),
            UserTable(id=2, name="业务员", phone="10000000002", password="unused", status="approved"),
        ])
    yield {"factory": factory, "client": app.test_client()}
    engine.dispose()
