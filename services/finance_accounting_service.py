"""Double-entry posting, period control and bank matching for finance v2.

Every hook accepts its caller's session. No hook commits, creates an independent
session or suppresses an audit failure. Closing and posting share a settings lock.
"""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from uuid import uuid4

from sqlalchemy import or_
from Auth import get_payload_roles
from data.database import SessionFactory
from data.finance.accounting import (
    FinanceSettings, FinanceGLAccount, FinancePeriod, FinanceJournalEntry,
    FinanceJournalLine, FinanceBankTransaction,
)
from utils.audit import record_audit

ZERO = Decimal("0.00")
CHART = [
    ("1001", "库存现金", "asset"), ("1002", "银行及其他资金", "asset"),
    ("1122", "应收账款", "asset"), ("1221", "其他应收款", "asset"),
    ("1601", "固定资产", "asset"), ("1602", "累计折旧", "asset"),
    ("2202", "应付账款", "liability"), ("2203", "待履约收入", "liability"),
    ("2211", "应付职工薪酬", "liability"), ("222101", "销项税额", "liability"),
    ("222102", "进项税额", "asset"), ("2241", "其他应付款", "liability"),
    ("4001", "实收资本", "equity"), ("4104", "未分配利润", "equity"),
    ("6001", "服务收入", "revenue"), ("6401", "服务成本", "expense"),
    ("6601", "销售费用", "expense"), ("6602", "管理费用", "expense"),
    ("6603", "财务费用", "expense"),
]
CONTROL = {"1122", "2202", "2203"}


class AccountingConflict(ValueError):
    status_code = 409


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _date(value, name="日期"):
    try:
        result = date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"{name}须为 YYYY-MM-DD")
    if str(value) != result.isoformat():
        raise ValueError(f"{name}须为 YYYY-MM-DD")
    return result.isoformat()


def _money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("金额必须为有效数字")
    if not result.is_finite() or abs(result) >= Decimal("10000000000000000"):
        raise ValueError("金额超出可用范围")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _text(value, name, limit=500, required=False):
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"请填写{name}")
    if len(result) > limit:
        raise ValueError(f"{name}不能超过{limit}字")
    return result


def _actor(actor):
    if not set(get_payload_roles(actor or {})) & {"admin", "finance"}:
        raise PermissionError("仅财务或管理员可操作")


def _version(row, body):
    if isinstance(body.get("version"), bool) or body.get("version") != row.version:
        raise AccountingConflict("记录已被更新，请刷新后重试")


@contextmanager
def _transaction(actor):
    _actor(actor)
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _audit(session, actor, target_type, row_id, action, before=None, after=None, reason=None):
    record_audit(event_type="finance_accounting", target_type=target_type,
                 target_id=row_id, action=action, before_data=before,
                 after_data=after, remark=reason, session=session,
                 operator_payload=actor)


def _settings(session, required=True):
    settings = session.query(FinanceSettings).filter_by(id=1).with_for_update().one_or_none()
    if settings is None and required:
        raise ValueError("请先在会计与月结中完成建账设置，并创建开放期间")
    return settings


def validate_accounting_date(session, accounting_date):
    """Serialize all financial effective dates against period closing."""
    value = _date(accounting_date)
    settings = _settings(session)
    if value < settings.opening_date:
        raise ValueError("日期不能早于建账日期")
    period = session.query(FinancePeriod).filter(
        FinancePeriod.date_from <= value, FinancePeriod.date_to >= value,
    ).with_for_update().one_or_none()
    if period is None:
        raise ValueError(f"{value} 没有开放会计期间，请先创建期间")
    if period.status != "open":
        raise ValueError(f"{period.name} 已关账，请在开放期间更正")
    return settings


def _settings_data(row):
    if row is None:
        return {"configured": False, "currency": "CNY"}
    return {"configured": True, **{k: getattr(row, k) for k in (
        "company_name", "currency", "revenue_policy", "opening_date", "opening_confirmed", "version")}}


def get_settings(actor):
    _actor(actor)
    with SessionFactory() as session:
        return _settings_data(session.get(FinanceSettings, 1))


