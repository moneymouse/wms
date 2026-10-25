"""Transactional push history and local-only tracking projections.

The caller locks the current order and parcel before recording an update. Time
watermarks reject clearly older data; they do not guarantee a global ordering
of provider callbacks. No operation in this module contacts 17TRACK.
"""

from datetime import datetime, timezone
import json
import uuid

from sqlalchemy.exc import IntegrityError

from data.database import SessionFactory
from data.parcel_tracking import ParcelTrackingUpdateTable


class TrackingConflictError(ValueError):
    """A persistent delivery key was reused for different tracking content."""


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("物流推送内容无效") from None


def _aware_utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _source_updated_at(row):
    info = row.get("track_info")
    if not isinstance(info, dict):
        return None
    tracking = info.get("tracking")
    providers = tracking.get("providers") if isinstance(tracking, dict) else None
    sync_times = [
        parsed for provider in providers if isinstance(provider, dict)
        for parsed in [_aware_utc(provider.get("latest_sync_time"))] if parsed
    ] if isinstance(providers, list) else []
    if sync_times:
        return max(sync_times)
    latest = info.get("latest_event")
    if isinstance(latest, dict):
        return _aware_utc(latest.get("time_utc")) or _aware_utc(latest.get("time_iso"))
    return None


def _displayable(row):
    info = row.get("track_info")
    if not isinstance(info, dict):
        return False
    status = info.get("latest_status")
    return bool(
        isinstance(status, dict) and isinstance(status.get("status"), str) and status["status"].strip()
        and all(status.get(field) is None or isinstance(status.get(field), str)
                for field in ("sub_status", "sub_status_descr"))
    )


def _replayed(session, *, event_key, cargo, row_json):
    record = session.query(ParcelTrackingUpdateTable).filter_by(event_key=event_key).with_for_update().first()
    if record is None:
        return None
    if (record.cargo_uid != cargo.uid
            or record.waybill_id != (cargo.waybill_id or "").strip() or record.row_json != row_json):
        raise TrackingConflictError("物流事件编号已用于另一条更新")
    return record


def record_tracking_update(session, cargo, row, event_key):
    """Return (record, replayed, applied) in a caller-owned transaction.

    Payload, receipt time and watermark remain immutable. Only is_current and
    the transactionally linked exception_uid can change after insertion.
    Duplicate delivery returns the original record with applied=False.
    """
    if not isinstance(row, dict):
        raise ValueError("物流推送内容必须为 JSON 对象")
    if not isinstance(event_key, str) or not event_key.strip() or len(event_key) > 128:
        raise ValueError("物流事件编号无效")
    event_key = event_key.strip()
    number = (cargo.waybill_id or "").strip()
    if not cargo.uid or not cargo.target_order_uid or not number:
        raise ValueError("包裹未关联订单或转单号")
    if not isinstance(row.get("number"), str) or row["number"].strip() != number:
        raise TrackingConflictError("物流转单号与当前包裹不符")
    row_json = _canonical(row)
    session.flush()
    existing = _replayed(session, event_key=event_key, cargo=cargo, row_json=row_json)
    if existing is not None:
        return existing, True, False
    watermark = _source_updated_at(row)
    current = session.query(ParcelTrackingUpdateTable).filter_by(
        cargo_uid=cargo.uid, waybill_id=number, is_current=True,
    ).with_for_update().first()
    applied = _displayable(row)
    if current is not None and current.source_updated_at is not None:
        if watermark is None or watermark < current.source_updated_at:
            applied = False
    record = ParcelTrackingUpdateTable(
        uid=uuid.uuid4().hex, cargo_uid=cargo.uid, order_uid=cargo.target_order_uid,
        waybill_id=number, event_key=event_key, row_json=row_json,
        received_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        source_updated_at=watermark, is_current=applied,
    )
    try:
        with session.begin_nested():
            if applied:
                session.query(ParcelTrackingUpdateTable).filter_by(cargo_uid=cargo.uid, is_current=True).update(
                    {ParcelTrackingUpdateTable.is_current: False}, synchronize_session="fetch",
                )
            session.add(record)
            session.flush()
    except IntegrityError:
        existing = _replayed(session, event_key=event_key, cargo=cargo, row_json=row_json)
        if existing is None:
            raise
        return existing, True, False
    return record, False, applied


def _pending():
    return {"track_status": None, "desc": "", "events": [], "track_info": None,
            "tracking_received_at": None, "tracking_pending": True}


def _events(info):
    tracking = info.get("tracking")
    providers = tracking.get("providers") if isinstance(tracking, dict) else None
    if not isinstance(providers, list):
        return []
    events, seen = [], set()
    for provider in providers:
        items = provider.get("events") if isinstance(provider, dict) else None
        if not isinstance(items, list):
            continue
        for event in items:
            if not isinstance(event, dict):
                continue
            # Timeline renders these values as text, so malformed provider
            # structures must not reach React as child objects.
            if any(event.get(field) is not None and not isinstance(event.get(field), str)
                   for field in ("location", "description", "time_utc", "time_iso")):
                continue
            raw = event.get("time_raw")
            if raw is not None and (not isinstance(raw, dict) or any(
                    raw.get(field) is not None and not isinstance(raw.get(field), str)
                    for field in ("date", "time", "timezone"))):
                continue
            event_key = _canonical(event)
            if event_key not in seen:
                seen.add(event_key)
                events.append(event)
    # Known event instants sort newest first across providers; stable sorting
    # preserves receipt order for ties and events without comparable times.
    return sorted(events, key=lambda event: (
        _aware_utc(event.get("time_utc")) or _aware_utc(event.get("time_iso")) or ""
    ), reverse=True)


def cached_tracking_for_cargos(cargos):
    """Batch-read the current push matching each live cargo/order/waybill tuple."""
    result = {cargo["uid"]: _pending() for cargo in cargos}
    eligible = {cargo["uid"]: cargo for cargo in cargos
                if cargo.get("target_order_uid") and str(cargo.get("waybill_id") or "").strip()}
    if not eligible:
        return result
    with SessionFactory() as session:
        records = session.query(ParcelTrackingUpdateTable).filter(
            ParcelTrackingUpdateTable.cargo_uid.in_(eligible), ParcelTrackingUpdateTable.is_current.is_(True),
        ).order_by(ParcelTrackingUpdateTable.received_at.asc(), ParcelTrackingUpdateTable.uid.asc()).all()
        for record in records:
            cargo = eligible[record.cargo_uid]
            if (record.order_uid != cargo.get("target_order_uid")
                    or record.waybill_id != str(cargo.get("waybill_id") or "").strip()):
                continue
            try:
                row = json.loads(record.row_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict) or not _displayable(row):
                continue
            info = row["track_info"]
            status = info["latest_status"]
            result[record.cargo_uid] = {
                "track_status": status.get("sub_status") or status["status"],
                "desc": status.get("sub_status_descr") or "", "events": _events(info),
                "track_info": info, "tracking_received_at": record.received_at, "tracking_pending": False,
            }
    return result
