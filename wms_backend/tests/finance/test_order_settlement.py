"""Actual order/quote mutations never rewrite confirmed cash movements."""
from decimal import Decimal
import pytest
from Auth import create_jwt
from data.DB import OrderTable, CargoTable, OrderQuoteVersionTable
from data.customer.Customer import CustomerTable
from data.finance.ledger import FinanceDocument, FinancePayment, FinanceAllocation
from data.finance.accounting import FinancePeriod, FinanceSettings
from data.finance.order_settlement import FinanceOrderSettlement
from services import finance_order_service as orders
from services import finance_ledger_service as ledger
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import finance, ACTOR, SALES, payment

TODAY = "2026-10-05"


@pytest.fixture
def order_finance(finance, monkeypatch):
    monkeypatch.setattr(ledger, "_today", lambda: TODAY)
    with TestSessionFactory() as session:
        customer = session.get(CustomerTable, finance["customer"])
        for suffix in ("one", "two", "empty"):
            row = OrderTable(uid=f"order-{suffix}", order_id=f"ORDER-{suffix}", customer_name=customer.name, archive=False)
            row.customers = [customer]
            session.add(row)
            if suffix != "empty":
                session.add(CargoTable(uid=f"cargo-{suffix}", target_order_uid=row.uid, weight=10, count=1, status=0, archive=False))
                session.add(OrderQuoteVersionTable(order_uid=row.uid, version_no=1, transportation_name="测试渠道", channel_cost=5,
                    min_price=5, unit_price=10, surcharge=0, weight_snapshot=10, billing_weight_snapshot=10, receivable_amount=100,
                    quoted_price=10, status="adopted", is_final=True, archive=False,
                    create_date=TODAY + " 08:00:00", effective_date=TODAY + " 08:00:00"))
        session.commit()
    return finance


def preview(uid="order-one"):
    return next(row for row in orders.list_orders(ACTOR)["items"] if row["order_uid"] == uid)


def sync(uid="order-one", **extra):
    return orders.sync_order(uid, {"source_hash": preview(uid)["source_hash"], "document_date": TODAY,
        "reason": "核对订单当前报价", **extra}, ACTOR)


def allocate(pay, amount, uid="order-one", **extra):
    current = ledger.get_payment(pay["id"], ACTOR)
    return orders.allocate_orders({"payment_id": pay["id"], "version": current["version"], "allocation_date": TODAY,
        "allocations": [{"order_uid": uid, "amount": amount, "source_hash": preview(uid)["source_hash"]}], **extra}, ACTOR)


def price(value):
    with TestSessionFactory() as session:
        quote = session.query(OrderQuoteVersionTable).filter_by(order_uid="order-one").one()
        quote.unit_price = value
        session.commit()


def test_prepaid_money_is_independent_and_order_reads_do_not_post(order_finance):
    cash = payment(order_finance, "180", payment_date=TODAY)
    row = preview()
    assert row["receivable_balance"] == "100.00"
    assert row["allocated_amount"] == "0.00"
    assert row["sync_delta"] == "100.00"
    assert not preview("order-empty")["can_allocate"]
    assert ledger.get_payment(cash["id"], ACTOR)["unallocated_amount"] == "180.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0
        assert session.query(FinanceOrderSettlement).count() == 0


