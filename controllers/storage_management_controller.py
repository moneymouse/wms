"""Administrator controls for the private paper photo storage."""

from functools import wraps
from io import BytesIO

from flask import Blueprint, current_app, jsonify, request, send_file

from Auth import allow, verify
from services import storage_management_service as service
from utils.log import log


storage_management_bp = Blueprint("storage_management", __name__, url_prefix="/api/storage")


def handled(fn):
    @wraps(fn)
    def wrapper(**kwargs):
        try:
            return fn(**kwargs)
        except service.StorageManagementError as exc:
            return jsonify({"code": exc.status, "msg": str(exc)}), exc.status
        except Exception:
            current_app.logger.exception("Paper photo storage operation failed")
            return jsonify({"code": 500, "msg": "存储操作失败，请刷新状态后重试"}), 500
    return wrapper


@storage_management_bp.get("/summary")
@verify
@allow(role=service.STORAGE_ROLES)
@handled
def summary():
    return jsonify({"code": 200, "data": service.storage_summary(request.args.get("days")), "msg": "success"})


@storage_management_bp.get("/packing-lists")
@verify
@allow(role=service.STORAGE_ROLES)
@handled
def packing_lists():
    result = service.list_packing_list_photos(
        page=request.args.get("page"), page_size=request.args.get("page_size"),
        q=request.args.get("q"), days=request.args.get("days"),
    )
    return jsonify({"code": 200, "data": result, "msg": "success"})


@storage_management_bp.get("/intakes/<string:uid>/photos")
@verify
@allow(role=service.STORAGE_ROLES)
@handled
def intake_photos(uid):
    return jsonify({"code": 200, "data": service.list_intake_photos(uid), "msg": "success"})


@storage_management_bp.get("/intakes/<string:uid>/photos/<string:photo_uid>")
@verify
@allow(role=service.STORAGE_ROLES)
@handled
def intake_photo(uid, photo_uid):
    data, mime_type, filename = service.get_intake_photo(uid, photo_uid)
    response = send_file(BytesIO(data), mimetype=mime_type, download_name=filename, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@storage_management_bp.delete("/intakes/<string:uid>/photos")
@verify
@allow(role=service.STORAGE_ROLES)
@log(desc="Delete paper intake source photos.", is_json=True)
@handled
def delete_intake_photos(uid):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.StorageManagementError("请求须为JSON对象")
    result = service.delete_intake_photos(uid, data.get("days"))
    message = "照片记录已清理，部分文件待重试清理" if result["pending_files"] else "success"
    return jsonify({"code": 200, "data": result, "msg": message})


@storage_management_bp.delete("/packing-lists/<string:uid>/photos")
@verify
@allow(role=service.STORAGE_ROLES)
@log(desc="Delete shipped packing list source photos.", is_json=True)
@handled
def delete_photos(uid):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.StorageManagementError("请求须为JSON对象")
    result = service.delete_packing_list_photos(uid, data.get("days"))
    message = "照片记录已清理，部分文件待重试清理" if result["pending_files"] else "success"
    return jsonify({"code": 200, "data": result, "msg": message})


@storage_management_bp.post("/cleanup")
@verify
@allow(role=service.STORAGE_ROLES)
@log(desc="Retry pending paper photo file cleanup.")
@handled
def cleanup():
    return jsonify({"code": 200, "data": service.retry_photo_cleanup(), "msg": "success"})
