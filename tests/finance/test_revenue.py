"""Deferred revenue remains linked to its invoice and subsequent credit notes."""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from Auth import create_jwt
from data.finance.accounting import FinanceJournalEntry, FinancePeriod
from data.finance.ledger import FinanceDocument
from services import finance_accounting_service as accounting
from services import finance_ledger_service as ledger
from services import finance_revenue_service as revenue
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import ACTOR, SALES, finance, document


@pytest.fixture
def deferred_finance(finance):
    settings = accounting.get_settings(ACTOR)
    accounting.configure({**settings, "revenue_policy": "deferred"}, ACTOR)
    return finance


def recognize(doc, amount, **extra):
    current = ledger.get_document(doc["id"], ACTOR)
    return revenue.recognize(doc["id"], {"version": current["version"], "amount": amount,
        "recognition_date": "2026-01-15", "reason": "客户已确认运输服务完成",
        "idempotency_key": uuid4().hex, **extra}, ACTOR)


def reverse(entry, **extra):
    return revenue.reverse(entry["id"], {"version": entry["version"], "reversal_date": "2026-02-01",
        "reason": "履约确认日期有误", "idempotency_key": uuid4().hex, **extra}, ACTOR)


def test_partial_recognition_posts_balanced_entries_and_updates_invoice_history(deferred_finance):
    doc = document(deferred_finance)
    first = recognize(doc, "40")
    assert first["invoice"]["deferred_amount"] == "60.00"
    assert first["invoice"]["recognized_amount"] == "40.00"
    second = recognize(doc, "60")
    assert second["invoice"]["deferred_amount"] == "0.00"
    assert len(second["invoice"]["entries"]) == 2
    assert revenue.list_invoices(ACTOR)["total"] == 0
    assert revenue.list_invoices(ACTOR, open_only=False)["total"] == 1
    report = accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")
    assert report["profit_loss"]["revenue"] == "100.00"
    assert report["balance_sheet"]["difference"] == "0.00"
    events = ledger.history("documents", doc["id"], ACTOR)["items"]
    assert len([row for row in events if row["action"] == "revenue_recognize"]) == 2
    with pytest.raises(ValueError, match="待履约余额"):
        recognize(doc, "0.01")


def test_reversal_restores_deferred_and_preserves_previous_cutoff(deferred_finance):
    doc = document(deferred_finance)
    result = recognize(doc, "60")
    reversed_result = reverse(result["entry"])
    assert reversed_result["invoice"]["deferred_amount"] == "100.00"
    assert reversed_result["invoice"]["recognized_amount"] == "0.00"
    assert reversed_result["invoice"]["entries"][0]["status"] == "reversed"
    assert accounting.financial_report(ACTOR, "2026-01-01", "2026-01-31")["profit_loss"]["revenue"] == "60.00"
    assert accounting.financial_report(ACTOR, "2026-01-01", "2026-02-28")["profit_loss"]["revenue"] == "0.00"
    with pytest.raises(ledger.FinanceConflictError):
        reverse(result["entry"])


def test_credit_consumes_deferred_then_revenue_and_blocks_destructive_reversal(deferred_finance):
    doc = document(deferred_finance)
    result = recognize(doc, "80")
    document(deferred_finance, "50", kind="customer_credit", original_document_id=doc["id"], document_date="2026-02-01", due_date="2026-02-01")
    current = revenue.get_invoice(doc["id"], ACTOR)
    assert current["deferred_amount"] == "0.00"
    assert current["recognized_amount"] == "50.00"
    with pytest.raises(ValueError, match="负收入"):
        reverse(result["entry"], reversal_date="2026-02-02")
    with TestSessionFactory() as session:
        assert session.get(FinanceJournalEntry, result["entry"]["id"]).status == "posted"


def test_credit_within_deferred_still_allows_reversal(deferred_finance):
    doc = document(deferred_finance)
    result = recognize(doc, "40")
    document(deferred_finance, "20", kind="customer_credit", original_document_id=doc["id"], document_date="2026-01-20")
    restored = reverse(result["entry"])
    assert restored["invoice"]["deferred_amount"] == "80.00"
    assert restored["invoice"]["recognized_amount"] == "0.00"


def test_backdated_credit_cannot_create_negative_income_before_recognition(deferred_finance):
    doc = document(deferred_finance)
    recognize(doc, "80", recognition_date="2026-02-01")
    with pytest.raises(ValueError, match="历史"):
        document(deferred_finance, "50", kind="customer_credit", original_document_id=doc["id"], document_date="2026-01-10")
    assert revenue.get_invoice(doc["id"], ACTOR)["recognized_amount"] == "80.00"


def test_recognition_rejects_stale_version_and_replays_identical_command(deferred_finance):
    doc = document(deferred_finance)
    body = {"version": doc["version"], "amount": "20", "recognition_date": "2026-01-10", "reason": "履约完成", "idempotency_key": "recognize-once"}
    first = revenue.recognize(doc["id"], body, ACTOR)
    assert revenue.recognize(doc["id"], body, ACTOR) == first
    with pytest.raises(ledger.FinanceConflictError):
        revenue.recognize(doc["id"], {**body, "idempotency_key": "different-request"}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        revenue.recognize(doc["id"], {**body, "amount": "21"}, ACTOR)
    assert len(revenue.get_invoice(doc["id"], ACTOR)["entries"]) == 1


def test_recognition_audit_failure_rolls_back_entry_and_document_version(deferred_finance):
    doc = document(deferred_finance)
    with patch.object(revenue, "record_audit", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError, match="audit unavailable"):
            recognize(doc, "50")
    assert revenue.get_invoice(doc["id"], ACTOR)["deferred_amount"] == "100.00"
    assert ledger.get_document(doc["id"], ACTOR)["version"] == doc["version"]
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(kind="revenue").count() == 0


def test_dates_and_closed_period_cannot_be_bypassed(deferred_finance):
    doc = document(deferred_finance)
    with pytest.raises(ValueError, match="早于账单"):
        recognize(doc, "20", recognition_date="2026-01-04")
    with TestSessionFactory() as session:
        session.query(FinancePeriod).one().status = "closed"
        session.commit()
    with pytest.raises(ValueError, match="关账"):
        recognize(doc, "20")


def test_backdated_recognition_cannot_overdraw_after_later_recognition(deferred_finance):
    doc = document(deferred_finance)
    recognize(doc, "80", recognition_date="2026-02-01")
    with pytest.raises(ValueError, match="待履约余额"):
        recognize(doc, "30", recognition_date="2026-01-10")


def test_invoice_revenue_policy_does_not_double_recognize(finance):
    doc = document(finance)
    with pytest.raises(ValueError, match="无需重复"):
        recognize(doc, "20")


def test_read_write_routes_enforce_finance_permissions(client, deferred_finance):
    doc = document(deferred_finance)
    headers = {"x-token": create_jwt(SALES)}
    assert client.get("/api/finance/v2/revenue", headers=headers).status_code == 403
    assert client.get(f"/api/finance/v2/revenue/{doc['id']}", headers=headers).status_code == 403
    assert client.post(f"/api/finance/v2/revenue/{doc['id']}/recognize", headers=headers, json={}).status_code == 403
    assert client.get("/api/finance/v2/revenue", headers={"x-token": create_jwt(ACTOR)}).get_json()["data"]["total"] == 1
    with pytest.raises(PermissionError):
        revenue.get_invoice(doc["id"], SALES)
    with pytest.raises(PermissionError):
        revenue.recognize(doc["id"], {}, SALES)
    with pytest.raises(PermissionError):
        revenue.reverse(1, {}, SALES)
