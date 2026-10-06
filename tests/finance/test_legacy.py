"""Reviewed legacy cutover tests: net balances, provenance, drift and matched proof."""
import importlib.util
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from Auth import create_jwt
from data.DB import CargoTable, OrderTable, OrderQuoteVersionTable, OrderPriceAdjustmentTable, PaymentReceiptTable, PaymentReceiptItemTable
from data.finance.legacy import FinanceLegacyLink, FinanceLegacyEvidence
from data.finance.ledger import FinanceDocument, FinancePayment
from data.finance.accounting import FinanceJournalEntry, FinanceSettings
from services import finance_legacy_service as service
from services import finance_ledger_service as ledger
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import finance, ACTOR, SALES, document, payment


TODAY = "2026-10-05"


@pytest.fixture
def legacy(finance, monkeypatch):
    monkeypatch.setattr(service, "SessionFactory", TestSessionFactory)
    monkeypatch.setattr(ledger, "_today", lambda: TODAY)
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_date = TODAY
        from data.customer.Customer import CustomerTable
        customer = session.get(CustomerTable, finance["customer"])
        order = OrderTable(uid="legacy-cutover-order", order_id="LEGACY-001", customer_name=customer.name, archive=False)
        order.customers = [customer]
        session.add(order)
        session.add(CargoTable(uid="legacy-cutover-cargo", target_order_uid=order.uid, weight=10, count=1, status=0, archive=False))
        session.add(OrderQuoteVersionTable(order_uid=order.uid, version_no=1, transportation_name="测试渠道", channel_cost=5,
            min_price=5, unit_price=10, surcharge=0, weight_snapshot=10, billing_weight_snapshot=10, receivable_amount=100,
            quoted_price=10, status="adopted", is_final=True, create_date=TODAY + " 08:00:00", effective_date=TODAY + " 08:00:00", archive=False))
        session.commit()
    return {**finance, "order_uid": "legacy-cutover-order"}


def receipt(legacy, amount="30", status="approved", difference="0", **extra):
    with TestSessionFactory() as session:
        row = PaymentReceiptTable(receipt_no=f"OLD-{uuid.uuid4().hex[:8]}", customer_id=legacy["customer"], customer_name="甲客户",
            receipt_date=TODAY, payment_method="bank_transfer", status=status, settlement_status="unsettled", creator_id=701,
            creator_name="财务复核", create_date=TODAY + " 08:00:00", update_date=TODAY + " 08:00:00",
            review_date=TODAY + " 09:00:00" if status == "approved" else None, **extra)
        session.add(row)
        session.flush()
        session.add(PaymentReceiptItemTable(receipt_id=row.id, order_uid=legacy["order_uid"], order_id="LEGACY-001",
            receivable_snapshot=100, received_before=0, amount=Decimal(amount), remaining_after=100-Decimal(amount), settlement_difference=Decimal(difference), archive=False))
        session.commit()
        return row.id


def reviewed_import(legacy, **extra):
    snapshot = service.preview(ACTOR, legacy["order_uid"], TODAY)
    return service.import_balance({"order_uid": legacy["order_uid"], "cutoff_date": TODAY, "source_hash": snapshot["source_hash"],
        "confirmed": True, "reason": "核对客户确认单及银行到账", "account_id": legacy["account"]["id"], **extra}, ACTOR)


def change_quote(price):
    with TestSessionFactory() as session:
        row = session.query(OrderQuoteVersionTable).filter_by(order_uid="legacy-cutover-order", is_final=True).one()
        row.unit_price = Decimal(str(price))
        session.commit()


def current_invoice(legacy, amount, **extra):
    return document(legacy, amount, document_date=TODAY, due_date=TODAY, **extra)


def current_payment(legacy, amount, **extra):
    return payment(legacy, amount, payment_date=TODAY, **extra)


