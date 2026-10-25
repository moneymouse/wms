"""Authenticated 17TRACK v2.2 updates, using the shared exception transaction.

The provider signs the original UTF-8 request body, not a reserialized JSON
document. A canonical content key is used *after* verification for persistent
deduplication of stored logistics updates and exception notifications.
Warehouse cargo status is untouched.
"""

import hashlib
import hmac
import json
import re
from pathlib import Path

import toml

from data.DB import CargoTable, OrderTable
from data.database import SessionFactory
from services.order_exception_service import ExceptionConflictError, register_exception
from services.tracking_status import SUB_STATUS_TEXT
from services.parcel_tracking_service import record_tracking_update


class WebhookNotConfigured(RuntimeError):
    pass


def configured_key():
    # Reuse the same existing API security key as utils/l7track.py. Never load
    # private configuration from the original checkout or log its contents.
    try:
        value = toml.load(Path(__file__).resolve().parents[1] / "env.toml").get("17track_token")
    except (OSError, ValueError):
        raise WebhookNotConfigured("17TRACK 回调验签密钥未配置") from None
    if not isinstance(value, str) or not value.strip():
        raise WebhookNotConfigured("17TRACK 回调验签密钥未配置")
    return value


def verify_signature(raw_body, signature, key):
    if not isinstance(key, str) or not key.strip():
        raise WebhookNotConfigured("17TRACK 回调验签密钥未配置")
    if not isinstance(signature, str) or re.fullmatch(r"[0-9a-fA-F]{64}", signature) is None:
        raise PermissionError("17TRACK 回调签名无效")
    expected = hashlib.sha256(raw_body + b"/" + key.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise PermissionError("17TRACK 回调签名无效")


def _json(raw_body):
    # Reject duplicate JSON keys instead of silently accepting a different
    # interpretation of a signed object in different runtimes.
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("17TRACK 回调 JSON 字段重复")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("17TRACK 回调 JSON 数值无效")

    try:
        payload = json.loads(raw_body.decode("utf-8"), object_pairs_hook=object_pairs,
                             parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("17TRACK 回调内容无效") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
        raise ValueError("17TRACK 回调内容无效")
    return payload


def _validate_tracking_info(info):
    latest = info.get("latest_event")
    if latest is not None and not isinstance(latest, dict):
        raise ValueError("17TRACK 回调物流事件无效")
    tracking = info.get("tracking")
    if tracking is None:
        return
    if not isinstance(tracking, dict):
        raise ValueError("17TRACK 回调物流轨迹无效")
    providers = tracking.get("providers", [])
    if not isinstance(providers, list):
        raise ValueError("17TRACK 回调物流轨迹无效")
    for provider in providers:
        if not isinstance(provider, dict):
            raise ValueError("17TRACK 回调物流轨迹无效")
        sync_time = provider.get("latest_sync_time")
        if sync_time is not None and not isinstance(sync_time, str):
            raise ValueError("17TRACK 回调物流时间无效")
        events = provider.get("events", [])
        if events is None:
            events = []
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            raise ValueError("17TRACK 回调物流事件无效")
        for event in events + ([latest] if latest else []):
            for field in ("time_utc", "time_iso", "location", "description"):
                value = event.get(field)
                if value is not None and not isinstance(value, str):
                    raise ValueError("17TRACK 回调物流事件无效")
            raw_time = event.get("time_raw")
            if raw_time is not None and (not isinstance(raw_time, dict) or any(
                    value is not None and not isinstance(value, str) for value in raw_time.values())):
                raise ValueError("17TRACK 回调物流时间无效")


def _updates(payload):
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("17TRACK 回调物流数据无效")
    # The detailed v2.2 webhook schema contains one record; its quick-start
    # example also shows an accepted array. Both use the same record schema.
    if "accepted" in data:
        rows = data["accepted"]
        if not isinstance(rows, list) or not rows or len(rows) > 40:
            raise ValueError("17TRACK 回调物流数据无效")
    else:
        rows = [data]
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("17TRACK 回调物流数据无效")
        number, tag = row.get("number"), row.get("tag")
        if not isinstance(number, str) or not number.strip() or len(number) > 256:
            raise ValueError("17TRACK 回调转单号无效")
        if tag is not None and (not isinstance(tag, str) or len(tag) > 100):
            raise ValueError("17TRACK 回调包裹标识无效")
        info = row.get("track_info")
        if info is None:
            normalized.append((row, None))
            continue
        if not isinstance(info, dict):
            raise ValueError("17TRACK 回调物流状态无效")
        _validate_tracking_info(info)
        status = info.get("latest_status")
        if status is None:
            normalized.append((row, None))
            continue
        if (not isinstance(status, dict) or not isinstance(status.get("status"), str)
                or not status["status"]):
            raise ValueError("17TRACK 回调物流状态无效")
        for field in ("sub_status", "sub_status_descr"):
            value = status.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 2000):
                raise ValueError("17TRACK 回调物流状态无效")
        normalized.append((row, status))
    return normalized


def _locked_live_cargo(session, order_uid, cargo_uid, number):
    # Use the same order -> cargo lock order as ordinary parcel mutations and
    # exception registration, then recheck the registration after waiting.
    order = (session.query(OrderTable).filter(OrderTable.uid == order_uid)
             .populate_existing().with_for_update().first())
    cargo = (session.query(CargoTable).filter(CargoTable.uid == cargo_uid)
             .populate_existing().with_for_update().first())
    if (order is None or order.archive or cargo is None or cargo.archive
            or cargo.target_order_uid != order_uid
            or (cargo.waybill_id or "").strip() != number.strip()):
        return None
    return cargo


def receive_update(raw_body, signature, *, key=None):
    verify_signature(raw_body, signature, configured_key() if key is None else key)
    payload = _json(raw_body)
    if payload["event"] != "TRACKING_UPDATED":
        return {"processed": 0, "recorded": 0, "updated": 0, "ignored": 1,
                "stale": 0, "exception_uids": []}
    updates = _updates(payload)
    ignored, processed, recorded, updated, stale, exception_uids = 0, 0, 0, 0, 0, []
    with SessionFactory() as session:
        # Store all logistics states. Registration, the full snapshot, history
        # and any exception notice commit together, or all remain retryable.
        matched = []
        for row, status in updates:
            cargo = session.get(CargoTable, row.get("tag")) if row.get("tag") else None
            if (cargo is None or cargo.archive or not cargo.target_order_uid
                    or (cargo.waybill_id or "").strip() != row["number"].strip()):
                ignored += 1
                continue
            matched.append((cargo.target_order_uid, cargo.uid, row, status))
        for order_uid, cargo_uid, row, status in sorted(matched, key=lambda item: (item[0], item[1])):
            cargo = _locked_live_cargo(session, order_uid, cargo_uid, row["number"])
            if cargo is None:
                ignored += 1
                continue
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            event_key = "17track:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            saved, replayed, applied = record_tracking_update(session, cargo, row, event_key)
            processed += 1
            recorded += int(not replayed)
            updated += int(applied)
            stale += int(not replayed and not applied)
            if replayed:
                if saved.exception_uid:
                    exception_uids.append(saved.exception_uid)
                continue
            if applied and status is not None and status["status"] == "Exception":
                sub_status = status.get("sub_status")
                reason = SUB_STATUS_TEXT.get(sub_status, "物流异常")
                description = (status.get("sub_status_descr") or "").strip()
                if description:
                    reason = (reason + "：" + description)[:2000]
                case = register_exception(session, order_uid=order_uid, cargo_uid=cargo_uid,
                                          reason=reason, source="17track", event_key=event_key,
                                          tracking_status=sub_status or "Exception",
                                          expected_waybill_id=row["number"].strip())
                saved.exception_uid = case.uid
                exception_uids.append(case.uid)
            # A normal logistics state never resolves an open exception.
        session.commit()
    return {"processed": processed, "recorded": recorded, "updated": updated,
            "ignored": ignored, "stale": stale, "exception_uids": exception_uids}
