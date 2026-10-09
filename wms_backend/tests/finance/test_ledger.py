"""Financial invariants exercised against actual ORM transactions and journal hooks."""
import importlib.util
from pathlib import Path
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from Auth import create_jwt
from data.database import Base
from data.customer.Customer import CustomerTable
from data.DB import AuditLogTable, OrderTable
from data.finance.ledger import FinanceAllocation, FinanceDocument, FinancePayment
from data.finance.accounting import FinanceJournalEntry, FinancePeriod, FinanceSettings
from services import finance_ledger_service as ledger
from services import finance_accounting_service as accounting
from tests.conftest import TestSessionFactory, test_engine
from utils import audit


ACTOR = {"id": 701, "user_id": 701, "name": "财务复核", "roles": ["finance"]}
SALES = {"id": 702, "name": "业务员", "roles": ["salesperson"]}


@pytest.fixture
def finance(monkeypatch):
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(ledger, "SessionFactory", TestSessionFactory)
    monkeypatch.setattr(accounting, "SessionFactory", TestSessionFactory)
    monkeypatch.setattr(audit, "SessionFactory", TestSessionFactory)
    with TestSessionFactory() as session:
        first, second = CustomerTable(name="甲客户"), CustomerTable(name="乙客户")
        session.add_all([first, second])
        session.commit()
        customer, other_customer = first.id, second.id
    accounting.configure({"company_name": "财务闭环测试", "opening_date": "2026-01-01", "revenue_policy": "invoice"}, ACTOR)
    accounting.create_period({"name": "测试会计期间", "date_from": "2026-01-01", "date_to": "2026-12-31"}, ACTOR)
    account = ledger.save_master("accounts", {"name": "公司银行", "account_type": "bank", "account_number": "TEST-001"}, ACTOR)
    vendor = ledger.save_master("vendors", {"name": "承运商"}, ACTOR)
    return {"customer": customer, "other_customer": other_customer, "account": account, "vendor": vendor}


def document(finance, amount="100.00", kind="customer_invoice", post=True, **extra):
    partner = finance["customer"] if kind.startswith("customer") else finance["vendor"]["id"]
    row = ledger.create_document({"document_type": kind, "partner_id": partner,
        "document_date": "2026-01-05", "due_date": "2026-01-20",
        "lines": [{"description": "运输服务", "quantity": "1", "unit_price": amount}], **extra}, ACTOR)
    return ledger.post_document(row["id"], {"version": row["version"]}, ACTOR) if post else row


def payment(finance, amount="100.00", partner_type="customer", direction="incoming", post=True, **extra):
    partner = finance["customer"] if partner_type == "customer" else finance["vendor"]["id"]
    row = ledger.create_payment({"direction": direction, "partner_type": partner_type, "partner_id": partner,
        "account_id": finance["account"]["id"], "payment_date": "2026-01-10", "amount": amount, **extra}, ACTOR)
    return ledger.post_payment(row["id"], {"version": row["version"]}, ACTOR) if post else row


def allocate(pay, doc, amount, **extra):
    pay = ledger.get_payment(pay["id"], ACTOR)
    return ledger.create_allocations({"payment_id": pay["id"], "version": pay["version"], "allocation_date": "2026-01-12",
        "allocations": [{"document_id": doc["id"], "amount": amount}], **extra}, ACTOR)


