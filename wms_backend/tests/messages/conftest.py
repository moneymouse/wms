"""Isolated inbox tests: pytest --confcutdir=tests/messages tests/messages."""

import os
from pathlib import Path
import sys

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from controllers.message_controller import message_bp
from data.database import Base
from data.user.User import UserTable
from services import message_service


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # Match real transactional savepoints; sqlite3 legacy mode otherwise
        # releases a first savepoint as an implicit commit.
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(message_service, "SessionFactory", factory)
    with factory() as session:
        session.add_all([
            UserTable(id=user_id, phone=f"138000000{user_id:02d}", name=f"员工{user_id}",
                      password="test", status="approved" if user_id < 3 else "rejected")
            for user_id in (1, 2, 3)
        ])
        session.commit()
    yield factory
    engine.dispose()


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(message_bp)
    return app.test_client()
