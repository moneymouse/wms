"""Clerk-accessible evidence ingestion; financial posting remains finance-only."""
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from Auth import allow, get_token_payload, verify
from services import supplier_reconciliation_service as service
from services.finance_ledger_service import FinanceConflictError

supplier_reconciliation_bp = Blueprint("supplier_reconciliation", __name__, url_prefix="/api/supplier-reconciliation")


def _endpoint(function):
    @wraps(function)
    @verify
    @allow(role=["admin", "clerk", "finance"])
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            return result if not isinstance(result, dict) else jsonify({"code": 200, "data": result})
        except PermissionError as exc:
            return jsonify({"code": 403, "msg": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"code": 404, "msg": str(exc)}), 404
        except FinanceConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"code": 400, "msg": str(exc)}), 400
    return wrapped


def _pagination():
    return {"page": max(request.args.get("p", 1, type=int) or 1, 1),
        "page_size": min(max(request.args.get("s", 50, type=int) or 50, 1), 200)}


@supplier_reconciliation_bp.get("/template")
@_endpoint
def template():
    service._actor(get_token_payload())
    path = Path(current_app.root_path) / "static" / "supplier_reconciliation_template.xlsx"
    if not path.is_file():
        raise LookupError("统一模板尚未配置")
    return send_file(path, as_attachment=True, download_name="供应商对账统一模板.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@supplier_reconciliation_bp.get("/vendors")
@_endpoint
def vendors():
    return service.list_vendors(get_token_payload(), query_text=request.args.get("q", ""), **_pagination())


@supplier_reconciliation_bp.post("/batches")
@_endpoint
def upload():
    file = request.files.get("file")
    if file is None:
        raise ValueError("请选择对账明细 Excel 文件")
    return service.upload_batch(file.read(service.MAX_FILE_BYTES + 1), file.filename,
        request.form.get("vendor_id"), request.form.get("period"), get_token_payload())


@supplier_reconciliation_bp.get("/batches")
@_endpoint
def batches():
    return service.list_batches(get_token_payload(), query_text=request.args.get("q", ""),
        vendor_id=request.args.get("vendor_id"), period=request.args.get("period", ""), **_pagination())


@supplier_reconciliation_bp.get("/batches/<int:batch_id>")
@_endpoint
def batch(batch_id):
    return service.get_batch(batch_id, get_token_payload(), row_status=request.args.get("row_status", ""), **_pagination())


@supplier_reconciliation_bp.post("/batches/<int:batch_id>/reconcile")
@_endpoint
def reconcile(batch_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为 JSON 对象")
    return service.reconcile_batch(batch_id, body, get_token_payload())


@supplier_reconciliation_bp.get("/orders/<order_uid>/costs")
@_endpoint
def costs(order_uid):
    return service.order_costs(order_uid, get_token_payload())
