"""Provider HTTP/signature/retry tests against isolated transactional storage."""

import hashlib
import json

import pytest
from flask import Flask

from Auth import create_jwt
from controllers.tracking_webhook_controller import tracking_webhook_bp
from data.DB import CargoTable, OrderTable
from data.message import MessageTable
from data.order_exception import OrderExceptionTable, OrderExceptionHistoryTable
from services import order_exception_service as exceptions
from services import tracking_webhook_service as webhook


KEY = 'isolated-test-provider-key'


def payload(status='Exception', sub_status='Exception_Delayed', **changes):
    data = {
        'number': 'WAYBILL-A', 'tag': 'cargo-a', 'carrier': 3011,
        'track_info': {'latest_status': {
            'status': status, 'sub_status': sub_status, 'sub_status_descr': '派送延误',
        }, 'latest_event': {'time_utc': '2026-10-11T12:00:00Z', 'description': 'Delay'}},
    }
    data.update(changes)
    return {'event': 'TRACKING_UPDATED', 'data': data}


def signed_body(body, key=KEY):
    return hashlib.sha256(body + b'/' + key.encode()).hexdigest()


def post(client, value=None, raw=None, sign=None):
    raw = json.dumps(value or payload(), ensure_ascii=False).encode() if raw is None else raw
    return client.post('/api/webhooks/17track', data=raw,
                       headers={'sign': signed_body(raw) if sign is None else sign},
                       content_type='application/json')


@pytest.fixture
def hook(database, monkeypatch):
    monkeypatch.setattr(webhook, 'SessionFactory', database)
    monkeypatch.setattr(webhook, 'configured_key', lambda: KEY)
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(tracking_webhook_bp)
    return app.test_client()


def counts(database):
    with database() as session:
        return tuple(session.query(model).count() for model in
                     (OrderExceptionTable, OrderExceptionHistoryTable, MessageTable))


