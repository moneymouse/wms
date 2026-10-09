"""Supplier payables coexist with managed receivables without weakening safeguards."""

import pytest

from data.finance.accounting import FinanceJournalEntry
from data.finance.ledger import FinanceDocument
from services import finance_ledger_service as ledger
from services import supplier_reconciliation_service as reconciliation
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import document
from tests.finance.test_order_settlement import (
    ACTOR, TODAY, finance, order_finance, preview, price, sync,
)
from tests.finance.test_supplier_reconciliation import CLERK, workbook


def linked_document(order_finance, amount, *, kind="vendor_bill", post=True, **extra):
    return document(
        order_finance, amount, kind=kind, post=post,
        document_date=TODAY, due_date=TODAY,
        lines=[{
            "description": "订单运输费用", "quantity": "1", "unit_price": amount,
            "order_uid": "order-one",
        }],
        **extra,
    )


def test_vendor_bill_can_post_after_order_receivable_is_managed(order_finance):
    managed = sync()
    bill = linked_document(order_finance, "80", post=False)
    posted = ledger.post_document(bill["id"], {"version": bill["version"]}, ACTOR)

    assert posted["status"] == "posted"
    assert posted["lines"][0]["order_uid"] == "order-one"
    assert preview()["can_allocate"] is True
    assert preview()["receivable_amount"] == managed["receivable_amount"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(
            source_type="finance_document", source_id=str(bill["id"]),
        ).count() == 1

    price(12)
    adjusted = sync()
    assert adjusted["receivable_amount"] == "120.00"
    assert adjusted["sync_delta"] == "0.00"
    assert ledger.get_document(bill["id"], ACTOR)["total_amount"] == "80.00"


def test_vendor_credit_can_post_without_blocking_next_receivable_sync(order_finance):
    sync()
    bill = linked_document(order_finance, "80")
    credit = linked_document(
        order_finance, "20", kind="vendor_credit", post=False,
        original_document_id=bill["id"],
    )
    posted = ledger.post_document(credit["id"], {"version": credit["version"]}, ACTOR)

    assert posted["status"] == "posted"
    assert posted["original_document_id"] == bill["id"]
    assert posted["lines"][0]["order_uid"] == "order-one"
    assert preview()["can_allocate"] is True

    price(8)
    adjusted = sync()
    assert adjusted["receivable_amount"] == "80.00"
    assert adjusted["sync_delta"] == "0.00"
    assert all(row["document_type"].startswith("customer") for row in adjusted["documents"])
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(
            source_type="finance_document", source_id=str(credit["id"]),
        ).count() == 1
        assert session.get(FinanceDocument, bill["id"]).status == "posted"


def test_existing_supplier_bill_does_not_block_first_receivable_sync(order_finance):
    bill = linked_document(order_finance, "80")

    assert preview()["can_allocate"] is True
    managed = sync()
    assert managed["receivable_amount"] == "100.00"
    assert managed["sync_delta"] == "0.00"
    assert len(managed["documents"]) == 1
    assert managed["documents"][0]["document_type"] == "customer_invoice"
    assert ledger.get_document(bill["id"], ACTOR)["status"] == "posted"


def test_extra_customer_invoice_cannot_post_for_managed_order(order_finance):
    sync()
    draft = linked_document(order_finance, "20", kind="customer_invoice", post=False)

    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        ledger.post_document(draft["id"], {"version": draft["version"]}, ACTOR)

    assert ledger.get_document(draft["id"], ACTOR)["status"] == "draft"
    assert preview()["receivable_amount"] == "100.00"
    assert preview()["can_allocate"] is True
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(
            source_type="finance_document", source_id=str(draft["id"]),
        ).count() == 0


def test_existing_independent_customer_invoice_still_blocks_first_sync(order_finance):
    invoice = linked_document(order_finance, "100", kind="customer_invoice")
    current = preview()

    assert current["can_allocate"] is False
    assert any("其他已入账账单" in blocker for blocker in current["blockers"])
    with pytest.raises(ledger.FinanceConflictError, match="其他已入账账单"):
        sync()

    assert ledger.get_document(invoice["id"], ACTOR)["status"] == "posted"
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceJournalEntry).count() == 1


