"""Journals and reporting use real ORM rows, not mocked financial arithmetic."""
from decimal import Decimal
from unittest.mock import patch

import pytest
from data.finance.accounting import FinanceBankTransaction, FinanceJournalEntry, FinanceSettings
from data.finance.ledger import FinanceDocument
from services import finance_accounting_service as accounting
from services import finance_ledger_service as ledger
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import ACTOR, SALES, finance, document, payment, allocate

ADMIN = {"user_id": 700, "name": "主管", "roles": ["admin"]}


def manual(finance, **extra):
    return accounting.create_manual_entry({"entry_date": "2026-01-15", "description": "经营费用",
        "lines": [{"account_code": "6602", "debit": "20"},
                  {"account_code": "1002", "credit": "20", "fund_account_id": finance["account"]["id"]}], **extra}, ACTOR)


def test_journal_and_subledger_amounts_reconcile(finance):
    doc = document(finance, "100")
    pay = payment(finance, "70")
    allocate(pay, doc, "70")
    report = accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")
    rows = {row["code"]: row for row in report["trial_balance"]}
    assert rows["1122"]["closing"] == "30.00"
    assert rows["1002"]["closing"] == "70.00"
    assert report["profit_loss"]["profit"] == "100.00"
    assert report["balance_sheet"]["difference"] == "0.00"
    assert report["total_credit"] == report["total_debit"] == "170.00"


def test_deferred_income_policy_does_not_call_receipt_profit(finance):
    settings = accounting.get_settings(ACTOR)
    accounting.configure({**settings, "revenue_policy": "deferred"}, ACTOR)
    document(finance, "100")
    payment(finance, "100")
    report = accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")
    assert report["profit_loss"]["revenue"] == "0.00"
    assert report["balance_sheet"]["liabilities"] == "100.00"
    assert report["cashflow"]["operating"] == "100.00"


def test_closed_period_blocks_post_and_audit_failure_rolls_back(finance):
    draft = document(finance, post=False)
    with TestSessionFactory() as session:
        from data.finance.accounting import FinancePeriod
        period = session.query(FinancePeriod).one()
        period.status = "closed"
        session.commit()
    with pytest.raises(ValueError, match="关账"):
        ledger.post_document(draft["id"], {"version": draft["version"]}, ACTOR)
    assert ledger.get_document(draft["id"], ACTOR)["status"] == "draft"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0