def configure(body, actor):
    with _transaction(actor) as session:
        row = _settings(session, required=False)
        before = _settings_data(row)
        if row:
            _version(row, body)
        opening_date = _date(body.get("opening_date"), "建账日期")
        policy = body.get("revenue_policy", "deferred")
        if policy not in {"deferred", "invoice"}:
            raise ValueError("请选择账单确认收入或履约后确认收入")
        company = _text(body.get("company_name"), "公司名称", 200, True)
        if row and (opening_date != row.opening_date or policy != row.revenue_policy):
            if session.query(FinanceJournalEntry.id).filter(FinanceJournalEntry.status != "draft").first():
                raise ValueError("已有生效凭证，建账日期和收入政策不可直接修改")
        if row is None:
            row = FinanceSettings(id=1, company_name=company, opening_date=opening_date,
                                  revenue_policy=policy, opening_confirmed=False, version=1)
            session.add(row)
            for code, name, account_type in CHART:
                session.add(FinanceGLAccount(code=code, name=name, account_type=account_type, active=True, system=True))
        else:
            row.company_name, row.opening_date, row.revenue_policy = company, opening_date, policy
            row.version += 1
        session.flush()
        result = _settings_data(row)
        _audit(session, actor, "finance_settings", 1, "settings_configure", before, result)
        return result


def confirm_opening(body, actor):
    with _transaction(actor) as session:
        row = _settings(session)
        _version(row, body)
        reason = _text(body.get("reason"), "期初核对依据", required=True)
        if session.query(FinanceJournalEntry.id).filter_by(kind="opening", status="draft").first():
            raise ValueError("还有期初凭证草稿未过账")
        before = _settings_data(row)
        row.opening_confirmed = True
        row.version += 1
        result = _settings_data(row)
        _audit(session, actor, "finance_settings", 1, "opening_confirm", before, result, reason)
        return result


def list_accounts(actor):
    _actor(actor)
    with SessionFactory() as session:
        return [{k: getattr(row, k) for k in ("code", "name", "account_type", "active", "system")}
                for row in session.query(FinanceGLAccount).order_by(FinanceGLAccount.code).all()]


def create_account(body, actor):
    with _transaction(actor) as session:
        _settings(session)
        code = _text(body.get("code"), "科目代码", 20, True)
        if not code.isdigit():
            raise ValueError("科目代码只能包含数字")
        if session.get(FinanceGLAccount, code):
            raise AccountingConflict("科目代码已存在")
        kind = body.get("account_type")
        if kind not in {"asset", "liability", "equity", "revenue", "expense"}:
            raise ValueError("科目类别无效")
        row = FinanceGLAccount(code=code, name=_text(body.get("name"), "科目名称", 120, True),
                               account_type=kind, active=True, system=False)
        session.add(row)
        session.flush()
        result = {k: getattr(row, k) for k in ("code", "name", "account_type", "active", "system")}
        _audit(session, actor, "finance_gl_account", code, "account_create", after=result)
        return result


def _entry_data(row):
    return {**{k: getattr(row, k) for k in (
        "id", "number", "entry_date", "kind", "source_type", "source_id", "source_action",
        "description", "status", "version", "reversal_of_id", "cashflow_activity",
        "created_at", "created_by_name", "posted_at")},
        "total_debit": str(sum((line.debit for line in row.lines), ZERO)),
        "total_credit": str(sum((line.credit for line in row.lines), ZERO)),
        "lines": [{**{k: getattr(line, k) for k in (
            "id", "account_code", "account_name", "partner_type", "partner_id", "partner_name",
            "fund_account_id", "memo")}, "debit": str(line.debit), "credit": str(line.credit)} for line in row.lines]}


