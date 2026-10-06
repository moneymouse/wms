"""Invoice-linked deferred revenue endpoints."""
from flask import Blueprint, request
from controllers.finance_ledger_controller import _endpoint, _actor, _body
from services import finance_revenue_service as service

finance_revenue_bp = Blueprint("finance_revenue", __name__, url_prefix="/api/finance/v2/revenue")


@finance_revenue_bp.get("")
@_endpoint
def invoices():
    return service.list_invoices(_actor(), page=request.args.get("p", 1, type=int),
        page_size=request.args.get("s", 20, type=int), query_text=request.args.get("q", ""),
        open_only=request.args.get("open_only", "true").lower() not in {"0", "false"})


@finance_revenue_bp.get("/<int:invoice_id>")
@_endpoint
def invoice(invoice_id):
    return service.get_invoice(invoice_id, _actor())


@finance_revenue_bp.post("/<int:invoice_id>/recognize")
@_endpoint
def recognize(invoice_id):
    return service.recognize(invoice_id, _body(), _actor())


@finance_revenue_bp.post("/entries/<int:entry_id>/reverse")
@_endpoint
def reverse(entry_id):
    return service.reverse(entry_id, _body(), _actor())
