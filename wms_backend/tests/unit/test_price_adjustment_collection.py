"""Re-quote supplemental collection, reservations, review and migration."""

from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from data.DB import OrderPriceAdjustmentTable, OrderQuoteVersionTable, PaymentReceiptItemTable, PaymentReceiptTable
from services import receivable_service as service
from tests.unit.test_order_business_lock_and_adjustments import _settle_original_quote
from tests.unit.test_order_receipt_revision import _seed_world
from tests.unit.test_receipt_settlement import SALES, FINANCE, _body, _review


def _seed_adjustment(session, unit_price=13):
    customer, orders, _ = _seed_world(session)
    _settle_original_quote(session, customer, orders[0])
    service.create_order_quote(orders[0].uid, {"unit_price": unit_price, "surcharge": 0}, SALES)
    adjustment = session.query(OrderPriceAdjustmentTable).one()
    return customer, orders, adjustment


def _collection_body(customer, orders, adjustment, amount, **extra):
    body = _body(customer, orders, [amount], **extra)
    body["items"][0]["adjustment_id"] = adjustment.id
    return body


def _detail(adjustment):
    return service.get_price_adjustment_detail(adjustment.id, SALES)


def test_full_supplemental_collection_closes_task_only_after_approval(
    client, setup_test_database, salesperson_token, admin_token,
):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    initial = service.list_price_adjustments(SALES)["items"][0]
    assert initial["customer_id"] == customer.id
    assert (initial["approved_received"], initial["pending_amount"], initial["available_amount"]) == (0, 0, 11)
    response = client.post(
        "/api/receipts", headers={"x-token": salesperson_token},
        json=_collection_body(customer, orders, adjustment, 11),
    )
    assert response.status_code == 200
    receipt = response.get_json()["data"]
    assert receipt["settlement_status"] == "unsettled"
    assert receipt["items"][0]["adjustment_id"] == adjustment.id
    detail_response = client.get(
        f"/api/receivable-adjustments/{adjustment.id}", headers={"x-token": salesperson_token},
    )
    assert detail_response.status_code == 200
    pending = detail_response.get_json()["data"]
    assert (pending["status"], pending["pending_amount"], pending["available_amount"]) == ("pending", 11, 0)
    assert "待审核" in pending["collection_blocked_reason"]
    reviewed = client.put(
        f"/api/finance/receipts/{receipt['id']}/review", headers={"x-token": admin_token},
        json={"action": "approve", "review_remark": "补收确认"},
    )
    assert reviewed.status_code == 200
    assert reviewed.get_json()["data"]["items"][0]["settlement_difference"] == 0
    assert service.list_price_adjustments(SALES)["total"] == 0
    completed = _detail(adjustment)
    assert (completed["status"], completed["approved_received"], completed["available_amount"]) == ("resolved", 11, 0)
    with pytest.raises(ValueError):
        service.create_receipt(_collection_body(customer, orders, adjustment, 1), SALES)


def test_partial_collection_remains_collectible_without_waiving_small_balance(setup_test_database):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    first = service.create_receipt(_collection_body(customer, orders, adjustment, 4), SALES)
    assert first["settlement_status"] == "unsettled"
    _review(first)
    remaining = _detail(adjustment)
    assert (remaining["status"], remaining["approved_received"], remaining["available_amount"]) == ("pending", 4, 7)
    with pytest.raises(ValueError, match="最多可收 7.00"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 8), SALES)
    final = service.create_receipt(_collection_body(customer, orders, adjustment, 7), SALES)
    _review(final)
    assert _detail(adjustment)["status"] == "resolved"
    ledger = service.accounts_receivable_ledger(date_to="2099-12-31")["items"][0]
    assert (ledger["received_amount"], ledger["settlement_difference"], ledger["outstanding_amount"]) == (143, 0, 0)


