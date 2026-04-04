from flask import Blueprint, jsonify

from Auth import verify, allow
from utils.log import load_log

log_bp = Blueprint("log", __name__, url_prefix="/api")


@log_bp.get("/logs")
@verify
@allow(role="admin")
def get_logs():
    try:
        return jsonify({"code": 200, "data": load_log()})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"加载日志失败: {str(e)}"}), 500
