"""Receipt-wide settlement, cash accounting, and approval lifecycle regressions."""

from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from data.DB import OrderQuoteVersionTable, PaymentReceiptTable
from services import receivable_service as service
from tests.unit.test_order_receipt_revision import _seed_world


SALES = {"user_id": 3, "name": "业务员测试", "role": "salesperson"}
FINANCE = {"user_id": 1, "name": "管理员测试", "role": "admin"}


def _body(customer, orders, amounts, **extra):
    return {
        "customer_id": customer.id,
        "receipt_date": "2026-09-09",
        "payment_method": "cash",
        "items": [
            {"order_uid": order.uid, "amount": str(amount)}
            for order, amount in zip(orders, amounts)
        ],
        **extra,
    }


def _review(receipt, action="approve"):
    return service.review_receipt(receipt["id"], action, "测试审核", FINANCE)


def _ledger(**kwargs):
    return service.accounts_receivable_ledger(date_to="2099-12-31", **kwargs)


@pytest.mark.parametrize("remaining,expected", [
    ("0", "settled"), ("29.99", "settled"),
    ("30", "unsettled"), ("30.01", "unsettled"),
])
def test_default_uses_strict_thirty_yuan_boundary(setup_test_database, remaining, expected):
    customer, orders, _ = _seed_world(setup_test_database)
    amount = Decimal("132") - Decimal(remaining)
    receipt = service.create_receipt(_body(customer, orders, [amount]), SALES)
    assert receipt["settlement_status"] == expected
    assert receipt["total_amount"] == float(amount)
    assert receipt["items"][0]["remaining_after"] == float(remaining)
    assert receipt["items"][0]["settlement_difference"] is None
    assert service.list_receipts(SALES)["items"][0]["settlement_status"] == expected


@pytest.mark.parametrize("remaining,expected", [
    (("15", "15"), "unsettled"), (("14.99", "15"), "settled"),
])
def test_default_sums_all_selected_order_balances(setup_test_database, remaining, expected):
    customer, orders, _ = _seed_world(setup_test_database, order_count=2)
    amounts = [Decimal("132") - Decimal(remaining[0]), Decimal("144") - Decimal(remaining[1])]
    receipt = service.create_receipt(_body(customer, orders, amounts), SALES)
    assert receipt["settlement_status"] == expected


def test_default_ignores_other_pending_cash_but_reserves_it(setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database)
    service.create_receipt(_body(customer, orders, [40], settlement_status="unsettled"), SALES)
    receipt = service.create_receipt(_body(customer, orders, [82]), SALES)
    # Actual remaining is 50; the old reservation snapshot is still 10.
    assert receipt["settlement_status"] == "unsettled"
    assert receipt["items"][0]["remaining_after"] == 10
    with pytest.raises(ValueError, match="最多可收 10.00"):
        service.create_receipt(_body(customer, orders, [11]), SALES)


@pytest.mark.parametrize("status", [None, "paid", "", True, 1, [], {}])
def test_explicit_invalid_status_is_rejected_by_api(
    client, setup_test_database, salesperson_token, status,
):
    customer, orders, _ = _seed_world(setup_test_database)
    response = client.post(
        "/api/receipts",
        headers={"x-token": salesperson_token},
        json=_body(customer, orders, [100], settlement_status=status),
    )
    assert response.status_code == 400
    assert "结清状态" in response.get_json()["msg"]
    assert setup_test_database.query(PaymentReceiptTable).count() == 0


