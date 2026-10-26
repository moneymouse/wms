"""One independent money record from sales entry to finance approval."""
import base64
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from Auth import create_jwt
from data.customer.Customer import CustomerTable
from data.DB import CargoTable, OrderTable, AuditLogTable
from data.finance.accounting import FinanceJournalEntry
from data.finance.ledger import FinanceAllocation, FinancePayment
from services import finance_ledger_service as ledger
from services import finance_accounting_service as accounting
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import finance, ACTOR, SALES, document
from utils.finance_payment_pdf import build_finance_payment_pdf


OTHER_SALES = {"id": 703, "user_id": 703, "name": "另一业务员", "roles": ["salesperson"]}
OTHER_FINANCE = {"id": 704, "user_id": 704, "name": "第二财务", "roles": ["finance"]}


@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
@pytest.mark.parametrize("actor", [SALES, ACTOR, {"id": 705, "name": "管理员", "roles": ["admin"]}])
def test_pending_payment_cancellation_preserves_record_and_history(finance, direction, actor):
    created = ledger.create_payment(body(finance, direction=direction), SALES)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, SALES)
    request = {"version": pending["version"], "reason": "金额登记错误", "idempotency_key": "cancel-pending"}
    cancelled = ledger.cancel_payment(created["id"], request, actor)
    assert cancelled["status"] == "cancelled"
    assert cancelled["number"] == created["number"]
    assert cancelled["amount"] == created["amount"]
    assert cancelled["submitted_at"] == pending["submitted_at"]
    assert cancelled["cancelled_at"]
    assert cancelled["cancellation_reason"] == request["reason"]
    assert ledger.cancel_payment(created["id"], request, actor) == cancelled
    events = ledger.history("payments", created["id"], actor)
    cancellations = [event for event in events["items"] if event["action"] == "cancel"]
    assert len(cancellations) == 1
    assert cancellations[0]["remark"] == request["reason"]
    assert cancellations[0]["operator_id"] == actor.get("user_id", actor["id"])
    assert cancellations[0]["before_data"]["status"] == "pending"
    assert cancellations[0]["after_data"]["status"] == "cancelled"
    with TestSessionFactory() as session:
        assert session.get(FinancePayment, created["id"]).status == "cancelled"
        assert session.query(FinanceAllocation).count() == 0
        assert session.query(FinanceJournalEntry).count() == 0
    with pytest.raises(ledger.FinanceConflictError):
        ledger.post_payment(created["id"], {"version": pending["version"]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.submit_payment(created["id"], {"version": cancelled["version"]}, SALES)


def test_pending_cancellation_requires_owner_reason_and_current_version(finance):
    created = ledger.create_payment(body(finance), SALES)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, SALES)
    with pytest.raises(PermissionError):
        ledger.cancel_payment(created["id"], {"version": pending["version"], "reason": "错误"}, OTHER_SALES)
    with pytest.raises(ValueError):
        ledger.cancel_payment(created["id"], {"version": pending["version"], "reason": "  "}, SALES)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.cancel_payment(created["id"], {"version": created["version"], "reason": "错误"}, SALES)
    posted = ledger.post_payment(created["id"], {"version": pending["version"]}, ACTOR)
    with pytest.raises(ledger.FinanceConflictError):
        ledger.cancel_payment(created["id"], {"version": posted["version"], "reason": "错误"}, SALES)
    assert ledger.get_payment(created["id"], SALES)["status"] == "posted"


def body(finance, **extra):
    return {"partner_type": "customer", "partner_id": finance["customer"], "direction": "incoming",
        "account_id": finance["account"]["id"], "payment_date": "2026-01-10", "amount": "100.00", **extra}


@pytest.fixture
def customer_orders(finance):
    with TestSessionFactory() as session:
        customer = session.get(CustomerTable, finance["customer"])
        other = session.get(CustomerTable, finance["other_customer"])
        first = OrderTable(uid="customer-empty-order", order_id="EMPTY-ORDER", customer_name=customer.name,
            archive=False, salesman_id=OTHER_SALES["id"], create_date="2026-10-05 09:30", order_date="2026-10-01 08:00",
            transportation="DHL", receiver="Jane Doe", receiver_phone="555-0100", mail="jane@example.com",
            country="美国", province="NY", city="New York", address="123 Broadway", en_name="Office Supplies",
            cn_name="办公用品", post_code="HS-123", zip_code="10001", tag_all="甲客户最新唛头", total_weight=12.5,
            cargo_count=3, update_date="2026-10-05 10:00")
        first.customers = [customer]
        second = OrderTable(uid="customer-cargo-order", order_id="CARGO-ORDER", customer_name=customer.name,
            archive=False, create_date="2026-10-04 09:30", receiver="John Smith", country="英国")
        second.customers = [customer]
        wrong = OrderTable(uid="another-customer-order", order_id="OTHER-ORDER", customer_name=other.name, archive=False)
        wrong.customers = [other]
        session.add_all([first, second, wrong])
        session.add(CargoTable(uid="customer-payment-box", target_order_uid=second.uid, weight=10, archive=False, status=0))
        session.commit()
    return ["customer-empty-order", "customer-cargo-order"]


def test_sales_registers_customer_money_without_any_order_or_quote(finance):
    payment = ledger.create_payment(body(finance), SALES)
    assert payment["status"] == "draft"
    assert payment["requires_submission"] is True
    assert payment["reference_orders"] == []
    assert payment["amount"] == "100.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).count() == 0
        assert session.query(FinanceJournalEntry).count() == 0
    with pytest.raises(ledger.FinanceConflictError, match="尚未提交"):
        ledger.post_payment(payment["id"], {"version": payment["version"]}, ACTOR)


def test_empty_unquoted_other_salesperson_orders_are_optional_notes_only(finance, customer_orders):
    choices = ledger.payment_options("orders", SALES, customer_id=finance["customer"])
    assert {row["order_uid"] for row in choices["items"]} == set(customer_orders)
    payment = ledger.create_payment(body(finance, amount="555.50", reference_order_uids=customer_orders), SALES)
    assert payment["reference_order_uids"] == customer_orders
    assert payment["reference_orders"][0]["order_number"] == "EMPTY-ORDER"
    pending = ledger.submit_payment(payment["id"], {"version": payment["version"]}, SALES)
    with TestSessionFactory() as session:
        session.query(CargoTable).filter_by(uid="customer-payment-box").one().weight = 999
        order = session.query(OrderTable).filter_by(uid=customer_orders[0]).one()
        order.order_id, order.archive = "RENAMED-ORDER", True
        session.commit()
    posted = ledger.post_payment(payment["id"], {"version": pending["version"]}, ACTOR)
    assert posted["amount"] == "555.50"
    assert posted["reference_orders"][0]["order_number"] == "EMPTY-ORDER"
    assert posted["allocated_amount"] == "0.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceAllocation).count() == 0


def test_payment_order_options_return_order_list_fields_without_financial_data(finance, customer_orders):
    with TestSessionFactory() as session:
        customer = session.get(CustomerTable, finance["customer"])
        customer.phone, customer.wechat = "13912345678", "private-customer-contact"
        session.commit()
    choices = ledger.payment_options("orders", SALES, customer_id=finance["customer"])
    assert [row["order_uid"] for row in choices["items"]] == customer_orders
    latest = choices["items"][0]
    assert latest == {
        "uid": "customer-empty-order", "order_id": "EMPTY-ORDER", "order_uid": "customer-empty-order",
        "order_number": "EMPTY-ORDER", "customer_id": finance["customer"], "customer_name": "甲客户",
        "transportation": "DHL", "receiver": "Jane Doe", "receiver_phone": "555-0100", "mail": "jane@example.com",
        "country": "美国", "province": "NY", "city": "New York", "address": "123 Broadway",
        "en_name": "Office Supplies", "cn_name": "办公用品", "post_code": "HS-123", "zip_code": "10001",
        "tag_all": "甲客户最新唛头", "create_date": "2026-10-05 09:30", "order_date": "2026-10-05 09:30",
        "update_date": "2026-10-05 10:00", "total_weight": 12.5, "cargo_count": 3,
    }
    assert not {"phone", "wechat", "salesman", "salesman_id", "archive", "quote", "cost", "balance"}.intersection(latest)


def test_payment_order_options_keep_customer_scope_and_stable_creation_paging(finance, customer_orders):
    with TestSessionFactory() as session:
        customer = session.get(CustomerTable, finance["customer"])
        other = session.get(CustomerTable, finance["other_customer"])
        tie = OrderTable(uid="z-customer-order", order_id="TIE-ORDER", customer_name=customer.name,
            create_date="2026-10-05 09:30", archive=False)
        tie.customers = [customer]
        # A stale customer name must never override an explicit customer link.
        wrong = OrderTable(uid="wrong-customer-link", customer_name=customer.name,
            create_date="2026-10-06 10:00", archive=False)
        wrong.customers = [other]
        archived = OrderTable(uid="archived-customer-order", customer_name=customer.name,
            create_date="2026-10-06 10:00", archive=True)
        archived.customers = [customer]
        legacy = OrderTable(uid="legacy-customer-order", customer_name=customer.name,
            order_date="2026-09-01 09:00", archive=False)
        session.add_all([tie, wrong, archived, legacy])
        session.commit()
    pages = [ledger.payment_options("orders", SALES, customer_id=finance["customer"], page=p, page_size=1)
        for p in range(1, 5)]
    assert [row["items"][0]["order_uid"] for row in pages] == ["z-customer-order", *customer_orders, "legacy-customer-order"]
    assert all(row["total"] == 4 and row["page_size"] == 1 for row in pages)
    legacy_option = pages[-1]["items"][0]
    assert legacy_option["order_id"] == legacy_option["order_number"] == "legacy-customer-order"
    assert legacy_option["order_date"] == "2026-09-01 09:00"


@pytest.mark.parametrize("query", ["Jane", "Broadway", "DHL", "办公用品", "最新唛头", "2026-10-05 09:30"])
def test_payment_order_options_search_operational_fields_within_customer(finance, customer_orders, query):
    choices = ledger.payment_options("orders", SALES, customer_id=finance["customer"], q=query)
    assert choices["total"] == 1
    assert choices["items"][0]["order_uid"] == customer_orders[0]
    assert ledger.payment_options("orders", SALES, customer_id=finance["other_customer"], q=query)["total"] == 0


def test_payment_order_options_http_returns_creation_sorted_paged_customer_rows(finance, customer_orders, client):
    response = client.get(f"/api/finance/v2/payment-options/orders?customer_id={finance['customer']}&p=1&s=1",
        headers={"x-token": create_jwt(SALES)})
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert (data["total"], data["page"], data["page_size"]) == (2, 1, 1)
    assert data["items"][0]["uid"] == customer_orders[0]
    assert data["items"][0]["receiver"] == "Jane Doe"


@pytest.mark.parametrize("references", [["another-customer-order"], ["missing-order"], ["customer-empty-order", "customer-empty-order"], "customer-empty-order"])
def test_invalid_or_cross_customer_notes_never_create_money(finance, customer_orders, references):
    with pytest.raises(ValueError):
        ledger.create_payment(body(finance, reference_order_uids=references), SALES)
    with TestSessionFactory() as session:
        assert session.query(FinancePayment).count() == 0


def test_sales_scope_cannot_be_broadened_by_filter_id_or_history(finance):
    own = ledger.create_payment(body(finance), SALES)
    other = ledger.create_payment(body(finance), OTHER_SALES)
    assert [row["id"] for row in ledger.list_payments(SALES, created_by_id=OTHER_SALES["id"])["items"]] == [own["id"]]
    assert ledger.list_payments(ACTOR)["total"] == 2
    assert ledger.list_payments(ACTOR, created_by_id=OTHER_SALES["id"])["items"][0]["id"] == other["id"]
    for operation in (lambda: ledger.get_payment(other["id"], SALES), lambda: ledger.history("payments", other["id"], SALES),
        lambda: ledger.update_payment(other["id"], {"version": other["version"], "amount": "900"}, SALES),
        lambda: ledger.cancel_payment(other["id"], {"version": other["version"], "reason": "bad"}, SALES),
        lambda: ledger.submit_payment(other["id"], {"version": other["version"]}, SALES)):
        with pytest.raises(PermissionError):
            operation()


def test_return_edit_resubmit_and_post_use_same_payment_and_complete_history(finance):
    created = ledger.create_payment(body(finance), SALES)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, SALES)
    assert pending["status"] == "pending"
    assert pending["available_amount"] == "0.00"
    dashboard = ledger.dashboard(ACTOR, "2026-01-20")
    assert dashboard["account_balance"] == "0.00"
    assert dashboard["pending_payments"] == 1
    assert dashboard["draft_payments"] == 0
    with pytest.raises(ledger.FinanceConflictError):
        ledger.update_payment(created["id"], {"version": pending["version"], "amount": "10"}, SALES)
    returned = ledger.return_payment(created["id"], {"version": pending["version"], "reason": "请按银行回单改为 80 元"}, ACTOR)
    assert returned["status"] == "draft"
    assert returned["review_remark"] == "请按银行回单改为 80 元"
    updated = ledger.update_payment(created["id"], {"version": returned["version"], "amount": "80"}, SALES)
    pending_again = ledger.submit_payment(created["id"], {"version": updated["version"]}, SALES)
    posted = ledger.post_payment(created["id"], {"version": pending_again["version"], "reason": "到账核对一致"}, ACTOR)
    assert posted["id"] == created["id"]
    assert posted["amount"] == "80.00"
    assert posted["reviewed_by_id"] == ACTOR["id"]
    assert posted["allocated_amount"] == "0.00"
    assert ledger.dashboard(ACTOR, "2026-01-20")["account_balance"] == "80.00"
    history = ledger.history("payments", created["id"], SALES)
    assert [row["action"] for row in reversed(history["items"])] == ["create", "submit", "return", "update", "submit", "post"]
    with TestSessionFactory() as session:
        assert session.query(FinancePayment).count() == 1
        assert session.query(FinanceJournalEntry).count() == 1


