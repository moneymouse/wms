"""Run with --confcutdir=tests/shipping_confirmation against isolated SQLite."""

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

from controllers.packing_controller import packing_bp
from data.database import Base
from data.DB import CargoTable, OrderTable, TransportationModeTable
from data.customer.Customer import CustomerTable
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


@pytest.fixture
def world(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drafts.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("services.shipping_confirmation_draft_service.SessionFactory", factory)
    monkeypatch.setattr("utils.audit.SessionFactory", factory)
    with factory.begin() as session:
        session.add_all([
            UserTable(id=1, phone="1", name="业务员", password="unused"),
            UserTable(id=2, phone="2", name="其他业务员", password="unused"),
            CustomerTable(id=1, name="测试客户"),
            PackingListTable(uid="packing-a", list_number="MARK-A", creator_id=1, customer_id=1, archive=False),
            PackingListTable(uid="packing-b", list_number="MARK-B", creator_id=1, customer_id=1, archive=False),
            TransportationModeTable(name="渠道", channel_group="极飞"),
            OrderTable(uid="order", order_id="ORDER", customer_name="测试客户", transportation="渠道", archive=False),
            CargoTable(uid="box-a", packing_list_uid="packing-a", box_number=1, tag="MARK-A-1", transfer_id="OLD-A", archive=False, status=0),
            CargoTable(uid="box-b", packing_list_uid="packing-b", box_number=2, tag="MARK-B-2", transfer_id="OLD-B", archive=False, status=0, target_order_uid="order"),
            CargoTable(uid="box-c", packing_list_uid="packing-a", box_number=3, tag="MARK-A-3", archive=False, status=0),
            CargoTable(uid="archived", packing_list_uid="packing-a", archive=True),
        ])
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(packing_bp)
    yield {"factory": factory, "client": app.test_client(), "engine": engine}
    engine.dispose()