def _make_entry(session, actor, *, entry_date, kind, description, lines,
                source_type=None, source_id=None, source_action="post", posted=True,
                reversal_of_id=None, cashflow_activity="operating"):
    validate_accounting_date(session, entry_date)
    if source_type and source_id is not None:
        existing = session.query(FinanceJournalEntry).filter_by(
            source_type=source_type, source_id=str(source_id), source_action=source_action).one_or_none()
        if existing:
            return existing
    if cashflow_activity not in {"operating", "investing", "financing", "opening", "transfer"}:
        raise ValueError("现金流类别无效")
    debit = sum((_money(line.get("debit", 0)) for line in lines), ZERO)
    credit = sum((_money(line.get("credit", 0)) for line in lines), ZERO)
    if len(lines) < 2 or debit <= 0 or debit != credit:
        raise ValueError(f"凭证借贷必须平衡且大于零（借 {debit} / 贷 {credit}）")
    row = FinanceJournalEntry(number=f"JV-{entry_date.replace('-', '')}-{uuid4().hex[:10].upper()}",
        entry_date=entry_date, kind=kind, source_type=source_type,
        source_id=str(source_id) if source_id is not None else None, source_action=source_action,
        description=description, status="posted" if posted else "draft", version=1,
        created_at=_now(), created_by_id=actor.get("user_id"),
        created_by_name=actor.get("name") or actor.get("user_name") or "财务人员",
        posted_at=_now() if posted else None, reversal_of_id=reversal_of_id,
        cashflow_activity=cashflow_activity)
    for line in lines:
        dr, cr = _money(line.get("debit", 0)), _money(line.get("credit", 0))
        if dr < 0 or cr < 0 or (dr > 0 and cr > 0) or (dr == 0 and cr == 0):
            raise ValueError("每行只能有一个正的借方或贷方金额")
        account = session.get(FinanceGLAccount, str(line.get("account_code", "")))
        if not account or not account.active:
            raise ValueError(f"科目不存在或已停用：{line.get('account_code')}")
        row.lines.append(FinanceJournalLine(account_code=account.code, account_name=account.name,
            debit=dr, credit=cr, partner_type=line.get("partner_type"),
            partner_id=line.get("partner_id"), partner_name=line.get("partner_name"),
            fund_account_id=line.get("fund_account_id"), memo=line.get("memo")))
    session.add(row)
    session.flush()
    _audit(session, actor, "finance_journal_entry", row.id,
           "journal_post" if posted else "journal_create", after=_entry_data(row))
    return row


def post_document(session, document, actor):
    settings = validate_accounting_date(session, document.document_date)
    customer = document.document_type.startswith("customer")
    is_credit = document.document_type.endswith("credit")
    net = _money(document.subtotal)
    tax = _money(document.tax_amount)
    total = _money(document.total_amount)
    from data.finance.ledger import FinanceDocument
    original = session.get(FinanceDocument, document.original_document_id) if is_credit else None
    opening = bool(getattr(document, "is_opening", False) or (original and getattr(original, "is_opening", False)))
    revenue_code = "2203" if settings.revenue_policy == "deferred" else "6001"
    partner = dict(partner_type=document.partner_type, partner_id=document.partner_id,
                   partner_name=document.partner_name)
    lines = [{"account_code": "1122" if customer else "2202",
              "debit": total if customer else 0, "credit": 0 if customer else total, **partner}]
    if opening:
        lines.append({"account_code": "4104", "debit": 0 if customer else total,
                      "credit": total if customer else 0})
    elif is_credit and customer and settings.revenue_policy == "deferred":
        from services.finance_revenue_service import credit_revenue_split
        deferred, _ = credit_revenue_split(session, original, net, document.document_date)
        if deferred:
            lines.append({"account_code": "2203", "debit": 0, "credit": deferred})
        if net > deferred:
            lines.append({"account_code": "6001", "debit": 0, "credit": net-deferred})
    elif net:
        lines.append({"account_code": revenue_code if customer else "6401",
                      "debit": 0 if customer else net, "credit": net if customer else 0})
    if tax and not opening:
        lines.append({"account_code": "222101" if customer else "222102",
                      "debit": 0 if customer else tax, "credit": tax if customer else 0})
    if is_credit:
        lines = [{**line, "debit": line.get("credit", 0), "credit": line.get("debit", 0)} for line in lines]
    return _make_entry(session, actor, entry_date=document.document_date, kind="document",
                       description=f"{document.number} · {document.partner_name}", lines=lines,
                       source_type="finance_document", source_id=document.id)


def post_payment(session, payment, actor):
    from data.finance.ledger import FinanceAccount
    account = session.get(FinanceAccount, payment.account_id)
    incoming = payment.direction == "incoming"
    amount = _money(payment.amount)
    opening = bool(getattr(payment, "is_opening", False))
    fund_code = "4104" if opening else ("1001" if account.account_type == "cash" else "1002")
    lines = [
        dict(account_code=fund_code, debit=amount if incoming else 0,
             credit=0 if incoming else amount, fund_account_id=None if opening else account.id),
        dict(account_code="1122" if payment.partner_type == "customer" else "2202",
             debit=0 if incoming else amount, credit=amount if incoming else 0,
             partner_type=payment.partner_type, partner_id=payment.partner_id, partner_name=payment.partner_name),
    ]
    return _make_entry(session, actor, entry_date=payment.payment_date, kind="payment",
                       description=f"{payment.number} · {payment.partner_name}", lines=lines,
                       source_type="finance_payment", source_id=payment.id)


