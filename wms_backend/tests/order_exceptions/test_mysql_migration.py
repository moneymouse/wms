"""Opt-in feature migration smoke test on an empty dedicated MySQL database."""

import importlib.util
import os
from pathlib import Path
import re

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from data.order_exception import OrderExceptionTable, OrderExceptionHistoryTable


def test_mysql_upgrade_downgrade_preserves_unrelated_data():
    configured = os.environ.get('WMS_TEST_MYSQL_URL')
    if not configured:
        pytest.skip('WMS_TEST_MYSQL_URL is absent; isolated MySQL is opt-in')
    url = make_url(configured)
    if url.get_backend_name() != 'mysql' or not re.fullmatch(r'exception_test|wms_test_[a-z0-9_]+', url.database or ''):
        pytest.fail('A dedicated exception_test or wms_test_* database is required')
    engine = create_engine(url)
    files = list((Path(__file__).resolve().parents[2] / 'alembic/versions').glob('*_add_order_exceptions.py'))
    assert len(files) == 1
    spec = importlib.util.spec_from_file_location('mysql_exception_migration', files[0])
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with engine.connect() as connection:
            if inspect(connection).get_table_names():
                pytest.fail('Refusing to modify a nonempty database')
            try:
                connection.exec_driver_sql('CREATE TABLE exception_test_marker (uid INTEGER PRIMARY KEY)')
                connection.exec_driver_sql('INSERT INTO exception_test_marker VALUES (42)')
                connection.commit()
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
                inspector = inspect(connection)
                for model in (OrderExceptionTable, OrderExceptionHistoryTable):
                    assert {column['name'] for column in inspector.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
                assert inspector.get_unique_constraints('order_exception_history')[0]['column_names'] == ['event_key']
                with Operations.context(MigrationContext.configure(connection)):
                    migration.downgrade()
                assert inspect(connection).get_table_names() == ['exception_test_marker']
                assert connection.exec_driver_sql('SELECT uid FROM exception_test_marker').scalar_one() == 42
            finally:
                # These are solely tables created after the explicit empty-DB
                # guard; no existing application tables are removed.
                connection.exec_driver_sql('DROP TABLE IF EXISTS order_exception_history')
                connection.exec_driver_sql('DROP TABLE IF EXISTS order_exceptions')
                connection.exec_driver_sql('DROP TABLE IF EXISTS exception_test_marker')
                connection.commit()
    finally:
        engine.dispose()
