"""Tracking facts persist atomically and GET never refreshes from 17TRACK."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.dialects import mysql

from data.DB import CargoTable, OrderTable
from data.parcel_tracking import ParcelTrackingUpdateTable
from services import cargo_service, parcel_tracking_service


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) if value else None


def tracking_row(*, updated_at="2026-10-11T10:00:00Z", status="InTransit",
                 sub_status="InTransit_Other", description="运输中"):
    provider = {"provider": {"key": 100001, "name": "Test carrier"}, "events": []}
    if updated_at is not None:
        provider["latest_sync_time"] = updated_at
    return {
        "number": "WAYBILL-A", "tag": "cargo-a", "carrier": 100001,
        "track_info": {
            "latest_status": {"status": status, "sub_status": sub_status,
                              "sub_status_descr": description},
            "latest_event": None,
            "tracking": {"providers": [provider]},
            "custom_provider_field": {"detail": "完整原始缓存"},
        },
    }


def append_update(factory, row, key, *, cargo_uid="cargo-a"):
    with factory.begin() as session:
        cargo = session.get(CargoTable, cargo_uid)
        record, replayed, applied = parcel_tracking_service.record_tracking_update(
            session, cargo, row, key,
        )
        return record.uid, replayed, applied


def cargo_payload(factory, cargo_uid="cargo-a"):
    with factory() as session:
        cargo = session.get(CargoTable, cargo_uid)
        return {column.name: getattr(cargo, column.name)
                for column in CargoTable.__table__.columns}


def cached(factory, cargo_uid="cargo-a"):
    payload = cargo_payload(factory, cargo_uid)
    return parcel_tracking_service.cached_tracking_for_cargos([payload])[cargo_uid]


def ledger(factory):
    with factory() as session:
        return [{column.name: getattr(record, column.name)
                 for column in ParcelTrackingUpdateTable.__table__.columns}
                for record in session.query(ParcelTrackingUpdateTable).all()]


def test_preserves_complete_row_and_integer_business_status(database):
    row = tracking_row()
    uid, replayed, applied = append_update(database, row, "event-1")

    assert (replayed, applied) == (False, True)
    record = ledger(database)[0]
    assert record["uid"] == uid
    assert record["cargo_uid"] == "cargo-a"
    assert record["order_uid"] == "order-a"
    assert record["waybill_id"] == "WAYBILL-A"
    assert record["event_key"] == "event-1"
    assert json.loads(record["row_json"]) == row
    assert record["is_current"] is True
    assert record["exception_uid"] is None
    assert instant(record["source_updated_at"]) == instant("2026-10-11T10:00:00Z")
    assert record["source_updated_at"].endswith("Z")
    assert datetime.fromisoformat(record["received_at"].replace("Z", "+00:00")).tzinfo is not None
    assert cargo_payload(database)["status"] == 1
    result = cached(database)
    assert result["track_status"] == "InTransit_Other"
    assert result["desc"] == "运输中"
    assert result["track_info"] == row["track_info"]
    assert result["tracking_received_at"] == record["received_at"]
    assert result["tracking_pending"] is False


def test_mysql_uses_longtext_for_full_provider_timeline():
    assert ParcelTrackingUpdateTable.__table__.c.row_json.type.compile(dialect=mysql.dialect()) == "LONGTEXT"


def test_provider_row_larger_than_mysql_text_limit_is_fully_preserved(database):
    row = tracking_row()
    row["track_info"]["custom_provider_field"]["detail"] = "完整物流信息" * 15000
    append_update(database, row, "large-payload")
    record = ledger(database)[0]

    assert len(record["row_json"].encode("utf-8")) > 65535
    assert json.loads(record["row_json"]) == row
    assert cached(database)["track_info"] == row["track_info"]


def test_exact_replay_returns_original_without_applying_again(database):
    row = tracking_row()
    original_uid, _, _ = append_update(database, row, "same-event")
    # JSON object order must not turn a provider retry into a conflict.
    reordered = {key: row[key] for key in reversed(row)}
    replay_uid, replayed, applied = append_update(database, reordered, "same-event")

    assert replay_uid == original_uid
    assert (replayed, applied) == (True, False)
    assert len(ledger(database)) == 1


def test_same_event_key_with_changed_content_conflicts_and_retains_current(database):
    original = tracking_row()
    append_update(database, original, "same-event")
    changed = tracking_row(description="changed retry content")

    with pytest.raises(parcel_tracking_service.TrackingConflictError):
        append_update(database, changed, "same-event")

    assert len(ledger(database)) == 1
    assert cached(database)["track_info"] == original["track_info"]


def test_global_event_key_cannot_be_reused_for_another_parcel(database):
    append_update(database, tracking_row(), "same-event")
    another = tracking_row()
    another.update(number="WAYBILL-B", tag="cargo-b")

    with pytest.raises(parcel_tracking_service.TrackingConflictError):
        append_update(database, another, "same-event", cargo_uid="cargo-b")

    assert len(ledger(database)) == 1
    assert cached(database, "cargo-b")["tracking_pending"] is True


def test_replay_after_order_reassignment_preserves_original_scope(database):
    row = tracking_row()
    original_uid, _, _ = append_update(database, row, "before-reassignment")
    with database.begin() as session:
        session.get(CargoTable, "cargo-a").target_order_uid = "order-b"

    uid, replayed, applied = append_update(database, row, "before-reassignment")

    assert uid == original_uid
    assert (replayed, applied) == (True, False)
    assert len(ledger(database)) == 1
    assert ledger(database)[0]["order_uid"] == "order-a"
    assert cached(database)["tracking_pending"] is True


def test_new_callback_after_order_reassignment_records_new_scope(database):
    append_update(database, tracking_row(), "before-reassignment")
    with database.begin() as session:
        session.get(CargoTable, "cargo-a").target_order_uid = "order-b"
    new_uid, _, applied = append_update(
        database, tracking_row(description="new order scope"), "after-reassignment",
    )

    assert applied is True
    records = ledger(database)
    assert {record["order_uid"] for record in records} == {"order-a", "order-b"}
    assert [(record["uid"], record["order_uid"]) for record in records if record["is_current"]] == [
        (new_uid, "order-b"),
    ]
    assert cached(database)["desc"] == "new order scope"


def test_waybill_mismatch_rejects_update_without_persisting(database):
    row = tracking_row()
    row["number"] = "WRONG-WAYBILL"
    with pytest.raises(parcel_tracking_service.TrackingConflictError):
        append_update(database, row, "wrong-number")

    assert ledger(database) == []
    assert cached(database)["tracking_pending"] is True


def test_caller_rollback_removes_fact_and_allows_error_retry(database):
    with database() as session:
        cargo = session.get(CargoTable, "cargo-a")
        parcel_tracking_service.record_tracking_update(session, cargo, tracking_row(), "retryable")
        assert session.query(ParcelTrackingUpdateTable).count() == 1
        session.rollback()

    assert ledger(database) == []
    assert cached(database)["tracking_pending"] is True
    _, replayed, applied = append_update(database, tracking_row(), "retryable")
    assert (replayed, applied) == (False, True)
    assert len(ledger(database)) == 1


def test_rollback_restores_previous_current_flag(database):
    original = tracking_row()
    original_uid, _, _ = append_update(database, original, "initial")
    with database() as session:
        cargo = session.get(CargoTable, "cargo-a")
        parcel_tracking_service.record_tracking_update(
            session, cargo, tracking_row(updated_at="2026-10-11T11:00:00Z"), "failed-next",
        )
        session.rollback()

    assert [(record["uid"], record["is_current"]) for record in ledger(database)] == [(original_uid, True)]
    assert cached(database)["track_info"] == original["track_info"]


def test_older_update_is_retained_as_history_without_overriding_current(database):
    current = tracking_row(updated_at="2026-10-11T11:00:00Z", description="newest")
    current_uid, _, _ = append_update(database, current, "newer")
    older_uid, replayed, applied = append_update(
        database, tracking_row(updated_at="2026-10-11T10:00:00Z"), "older",
    )

    assert (replayed, applied) == (False, False)
    records = {record["uid"]: record for record in ledger(database)}
    assert records[current_uid]["is_current"] is True
    assert records[older_uid]["is_current"] is False
    assert cached(database)["desc"] == "newest"


def test_equal_utc_timestamp_can_apply_more_recent_callback_content(database):
    original_uid, _, _ = append_update(database, tracking_row(), "original")
    new_row = tracking_row(updated_at="2026-10-11T18:00:00+08:00", description="same instant, new detail")
    current_uid, _, applied = append_update(database, new_row, "equal-instant")

    assert applied is True
    records = {record["uid"]: record for record in ledger(database)}
    assert records[original_uid]["is_current"] is False
    assert records[current_uid]["is_current"] is True
    assert instant(records[current_uid]["source_updated_at"]) == instant("2026-10-11T10:00:00Z")
    assert cached(database)["desc"] == "same instant, new detail"


def test_known_current_timestamp_rejects_unknown_time_as_current(database):
    append_update(database, tracking_row(description="known date"), "known")
    _, replayed, applied = append_update(database, tracking_row(updated_at=None), "unknown")

    assert (replayed, applied) == (False, False)
    assert cached(database)["desc"] == "known date"
    assert len(ledger(database)) == 2


def test_unknown_dates_use_arrival_order_until_a_known_date_arrives(database):
    initial_uid, _, applied = append_update(database, tracking_row(updated_at=None), "first-unknown")
    assert applied is True
    second_uid, _, applied = append_update(
        database, tracking_row(updated_at=None, description="second arrival"), "second-unknown",
    )
    assert applied is True
    assert cached(database)["desc"] == "second arrival"
    dated_uid, _, applied = append_update(database, tracking_row(description="dated"), "known")

    assert applied is True
    records = {record["uid"]: record for record in ledger(database)}
    assert records[initial_uid]["source_updated_at"] is None
    assert records[second_uid]["is_current"] is False
    assert records[dated_uid]["is_current"] is True


def test_source_time_uses_maximum_valid_provider_sync_time(database):
    row = tracking_row(updated_at="2026-10-11T18:00:00+08:00")
    row["track_info"]["latest_event"] = {"time_utc": "2026-10-13T12:00:00Z"}
    row["track_info"]["tracking"]["providers"].extend([
        {"latest_sync_time": "2026-10-11T11:30:00Z", "events": []},
        {"latest_sync_time": "2026-10-15T12:00:00", "events": []},
        {"latest_sync_time": "invalid", "events": []},
    ])
    append_update(database, row, "many-providers")

    # Sync times describe the provider snapshot and take precedence over events.
    assert instant(ledger(database)[0]["source_updated_at"]) == instant("2026-10-11T11:30:00Z")


@pytest.mark.parametrize("latest_event, expected", [
    ({"time_utc": "2026-10-11T10:30:00Z"}, "2026-10-11T10:30:00Z"),
    ({"time_iso": "2026-10-11T18:30:00+08:00"}, "2026-10-11T10:30:00Z"),
    ({"time_utc": "invalid", "time_iso": "2026-10-11T18:30:00+08:00"}, "2026-10-11T10:30:00Z"),
    ({"time_utc": "2026-10-11T10:30:00"}, None),
    ({"time_raw": {"date": "2026-10-11", "time": "10:30:00"}}, None),
    (None, None),
])
def test_fallback_event_time_requires_timezone(database, latest_event, expected):
    row = tracking_row(updated_at=None)
    row["track_info"]["latest_event"] = latest_event
    append_update(database, row, "event-time")

    assert instant(ledger(database)[0]["source_updated_at"]) == instant(expected)


@pytest.mark.parametrize("missing", ["track_info", "null_info", "latest_status", "null_status", "status", "null_status_value"])
def test_incomplete_callback_never_clears_good_cached_state(database, missing):
    original = tracking_row()
    append_update(database, original, "good")
    incomplete = tracking_row(updated_at="2026-10-11T12:00:00Z")
    if missing == "track_info":
        incomplete.pop("track_info")
    elif missing == "null_info":
        incomplete["track_info"] = None
    elif missing == "latest_status":
        incomplete["track_info"].pop("latest_status")
    elif missing == "null_status":
        incomplete["track_info"]["latest_status"] = None
    elif missing == "status":
        incomplete["track_info"]["latest_status"].pop("status")
    else:
        incomplete["track_info"]["latest_status"]["status"] = None

    _, replayed, applied = append_update(database, incomplete, f"missing-{missing}")
    assert (replayed, applied) == (False, False)
    assert len(ledger(database)) == 2
    assert cached(database)["track_info"] == original["track_info"]


def test_replay_of_noncurrent_history_does_not_reactivate_it(database):
    old = tracking_row(updated_at="2026-10-11T09:00:00Z")
    old_uid, _, _ = append_update(database, old, "old")
    append_update(database, tracking_row(description="current"), "new")
    uid, replayed, applied = append_update(database, old, "old")

    assert uid == old_uid
    assert (replayed, applied) == (True, False)
    assert cached(database)["desc"] == "current"
    assert sum(record["is_current"] for record in ledger(database)) == 1


@pytest.mark.parametrize("field, value", [
    ("uid", "cargo-b"), ("target_order_uid", "order-b"), ("waybill_id", "REPLACED-WAYBILL"),
])
def test_cache_must_match_cargo_order_and_waybill_snapshots(database, field, value):
    append_update(database, tracking_row(), "original")
    payload = cargo_payload(database)
    payload[field] = value

    result = parcel_tracking_service.cached_tracking_for_cargos([payload])[payload["uid"]]
    assert result["tracking_pending"] is True
    assert result["track_info"] is None
    assert not result["events"]


def test_waybill_change_leaves_old_history_and_waits_for_matching_callback(database):
    old_uid, _, _ = append_update(database, tracking_row(), "old-number")
    with database.begin() as session:
        cargo = session.get(CargoTable, "cargo-a")
        cargo.waybill_id = "NEW-WAYBILL"

    assert cached(database)["tracking_pending"] is True
    new_row = tracking_row(updated_at="2026-10-11T11:00:00Z", description="new number")
    new_row["number"] = "NEW-WAYBILL"
    new_uid, _, applied = append_update(database, new_row, "new-number")
    assert applied is True
    records = {record["uid"]: record for record in ledger(database)}
    assert records[old_uid]["waybill_id"] == "WAYBILL-A"
    assert records[new_uid]["waybill_id"] == "NEW-WAYBILL"
    assert cached(database)["desc"] == "new number"


def test_deleted_cargo_and_order_keep_tracking_history(database):
    append_update(database, tracking_row(), "retained-history")
    with database.begin() as session:
        session.query(CargoTable).filter_by(uid="cargo-a").delete(synchronize_session=False)
        session.query(OrderTable).filter_by(uid="order-a").delete(synchronize_session=False)

    records = ledger(database)
    assert len(records) == 1
    assert (records[0]["cargo_uid"], records[0]["order_uid"], records[0]["waybill_id"]) == (
        "cargo-a", "order-a", "WAYBILL-A",
    )


def test_events_include_every_provider_and_remove_duplicate_event_objects(database):
    first = {"time_utc": "2026-10-11T08:00:00Z", "location": "A", "description": "first"}
    second = {"time_utc": "2026-10-11T09:00:00Z", "location": "B", "description": "second"}
    third = {"time_utc": "2026-10-11T10:00:00Z", "location": "C", "description": "third"}
    row = tracking_row()
    row["track_info"]["tracking"]["providers"][0]["events"] = [first, second]
    row["track_info"]["tracking"]["providers"].append({
        "events": [dict(reversed(list(second.items()))), third],
    })
    append_update(database, row, "all-events")

    events = cached(database)["events"]
    assert len(events) == 3
    assert {event["description"] for event in events} == {"first", "second", "third"}
    assert [event["description"] for event in events] == ["third", "second", "first"]
    assert cached(database)["track_info"] == row["track_info"]


def test_provider_events_sort_by_aware_utc_with_unknown_times_last(database):
    row = tracking_row()
    row["track_info"]["tracking"]["providers"][0]["events"] = [
        {"time_iso": "2026-10-11T17:00:00+08:00", "description": "09:00 UTC"},
        {"description": "unknown first"},
    ]
    row["track_info"]["tracking"]["providers"].append({"events": [
        {"time_utc": "2026-10-11T10:00:00Z", "description": "10:00 UTC"},
        {"time_utc": "2026-10-11T11:00:00", "description": "naive second"},
    ]})
    append_update(database, row, "cross-provider-timeline")

    assert [event["description"] for event in cached(database)["events"]] == [
        "10:00 UTC", "09:00 UTC", "unknown first", "naive second",
    ]


def test_malformed_event_fields_are_retained_in_raw_cache_but_not_timeline(database):
    valid = {"description": "valid", "location": "A", "time_iso": "2026-10-11T10:00:00Z"}
    malformed = [None, "event", {"description": {"unexpected": "object"}},
                 {"location": ["unexpected"]}, {"time_utc": 123},
                 {"time_raw": {"date": ["unexpected"]}}]
    row = tracking_row()
    row["track_info"]["tracking"]["providers"][0]["events"] = [valid, *malformed]
    row["track_info"]["tracking"]["providers"].extend([None, {"events": "invalid"}])
    append_update(database, row, "malformed-events")

    result = cached(database)
    assert result["events"] == [valid]
    assert result["track_info"] == row["track_info"]
    assert json.loads(ledger(database)[0]["row_json"]) == row


def test_empty_and_untracked_cargos_have_pending_local_response(database):
    assert parcel_tracking_service.cached_tracking_for_cargos([]) == {}
    payload = cargo_payload(database)
    payload["waybill_id"] = None
    result = parcel_tracking_service.cached_tracking_for_cargos([payload])["cargo-a"]

    assert result["tracking_pending"] is True
    assert result["track_info"] is None
    assert not result["events"]


@pytest.mark.parametrize("case", ["empty", "missing_order", "no_waybill"])
def test_no_eligible_tracking_tuple_avoids_database_query(database, monkeypatch, case):
    payload = cargo_payload(database)
    if case == "missing_order":
        payload["target_order_uid"] = None
    elif case == "no_waybill":
        payload["waybill_id"] = "  "
    factory = Mock(side_effect=AssertionError("ineligible parcel queried tracking database"))
    monkeypatch.setattr(parcel_tracking_service, "SessionFactory", factory)

    result = parcel_tracking_service.cached_tracking_for_cargos([] if case == "empty" else [payload])

    assert result == {} if case == "empty" else result["cargo-a"]["tracking_pending"] is True
    factory.assert_not_called()


@pytest.mark.parametrize("has_cache", [False, True])
def test_get_cargo_merges_only_local_cache_without_network_or_writes(database, has_cache):
    if has_cache:
        append_update(database, tracking_row(), "cached")
    original = cargo_payload(database)
    order_model, cargo_model = Mock(), Mock()
    order_model.read.return_value = {"cargo_uid_list": ["cargo-a", "missing-cargo"]}
    cargo_model.read.side_effect = [deepcopy(original), None]
    before = ledger(database)

    with patch("requests.sessions.Session.request", side_effect=AssertionError("GET attempted outbound HTTP")) as network, patch(
        "services.cargo_service.getTrackInfo", side_effect=AssertionError("GET queried 17TRACK")
    ) as query_tracking, patch(
        "services.cargo_service.registerTrack", side_effect=AssertionError("GET registered with 17TRACK")
    ) as register_tracking:
        result, error = cargo_service.get_cargo_with_tracking("order-a", order_model, cargo_model)

    assert error is None
    assert len(result) == 1
    assert result[0]["status"] == 1
    assert result[0]["tracking_pending"] is (not has_cache)
    assert result[0]["track_info"] == (tracking_row()["track_info"] if has_cache else None)
    network.assert_not_called()
    query_tracking.assert_not_called()
    register_tracking.assert_not_called()
    cargo_model.update.assert_not_called()
    assert ledger(database) == before
    assert cargo_payload(database) == original


def test_get_cargo_order_not_found_does_not_read_cache(database, monkeypatch):
    order_model, cargo_model = Mock(), Mock()
    order_model.read.return_value = None
    cache = Mock(side_effect=AssertionError("missing order queried cache"))
    monkeypatch.setattr(cargo_service, "cached_tracking_for_cargos", cache)

    assert cargo_service.get_cargo_with_tracking("missing-order", order_model, cargo_model) == (None, "Order Not Found")
    cargo_model.read.assert_not_called()
    cache.assert_not_called()


@pytest.mark.parametrize("change", ["moved", "archived"])
def test_get_cargo_drops_parcels_moved_or_archived_since_order_read(database, change):
    append_update(database, tracking_row(), "original-order")
    payload = cargo_payload(database)
    if change == "moved":
        payload["target_order_uid"] = "order-b"
    else:
        payload["archive"] = True
    order_model, cargo_model = Mock(), Mock()
    order_model.read.return_value = {"cargo_uid_list": ["cargo-a"]}
    cargo_model.read.return_value = payload

    result, error = cargo_service.get_cargo_with_tracking("order-a", order_model, cargo_model)

    assert error is None
    assert result == []
    cargo_model.update.assert_not_called()
