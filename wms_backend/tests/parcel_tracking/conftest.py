"""Isolated cache tests: pytest --confcutdir=tests/parcel_tracking tests/parcel_tracking."""

import os
from pathlib import Path
import sys

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "isolated-parcel-tracking-test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from data.database import Base
from data.DB import CargoTable, OrderTable
from data.customer.Customer import CustomerTable  # noqa: F401
from data.finance.BonusItem import BonusItemTable  # noqa: F401
from data.packing.PackingList import PackingListTable  # noqa: F401
from data.user.Role import RoleTable  # noqa: F401
from data.user.User import UserTable  # noqa: F401
from services import parcel_tracking_service


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # Real BEGIN is required for rollback to include the first savepoint.
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(parcel_tracking_service, "SessionFactory", factory)
    with factory.begin() as session:
        session.add_all([
            OrderTable(uid="order-a", order_id="ORDER-A", archive=False),
            OrderTable(uid="order-b", order_id="ORDER-B", archive=False),
        ])
        session.flush()
        session.add_all([
            CargoTable(uid="cargo-a", target_order_uid="order-a", waybill_id="WAYBILL-A",
                       status=1, archive=False),
            CargoTable(uid="cargo-b", target_order_uid="order-b", waybill_id="WAYBILL-B",
                       status=0, archive=False),
        ])
    yield factory
    engine.dispose()