def test_partial_order_allocation_and_reversal_leave_cash_unchanged(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    result = allocate(cash, "40")
    allocation = result["items"][0]
    assert allocation["order_uid"] == "order-one"
    assert preview()["receivable_balance"] == "60.00"
    assert result["source"]["amount"] == "100.00"
    assert result["source"]["unallocated_amount"] == "60.00"
    ledger.reverse_allocation(allocation["id"], {"version": allocation["version"], "reversal_date": TODAY, "reason": "选错订单"}, ACTOR)
    assert preview()["receivable_balance"] == "100.00"
    assert ledger.get_payment(cash["id"], ACTOR)["unallocated_amount"] == "100.00"
    assert ledger.get_payment(cash["id"], ACTOR)["status"] == "posted"


def test_price_increase_and_decrease_create_adjustments_and_refund_without_editing_cash(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    allocate(cash, "100")
    price(15)
    assert preview()["receivable_balance"] == "50.00"
    sync()
    price(8)
    assert preview()["refundable_amount"] == "20.00"
    after = sync()
    assert after["sync_delta"] == "0.00"
    assert len(after["documents"]) == 4
    assert ledger.get_payment(cash["id"], ACTOR)["amount"] == "100.00"
    refund = payment(order_finance, "20", direction="outgoing", payment_date=TODAY)
    allocate(refund, "20")
    assert preview()["refundable_amount"] == "0.00"
    assert preview()["allocated_amount"] == "80.00"
    assert ledger.get_payment(cash["id"], ACTOR)["amount"] == "100.00"


def test_weight_change_updates_receivable_preview_only(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    allocate(cash, "60")
    with TestSessionFactory() as session:
        session.get(CargoTable, "cargo-one").weight = 20
        session.commit()
    row = preview()
    assert row["receivable_amount"] == "200.00"
    assert row["receivable_balance"] == "140.00"
    assert row["sync_delta"] == "100.00"
    assert ledger.get_payment(cash["id"], ACTOR)["amount"] == "100.00"


def test_multi_order_allocation_is_atomic_and_rejects_stale_quote(order_finance):
    cash = payment(order_finance, "200", payment_date=TODAY)
    one, two = preview(), preview("order-two")
    body = {"payment_id": cash["id"], "version": cash["version"], "allocation_date": TODAY,
        "allocations": [{"order_uid": "order-one", "amount": "60", "source_hash": one["source_hash"]},
                        {"order_uid": "order-two", "amount": "40", "source_hash": "stale"}]}
    with pytest.raises(ledger.FinanceConflictError, match="已变化"):
        orders.allocate_orders(body, ACTOR)
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0
        assert session.query(FinanceAllocation).count() == 0
    body["allocations"][1]["source_hash"] = two["source_hash"]
    result = orders.allocate_orders(body, ACTOR)
    assert len(result["items"]) == 2
    assert result["source"]["unallocated_amount"] == "100.00"


def test_empty_order_and_cross_customer_are_not_financial_allocation_targets(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    with pytest.raises(ValueError, match="余额"):
        allocate(cash, "1", uid="order-empty")
    with TestSessionFactory() as session:
        session.get(OrderTable, "order-one").customers = [session.get(CustomerTable, order_finance["other_customer"])]
        session.commit()
    with pytest.raises(ValueError, match="同一客户"):
        allocate(cash, "10")


def test_closed_period_and_audit_failure_roll_back_new_receivables(order_finance, monkeypatch):
    with TestSessionFactory() as session:
        session.query(FinancePeriod).one().status = "closed"
        session.commit()
    with pytest.raises(ValueError, match="关账"):
        sync()
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0
        session.query(FinancePeriod).one().status = "open"
        session.commit()
    original = ledger._audit
    def fail(*args, **kwargs):
        if args[2] == "finance_order_settlement":
            raise RuntimeError("audit unavailable")
        return original(*args, **kwargs)
    monkeypatch.setattr(ledger, "_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        sync()
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 0
        assert session.query(FinanceOrderSettlement).count() == 0


def test_sales_cannot_allocate_and_old_http_creation_is_retired(order_finance, client):
    with pytest.raises(PermissionError):
        orders.list_orders(SALES)
    headers = {"x-token": create_jwt(SALES)}
    assert client.post('/api/receipts', headers=headers, json={}).status_code == 410
    assert client.get('/api/finance/v2/order-settlements', headers=headers).status_code == 403


def test_managed_order_documents_cannot_be_manually_credited_or_reversed(order_finance):
    row = sync()["documents"][0]
    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        ledger.reverse_document(row["id"], {"version": row["version"], "reason": "重复冲销"}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError, match="订单应收"):
        ledger.create_document({"document_type": "customer_credit", "partner_id": order_finance["customer"],
            "original_document_id": row["id"], "document_date": TODAY,
            "lines": [{"description": "重复贷项", "unit_price": 10}]}, ACTOR)


def test_order_sync_replay_does_not_create_duplicate_documents(order_finance):
    body = {"source_hash": preview()["source_hash"], "document_date": TODAY, "reason": "确认应收", "idempotency_key": "sync-once"}
    one = orders.sync_order("order-one", body, ACTOR)
    assert orders.sync_order("order-one", body, ACTOR) == one
    with TestSessionFactory() as session:
        assert session.query(FinanceDocument).count() == 1


def test_legacy_net_balance_enters_order_flow_without_duplicating_historical_cash(order_finance, monkeypatch):
    from services import finance_legacy_service as legacy
    from tests.finance.test_legacy import receipt
    monkeypatch.setattr(legacy, "SessionFactory", TestSessionFactory)
    receipt({**order_finance, "order_uid": "order-one"}, amount="30")
    assert not preview()["can_allocate"]
    assert preview()["receivable_balance"] == "70.00"
    with TestSessionFactory() as session:
        session.get(FinanceSettings, 1).opening_date = TODAY
        session.commit()
    initial = legacy.preview(ACTOR, "order-one", TODAY)
    link = legacy.import_balance({"order_uid": "order-one", "cutoff_date": TODAY,
        "source_hash": initial["source_hash"], "confirmed": True, "reason": "已核对历史实际收款"}, ACTOR)
    assert sync()["receivable_balance"] == "70.00"
    price(12)
    after = sync()
    assert after["receivable_balance"] == "90.00"
    assert after["legacy_settled_amount"] == "30.00"
    assert legacy.get_link(link["id"], ACTOR)["status"] == "current"
    with TestSessionFactory() as session:
        assert session.query(FinancePayment).count() == 0
        assert sum(row.total_amount for row in session.query(FinanceDocument)) == Decimal("90.00")


def test_managed_invoice_cannot_bypass_live_order_validation(order_finance):
    cash = payment(order_finance, "100", payment_date=TODAY)
    document = sync()["documents"][0]
    with pytest.raises(ledger.FinanceConflictError, match="核销订单"):
        ledger.create_allocations({"payment_id": cash["id"], "version": cash["version"], "allocation_date": TODAY,
            "allocations": [{"document_id": document["id"], "amount": "10"}]}, ACTOR)


def test_unconfirmed_quote_change_is_visible_in_month_close_checks(order_finance):
    from services import finance_accounting_service as accounting
    sync()
    with TestSessionFactory() as session:
        period_id = session.query(FinancePeriod).one().id
    price(12)
    checks = accounting.closing_checks(period_id, ACTOR)["checks"]
    assert next(row for row in checks if row["key"] == "orders")["count"] == 1
    sync()
    checks = accounting.closing_checks(period_id, ACTOR)["checks"]
    assert next(row for row in checks if row["key"] == "orders")["passed"]
