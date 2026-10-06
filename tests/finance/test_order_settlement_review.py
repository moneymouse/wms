"""Regression coverage for migration/managed-order boundaries found in review."""
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from data.finance.accounting import FinanceJournalEntry, FinanceSettings
from data.finance.ledger import FinanceAllocation, FinanceDocument
from data.finance.legacy import FinanceLegacyLink
from data.finance.order_settlement import FinanceOrderDocument, FinanceOrderSettlement
from services import finance_ledger_service as ledger
from services import finance_legacy_service as legacy
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import document
from tests.finance.test_order_settlement import (
    ACTOR, TODAY, finance, order_finance, payment, preview, sync, allocate, price,
)


def import_opening(order_finance, monkeypatch):
    monkeypatch.setattr(legacy, "SessionFactory", TestSessionFactory)
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_date = TODAY
        session.commit()
    snapshot = legacy.preview(ACTOR, "order-one", TODAY)
    assert snapshot["can_import"] is True
    return legacy.import_balance({"order_uid": "order-one", "cutoff_date": TODAY,
        "source_hash": snapshot["source_hash"], "confirmed": True,
        "reason": "核准切换日净余额"}, ACTOR)


def external_credit(order_finance, opening, *, post=False):
    return document(order_finance, "20", kind="customer_credit", original_document_id=opening["document_id"],
        document_date=TODAY, due_date=TODAY, post=post)


def test_synced_order_cannot_be_imported_again_as_opening_balance(order_finance, monkeypatch):
    monkeypatch.setattr(legacy, "SessionFactory", TestSessionFactory)
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_date = TODAY
        session.commit()
    managed = sync()
    snapshot = legacy.preview(ACTOR, "order-one", TODAY)
    assert snapshot["can_import"] is False
    assert any("统一订单应收" in value for value in snapshot["blockers"])
    with pytest.raises(ledger.FinanceConflictError, match="统一订单应收"):
        legacy.import_balance({"order_uid": "order-one", "cutoff_date": TODAY, "source_hash": snapshot["source_hash"],
            "confirmed": True, "reason": "不能重复创建期初"}, ACTOR)
    with TestSessionFactory() as session:
        assert session.query(FinanceLegacyLink).count() == 0
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceJournalEntry).count() == 1
    assert preview()["receivable_balance"] == managed["receivable_balance"] == "100.00"