def test_business_refund_can_wait_for_finance_balance_without_losing_record(finance):
    refund = ledger.create_payment(body(finance, direction="outgoing", amount="120"), SALES)
    pending = ledger.submit_payment(refund["id"], {"version": refund["version"]}, SALES)
    with pytest.raises(ValueError, match="可退余额"):
        ledger.post_payment(refund["id"], {"version": pending["version"]}, ACTOR)
    assert ledger.get_payment(refund["id"], SALES)["status"] == "pending"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0


def test_pending_creator_cannot_approve_or_return_own_record(finance):
    created = ledger.create_payment(body(finance), ACTOR)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, ACTOR)
    for operation in (ledger.post_payment, ledger.return_payment):
        with pytest.raises(PermissionError, match="不能审核自己"):
            operation(created["id"], {"version": pending["version"], "reason": "自己审核"}, ACTOR)
    assert ledger.post_payment(created["id"], {"version": pending["version"]}, OTHER_FINANCE)["status"] == "posted"


def test_business_permission_never_authorizes_posting_vendor_opening_or_allocations(finance):
    created = ledger.create_payment(body(finance), SALES)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, SALES)
    for operation in (lambda: ledger.post_payment(created["id"], {"version": pending["version"]}, SALES),
        lambda: ledger.return_payment(created["id"], {"version": pending["version"], "reason": "绕过"}, SALES),
        lambda: ledger.reverse_payment(created["id"], {"version": pending["version"], "reason": "绕过"}, SALES),
        lambda: ledger.create_payment(body(finance, partner_type="vendor", partner_id=finance["vendor"]["id"]), SALES),
        lambda: ledger.create_payment(body(finance, is_opening=True, payment_date="2026-01-01"), SALES),
        lambda: ledger.create_allocations({"payment_id": created["id"], "version": pending["version"], "allocations": []}, SALES)):
        with pytest.raises(PermissionError):
            operation()
    doc = document(finance)
    with pytest.raises(ledger.FinanceConflictError, match="已生效"):
        ledger.create_allocations({"payment_id": created["id"], "version": pending["version"], "allocation_date": "2026-01-20",
            "allocations": [{"document_id": doc["id"], "amount": "20"}]}, ACTOR)


