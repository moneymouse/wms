import json
import time
from functools import wraps

from flask import request
from sqlalchemy import Column, Integer, String, Text

from Auth import get_token_payload
from data.database import Base, SessionFactory


# ---------------------------------------------------------------------------
# ORM table definition
# ---------------------------------------------------------------------------


class OperationLogTable(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(64))
    pc_name = Column(String(256))
    user_name = Column(String(128))
    user_role = Column(String(32))
    desc = Column(String(512))
    kwargs = Column(Text)  # JSON-serialised dict
    json_body = Column(Text)  # JSON-serialised request body
    method = Column(String(16))
    log_date = Column(String(32))


OPERATION_LOG_SORT_FIELDS = {
    "id": OperationLogTable.id,
    "log_date": OperationLogTable.log_date,
    "pc_name": OperationLogTable.pc_name,
    "user_name": OperationLogTable.user_name,
    "user_role": OperationLogTable.user_role,
    "method": OperationLogTable.method,
}


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def log(desc: str = "", is_json: bool = False):
    def wrapper(func):
        @wraps(func)
        def wrap_function(*args, **kwargs):
            json_body: dict = {}
            if is_json or request.is_json:
                try:
                    json_body = json.loads(request.data)
                except Exception:
                    json_body = {}

            token_payload = get_token_payload() or {}
            pc_name = token_payload.get("hostname", "")
            user_name = token_payload.get("name", "") or ""
            user_role = token_payload.get("role", "") or ""

            s = SessionFactory()
            try:
                entry = OperationLogTable(
                    ip=request.remote_addr,
                    pc_name=pc_name,
                    user_name=user_name,
                    user_role=user_role,
                    desc=desc,
                    kwargs=json.dumps(kwargs, ensure_ascii=False),
                    json_body=json.dumps(json_body, ensure_ascii=False),
                    method=request.method,
                    log_date=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                s.add(entry)
                s.commit()
            except Exception:
                s.rollback()
            finally:
                s.close()

            return func(*args, **kwargs)

        return wrap_function

    return wrapper


# ---------------------------------------------------------------------------
# Log reader (used by GET /api/logs)
# ---------------------------------------------------------------------------


def _serialize_operation_log(row: OperationLogTable) -> dict:
    try:
        kwargs_val = json.loads(row.kwargs) if row.kwargs else {}
    except Exception:
        kwargs_val = {}
    try:
        json_val = json.loads(row.json_body) if row.json_body else {}
    except Exception:
        json_val = {}
    return {
        "id": row.id,
        "ip": row.ip,
        "pc_name": row.pc_name,
        "user_name": row.user_name,
        "user_role": row.user_role,
        "desc": row.desc,
        "kwargs": kwargs_val,
        "json": json_val,
        "method": row.method,
        "log_date": row.log_date,
    }


def load_log(
    page: int = 1,
    page_size: int = 10,
    sort_field: str = "log_date",
    sort_desc: bool = True,
) -> dict:
    s = SessionFactory()
    try:
        query = s.query(OperationLogTable)
        total = query.count()
        sort_column = OPERATION_LOG_SORT_FIELDS.get(
            sort_field, OperationLogTable.log_date
        )
        order_by = sort_column.desc() if sort_desc else sort_column.asc()
        id_order = OperationLogTable.id.desc() if sort_desc else OperationLogTable.id.asc()
        rows = (
            query.order_by(order_by, id_order)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [_serialize_operation_log(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        s.close()