def controlled_import_bill(order_finance, monkeypatch):
    bill = document(
        order_finance, "150", kind="vendor_bill", document_date=TODAY, due_date=TODAY,
        lines=[
            {"description": "第一单运费", "unit_price": "50", "order_uid": "order-one"},
            {"description": "第二单运费", "unit_price": "100", "order_uid": "order-two"},
        ],
    )
    monkeypatch.setattr(reconciliation, "is_import_document", lambda session, document_id: document_id == bill["id"])
    return bill


@pytest.mark.parametrize("order_uid, amount, error", [
    (None, "20", "订单归属"),
    ("order-empty", "20", "订单归属"),
    ("order-one", "60", "订单费用"),
])
def test_imported_bill_credit_preserves_order_attribution_and_limit(order_finance, monkeypatch, order_uid, amount, error):
    bill = controlled_import_bill(order_finance, monkeypatch)
    credit = document(
        order_finance, amount, kind="vendor_credit", post=False,
        original_document_id=bill["id"], document_date=TODAY, due_date=TODAY,
        lines=[{"description": "运费调减", "unit_price": amount, "order_uid": order_uid}],
    )

    with pytest.raises(ledger.FinanceConflictError, match=error):
        ledger.post_document(credit["id"], {"version": credit["version"]}, ACTOR)

    assert ledger.get_document(credit["id"], ACTOR)["status"] == "draft"
    assert ledger.get_document(bill["id"], ACTOR)["total_amount"] == "150.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 1


def test_imported_bill_credit_limit_includes_prior_posted_credits(order_finance, monkeypatch):
    bill = controlled_import_bill(order_finance, monkeypatch)
    first = linked_document(
        order_finance, "40", kind="vendor_credit", original_document_id=bill["id"],
    )
    second = linked_document(
        order_finance, "15", kind="vendor_credit", post=False,
        original_document_id=bill["id"],
    )

    assert first["status"] == "posted"
    with pytest.raises(ledger.FinanceConflictError, match="累计供应商贷项"):
        ledger.post_document(second["id"], {"version": second["version"]}, ACTOR)

    assert ledger.get_document(second["id"], ACTOR)["status"] == "draft"
    assert ledger.get_document(first["id"], ACTOR)["total_amount"] == "40.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).filter_by(document_type="vendor_credit", status="posted").count() == 1
        assert session.query(FinanceJournalEntry).count() == 2


def test_imported_bill_full_reversal_keeps_each_original_order_amount(order_finance, monkeypatch):
    bill = controlled_import_bill(order_finance, monkeypatch)
    sync()
    sync("order-two")

    reversed_bill = ledger.reverse_document(
        bill["id"], {"version": bill["version"], "document_date": TODAY, "reason": "供应商账单撤回"}, ACTOR,
    )

    credit = reversed_bill["credit"]
    assert credit["status"] == "posted"
    assert credit["document_type"] == "vendor_credit"
    assert credit["original_document_id"] == bill["id"]
    assert {line["order_uid"]: line["total_amount"] for line in credit["lines"]} == {
        "order-one": "50.00", "order-two": "100.00",
    }
    assert reversed_bill["document"]["reversed_by_id"] == credit["id"]
    assert preview()["can_allocate"] is True
    assert preview("order-two")["can_allocate"] is True
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(
            source_type="finance_document", source_id=str(credit["id"]),
        ).count() == 1


def test_real_order_level_import_posts_and_reverses_with_managed_receivable(order_finance):
    managed = sync()
    imported = reconciliation.upload_batch(workbook([["ORDER-one", None, "9", "80", "整单费用"]]),
        "整单.xlsx", order_finance["vendor"]["id"], "2026-10", CLERK)
    source = imported["rows"]["items"][0]
    assert source["match_type"] == "order" and source["cargo_uid"] is None
    bill = imported["batch"]["documents"][0]
    posted = ledger.post_document(bill["id"], {"version": bill["version"]}, ACTOR)
    assert reconciliation.order_costs("order-one", CLERK)["confirmed_amount"] == "80.00"
    assert preview()["receivable_amount"] == managed["receivable_amount"] == "100.00"
    assert preview()["can_allocate"] is True
    reversed_bill = ledger.reverse_document(bill["id"], {"version": posted["version"],
        "document_date": TODAY, "reason": "整单对账撤回"}, ACTOR)
    assert reversed_bill["credit"]["lines"][0]["order_uid"] == "order-one"
    assert reconciliation.order_costs("order-one", CLERK)["confirmed_amount"] == "0.00"
    price(12)
    assert sync()["receivable_amount"] == "120.00"