def test_receivable_cutover_imports_net_not_original_income_or_receipts(legacy):
    receipt(legacy, "30", difference="10")
    preview = service.preview(ACTOR, legacy["order_uid"], TODAY)
    assert preview["can_import"] is True
    assert preview["amount"] == "60.00"
    assert preview["source"]["receivable_amount"] == "100.00"
    row = reviewed_import(legacy)
    assert row["status"] == "current"
    assert row["document_id"] is not None
    assert row["payment_id"] is None
    imported = ledger.get_document(row["document_id"], ACTOR)
    assert imported["total_amount"] == "60.00"
    assert imported["is_opening"] is True
    with TestSessionFactory() as session:
        assert session.query(FinancePayment).count() == 0
        assert session.query(FinanceJournalEntry).count() == 1
        assert {line.account_code for line in session.query(FinanceJournalEntry).one().lines} == {"1122", "4104"}
        assert session.query(OrderQuoteVersionTable).one().receivable_amount == 100
        assert session.query(PaymentReceiptTable).one().status == "approved"


def test_overpayment_cutover_creates_only_opening_advance_no_duplicate_bank_cash(legacy):
    receipt(legacy, "130")
    row = reviewed_import(legacy)
    assert row["import_kind"] == "advance"
    assert row["amount"] == "30.00"
    assert row["document_id"] is None
    assert ledger.get_payment(row["payment_id"], ACTOR)["is_opening"] is True
    metrics = ledger.dashboard(ACTOR, TODAY)
    assert metrics["customer_advances"] == "30.00"
    assert metrics["account_balance"] == "0.00"
    assert metrics["posted_receipts"] == "0.00"


def test_settled_order_creates_baseline_without_a_zero_journal(legacy):
    receipt(legacy, "80", difference="20")
    row = reviewed_import(legacy)
    assert row["import_kind"] == "settled"
    assert row["document_id"] is None and row["payment_id"] is None
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0
        assert session.query(FinanceLegacyLink).count() == 1


@pytest.mark.parametrize("unresolved", ["receipt", "quote", "archive", "customer"])
def test_unresolved_old_sources_block_import(legacy, unresolved):
    if unresolved == "receipt":
        receipt(legacy, status="pending")
    else:
        with TestSessionFactory() as session:
            order = session.query(OrderTable).filter_by(uid=legacy["order_uid"]).one()
            quote = session.query(OrderQuoteVersionTable).one()
            if unresolved == "quote":
                quote.status = "pending"
            elif unresolved == "archive":
                order.archive = True
            else:
                order.customers = []
            session.commit()
    preview = service.preview(ACTOR, legacy["order_uid"], TODAY)
    assert preview["can_import"] is False
    assert preview["blockers"]
    with pytest.raises(ledger.FinanceConflictError):
        reviewed_import(legacy)


def test_net_cutover_transfers_legacy_difference_tasks_without_recording_cash(legacy):
    with TestSessionFactory() as session:
        quote = session.query(OrderQuoteVersionTable).one()
        session.add(OrderPriceAdjustmentTable(order_uid=legacy["order_uid"], previous_quote_id=quote.id, new_quote_id=quote.id,
            old_receivable=90, new_receivable=100, delta_amount=10, direction="collect", status="pending",
            creator_name="测试", create_date=TODAY, archive=False))
        session.commit()
    assert service.preview(ACTOR, legacy["order_uid"], TODAY)["can_import"]
    result = reviewed_import(legacy)
    assert result["amount"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(OrderPriceAdjustmentTable).one().status == "resolved"
        assert session.query(FinancePayment).count() == 0
        assert session.query(FinanceDocument).one().total_amount == Decimal("100.00")


def test_historical_date_and_unconfirmed_snapshot_are_rejected(legacy):
    preview = service.preview(ACTOR, legacy["order_uid"], "2026-10-04")
    assert any("历史余额" in value for value in preview["blockers"])
    with pytest.raises(ValueError, match="明确确认"):
        reviewed_import(legacy, confirmed=False)
    preview = service.preview(ACTOR, legacy["order_uid"], TODAY)
    change_quote(11)
    with pytest.raises(ledger.FinanceConflictError, match="已变化"):
        reviewed_import(legacy, source_hash=preview["source_hash"])


def test_import_idempotency_and_unique_order_baseline(legacy):
    preview = service.preview(ACTOR, legacy["order_uid"], TODAY)
    body = {"order_uid": legacy["order_uid"], "cutoff_date": TODAY, "source_hash": preview["source_hash"],
        "confirmed": True, "reason": "已核对", "idempotency_key": "legacy-once"}
    row = service.import_balance(body, ACTOR)
    assert service.import_balance(body, ACTOR) == row
    with pytest.raises(ledger.FinanceConflictError, match="重复"):
        reviewed_import(legacy)
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceLegacyLink).count() == 1


