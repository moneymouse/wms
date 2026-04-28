"""Goods name management APIs."""

import time

from flask import Blueprint, jsonify, request

from Auth import allow, verify
from data.database import SessionFactory
from data.DB import GoodsNameTable

goods_name_bp = Blueprint("goods_name", __name__, url_prefix="/api")


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

        data = [
            {
                "id": r.id,
                "name": r.name,
                "lang": r.lang,
                "create_date": r.create_date,
                "update_date": r.update_date,
            }
            for r in records
        ]

    return jsonify({"code": 200, "data": data})


@goods_name_bp.post("/goods-names")
@verify
@allow(role="admin")
def create_goods_name():
    """新增品名。仅管理员。"""
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()
    lang = (body.get("lang") or "").strip().lower()

    if not name:
        return jsonify({"code": 400, "msg": "品名不能为空"}), 400
    if lang not in ("cn", "en"):
        return jsonify({"code": 400, "msg": "lang 必须为 cn 或 en"}), 400

    now = time.strftime("%Y-%m-%d %H:%M")
    record = GoodsNameTable(name=name, lang=lang, create_date=now, update_date=now)

    with SessionFactory() as session:
        session.add(record)
        session.commit()
        return jsonify(
            {
                "code": 200,
                "data": {
                    "id": record.id,
                    "name": record.name,
                    "lang": record.lang,
                    "create_date": record.create_date,
                    "update_date": record.update_date,
                },
            }
        )


@goods_name_bp.put("/goods-names/<int:record_id>")
@verify
@allow(role="admin")
def update_goods_name(record_id: int):
    """修改品名。仅管理员。"""
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()

    if not name:
        return jsonify({"code": 400, "msg": "品名不能为空"}), 400

    with SessionFactory() as session:
        record = (
            session.query(GoodsNameTable)
            .filter(GoodsNameTable.id == record_id)
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "品名不存在"}), 404

        record.name = name
        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()

        return jsonify(
            {
                "code": 200,
                "data": {
                    "id": record.id,
                    "name": record.name,
                    "lang": record.lang,
                    "create_date": record.create_date,
                    "update_date": record.update_date,
                },
            }
        )


@goods_name_bp.delete("/goods-names/<int:record_id>")
@verify
@allow(role="admin")
def delete_goods_name(record_id: int):
    """删除品名。仅管理员。"""
    with SessionFactory() as session:
        record = (
            session.query(GoodsNameTable)
            .filter(GoodsNameTable.id == record_id)
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "品名不存在"}), 404

        session.delete(record)
        session.commit()
        return jsonify({"code": 200, "msg": "已删除"})
