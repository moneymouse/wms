"""Financial returns and notifications share actual ORM transactions.

Standalone: pytest --confcutdir=tests/finance tests/finance/test_payment_return_messages.py
"""

import os
from pathlib import Path
import sys

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from data.database import Base
from data.customer.Customer import CustomerTable
from data.DB import AuditLogTable, OrderTable
from data.finance.accounting import FinanceSettings  # noqa: F401 registers _run lock table
from data.finance.ledger import FinanceAccount, FinanceIdempotency, FinancePayment, FinanceVendor
from data.message import MessageTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import finance_ledger_service as ledger
from services import message_service


REGISTRAR = {"user_id": 101, "name": "原登记业务员", "roles": ["salesperson"]}
SUBMITTER = {"user_id": 102, "name": "代提交财务", "roles": ["finance"]}
REVIEWER = {"user_id": 103, "name": "复核财务", "roles": ["finance"]}
OTHER_SALES = {"user_id": 104, "name": "订单业务员", "roles": ["salesperson"]}
TODAY = "2026-10-07"


@pytest.fixture
def return_database(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # sqlite3 legacy mode must not release a first savepoint as a commit.
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(ledger, "SessionFactory", factory)
    monkeypatch.setattr(message_service, "SessionFactory", factory)
    with factory() as session:
        roles = {name: RoleTable(name=name, label=name) for name in ("salesperson", "finance", "worker")}
        session.add_all(list(roles.values()))
        for actor in (REGISTRAR, SUBMITTER, REVIEWER, OTHER_SALES):
            session.add(UserTable(id=actor["user_id"], phone=f"13800000{actor['user_id']:03d}", name=actor["name"],
                password="test", status="approved", roles=[roles[actor["roles"][0]]]))
        session.add(CustomerTable(id=201, name="客户"))
        session.add(FinanceVendor(id=202, name="供应商", created_at=TODAY, updated_at=TODAY))
        session.add(FinanceAccount(id=301, name="资金账户", account_type="bank", created_at=TODAY, updated_at=TODAY))
        session.commit()
    yield factory
    engine.dispose()


def _pending(database, *, creator=REGISTRAR, submitter=SUBMITTER, partner_type="customer", reference_order=False):
    values = {"partner_type": partner_type, "partner_id": 201 if partner_type == "customer" else 202,
        "direction": "incoming" if partner_type == "customer" else "outgoing", "account_id": 301,
        "payment_date": TODAY, "amount": "100.00"}
    if reference_order:
        with database() as session:
            order = OrderTable(uid="other-sales-order", order_id="ORDER-OTHER", salesman_id=OTHER_SALES["user_id"], archive=False)
            order.customers = [session.get(CustomerTable, 201)]
            session.add(order)
            session.commit()
        values["reference_order_uids"] = ["other-sales-order"]
    payment = ledger.create_payment(values, creator)
    return ledger.submit_payment(payment["id"], {"version": payment["version"]}, submitter)


def _return(payment, *, reason="请核对回单金额", key=None, actor=REVIEWER):
    command = {"version": payment["version"], "reason": reason}
    if key:
        command["idempotency_key"] = key
    return ledger.return_payment(payment["id"], command, actor)


def _rows(database):
    with database() as session:
        return session.query(MessageTable).order_by(MessageTable.created_at).all()


def test_return_notifies_original_registrar_with_reason_and_exact_edit_link(return_database):
    pending = _pending(return_database, reference_order=True)
    assert pending["submitted_by_id"] == SUBMITTER["user_id"]
    returned = _return(pending, reason="金额与银行回单不符，请修改为 80 元")
    assert returned["status"] == "draft"
    notice, = _rows(return_database)
    assert notice.recipient_id == REGISTRAR["user_id"]
    assert notice.recipient_id not in (SUBMITTER["user_id"], REVIEWER["user_id"], OTHER_SALES["user_id"])
    assert pending["number"] in notice.title and pending["number"] in notice.body
    assert "金额与银行回单不符，请修改为 80 元" in notice.body
    assert "修改" in notice.body and "重新提交" in notice.body
    assert notice.category == "finance_return"
    assert notice.source_name == "财务：复核财务"
    assert notice.action_path == f"/receipts?payment_id={pending['id']}"
    assert notice.business_type == "finance_payment" and notice.business_id == str(pending["id"])
    assert notice.event_key == f"finance:payment:return:{pending['id']}:{returned['version']}"
    assert notice.read_at is None
    with return_database() as session:
        audit = session.query(AuditLogTable).filter_by(action="return", target_id=str(pending["id"])).one()
        assert audit.remark == "金额与银行回单不符，请修改为 80 元"


def test_return_idempotency_retry_does_not_duplicate_notification(return_database):
    pending = _pending(return_database)
    first = _return(pending, key="return-request-1")
    second = _return(pending, key="return-request-1")
    assert second == first
    assert len(_rows(return_database)) == 1
    with return_database() as session:
        assert session.query(AuditLogTable).filter_by(action="return").count() == 1
        assert session.query(FinanceIdempotency).count() == 1


def test_separate_return_cycles_create_separate_notifications(return_database):
    pending = _pending(return_database)
    first_return = _return(pending, key="first-return")
    changed = ledger.update_payment(pending["id"], {"version": first_return["version"], "amount": "80"}, REGISTRAR)
    pending_again = ledger.submit_payment(pending["id"], {"version": changed["version"]}, REGISTRAR)
    second_return = _return(pending_again, key="second-return", reason="回单仍需补全")
    notices = _rows(return_database)
    assert len(notices) == 2
    assert {row.event_key for row in notices} == {
        f"finance:payment:return:{pending['id']}:{first_return['version']}",
        f"finance:payment:return:{pending['id']}:{second_return['version']}",
    }


@pytest.mark.parametrize("failure", ["delivery", "audit"])
def test_delivery_or_audit_failure_rolls_back_status_audit_and_notice(return_database, monkeypatch, failure):
    pending = _pending(return_database)
    audit_count = None
    with return_database() as session:
        audit_count = session.query(AuditLogTable).count()
    if failure == "delivery":
        original = ledger.send_message

        def fail_after_notice(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("delivery failed after insert")

        monkeypatch.setattr(ledger, "send_message", fail_after_notice)
    else:
        original = ledger.record_audit

        def fail_after_audit(**kwargs):
            original(**kwargs)
            if kwargs["action"] == "return":
                raise RuntimeError("audit failed after insert")

        monkeypatch.setattr(ledger, "record_audit", fail_after_audit)
    with pytest.raises(RuntimeError):
        _return(pending, key="failed-return")
    with return_database() as session:
        payment = session.get(FinancePayment, pending["id"])
        assert payment.status == "pending" and payment.version == pending["version"]
        assert payment.reviewed_at is None and payment.review_remark is None
        assert session.query(MessageTable).count() == 0
        assert session.query(AuditLogTable).count() == audit_count
        assert session.query(FinanceIdempotency).count() == 0


@pytest.mark.parametrize("invalid_case", ["stale", "missing_reason", "salesperson", "self_review", "draft"])
def test_invalid_or_forbidden_returns_do_not_attempt_notification(return_database, monkeypatch, invalid_case):
    pending = _pending(return_database, creator=REVIEWER if invalid_case == "self_review" else REGISTRAR)
    command = {"version": pending["version"], "reason": "退回原因"}
    actor = REVIEWER
    error_type = ledger.FinanceConflictError
    if invalid_case == "stale":
        command["version"] -= 1
    elif invalid_case == "missing_reason":
        command.pop("reason")
        error_type = ValueError
    elif invalid_case == "salesperson":
        actor, error_type = REGISTRAR, PermissionError
    elif invalid_case == "self_review":
        error_type = PermissionError
    elif invalid_case == "draft":
        with return_database() as session:
            session.get(FinancePayment, pending["id"]).status = "draft"
            session.commit()

    def must_not_send(*args, **kwargs):
        pytest.fail("invalid return attempted notification")

    monkeypatch.setattr(ledger, "send_message", must_not_send)
    with pytest.raises(error_type):
        ledger.return_payment(pending["id"], command, actor)
    assert _rows(return_database) == []


@pytest.mark.parametrize("creator_state", ["missing", "deleted", "pending", "rejected"])
def test_legacy_deleted_or_unapproved_registrar_does_not_block_valid_return(return_database, caplog, creator_state):
    pending = _pending(return_database)
    with return_database() as session:
        if creator_state == "missing":
            session.get(FinancePayment, pending["id"]).created_by_id = None
        elif creator_state == "deleted":
            session.delete(session.get(UserTable, REGISTRAR["user_id"]))
        else:
            session.get(UserTable, REGISTRAR["user_id"]).status = creator_state
        session.commit()
    returned = _return(pending)
    assert returned["status"] == "draft" and returned["review_remark"] == "请核对回单金额"
    assert _rows(return_database) == []
    assert "Skipping return notice" in caplog.text
    with return_database() as session:
        assert session.query(AuditLogTable).filter_by(action="return").count() == 1


def test_approved_registrar_receives_notice_after_role_change(return_database):
    pending = _pending(return_database)
    with return_database() as session:
        session.get(UserTable, REGISTRAR["user_id"]).roles = [session.query(RoleTable).filter_by(name="worker").one()]
        session.commit()
    _return(pending)
    notice, = _rows(return_database)
    assert notice.recipient_id == REGISTRAR["user_id"]


def test_vendor_return_does_not_generate_customer_receipts_link(return_database):
    pending = _pending(return_database, creator=SUBMITTER, partner_type="vendor")
    assert _return(pending)["status"] == "draft"
    assert _rows(return_database) == []


def test_finance_display_name_does_not_exceed_message_source_limit(return_database):
    pending = _pending(return_database)
    _return(pending, actor={**REVIEWER, "name": "财" * 128})
    notice, = _rows(return_database)
    assert notice.source_name.startswith("财务：") and len(notice.source_name) == 128