def test_import_audit_failure_rolls_back_baseline_opening_and_journal(legacy, monkeypatch):
    original = ledger.record_audit
    def failure(**kwargs):
        if kwargs["target_type"] == "finance_legacy_link":
            raise RuntimeError("audit insert failed")
        return original(**kwargs)
    monkeypatch.setattr(ledger, "record_audit", failure)
    with pytest.raises(RuntimeError, match="audit insert"):
        reviewed_import(legacy)
    with TestSessionFactory() as session:
        assert session.query(FinanceLegacyLink).count() == 0
        assert session.query(FinanceDocument).count() == 0
        assert session.query(FinanceJournalEntry).count() == 0


def test_source_drift_does_not_silently_change_new_ledger_and_needs_matching_proof(legacy):
    row = reviewed_import(legacy)
    change_quote(12)
    drift = service.get_link(row["id"], ACTOR)
    assert drift["status"] == "reconciliation_required"
    assert drift["delta"]["receivable_amount"] == "20.00"
    assert ledger.get_document(row["document_id"], ACTOR)["total_amount"] == "100.00"
    body = {"version": drift["version"], "source_hash": drift["current_source_hash"], "reason": "复核改价", "related_document_ids": [], "related_payment_ids": []}
    with pytest.raises(ValueError, match="账单净变化应为 20.00"):
        service.acknowledge(row["id"], body, ACTOR)
    adjustment = current_invoice(legacy, "20")
    done = service.acknowledge(row["id"], {**body, "related_document_ids": [adjustment["id"]]}, ACTOR)
    assert done["status"] == "current"
    assert done["version"] == 2
    assert service.history(row["id"], ACTOR)["total"] == 2


def test_reconcile_requires_both_cash_and_document_effect_even_when_net_delta_zero(legacy):
    row = reviewed_import(legacy)
    change_quote(11)
    receipt(legacy, "10")
    drift = service.get_link(row["id"], ACTOR)
    assert drift["delta"]["signed_balance"] == "0.00"
    body = {"version": row["version"], "source_hash": drift["current_source_hash"], "reason": "同步报价与到账"}
    with pytest.raises(ValueError, match="不匹配"):
        service.acknowledge(row["id"], body, ACTOR)
    invoice, received = current_invoice(legacy, "10"), current_payment(legacy, "10")
    done = service.acknowledge(row["id"], {**body, "related_document_ids": [invoice["id"]], "related_payment_ids": [received["id"]]}, ACTOR)
    assert done["status"] == "current"
    with TestSessionFactory() as session:
        assert session.query(FinanceLegacyEvidence).count() == 2


def test_wrong_customer_or_prebaseline_proof_cannot_clear_drift(legacy):
    earlier = current_invoice(legacy, "20")
    row = reviewed_import(legacy)
    change_quote(12)
    drift = service.get_link(row["id"], ACTOR)
    body = {"version": row["version"], "source_hash": drift["current_source_hash"], "reason": "核对", "related_document_ids": [earlier["id"]]}
    with pytest.raises(ValueError, match="上次核对之后"):
        service.acknowledge(row["id"], body, ACTOR)
    wrong = current_invoice(legacy, "20", partner_id=legacy["other_customer"])
    with pytest.raises(ValueError, match="同一客户"):
        service.acknowledge(row["id"], {**body, "related_document_ids": [wrong["id"]]}, ACTOR)


def test_reversed_reconciliation_payment_reopens_review(legacy):
    row = reviewed_import(legacy)
    receipt(legacy, "10")
    drift = service.get_link(row["id"], ACTOR)
    received = current_payment(legacy, "10")
    done = service.acknowledge(row["id"], {"version": row["version"], "source_hash": drift["current_source_hash"], "reason": "到账复核", "related_payment_ids": [received["id"]]}, ACTOR)
    ledger.reverse_payment(received["id"], {"version": received["version"], "reason": "误登记", "payment_date": TODAY}, ACTOR)
    after = service.get_link(row["id"], ACTOR)
    assert after["status"] == "reconciliation_required"
    assert after["required_payment_amount"] == "10.00"
    assert after["current_preview"]["blockers"]
    with pytest.raises(ValueError, match="收款净变化应为 10.00"):
        service.acknowledge(row["id"], {"version": done["version"], "source_hash": done["source_hash"], "reason": "不能略过"}, ACTOR)
    replacement = current_payment(legacy, "10")
    repaired = service.acknowledge(row["id"], {"version": done["version"], "source_hash": done["source_hash"], "reason": "以正确资金凭证补记", "related_payment_ids": [replacement["id"]]}, ACTOR)
    assert repaired["status"] == "current"


