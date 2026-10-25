"""Authenticated exception registration and salesperson follow-up API."""
from functools import wraps
from flask import Blueprint, jsonify, request
from Auth import get_token_payload, verify
from services import order_exception_service as service

order_exception_bp = Blueprint("order_exceptions", __name__, url_prefix="/api/order-exceptions")

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
        except service.ExceptionConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"code": 400, "msg": str(exc)}), 400
    return wrapped

@order_exception_bp.post("")
@_endpoint
def create_exception():
    return service.create_exception(request.get_json(silent=True), get_token_payload())

@order_exception_bp.get("")
@_endpoint
def exceptions():
    return service.list_exceptions(
        get_token_payload(), page=request.args.get("page", "1"),
        page_size=request.args.get("page_size", "20"), status=request.args.get("status", "all"),
        salesman_id=request.args.get("salesman_id"),
    )

@order_exception_bp.get("/salespeople")
@_endpoint
def salespeople():
    return service.salespeople(get_token_payload())

@order_exception_bp.get("/<string:uid>")
@_endpoint
def exception(uid):
    return service.get_exception(uid, get_token_payload())

@order_exception_bp.post("/<string:uid>/followups")
@_endpoint
def followup(uid):
    return service.add_followup(uid, request.get_json(silent=True), get_token_payload())

@order_exception_bp.post("/<string:uid>/resolve")
@_endpoint
def resolve(uid):
    return service.resolve_exception(uid, request.get_json(silent=True), get_token_payload())
