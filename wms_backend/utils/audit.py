"""Business audit events. Financial writes must pass their active session."""
import json
import time
import uuid
from decimal import Decimal

from flask import has_request_context, request
from sqlalchemy import or_

from Auth import get_payload_roles, get_token_payload
from data.database import SessionFactory
from data.DB import AuditLogTable


AUDIT_LOG_SORT_FIELDS = {
    field: getattr(AuditLogTable, field)
    for field in ("id", "create_date", "event_type", "action", "target_type", "operator_name", "operator_role")
}
META_KEY = "_audit_metadata"


def _correlation_id(session, supplied):
    if session is None:
        return supplied or uuid.uuid4().hex
    transaction = session.get_transaction() or session.begin()
    prior_transaction, prior_id = session.info.get("wms_audit_correlation", (None, None))
    value = supplied or (prior_id if prior_transaction is transaction else None) or uuid.uuid4().hex
    session.info["wms_audit_correlation"] = (transaction, value)
    return value


def _json_dump(value):
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


def _parse_json_value(raw):
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return raw


def field_changes(before, after, path=""):
    """Readable leaf differences; arrays are compared by stable item ID when available."""
    if before == after:
        return []
    if isinstance(before, dict) or isinstance(after, dict):
        old, new = before if isinstance(before, dict) else {}, after if isinstance(after, dict) else {}
        result = []
        for key in sorted(set(old) | set(new)):
            if key == META_KEY:
                continue
            result.extend(field_changes(old.get(key), new.get(key), f"{path}.{key}" if path else key))
        return result
    if isinstance(before, list) and isinstance(after, list) and before and after:
        rows = before + after
        if all(isinstance(row, dict) and row.get("id") is not None for row in rows):
            old, new = {str(row['id']): row for row in before}, {str(row['id']): row for row in after}
            return [change for key in sorted(set(old) | set(new))
                    for change in field_changes(old.get(key), new.get(key), f"{path}[{key}]")]
    # Decimal-backed money may have JSON numbers in legacy events and strings in v2.
    if (not isinstance(before, bool) and not isinstance(after, bool)
            and isinstance(before, (int, float, Decimal)) and isinstance(after, (int, float, Decimal))):
        if Decimal(str(before)) == Decimal(str(after)):
            return []
    return [{"field": path, "before": before, "after": after}]


def record_audit(event_type, target_type, target_id=None, action="", before_data=None,
                 after_data=None, remark=None, operator=None, *, session=None,
                 operator_payload=None, correlation_id=None, metadata=None):
    """Append an event, without committing the caller's transaction.

    A failed audit insert fails the business mutation. The legacy standalone call
    still owns its transaction but no longer silently discards insertion errors.
    """
    payload = operator_payload if operator_payload is not None else operator
    if payload is None:
        payload = (get_token_payload() or {}) if has_request_context() else {}
    payload = payload or {}
    roles = get_payload_roles(payload)
    # Keep the existing table and old snapshots readable. Metadata is namespaced
    # inside the after snapshot and stripped out by the serializer.
    meta = {**(metadata or {}), "schema_version": 2,
            "correlation_id": _correlation_id(session, correlation_id)}
    after = dict(after_data) if isinstance(after_data, dict) else {"value": after_data}
    after[META_KEY] = meta
    entry = AuditLogTable(
        event_type=event_type, target_type=target_type,
        target_id=str(target_id) if target_id is not None else None, action=action,
        operator_id=payload.get("user_id") or payload.get("id"),
        operator_name=payload.get("name") or payload.get("username") or payload.get("phone"),
        operator_role=",".join(sorted(roles)), before_data=_json_dump(before_data),
        after_data=_json_dump(after), remark=remark,
        ip=request.remote_addr if has_request_context() else None,
        create_date=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    if session is not None:
        session.add(entry)
        session.flush()
        return _serialize_audit_log(entry)
    with SessionFactory() as owned_session:
        owned_session.add(entry)
        owned_session.commit()
        return _serialize_audit_log(entry)


def _serialize_audit_log(row):
    before = _parse_json_value(row.before_data)
    after = _parse_json_value(row.after_data)
    metadata = after.pop(META_KEY, {}) if isinstance(after, dict) else {}
    if metadata and isinstance(after, dict) and set(after) == {"value"}:
        after = after["value"]
    return {
        "id": row.id, "event_type": row.event_type, "target_type": row.target_type,
        "target_id": row.target_id, "action": row.action,
        "operator_id": row.operator_id, "operator_name": row.operator_name,
        "operator_role": row.operator_role, "before_data": before, "after_data": after,
        "remark": row.remark, "ip": row.ip, "create_date": row.create_date,
        "metadata": metadata, "correlation_id": metadata.get("correlation_id"),
        "changes": field_changes(before, after), "legacy": not bool(metadata),
    }


def load_audit_logs(page=1, page_size=10, sort_field="create_date", sort_desc=True,
                    event_type=None, target_type=None, target_id=None, action=None,
                    operator_name=None, date_from=None, date_to=None, query_text=None):
    page, page_size = max(int(page or 1), 1), min(max(int(page_size or 10), 1), 200)
    with SessionFactory() as session:
        query = session.query(AuditLogTable)
        for field, value in (("event_type", event_type), ("target_type", target_type),
                             ("target_id", target_id), ("action", action)):
            if value is not None and value != "":
                query = query.filter(getattr(AuditLogTable, field) == str(value))
        if operator_name:
            query = query.filter(AuditLogTable.operator_name.contains(operator_name, autoescape=True))
        if date_from:
            query = query.filter(AuditLogTable.create_date >= date_from)
        if date_to:
            query = query.filter(AuditLogTable.create_date <= (date_to + " 23:59:59" if len(date_to) == 10 else date_to))
        if query_text:
            query = query.filter(or_(*[getattr(AuditLogTable, field).contains(query_text, autoescape=True)
                                       for field in ("target_id", "remark", "operator_name", "before_data", "after_data")]))
        total = query.count()
        column = AUDIT_LOG_SORT_FIELDS.get(sort_field, AuditLogTable.create_date)
        rows = query.order_by(column.desc() if sort_desc else column.asc(),
                              AuditLogTable.id.desc() if sort_desc else AuditLogTable.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"items": [_serialize_audit_log(row) for row in rows], "total": total,
                "page": page, "page_size": page_size}