def _reverse_entry(session, entry, actor, reversal_date, reason):
    validate_accounting_date(session, reversal_date)
    if entry.status != "posted":
        raise ValueError("只有已过账且未冲销的凭证可以冲销")
    if reversal_date < entry.entry_date:
        raise ValueError("冲销日期不能早于原凭证日期")
    result = _make_entry(session, actor, entry_date=reversal_date, kind="reversal", description=reason,
        source_type="finance_journal_entry", source_id=entry.id, source_action="reverse",
        reversal_of_id=entry.id, cashflow_activity=entry.cashflow_activity,
        lines=[{**line, "debit": line["credit"], "credit": line["debit"]} for line in _entry_data(entry)["lines"]])
    before = _entry_data(entry)
    entry.status = "reversed"
    entry.version += 1
    _audit(session, actor, "finance_journal_entry", entry.id, "journal_reverse", before, _entry_data(entry), reason)
    return result


def reverse_payment(session, payment, actor, reversal_date, reason):
    if session.query(FinanceBankTransaction.id).filter_by(payment_id=payment.id, status="matched").first():
        raise ValueError("收付款已经银行对账，请先撤销匹配并核实实际资金")
    entry = session.query(FinanceJournalEntry).filter_by(source_type="finance_payment", source_id=str(payment.id), source_action="post").one()
    return _reverse_entry(session, entry, actor, reversal_date, reason)


def list_entries(actor, **filters):
    _actor(actor)
    with SessionFactory() as session:
        query = session.query(FinanceJournalEntry)
        for name in ("status", "kind", "source_type", "source_id"):
            if filters.get(name):
                query = query.filter(getattr(FinanceJournalEntry, name) == str(filters[name]))
        if filters.get("date_from"):
            query = query.filter(FinanceJournalEntry.entry_date >= _date(filters["date_from"]))
        if filters.get("date_to"):
            query = query.filter(FinanceJournalEntry.entry_date <= _date(filters["date_to"]))
        if filters.get("q"):
            query = query.filter(or_(FinanceJournalEntry.number.contains(filters["q"]), FinanceJournalEntry.description.contains(filters["q"])))
        page, size = max(int(filters.get("p") or 1), 1), min(max(int(filters.get("s") or 20), 1), 200)
        return dict(items=[_entry_data(row) for row in query.order_by(FinanceJournalEntry.entry_date.desc(), FinanceJournalEntry.id.desc()).offset((page-1)*size).limit(size)],
                    total=query.count(), page=page, page_size=size)


def get_entry(entry_id, actor):
    _actor(actor)
    with SessionFactory() as session:
        row = session.get(FinanceJournalEntry, entry_id)
        if not row:
            raise LookupError("凭证不存在")
        return _entry_data(row)


def create_manual_entry(body, actor):
    from data.finance.ledger import FinanceAccount
    from services.finance_ledger_service import _run
    def change(session):
        settings = _settings(session)
        kind = body.get("kind", "manual")
        if kind not in {"manual", "opening"}:
            raise ValueError("只允许录入普通或期初凭证")
        day = _date(body.get("entry_date"))
        if kind == "opening" and (settings.opening_confirmed or day != settings.opening_date):
            raise ValueError("期初凭证须在建账日录入，且期初尚未确认")
        lines = body.get("lines")
        if not isinstance(lines, list) or len(lines) > 200:
            raise ValueError("凭证明细须为不超过200行的列表")
        normalized = []
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("凭证明细格式无效")
            code = str(line.get("account_code", ""))
            if code in CONTROL:
                raise ValueError("应收应付及待履约科目由账单、收付款和收入确认生成，请通过对应业务录入")
            fund_id = line.get("fund_account_id")
            if code in {"1001", "1002"}:
                fund = session.get(FinanceAccount, fund_id) if isinstance(fund_id, int) else None
                if not fund or not fund.active:
                    raise ValueError("现金/银行科目须关联有效资金账户")
                if code != ("1001" if fund.account_type == "cash" else "1002"):
                    raise ValueError("科目与资金账户类型不符")
            elif fund_id:
                raise ValueError("只有现金/银行科目允许关联资金账户")
            normalized.append(dict(account_code=code, debit=line.get("debit", 0), credit=line.get("credit", 0),
                fund_account_id=fund_id, memo=_text(line.get("memo"), "摘要")))
        row = _make_entry(session, actor, entry_date=day, kind=kind,
            description=_text(body.get("description"), "凭证摘要", required=True), lines=normalized,
            posted=False, cashflow_activity="opening" if kind == "opening" else body.get("cashflow_activity", "operating"))
        return _entry_data(row)
    return _run(actor, "accounting.entries.create", body, change)


