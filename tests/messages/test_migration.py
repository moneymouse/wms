"""Exercise only this migration against a disposable database."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from data.message import MessageTable


def test_migration_matches_model_and_downgrade_preserves_users():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261007_9bf6c7d8e9f0_inbox_messages.py"
    spec = importlib.util.spec_from_file_location("inbox_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        inspector = inspect(connection)
        assert {column["name"] for column in inspector.get_columns("inbox_messages")} == set(MessageTable.__table__.columns.keys())
        assert {item["name"] for item in inspector.get_indexes("inbox_messages")} == {
            "ix_inbox_recipient_created", "ix_inbox_recipient_read",
        }
        assert inspector.get_unique_constraints("inbox_messages")[0]["column_names"] == ["recipient_id", "event_key"]
        assert inspector.get_foreign_keys("inbox_messages")[0]["referred_table"] == "users"
        assert inspector.get_foreign_keys("inbox_messages")[0]["options"]["ondelete"] == "CASCADE"
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert inspect(connection).get_table_names() == ["users"]
    engine.dispose()
