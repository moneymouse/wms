"""Real InnoDB serialization of logistics history and exception side effects."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Barrier

from data.DB import CargoTable
from data.message import MessageTable
from data.order_exception import OrderExceptionHistoryTable, OrderExceptionTable
from data.parcel_tracking import ParcelTrackingUpdateTable
from services import tracking_webhook_service as webhook
from test_mysql_concurrency import mysql_engine, mysql_database  # noqa: F401

KEY = 'mysql-isolated-tracking-key'


def _body(status='Exception', time='2026-10-11T12:00:00Z'):
    return json.dumps({'event': 'TRACKING_UPDATED', 'data': {
        'tag': 'cargo-a', 'number': 'WAYBILL-A',
        'track_info': {'latest_status': {'status': status, 'sub_status': f'{status}_Other'},
                       'latest_event': {'time_utc': time, 'description': status}},
    }}).encode()


def _send(raw, barrier):
    barrier.wait(timeout=10)
    return webhook.receive_update(raw, hashlib.sha256(raw + b'/' + KEY.encode()).hexdigest(), key=KEY)


def _parallel(first, second):
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_send, raw, barrier) for raw in (first, second)]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_duplicate_push_commits_one_tracking_record_and_notice(mysql_database, monkeypatch):
    monkeypatch.setattr(webhook, 'SessionFactory', mysql_database)
    results = _parallel(_body(), _body())
    assert sum(result['recorded'] for result in results) == 1
    assert results[0]['exception_uids'] == results[1]['exception_uids']
    with mysql_database() as session:
        assert session.query(ParcelTrackingUpdateTable).count() == 1
        assert session.query(OrderExceptionTable).count() == 1
        assert session.query(OrderExceptionHistoryTable).count() == 1
        assert session.query(MessageTable).count() == 1
        assert session.get(CargoTable, 'cargo-a').status == 1


def test_concurrent_normal_updates_keep_newest_snapshot_and_both_history(mysql_database, monkeypatch):
    monkeypatch.setattr(webhook, 'SessionFactory', mysql_database)
    _parallel(_body('InTransit', '2026-10-11T12:00:00Z'), _body('Delivered', '2026-10-11T13:00:00Z'))
    with mysql_database() as session:
        assert session.query(ParcelTrackingUpdateTable).count() == 2
        current = session.query(ParcelTrackingUpdateTable).filter_by(is_current=True).one()
        assert json.loads(current.row_json)['track_info']['latest_status']['status'] == 'Delivered'
        assert session.query(OrderExceptionTable).count() == session.query(MessageTable).count() == 0
