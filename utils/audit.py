import json
import time

from flask import request

from Auth import get_payload_roles, get_token_payload
from data.database import SessionFactory
from data.DB import AuditLogTable


AUDIT_LOG_SORT_FIELDS = {
    "id": AuditLogTable.id,
    "create_date": AuditLogTable.create_date,
    "event_type": AuditLogTable.event_type,
    "action": AuditLogTable.action,
    "target_type": AuditLogTable.target_type,
    "operator_name": AuditLogTable.operator_name,
    "operator_role": AuditLogTable.operator_role,
}


def _json_dump(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def record_audit(
    event_type,
    target_type,
    target_id=None,
    action="",
    before_data=None,
    after_data=None,
    remark=None,
    operator=None,
):
    payload = operator or get_token_payload() or {}
    roles = get_payload_roles(payload)
    entry = AuditLogTable(
        event_type=event_type,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        action=action,
        operator_id=payload.get("user_id") or payload.get("id"),
        operator_name=payload.get("name") or payload.get("username") or payload.get("phone"),
        operator_role=",".join(roles),
        before_data=_json_dump(before_data),
        after_data=_json_dump(after_data),
        remark=remark,
        ip=request.remote_addr if request else None,
        create_date=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    with SessionFactory() as session:
        try:
            session.add(entry)
            session.commit()
        except Exception:
            session.rollback()


def _parse_json_value(raw):
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return raw


def _serialize_audit_log(row: AuditLogTable) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "action": row.action,
        "operator_id": row.operator_id,
        "operator_name": row.operator_name,
        "operator_role": row.operator_role,
        "before_data": _parse_json_value(row.before_data),
        "after_data": _parse_json_value(row.after_data),
        "remark": row.remark,
        "ip": row.ip,
        "create_date": row.create_date,
    }


def load_audit_logs(
    page: int = 1,
    page_size: int = 10,
    sort_field: str = "create_date",
    sort_desc: bool = True,
    event_type=None,
) -> dict:
    with SessionFactory() as session:
        query = session.query(AuditLogTable)
        if event_type:
            query = query.filter(AuditLogTable.event_type == event_type)
        total = query.count()
        sort_column = AUDIT_LOG_SORT_FIELDS.get(sort_field, AuditLogTable.create_date)
        order_by = sort_column.desc() if sort_desc else sort_column.asc()
        id_order = AuditLogTable.id.desc() if sort_desc else AuditLogTable.id.asc()
        rows = (
            query.order_by(order_by, id_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [_serialize_audit_log(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