def test_business_lookups_expose_account_identity_but_no_balances(finance, customer_orders):
    accounts = ledger.payment_options("accounts", SALES)
    assert accounts["items"][0]["id"] == finance["account"]["id"]
    assert "balance" not in accounts["items"][0]
    assert ledger.payment_options("customers", SALES)["total"] == 2
    with pytest.raises(PermissionError):
        ledger.list_masters("accounts", SALES)
    with pytest.raises(PermissionError):
        ledger.payment_options("accounts", {"id": 99, "roles": ["worker"]})


def test_submission_idempotency_conflict_and_audit_rollback(finance, monkeypatch):
    created = ledger.create_payment(body(finance), SALES)
    command = {"version": created["version"], "idempotency_key": "customer-submit"}
    first = ledger.submit_payment(created["id"], command, SALES)
    assert ledger.submit_payment(created["id"], command, SALES) == first
    with pytest.raises(ledger.FinanceConflictError):
        ledger.submit_payment(created["id"], {**command, "reason": "changed"}, SALES)
    original_audit = ledger.record_audit
    def fail(**kwargs):
        if kwargs["action"] == "return":
            raise RuntimeError("audit failed")
        return original_audit(**kwargs)
    monkeypatch.setattr(ledger, "record_audit", fail)
    with pytest.raises(RuntimeError):
        ledger.return_payment(created["id"], {"version": first["version"], "reason": "退回"}, ACTOR)
    assert ledger.get_payment(created["id"], SALES)["status"] == "pending"


