"""Accountant-facing settings, journals, periods, reports and bank reconciliation."""
import csv
from functools import wraps
from io import StringIO

from flask import Blueprint, Response, jsonify, request
from sqlalchemy.exc import IntegrityError

from Auth import allow, get_token_payload, verify
from services import finance_accounting_service as service
from services.finance_ledger_service import FinanceConflictError
from utils.audit import load_audit_logs

finance_accounting_bp = Blueprint("finance_accounting", __name__, url_prefix="/api/finance/v2/accounting")


def endpoint(function):
    @wraps(function)
    @verify
    @allow(role=["admin", "finance"])
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            if isinstance(result, Response):
                return result
            return jsonify(code=200, data=result)
        except PermissionError as exc:
            return jsonify(code=403, msg=str(exc)), 403
        except LookupError as exc:
            return jsonify(code=404, msg=str(exc)), 404
        except (service.AccountingConflict, FinanceConflictError) as exc:
            return jsonify(code=409, msg=str(exc)), 409
        except (ValueError, TypeError) as exc:
            return jsonify(code=400, msg=str(exc)), 400
        except IntegrityError:
            return jsonify(code=409, msg="记录冲突，请刷新后重试"), 409
    return wrapped


def actor():
    return get_token_payload() or {}


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("请求必须为 JSON 对象")
    return value


@finance_accounting_bp.get("/settings")
@endpoint
def get_settings():
    return service.get_settings(actor())


@finance_accounting_bp.put("/settings")
@endpoint
def configure():
    return service.configure(body(), actor())


@finance_accounting_bp.post("/opening-confirmation")
@endpoint
def confirm_opening():
    return service.confirm_opening(body(), actor())


@finance_accounting_bp.get("/accounts")
@endpoint
def accounts():
    return service.list_accounts(actor())


@finance_accounting_bp.post("/accounts")
@endpoint
def create_account():
    return service.create_account(body(), actor())


@finance_accounting_bp.get("/entries")
@endpoint
def entries():
    return service.list_entries(actor(), **request.args.to_dict())


@finance_accounting_bp.post("/entries")
@endpoint
def create_entry():
    return service.create_manual_entry(body(), actor())


@finance_accounting_bp.get("/entries/<int:entry_id>")
@endpoint
def get_entry(entry_id):
    return service.get_entry(entry_id, actor())


@finance_accounting_bp.post("/entries/<int:entry_id>/<action>")
@endpoint
def entry_action(entry_id, action):
    return service.entry_action(entry_id, action, body(), actor())


@finance_accounting_bp.get("/entries/<int:entry_id>/history")
@endpoint
def entry_history(entry_id):
    service.get_entry(entry_id, actor())
    result = load_audit_logs(target_type="finance_journal_entry", target_id=entry_id,
                            page=request.args.get("p", 1, type=int), page_size=request.args.get("s", 20, type=int))
    return {**result, "history_complete": True, "notice": "凭证变更与业务操作在同一事务中保存"}


@finance_accounting_bp.get("/periods")
@endpoint
def periods():
    return service.list_periods(actor())


@finance_accounting_bp.post("/periods")
@endpoint
def create_period():
    return service.create_period(body(), actor())


@finance_accounting_bp.get("/periods/<int:period_id>/checks")
@endpoint
def checks(period_id):
    return service.closing_checks(period_id, actor())


@finance_accounting_bp.post("/periods/<int:period_id>/<action>")
@endpoint
def period_action(period_id, action):
    return service.period_action(period_id, action, body(), actor())


@finance_accounting_bp.get("/reports")
@endpoint
def reports():
    return service.financial_report(actor(), request.args.get("date_from"), request.args.get("date_to"), request.args.get("account_code"))


@finance_accounting_bp.get("/reports/export")
@endpoint
def export_report():
    report = service.financial_report(actor(), request.args.get("date_from"), request.args.get("date_to"), request.args.get("account_code"))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["科目代码", "科目名称", "期初余额（借方为正）", "本期借方", "本期贷方", "期末余额（借方为正）"])
    for row in report["trial_balance"]:
        # Prevent spreadsheet formula execution when exporting user-defined labels.
        name = row["name"]
        if name.startswith(("=", "+", "-", "@", "\t", "\r")):
            name = "'" + name
        writer.writerow([row["code"], name, row["opening"], row["debit"], row["credit"], row["closing"]])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="trial-balance.csv"'})


@finance_accounting_bp.get("/bank-transactions")
@endpoint
def bank_transactions():
    return service.list_bank_transactions(actor(), **request.args.to_dict())


@finance_accounting_bp.post("/bank-transactions/preview")
@endpoint
def preview_bank_import():
    return service.import_bank_transactions(body(), actor(), preview=True)


@finance_accounting_bp.post("/bank-transactions/import")
@endpoint
def bank_import():
    return service.import_bank_transactions(body(), actor())


@finance_accounting_bp.post("/bank-transactions/<int:transaction_id>/<action>")
@endpoint
def bank_action(transaction_id, action):
    return service.bank_action(transaction_id, action, body(), actor())


@finance_accounting_bp.get("/partner-statement")
@endpoint
def partner_statement():
    return service.partner_statement(actor(), request.args.get("partner_type"), request.args.get("partner_id"),
                                     request.args.get("date_from"), request.args.get("date_to"))


@finance_accounting_bp.get("/partner-statement/export")
@endpoint
def export_partner_statement():
    statement = service.partner_statement(
        actor(), request.args.get("partner_type"), request.args.get("partner_id"),
        request.args.get("date_from"), request.args.get("date_to"))
    output = StringIO()
    writer = csv.writer(output)
    def safe(value):
        value = str(value or "")
        return "'"+value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
    writer.writerow(["往来对账单", safe(statement["company_name"]), safe(statement["partner_name"]), "CNY"])
    writer.writerow(["开始日期", statement["date_from"], "截止日期", statement["date_to"]])
    writer.writerow(["期初余额", statement["opening_balance"]])
    writer.writerow(["日期", "凭证号", "摘要", "增加", "减少", "余额"])
    for row in statement["items"]:
        writer.writerow([row["entry_date"], safe(row["entry_number"]), safe(row["description"]), row["increase"], row["decrease"], row["balance"]])
    writer.writerow(["期末余额", statement["closing_balance"]])
    return Response("\ufeff"+output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="partner-statement.csv"'})


def _entity_history(model, target_type, row_id):
    with service.SessionFactory() as session:
        if session.get(model, row_id) is None:
            raise LookupError("记录不存在")
    result = load_audit_logs(target_type=target_type, target_id=row_id,
        page=request.args.get("p", 1, type=int), page_size=request.args.get("s", 20, type=int))
    return {**result, "history_complete": True, "notice": "本记录自创建起的变更与业务在同一事务保存"}


@finance_accounting_bp.get("/periods/<int:period_id>/history")
@endpoint
def period_history(period_id):
    return _entity_history(service.FinancePeriod, "finance_period", period_id)


@finance_accounting_bp.get("/bank-transactions/<int:transaction_id>/history")
@endpoint
def bank_history(transaction_id):
    return _entity_history(service.FinanceBankTransaction, "finance_bank_transaction", transaction_id)