def test_old_draft_credit_cannot_post_after_opening_invoice_becomes_managed(order_finance, monkeypatch):
    opening = import_opening(order_finance, monkeypatch)
    draft = external_credit(order_finance, opening)
    synced = sync()
    assert synced["receivable_balance"] == "100.00"
    with TestSessionFactory() as session:
        assert session.get(FinanceOrderDocument, opening["document_id"]) is not None
    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        ledger.post_document(draft["id"], {"version": draft["version"]}, ACTOR)
    assert ledger.get_document(draft["id"], ACTOR)["status"] == "draft"
    assert preview()["receivable_balance"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 1


def test_existing_posted_external_credit_blocks_first_order_sync(order_finance, monkeypatch):
    opening = import_opening(order_finance, monkeypatch)
    credit = external_credit(order_finance, opening, post=True)
    current = preview()
    assert current["can_allocate"] is False
    assert any("其他已入账账单" in value for value in current["blockers"])
    with pytest.raises(ledger.FinanceConflictError, match="其他已入账账单"):
        sync()
    with TestSessionFactory() as session:
        assert session.query(FinanceOrderSettlement).count() == 0
        assert session.query(FinanceOrderDocument).count() == 0
        assert session.query(FinanceDocument).count() == 2
        assert session.query(FinanceJournalEntry).count() == 2
    assert ledger.get_document(credit["id"], ACTOR)["status"] == "posted"


def test_managed_credit_cannot_be_spent_on_unrelated_invoice_via_generic_allocation(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    allocate(cash, "100")
    price(8)
    synchronized = sync()
    credit = next(row for row in synchronized["documents"] if row["document_type"] == "customer_credit")
    assert credit["residual_amount"] == "20.00"
    unrelated = document(order_finance, "30", document_date=TODAY, due_date=TODAY)
    with pytest.raises(ledger.FinanceConflictError, match="订单调减贷项"):
        ledger.create_allocations({"credit_document_id": credit["id"], "version": credit["version"],
            "allocation_date": TODAY, "allocations": [{"document_id": unrelated["id"], "amount": "20"}]}, ACTOR)
    assert ledger.get_document(unrelated["id"], ACTOR)["residual_amount"] == "30.00"
    assert preview()["refundable_amount"] == "20.00"
    assert ledger.get_payment(cash["id"], ACTOR)["amount"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).count() == 1


def test_no_legacy_cash_does_not_allow_reposting_manually_reconciled_invoice(order_finance, monkeypatch):
    opening = import_opening(order_finance, monkeypatch)
    assert opening["baseline"]["received_amount"] == "0.00"
    price(12)
    manual_invoice = document(order_finance, "20", document_date=TODAY, due_date=TODAY)
    drift = legacy.get_link(opening["id"], ACTOR)
    reconciled = legacy.acknowledge(opening["id"], {"version": drift["version"], "source_hash": drift["current_source_hash"],
        "reason": "报价差异已经独立入账", "related_document_ids": [manual_invoice["id"]]}, ACTOR)
    assert reconciled["status"] == "current"
    assert preview()["can_allocate"] is False
    assert any("人工对账" in value for value in preview()["blockers"])
    with pytest.raises(ledger.FinanceConflictError, match="人工对账"):
        sync()
    with TestSessionFactory() as session:
        assert session.query(FinanceOrderSettlement).count() == 0
        assert session.query(FinanceDocument).count() == 2
        assert sum(row.total_amount for row in session.query(FinanceDocument)) == Decimal("120.00")


def test_legacy_ack_and_revoke_cannot_bypass_managed_order_flow(order_finance, monkeypatch):
    opening = import_opening(order_finance, monkeypatch)
    sync()
    current = legacy.get_link(opening["id"], ACTOR)
    assert current["can_revoke"] is False
    assert any("订单应收" in value for value in current["revoke_blockers"])
    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        legacy.acknowledge(opening["id"], {"version": current["version"], "source_hash": current["current_source_hash"],
            "reason": "不可旁路"}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        legacy.revoke(opening["id"], {"version": current["version"], "reason": "不可旁路撤销"}, ACTOR)
    assert ledger.get_document(opening["document_id"], ACTOR)["reversed_by_id"] is None
    assert preview()["receivable_balance"] == "100.00"


def test_order_settlement_migration_keeps_payment_data_on_upgrade_and_downgrade():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_35a0b1c2d3e4_order_settlements.py"
    spec = importlib.util.spec_from_file_location("order_settlement_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE finance_legacy_links (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE finance_documents (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE finance_payments (id INTEGER PRIMARY KEY, number TEXT, amount NUMERIC(18,2), status TEXT, reference_orders_json TEXT)"))
        connection.execute(text("INSERT INTO finance_payments VALUES (1, 'PAY-EXISTING', 125.50, 'posted', '[]')"))
        connection.execute(text("INSERT INTO finance_payments VALUES (2, 'PAY-PENDING', 20, 'pending', '[\"order-one\"]')"))
        connection.execute(text("INSERT INTO finance_legacy_links VALUES (9)"))
        connection.execute(text("INSERT INTO finance_documents VALUES (7)"))
        before = connection.execute(text("SELECT * FROM finance_payments ORDER BY id")).all()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text("SELECT * FROM finance_payments ORDER BY id")).all() == before
        assert {"finance_order_settlements", "finance_order_documents"}.issubset(inspect(connection).get_table_names())
        connection.execute(text("INSERT INTO finance_order_settlements VALUES ('order-one','ORDER-ONE',1,9,30,'source',1,'2026-10-05','2026-10-05')"))
        connection.execute(text("INSERT INTO finance_order_documents VALUES (7,'order-one','source','{}')"))
        migration.downgrade()
        assert connection.execute(text("SELECT * FROM finance_payments ORDER BY id")).all() == before
        assert "finance_order_settlements" not in inspect(connection).get_table_names()
        assert "finance_order_documents" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT id FROM finance_documents")).scalar() == 7