def test_valid_exception_and_semantic_replay_notify_once(hook, database):
    first = post(hook)
    assert first.status_code == 200
    uid = first.json['data']['exception_uids'][0]
    # Signature verifies the *original* body, while event dedup handles changed
    # JSON whitespace/ordering on an equivalent signed replay.
    raw = json.dumps(payload(), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    replay = post(hook, raw=raw)
    assert replay.status_code == 200
    assert replay.json['data']['exception_uids'] == [uid]
    assert counts(database) == (1, 1, 1)
    with database() as session:
        case = session.get(OrderExceptionTable, uid)
        message = session.query(MessageTable).one()
        history = session.query(OrderExceptionHistoryTable).one()
        assert case.cargo_uid == 'cargo-a' and case.source == '17track'
        assert message.recipient_id == 1 and message.business_id == uid
        assert message.action_path == f'/order-exceptions?exception_uid={uid}'
        assert history.tracking_status == 'Exception_Delayed' and history.actor_id is None
        assert session.get(CargoTable, 'cargo-a').status == 1


@pytest.mark.parametrize('sign', ['', 'abc', '0' * 64, '💡' * 64])
def test_invalid_signature_never_writes(hook, database, sign):
    assert post(hook, sign=sign).status_code == 401
    assert counts(database) == (0, 0, 0)


def test_modified_body_does_not_verify_old_signature(hook, database):
    raw = json.dumps(payload()).encode()
    assert post(hook, raw=raw + b' ', sign=signed_body(raw)).status_code == 401
    assert counts(database) == (0, 0, 0)


def test_missing_key_is_retryable_without_secret_disclosure(hook, database, monkeypatch):
    def unavailable():
        raise webhook.WebhookNotConfigured('not configured')
    monkeypatch.setattr(webhook, 'configured_key', unavailable)
    response = post(hook)
    assert response.status_code == 503
    assert KEY not in response.text
    assert counts(database) == (0, 0, 0)


@pytest.mark.parametrize('value', [b'{bad json', b'[]', b'\xff',
                                  b'{"event":"TRACKING_UPDATED","event":"x","data":{}}',
                                  b'{"event":"TRACKING_UPDATED","data":{"number":NaN}}'])
def test_signed_invalid_json_does_not_write(hook, database, value):
    assert post(hook, raw=value).status_code == 400
    assert counts(database) == (0, 0, 0)


@pytest.mark.parametrize('changes', [
    {'tag': 'other-cargo'}, {'tag': None}, {'number': 'OBSOLETE-WAYBILL'},
    {'tag': 'cargo-b', 'number': 'WAYBILL-A'},
    {'tag': 'archived-cargo', 'number': 'WAYBILL-A'},
])
def test_callback_must_match_live_parcel_and_waybill(hook, database, changes):
    response = post(hook, payload(**changes))
    assert response.status_code == 200
    assert response.json['data']['ignored'] == 1
    assert counts(database) == (0, 0, 0)


@pytest.mark.parametrize('status', ['Delivered', 'InTransit', 'DeliveryFailure', 'Expired'])
def test_non_exception_states_do_not_close_or_register(hook, database, status):
    uid = post(hook).json['data']['exception_uids'][0]
    assert post(hook, payload(status=status, sub_status=f'{status}_Other')).status_code == 200
    assert counts(database) == (1, 1, 1)
    with database() as session:
        assert session.get(OrderExceptionTable, uid).status == 'open'


def test_failure_rolls_back_notification_history_and_case_then_retry_succeeds(hook, database, monkeypatch):
    original = exceptions.send_message
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated commit failure with sensitive-provider-key')
    monkeypatch.setattr(exceptions, 'send_message', fail)
    response = post(hook)
    assert response.status_code == 503
    assert 'sensitive-provider-key' not in response.text
    assert counts(database) == (0, 0, 0)
    monkeypatch.setattr(exceptions, 'send_message', original)
    assert post(hook).status_code == 200
    assert counts(database) == (1, 1, 1)


def test_unassigned_owner_does_not_consume_event(hook, database):
    with database.begin() as session:
        session.get(OrderTable, 'order-a').salesman_id = None
    assert post(hook).status_code == 409
    assert counts(database) == (0, 0, 0)
    with database.begin() as session:
        session.get(OrderTable, 'order-a').salesman_id = 1
    assert post(hook).status_code == 200
    assert counts(database) == (1, 1, 1)


def test_resolved_replay_stays_closed_and_new_event_creates_new_case(hook, database):
    uid = post(hook).json['data']['exception_uids'][0]
    exceptions.resolve_exception(uid, {'note': '已联系承运商解决', 'event_key': 'resolve'}, {'user_id': 1})
    assert post(hook).json['data']['exception_uids'] == [uid]
    changed = payload(sub_status='Exception_Lost')
    changed['data']['track_info']['latest_event']['description'] = 'Lost'
    next_uid = post(hook, changed).json['data']['exception_uids'][0]
    assert next_uid != uid
    with database() as session:
        assert session.get(OrderExceptionTable, uid).status == 'resolved'
        assert session.get(OrderExceptionTable, next_uid).status == 'open'
    assert counts(database) == (2, 3, 2)


def test_batch_failure_is_atomic(hook, database, monkeypatch):
    data_a, data_b = payload()['data'], payload(number='WAYBILL-B', tag='cargo-b')['data']
    batch = {'event': 'TRACKING_UPDATED', 'data': {'accepted': [data_a, data_b]}}
    original = exceptions.send_message
    def fail_second(*args, **kwargs):
        if kwargs['recipient_id'] == 2:
            raise RuntimeError('retry second row')
        return original(*args, **kwargs)
    monkeypatch.setattr(exceptions, 'send_message', fail_second)
    assert post(hook, batch).status_code == 503
    assert counts(database) == (0, 0, 0)
    monkeypatch.setattr(exceptions, 'send_message', original)
    assert post(hook, batch).status_code == 200
    assert counts(database) == (2, 2, 2)
    assert post(hook, batch).status_code == 200
    assert counts(database) == (2, 2, 2)


def test_body_size_limit_before_processing(hook, database):
    assert post(hook, raw=b'a' * (2 * 1024 * 1024 + 1)).status_code == 413
    assert counts(database) == (0, 0, 0)


def test_signed_other_event_is_acknowledged(hook, database):
    assert post(hook, {'event': 'TRACKING_STOPPED', 'data': {}}).status_code == 200
    assert counts(database) == (0, 0, 0)


def tracking_count(database):
    from data.parcel_tracking import ParcelTrackingUpdateTable
    with database() as session:
        return session.query(ParcelTrackingUpdateTable).count()


def local_tracking(database):
    from services.parcel_tracking_service import cached_tracking_for_cargos
    return cached_tracking_for_cargos([{
        'uid': 'cargo-a', 'target_order_uid': 'order-a', 'waybill_id': 'WAYBILL-A',
    }])['cargo-a']


def full_payload(status='InTransit', time='2026-10-11T12:00:00Z'):
    value = payload(status=status, sub_status=f'{status}_Other')
    info = value['data']['track_info']
    info['latest_event']['time_utc'] = time
    info['tracking'] = {'providers': [{
        'provider': {'key': 3011}, 'latest_sync_time': time,
        'events': [{'time_utc': time, 'time_raw': {'date': '2026-10-11', 'time': '20:00', 'timezone': '+0800'},
                    'description': '运输途中', 'location': '上海'}],
    }]}
    return value


def test_normal_push_saves_full_logistics_and_replay_records_once(hook, database):
    value = full_payload()
    first = post(hook, value)
    assert first.status_code == 200
    assert first.json['data']['recorded'] == first.json['data']['updated'] == 1
    assert first.json['data']['exception_uids'] == []
    cached = local_tracking(database)
    assert cached['track_status'] == 'InTransit_Other'
    assert cached['track_info'] == value['data']['track_info']
    assert cached['events'][0]['description'] == '运输途中'
    assert cached['tracking_pending'] is False and cached['tracking_received_at']
    replay = post(hook, value)
    assert replay.status_code == 200
    assert replay.json['data']['recorded'] == replay.json['data']['updated'] == 0
    assert tracking_count(database) == 1 and counts(database) == (0, 0, 0)
    with database() as session:
        assert session.get(CargoTable, 'cargo-a').status == 1


def test_older_exception_is_recorded_without_replacing_current_or_notifying(hook, database):
    assert post(hook, full_payload('Delivered', '2026-10-11T13:00:00Z')).status_code == 200
    response = post(hook, full_payload('Exception', '2026-10-11T12:00:00Z'))
    assert response.status_code == 200 and response.json['data']['stale'] == 1
    assert tracking_count(database) == 2
    assert local_tracking(database)['track_status'] == 'Delivered_Other'
    assert counts(database) == (0, 0, 0)


def test_tracking_snapshot_and_history_roll_back_with_failed_notice(hook, database, monkeypatch):
    original = exceptions.send_message
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('notification failure')
    monkeypatch.setattr(exceptions, 'send_message', fail)
    assert post(hook, full_payload('Exception')).status_code == 503
    assert tracking_count(database) == 0 and counts(database) == (0, 0, 0)
    monkeypatch.setattr(exceptions, 'send_message', original)
    assert post(hook, full_payload('Exception')).status_code == 200
    assert tracking_count(database) == 1 and counts(database) == (1, 1, 1)


def test_missing_details_and_stopped_event_do_not_erase_saved_tracking(hook, database):
    assert post(hook, full_payload()).status_code == 200
    assert post(hook, payload(track_info=None)).status_code == 200
    assert post(hook, {'event': 'TRACKING_STOPPED', 'data': {'number': 'WAYBILL-A', 'tag': 'cargo-a'}}).status_code == 200
    assert local_tracking(database)['track_status'] == 'InTransit_Other'
    assert tracking_count(database) == 2


def test_batch_retry_includes_normal_tracking_and_exception_notice(hook, database, monkeypatch):
    value = {'event': 'TRACKING_UPDATED', 'data': {'accepted': [
        full_payload()['data'], payload(number='WAYBILL-B', tag='cargo-b')['data'],
    ]}}
    original = exceptions.send_message
    monkeypatch.setattr(exceptions, 'send_message', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('failure')))
    assert post(hook, value).status_code == 503
    assert tracking_count(database) == 0 and counts(database) == (0, 0, 0)
    monkeypatch.setattr(exceptions, 'send_message', original)
    assert post(hook, value).status_code == 200
    assert tracking_count(database) == 2 and counts(database) == (1, 1, 1)
    assert post(hook, value).status_code == 200
    assert tracking_count(database) == 2 and counts(database) == (1, 1, 1)


