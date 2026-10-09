"""Invoice-linked revenue recognition, with immutable postings and reversals."""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import and_, or_
from data.finance.accounting import FinanceJournalEntry, FinanceSettings
from data.finance.ledger import FinanceDocument
from services import finance_accounting_service as accounting
from services import finance_ledger_service as ledger
from utils.audit import record_audit

ZERO = Decimal("0.00")


def _related_entries(session, invoice):
    document_ids = [str(row[0]) for row in session.query(FinanceDocument.id).filter(
        or_(FinanceDocument.id == invoice.id, FinanceDocument.original_document_id == invoice.id)).all()]
    entries = session.query(FinanceJournalEntry).filter(
        FinanceJournalEntry.status.in_(["posted", "reversed"]),
        or_(and_(FinanceJournalEntry.source_type == "finance_document", FinanceJournalEntry.source_id.in_(document_ids)),
            and_(FinanceJournalEntry.source_type == "finance_revenue", FinanceJournalEntry.source_id == str(invoice.id))),
    ).all()
    if entries:
        entries += session.query(FinanceJournalEntry).filter(
            FinanceJournalEntry.status.in_(["posted", "reversed"]),
            FinanceJournalEntry.reversal_of_id.in_([entry.id for entry in entries]),
        ).all()
    return entries


def _balance(entries, code, as_of=None):
    return sum((line.credit - line.debit for entry in entries
                if as_of is None or entry.entry_date <= as_of
                for line in entry.lines if line.account_code == code), ZERO)


def deferred_balance(session, invoice, as_of=None):
    """Net credit in 2203 for the invoice, its credits and revenue reversals."""
    return _balance(_related_entries(session, invoice), "2203", as_of)


def recognized_balance(session, invoice, as_of=None):
    """Net recognized service revenue, after credit notes and reversals."""
    return _balance(_related_entries(session, invoice), "6001", as_of)


def credit_revenue_split(session, invoice, amount, credit_date):
    """Split a credit without making any historical deferred/income balance negative."""
    entries = _related_entries(session, invoice)
    checkpoints = {credit_date} | {row.entry_date for row in entries if row.entry_date >= credit_date}
    deferred = min(amount, max(min(_balance(entries, "2203", point) for point in checkpoints), ZERO))
    recognized = amount - deferred
    available = min(_balance(entries, "6001", point) for point in checkpoints)
    if recognized > max(available, ZERO):
        raise ValueError("该贷项日期会使历史待履约余额或已确认收入为负，请选择相关收入确认之后的日期，或先更正收入确认")
    return deferred, recognized


def _invoice_data(session, invoice, *, include_entries=False):
    entries = _related_entries(session, invoice)
    result = {key: getattr(invoice, key) for key in (
        "id", "number", "partner_id", "partner_name", "document_date", "version", "status")}
    result.update(subtotal=str(invoice.subtotal), deferred_amount=str(_balance(entries, "2203")),
                  recognized_amount=str(_balance(entries, "6001")), currency="CNY")
    if include_entries:
        recognitions = [entry for entry in entries if entry.source_type == "finance_revenue"]
        result["entries"] = [{**accounting._entry_data(entry),
                              "recognized_amount": str(sum((line.credit for line in entry.lines if line.account_code == "6001"), ZERO))}
                             for entry in sorted(recognitions, key=lambda row: (row.entry_date, row.id), reverse=True)]
    return result


def _invoice(session, invoice_id, locked=False):
    invoice = ledger._lock_financial_row(session, FinanceDocument, invoice_id) if locked else ledger._row(session, FinanceDocument, invoice_id)
    if invoice.document_type != "customer_invoice" or invoice.status != "posted":
        raise ValueError("收入确认只能关联已生效的客户账单")
    return invoice


def get_invoice(invoice_id, actor):
    ledger._actor(actor)
    with ledger.SessionFactory() as session:
        return _invoice_data(session, _invoice(session, invoice_id), include_entries=True)


def list_invoices(actor, *, page=1, page_size=20, query_text="", open_only=True):
    ledger._actor(actor)
    with ledger.SessionFactory() as session:
        settings = session.get(FinanceSettings, 1)
        query = session.query(FinanceDocument).filter_by(document_type="customer_invoice", status="posted")
        if query_text:
            query = query.filter(or_(FinanceDocument.number.contains(query_text, autoescape=True),
                                     FinanceDocument.partner_name.contains(query_text, autoescape=True)))
        items = [_invoice_data(session, row) for row in query.order_by(FinanceDocument.document_date, FinanceDocument.id).all()]
        if open_only:
            items = [row for row in items if Decimal(row["deferred_amount"]) > ZERO]
        return {**ledger._page(items, page, page_size),
                "revenue_policy": settings.revenue_policy if settings else None,
                "notice": "按履约依据确认未税服务收入，收款本身不构成收入确认。"}


