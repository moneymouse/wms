"""Finance v2 HTTP boundary. All document permissions are enforced server-side."""
import base64
from functools import wraps

from flask import Blueprint, jsonify, request

from Auth import allow, get_token_payload, verify
from services import finance_ledger_service as service


finance_ledger_bp = Blueprint("finance_ledger", __name__, url_prefix="/api/finance/v2")


def _endpoint(function):
    @wraps(function)
    @verify
    @allow(role=["admin", "finance"])
    def wrapped(*args, **kwargs):
        try:
            return jsonify({"code": 200, "data": function(*args, **kwargs)})
        except PermissionError as exc:
            return jsonify({"code": 403, "msg": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"code": 404, "msg": str(exc)}), 404
        except service.FinanceConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            code = 409 if getattr(exc, "status_code", None) == 409 else 400
            return jsonify({"code": code, "msg": str(exc)}), code
    return wrapped


def _payment_endpoint(function):
    @wraps(function)
    @verify
    @allow(role=["admin", "finance", "salesperson"])
    def wrapped(*args, **kwargs):
        try:
            return jsonify({"code": 200, "data": function(*args, **kwargs)})
        except PermissionError as exc:
            return jsonify({"code": 403, "msg": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"code": 404, "msg": str(exc)}), 404
        except service.FinanceConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            code = 409 if getattr(exc, "status_code", None) == 409 else 400
            return jsonify({"code": code, "msg": str(exc)}), code
    return wrapped


def _actor():
    return get_token_payload() or {}


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为 JSON 对象")
    if request.headers.get("Idempotency-Key"):
        body["idempotency_key"] = request.headers["Idempotency-Key"]
    return body


def _filters():
    values = request.args.to_dict()
    values["page"] = max(request.args.get("p", 1, type=int) or 1, 1)
    values["page_size"] = min(max(request.args.get("s", 30, type=int) or 30, 1), 200)
    return values


@finance_ledger_bp.get("/documents")
@_endpoint
def documents():
    return service.list_documents(_actor(), **_filters())


@finance_ledger_bp.post("/documents")
@_endpoint
def create_document():
    return service.create_document(_body(), _actor())


@finance_ledger_bp.get("/documents/<int:document_id>")
@_endpoint
def document(document_id):
    return service.get_document(document_id, _actor())


@finance_ledger_bp.patch("/documents/<int:document_id>")
@_endpoint
def update_document(document_id):
    return service.update_document(document_id, _body(), _actor())


@finance_ledger_bp.post("/documents/<int:document_id>/<action>")
@_endpoint
def document_action(document_id, action):
    handler = {"post": service.post_document, "cancel": service.cancel_document, "reverse": service.reverse_document}.get(action)
    if handler is None:
        raise LookupError("账单动作不存在")
    return handler(document_id, _body(), _actor())


@finance_ledger_bp.get("/documents/<int:document_id>/history")
@_endpoint
def document_history(document_id):
    filters = _filters()
    return service.history("documents", document_id, _actor(), filters["page"], filters["page_size"])


@finance_ledger_bp.get("/payments")
@_payment_endpoint
def payments():
    return service.list_payments(_actor(), **_filters())


@finance_ledger_bp.post("/payments")
@_payment_endpoint
def create_payment():
    return service.create_payment(_body(), _actor())


@finance_ledger_bp.get("/payments/<int:payment_id>")
@_payment_endpoint
def payment(payment_id):
    return service.get_payment(payment_id, _actor())


@finance_ledger_bp.patch("/payments/<int:payment_id>")
@_payment_endpoint
def update_payment(payment_id):
    return service.update_payment(payment_id, _body(), _actor())


@finance_ledger_bp.post("/payments/<int:payment_id>/<action>")
@_payment_endpoint
def payment_action(payment_id, action):
    handler = {"post": service.post_payment, "cancel": service.cancel_payment, "reverse": service.reverse_payment,
        "submit": service.submit_payment, "return": service.return_payment}.get(action)
    if handler is None:
        raise LookupError("资金动作不存在")
    return handler(payment_id, _body(), _actor())


@finance_ledger_bp.get("/payments/<int:payment_id>/history")
@_payment_endpoint
def payment_history(payment_id):
    filters = _filters()
    return service.history("payments", payment_id, _actor(), filters["page"], filters["page_size"])


@finance_ledger_bp.get("/payment-options/<kind>")
@_payment_endpoint
def payment_options(kind):
    return service.payment_options(kind, _actor(), **_filters())


@finance_ledger_bp.get("/payments/<int:payment_id>/pdf")
@verify
@allow(role=["admin", "finance", "salesperson"])
def payment_pdf(payment_id):
    from utils.finance_payment_pdf import build_finance_payment_pdf
    try:
        payment = service.get_payment(payment_id, _actor())
        pdf = build_finance_payment_pdf(payment)
        return jsonify({"code": 200, "data": base64.b64encode(pdf.getvalue()).decode("ascii"),
            "filename": f"{payment['number']}.pdf", "mime_type": "application/pdf"})
    except PermissionError as exc:
        return jsonify({"code": 403, "msg": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404


@finance_ledger_bp.get("/allocations")
@_endpoint
def allocations():
    return service.list_allocations(_actor(), **_filters())


@finance_ledger_bp.post("/allocations")
@_endpoint
def create_allocations():
    return service.create_allocations(_body(), _actor())


@finance_ledger_bp.post("/allocations/<int:allocation_id>/reverse")
@_endpoint
def reverse_allocation(allocation_id):
    return service.reverse_allocation(allocation_id, _body(), _actor())


@finance_ledger_bp.get("/partners")
@_endpoint
def partners():
    return service.list_partners(_actor(), request.args.get("partner_type", "customer"), request.args.get("q", ""), request.args.get("include_inactive", ""))


@finance_ledger_bp.get("/vendors")
@_endpoint
def vendors():
    return service.list_masters("vendors", _actor(), **_filters())


@finance_ledger_bp.post("/vendors")
@_endpoint
def create_vendor():
    return service.save_master("vendors", _body(), _actor())


@finance_ledger_bp.patch("/vendors/<int:row_id>")
@_endpoint
def update_vendor(row_id):
    return service.save_master("vendors", _body(), _actor(), row_id)


@finance_ledger_bp.get("/vendors/<int:row_id>/history")
@_endpoint
def vendor_history(row_id):
    filters = _filters()
    return service.history("vendors", row_id, _actor(), filters["page"], filters["page_size"])


@finance_ledger_bp.get("/accounts")
@_endpoint
def accounts():
    return service.list_masters("accounts", _actor(), **_filters())


@finance_ledger_bp.post("/accounts")
@_endpoint
def create_account():
    return service.save_master("accounts", _body(), _actor())


@finance_ledger_bp.patch("/accounts/<int:row_id>")
@_endpoint
def update_account(row_id):
    return service.save_master("accounts", _body(), _actor(), row_id)


@finance_ledger_bp.get("/accounts/<int:row_id>/history")
@_endpoint
def account_history(row_id):
    filters = _filters()
    return service.history("accounts", row_id, _actor(), filters["page"], filters["page_size"])


@finance_ledger_bp.get("/dashboard")
@_endpoint
def dashboard():
    return service.dashboard(_actor(), request.args.get("as_of"))


@finance_ledger_bp.get("/aging")
@_endpoint
def aging():
    return service.aging(_actor(), request.args.get("partner_type", "customer"), request.args.get("as_of"))
