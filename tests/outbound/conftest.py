"""Isolated outbound tests: run with --confcutdir=tests/outbound.

Never import app.py, use a business database, or call external tracking.
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

from data.database import Base
from data.DB import CargoTable, OrderTable, TransportationModeTable
from data.customer.Customer import CustomerTable
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


@pytest.fixture
def world(monkeypatch):
    from controllers.cargo_controller import cargo_bp
    from controllers.packing_controller import packing_bp
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    for module in ["data.DB", "data.packing.PackingList", "data.order_version",
                   "services.cargo_service", "utils.log", "utils.audit",
                   "controllers.cargo_controller", "data.user.User"]:
        monkeypatch.setattr(module + ".SessionFactory", factory)
    monkeypatch.setattr("controllers.cargo_controller.background_register", lambda *args: None)
    monkeypatch.setattr("services.cargo_service.background_register", lambda *args: None)
    monkeypatch.setattr("services.cargo_service.registerTrack", lambda *args: None)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(cargo_bp)
    app.register_blueprint(packing_bp)
    with factory() as session:
        customer = CustomerTable(id=1, name="客户")
        user = UserTable(id=1, name="管理员", phone="10000000001", password="unused", status="approved")
        order = OrderTable(uid="order", order_id="ORD", archive=False, transportation="渠道", cargo_count=2)
        order.customers = [customer]
        packing = PackingListTable(uid="packing", list_number="MARK", customer_id=1, creator_id=1, archive=False)
        session.add_all([customer, user, order, packing, TransportationModeTable(id=1, name="渠道", cost=3, archive=False)])
        session.add_all([
            CargoTable(uid="box", packing_list_uid="packing", target_order_uid="order", transfer_id="ORIG-BOX", waybill_id="", status=0, weight=2, archive=False, piece_count=1),
            CargoTable(uid="cargo", target_order_uid="order", transfer_id="ORIG-CARGO", waybill_id="", status=0, weight=4, archive=False),
        ])
        session.commit()
    yield {"factory": factory, "client": app.test_client(), "engine": engine}
    engine.dispose()


@pytest.fixture
def headers():
    from Auth import create_jwt
    return {"x-token": create_jwt({"user_id": 1, "name": "管理员", "role": "admin"}),
            "Content-Type": "application/json"}
