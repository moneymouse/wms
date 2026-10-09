"""Explicit preview/approval boundary for legacy balance cutover."""
from flask import Blueprint, request
from controllers.finance_ledger_controller import _actor, _body, _endpoint
from services import finance_legacy_service as service

finance_legacy_bp = Blueprint("finance_legacy", __name__, url_prefix="/api/finance/v2/legacy")


@finance_legacy_bp.get("/orders")
@_endpoint
def orders():
    return service.list_orders(_actor(), **request.args.to_dict())


@finance_legacy_bp.get("/preview")
@_endpoint
def preview():
    return service.preview(_actor(), request.args.get("order_uid"), request.args.get("cutoff_date"))


@finance_legacy_bp.post("/import")
@_endpoint
def import_balance():
    return service.import_balance(_body(), _actor())


@finance_legacy_bp.get("/links")
@_endpoint
def links():
    return service.list_links(_actor(), **request.args.to_dict())


@finance_legacy_bp.get("/links/<int:row_id>")
@_endpoint
def link(row_id):
    return service.get_link(row_id, _actor())


@finance_legacy_bp.post("/links/<int:row_id>/acknowledge")
@_endpoint
def acknowledge(row_id):
    return service.acknowledge(row_id, _body(), _actor())


@finance_legacy_bp.post("/links/<int:row_id>/revoke")
@_endpoint
def revoke(row_id):
    return service.revoke(row_id, _body(), _actor())


@finance_legacy_bp.get("/links/<int:row_id>/history")
@_endpoint
def history(row_id):
    return service.history(row_id, _actor(), max(request.args.get("p", 1, type=int) or 1, 1), min(max(request.args.get("s", 50, type=int) or 50, 1), 200))