@pytest.mark.parametrize('tracking', [[], {'providers': {}}, {'providers': [{'events': [3]}]},
                                       {'providers': [{'latest_sync_time': {}}]}])
def test_malformed_full_tracking_does_not_write(hook, database, tracking):
    value = full_payload()
    value['data']['track_info']['tracking'] = tracking
    assert post(hook, value).status_code == 400
    assert tracking_count(database) == 0 and counts(database) == (0, 0, 0)


def test_late_exception_after_same_waybill_order_move_remains_history_only(hook, database):
    assert post(hook, full_payload('Delivered', '2026-10-11T13:00:00Z')).status_code == 200
    with database.begin() as session:
        session.get(CargoTable, 'cargo-a').target_order_uid = 'order-b'
    response = post(hook, full_payload('Exception', '2026-10-11T12:00:00Z'))
    assert response.status_code == 200 and response.json['data']['stale'] == 1
    assert response.json['data']['updated'] == 0
    assert tracking_count(database) == 2 and counts(database) == (0, 0, 0)
    from services.parcel_tracking_service import cached_tracking_for_cargos
    assert cached_tracking_for_cargos([{
        'uid': 'cargo-a', 'target_order_uid': 'order-b', 'waybill_id': 'WAYBILL-A',
    }])['cargo-a']['tracking_pending'] is True
