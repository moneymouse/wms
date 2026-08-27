"""Goods name management APIs."""

import time

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from Auth import allow, verify
from data.database import SessionFactory
from data.DB import GoodsNameTable

goods_name_bp = Blueprint("goods_name", __name__, url_prefix="/api")


def _serialize(record: GoodsNameTable) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "lang": record.lang,
        "category": record.category,
        "create_date": record.create_date,
        "update_date": record.update_date,
    }


def _normalize_category(value) -> str | None:
    category = str(value or "").strip()
    return category or None


def _find_duplicate(session, name: str, lang: str, exclude_id: int | None = None):
    query = session.query(GoodsNameTable).filter(
        GoodsNameTable.lang == lang,
        func.lower(GoodsNameTable.name) == name.casefold(),
    )
    if exclude_id is not None:
        query = query.filter(GoodsNameTable.id != exclude_id)
    return query.first()


@goods_name_bp.get("/goods-names")
@verify
def get_goods_names():
    """获取品名列表，支持按语言筛选。所有已登录用户可访问。"""
    lang = request.args.get("lang", "").strip().lower()

    with SessionFactory() as session:
        query = session.query(GoodsNameTable)
        if lang in ("cn", "en"):
            query = query.filter(GoodsNameTable.lang == lang)
        records = query.order_by(GoodsNameTable.id.desc()).all()
        data = [_serialize(record) for record in records]

    return jsonify({"code": 200, "data": data})


@goods_name_bp.post("/goods-names")
@verify
@allow(role="admin")
def create_goods_name():
    """新增品名。仅管理员。"""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    lang = str(body.get("lang") or "").strip().lower()
    category = _normalize_category(body.get("category")) if lang == "en" else None

    if not name:
        return jsonify({"code": 400, "msg": "品名不能为空"}), 400
    if len(name) > 256:
        return jsonify({"code": 400, "msg": "品名不能超过 256 个字符"}), 400
    if lang not in ("cn", "en"):
        return jsonify({"code": 400, "msg": "lang 必须为 cn 或 en"}), 400
    if category and len(category) > 128:
        return jsonify({"code": 400, "msg": "子标题不能超过 128 个字符"}), 400

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        if _find_duplicate(session, name, lang):
            return jsonify({"code": 409, "msg": "品名已存在"}), 409

        record = GoodsNameTable(
            name=name,
            lang=lang,
            category=category,
            create_date=now,
            update_date=now,
        )
        session.add(record)
        session.commit()
        return jsonify({"code": 200, "data": _serialize(record)})


@goods_name_bp.post("/goods-names/import")
@verify
@allow(role="admin")
def import_goods_names():
    """批量导入带分类的英文品名。仅管理员。"""
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"code": 400, "msg": "items 必须为非空列表"}), 400

    normalized_items = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return jsonify({"code": 400, "msg": f"第 {index} 项格式不正确"}), 400
        name = str(item.get("name") or "").strip()
        category = _normalize_category(item.get("category"))
        if not name:
            return jsonify({"code": 400, "msg": f"第 {index} 项品名不能为空"}), 400
        if not category:
            return jsonify({"code": 400, "msg": f"第 {index} 项子标题不能为空"}), 400
        if len(name) > 256:
            return jsonify({"code": 400, "msg": f"第 {index} 项品名不能超过 256 个字符"}), 400
        if len(category) > 128:
            return jsonify({"code": 400, "msg": f"第 {index} 项子标题不能超过 128 个字符"}), 400
        normalized_items.append({"name": name, "category": category})

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        existing_names = {
            name.casefold()
            for (name,) in session.query(GoodsNameTable.name)
            .filter(GoodsNameTable.lang == "en")
            .all()
        }
        seen_names = set()
        created_count = 0
        skipped = []

        for item in normalized_items:
            normalized_name = item["name"].casefold()
            if normalized_name in existing_names:
                skipped.append({**item, "reason": "already_exists"})
                continue
            if normalized_name in seen_names:
                skipped.append({**item, "reason": "duplicate_in_file"})
                continue

            seen_names.add(normalized_name)
            session.add(
                GoodsNameTable(
                    name=item["name"],
                    lang="en",
                    category=item["category"],
                    create_date=now,
                    update_date=now,
                )
            )
            created_count += 1

        session.commit()

    return jsonify(
        {
            "code": 200,
            "data": {
                "created_count": created_count,
                "skipped_count": len(skipped),
                "skipped": skipped,
            },
        }
    )


@goods_name_bp.put("/goods-names/<int:record_id>")
@verify
@allow(role="admin")
def update_goods_name(record_id: int):
    """修改品名。仅管理员。"""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()

    if not name:
        return jsonify({"code": 400, "msg": "品名不能为空"}), 400
    if len(name) > 256:
        return jsonify({"code": 400, "msg": "品名不能超过 256 个字符"}), 400

    with SessionFactory() as session:
        record = session.query(GoodsNameTable).filter(GoodsNameTable.id == record_id).first()
        if record is None:
            return jsonify({"code": 404, "msg": "品名不存在"}), 404
        if _find_duplicate(session, name, record.lang, exclude_id=record_id):
            return jsonify({"code": 409, "msg": "品名已存在"}), 409

        category = record.category
        if record.lang == "en" and "category" in body:
            category = _normalize_category(body.get("category"))
            if category and len(category) > 128:
                return jsonify({"code": 400, "msg": "子标题不能超过 128 个字符"}), 400

        record.name = name
        record.category = category if record.lang == "en" else None
        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()
        return jsonify({"code": 200, "data": _serialize(record)})


@goods_name_bp.delete("/goods-names/<int:record_id>")
@verify
@allow(role="admin")
def delete_goods_name(record_id: int):
    """删除品名。仅管理员。"""
    with SessionFactory() as session:
        record = session.query(GoodsNameTable).filter(GoodsNameTable.id == record_id).first()
        if record is None:
            return jsonify({"code": 404, "msg": "品名不存在"}), 404

        session.delete(record)
        session.commit()
        return jsonify({"code": 200, "msg": "已删除"})
