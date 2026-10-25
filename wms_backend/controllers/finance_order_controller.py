from flask import Blueprint, request
from controllers.finance_ledger_controller import _actor, _body, _endpoint, _payment_endpoint
from services import finance_order_service as service

finance_order_bp = Blueprint("finance_order", __name__, url_prefix="/api/finance/v2")


@finance_order_bp.get("/order-payments/<string:order_uid>")
@_payment_endpoint
def order_payments(order_uid):
    return service.list_order_payments(order_uid, _actor(),
        page=request.args.get("p", 1, type=int), page_size=request.args.get("s", 30, type=int))


@finance_order_bp.get("/order-settlements")
@_endpoint
def orders():
    return service.list_orders(_actor(), **request.args.to_dict())


@finance_order_bp.post("/order-settlements/<string:order_uid>/sync")
@_endpoint
def sync(order_uid):
    return service.sync_order(order_uid, _body(), _actor())


@finance_order_bp.post("/order-allocations")
@_endpoint
def allocate():
    return service.allocate_orders(_body(), _actor())
