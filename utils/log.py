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


def load_log() -> list:
    s = SessionFactory()
    try:
        rows = (
            s.query(OperationLogTable).order_by(OperationLogTable.log_date.desc()).all()
        )
        result = []
        for row in rows:
            try:
                kwargs_val = json.loads(row.kwargs) if row.kwargs else {}
            except Exception:
                kwargs_val = {}
            try:
                json_val = json.loads(row.json_body) if row.json_body else {}
            except Exception:
                json_val = {}
            result.append(
                {
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
            )
        return result
    finally:
        s.close()