def entry_action(entry_id, action, body, actor):
    with _transaction(actor) as session:
        _settings(session)
        row = session.query(FinanceJournalEntry).filter_by(id=entry_id).with_for_update().one_or_none()
        if not row:
            raise LookupError("凭证不存在")
        _version(row, body)
        if row.source_type:
            raise ValueError("业务凭证请通过来源账单或收付款更正")
        if action == "reverse":
            result = _reverse_entry(session, row, actor, _date(body.get("entry_date")),
                                    _text(body.get("reason"), "冲销原因", required=True))
            return _entry_data(result)
        before = _entry_data(row)
        if row.status != "draft":
            raise ValueError("只有草稿凭证可以过账或作废")
        if action == "post":
            settings = validate_accounting_date(session, row.entry_date)
            if row.kind == "opening" and settings.opening_confirmed:
                raise ValueError("期初已确认，不能再补录期初凭证")
            row.status, row.posted_at = "posted", _now()
        elif action == "cancel":
            _text(body.get("reason"), "作废原因", required=True)
            row.status = "cancelled"
        else:
            raise ValueError("操作无效")
        row.version += 1
        result = _entry_data(row)
        _audit(session, actor, "finance_journal_entry", row.id, f"journal_{action}", before, result, body.get("reason"))
        return result


def _period_data(row):
    return {k: getattr(row, k) for k in ("id", "name", "date_from", "date_to", "status", "version", "closed_at", "closed_by", "remark")}


def list_periods(actor):
    _actor(actor)
    with SessionFactory() as session:
        return [_period_data(row) for row in session.query(FinancePeriod).order_by(FinancePeriod.date_from.desc())]


def create_period(body, actor):
    with _transaction(actor) as session:
        settings = _settings(session)
        start, end = _date(body.get("date_from")), _date(body.get("date_to"))
        if start > end or start < settings.opening_date:
            raise ValueError("期间范围无效或早于建账日")
        if session.query(FinancePeriod.id).filter(FinancePeriod.date_from <= end, FinancePeriod.date_to >= start).first():
            raise ValueError("会计期间不能重叠")
        row = FinancePeriod(name=_text(body.get("name"), "期间名称", 40, True), date_from=start, date_to=end, status="open", version=1)
        session.add(row)
        session.flush()
        result = _period_data(row)
        _audit(session, actor, "finance_period", row.id, "period_create", after=result)
        return result


def _closing_checks(session, period):
    from data.finance.ledger import FinanceDocument, FinancePayment
    from services.finance_legacy_service import reconciliation_count
    settings = _settings(session)
    checks = []
    def check(key, label, count):
        checks.append(dict(key=key, label=label, count=count, passed=count == 0))
    check("opening", "期初余额已核对确认", 0 if settings.opening_confirmed else 1)
    for model, field, name, label in (
        (FinanceDocument, FinanceDocument.document_date, "documents", "期间账单草稿已处理"),
        (FinancePayment, FinancePayment.payment_date, "payments", "期间收付款草稿及待财务确认已处理"),
        (FinanceJournalEntry, FinanceJournalEntry.entry_date, "entries", "期间凭证草稿已处理"),
    ):
        pending_statuses = ("draft", "pending") if model is FinancePayment else ("draft",)
        query = session.query(model.id).filter(field >= period.date_from, field <= period.date_to)
        check(name, label, query.filter(model.status.in_(pending_statuses)).count())
        if model is FinancePayment:
            checks[-1]["draft_count"] = query.filter(model.status == "draft").count()
            checks[-1]["pending_count"] = query.filter(model.status == "pending").count()
    check("bank", "期间银行流水已匹配", session.query(FinanceBankTransaction.id).filter(
        FinanceBankTransaction.transaction_date >= period.date_from,
        FinanceBankTransaction.transaction_date <= period.date_to,
        FinanceBankTransaction.status == "unmatched").count())
    rows = session.query(FinanceJournalEntry).filter(FinanceJournalEntry.entry_date <= period.date_to,
        FinanceJournalEntry.status.in_(["posted", "reversed"])).all()
    unbalanced = sum(1 for row in rows if sum((line.debit-line.credit for line in row.lines), ZERO) != ZERO)
    check("balanced", "全部生效凭证借贷平衡", unbalanced)
    check("prior", "更早期间已关闭", session.query(FinancePeriod.id).filter(
        FinancePeriod.date_to < period.date_from, FinancePeriod.status == "open").count())
    check("legacy", "已接入订单与旧系统变动已核对", reconciliation_count(session, period.date_to))
    from services.finance_order_service import reconciliation_count as order_reconciliation_count
    check("orders", "已管理订单的应收变化已核对", order_reconciliation_count(session, period.date_to))
    return {"period": _period_data(period), "checks": checks, "can_close": all(item["passed"] for item in checks)}


