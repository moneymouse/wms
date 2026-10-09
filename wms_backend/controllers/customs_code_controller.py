"""Customs code mapping management APIs."""

import time

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from Auth import allow, verify
from data.database import SessionFactory
from data.DB import CustomsCodeTable

customs_code_bp = Blueprint("customs_code", __name__, url_prefix="/api")


def _serialize(record: CustomsCodeTable) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "code": record.code,
        "create_date": record.create_date,
        "update_date": record.update_date,
    }


def _normalize_item(item, index: int | None = None):
    prefix = f"第 {index} 项" if index is not None else ""
    if not isinstance(item, dict):
        return None, f"{prefix}格式不正确"
    name = str(item.get("name") or "").strip()
    code = str(item.get("code") or "").strip()
    if not name:
        return None, f"{prefix}品名不能为空"
    if not code:
        return None, f"{prefix}海关编码不能为空"
    if len(name) > 256:
        return None, f"{prefix}品名不能超过 256 个字符"
    if len(code) > 64:
        return None, f"{prefix}海关编码不能超过 64 个字符"
    return {"name": name, "code": code}, None


def _find_duplicate(session, name: str, exclude_id: int | None = None):
    query = session.query(CustomsCodeTable).filter(
        func.lower(CustomsCodeTable.name) == name.casefold()
    )
    if exclude_id is not None:
        query = query.filter(CustomsCodeTable.id != exclude_id)
    return query.first()


@customs_code_bp.get("/customs-codes")
@verify
def get_customs_codes():
    with SessionFactory() as session:
        records = session.query(CustomsCodeTable).order_by(CustomsCodeTable.name.asc()).all()
        data = [_serialize(record) for record in records]
    return jsonify({"code": 200, "data": data})


@customs_code_bp.post("/customs-codes")
@verify
@allow(role="admin")
def create_customs_code():
    item, error = _normalize_item(request.get_json(silent=True) or {})
    if error:
        return jsonify({"code": 400, "msg": error}), 400

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        if _find_duplicate(session, item["name"]):
            return jsonify({"code": 409, "msg": "该品名的海关编码已存在"}), 409
        record = CustomsCodeTable(
            name=item["name"],
            code=item["code"],
            create_date=now,
            update_date=now,
        )
        session.add(record)
        session.commit()
        return jsonify({"code": 200, "data": _serialize(record)})


@customs_code_bp.post("/customs-codes/import")
@verify
@allow(role="admin")
def import_customs_codes():
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"code": 400, "msg": "items 必须为非空列表"}), 400

    normalized_items = []
    for index, raw_item in enumerate(items, start=1):
        item, error = _normalize_item(raw_item, index=index)
        if error:
            return jsonify({"code": 400, "msg": error}), 400
        normalized_items.append(item)

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        existing = {
            record.name.casefold(): record
            for record in session.query(CustomsCodeTable).all()
        }
        seen = set()
        created_count = 0
        updated_count = 0
        skipped = []

        for item in normalized_items:
            normalized_name = item["name"].casefold()
            if normalized_name in seen:
                skipped.append({**item, "reason": "duplicate_in_file"})
                continue
            seen.add(normalized_name)

            record = existing.get(normalized_name)
            if record is None:
                session.add(
                    CustomsCodeTable(
                        name=item["name"],
                        code=item["code"],
                        create_date=now,
                        update_date=now,
                    )
                )
                created_count += 1
            elif record.code == item["code"]:
                skipped.append({**item, "reason": "unchanged"})
            else:
                record.name = item["name"]
                record.code = item["code"]
                record.update_date = now
                updated_count += 1

        session.commit()

    return jsonify(
        {
            "code": 200,
            "data": {
                "created_count": created_count,
                "updated_count": updated_count,
                "skipped_count": len(skipped),
                "skipped": skipped,
            },
        }
    )


@customs_code_bp.put("/customs-codes/<int:record_id>")
@verify
@allow(role="admin")
def update_customs_code(record_id: int):
    item, error = _normalize_item(request.get_json(silent=True) or {})
    if error:
        return jsonify({"code": 400, "msg": error}), 400

    with SessionFactory() as session:
        record = session.query(CustomsCodeTable).filter(CustomsCodeTable.id == record_id).first()
        if record is None:
            return jsonify({"code": 404, "msg": "海关编码映射不存在"}), 404
        if _find_duplicate(session, item["name"], exclude_id=record_id):
            return jsonify({"code": 409, "msg": "该品名的海关编码已存在"}), 409
        record.name = item["name"]
        record.code = item["code"]
        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()
        return jsonify({"code": 200, "data": _serialize(record)})


@customs_code_bp.delete("/customs-codes/<int:record_id>")
@verify
@allow(role="admin")
def delete_customs_code(record_id: int):
    with SessionFactory() as session:
        record = session.query(CustomsCodeTable).filter(CustomsCodeTable.id == record_id).first()
        if record is None:
            return jsonify({"code": 404, "msg": "海关编码映射不存在"}), 404
        session.delete(record)
        session.commit()
    return jsonify({"code": 200, "msg": "已删除"})