def test_business_http_and_pdf_scope_and_fund_status(finance, customer_orders, client):
    sales_headers = {"x-token": create_jwt(SALES)}
    other_headers = {"x-token": create_jwt(OTHER_SALES)}
    created = client.post("/api/finance/v2/payments", json=body(finance, reference_order_uids=customer_orders), headers=sales_headers)
    assert created.status_code == 200
    row = created.get_json()["data"]
    submitted = client.post(f"/api/finance/v2/payments/{row['id']}/submit", json={"version": row["version"]}, headers=sales_headers)
    assert submitted.status_code == 200
    pdf = client.get(f"/api/finance/v2/payments/{row['id']}/pdf", headers=sales_headers)
    assert pdf.status_code == 200
    assert base64.b64decode(pdf.get_json()["data"]).startswith(b"%PDF-")
    assert client.get(f"/api/finance/v2/payments/{row['id']}/pdf", headers=other_headers).status_code == 403
    assert client.get(f"/api/finance/v2/payments/{row['id']}/history", headers=other_headers).status_code == 403
    assert client.get("/api/finance/v2/payment-options/accounts", headers=sales_headers).status_code == 200
    assert client.get(f"/api/finance/v2/payment-options/orders?customer_id={finance['customer']}", headers=sales_headers).get_json()["data"]["total"] == 2
    assert client.get("/api/finance/v2/accounts", headers=sales_headers).status_code == 403
    assert client.post(f"/api/finance/v2/payments/{row['id']}/post", json={"version": submitted.get_json()['data']['version']}, headers=sales_headers).status_code == 403


