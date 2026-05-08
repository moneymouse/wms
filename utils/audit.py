import json
import time

from flask import request

from Auth import get_payload_roles, get_token_payload
from data.database import SessionFactory
from data.DB import AuditLogTable


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


def load_audit_logs(limit=500, event_type=None):
    with SessionFactory() as session:
        query = session.query(AuditLogTable)
        if event_type:
            query = query.filter(AuditLogTable.event_type == event_type)
        rows = query.order_by(AuditLogTable.create_date.desc()).limit(limit).all()
        result = []
        for row in rows:
            def parse(raw):
                try:
                    return json.loads(raw) if raw else None
                except Exception:
                    return raw

            result.append({
                "id": row.id,
                "event_type": row.event_type,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "action": row.action,
                "operator_id": row.operator_id,
                "operator_name": row.operator_name,
                "operator_role": row.operator_role,
                "before_data": parse(row.before_data),
                "after_data": parse(row.after_data),
                "remark": row.remark,
                "ip": row.ip,
                "create_date": row.create_date,
            })
        return result
