"""Generated feature migration must match ORM and preserve unrelated tables."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from data.order_exception import OrderExceptionTable, OrderExceptionHistoryTable


def test_generated_migration_upgrade_and_downgrade():
    files = list((Path(__file__).resolve().parents[2] / 'alembic/versions').glob('*_add_order_exceptions.py'))
    assert len(files) == 1
    spec = importlib.util.spec_from_file_location('exception_migration_under_test', files[0])
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == '9bf6c7d8e9f0'
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE unrelated (uid INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('INSERT INTO unrelated VALUES (42)')
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        inspector = inspect(connection)
        for model in (OrderExceptionTable, OrderExceptionHistoryTable):
            assert {column['name'] for column in inspector.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
            assert {item['name'] for item in inspector.get_indexes(model.__tablename__)} == {item.name for item in model.__table__.indexes}
        constraints = inspector.get_unique_constraints('order_exception_history')
        assert {tuple(item['column_names']) for item in constraints} == {('event_key',)}
        assert inspector.get_foreign_keys('order_exception_history')[0]['options']['ondelete'] == 'CASCADE'
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert inspect(connection).get_table_names() == ['unrelated']
        assert connection.exec_driver_sql('SELECT uid FROM unrelated').scalar_one() == 42
    engine.dispose()
