"""Isolated exceptions: pytest --confcutdir=tests/order_exceptions tests/order_exceptions."""

import os
from pathlib import Path
import sys

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "isolated-order-exception-test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from controllers.order_exception_controller import order_exception_bp
from data.database import Base
from data.DB import CargoTable, OrderTable
from data.customer.Customer import CustomerTable  # noqa: F401
from data.finance.BonusItem import BonusItemTable  # noqa: F401
from data.packing.PackingList import PackingListTable  # noqa: F401
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import message_service, order_exception_service, parcel_tracking_service


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # sqlite3's legacy mode otherwise commits the first savepoint early.
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(order_exception_service, "SessionFactory", factory)
    monkeypatch.setattr(message_service, "SessionFactory", factory)
    monkeypatch.setattr(parcel_tracking_service, "SessionFactory", factory)
    with factory.begin() as session:
        roles = {
            name: RoleTable(name=name, label=name)
            for name in ("salesperson", "admin", "clerk", "worker")
        }
        session.add_all(roles.values())
        for user_id, role, status in (
            (1, "salesperson", "approved"), (2, "salesperson", "approved"),
            (3, "admin", "approved"), (4, "clerk", "approved"),
            (5, "worker", "approved"), (6, "salesperson", "rejected"),
            (7, None, "approved"),
        ):
            session.add(UserTable(
                id=user_id, phone=f"138000000{user_id:02d}", name=f"员工{user_id}",
                password="unused", status=status, roles=[roles[role]] if role else [],
            ))
        session.flush()
        session.add_all([
            OrderTable(uid="order-a", order_id="ORDER-A", salesman_id=1, archive=False),
            OrderTable(uid="order-b", order_id="ORDER-B", salesman_id=2, archive=False),
            OrderTable(uid="order-admin", order_id="ORDER-ADMIN", salesman_id=3, archive=False),
            OrderTable(uid="unassigned", order_id="NO-OWNER", archive=False),
            OrderTable(uid="invalid-owner", order_id="WORKER-OWNER", salesman_id=5, archive=False),
            OrderTable(uid="rejected-owner", order_id="REJECTED-OWNER", salesman_id=6, archive=False),
        ])
        session.flush()
        session.add_all([
            CargoTable(uid="cargo-a", origin_id="PARCEL-A", transfer_id="ORIGINAL-A", target_order_uid="order-a",
                       waybill_id="WAYBILL-A", archive=False, status=1),
            CargoTable(uid="cargo-b", origin_id="PARCEL-B", target_order_uid="order-b",
                       waybill_id="WAYBILL-B", archive=False, status=0),
            CargoTable(uid="archived-cargo", target_order_uid="order-a", archive=True, status=1),
        ])
    yield factory
    engine.dispose()


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(order_exception_bp)
    return app.test_client()
