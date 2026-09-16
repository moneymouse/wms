"""Work detail and finance settlement APIs."""

from flask import Blueprint, jsonify, request

from Auth import allow, get_payload_roles, get_token_payload, verify
from data.DB import OrderRevisionOpenError
from services import work_finance_service

work_finance_bp = Blueprint("work_finance", __name__, url_prefix="/api")

WORK_DETAIL_ROLES = ["admin", "finance", "worker", "salesperson"]
WORK_BONUS_ROLES = ["admin", "finance", "worker", "salesperson"]
FINANCE_ROLES = ["admin", "finance"]


@work_finance_bp.get("/work/workers")
@verify
def get_workers():
    """获取操作人员列表（财务/管理员）。"""
    roles = request.args.get("roles")
    role_names = (
        [role.strip() for role in roles.split(",") if role.strip()] if roles else None
    )
    workers = work_finance_service.get_workers(role_names=role_names)
    return jsonify({"code": 200, "data": workers})


@work_finance_bp.get("/work/details")
@verify
@allow(role=WORK_DETAIL_ROLES)
def get_work_details():
    """获取工作详情，worker 仅可查看自己。"""
    payload = get_token_payload() or {}
    roles = get_payload_roles(payload)
    current_user_id = payload.get("user_id") or payload.get("id")

    month = request.args.get("month")
    requested_worker_id = request.args.get("worker_id", type=int)

    if "admin" in roles or "finance" in roles:
        worker_id = requested_worker_id or current_user_id
    else:
        worker_id = current_user_id

    if worker_id is None:
        return jsonify({"code": 400, "msg": "worker_id is required"}), 400

    try:
        result = work_finance_service.get_worker_work_details(
            worker_id=worker_id, month=month
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/work/bonus")
@verify
@allow(role=WORK_BONUS_ROLES)
def get_worker_bonus():
    """获取按天、按奖金分项统计的奖金数据。"""
    payload = get_token_payload() or {}
    roles = get_payload_roles(payload)
    current_user_id = payload.get("user_id") or payload.get("id")

    month = request.args.get("month")
    requested_worker_id = request.args.get("worker_id", type=int)

    if "admin" in roles or "finance" in roles:
        worker_id = requested_worker_id or current_user_id
    else:
        worker_id = current_user_id

    if worker_id is None:
        return jsonify({"code": 400, "msg": "worker_id is required"}), 400

    try:
        result = work_finance_service.get_worker_bonus_summary(
            worker_id=worker_id, month=month
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/work/bonus-estimate")
@verify
@allow(role=WORK_BONUS_ROLES)
def get_bonus_estimate():
    """兼容旧路由：返回新奖金统计结构。"""
    payload = get_token_payload() or {}
    roles = get_payload_roles(payload)
    current_user_id = payload.get("user_id") or payload.get("id")

    month = request.args.get("month")
    requested_worker_id = request.args.get("worker_id", type=int)

    if "admin" in roles or "finance" in roles:
        worker_id = requested_worker_id or current_user_id
    else:
        worker_id = current_user_id

    if worker_id is None:
        return jsonify({"code": 400, "msg": "worker_id is required"}), 400

    try:
        result = work_finance_service.get_bonus_estimate(
            worker_id=worker_id, month=month
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/finance/bonus-items")
@verify
@allow(role=FINANCE_ROLES)
def get_bonus_items():
    """获取奖金分项列表。"""
    active_only = request.args.get("active_only", "true").lower() == "true"
    items = work_finance_service.get_bonus_items(active_only=active_only)
    return jsonify({"code": 200, "data": items})


@work_finance_bp.post("/finance/bonus-items")
@verify
@allow(role=FINANCE_ROLES)
def create_bonus_item():
    """创建奖金分项。"""
    payload = get_token_payload() or {}
    operator_id = payload.get("user_id")

    body = request.get_json() or {}
    try:
        item = work_finance_service.create_bonus_item(body, operator_id=operator_id)
        return jsonify({"code": 200, "data": item, "msg": "bonus item created"})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.put("/finance/bonus-items/<int:item_id>")
@verify
@allow(role=FINANCE_ROLES)
def update_bonus_item(item_id: int):
    """更新奖金分项。"""
    payload = get_token_payload() or {}
    operator_id = payload.get("user_id")

    body = request.get_json() or {}
    try:
        item = work_finance_service.update_bonus_item(
            item_id=item_id,
            payload=body,
            operator_id=operator_id,
        )
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400

    if item is None:
        return jsonify({"code": 404, "msg": "bonus item not found"}), 404

    return jsonify({"code": 200, "data": item, "msg": "bonus item updated"})


@work_finance_bp.delete("/finance/bonus-items/<int:item_id>")
@verify
@allow(role=FINANCE_ROLES)
def delete_bonus_item(item_id: int):
    """停用奖金分项（软删除）。"""
    payload = get_token_payload() or {}
    operator_id = payload.get("user_id")

    item = work_finance_service.disable_bonus_item(
        item_id=item_id, operator_id=operator_id
    )
    if item is None:
        return jsonify({"code": 404, "msg": "bonus item not found"}), 404

    return jsonify({"code": 200, "data": item, "msg": "bonus item disabled"})


@work_finance_bp.get("/finance/bonus-allocation/pending-packing-lists")
@verify
@allow(role=FINANCE_ROLES)
def get_pending_bonus_allocation_packing_lists():
    """获取未分配奖金的装箱单列表。"""
    month = request.args.get("month")
    mark_search = request.args.get("q")

    try:
        result = work_finance_service.get_pending_bonus_allocation_packing_lists(
            month=month,
            mark_search=mark_search,
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.put("/finance/bonus-allocation/packing-list/<string:packing_list_uid>")
@verify
@allow(role=FINANCE_ROLES)
def allocate_bonus_for_packing_list(packing_list_uid: str):
    """提交某装箱单的奖金分配。"""
    payload = get_token_payload() or {}
    operator_id = payload.get("user_id")

    body = request.get_json() or {}
    assignments = body.get("assignments") or []

    try:
        result = work_finance_service.assign_bonus_for_packing_list(
            packing_list_uid=packing_list_uid,
            assignments=assignments,
            operator_id=operator_id,
        )
        return jsonify({"code": 200, "data": result, "msg": "bonus allocated"})
    except OrderRevisionOpenError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/finance/worker-bonus-overview")
@verify
@allow(role=FINANCE_ROLES)
def get_worker_bonus_overview():
    """获取工人奖金汇总。"""
    month = request.args.get("month")
    worker_id = request.args.get("worker_id", type=int)

    try:
        result = work_finance_service.get_bonus_overview(
            month=month, worker_id=worker_id
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