@pytest.mark.parametrize("amount,status,difference,expected_status", [
    (10, "settled", 122, "paid"),
    (127, "unsettled", 0, "partial"),
    (132, "unsettled", 0, "paid"),
])
def test_manual_choice_controls_waiver_without_changing_cash_or_quote(
    setup_test_database, amount, status, difference, expected_status,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    receipt = service.create_receipt(_body(customer, orders, [amount], settlement_status=status), SALES)
    assert receipt["settlement_status"] == status
    pending_ledger = _ledger()["items"][0]
    assert pending_ledger["received_amount"] == 0
    assert pending_ledger["settlement_difference"] == 0
    assert pending_ledger["outstanding_amount"] == 132
    approved = _review(receipt)
    assert approved["items"][0]["settlement_difference"] == difference
    assert approved["items"][0]["preview_settlement_difference"] is None
    row = _ledger()["items"][0]
    assert row["receivable_amount"] == 132
    assert row["received_amount"] == amount
    assert row["settlement_difference"] == difference
    assert row["outstanding_amount"] == 132 - amount - difference
    assert row["settlement_status"] == expected_status
    assert _ledger(settlement_status=expected_status)["total"] == 1
    quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=orders[0].uid).one()
    assert quote.receivable_amount == Decimal("132.00")