def test_reversed_document_proof_requires_credit_and_matching_effect(legacy):
    row = reviewed_import(legacy)
    change_quote(12)
    current = service.get_link(row["id"], ACTOR)
    extra = current_invoice(legacy, "20")
    acknowledged = service.acknowledge(row["id"], {"version": row["version"], "source_hash": current["current_source_hash"], "reason": "补记运费", "related_document_ids": [extra["id"]]}, ACTOR)
    reversal = ledger.reverse_document(extra["id"], {"version": extra["version"], "reason": "错误补价退回", "document_date": TODAY}, ACTOR)
    assert service.get_link(row["id"], ACTOR)["status"] == "reconciliation_required"
    change_quote(10)
    current = service.get_link(row["id"], ACTOR)
    fixed = service.acknowledge(row["id"], {"version": acknowledged["version"], "source_hash": current["current_source_hash"], "reason": "同步旧订单恢复原价", "related_document_ids": [reversal["credit"]["id"]]}, ACTOR)
    assert fixed["status"] == "current"
    with TestSessionFactory() as session:
        assert service.reconciliation_count(session, TODAY) == 0


def test_order_archive_after_cutover_never_removes_financial_balance(legacy):
    row = reviewed_import(legacy)
    with TestSessionFactory() as session:
        session.query(OrderTable).filter_by(uid=legacy["order_uid"]).one().archive = True
        session.commit()
    assert service.get_link(row["id"], ACTOR)["status"] == "source_unavailable"
    assert ledger.get_document(row["document_id"], ACTOR)["residual_amount"] == "100.00"


def test_opening_targets_are_monitored_without_inventing_current_cash(legacy):
    receipt(legacy, "130")
    row = reviewed_import(legacy)
    advance = ledger.get_payment(row["payment_id"], ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="撤销接入"):
        ledger.reverse_payment(advance["id"], {"version": advance["version"], "reason": "期初核准错误", "payment_date": TODAY}, ACTOR)
    # Simulate a previously damaged/imported database, bypassing the guarded API.
    with TestSessionFactory() as session:
        target = session.get(FinancePayment, advance["id"])
        target.status, target.reversal_date = "reversed", TODAY
        session.commit()
    broken = service.get_link(row["id"], ACTOR)
    assert broken["status"] == "source_unavailable"
    with TestSessionFactory() as session:
        assert service.reconciliation_count(session, TODAY) == 1
    with pytest.raises(ledger.FinanceConflictError, match="不能用本期普通收款"):
        service.acknowledge(row["id"], {"version": row["version"], "source_hash": broken["current_source_hash"], "reason": "不能略过"}, ACTOR)


def test_credit_against_initial_opening_bill_must_be_explicitly_reconciled(legacy):
    row = reviewed_import(legacy)
    credit = current_invoice(legacy, "20", kind="customer_credit", original_document_id=row["document_id"])
    before = service.get_link(row["id"], ACTOR)
    assert before["status"] == "reconciliation_required"
    assert before["required_documents"][0]["number"] == credit["number"]
    change_quote(8)
    drift = service.get_link(row["id"], ACTOR)
    cleared = service.acknowledge(row["id"], {"version": row["version"], "source_hash": drift["current_source_hash"],
        "reason": "核对原收费更正", "related_document_ids": [credit["id"]]}, ACTOR)
    assert cleared["status"] == "current"


def test_legacy_http_permissions_history_and_filters(legacy, client):
    headers = {"x-token": create_jwt(ACTOR)}
    assert client.get("/api/finance/v2/legacy/orders", headers={"x-token": create_jwt(SALES)}).status_code == 403
    found = client.get("/api/finance/v2/legacy/orders?q=LEGACY", headers=headers)
    assert found.get_json()["data"]["total"] == 1
    row = reviewed_import(legacy)
    assert client.get(f"/api/finance/v2/legacy/links/{row['id']}/history", headers=headers).get_json()["data"]["history_complete"] is True
    change_quote(12)
    assert service.list_links(ACTOR, status="drift")["total"] == 1
    assert service.list_links(ACTOR, status="current")["total"] == 0


