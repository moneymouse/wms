"""Creator migration preserves legacy rows and supports both database dialects."""

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, inspect, text


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_46b1c2d3e4f5_customer_creator.py"
    spec = importlib.util.spec_from_file_location("customer_creator_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_creator_migration_preserves_existing_customers_and_order_links():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table("users", metadata, Column("id", Integer, primary_key=True))
    Table("customers", metadata, Column("id", Integer, primary_key=True), Column("name", String(256), unique=True, nullable=False))
    Table("order_customers", metadata, Column("order_uid", String(128), primary_key=True), Column("customer_id", Integer, ForeignKey("customers.id"), primary_key=True))
    metadata.create_all(engine)
    migration = _migration()
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id) VALUES (3)"))
        connection.execute(text("INSERT INTO customers (id, name) VALUES (101, 'legacy')"))
        connection.execute(text("INSERT INTO order_customers (order_uid, customer_id) VALUES ('order', 101)"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert connection.execute(text("SELECT id, name, created_by_id FROM customers")).one() == (101, "legacy", None)
        assert connection.execute(text("SELECT order_uid, customer_id FROM order_customers")).one() == ("order", 101)
        inspector = inspect(connection)
        assert any(index["column_names"] == ["created_by_id"] for index in inspector.get_indexes("customers"))
        creator_fk = next(fk for fk in inspector.get_foreign_keys("customers") if fk["constrained_columns"] == ["created_by_id"])
        assert creator_fk["referred_table"] == "users"
        assert creator_fk["options"]["ondelete"] == "SET NULL"
        connection.execute(text("UPDATE customers SET created_by_id = 3"))
        with Operations.context(context):
            migration.downgrade()
        assert "created_by_id" not in {column["name"] for column in inspect(connection).get_columns("customers")}
        assert connection.execute(text("SELECT id, name FROM customers")).one() == (101, "legacy")
        assert connection.execute(text("SELECT customer_id FROM order_customers")).scalar_one() == 101
    engine.dispose()


def test_creator_migration_emits_mysql_foreign_key_and_index():
    output = StringIO()
    context = MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output})
    migration = _migration()
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "ADD COLUMN created_by_id INTEGER" in sql
    assert "REFERENCES users (id) ON DELETE SET NULL" in sql
    assert "CREATE INDEX ix_customers_created_by_id" in sql
    assert "DROP FOREIGN KEY fk_customers_created_by_id_users" in sql
    assert "DROP COLUMN created_by_id" in sql


def test_creator_migration_extends_the_existing_head():
    script = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic"))
    assert script.get_heads() == ["46b1c2d3e4f5"]
    assert script.get_revision("46b1c2d3e4f5").down_revision == "35a0b1c2d3e4"
