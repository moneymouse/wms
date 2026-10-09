"""Authenticated inbox API with restricted, generic employee delivery."""

from functools import wraps

from flask import Blueprint, jsonify, request

from Auth import get_token_payload, verify
from services import message_service as service


message_bp = Blueprint("messages", __name__, url_prefix="/api/messages")


def _endpoint(function):
    @wraps(function)
    @verify
    def wrapped(**kwargs):
        try:
            return jsonify({"code": 200, "data": function(**kwargs)})
        except PermissionError as exc:
            return jsonify({"code": 403, "msg": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"code": 404, "msg": str(exc)}), 404
        except service.MessageConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"code": 400, "msg": str(exc)}), 400
    return wrapped


@message_bp.post("")
@_endpoint
def send_message():
    return service.send_http_message(request.get_json(silent=True), get_token_payload())


@message_bp.get("")
@_endpoint
def messages():
    return service.list_messages(
        get_token_payload(), page=request.args.get("page", request.args.get("p", "1")),
        page_size=request.args.get("page_size", request.args.get("s", "20")), status=request.args.get("status", "all"),
    )


@message_bp.get("/unread-count")
@_endpoint
def unread_count():
    return service.unread_count(get_token_payload())


@message_bp.get("/<string:uid>")
@_endpoint
def message(uid):
    return service.get_message(uid, get_token_payload())


@message_bp.post("/<string:uid>/read")
@_endpoint
def mark_read(uid):
    return service.mark_read(uid, get_token_payload())


@message_bp.post("/read-all")
@_endpoint
def mark_all_read():
    return service.mark_all_read(get_token_payload())