@pytest.mark.parametrize("paid,kind", [("0", "receivable"), ("130", "advance"), ("100", "settled")])
def test_reviewed_revoke_and_reimport_preserve_facts_without_duplicate_balance(legacy, paid, kind):
    if paid != "0":
        receipt(legacy, paid)
    first = reviewed_import(legacy)
    assert first["can_revoke"] is True
    if first["document_id"]:
        target = ledger.get_document(first["document_id"], ACTOR)
        with pytest.raises(ledger.FinanceConflictError, match="撤销接入"):
            ledger.reverse_document(target["id"], {"version": target["version"], "document_date": TODAY, "reason": "应从接入撤销"}, ACTOR)
    revoked = service.revoke(first["id"], {"version": first["version"], "reason": "重新核准来源", "idempotency_key": "revoke-once"}, ACTOR)
    assert revoked["link_status"] == "revoked"
    assert revoked["status"] == "revoked"
    with TestSessionFactory() as session:
        assert service.reconciliation_count(session, TODAY) == 0
    assert service.preview(ACTOR, legacy["order_uid"], TODAY)["can_import"] is True
    second = reviewed_import(legacy)
    assert second["id"] == first["id"]
    assert second["version"] == 3
    assert second["status"] == "current"
    assert service.history(second["id"], ACTOR)["total"] == 3
    metrics = ledger.dashboard(ACTOR, TODAY)
    assert metrics["account_balance"] == "0.00"
    assert metrics["receivable"] == ("100.00" if kind == "receivable" else "0.00")
    assert metrics["customer_advances"] == ("30.00" if kind == "advance" else "0.00")


def test_revoke_respects_allocations_and_confirmed_opening(legacy):
    row = reviewed_import(legacy)
    received = current_payment(legacy, "10")
    ledger.create_allocations({"payment_id": received["id"], "version": received["version"], "allocation_date": TODAY,
        "allocations": [{"document_id": row["document_id"], "amount": "10"}]}, ACTOR)
    assert service.get_link(row["id"], ACTOR)["can_revoke"] is False
    with pytest.raises(ledger.FinanceConflictError, match="核销"):
        service.revoke(row["id"], {"version": row["version"], "reason": "误导入"}, ACTOR)
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_confirmed = True
        session.commit()
    assert any("期初已确认" in value for value in service.get_link(row["id"], ACTOR)["revoke_blockers"])


def test_revoke_fails_atomically_when_audit_fails(legacy, monkeypatch):
    row = reviewed_import(legacy)
    original = ledger.record_audit
    def failure(**kwargs):
        if kwargs["action"] == "legacy_revoke":
            raise RuntimeError("audit unavailable")
        return original(**kwargs)
    monkeypatch.setattr(ledger, "record_audit", failure)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.revoke(row["id"], {"version": row["version"], "reason": "重建"}, ACTOR)
    assert service.get_link(row["id"], ACTOR)["status"] == "current"
    assert ledger.get_document(row["document_id"], ACTOR)["reversed_by_id"] is None
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceJournalEntry).count() == 1


def test_dashboard_surfaces_old_source_drift_without_changing_financial_totals(legacy):
    row = reviewed_import(legacy)
    initial = ledger.dashboard(ACTOR, TODAY)
    assert initial["legacy_reconciliation_required"] == 0
    change_quote(12)
    drift = ledger.dashboard(ACTOR, TODAY)
    assert drift["legacy_reconciliation_required"] == 1
    assert drift["receivable"] == initial["receivable"] == "100.00"
    assert drift["account_balance"] == initial["account_balance"] == "0.00"
    service.revoke(row["id"], {"version": row["version"], "reason": "重新核准切换金额"}, ACTOR)
    assert ledger.dashboard(ACTOR, TODAY)["legacy_reconciliation_required"] == 0


def test_legacy_migration_upgrade_and_downgrade():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_138e9f0a1b2c_finance_legacy_links.py"
    spec = importlib.util.spec_from_file_location("legacy_finance_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert set(inspect(connection).get_table_names()) == {"finance_legacy_links", "finance_legacy_evidence"}
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
