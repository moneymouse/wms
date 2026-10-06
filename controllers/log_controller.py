from flask import Blueprint, jsonify, request

from Auth import verify, allow
from utils.audit import load_audit_logs
from utils.log import load_log

log_bp = Blueprint("log", __name__, url_prefix="/api")


def _get_log_query_args(default_sort_field: str) -> dict:
    page = request.args.get("p", 1, type=int)
    page_size = request.args.get("s", 10, type=int)
    sort_field = request.args.get("sf", default_sort_field, type=str)
    sort_order = request.args.get("so", 1, type=int)

    page = max(page or 1, 1)
    page_size = min(max(page_size or 10, 1), 200)
    return {
        "page": page,
        "page_size": page_size,
        "sort_field": sort_field,
        "sort_desc": sort_order != 0,
    }


def _jsonify_paginated(result: dict):
    return jsonify({
        "code": 200,
        "data": result["items"],
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@log_bp.get("/logs")
@verify
@allow(role="admin")
def get_logs():
    try:
        result = load_log(**_get_log_query_args("log_date"))
        return _jsonify_paginated(result)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"加载日志失败: {str(e)}"}), 500


@log_bp.get("/audit-logs")
@verify
@allow(role="admin")
def get_audit_logs():
    try:
        filters = {key: request.args[key].strip() for key in
                   ("event_type", "target_type", "target_id", "action", "operator_name", "date_from", "date_to")
                   if request.args.get(key)}
        if request.args.get("q"):
            filters["query_text"] = request.args["q"].strip()
        result = load_audit_logs(**_get_log_query_args("create_date"), **filters)
        return _jsonify_paginated(result)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"加载审计日志失败: {str(e)}"}), 500