def closing_checks(period_id, actor):
    _actor(actor)
    with SessionFactory() as session:
        period = session.get(FinancePeriod, period_id)
        if not period:
            raise LookupError("期间不存在")
        return _closing_checks(session, period)


def period_action(period_id, action, body, actor):
    with _transaction(actor) as session:
        _settings(session)
        row = session.query(FinancePeriod).filter_by(id=period_id).with_for_update().one_or_none()
        if not row:
            raise LookupError("期间不存在")
        _version(row, body)
        reason = _text(body.get("reason"), "操作依据", required=True)
        before = _period_data(row)
        if action == "close" and row.status == "open":
            checks = _closing_checks(session, row)
            if not checks["can_close"]:
                raise ValueError("关账检查未通过：" + "、".join(item["label"] for item in checks["checks"] if not item["passed"]))
            row.status, row.closed_at, row.closed_by = "closed", _now(), actor.get("name") or actor.get("user_name")
        elif action == "reopen" and row.status == "closed":
            if "admin" not in get_payload_roles(actor):
                raise PermissionError("只有管理员可以重开期间")
            if session.query(FinancePeriod.id).filter(FinancePeriod.date_from > row.date_to, FinancePeriod.status == "closed").first():
                raise ValueError("请先按倒序重开更晚的已关账期间")
            row.status, row.closed_at, row.closed_by = "open", None, None
        else:
            raise ValueError("期间当前状态不支持此操作")
        row.remark, row.version = reason, row.version + 1
        result = _period_data(row)
        _audit(session, actor, "finance_period", row.id, f"period_{action}", before, result, reason)
        return result


def financial_report(actor, date_from=None, date_to=None, account_code=None):
    _actor(actor)
    end = _date(date_to or date.today().isoformat())
    with SessionFactory() as session:
        settings = session.get(FinanceSettings, 1)
        start = _date(date_from or (settings.opening_date if settings else end[:4]+"-01-01"))
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        accounts = {row.code: row for row in session.query(FinanceGLAccount).all()}
        amounts = {code: dict(opening=ZERO, debit=ZERO, credit=ZERO, closing=ZERO) for code in accounts}
        ledger, cashflows = [], {key: ZERO for key in ("operating", "investing", "financing", "opening", "transfer")}
        funds = {}
        entries = session.query(FinanceJournalEntry).filter(
            FinanceJournalEntry.status.in_(["posted", "reversed"]), FinanceJournalEntry.entry_date <= end,
        ).order_by(FinanceJournalEntry.entry_date, FinanceJournalEntry.id).all()
        for entry in entries:
            for line in entry.lines:
                amount = line.debit-line.credit
                bucket = amounts[line.account_code]
                bucket["closing"] += amount
                if entry.entry_date < start:
                    bucket["opening"] += amount
                else:
                    bucket["debit"] += line.debit
                    bucket["credit"] += line.credit
                    if not account_code or account_code == line.account_code:
                        ledger.append(dict(line_id=line.id, entry_id=entry.id, entry_number=entry.number, entry_date=entry.entry_date,
                            account_code=line.account_code, account_name=line.account_name,
                            description=entry.description, debit=str(line.debit), credit=str(line.credit),
                            partner_name=line.partner_name, source_type=entry.source_type, source_id=entry.source_id))
                if line.fund_account_id:
                    fund = funds.setdefault(line.fund_account_id, dict(opening=ZERO, inflow=ZERO, outflow=ZERO, closing=ZERO))
                    fund["closing"] += amount
                    if entry.entry_date < start:
                        fund["opening"] += amount
                    else:
                        fund["inflow"] += line.debit
                        fund["outflow"] += line.credit
                        cashflows[entry.cashflow_activity] += amount
        trial = [{"code": code, "name": account.name, "account_type": account.account_type,
                  **{k: str(v) for k, v in amounts[code].items()}} for code, account in sorted(accounts.items())]
        pnl = [{**row, "amount": str((Decimal(row["credit"])-Decimal(row["debit"])) if row["account_type"] == "revenue"
                                      else (Decimal(row["debit"])-Decimal(row["credit"])))}
               for row in trial if row["account_type"] in {"revenue", "expense"}]
        revenue = sum((Decimal(row["amount"]) for row in pnl if row["account_type"] == "revenue"), ZERO)
        expense = sum((Decimal(row["amount"]) for row in pnl if row["account_type"] == "expense"), ZERO)
        assets = sum((Decimal(row["closing"]) for row in trial if row["account_type"] == "asset"), ZERO)
        liabilities = -sum((Decimal(row["closing"]) for row in trial if row["account_type"] == "liability"), ZERO)
        equity = -sum((Decimal(row["closing"]) for row in trial if row["account_type"] == "equity"), ZERO)
        cumulative_profit = -sum((Decimal(row["closing"]) for row in trial if row["account_type"] in {"revenue", "expense"}), ZERO)
        return dict(date_from=start, date_to=end, currency="CNY", opening_confirmed=bool(settings and settings.opening_confirmed),
            trial_balance=trial, ledger=ledger, profit_loss=dict(items=pnl, revenue=str(revenue), expense=str(expense), profit=str(revenue-expense)),
            balance_sheet=dict(assets=str(assets), liabilities=str(liabilities), equity=str(equity), unclosed_profit=str(cumulative_profit),
                               difference=str(assets-liabilities-equity-cumulative_profit), items=trial),
            funds=[dict(account_id=k, **{key: str(val) for key, val in v.items()}) for k, v in funds.items()],
            cashflow={key: str(value) for key, value in cashflows.items()},
            total_debit=str(sum((Decimal(row["debit"]) for row in trial), ZERO)),
            total_credit=str(sum((Decimal(row["credit"]) for row in trial), ZERO)),
            notice="报表仅包含本账簿已过账凭证；期初、税务和会计政策需经财务核对。资金流按凭证类别归集。")


