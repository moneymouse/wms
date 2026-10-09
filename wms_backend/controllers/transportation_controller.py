import json
import time

from flask import Blueprint, jsonify, request

from Auth import verify, allow, get_token_payload
from data.database import SessionFactory
from data.DB import TransportationCostVersionTable, TransportationModeTable
from utils.audit import record_audit

transportation_bp = Blueprint("transportation", __name__, url_prefix="/api")

COST_ROLES = ["admin", "store_manager"]


def _mode_dict(mode):
    return {
        "id": mode.id,
        "name": mode.name,
        "channel_group": mode.channel_group,
        "cost": mode.cost,
        "min_price": mode.min_price,
        "create_date": mode.create_date,
        "update_date": mode.update_date,
    }


def _operator_info():
    payload = get_token_payload() or {}
    return {
        "id": payload.get("user_id") or payload.get("id"),
        "name": payload.get("name") or payload.get("username") or payload.get("phone"),
        "payload": payload,
    }


def _add_cost_version(session, mode, change_type, remark=None):
    max_version = (
        session.query(TransportationCostVersionTable.version_no)
        .filter(TransportationCostVersionTable.transportation_mode_id == mode.id)
        .order_by(TransportationCostVersionTable.version_no.desc())
        .first()
    )
    operator = _operator_info()
    version = TransportationCostVersionTable(
        transportation_mode_id=mode.id,
        version_no=(max_version[0] if max_version else 0) + 1,
        name=mode.name,
        channel_group=mode.channel_group,
        cost=mode.cost,
        min_price=mode.min_price,
        change_type=change_type,
        remark=remark,
        operator_id=operator["id"],
        operator_name=operator["name"],
        create_date=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    session.add(version)
    return version


@transportation_bp.get("/transportation-modes")
@verify
def get_transportation_modes():
    """获取所有未归档的运输方式列表"""
    with SessionFactory() as session:
        modes = (
            session.query(TransportationModeTable)
            .filter(TransportationModeTable.archive == False)  # noqa: E712
            .order_by(TransportationModeTable.channel_group, TransportationModeTable.name)
            .all()
        )
        return jsonify({
            "code": 200,
            "data": [
                {
                    **_mode_dict(m),
                }
                for m in modes
            ]
        })


@transportation_bp.post("/transportation-modes")
@verify
@allow(role=COST_ROLES)
def create_transportation_mode():
    """创建新的运输方式（管理员）"""
    body = json.loads(request.data)
    name = (body.get("name") or "").strip()
    channel_group = (body.get("channel_group") or "").strip()
    cost = body.get("cost")
    min_price = body.get("min_price")
    remark = body.get("remark")

    if not name:
        return jsonify({"code": 400, "msg": "运输方式名称不能为空"}), 400

    now = time.strftime("%Y-%m-%d %H:%M")
    with SessionFactory() as session:
        existing = (
            session.query(TransportationModeTable)
            .filter(TransportationModeTable.name == name)
            .first()
        )
        if existing:
            return jsonify({"code": 409, "msg": "该运输方式已存在"}), 409

        mode = TransportationModeTable(
            name=name,
            channel_group=channel_group,
            cost=float(cost) if cost is not None else 0,
            min_price=float(min_price) if min_price is not None else 0,
            create_date=now,
            update_date=now,
        )
        session.add(mode)
        session.flush()
        version = _add_cost_version(session, mode, "create", remark)
        record_audit(
            event_type="transportation_cost",
            target_type="transportation_mode",
            target_id=mode.id,
            action="create",
            after_data={**_mode_dict(mode), "version_no": version.version_no},
            remark=remark,
            session=session,
        )
        session.commit()
        return jsonify({
            "code": 200,
            "msg": "创建成功",
            "data": _mode_dict(mode),
        })


@transportation_bp.put("/transportation-modes/<int:mode_id>")
@verify
@allow(role=COST_ROLES)
def update_transportation_mode(mode_id):
    """更新运输方式（管理员）"""
    body = json.loads(request.data)
    name = body.get("name")
    channel_group = body.get("channel_group")
    cost = body.get("cost")
    min_price = body.get("min_price")
    remark = body.get("remark")

    with SessionFactory() as session:
        mode = (
            session.query(TransportationModeTable)
            .filter(TransportationModeTable.id == mode_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if mode is None:
            return jsonify({"code": 404, "msg": "运输方式不存在"}), 404

        before_data = _mode_dict(mode)

        if name is not None:
            name = name.strip()
            if not name:
                return jsonify({"code": 400, "msg": "运输方式名称不能为空"}), 400
            existing = (
                session.query(TransportationModeTable)
                .filter(
                    TransportationModeTable.name == name,
                    TransportationModeTable.id != mode_id,
                )
                .first()
            )
            if existing:
                return jsonify({"code": 409, "msg": "该运输方式名称已被使用"}), 409
            mode.name = name

        if channel_group is not None:
            mode.channel_group = channel_group.strip()
        if cost is not None:
            mode.cost = float(cost)
        if min_price is not None:
            mode.min_price = float(min_price)

        mode.update_date = time.strftime("%Y-%m-%d %H:%M")
        version = _add_cost_version(session, mode, "update", remark)
        record_audit(
            event_type="transportation_cost",
            target_type="transportation_mode",
            target_id=mode.id,
            action="update",
            before_data=before_data,
            after_data={**_mode_dict(mode), "version_no": version.version_no},
            remark=remark,
            session=session,
        )
        session.commit()
        return jsonify({
            "code": 200,
            "msg": "更新成功",
            "data": _mode_dict(mode),
        })


@transportation_bp.delete("/transportation-modes/<int:mode_id>")
@verify
@allow(role=COST_ROLES)
def delete_transportation_mode(mode_id):
    """删除运输方式（管理员，硬删除）"""
    with SessionFactory() as session:
        mode = (
            session.query(TransportationModeTable)
            .filter(TransportationModeTable.id == mode_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if mode is None:
            return jsonify({"code": 404, "msg": "运输方式不存在"}), 404

        before_data = _mode_dict(mode)
        mode.archive = True
        mode.update_date = time.strftime("%Y-%m-%d %H:%M")
        version = _add_cost_version(session, mode, "archive")
        record_audit(
            event_type="transportation_cost",
            target_type="transportation_mode",
            target_id=mode.id,
            action="archive",
            before_data=before_data,
            after_data={**_mode_dict(mode), "version_no": version.version_no},
            session=session,
        )
        session.commit()
        return jsonify({"code": 200, "msg": "删除成功"})


@transportation_bp.get("/transportation-modes/<int:mode_id>/cost-versions")
@verify
@allow(role=COST_ROLES)
def get_transportation_cost_versions(mode_id):
    with SessionFactory() as session:
        rows = (
            session.query(TransportationCostVersionTable)
            .filter(TransportationCostVersionTable.transportation_mode_id == mode_id)
            .order_by(TransportationCostVersionTable.version_no.desc())
            .all()
        )
        return jsonify({
            "code": 200,
            "data": [
                {
                    "id": row.id,
                    "transportation_mode_id": row.transportation_mode_id,
                    "version_no": row.version_no,
                    "name": row.name,
                    "channel_group": row.channel_group,
                    "cost": row.cost,
                    "min_price": row.min_price,
                    "change_type": row.change_type,
                    "remark": row.remark,
                    "operator_id": row.operator_id,
                    "operator_name": row.operator_name,
                    "create_date": row.create_date,
                }
                for row in rows
            ],
        })