def test_document_decimal_totals_snapshot_and_post_freeze(finance):
    row = document(finance, post=False, lines=[{"description": "运费", "quantity": "3.0000", "unit_price": "0.3333", "tax_rate": "6"}])
    assert row["subtotal"] == "1.00"
    assert row["tax_amount"] == "0.06"
    assert row["total_amount"] == "1.06"
    updated = ledger.update_document(row["id"], {"version": row["version"], "memo": "核实"}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.update_document(row["id"], {"version": row["version"], "memo": "过期修改"}, ACTOR)
    posted = ledger.post_document(row["id"], {"version": updated["version"]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.update_document(row["id"], {"version": posted["version"], "lines": [{"description": "改价", "unit_price": 999}]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.cancel_document(row["id"], {"version": posted["version"], "reason": "不能删除事实"}, ACTOR)
    with TestSessionFactory() as session:
        entry = session.query(FinanceJournalEntry).filter_by(source_type="finance_document", source_id=str(row["id"])).one()
        assert sum(line.debit for line in entry.lines) == sum(line.credit for line in entry.lines)
        assert sum(line.debit for line in entry.lines) == Decimal("1.06")


def test_draft_line_edit_replaces_lines_and_preserves_audit(finance):
    row = document(finance, post=False)
    edited = ledger.update_document(row["id"], {"version": row["version"], "lines": [{"description": "改后运费", "quantity": 2, "unit_price": 30}]}, ACTOR)
    assert edited["total_amount"] == "60.00"
    assert len(edited["lines"]) == 1
    events = ledger.history("documents", row["id"], ACTOR)
    assert events["history_complete"] is True
    assert {row["action"] for row in events["items"]} == {"create", "update"}


def test_one_payment_multiple_invoices_and_remaining_advance(finance):
    first, second = document(finance, "100"), document(finance, "50")
    pay = payment(finance, "200")
    result = ledger.create_allocations({"payment_id": pay["id"], "version": pay["version"], "allocation_date": "2026-01-12",
        "allocations": [{"document_id": first["id"], "amount": "100"}, {"document_id": second["id"], "amount": "30"}]}, ACTOR)
    assert result["source"]["unallocated_amount"] == "70.00"
    assert ledger.get_document(first["id"], ACTOR)["payment_status"] == "paid"
    assert ledger.get_document(second["id"], ACTOR)["residual_amount"] == "20.00"
    metrics = ledger.dashboard(ACTOR, "2026-01-15")
    assert metrics["receivable"] == "20.00"
    assert metrics["customer_advances"] == "70.00"
    assert metrics["account_balance"] == "200.00"


def test_multiple_payments_one_invoice_and_no_overallocation(finance):
    doc = document(finance)
    first, second = payment(finance, "60"), payment(finance, "60")
    allocate(first, doc, "60")
    with pytest.raises(ValueError, match="余额不足"):
        allocate(second, doc, "60")
    assert ledger.get_payment(second["id"], ACTOR)["unallocated_amount"] == "60.00"
    allocate(second, doc, "40")
    assert ledger.get_document(doc["id"], ACTOR)["residual_amount"] == "0.00"


def test_allocation_batch_rolls_back_every_target_if_one_is_invalid(finance):
    first = document(finance)
    second = document(finance, partner_id=finance["other_customer"])
    pay = payment(finance, "200")
    with pytest.raises(ValueError, match="同一往来"):
        ledger.create_allocations({"payment_id": pay["id"], "version": pay["version"], "allocation_date": "2026-01-12",
            "allocations": [{"document_id": first["id"], "amount": "50"}, {"document_id": second["id"], "amount": "50"}]}, ACTOR)
    assert ledger.get_document(first["id"], ACTOR)["residual_amount"] == "100.00"
    assert ledger.get_payment(pay["id"], ACTOR)["unallocated_amount"] == "200.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).count() == 0


def test_allocation_reversal_keeps_as_of_balances_and_releases_cash(finance):
    doc, pay = document(finance), payment(finance)
    allocation = allocate(pay, doc, "60")["items"][0]
    ledger.reverse_allocation(allocation["id"], {"version": allocation["version"], "reason": "核销错单", "reversal_date": "2026-02-01"}, ACTOR)
    assert ledger.aging(ACTOR, as_of="2026-01-31")["totals"]["total"] == "40.00"
    assert ledger.aging(ACTOR, as_of="2026-02-01")["totals"]["total"] == "100.00"
    assert ledger.get_payment(pay["id"], ACTOR)["unallocated_amount"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).one().status == "reversed"


def test_backdated_allocation_cannot_overdraw_a_historical_balance(finance):
    doc, pay = document(finance), payment(finance)
    allocation = allocate(pay, doc, "100")["items"][0]
    ledger.reverse_allocation(allocation["id"], {"version": allocation["version"], "reason": "重新分配", "reversal_date": "2026-02-01"}, ACTOR)
    with pytest.raises(ValueError, match="历史"):
        allocate(pay, doc, "100", allocation_date="2026-01-20")
    allocate(pay, doc, "100", allocation_date="2026-02-01")


def test_unallocated_payment_is_advance_then_can_be_reversed(finance):
    pay = payment(finance, "130")
    assert ledger.dashboard(ACTOR, "2026-01-20")["customer_advances"] == "130.00"
    reversed_payment = ledger.reverse_payment(pay["id"], {"version": pay["version"], "reason": "重复登记", "payment_date": "2026-02-01"}, ACTOR)
    assert reversed_payment["status"] == "reversed"
    assert ledger.dashboard(ACTOR, "2026-01-31")["account_balance"] == "130.00"
    assert ledger.dashboard(ACTOR, "2026-02-01")["account_balance"] == "0.00"
    with TestSessionFactory() as session:
        entries = session.query(FinanceJournalEntry).all()
        assert len(entries) == 2
        assert {row.status for row in entries} == {"posted", "reversed"}


def test_allocated_payment_must_unallocate_before_reverse(finance):
    doc, pay = document(finance), payment(finance)
    allocate(pay, doc, "50")
    pay = ledger.get_payment(pay["id"], ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="全部核销"):
        ledger.reverse_payment(pay["id"], {"version": pay["version"], "reason": "误登记", "payment_date": "2026-02-01"}, ACTOR)


def test_full_reversal_offsets_unpaid_invoice_without_deleting_original(finance):
    doc = document(finance)
    result = ledger.reverse_document(doc["id"], {"version": doc["version"], "document_date": "2026-02-01", "reason": "原账单重复"}, ACTOR)
    assert result["document"]["status"] == "posted"
    assert result["document"]["reversed_by_id"] == result["credit"]["id"]
    assert result["document"]["residual_amount"] == "0.00"
    assert result["credit"]["residual_amount"] == "0.00"
    assert ledger.dashboard(ACTOR, "2026-01-31")["receivable"] == "100.00"
    assert ledger.dashboard(ACTOR, "2026-02-01")["receivable"] == "0.00"


def test_paid_invoice_credit_supports_partial_refund_and_offset(finance):
    doc, pay = document(finance), payment(finance)
    allocate(pay, doc, "100")
    credit = document(finance, "40", kind="customer_credit", original_document_id=doc["id"], document_date="2026-02-01", due_date="2026-02-01")
    refund = payment(finance, "15", direction="outgoing", payment_date="2026-02-02")
    allocate(refund, credit, "15", allocation_date="2026-02-02")
    next_doc = document(finance, "100", document_date="2026-02-02", due_date="2026-02-20")
    credit = ledger.get_document(credit["id"], ACTOR)
    ledger.create_allocations({"credit_document_id": credit["id"], "version": credit["version"], "allocation_date": "2026-02-03",
        "allocations": [{"document_id": next_doc["id"], "amount": "25"}]}, ACTOR)
    assert ledger.get_document(credit["id"], ACTOR)["residual_amount"] == "0.00"
    assert ledger.get_document(next_doc["id"], ACTOR)["residual_amount"] == "75.00"
    metrics = ledger.dashboard(ACTOR, "2026-02-04")
    assert metrics["account_balance"] == "85.00"
    assert metrics["customer_credit"] == "0.00"


def test_vendor_prepayment_bill_credit_and_refund(finance):
    prepaid = payment(finance, "200", partner_type="vendor", direction="outgoing")
    bill = document(finance, "150", kind="vendor_bill")
    allocate(prepaid, bill, "150")
    assert ledger.dashboard(ACTOR, "2026-01-20")["vendor_prepayments"] == "50.00"
    credit = document(finance, "30", kind="vendor_credit", original_document_id=bill["id"])
    refund = payment(finance, "30", partner_type="vendor", direction="incoming")
    allocate(refund, credit, "30")
    assert ledger.get_document(credit["id"], ACTOR)["payment_status"] == "paid"
    assert ledger.dashboard(ACTOR, "2026-01-20")["account_balance"] == "-170.00"


def test_credit_cannot_exceed_original_total_and_no_partial_side_effect(finance):
    original = document(finance)
    document(finance, "70", kind="customer_credit", original_document_id=original["id"])
    excessive = document(finance, "40", kind="customer_credit", original_document_id=original["id"], post=False)
    with pytest.raises(ValueError, match="累计贷项"):
        ledger.post_document(excessive["id"], {"version": excessive["version"]}, ACTOR)
    assert ledger.get_document(excessive["id"], ACTOR)["status"] == "draft"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 2


def test_idempotent_create_and_post_replay_but_changed_payload_conflicts(finance):
    body = {"document_type": "customer_invoice", "partner_id": finance["customer"], "document_date": "2026-01-05",
        "lines": [{"description": "运费", "unit_price": "100"}], "idempotency_key": "invoice-A"}
    first = ledger.create_document(body, ACTOR)
    assert ledger.create_document(body, ACTOR) == first
    with pytest.raises(ledger.FinanceConflictError, match="幂等键"):
        ledger.create_document({**body, "memo": "不同请求"}, ACTOR)
    command = {"version": first["version"], "idempotency_key": "post-A"}
    posted = ledger.post_document(first["id"], command, ACTOR)
    assert ledger.post_document(first["id"], command, ACTOR) == posted
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceJournalEntry).count() == 1


def test_audit_failure_rolls_back_posted_document_and_journal(finance, monkeypatch):
    row = document(finance, post=False)
    original_audit = ledger.record_audit
    def failing_audit(**kwargs):
        if kwargs["action"] == "post":
            raise RuntimeError("audit unavailable")
        return original_audit(**kwargs)
    monkeypatch.setattr(ledger, "record_audit", failing_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        ledger.post_document(row["id"], {"version": row["version"]}, ACTOR)
    assert ledger.get_document(row["id"], ACTOR)["status"] == "draft"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0
        assert session.query(AuditLogTable).filter_by(target_type="finance_document", action="post").count() == 0


def test_closed_period_blocks_post_allocation_and_reversal(finance):
    doc, pay = document(finance), payment(finance)
    allocation = allocate(pay, doc, "30")["items"][0]
    draft = document(finance, post=False)
    with TestSessionFactory() as session:
        session.query(FinancePeriod).one().status = "closed"
        session.commit()
    with pytest.raises(ValueError, match="关账"):
        ledger.post_document(draft["id"], {"version": draft["version"]}, ACTOR)
    with pytest.raises(ValueError, match="关账"):
        allocate(pay, doc, "20")
    with pytest.raises(ValueError, match="关账"):
        ledger.reverse_allocation(allocation["id"], {"version": allocation["version"], "reason": "错单", "reversal_date": "2026-02-01"}, ACTOR)
    assert ledger.get_document(doc["id"], ACTOR)["residual_amount"] == "70.00"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", True, None, "999999999999999999999"])
def test_invalid_money_is_rejected_without_persistence(finance, value):
    with pytest.raises(ValueError):
        document(finance, amount=value, post=False)
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0


def test_customer_archive_and_order_change_cannot_change_document_snapshot(finance):
    with TestSessionFactory() as session:
        order = OrderTable(uid="finance-snapshot-order", order_id="OLD-001", customer_name="甲客户", archive=False)
        session.add(order)
        session.commit()
    row = document(finance, lines=[{"description": "按订单计费", "unit_price": "200", "order_uid": "finance-snapshot-order"}])
    with TestSessionFactory() as session:
        order = session.query(OrderTable).filter_by(uid="finance-snapshot-order").one()
        order.order_id, order.archive = "NEW-001", True
        session.query(CustomerTable).filter_by(id=finance["customer"]).one().name = "客户已改名"
        session.commit()
    snapshot = ledger.get_document(row["id"], ACTOR)
    assert snapshot["partner_name"] == "甲客户"
    assert snapshot["lines"][0]["order_number"] == "OLD-001"
    assert ledger.aging(ACTOR, as_of="2026-02-28")["totals"]["total"] == "200.00"


def test_aging_buckets_include_old_balances_and_open_filters(finance):
    document(finance, "100", due_date="2026-01-05")
    document(finance, "50", due_date="2026-03-01")
    result = ledger.aging(ACTOR, as_of="2026-02-20")
    assert result["totals"]["days_31_60"] == "100.00"
    assert result["totals"]["current"] == "50.00"
    assert result["totals"]["total"] == "150.00"
    assert ledger.list_documents(ACTOR, open_only=1)["total"] == 2


def test_master_identity_frozen_after_post_and_disable_blocks_new_post(finance):
    payment(finance)
    account = finance["account"]
    with pytest.raises(ledger.FinanceConflictError, match="账号"):
        ledger.save_master("accounts", {"version": account["version"], "account_number": "DIFFERENT"}, ACTOR, account["id"])
    updated = ledger.save_master("accounts", {"version": account["version"], "name": "公司基本户", "active": False}, ACTOR, account["id"])
    assert updated["active"] is False
    with pytest.raises(ValueError, match="停用"):
        payment(finance)


def test_api_denies_business_user_and_supports_history(finance, client):
    sales_headers = {"x-token": create_jwt(SALES)}
    headers = {"x-token": create_jwt(ACTOR)}
    assert client.get("/api/finance/v2/documents", headers=sales_headers).status_code == 403
    assert client.get("/api/finance/v2/dashboard").status_code == 401
    row = document(finance, post=False)
    result = client.get(f"/api/finance/v2/documents/{row['id']}/history", headers=headers)
    assert result.status_code == 200
    assert result.get_json()["data"]["history_complete"] is True
    stale = client.patch(f"/api/finance/v2/documents/{row['id']}", json={"version": 999, "memo": "bad"}, headers=headers)
    assert stale.status_code == 409
    bad = client.post("/api/finance/v2/documents", json=[], headers=headers)
    assert bad.status_code == 400
    with pytest.raises(PermissionError):
        ledger.get_document(row["id"], SALES)


def test_subledger_migration_upgrade_and_downgrade():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_f16c7d8e9f0a_finance_subledger.py"
    spec = importlib.util.spec_from_file_location("finance_subledger_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, target_type VARCHAR(64), target_id VARCHAR(128))"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        names = inspect(connection).get_table_names()
        assert len(names) == 8
        assert "finance_allocations" in names
        assert "reversal_date" in {row["name"] for row in inspect(connection).get_columns("finance_payments")}
        migration.downgrade()
        assert inspect(connection).get_table_names() == ["audit_logs"]


def test_paid_invoice_credit_cannot_be_refunded_twice(finance):
    doc, pay = document(finance), payment(finance)
    allocate(pay, doc, "100")
    credit = document(finance, "20", kind="customer_credit", original_document_id=doc["id"])
    refund = payment(finance, "20", direction="outgoing")
    with pytest.raises(ValueError, match="可退余额"):
        payment(finance, "20", direction="outgoing")
    allocate(refund, credit, "20")
    with pytest.raises(ValueError, match="可退余额"):
        payment(finance, "1", direction="outgoing")
    assert ledger.dashboard(ACTOR, "2026-01-20")["account_balance"] == "80.00"


def test_advance_refund_reserves_funds_against_second_refund_and_allocation(finance):
    advance = payment(finance)
    payment(finance, "60", direction="outgoing")
    with pytest.raises(ValueError, match="可退余额"):
        payment(finance, "50", direction="outgoing")
    doc = document(finance)
    with pytest.raises(ValueError, match="退款"):
        allocate(advance, doc, "100")
    allocate(advance, doc, "40")
    metrics = ledger.dashboard(ACTOR, "2026-01-20")
    assert metrics["customer_advances"] == "0.00"
    assert metrics["receivable"] == "60.00"
    assert metrics["account_balance"] == "40.00"


def test_refund_cannot_be_backdated_before_available_funds(finance):
    payment(finance)
    with pytest.raises(ValueError, match="历史可退"):
        payment(finance, "30", direction="outgoing", payment_date="2026-01-09")


def test_master_history_endpoints_are_audited_and_protected(finance, client):
    headers = {"x-token": create_jwt(ACTOR)}
    for kind, row_id in (("accounts", finance["account"]["id"]), ("vendors", finance["vendor"]["id"])):
        response = client.get(f"/api/finance/v2/{kind}/{row_id}/history", headers=headers)
        assert response.status_code == 200
        assert response.get_json()["data"]["items"][0]["action"] == "create"
        assert client.get(f"/api/finance/v2/{kind}/{row_id}/history", headers={"x-token": create_jwt(SALES)}).status_code == 403


def test_fund_balances_include_opening_manual_entries_and_exclude_drafts(finance):
    opening = accounting.create_manual_entry({"kind": "opening", "entry_date": "2026-01-01", "description": "银行期初",
        "lines": [{"account_code": "1002", "fund_account_id": finance["account"]["id"], "debit": "1000"},
                  {"account_code": "4104", "credit": "1000"}]}, ACTOR)
    assert ledger.dashboard(ACTOR, "2026-01-01")["account_balance"] == "0.00"
    accounting.entry_action(opening["id"], "post", {"version": opening["version"]}, ACTOR)
    payment(finance, "100")
    assert ledger.dashboard(ACTOR, "2026-01-01")["account_balance"] == "1000.00"
    assert ledger.dashboard(ACTOR, "2026-01-20")["account_balance"] == "1100.00"
    assert ledger.dashboard(ACTOR, "2026-01-20")["posted_receipts"] == "100.00"
    assert ledger.list_masters("accounts", ACTOR)["items"][0]["balance"] == "1100.00"


@pytest.mark.parametrize("usage", ["journal", "bank"])
def test_account_identity_freezes_for_journal_and_bank_usage(finance, usage):
    account = finance["account"]
    if usage == "journal":
        accounting.create_manual_entry({"kind": "opening", "entry_date": "2026-01-01", "description": "期初核对中",
            "lines": [{"account_code": "1002", "fund_account_id": account["id"], "debit": "100"},
                      {"account_code": "4104", "credit": "100"}]}, ACTOR)
    else:
        accounting.import_bank_transactions({"account_id": account["id"], "rows": [{"reference": "BANK-001", "transaction_date": "2026-01-02", "amount": "100"}]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="账号"):
        ledger.save_master("accounts", {"version": account["version"], "account_number": "DIFFERENT"}, ACTOR, account["id"])


@pytest.mark.parametrize("credit_price,credit_tax,error", [("106", "0", "不含税"), ("10", "100", "税额")])
def test_credit_cannot_overreverse_net_or_tax_component(finance, credit_price, credit_tax, error):
    original = document(finance, lines=[{"description": "含税运费", "unit_price": "100", "tax_rate": "6"}])
    credit = document(finance, kind="customer_credit", original_document_id=original["id"], post=False,
        lines=[{"description": "贷项", "unit_price": credit_price, "tax_rate": credit_tax}])
    with pytest.raises(ValueError, match=error):
        ledger.post_document(credit["id"], {"version": credit["version"]}, ACTOR)
    assert ledger.get_document(credit["id"], ACTOR)["status"] == "draft"


def test_opening_invoice_preserves_prior_due_date_and_does_not_create_revenue(finance):
    opening = document(finance, is_opening=True, document_date="2026-01-01", due_date="2025-10-31")
    assert opening["is_opening"] is True
    assert ledger.aging(ACTOR, as_of="2026-01-01")["totals"]["days_61_90"] == "100.00"
    with TestSessionFactory() as session:
        entry = session.query(FinanceJournalEntry).filter_by(source_type="finance_document", source_id=str(opening["id"])).one()
        assert {line.account_code for line in entry.lines} == {"1122", "4104"}
    with pytest.raises(ValueError, match="建账日期"):
        document(finance, is_opening=True)
    with pytest.raises(ValueError, match="仅客户账单"):
        document(finance, is_opening=True, kind="customer_credit", original_document_id=opening["id"], document_date="2026-01-01", due_date="2026-01-01")


def test_opening_advance_does_not_double_count_funds(finance):
    advance = payment(finance, "60", is_opening=True, payment_date="2026-01-01")
    assert advance["is_opening"] is True
    metrics = ledger.dashboard(ACTOR, "2026-01-01")
    assert metrics["customer_advances"] == "60.00"
    assert metrics["posted_receipts"] == "0.00"
    assert metrics["account_balance"] == "0.00"
    with TestSessionFactory() as session:
        entry = session.query(FinanceJournalEntry).filter_by(source_type="finance_payment", source_id=str(advance["id"])).one()
        assert {line.account_code for line in entry.lines} == {"1122", "4104"}
    with pytest.raises(ValueError, match="期初结算"):
        payment(finance, is_opening=True, direction="outgoing", payment_date="2026-01-01")


def test_opening_confirmation_blocks_new_and_preexisting_drafts(finance):
    draft = document(finance, is_opening=True, document_date="2026-01-01", due_date="2026-01-20", post=False)
    advance = payment(finance, is_opening=True, payment_date="2026-01-01", post=False)
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_confirmed = True
        session.commit()
    with pytest.raises(ledger.FinanceConflictError, match="期初余额已确认"):
        ledger.post_document(draft["id"], {"version": draft["version"]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="期初余额已确认"):
        ledger.post_payment(advance["id"], {"version": advance["version"]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="期初余额已确认"):
        document(finance, is_opening=True, document_date="2026-01-01")


def test_payment_reversal_cannot_retroactively_remove_refunded_money(finance):
    original = payment(finance, "100", payment_date="2026-01-10")
    payment(finance, "100", direction="outgoing", payment_date="2026-01-20")
    payment(finance, "100", payment_date="2026-02-01")
    with pytest.raises(ValueError, match="历史已退款"):
        ledger.reverse_payment(original["id"], {"version": original["version"], "reason": "误登记", "payment_date": "2026-01-15"}, ACTOR)
    assert ledger.get_payment(original["id"], ACTOR)["status"] == "posted"


def test_available_amount_respects_refund_reservation_and_inactive_vendor_lookup(finance):
    advance = payment(finance)
    payment(finance, "60", direction="outgoing")
    row = ledger.get_payment(advance["id"], ACTOR)
    assert row["unallocated_amount"] == "100.00"
    assert row["available_amount"] == "40.00"
    vendor = finance["vendor"]
    ledger.save_master("vendors", {"version": vendor["version"], "active": False}, ACTOR, vendor["id"])
    assert ledger.list_partners(ACTOR, "vendor")["total"] == 0
    assert ledger.list_partners(ACTOR, "vendor", include_inactive=True)["total"] == 1