def test_payment_pdf_handles_long_memo_and_many_reference_orders(finance):
    value = ledger.create_payment(body(finance, memo="长备注 <需要核对> & 原始回单。" * 220), SALES)
    value["reference_orders"] = [{"order_uid": f"row-{i}", "order_number": f"说明订单 {i}"} for i in range(100)]
    rendered = build_finance_payment_pdf(value).getvalue()
    assert rendered.startswith(b"%PDF-")
    assert len(rendered) > 5000


def test_idempotency_replay_does_not_bypass_reduced_role_scope(finance):
    values = body(finance, partner_type="vendor", partner_id=finance["vendor"]["id"], idempotency_key="financial-only-record")
    ledger.create_payment(values, ACTOR)
    restricted = {**ACTOR, "roles": ["salesperson"]}
    with pytest.raises(PermissionError, match="自己登记的客户"):
        ledger.create_payment(values, restricted)


def test_pending_review_blocks_month_close_with_explicit_pending_count(finance):
    settings = accounting.get_settings(ACTOR)
    accounting.confirm_opening({"version": settings["version"], "reason": "已核对零期初"}, ACTOR)
    period = accounting.list_periods(ACTOR)[0]
    created = ledger.create_payment(body(finance), SALES)
    pending = ledger.submit_payment(created["id"], {"version": created["version"]}, SALES)
    checks = accounting.closing_checks(period["id"], ACTOR)
    payment_check = next(item for item in checks["checks"] if item["key"] == "payments")
    assert payment_check["count"] == payment_check["pending_count"] == 1
    assert payment_check["draft_count"] == 0
    assert checks["can_close"] is False
    with pytest.raises(ValueError):
        accounting.period_action(period["id"], "close", {"version": period["version"], "reason": "不能跳过待审款"}, ACTOR)
    returned = ledger.return_payment(created["id"], {"version": pending["version"], "reason": "误录，退回取消"}, ACTOR)
    checks = accounting.closing_checks(period["id"], ACTOR)
    payment_check = next(item for item in checks["checks"] if item["key"] == "payments")
    assert (payment_check["pending_count"], payment_check["draft_count"]) == (0, 1)
    ledger.cancel_payment(created["id"], {"version": returned["version"], "reason": "错误登记"}, SALES)
    assert accounting.closing_checks(period["id"], ACTOR)["can_close"] is True


def test_customer_payment_migration_preserves_existing_records_and_downgrades():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261006_249fa0b1c2d3_unified_customer_payments.py"
    spec = importlib.util.spec_from_file_location("customer_payment_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE finance_payments (id INTEGER PRIMARY KEY, created_by_id INTEGER, status VARCHAR(16))"))
        connection.execute(text("INSERT INTO finance_payments VALUES (1, 10, 'posted')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        row = connection.execute(text("SELECT status, requires_submission, reference_orders_json FROM finance_payments WHERE id=1")).one()
        assert row == ("posted", 0, None)
        assert "review_remark" in {col["name"] for col in inspect(connection).get_columns("finance_payments")}
        migration.downgrade()
        assert connection.execute(text("SELECT status FROM finance_payments WHERE id=1")).scalar() == "posted"
        assert "review_remark" not in {col["name"] for col in inspect(connection).get_columns("finance_payments")}