def test_audit_failure_rolls_back_manual_entry(finance):
    with patch.object(accounting, "record_audit", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            manual(finance)
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0


def test_manual_entry_balanced_then_post_and_reverse_preserves_cutoff(finance):
    draft = manual(finance)
    assert accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")["profit_loss"]["expense"] == "0.00"
    posted = accounting.entry_action(draft["id"], "post", {"version": draft["version"]}, ACTOR)
    accounting.entry_action(posted["id"], "reverse", {"version": posted["version"], "entry_date": "2026-02-02", "reason": "重复费用"}, ACTOR)
    assert accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")["profit_loss"]["expense"] == "20.00"
    assert accounting.financial_report(ACTOR, "2026-01-01", "2026-02-28")["profit_loss"]["expense"] == "0.00"
    assert accounting.get_entry(posted["id"], ACTOR)["status"] == "reversed"


@pytest.mark.parametrize("lines", [
    [{"account_code": "6602", "debit": 20}, {"account_code": "2241", "credit": 21}],
    [{"account_code": "6602", "debit": 20, "credit": 20}, {"account_code": "2241", "credit": 0}],
    [{"account_code": "1122", "debit": 20}, {"account_code": "4001", "credit": 20}],
    [{"account_code": "1002", "debit": 20}, {"account_code": "4001", "credit": 20}],
    [{"account_code": "9999", "debit": 20}, {"account_code": "4001", "credit": 20}],
])
def test_invalid_manual_entries_are_atomic(finance, lines):
    with pytest.raises(ValueError):
        manual(finance, lines=lines)
    assert accounting.list_entries(ACTOR)["total"] == 0


def test_manual_post_conflict_and_source_journal_is_protected(finance):
    draft = manual(finance)
    accounting.entry_action(draft["id"], "post", {"version": draft["version"]}, ACTOR)
    with pytest.raises(accounting.AccountingConflict):
        accounting.entry_action(draft["id"], "post", {"version": draft["version"]}, ACTOR)
    document(finance)
    generated = next(row for row in accounting.list_entries(ACTOR)["items"] if row["kind"] == "document")
    with pytest.raises(ValueError, match="来源"):
        accounting.entry_action(generated["id"], "reverse", {"version": generated["version"], "entry_date": "2026-02-02", "reason": "不应允许"}, ACTOR)


def test_period_close_checks_then_admin_reopen(finance):
    period = accounting.list_periods(ACTOR)[0]
    checks = accounting.closing_checks(period["id"], ACTOR)
    assert checks["can_close"] is False
    settings = accounting.get_settings(ACTOR)
    accounting.confirm_opening({"version": settings["version"], "reason": "新公司零期初核对无误"}, ACTOR)
    assert accounting.closing_checks(period["id"], ACTOR)["can_close"] is True
    closed = accounting.period_action(period["id"], "close", {"version": period["version"], "reason": "已核对"}, ACTOR)
    with pytest.raises(PermissionError):
        accounting.period_action(closed["id"], "reopen", {"version": closed["version"], "reason": "更正"}, ACTOR)
    reopened = accounting.period_action(closed["id"], "reopen", {"version": closed["version"], "reason": "更正凭证"}, ADMIN)
    assert reopened["status"] == "open"


def test_period_overlap_and_early_date_are_rejected(finance):
    with pytest.raises(ValueError, match="重叠"):
        accounting.create_period({"name": "重复", "date_from": "2026-04-01", "date_to": "2026-04-30"}, ACTOR)
    with pytest.raises(ValueError, match="建账"):
        manual(finance, entry_date="2025-12-31")


def bank_rows(finance):
    return {"account_id": finance["account"]["id"], "rows": [{"transaction_date": "2026-01-11", "amount": "70", "reference": "BANK001", "description": "客户回款"}]}


def test_bank_import_preview_dedup_and_conflicting_reference(finance):
    body = bank_rows(finance)
    assert accounting.import_bank_transactions(body, ACTOR, preview=True)["imported"] == 0
    assert accounting.list_bank_transactions(ACTOR)["total"] == 0
    assert accounting.import_bank_transactions(body, ACTOR)["imported"] == 1
    assert accounting.import_bank_transactions(body, ACTOR)["duplicates"] == 1
    body["rows"][0]["amount"] = "71"
    with pytest.raises(accounting.AccountingConflict):
        accounting.import_bank_transactions(body, ACTOR)
    assert accounting.list_bank_transactions(ACTOR)["items"][0]["amount"] == "70.00"


def test_invalid_bank_batch_is_atomic(finance):
    body = bank_rows(finance)
    body["rows"].append({"transaction_date": "2026-01-11", "amount": "NaN", "reference": "BAD"})
    with pytest.raises(ValueError):
        accounting.import_bank_transactions(body, ACTOR)
    assert accounting.list_bank_transactions(ACTOR)["total"] == 0


def test_bank_match_requires_same_amount_and_prevents_payment_reversal(finance):
    pay = payment(finance, "70")
    accounting.import_bank_transactions(bank_rows(finance), ACTOR)
    bank = accounting.list_bank_transactions(ACTOR)["items"][0]
    matched = accounting.bank_action(bank["id"], "match", {"version": bank["version"], "payment_id": pay["id"]}, ACTOR)
    with pytest.raises(ValueError, match="银行对账"):
        ledger.reverse_payment(pay["id"], {"version": pay["version"], "reason": "误收", "payment_date": "2026-02-01"}, ACTOR)
    accounting.bank_action(bank["id"], "unmatch", {"version": matched["version"], "reason": "银行流水核对有误"}, ACTOR)
    ledger.reverse_payment(pay["id"], {"version": pay["version"], "reason": "重复登记", "payment_date": "2026-02-01"}, ACTOR)


def test_read_and_write_permissions_are_checked_in_service(finance):
    with pytest.raises(PermissionError):
        accounting.financial_report(SALES)
    with pytest.raises(PermissionError):
        accounting.create_manual_entry({}, SALES)


def test_period_report_has_opening_and_movement_separate(finance):
    document(finance, "100")
    payment(finance, "70", payment_date="2026-02-01")
    report = accounting.financial_report(ACTOR, "2026-02-01", "2026-02-28")
    row = next(row for row in report["trial_balance"] if row["code"] == "1122")
    assert (row["opening"], row["debit"], row["credit"], row["closing"]) == ("100.00", "0.00", "70.00", "30.00")
    assert report["profit_loss"]["revenue"] == "0.00"


def test_manual_create_idempotency_prevents_duplicate_entries(finance):
    first = manual(finance, idempotency_key="manual-expense-unique")
    replay = manual(finance, idempotency_key="manual-expense-unique")
    assert first == replay
    assert accounting.list_entries(ACTOR)["total"] == 1
    with pytest.raises(ledger.FinanceConflictError):
        manual(finance, idempotency_key="manual-expense-unique", description="different")


def test_inconsistent_duplicate_inside_bank_batch_is_rejected(finance):
    body = bank_rows(finance)
    body["rows"].append({**body["rows"][0], "amount": "75"})
    with pytest.raises(accounting.AccountingConflict):
        accounting.import_bank_transactions(body, ACTOR)
    assert accounting.list_bank_transactions(ACTOR)["total"] == 0


def test_opening_prepayment_cannot_match_bank_statement(finance):
    pay = payment(finance, "70", is_opening=True, payment_date="2026-01-01")
    accounting.import_bank_transactions(bank_rows(finance), ACTOR)
    bank = accounting.list_bank_transactions(ACTOR)["items"][0]
    with pytest.raises(ValueError, match="期初"):
        accounting.bank_action(bank["id"], "match", {"version": bank["version"], "payment_id": pay["id"]}, ACTOR)


def test_accounting_migration_roundtrip_matches_model_columns():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from data.finance.accounting import FinanceGLAccount, FinancePeriod, FinanceJournalLine
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_027d8e9f0a1b_finance_accounting.py"
    spec = importlib.util.spec_from_file_location("accounting_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE finance_accounts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE finance_payments (id INTEGER PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for model in (FinanceSettings, FinanceGLAccount, FinancePeriod, FinanceJournalEntry, FinanceJournalLine, FinanceBankTransaction):
            columns = {row["name"] for row in inspect(connection).get_columns(model.__tablename__)}
            assert columns == {column.name for column in model.__table__.columns}
        migration.downgrade()
        assert sorted(inspect(connection).get_table_names()) == ["finance_accounts", "finance_payments"]


def test_partner_statement_includes_opening_credits_and_unallocated_cash(finance):
    document(finance, "100")
    payment(finance, "70", payment_date="2026-02-01")
    statement = accounting.partner_statement(ACTOR, "customer", finance["customer"], "2026-02-01", "2026-02-28")
    assert statement["opening_balance"] == "100.00"
    assert statement["total_decrease"] == "70.00"
    assert statement["closing_balance"] == "30.00"
    assert len(statement["items"]) == 1
    assert statement["items"][0]["source_type"] == "finance_payment"
    assert statement["items"][0]["balance"] == "30.00"


def test_supplier_statement_uses_payable_sign(finance):
    document(finance, "100", kind="vendor_bill")
    payment(finance, "60", partner_type="vendor", direction="outgoing")
    statement = accounting.partner_statement(ACTOR, "vendor", finance["vendor"]["id"], "2026-01-01", "2026-01-31")
    assert statement["total_increase"] == "100.00"
    assert statement["total_decrease"] == "60.00"
    assert statement["closing_balance"] == "40.00"


def test_statement_api_permissions_and_safe_export(finance, client):
    from Auth import create_jwt
    from data.customer.Customer import CustomerTable
    with TestSessionFactory() as session:
        session.get(CustomerTable, finance["customer"]).name = '=HYPERLINK("unsafe")'
        session.commit()
    path = f"/api/finance/v2/accounting/partner-statement?partner_type=customer&partner_id={finance['customer']}&date_from=2026-01-01&date_to=2026-01-31"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"x-token": create_jwt(SALES)}).status_code == 403
    result = client.get(path.replace('partner-statement?', 'partner-statement/export?'), headers={"x-token": create_jwt(ACTOR)})
    assert result.status_code == 200
    assert "'=HYPERLINK" in result.data.decode("utf-8")


def test_period_and_bank_history_are_scoped_and_protected(finance, client):
    from Auth import create_jwt
    period = accounting.list_periods(ACTOR)[0]
    accounting.import_bank_transactions(bank_rows(finance), ACTOR)
    bank = accounting.list_bank_transactions(ACTOR)["items"][0]
    headers = {"x-token": create_jwt(ACTOR)}
    for path, expected_target, target_id in (
        (f"/api/finance/v2/accounting/periods/{period['id']}/history", "finance_period", period["id"]),
        (f"/api/finance/v2/accounting/bank-transactions/{bank['id']}/history", "finance_bank_transaction", bank["id"]),
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"x-token": create_jwt(SALES)}).status_code == 403
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        result = response.get_json()["data"]
        assert result["history_complete"] is True
        assert result["items"]
        assert all(item["target_type"] == expected_target and item["target_id"] == str(target_id) for item in result["items"])
    assert client.get('/api/finance/v2/accounting/periods/999999/history', headers=headers).status_code == 404