def test_duplicate_pending_partial_collection_is_rejected_and_rejection_releases_it(setup_test_database):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    first = service.create_receipt(_collection_body(customer, orders, adjustment, 4), SALES)
    assert _detail(adjustment)["available_amount"] == 0
    with pytest.raises(ValueError, match="已有待审核补收单"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 1), SALES)
    assert session.query(PaymentReceiptTable).count() == 2
    rejected = _review(first, "reject")
    assert rejected["items"][0]["adjustment_id"] == adjustment.id
    available = _detail(adjustment)
    assert (available["approved_received"], available["pending_amount"], available["available_amount"]) == (0, 0, 11)
    assert service.create_receipt(_collection_body(customer, orders, adjustment, 11), SALES)["status"] == "pending"


def test_supplemental_collection_cannot_request_settlement_waiver(setup_test_database):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    with pytest.raises(ValueError, match="差价补收必须选择未结清"):
        service.create_receipt(
            _collection_body(customer, orders, adjustment, 4, settlement_status="settled"), SALES,
        )


@pytest.mark.parametrize("second_is_adjustment", [False, True])
def test_supplemental_receipt_rejects_multiple_or_mixed_items(setup_test_database, second_is_adjustment):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    body = _collection_body(customer, orders, adjustment, 1)
    second = {"order_uid": "another-order", "amount": 1}
    if second_is_adjustment:
        second["adjustment_id"] = adjustment.id
    body["items"].append(second)
    with pytest.raises(ValueError, match="只能包含一笔差价明细"):
        service.create_receipt(body, SALES)


@pytest.mark.parametrize("invalid_id", [True, 0, -1, "bad", 1.5])
def test_invalid_adjustment_identifier_is_rejected(setup_test_database, invalid_id):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    body = _collection_body(customer, orders, adjustment, 1)
    body["items"][0]["adjustment_id"] = invalid_id
    with pytest.raises(ValueError, match="差价单编号无效"):
        service.create_receipt(body, SALES)


@pytest.mark.parametrize("change", ["wrong_order", "archived", "resolved", "refund"])
def test_uncollectible_or_wrong_order_adjustment_is_rejected(setup_test_database, change):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    if change == "wrong_order":
        adjustment.order_uid = "another-order"
    elif change == "archived":
        adjustment.archive = True
    elif change == "resolved":
        adjustment.status = "resolved"
    else:
        adjustment.direction = "refund"
        adjustment.delta_amount = Decimal("-11.00")
    session.commit()
    with pytest.raises(ValueError, match="差价"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 1), SALES)


def test_amount_cannot_exceed_delta_even_when_original_quote_is_unpaid(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    from tests.unit.test_order_receipt_revision import _add_receipt_history
    _add_receipt_history(session, customer, orders[0], status="rejected")
    service.create_order_quote(orders[0].uid, {"unit_price": 13, "surcharge": 0}, SALES)
    adjustment = session.query(OrderPriceAdjustmentTable).one()
    assert _detail(adjustment)["available_amount"] == 11
    with pytest.raises(ValueError, match="最多可补收 11.00"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 12), SALES)
    _review(service.create_receipt(_collection_body(customer, orders, adjustment, 11), SALES))
    assert _detail(adjustment)["status"] == "resolved"
    assert service.list_receivable_orders(customer.id, SALES)["items"][0]["available_amount"] == 132


def test_order_cash_reservations_cap_collection_and_ordinary_receipts_close_tasks(setup_test_database):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    ordinary = service.create_receipt(_body(customer, orders, [6], settlement_status="unsettled"), SALES)
    assert ordinary["items"][0]["adjustment_id"] is None
    assert _detail(adjustment)["available_amount"] == 5
    _review(ordinary)
    supplemental = service.create_receipt(_collection_body(customer, orders, adjustment, 5), SALES)
    _review(supplemental)
    final = _detail(adjustment)
    assert (final["status"], final["approved_received"]) == ("resolved", 5)


def test_ordinary_collection_closes_all_positive_tasks_for_fully_paid_order(setup_test_database):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    service.create_order_quote(orders[0].uid, {"unit_price": 14, "surcharge": 0}, SALES)
    assert service.list_price_adjustments(SALES)["total"] == 2
    receipt = service.create_receipt(_body(customer, orders, [22], settlement_status="unsettled"), SALES)
    _review(receipt)
    assert service.list_price_adjustments(SALES)["total"] == 0
    assert _detail(adjustment)["approved_received"] == 0


