"""Tracking storage survives real MySQL-sized histories and safe downgrade."""
import importlib.util
import os
from pathlib import Path
import re

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from data.parcel_tracking import ParcelTrackingUpdateTable


@pytest.mark.parametrize('dialect', ['sqlite', 'mysql'])
def test_tracking_migration_preserves_other_data_and_large_payload(dialect):
    if dialect == 'mysql':
        configured = os.environ.get('WMS_TEST_MYSQL_URL')
        if not configured:
            pytest.skip('WMS_TEST_MYSQL_URL absent; isolated MySQL is opt-in')
        url = make_url(configured)
        if url.get_backend_name() != 'mysql' or not re.fullmatch(r'exception_test|wms_test_[a-z0-9_]+', url.database or ''):
            pytest.fail('A dedicated exception_test or wms_test_* database is required')
        engine = create_engine(configured)
    else:
        engine = create_engine('sqlite:///:memory:')
    files = list((Path(__file__).resolve().parents[2] / 'alembic' / 'versions').glob('*_persist_parcel_tracking_webhook_updates.py'))
    assert len(files) == 1
    spec = importlib.util.spec_from_file_location('tracking_migration', files[0])
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        if inspect(connection).get_table_names():
            engine.dispose()
            pytest.fail('Refusing to modify a nonempty database')
        connection.execute(text('CREATE TABLE tracking_test_marker (value VARCHAR(64))'))
        connection.execute(text("INSERT INTO tracking_test_marker VALUES ('preserved')"))
        connection.commit()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            # Ordinary TEXT on MySQL would reject this complete tracking body.
            body = '{"description":"' + 'x' * 100000 + '"}'
            connection.execute(ParcelTrackingUpdateTable.__table__.insert().values(
                uid='tracking-row', cargo_uid='cargo-a', order_uid='order-a', waybill_id='WAYBILL-A',
                event_key='tracking-migration', row_json=body, received_at='2026-10-11T12:00:00.000000Z',
                is_current=True,
            ))
            connection.commit()
            assert connection.execute(text('SELECT row_json FROM parcel_tracking_updates')).scalar_one() == body
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            connection.commit()
            assert 'parcel_tracking_updates' not in inspect(connection).get_table_names()
            assert connection.execute(text('SELECT value FROM tracking_test_marker')).scalar_one() == 'preserved'
        finally:
            ParcelTrackingUpdateTable.__table__.drop(connection, checkfirst=True)
            connection.execute(text('DROP TABLE tracking_test_marker'))
            connection.commit()
    engine.dispose()
