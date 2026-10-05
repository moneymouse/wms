"""Payment receipt and accounts-receivable APIs."""

import base64
from datetime import datetime

from flask import Blueprint, jsonify, request

from Auth import allow, get_token_payload, verify
from services import receivable_service
from utils.audit import record_audit
from utils.receipt_pdf import build_receipt_pdf


receivable_bp = Blueprint("receivable", __name__, url_prefix="/api")
RECEIPT_ROLES = ["salesperson", "admin"]
RECEIPT_VIEW_ROLES = ["salesperson", "admin", "finance"]
FINANCE_ROLES = ["admin", "finance"]


def _error_response(exc):
    if isinstance(exc, PermissionError):
        return jsonify({"code": 403, "msg": str(exc)}), 403
    if isinstance(exc, LookupError):
        return jsonify({"code": 404, "msg": str(exc)}), 404
    return jsonify({"code": 400, "msg": str(exc)}), 400


@receivable_bp.get("/receivables/orders")
@verify
@allow(role=RECEIPT_ROLES)
def get_receivable_orders():
    customer_id = request.args.get("customer_id", type=int)
    page = max(request.args.get("p", 1, type=int) or 1, 1)
    page_size = min(max(request.args.get("s", 20, type=int) or 20, 1), 100)
    try:
        result = receivable_service.list_receivable_orders(
            customer_id=customer_id,
            operator_payload=get_token_payload() or {},
            query_text=request.args.get("q", ""),
            page=page,
            page_size=page_size,
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
            owner_id=request.args.get("owner_id", type=int),
            order_uid=request.args.get("order_uid"),
        )
        return jsonify({
            "code": 200,
            "data": result["items"],
            **{k: result[k] for k in ("total", "page", "page_size")},
        })
    except (ValueError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.get("/receivable-adjustments")
@verify
@allow(role=RECEIPT_VIEW_ROLES)
def get_receivable_adjustments():
    page = max(request.args.get("p", 1, type=int) or 1, 1)
    page_size = min(max(request.args.get("s", 20, type=int) or 20, 1), 200)
    try:
        result = receivable_service.list_price_adjustments(
            get_token_payload() or {},
            status=request.args.get("status", "pending") or None,
            query_text=request.args.get("q", ""),
            page=page,
            page_size=page_size,
            owner_id=request.args.get("owner_id", type=int),
            order_uid=request.args.get("order_uid"),
        )
        return jsonify({
            "code": 200,
            "data": result["items"],
            **{key: result[key] for key in ("total", "page", "page_size")},
        })
    except (ValueError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.get("/receivable-adjustments/<int:adjustment_id>")
@verify
@allow(role=RECEIPT_VIEW_ROLES)
def get_receivable_adjustment(adjustment_id):
    try:
        result = receivable_service.get_price_adjustment_detail(
            adjustment_id, get_token_payload() or {}
        )
        return jsonify({"code": 200, "data": result})
    except (ValueError, PermissionError, LookupError) as exc:
        return _error_response(exc)


@receivable_bp.post("/receipts")
@verify
@allow(role=RECEIPT_ROLES)
def create_receipt():
    try:
        result = receivable_service.create_receipt(
            request.get_json() or {}, get_token_payload() or {}
        )
        record_audit(
            event_type="payment_receipt",
            target_type="receipt",
            target_id=result["id"],
            action="receipt_create",
            after_data=result,
            remark=result.get("remark"),
        )
        return jsonify({"code": 200, "msg": "收款单已提交审核", "data": result})
    except (ValueError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.get("/receipts")
@verify
@allow(role=RECEIPT_VIEW_ROLES)
def get_receipts():
    page = max(request.args.get("p", 1, type=int) or 1, 1)
    page_size = min(max(request.args.get("s", 20, type=int) or 20, 1), 200)
    result = receivable_service.list_receipts(
        get_token_payload() or {},
        status=request.args.get("status") or None,
        page=page,
        page_size=page_size,
        query_text=request.args.get("q", ""),
        owner_id=request.args.get("owner_id", type=int),
    )
    return jsonify({"code": 200, "data": result["items"], **{k: result[k] for k in ("total", "page", "page_size")}})


@receivable_bp.get("/receipts/<int:receipt_id>")
@verify
@allow(role=RECEIPT_VIEW_ROLES)
def get_receipt(receipt_id):
    try:
        result = receivable_service.get_receipt_detail(receipt_id, get_token_payload() or {})
        return jsonify({"code": 200, "data": result})
    except (LookupError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.get("/receipts/<int:receipt_id>/pdf")
@verify
@allow(role=RECEIPT_VIEW_ROLES)
def get_receipt_pdf(receipt_id):
    try:
        receipt = receivable_service.get_receipt_detail(receipt_id, get_token_payload() or {})
        stream = build_receipt_pdf(receipt)
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        return jsonify({
            "code": 200,
            "filename": f"{receipt['receipt_no']}.pdf",
            "mime_type": "application/pdf",
            "data": encoded,
        })
    except (LookupError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.put("/finance/receipts/<int:receipt_id>/review")
@verify
@allow(role=FINANCE_ROLES)
def review_receipt(receipt_id):
    body = request.get_json() or {}
    try:
        before = receivable_service.get_receipt_detail(receipt_id, get_token_payload() or {})
        result = receivable_service.review_receipt(
            receipt_id=receipt_id,
            action=body.get("action"),
            review_remark=body.get("review_remark"),
            operator_payload=get_token_payload() or {},
        )
        record_audit(
            event_type="payment_receipt",
            target_type="receipt",
            target_id=receipt_id,
            action=f"receipt_{body.get('action')}",
            before_data=before,
            after_data=result,
            remark=body.get("review_remark"),
        )
        return jsonify({"code": 200, "msg": "审核完成", "data": result})
    except (ValueError, LookupError, PermissionError) as exc:
        return _error_response(exc)


@receivable_bp.get("/finance/accounts-receivable")
@verify
@allow(role=FINANCE_ROLES)
def get_accounts_receivable():
    date_to = request.args.get("date_to") or request.args.get("as_of") or datetime.now().strftime("%Y-%m-%d")
    page = max(request.args.get("p", 1, type=int) or 1, 1)
    page_size = min(max(request.args.get("s", 20, type=int) or 20, 1), 200)
    try:
        result = receivable_service.accounts_receivable_ledger(
            date_from=request.args.get("date_from") or None,
            date_to=date_to,
            page=page,
            page_size=page_size,
            customer_id=request.args.get("customer_id", type=int),
            owner_id=request.args.get("owner_id", type=int),
            settlement_status=request.args.get("status") or None,
            query_text=request.args.get("q", ""),
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as exc:
        return _error_response(exc)


@receivable_bp.get("/finance/sales-bonus-rates")
@verify
@allow(role=FINANCE_ROLES)
def get_sales_bonus_rates():
    return jsonify({"code": 200, "data": receivable_service.list_sales_bonus_rates()})


@receivable_bp.post("/finance/sales-bonus-rates")
@verify
@allow(role=FINANCE_ROLES)
def create_sales_bonus_rate():
    try:
        result = receivable_service.create_sales_bonus_rate(
            request.get_json() or {}, get_token_payload() or {}
        )
        record_audit(
            event_type="sales_bonus_rate",
            target_type="rate",
            target_id=result["id"],
            action="create",
            after_data=result,
            remark=result.get("remark"),
        )
        return jsonify({"code": 200, "msg": "跟单奖金费率已创建", "data": result})
    except ValueError as exc:
        return _error_response(exc)