def test_existing_settlement_difference_is_preserved_when_collecting_new_delta(setup_test_database):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    original = session.query(PaymentReceiptItemTable).one()
    original.amount = Decimal("120.00")
    original.settlement_difference = Decimal("12.00")
    session.commit()
    assert _detail(adjustment)["available_amount"] == 11
    _review(service.create_receipt(_collection_body(customer, orders, adjustment, 4), SALES))
    ledger = service.accounts_receivable_ledger(date_to="2099-12-31")["items"][0]
    assert (ledger["received_amount"], ledger["settlement_difference"], ledger["outstanding_amount"]) == (124, 12, 7)
    assert _detail(adjustment)["available_amount"] == 7
    _review(service.create_receipt(_collection_body(customer, orders, adjustment, 7), SALES))
    assert _detail(adjustment)["status"] == "resolved"


@pytest.mark.parametrize("latest_price,available", [("12.5", 5.5), ("12", 0)])
def test_later_negative_delta_caps_prior_positive_collection_by_current_balance(
    setup_test_database, latest_price, available,
):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    service.create_order_quote(orders[0].uid, {"unit_price": latest_price, "surcharge": 0}, SALES)
    assert _detail(adjustment)["available_amount"] == available
    with pytest.raises(ValueError):
        service.create_receipt(_collection_body(customer, orders, adjustment, 11), SALES)
    if available:
        _review(service.create_receipt(_collection_body(customer, orders, adjustment, available), SALES))
        detail = _detail(adjustment)
        assert (detail["status"], detail["approved_received"]) == ("resolved", available)
        pending = service.list_price_adjustments(SALES)["items"]
        assert len(pending) == 1 and pending[0]["direction"] == "refund"
    else:
        assert "暂无可补收余额" in _detail(adjustment)["collection_blocked_reason"]


def test_pending_closing_receipt_blocks_supplemental_entry(setup_test_database):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    service.create_receipt(_body(customer, orders, [1], settlement_status="settled"), SALES)
    detail = _detail(adjustment)
    assert detail["available_amount"] == 0
    assert "待审核结清" in detail["collection_blocked_reason"]
    with pytest.raises(ValueError, match="待审核结清"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 1), SALES)


def test_earlier_supplemental_receipt_can_be_reviewed_before_later_closing_receipt(setup_test_database):
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    first = service.create_receipt(_collection_body(customer, orders, adjustment, 4), SALES)
    closing = service.create_receipt(_body(customer, orders, [7], settlement_status="settled"), SALES)
    _review(first)
    _review(closing)
    assert _detail(adjustment)["status"] == "resolved"


def test_refund_remains_read_only_and_is_never_closed_by_cash_collection(setup_test_database):
    session = setup_test_database
    customer, orders, refund = _seed_adjustment(session, unit_price=11)
    refund_detail = _detail(refund)
    assert (refund_detail["direction"], refund_detail["available_amount"]) == ("refund", 0)
    assert "退款" in refund_detail["collection_blocked_reason"]
    service.create_order_quote(orders[0].uid, {"unit_price": 13, "surcharge": 0}, SALES)
    with pytest.raises(ValueError, match="仅待处理的补收差价"):
        service.create_receipt(_collection_body(customer, orders, refund, 1), SALES)
    _review(service.create_receipt(_body(customer, orders, [11], settlement_status="unsettled"), SALES))
    assert _detail(refund)["status"] == "pending"
    assert service.list_price_adjustments(SALES)["total"] == 1


def test_requote_after_entry_requires_rejection_and_releases_task(setup_test_database):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    receipt = service.create_receipt(_collection_body(customer, orders, adjustment, 4), SALES)
    service.create_order_quote(orders[0].uid, {"unit_price": 14, "surcharge": 0}, SALES)
    with pytest.raises(ValueError, match="应收已变化"):
        _review(receipt)
    assert _detail(adjustment)["pending_amount"] == 4
    _review(receipt, "reject")
    assert _detail(adjustment)["available_amount"] == 11


