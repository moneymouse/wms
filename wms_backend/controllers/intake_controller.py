"""Authenticated paper uploads checked by their uploader before completion."""
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from Auth import get_token_payload, verify
from services import intake_service as service

intake_bp = Blueprint("intake", __name__, url_prefix="/api/intakes")
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "static/templates/paper-packing-list-a4.pdf"


def handled(fn):
    @wraps(fn)
    def wrapper(**kwargs):
        try:
            return fn(**kwargs)
        except service.IntakeError as exc:
            result = {"code": exc.status, "msg": str(exc)}
            if exc.data is not None:
                result["data"] = exc.data
            return jsonify(result), exc.status
        except Exception:
            from flask import current_app
            current_app.logger.exception("Paper intake request failed")
            return jsonify({"code": 500, "msg": "操作失败，数据未确认；请刷新查看后重试"}), 500
    return wrapper


def payload():
    return get_token_payload() or {}


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise service.IntakeError("请求须为JSON对象")
    return data


@intake_bp.post("")
@verify
@handled
def submit():
    service.require_role(payload())
    if request.content_length and request.content_length > 25 * 1024 * 1024:
        raise service.IntakeError("照片合计不能超过24MB，请压缩或拆分回传", 413)
    record = service.create_intake(payload(), request.files.getlist("photos"), request.form)
    return jsonify({"code": 200, "data": record, "msg": "照片已暂存，请检查识别结果后完成上传"}), 201


@intake_bp.get("")
@verify
@handled
def list_records():
    return jsonify({"code": 200, "data": service.list_intakes(payload(), packing_list_uid=request.args.get("packing_list_uid"))})


@intake_bp.get("/<uid>")
@verify
@handled
def detail(uid):
    return jsonify({"code": 200, "data": service.get_intake(payload(), uid)})


@intake_bp.delete("/<uid>")
@verify
@handled
def delete(uid):
    data = body()
    return jsonify({"code": 200, "data": service.delete_intake(payload(), uid, data.get("version"))})


@intake_bp.get("/workers")
@verify
@handled
def workers():
    return jsonify({"code": 200, "data": service.list_workers(payload())})


@intake_bp.get("/template")
@verify
@handled
def paper_template():
    service.require_role(payload())
    if not TEMPLATE_PATH.is_file():
        raise service.IntakeError("装箱单模板暂不可用，请联系管理员", 503)
    response = send_file(TEMPLATE_PATH, mimetype="application/pdf", as_attachment=True, download_name="paper-packing-list-a4.pdf", max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@intake_bp.get("/my-packing-lists")
@verify
@handled
def my_packing_lists():
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except ValueError:
        raise service.IntakeError("分页参数须为整数")
    return jsonify({"code": 200, "data": service.my_packing_lists(payload(), page, page_size, request.args.get("mark"), request.args.get("status"))})


@intake_bp.get("/<uid>/photos/<photo_uid>")
@verify
@handled
def photo(uid, photo_uid):
    data, mime_type, filename = service.get_photo(payload(), uid, photo_uid, with_filename=True)
    response = send_file(BytesIO(data), mimetype=mime_type, download_name=filename, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@intake_bp.put("/<uid>/draft")
@verify
@handled
def draft(uid):
    data = body()
    return jsonify({"code": 200, "data": service.save_draft(payload(), uid, data.get("version"), data.get("draft"))})


@intake_bp.post("/<uid>/confirm")
@verify
@handled
def confirm(uid):
    data = body()
    return jsonify({"code": 200, "data": service.confirm_intake(payload(), uid, data.get("version"), reviewed=data.get("reviewed"))})


@intake_bp.post("/<uid>/recognize")
@verify
@handled
def recognize(uid):
    data = body()
    return jsonify({"code": 200, "data": service.start_recognition(payload(), uid, data.get("version"))}), 202