def recognize(invoice_id, body, actor):
    ledger._actor(actor)
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为对象")
    ledger._text(body.get("idempotency_key"), "幂等键", 128, required=True)
    def change(session):
        invoice = _invoice(session, invoice_id, locked=True)
        ledger._version(invoice, body)
        day = accounting._date(body.get("recognition_date"), "履约日期")
        if day < invoice.document_date:
            raise ValueError("履约日期不能早于账单日期")
        settings = accounting.validate_accounting_date(session, day)
        if settings.revenue_policy != "deferred":
            raise ValueError("当前账簿按账单确认收入，无需重复确认履约收入")
        amount = ledger._decimal(body.get("amount"), "确认收入", positive=True)
        reason = ledger._text(body.get("reason"), "履约依据", 2000, required=True)
        entries = _related_entries(session, invoice)
        checkpoints = {day} | {entry.entry_date for entry in entries if entry.entry_date >= day}
        if amount > _balance(entries, "2203") or any(amount > _balance(entries, "2203", point) for point in checkpoints):
            raise ValueError("确认金额超过该日期或后续日期的待履约余额，请核对贷项及已确认收入")
        before = _invoice_data(session, invoice)
        entry = accounting._make_entry(session, actor, entry_date=day, kind="revenue",
            description=f"{invoice.number} 履约收入：{reason}",
            source_type="finance_revenue", source_id=invoice.id, source_action=f"recognize-{uuid4().hex[:10]}",
            lines=[{"account_code": "2203", "debit": amount, "credit": ZERO},
                   {"account_code": "6001", "debit": ZERO, "credit": amount}],
            cashflow_activity="operating")
        ledger._touch(invoice)
        session.flush()
        result = _invoice_data(session, invoice, include_entries=True)
        record_audit("finance_document", "finance_document", invoice.id, action="revenue_recognize",
                     before_data=before, after_data=_invoice_data(session, invoice), remark=reason,
                     session=session, operator_payload=actor, metadata={"journal_entry_id": entry.id, "document_no": invoice.number})
        return {"invoice": result, "entry": accounting._entry_data(entry)}
    return ledger._run(actor, f"revenue.{invoice_id}.recognize", body, change)


def reverse(entry_id, body, actor):
    ledger._actor(actor)
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为对象")
    ledger._text(body.get("idempotency_key"), "幂等键", 128, required=True)
    def change(session):
        initial = ledger._row(session, FinanceJournalEntry, entry_id)
        if initial.kind != "revenue" or initial.source_type != "finance_revenue":
            raise ValueError("仅可撤销由履约确认生成的收入凭证")
        invoice = _invoice(session, int(initial.source_id), locked=True)
        entry = ledger._row(session, FinanceJournalEntry, entry_id, locked=True)
        ledger._version(entry, body)
        if entry.status != "posted":
            raise ledger.FinanceConflictError("该收入确认已经撤销")
        day = accounting._date(body.get("reversal_date"), "撤销日期")
        if day < entry.entry_date:
            raise ValueError("撤销日期不能早于收入确认日期")
        reason = ledger._text(body.get("reason"), "撤销依据", 2000, required=True)
        accounting.validate_accounting_date(session, day)
        entries = _related_entries(session, invoice)
        amount = sum((line.credit for line in entry.lines if line.account_code == "6001"), ZERO)
        checkpoints = {day} | {row.entry_date for row in entries if row.entry_date >= day}
        if amount > _balance(entries, "6001") or any(amount > _balance(entries, "6001", point) for point in checkpoints):
            raise ValueError("该收入已被后续贷项冲减，撤销会造成负收入；请先核对并更正关联贷项")
        before = _invoice_data(session, invoice)
        reversal = accounting._reverse_entry(session, entry, actor, day, reason)
        ledger._touch(invoice)
        session.flush()
        result = _invoice_data(session, invoice, include_entries=True)
        record_audit("finance_document", "finance_document", invoice.id, action="revenue_reverse",
                     before_data=before, after_data=_invoice_data(session, invoice), remark=reason,
                     session=session, operator_payload=actor,
                     metadata={"journal_entry_id": reversal.id, "reversal_of_id": entry.id, "document_no": invoice.number})
        return {"invoice": result, "entry": accounting._entry_data(reversal)}
    return ledger._run(actor, f"revenue.entry.{entry_id}.reverse", body, change)