def test_collection_permissions_follow_current_quote_owner_and_detail_has_errors(
    client, setup_test_database, salesperson_token,
):
    session = setup_test_database
    customer, orders, adjustment = _seed_adjustment(session)
    quote = session.query(OrderQuoteVersionTable).filter_by(id=adjustment.new_quote_id).one()
    quote.quoter_id = 1
    session.commit()
    assert service.list_price_adjustments(SALES)["items"] == []
    assert service.get_price_adjustment_detail(adjustment.id, FINANCE)["available_amount"] == 11
    with pytest.raises(PermissionError, match="跟单范围"):
        service.create_receipt(_collection_body(customer, orders, adjustment, 1), SALES)
    denied = client.get(f"/api/receivable-adjustments/{adjustment.id}", headers={"x-token": salesperson_token})
    assert denied.status_code == 403
    missing = client.get("/api/receivable-adjustments/99999", headers={"x-token": salesperson_token})
    assert missing.status_code == 404
    finance_only = {"user_id": 4, "name": "财务", "role": "finance"}
    detail = service.get_price_adjustment_detail(adjustment.id, finance_only)
    assert detail["available_amount"] == 0
    assert "无权创建" in detail["collection_blocked_reason"]


def test_receipt_mutations_and_requote_use_current_locked_quote_reads(setup_test_database, monkeypatch):
    lock_reads = []
    original = service.get_current_quote

    def observed(session, order_uid, *, for_update=False):
        lock_reads.append(for_update)
        return original(session, order_uid, for_update=for_update)

    monkeypatch.setattr(service, "get_current_quote", observed)
    customer, orders, adjustment = _seed_adjustment(setup_test_database)
    receipt = service.create_receipt(_collection_body(customer, orders, adjustment, 11), SALES)
    _review(receipt)
    assert lock_reads == [True, True, True]


def test_low_price_approval_reads_previous_effective_quote_with_lock(
    client, setup_test_database, admin_token, monkeypatch,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    _settle_original_quote(session, customer, orders[0])
    pending = service.create_order_quote(orders[0].uid, {"unit_price": 10, "surcharge": 0}, SALES)
    lock_reads = []
    original = service.get_current_quote

    def observed(session, order_uid, *, for_update=False):
        lock_reads.append(for_update)
        return original(session, order_uid, for_update=for_update)

    monkeypatch.setattr(service, "get_current_quote", observed)
    response = client.put(
        f"/api/finance/quote-approvals/{pending['id']}", headers={"x-token": admin_token},
        json={"action": "approve", "review_remark": "批准低价"},
    )
    assert response.status_code == 200
    assert lock_reads == [True]
    assert session.query(OrderPriceAdjustmentTable).one().delta_amount == Decimal("-22.00")


def test_adjustment_receipt_migration_preserves_historical_items_and_downgrades():
    path = Path(__file__).parents[2] / "alembic/versions/20260930_ce3f4a5b6c7d_adjustment_receipt_items.py"
    spec = importlib.util.spec_from_file_location("adjustment_receipt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE order_price_adjustments (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE payment_receipt_items (id INTEGER PRIMARY KEY, amount NUMERIC(14,2))"))
        connection.execute(sa.text("INSERT INTO payment_receipt_items VALUES (1, 11)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text("SELECT adjustment_id FROM payment_receipt_items")).scalar() is None
            foreign_keys = sa.inspect(connection).get_foreign_keys("payment_receipt_items")
            assert foreign_keys[0]["referred_table"] == "order_price_adjustments"
            assert foreign_keys[0]["constrained_columns"] == ["adjustment_id"]
            migration.downgrade()
        columns = {column["name"] for column in sa.inspect(connection).get_columns("payment_receipt_items")}
        assert "adjustment_id" not in columns
        assert connection.execute(sa.text("SELECT amount FROM payment_receipt_items")).scalar() == 11