@pytest.mark.parametrize("other_action,expected_difference", [("approve", 22), ("reject", 62)])
def test_pending_settlement_waits_for_other_receipts_and_previews_latest_cash(
    setup_test_database, other_action, expected_difference,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    earlier = service.create_receipt(_body(customer, orders, [40], settlement_status="unsettled"), SALES)
    closing = service.create_receipt(_body(customer, orders, [70], settlement_status="settled"), SALES)
    assert closing["items"][0]["remaining_after"] == 22
    assert closing["items"][0]["preview_settlement_difference"] == 62
    assert service.list_receivable_orders(None, SALES)["items"] == []
    with pytest.raises(ValueError, match="已结清或存在待审核结清"):
        service.create_receipt(_body(customer, orders, [1], settlement_status="unsettled"), SALES)
    with pytest.raises(ValueError, match=earlier["receipt_no"]):
        _review(closing)
    assert service.get_receipt_detail(closing["id"], FINANCE)["status"] == "pending"

    _review(earlier, other_action)
    preview = service.get_receipt_detail(closing["id"], FINANCE)
    assert preview["items"][0]["preview_settlement_difference"] == expected_difference
    assert preview["items"][0]["remaining_after"] == 22
    approved = _review(closing)
    assert approved["items"][0]["settlement_difference"] == expected_difference
    with pytest.raises(ValueError, match="已结清或存在待审核结清"):
        service.create_receipt(_body(customer, orders, [1]), SALES)
    assert service.list_receivable_orders(None, SALES)["items"] == []


def test_rejecting_pending_settlement_restores_collectible_orders(setup_test_database):
    customer, orders, _ = _seed_world(setup_test_database)
    closing = service.create_receipt(_body(customer, orders, [10], settlement_status="settled"), SALES)
    rejected = _review(closing, "reject")
    assert rejected["items"][0]["settlement_difference"] is None
    assert rejected["items"][0]["preview_settlement_difference"] is None
    assert service.list_receivable_orders(None, SALES)["items"][0]["available_amount"] == 132
    assert service.create_receipt(_body(customer, orders, [10]), SALES)["status"] == "pending"


def test_multi_order_approval_is_atomic_and_applies_choice_to_every_order(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session, order_count=2)
    earlier = service.create_receipt(_body(customer, orders[:1], [20], settlement_status="unsettled"), SALES)
    closing = service.create_receipt(_body(customer, orders, [100, 100], settlement_status="settled"), SALES)
    with pytest.raises(ValueError, match="其他待审核收据"):
        _review(closing)
    detail = service.get_receipt_detail(closing["id"], FINANCE)
    assert all(item["settlement_difference"] is None for item in detail["items"])
    assert detail["status"] == "pending"
    _review(earlier, "reject")
    approved = _review(closing)
    assert [item["settlement_difference"] for item in approved["items"]] == [32, 44]
    ledger = _ledger()
    assert all(row["settlement_status"] == "paid" for row in ledger["items"])
    assert ledger["totals"]["received_amount"] == 200
    assert ledger["totals"]["settlement_difference"] == 76
    assert ledger["totals"]["outstanding_amount"] == 0


def test_cutoff_and_same_second_approvals_preserve_the_closing_receipt(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    closing = service.create_receipt(_body(customer, orders, [100], settlement_status="settled"), SALES)
    # Model an older client receipt existing before deployment. Its ID is later
    # than the closing receipt, but it must be approved first.
    closing_row = session.query(PaymentReceiptTable).filter_by(id=closing["id"]).one()
    closing_row.settlement_status = None
    session.commit()
    earlier = service.create_receipt(_body(customer, orders, [20], settlement_status="unsettled"), SALES)
    closing_row = session.query(PaymentReceiptTable).filter_by(id=closing["id"]).one()
    closing_row.settlement_status = "settled"
    session.commit()
    _review(earlier)
    _review(closing)
    for receipt in session.query(PaymentReceiptTable).all():
        receipt.create_date = "2026-09-09 09:00:00"
        receipt.review_date = "2026-09-10 10:00:00"
    session.commit()
    before = service.accounts_receivable_ledger(date_to="2026-09-09")["totals"]
    after = service.accounts_receivable_ledger(date_to="2026-09-10")["totals"]
    assert (before["received_amount"], before["settlement_difference"], before["pending_amount"]) == (0, 0, 120)
    assert (after["received_amount"], after["settlement_difference"], after["outstanding_amount"]) == (120, 12, 0)


def test_historical_null_receipt_keeps_small_balance_collectible(setup_test_database):
    session = setup_test_database
    customer, orders, _ = _seed_world(session)
    receipt = service.create_receipt(_body(customer, orders, [120], settlement_status="unsettled"), SALES)
    row = session.query(PaymentReceiptTable).filter_by(id=receipt["id"]).one()
    row.settlement_status = None
    session.commit()
    approved = _review(receipt)
    assert approved["settlement_status"] is None
    assert approved["items"][0]["settlement_difference"] is None
    assert _ledger()["totals"]["outstanding_amount"] == 12
    assert service.list_receivable_orders(None, SALES)["items"][0]["available_amount"] == 12


def test_review_date_is_recorded_after_waiting_for_order_locks(setup_test_database, monkeypatch):
    customer, orders, _ = _seed_world(setup_test_database)
    receipt = service.create_receipt(_body(customer, orders, [100], settlement_status="settled"), SALES)
    clock = ["2026-09-09 23:59:59"]
    monkeypatch.setattr(service, "time", SimpleNamespace(strftime=lambda _format: clock[0]))
    original = service._locked_receipt_allocations

    def after_midnight(*args, **kwargs):
        clock[0] = "2026-09-10 00:00:01"
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_locked_receipt_allocations", after_midnight)
    approved = _review(receipt)
    assert approved["review_date"] == "2026-09-10 00:00:01"


def test_settlement_migration_preserves_historical_rows_and_downgrades():
    path = Path(__file__).parents[2] / "alembic/versions/20260909_7f8a9b0c1d2e_receipt_settlement.py"
    spec = importlib.util.spec_from_file_location("receipt_settlement_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE payment_receipts (id INTEGER PRIMARY KEY, status VARCHAR(32))"))
        connection.execute(sa.text("CREATE TABLE payment_receipt_items (id INTEGER PRIMARY KEY, amount NUMERIC(14,2), remaining_after NUMERIC(14,2))"))
        connection.execute(sa.text("INSERT INTO payment_receipts VALUES (1, 'approved')"))
        connection.execute(sa.text("INSERT INTO payment_receipt_items VALUES (1, 120, 12)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text("SELECT settlement_status FROM payment_receipts")).scalar() is None
            assert connection.execute(sa.text("SELECT settlement_difference FROM payment_receipt_items")).scalar() is None
            migration.downgrade()
        assert connection.execute(sa.text("SELECT amount, remaining_after FROM payment_receipt_items")).one() == (120, 12)
        assert "settlement_status" not in {column["name"] for column in sa.inspect(connection).get_columns("payment_receipts")}
