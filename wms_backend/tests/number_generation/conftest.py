"""Isolated number generation tests: use --confcutdir=tests/number_generation.

Only temporary SQLite databases and a minimal Flask app are used. Importing the
production app or calling shipment tracking is deliberately prohibited.
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
from data.DB import CargoTable, OrderTable
from data.customer.Customer import CustomerTable
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


@pytest.fixture
def world(monkeypatch, tmp_path):
    from controllers.cargo_controller import cargo_bp
    from controllers.order_controller import order_bp
    from controllers.packing_controller import packing_bp

    engine = create_engine(
        f"sqlite:///{tmp_path / 'number-generation.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    for module in (
        "data.database", "data.DB", "data.customer.Customer", "data.user.User",
        "data.order_version", "data.packing.PackingList", "services.order_service",
        "services.cargo_service", "services.number_generation_service",
        "utils.audit", "utils.log", "controllers.order_controller",
        "controllers.cargo_controller", "controllers.packing_controller",
    ):
        monkeypatch.setattr(f"{module}.SessionFactory", factory)

    def no_tracking(*args, **kwargs):
        raise AssertionError("Number generation must not call shipment tracking")

    for name in (
        "utils.l7track.getTrackInfo", "utils.l7track.registerTrack",
        "services.cargo_service.getTrackInfo", "services.cargo_service.registerTrack",
        "services.cargo_service.background_register",
        "controllers.cargo_controller.background_register",
    ):
        monkeypatch.setattr(name, no_tracking)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(order_bp)
    app.register_blueprint(cargo_bp)
    app.register_blueprint(packing_bp)

    with factory.begin() as session:
        customer = CustomerTable(id=1, name="号码测试客户")
        user = UserTable(
            id=1, name="操作员", phone="10000000001",
            password="unused", status="approved",
        )
        order = OrderTable(
            uid="order", order_id="8123456789", archive=False, salesman_id=1,
            transportation="测试渠道", cargo_count=3, total_weight=9,
            order_date="2026-10-01", receiver="测试收件人",
        )
        order.customers = [customer]
        packing = PackingListTable(
            uid="packing", list_number="MARK", customer_id=1,
            creator_id=1, archive=False,
        )
        session.add_all([
            customer, user, order, packing,
            OrderTable(uid="other-order", order_id="8999999999", archive=False),
        ])
        session.add_all([
            CargoTable(
                uid="box", packing_list_uid="packing", target_order_uid="order",
                transfer_id="8234567890", box_number=1, tag="MARK_1",
                waybill_id="WB-UNCHANGED", status=0, weight=2, archive=False,
                piece_count=1, remark="原备注",
            ),
            CargoTable(
                uid="second-box", packing_list_uid="packing", target_order_uid="order",
                transfer_id="8345678901", box_number=2, tag="MARK_2",
                waybill_id="", status=0, weight=3, archive=False, piece_count=1,
            ),
            CargoTable(
                uid="cargo", target_order_uid="order", transfer_id="8456789012",
                waybill_id="", status=0, weight=4, archive=False,
            ),
            CargoTable(
                uid="other-cargo", target_order_uid="other-order",
                transfer_id="8567890123", status=0, archive=False,
            ),
        ])

    yield {"factory": factory, "client": app.test_client(), "engine": engine}
    engine.dispose()