def _bank_data(row):
    return {**{k: getattr(row, k) for k in ("id", "account_id", "transaction_date", "reference", "description", "status", "payment_id", "version", "created_at", "matched_at")}, "amount": str(row.amount)}


def list_bank_transactions(actor, **filters):
    _actor(actor)
    with SessionFactory() as session:
        query = session.query(FinanceBankTransaction)
        if filters.get("account_id"):
            query = query.filter_by(account_id=int(filters["account_id"]))
        if filters.get("status"):
            query = query.filter_by(status=filters["status"])
        page, size = max(int(filters.get("p") or 1), 1), min(max(int(filters.get("s") or 20), 1), 200)
        return dict(items=[_bank_data(row) for row in query.order_by(FinanceBankTransaction.transaction_date.desc(), FinanceBankTransaction.id.desc()).offset((page-1)*size).limit(size)],
                    total=query.count(), page=page, page_size=size)


def import_bank_transactions(body, actor, preview=False):
    from data.finance.ledger import FinanceAccount
    with _transaction(actor) as session:
        _settings(session)
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > 1000:
            raise ValueError("请提供1至1000行银行流水")
        account = session.get(FinanceAccount, body.get("account_id"))
        if not account or not account.active:
            raise ValueError("请选择有效资金账户")
        items, seen = [], {}
        for index, item in enumerate(rows, 1):
            if not isinstance(item, dict):
                raise ValueError(f"第{index}行格式无效")
            day = _date(item.get("transaction_date"))
            validate_accounting_date(session, day)
            amount = _money(item.get("amount"))
            if amount == 0:
                raise ValueError(f"第{index}行金额不能为零")
            ref = _text(item.get("reference"), f"第{index}行银行流水号", 200, True)
            fingerprint = hashlib.sha256(f"{account.id}|{ref}".encode()).hexdigest()
            existing = session.query(FinanceBankTransaction).filter_by(fingerprint=fingerprint).one_or_none()
            if existing and (existing.amount != amount or existing.transaction_date != day):
                raise AccountingConflict(f"第{index}行流水号已存在，但日期或金额不同")
            if fingerprint in seen and seen[fingerprint] != (day, amount):
                raise AccountingConflict(f"第{index}行与文件中同流水号的日期或金额不一致")
            duplicate = bool(existing or fingerprint in seen)
            seen[fingerprint] = (day, amount)
            row = dict(account_id=account.id, transaction_date=day, amount=amount, reference=ref,
                       description=_text(item.get("description"), "流水说明"), fingerprint=fingerprint)
            items.append(dict(row=index, reference=ref, transaction_date=day, amount=str(amount), duplicate=duplicate))
            if not preview and not duplicate:
                record = FinanceBankTransaction(**row, status="unmatched", version=1, created_at=_now())
                session.add(record)
                session.flush()
                _audit(session, actor, "finance_bank_transaction", record.id, "bank_import", after=_bank_data(record))
        return dict(preview=preview, items=items, imported=0 if preview else sum(not item["duplicate"] for item in items), duplicates=sum(item["duplicate"] for item in items))


