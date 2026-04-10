"""Work detail and finance settlement APIs."""

from flask import Blueprint, jsonify, request

from Auth import allow, get_token_payload, verify
from services import work_finance_service

work_finance_bp = Blueprint("work_finance", __name__, url_prefix="/api")

WORK_DETAIL_ROLES = ["admin", "finance", "worker"]
FINANCE_ROLES = ["admin", "finance"]


@work_finance_bp.get("/work/workers")
@verify
@allow(role=FINANCE_ROLES)
def get_workers():
    """获取操作人员列表（财务/管理员）。"""
    workers = work_finance_service.get_workers()
    return jsonify({"code": 200, "data": workers})


@work_finance_bp.get("/work/details")
@verify
@allow(role=WORK_DETAIL_ROLES)
def get_work_details():
    """获取工作详情，worker 仅可查看自己。"""
    payload = get_token_payload() or {}
    role = payload.get("role")
    current_user_id = payload.get("user_id")

    month = request.args.get("month")
    requested_worker_id = request.args.get("worker_id", type=int)

    if role == "worker":
        worker_id = current_user_id
    else:
        worker_id = requested_worker_id or current_user_id

    if worker_id is None:
        return jsonify({"code": 400, "msg": "worker_id is required"}), 400

    try:
        result = work_finance_service.get_worker_work_details(
            worker_id=worker_id, month=month
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/work/bonus-estimate")
@verify
@allow(role=WORK_DETAIL_ROLES)
def get_bonus_estimate():
    """获取预计奖金，worker 仅可查看自己。"""
    payload = get_token_payload() or {}
    role = payload.get("role")
    current_user_id = payload.get("user_id")

    month = request.args.get("month")
    requested_worker_id = request.args.get("worker_id", type=int)

    if role == "worker":
        worker_id = current_user_id
    else:
        worker_id = requested_worker_id or current_user_id

    if worker_id is None:
        return jsonify({"code": 400, "msg": "worker_id is required"}), 400

    try:
        result = work_finance_service.get_bonus_estimate(
            worker_id=worker_id, month=month
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@work_finance_bp.get("/finance/bonus-rates")
@verify
@allow(role=FINANCE_ROLES)
def get_bonus_rates():
    """获取 1~4 人合打奖金基数。"""
    rates = work_finance_service.get_bonus_rates()
    return jsonify({"code": 200, "data": rates})


@work_finance_bp.put("/finance/bonus-rates")
@verify
@allow(role=FINANCE_ROLES)
def update_bonus_rates():
    """更新奖金基数。"""
    payload = get_token_payload() or {}
    operator_id = payload.get("user_id")

    body = request.get_json() or {}
    rates_body = body.get("rates", body)

    rates = {}
    for team_size in range(1, 5):
        raw_value = rates_body.get(str(team_size), rates_body.get(team_size))
        if raw_value is None:
            return (
                jsonify(
                    {"code": 400, "msg": f"rate for team_size {team_size} is required"}
                ),
                400,
            )
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return (
                jsonify(
                    {
                        "code": 400,
                        "msg": f"rate for team_size {team_size} must be numeric",
                    }
                ),
                400,
            )
        if value < 0:
            return (
                jsonify(
                    {"code": 400, "msg": f"rate for team_size {team_size} must be >= 0"}
                ),
                400,
            )
        rates[team_size] = value

    result = work_finance_service.set_bonus_rates(rates=rates, operator_id=operator_id)
    return jsonify({"code": 200, "data": result, "msg": "bonus rates updated"})


@work_finance_bp.get("/finance/worker-bonus-overview")
@verify
@allow(role=FINANCE_ROLES)
def get_worker_bonus_overview():
    """获取工人预计奖金汇总。"""
    month = request.args.get("month")
    worker_id = request.args.get("worker_id", type=int)

    try:
        result = work_finance_service.get_bonus_overview(
            month=month, worker_id=worker_id
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