def bank_action(transaction_id, action, body, actor):
    from data.finance.ledger import FinancePayment
    with _transaction(actor) as session:
        _settings(session)
        row = session.query(FinanceBankTransaction).filter_by(id=transaction_id).with_for_update().one_or_none()
        if not row:
            raise LookupError("银行流水不存在")
        _version(row, body)
        validate_accounting_date(session, row.transaction_date)
        before = _bank_data(row)
        if action == "match" and row.status == "unmatched":
            payment = session.query(FinancePayment).filter_by(id=body.get("payment_id")).with_for_update().one_or_none()
            if not payment or payment.status != "posted" or payment.account_id != row.account_id:
                raise ValueError("请选择同一账户下已生效的收付款")
            if getattr(payment, "is_opening", False):
                raise ValueError("期初预收预付不代表本期资金流水，不能进行银行匹配")
            signed = payment.amount if payment.direction == "incoming" else -payment.amount
            if signed != row.amount:
                raise ValueError("收付款方向和金额必须与银行流水一致")
            if session.query(FinanceBankTransaction.id).filter_by(payment_id=payment.id).first():
                raise AccountingConflict("该收付款已匹配其他银行流水")
            row.payment_id, row.status, row.matched_at = payment.id, "matched", _now()
        elif action == "unmatch" and row.status == "matched":
            _text(body.get("reason"), "撤销匹配原因", required=True)
            row.payment_id, row.status, row.matched_at = None, "unmatched", None
        else:
            raise ValueError("当前流水状态不支持此操作")
        row.version += 1
        result = _bank_data(row)
        _audit(session, actor, "finance_bank_transaction", row.id, f"bank_{action}", before, result, body.get("reason"))
        return result


def partner_statement(actor, partner_type, partner_id, date_from, date_to):
    """A reconciliable counterparty ledger, including opening and unapplied cash."""
    from services.finance_ledger_service import _partner, _id
    _actor(actor)
    if partner_type not in {"customer", "vendor"}:
        raise ValueError("请选择客户或供应商")
    partner_id = _id(partner_id, "往来单位")
    start, end = _date(date_from), _date(date_to)
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    with SessionFactory() as session:
        partner = _partner(session, partner_type, partner_id)
        settings = session.get(FinanceSettings, 1)
        rows = session.query(FinanceJournalEntry, FinanceJournalLine).join(
            FinanceJournalLine, FinanceJournalLine.entry_id == FinanceJournalEntry.id).filter(
                FinanceJournalEntry.status.in_(["posted", "reversed"]),
                FinanceJournalEntry.entry_date <= end,
                FinanceJournalLine.account_code == ("1122" if partner_type == "customer" else "2202"),
                FinanceJournalLine.partner_type == partner_type,
                FinanceJournalLine.partner_id == partner_id,
            ).order_by(FinanceJournalEntry.entry_date, FinanceJournalEntry.id, FinanceJournalLine.id).all()
        opening, balance, increase, decrease = ZERO, ZERO, ZERO, ZERO
        items = []
        for entry, line in rows:
            up = line.debit if partner_type == "customer" else line.credit
            down = line.credit if partner_type == "customer" else line.debit
            balance += up-down
            if entry.entry_date < start:
                opening += up-down
                continue
            increase, decrease = increase+up, decrease+down
            items.append(dict(entry_id=entry.id, entry_number=entry.number, entry_date=entry.entry_date,
                description=entry.description, source_type=entry.source_type, source_id=entry.source_id,
                increase=str(up), decrease=str(down), balance=str(balance)))
        return dict(company_name=settings.company_name if settings else "", partner_type=partner_type,
            partner_id=partner_id, partner_name=partner.name, currency="CNY", date_from=start, date_to=end,
            opening_balance=str(opening), closing_balance=str(balance), total_increase=str(increase), total_decrease=str(decrease),
            items=items, opening_confirmed=bool(settings and settings.opening_confirmed))
