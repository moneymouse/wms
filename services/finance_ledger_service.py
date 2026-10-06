"""Transactional customer/vendor settlement, independent of operational orders.

Amounts are Decimal throughout. A partner row serializes competing allocations;
all successful changes and audit events commit in one transaction. Accounting
hooks use that same session, so closed periods and failed posting roll back all.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import uuid

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from Auth import get_payload_roles
from data.database import SessionFactory
from data.customer.Customer import CustomerTable
from data.finance.ledger import (FinanceAccount, FinanceAllocation, FinanceDocument,
    FinanceDocumentLine, FinanceIdempotency, FinancePayment, FinanceVendor)
from data.finance.order_settlement import FinanceOrderDocument
from utils.audit import record_audit


MONEY = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO = Decimal("0.00")
DOCUMENT_TYPES = {
    "customer_invoice": "customer", "customer_credit": "customer",
    "vendor_bill": "vendor", "vendor_credit": "vendor",
}
CREDIT_FOR = {"customer_invoice": "customer_credit", "vendor_bill": "vendor_credit"}
PREFIX = {"customer_invoice": "INV", "customer_credit": "CN", "vendor_bill": "BILL", "vendor_credit": "VCN"}


class FinanceConflictError(ValueError):
    pass


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _today():
    return date.today().isoformat()


def _text(value, field, maximum=512, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为文字")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(f"{field} 不能为空且不得超过 {maximum} 字" if required else f"{field} 不得超过 {maximum} 字")
    return value


def _decimal(value, field="金额", precision=MONEY, positive=False, maximum=Decimal("999999999999.99")):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} 格式不正确")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > maximum:
            raise ValueError(f"{field} 超出允许范围")
        result = result.quantize(precision, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{field} 格式不正确") from exc
    if result < 0 or (positive and result <= 0):
        raise ValueError(f"{field} 必须大于 0" if positive else f"{field} 不能为负数")
    return result


def _money(value):
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _str(value, precision=MONEY):
    return format(Decimal(str(value or 0)).quantize(precision, rounding=ROUND_HALF_UP), "f")


def _date(value, field="日期"):
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须为 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} 必须为 YYYY-MM-DD")
    return value


def _id(value, field="编号"):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError(f"{field} 无效")
    return int(value)


def _actor(actor):
    if not set(get_payload_roles(actor or {})).intersection({"admin", "finance"}):
        raise PermissionError("仅财务和管理员可以访问财务账簿")
    actor_id = (actor or {}).get("user_id") or (actor or {}).get("id")
    if not actor_id:
        raise PermissionError("无法识别操作人")
    return int(actor_id), str(actor.get("name") or actor.get("username") or actor.get("phone") or actor_id)


def _payment_finance(actor):
    return bool(set(get_payload_roles(actor or {})).intersection({"admin", "finance"}))


def _payment_actor(actor):
    """Business entry permission only; it never authorizes posting/allocation."""
    if not set(get_payload_roles(actor or {})).intersection({"admin", "finance", "salesperson"}):
        raise PermissionError("仅业务员、财务或管理员可以登记收付款")
    actor_id = (actor or {}).get("user_id") or (actor or {}).get("id")
    if not actor_id:
        raise PermissionError("无法识别操作人")
    return int(actor_id), str(actor.get("name") or actor.get("username") or actor.get("phone") or actor_id)


def _payment_access(payment, actor):
    actor_id, _ = _payment_actor(actor)
    if not _payment_finance(actor) and (
        payment.partner_type != "customer" or payment.is_opening or payment.created_by_id != actor_id
    ):
        raise PermissionError("业务员只能查看或处理自己登记的客户收付款")


def _payment_entry_values_allowed(values, actor):
    _payment_actor(actor)
    if not _payment_finance(actor) and (values["partner_type"] != "customer" or values["is_opening"]):
        raise PermissionError("业务员只能登记客户收付款，不能登记供应商或期初资金")


def _version(row, body):
    if "version" not in body or _id(body["version"], "版本") != row.version:
        raise FinanceConflictError("单据已被其他操作更新，请刷新后重试")


def _touch(row):
    row.version += 1
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _row(session, model, row_id, *, locked=False):
    query = session.query(model).filter(model.id == _id(row_id))
    if locked:
        query = query.populate_existing().with_for_update()
    result = query.first()
    if result is None:
        raise LookupError("记录不存在")
    return result


def _partner(session, partner_type, partner_id, *, active=False, locked=False):
    if partner_type not in {"customer", "vendor"}:
        raise ValueError("往来单位类型无效")
    row = _row(session, CustomerTable if partner_type == "customer" else FinanceVendor, partner_id, locked=locked)
    if active and partner_type == "vendor" and not row.active:
        raise ValueError("供应商已停用")
    return row


def _lock_financial_row(session, model, row_id):
    initial = _row(session, model, row_id)
    _partner(session, initial.partner_type, initial.partner_id, locked=True)
    return _row(session, model, row_id, locked=True)


def _audit(session, actor, target, row_id, action, before=None, after=None, reason=None):
    record_audit(event_type=target, target_type=target, target_id=row_id, action=action,
        before_data=before, after_data=after, remark=reason, session=session, operator_payload=actor)


def _replay(row, operation, digest):
    if row.operation != operation or row.payload_hash != digest:
        raise FinanceConflictError("幂等键已用于不同请求，请使用新键")
    return json.loads(row.response_json)


def _run(actor, operation, body, callback, *, authorize=None, replay_guard=None):
    actor_id, _ = (authorize or _actor)(actor)
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为对象")
    key = _text(body.get("idempotency_key"), "幂等键", 128)
    normalized = {k: v for k, v in body.items() if k != "idempotency_key"}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    try:
        with SessionFactory() as session:
            # Keep the same lock order as accounting close/bank matching. This
            # also serializes partner changes on drafts against posting and
            # allocations. Read-only screens never take this global write lock.
            from data.finance.accounting import FinanceSettings
            session.query(FinanceSettings).filter_by(id=1).with_for_update().first()
            if key:
                previous = session.query(FinanceIdempotency).filter_by(actor_id=actor_id, key=key).with_for_update().first()
                if previous:
                    replayed = _replay(previous, operation, digest)
                    if replay_guard:
                        replay_guard(session, replayed, actor)
                    return replayed
            result = callback(session)
            if key:
                session.add(FinanceIdempotency(actor_id=actor_id, key=key, operation=operation,
                    payload_hash=digest, response_json=json.dumps(result, ensure_ascii=False), created_at=_now()))
            session.commit()
            return result
    except IntegrityError as exc:
        # A concurrent identical request may win the unique key race. Its
        # result is authoritative; this transaction's entire work rolled back.
        if key:
            with SessionFactory() as session:
                previous = session.query(FinanceIdempotency).filter_by(actor_id=actor_id, key=key).first()
                if previous:
                    replayed = _replay(previous, operation, digest)
                    if replay_guard:
                        replay_guard(session, replayed, actor)
                    return replayed
        raise FinanceConflictError("记录重复或引用已变化，请刷新后重试") from exc


def _payment_replay_guard(session, result, actor):
    # A cached result must not restore access removed by a later role change.
    _payment_access(_row(session, FinancePayment, result["id"]), actor)


def _effective_allocation(row, as_of=None):
    if as_of is None:
        return row.status == "active"
    return row.allocation_date <= as_of and (row.status == "active" or (row.reversal_date and row.reversal_date > as_of))


def _document_allocated(session, document_id, as_of=None):
    rows = session.query(FinanceAllocation).filter(or_(FinanceAllocation.document_id == document_id,
        FinanceAllocation.credit_document_id == document_id)).all()
    return sum((row.amount for row in rows if _effective_allocation(row, as_of)), ZERO)


def _payment_allocated(session, payment_id, as_of=None):
    rows = session.query(FinanceAllocation).filter_by(payment_id=payment_id).all()
    return sum((row.amount for row in rows if _effective_allocation(row, as_of)), ZERO)


def _normal_direction(partner_type):
    return "incoming" if partner_type == "customer" else "outgoing"


def _refundable_balance(session, partner_type, partner_id, exclude_payment_id=None, as_of=None):
    """Unallocated advance plus credit, less already recorded unallocated refunds."""
    payments = session.query(FinancePayment).filter_by(partner_type=partner_type, partner_id=partner_id).all()
    balance = ZERO
    for payment in payments:
        if payment.id == exclude_payment_id:
            continue
        if not (_payment_effective(payment, as_of) if as_of else payment.status == "posted"):
            continue
        available = payment.amount - _payment_allocated(session, payment.id, as_of)
        balance += available if payment.direction == _normal_direction(partner_type) else -available
    credits = session.query(FinanceDocument).filter_by(partner_type=partner_type, partner_id=partner_id,
        document_type="customer_credit" if partner_type == "customer" else "vendor_credit", status="posted").all()
    balance += sum((row.total_amount - _document_allocated(session, row.id, as_of) for row in credits if not as_of or row.document_date <= as_of), ZERO)
    return max(balance, ZERO)


def _balance_checkpoints(session, partner_type, partner_id, since):
    """Dates at which a partner's available funds can change."""
    payments = session.query(FinancePayment).filter_by(partner_type=partner_type, partner_id=partner_id).all()
    documents = session.query(FinanceDocument).filter_by(partner_type=partner_type, partner_id=partner_id).all()
    dates = {since}
    for row in payments:
        dates.update(value for value in (row.payment_date, row.reversal_date) if value and value >= since)
    for row in documents:
        if row.document_date >= since:
            dates.add(row.document_date)
    allocations = session.query(FinanceAllocation).filter(or_(FinanceAllocation.document_id.in_([row.id for row in documents]),
        FinanceAllocation.payment_id.in_([row.id for row in payments]))).all()
    for row in allocations:
        dates.update(value for value in (row.allocation_date, row.reversal_date) if value and value >= since)
    return dates


def _line_dict(line):
    return {"id": line.id, "sequence": line.sequence, "description": line.description,
        "quantity": _str(line.quantity, FOUR), "unit_price": _str(line.unit_price, FOUR),
        "tax_rate": _str(line.tax_rate, FOUR), "subtotal": _str(line.subtotal),
        "tax_amount": _str(line.tax_amount), "total_amount": _str(line.total_amount),
        "order_uid": line.order_uid, "order_number": line.order_number}


def document_dict(session, document, *, include_lines=True, as_of=None):
    fields = ("id", "number", "document_type", "is_opening", "partner_type", "partner_id", "partner_name",
        "document_date", "due_date", "currency", "reference", "memo", "status", "version",
        "original_document_id", "reversed_by_id", "created_by_id", "created_by_name", "created_at",
        "updated_at", "posted_at", "cancelled_at", "cancellation_reason")
    result = {field: getattr(document, field) for field in fields}
    order_link = session.get(FinanceOrderDocument, document.id)
    result["managed_order_uid"] = order_link.order_uid if order_link else None
    result["order_managed"] = bool(order_link)
    allocated = _document_allocated(session, document.id, as_of)
    residual = _money(document.total_amount - allocated)
    result.update(subtotal=_str(document.subtotal), tax_amount=_str(document.tax_amount), total_amount=_str(document.total_amount),
        allocated_amount=_str(allocated), residual_amount=_str(residual),
        payment_status="paid" if residual == 0 else ("partial" if allocated > 0 else "unpaid"))
    if document.document_type.endswith("credit"):
        result["available_amount"] = _str(min(residual, _refundable_balance(session, document.partner_type, document.partner_id, as_of=as_of)) if document.status == "posted" else ZERO)
    if include_lines:
        result["lines"] = [_line_dict(line) for line in document.lines]
    return result


def payment_dict(session, payment, *, as_of=None):
    fields = ("id", "number", "direction", "is_opening", "partner_type", "partner_id", "partner_name", "account_id", "account_name",
        "payment_date", "currency", "reference", "memo", "status", "version", "created_by_id", "created_by_name",
        "created_at", "updated_at", "posted_at", "cancelled_at", "cancellation_reason", "reversed_at", "reversal_date", "reversal_reason",
        "submitted_at", "submitted_by_id", "submitted_by_name", "reviewed_at", "reviewed_by_id", "reviewed_by_name", "review_remark", "requires_submission")
    result = {field: getattr(payment, field) for field in fields}
    allocated = _payment_allocated(session, payment.id, as_of)
    result.update(amount=_str(payment.amount), allocated_amount=_str(allocated), unallocated_amount=_str(payment.amount - allocated))
    available = payment.amount - allocated
    if payment.direction == _normal_direction(payment.partner_type):
        available = min(available, _refundable_balance(session, payment.partner_type, payment.partner_id, as_of=as_of))
    result["available_amount"] = _str(available if payment.status == "posted" else ZERO)
    references = json.loads(payment.reference_orders_json or "[]")
    result["reference_orders"] = references
    result["reference_order_uids"] = [row["order_uid"] for row in references]
    packing_boxes = json.loads(payment.reference_packing_boxes_json or "[]")
    result["reference_packing_boxes"] = packing_boxes
    result["reference_box_uids"] = [row["box_uid"] for row in packing_boxes]
    if packing_boxes:
        result.update(_payment_packing_order_references(session, payment, packing_boxes))
    else:
        result.update(packing_order_references=[], packing_order_uids=[], unresolved_packing_boxes=[])
    return result


def _allocation_dict(session, row):
    result = {field: getattr(row, field) for field in ("id", "payment_id", "credit_document_id", "document_id", "document_number",
        "status", "version", "allocation_date", "reason", "created_by_id", "created_by_name", "created_at", "reversed_at", "reversal_date", "reversal_reason")}
    result["amount"] = _str(row.amount)
    result["payment_number"] = _row(session, FinancePayment, row.payment_id).number if row.payment_id else None
    result["credit_document_number"] = _row(session, FinanceDocument, row.credit_document_id).number if row.credit_document_id else None
    order_link = session.get(FinanceOrderDocument, row.document_id)
    result["order_uid"] = order_link.order_uid if order_link else None
    if order_link:
        document = _row(session, FinanceDocument, row.document_id)
        result["order_number"] = document.lines[0].order_number if document.lines else None
    return result


def _page(items, page=1, page_size=30):
    page, page_size = max(int(page or 1), 1), min(max(int(page_size or 30), 1), 200)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "total": len(items), "page": page, "page_size": page_size}


def _currency(body):
    if body.get("currency", "CNY") != "CNY":
        raise ValueError("当前财务账簿仅支持人民币 CNY")
    return "CNY"


def _document_values(session, body, existing=None):
    document_type = body.get("document_type", existing.document_type if existing else None)
    if document_type not in DOCUMENT_TYPES:
        raise ValueError("账单类型无效")
    if existing and document_type != existing.document_type:
        raise ValueError("账单类型不能修改，请另建草稿")
    partner_type = DOCUMENT_TYPES[document_type]
    partner_id = _id(body.get("partner_id", existing.partner_id if existing else None), "往来单位")
    partner = _partner(session, partner_type, partner_id, active=True, locked=True)
    document_date = _date(body.get("document_date", existing.document_date if existing else None), "账单日期")
    is_opening = body.get("is_opening", existing.is_opening if existing else False)
    if not isinstance(is_opening, bool):
        raise ValueError("期初标志必须为 true 或 false")
    _validate_opening(session, document_type, document_date, is_opening)
    due_date = _date(body.get("due_date") or (existing.due_date if existing else document_date), "到期日期")
    if due_date < document_date and not is_opening:
        raise ValueError("到期日期不能早于账单日期")
    original_id = body.get("original_document_id", existing.original_document_id if existing else None)
    if original_id and session.get(FinanceOrderDocument, _id(original_id)):
        raise FinanceConflictError("订单应收账单请在订单应收中确认报价变化，系统会生成关联贷项")
    if document_type.endswith("credit"):
        original_id = _id(original_id, "原账单")
        original = _row(session, FinanceDocument, original_id, locked=True)
        if (original.status != "posted" or CREDIT_FOR.get(original.document_type) != document_type
            or original.partner_type != partner_type or original.partner_id != partner_id):
            raise ValueError("贷项必须关联同一往来单位的已生效原账单")
        if document_date < original.document_date:
            raise ValueError("贷项日期不能早于原账单")
    elif original_id is not None:
        raise ValueError("普通账单不能关联贷项原单")
    return dict(document_type=document_type, is_opening=is_opening, partner_type=partner_type, partner_id=partner_id, partner_name=partner.name,
        document_date=document_date, due_date=due_date, currency=_currency(body), original_document_id=original_id,
        reference=_text(body.get("reference", existing.reference if existing else ""), "外部单号", 256),
        memo=_text(body.get("memo", existing.memo if existing else ""), "备注", 5000))


def _validate_opening(session, document_type, document_date, is_opening):
    if not is_opening:
        return
    from data.finance.accounting import FinanceSettings
    settings = session.query(FinanceSettings).filter_by(id=1).with_for_update().first()
    if settings is None:
        raise ValueError("期初账单需要先完成建账设置")
    if document_type not in {"customer_invoice", "vendor_bill"}:
        raise ValueError("仅客户账单和供应商账单可以登记为期初余额")
    if document_date != settings.opening_date:
        raise ValueError("期初账单日期必须等于建账日期")
    if settings.opening_confirmed:
        raise FinanceConflictError("期初余额已确认，不能新增或生效期初账单")


def _lines(session, payload):
    from data.DB import OrderTable
    if not isinstance(payload, list) or not payload or len(payload) > 200:
        raise ValueError("账单必须包含 1 至 200 条费用明细")
    lines = []
    for sequence, value in enumerate(payload, 1):
        if not isinstance(value, dict):
            raise ValueError("费用明细格式无效")
        description = _text(value.get("description"), "费用说明", 512, required=True)
        quantity = _decimal(value.get("quantity", 1), "数量", FOUR, positive=True)
        unit_price = _decimal(value.get("unit_price"), "单价", FOUR)
        tax_rate = _decimal(value.get("tax_rate", 0), "税率", FOUR, maximum=Decimal("100"))
        subtotal = _decimal(quantity * unit_price, "明细金额")
        tax_amount = _decimal(subtotal * tax_rate / 100, "税额")
        total_amount = _decimal(subtotal + tax_amount, "含税金额")
        order_uid = value.get("order_uid") or None
        order_number = None
        if order_uid:
            order_uid = _text(order_uid, "订单编号", 32, required=True)
            order = session.query(OrderTable).filter_by(uid=order_uid).first()
            if order is None:
                raise ValueError("关联订单不存在")
            order_number = order.order_id or order.uid
        lines.append(FinanceDocumentLine(sequence=sequence, description=description, quantity=quantity,
            unit_price=unit_price, tax_rate=tax_rate, subtotal=subtotal, tax_amount=tax_amount,
            total_amount=total_amount, order_uid=order_uid, order_number=order_number))
    if sum((line.total_amount for line in lines), ZERO) <= 0:
        raise ValueError("账单总额必须大于 0")
    _decimal(sum((line.total_amount for line in lines), ZERO), "账单总额")
    return lines


def _set_lines(document, lines):
    document.lines.extend(lines)
    document.subtotal = sum((line.subtotal for line in lines), ZERO)
    document.tax_amount = sum((line.tax_amount for line in lines), ZERO)
    document.total_amount = sum((line.total_amount for line in lines), ZERO)


def create_document(body, actor):
    def change(session):
        values = _document_values(session, body)
        lines = _lines(session, body.get("lines"))
        actor_id, actor_name = _actor(actor)
        now = _now()
        document = FinanceDocument(**values, number=f"{PREFIX[values['document_type']]}-{uuid.uuid4().hex[:16].upper()}",
            status="draft", version=1, created_by_id=actor_id, created_by_name=actor_name, created_at=now, updated_at=now)
        _set_lines(document, lines)
        session.add(document)
        session.flush()
        result = document_dict(session, document)
        _audit(session, actor, "finance_document", document.id, "create", after=result)
        return result
    return _run(actor, "document.create", body, change)


def update_document(document_id, body, actor):
    def change(session):
        document = _lock_financial_row(session, FinanceDocument, document_id)
        _version(document, body)
        if document.status != "draft":
            raise FinanceConflictError("只有草稿可以修改，已生效账单请开具贷项或冲销")
        if "lines" in body:
            from services.supplier_reconciliation_service import is_import_document
            if is_import_document(session, document.id):
                raise FinanceConflictError("对账导入的费用明细不能直接编辑，请取消草稿后修正 Excel 并重新上传")
        before = document_dict(session, document)
        values = _document_values(session, body, document)
        for field, value in values.items():
            setattr(document, field, value)
        if "lines" in body:
            lines = _lines(session, body["lines"])
            document.lines.clear()
            session.flush()
            _set_lines(document, lines)
        _touch(document)
        session.flush()
        result = document_dict(session, document)
        _audit(session, actor, "finance_document", document.id, "update", before, result, body.get("reason"))
        return result
    return _run(actor, f"document.{document_id}.update", body, change)


def _post_document(session, document, actor, *, allow_order_adjustment=False):
    from services.finance_accounting_service import post_document as accounting_post
    if not allow_order_adjustment and document.document_type in {"customer_invoice", "customer_credit"}:
        from data.finance.order_settlement import FinanceOrderSettlement
        if (document.original_document_id and session.get(FinanceOrderDocument, document.original_document_id)) or any(
                line.order_uid and session.get(FinanceOrderSettlement, line.order_uid) for line in document.lines):
            raise FinanceConflictError("订单应收已由统一流程管理，请在订单应收确认变化，不能另行入账")
    if document.status != "draft":
        raise FinanceConflictError("只有草稿可以生效")
    if document.document_type == "vendor_bill":
        from services.supplier_reconciliation_service import validate_import_document_for_post
        validate_import_document_for_post(session, document)
    _partner(session, document.partner_type, document.partner_id, active=True, locked=True)
    _validate_opening(session, document.document_type, document.document_date, document.is_opening)
    if document.original_document_id:
        original = _row(session, FinanceDocument, document.original_document_id, locked=True)
        credits = session.query(FinanceDocument).filter_by(original_document_id=original.id, status="posted").all()
        if original.status != "posted" or document.total_amount + sum((row.total_amount for row in credits), ZERO) > original.total_amount:
            raise ValueError("累计贷项金额不能超过原账单金额")
        if document.subtotal + sum((row.subtotal for row in credits), ZERO) > original.subtotal:
            raise ValueError("累计贷项不含税金额不能超过原账单不含税金额")
        if document.tax_amount + sum((row.tax_amount for row in credits), ZERO) > original.tax_amount:
            raise ValueError("累计贷项税额不能超过原账单税额")
    document.status = "posted"
    document.posted_at = _now()
    _touch(document)
    session.flush()
    accounting_post(session, document, actor)


def post_document(document_id, body, actor):
    def change(session):
        document = _lock_financial_row(session, FinanceDocument, document_id)
        _version(document, body)
        before = document_dict(session, document)
        _post_document(session, document, actor)
        result = document_dict(session, document)
        _audit(session, actor, "finance_document", document.id, "post", before, result, body.get("reason"))
        return result
    return _run(actor, f"document.{document_id}.post", body, change)


def cancel_document(document_id, body, actor):
    def change(session):
        document = _lock_financial_row(session, FinanceDocument, document_id)
        _version(document, body)
        if document.status != "draft":
            raise FinanceConflictError("只有草稿可以取消，已生效账单请使用贷项或冲销")
        reason = _text(body.get("reason"), "取消原因", 2000, required=True)
        before = document_dict(session, document)
        document.status, document.cancelled_at, document.cancellation_reason = "cancelled", _now(), reason
        _touch(document)
        result = document_dict(session, document)
        _audit(session, actor, "finance_document", document.id, "cancel", before, result, reason)
        return result
    return _run(actor, f"document.{document_id}.cancel", body, change)


def reverse_document(document_id, body, actor):
    return _run(actor, f"document.{document_id}.reverse", body,
        lambda session: _reverse_document(session, document_id, body, actor))


def _reverse_document(session, document_id, body, actor, *, allow_legacy=False):
    if session.get(FinanceOrderDocument, document_id):
        raise FinanceConflictError("订单应收账单请在订单应收中确认报价变化，不能手工重复冲销")
    document = _lock_financial_row(session, FinanceDocument, document_id)
    _version(document, body)
    if not allow_legacy:
        from data.finance.legacy import FinanceLegacyLink
        if session.query(FinanceLegacyLink.id).filter_by(document_id=document_id, status="active").first():
            raise FinanceConflictError("该期初单据属于旧账接入，请在旧账接入记录使用撤销接入，保留完整迁移链")
    if document.status != "posted" or document.document_type not in CREDIT_FOR or document.reversed_by_id:
        raise FinanceConflictError("仅已生效且尚未冲销的原账单可以全额冲销")
    if session.query(FinanceDocument.id).filter_by(original_document_id=document.id, status="posted").first():
        raise FinanceConflictError("原账单已有贷项，请按剩余金额创建部分贷项")
    reason = _text(body.get("reason"), "冲销原因", 2000, required=True)
    reversal_date = _date(body.get("document_date") or _today(), "冲销日期")
    if reversal_date < document.document_date:
        raise ValueError("冲销日期不能早于原账单")
    actor_id, actor_name = _actor(actor)
    before = document_dict(session, document)
    credit_type = CREDIT_FOR[document.document_type]
    credit = FinanceDocument(number=f"{PREFIX[credit_type]}-{uuid.uuid4().hex[:16].upper()}", document_type=credit_type,
        is_opening=False,
        partner_type=document.partner_type, partner_id=document.partner_id, partner_name=document.partner_name,
        document_date=reversal_date, due_date=reversal_date, currency=document.currency, reference=document.number,
        memo=reason, original_document_id=document.id, status="draft", version=1,
        created_by_id=actor_id, created_by_name=actor_name, created_at=_now(), updated_at=_now())
    _set_lines(credit, [FinanceDocumentLine(**{field: getattr(line, field) for field in (
        "sequence", "description", "quantity", "unit_price", "tax_rate", "subtotal", "tax_amount", "total_amount", "order_uid", "order_number")}) for line in document.lines])
    session.add(credit)
    session.flush()
    _audit(session, actor, "finance_document", credit.id, "create", after=document_dict(session, credit), reason=reason)
    credit_before = document_dict(session, credit)
    _post_document(session, credit, actor)
    _audit(session, actor, "finance_document", credit.id, "post", credit_before, document_dict(session, credit), reason)
    document.reversed_by_id = credit.id
    _touch(document)
    remaining = document.total_amount - _document_allocated(session, document.id)
    if remaining > 0:
        _allocate(session, actor, credit=credit, payment=None,
            targets=[(document, remaining)], allocation_date=reversal_date, reason=reason)
    result = document_dict(session, document)
    _audit(session, actor, "finance_document", document.id, "reverse", before, result, reason)
    return {"document": result, "credit": document_dict(session, credit)}


def get_document(document_id, actor):
    _actor(actor)
    with SessionFactory() as session:
        return document_dict(session, _row(session, FinanceDocument, document_id))


def list_documents(actor, **filters):
    _actor(actor)
    with SessionFactory() as session:
        query = session.query(FinanceDocument)
        for field in ("document_type", "status", "partner_id", "partner_type"):
            if filters.get(field):
                query = query.filter(getattr(FinanceDocument, field) == filters[field])
        if filters.get("date_from"):
            query = query.filter(FinanceDocument.document_date >= _date(filters["date_from"]))
        if filters.get("date_to"):
            query = query.filter(FinanceDocument.document_date <= _date(filters["date_to"]))
        if filters.get("q"):
            value = f"%{filters['q']}%"
            query = query.filter(or_(FinanceDocument.number.ilike(value), FinanceDocument.partner_name.ilike(value), FinanceDocument.reference.ilike(value)))
        rows = [document_dict(session, row, include_lines=False) for row in query.order_by(FinanceDocument.id.desc()).all()]
        if filters.get("payment_status"):
            rows = [row for row in rows if row["payment_status"] == filters["payment_status"]]
        if str(filters.get("open_only", "")) in {"1", "true", "True"} or str(filters.get("overdue", "")) in {"1", "true", "True"}:
            rows = [row for row in rows if row["status"] == "posted" and Decimal(row["residual_amount"]) > 0]
        if str(filters.get("overdue", "")) in {"1", "true", "True"}:
            rows = [row for row in rows if row["due_date"] < _today()]
        return _page(rows, filters.get("page"), filters.get("page_size"))


def _payment_values(session, body, existing=None):
    direction = body.get("direction", existing.direction if existing else None)
    if direction not in {"incoming", "outgoing"}:
        raise ValueError("资金方向无效")
    partner_type = body.get("partner_type", existing.partner_type if existing else None)
    partner_id = _id(body.get("partner_id", existing.partner_id if existing else None), "往来单位")
    partner = _partner(session, partner_type, partner_id, active=True, locked=True)
    account = _row(session, FinanceAccount, body.get("account_id", existing.account_id if existing else None), locked=True)
    if not account.active:
        raise ValueError("资金账户已停用")
    payment_date = _date(body.get("payment_date", existing.payment_date if existing else None), "收付款日期")
    is_opening = body.get("is_opening", existing.is_opening if existing else False)
    if not isinstance(is_opening, bool):
        raise ValueError("期初标志必须为 true 或 false")
    _validate_opening_payment(session, partner_type, direction, payment_date, is_opening)
    return dict(direction=direction, partner_type=partner_type, partner_id=partner_id, partner_name=partner.name,
        is_opening=is_opening,
        account_id=account.id, account_name=account.name, currency=_currency(body),
        payment_date=payment_date,
        amount=_decimal(body.get("amount", existing.amount if existing else None), positive=True),
        reference_orders_json=_payment_reference_orders(session, body, partner_type, partner, existing),
        reference_packing_boxes_json=_payment_reference_packing_boxes(session, body, partner_type, partner, existing),
        reference=_text(body.get("reference", existing.reference if existing else ""), "资金凭据号", 256),
        memo=_text(body.get("memo", existing.memo if existing else ""), "备注", 5000))


def _payment_reference_orders(session, body, partner_type, partner, existing=None):
    from data.DB import OrderTable
    previous = json.loads(existing.reference_orders_json or "[]") if existing else []
    uids = body.get("reference_order_uids", [row["order_uid"] for row in previous])
    if not isinstance(uids, list) or len(uids) > 100:
        raise ValueError("备注订单须为最多 100 个订单编号的列表")
    if uids and partner_type != "customer":
        raise ValueError("仅客户收付款可以选择客户订单作备注")
    normalized = [_text(value, "备注订单编号", 32, required=True) for value in uids]
    if len(set(normalized)) != len(normalized):
        raise ValueError("备注订单不能重复")
    if existing and existing.partner_type == partner_type and existing.partner_id == partner.id and normalized == [row["order_uid"] for row in previous]:
        # Previously saved descriptions survive archive, renaming or moving an
        # order. Such operational changes cannot mutate or block a cash fact.
        return existing.reference_orders_json or "[]"
    if not normalized:
        return "[]"
    orders = session.query(OrderTable).filter(OrderTable.uid.in_(normalized)).all()
    mapping = {order.uid: order for order in orders}
    references = []
    for uid in normalized:
        order = mapping.get(uid)
        if order is None or order.archive:
            raise ValueError("备注订单不存在或已归档，请重新选择")
        customer_ids = {row.id for row in order.customers}
        same_customer = partner.id in customer_ids if customer_ids else order.customer_name == partner.name
        if not same_customer:
            raise ValueError("备注订单必须属于所选客户")
        references.append({"order_uid": order.uid, "order_number": order.order_id or order.uid, "customer_id": partner.id})
    return json.dumps(references, ensure_ascii=False)


def _payment_packing_box_option(box, packing_list):
    return {"box_uid": box.uid, "packing_list_uid": packing_list.uid,
        "list_number": packing_list.list_number, "box_number": box.box_number,
        "transfer_id": box.transfer_id or "", "item_name": box.item_name or "",
        "weight": box.weight, "customer_id": packing_list.customer_id,
        "target_order_uid": box.target_order_uid}


def _payment_reference_packing_boxes(session, body, partner_type, partner, existing=None):
    """Save identities and descriptions even when no operational order exists."""
    from data.DB import CargoTable
    from data.packing.PackingList import PackingListTable
    previous = json.loads(existing.reference_packing_boxes_json or "[]") if existing else []
    uids = body.get("reference_box_uids", [row["box_uid"] for row in previous])
    if not isinstance(uids, list) or len(uids) > 500:
        raise ValueError("备注箱子须为最多 500 个箱子编号的列表")
    if uids and partner_type != "customer":
        raise ValueError("仅客户收付款可以备注装箱单箱子")
    normalized = [_text(value, "备注箱子编号", 32, required=True) for value in uids]
    if len(set(normalized)) != len(normalized):
        raise ValueError("备注箱子不能重复")
    same_partner = existing and existing.partner_type == partner_type and existing.partner_id == partner.id
    previous_by_uid = {row["box_uid"]: row for row in previous} if same_partner else {}
    added = [uid for uid in normalized if uid not in previous_by_uid]
    rows = session.query(CargoTable, PackingListTable).join(
        PackingListTable, CargoTable.packing_list_uid == PackingListTable.uid).filter(
        CargoTable.uid.in_(added), CargoTable.archive.is_(False), PackingListTable.archive.is_(False)).all() if added else []
    mapping = {box.uid: (box, packing) for box, packing in rows}
    references = []
    for uid in normalized:
        if uid in previous_by_uid:
            references.append(previous_by_uid[uid])
            continue
        if uid not in mapping:
            raise ValueError("备注箱子或装箱单不存在或已归档，请重新选择")
        box, packing = mapping[uid]
        if packing.customer_id is not None and packing.customer_id != partner.id:
            raise ValueError("备注装箱单箱子已绑定其他客户，请重新选择")
        references.append(_payment_packing_box_option(box, packing))
    return json.dumps(references, ensure_ascii=False)


def _payment_packing_order_references(session, payment, references=None):
    """Resolve current box ownership without changing saved cash or notes."""
    from data.DB import CargoTable, OrderTable
    references = references if references is not None else json.loads(payment.reference_packing_boxes_json or "[]")
    box_uids = [row["box_uid"] for row in references]
    boxes = {row.uid: row for row in session.query(CargoTable).filter(CargoTable.uid.in_(box_uids)).all()} if box_uids else {}
    order_uids = {row.target_order_uid for row in boxes.values() if row.target_order_uid}
    orders = {row.uid: row for row in session.query(OrderTable).filter(OrderTable.uid.in_(order_uids)).all()} if order_uids else {}
    resolved, unresolved = {}, []
    for reference in references:
        box = boxes.get(reference["box_uid"])
        order = orders.get(box.target_order_uid) if box else None
        reason = None
        if box is None or box.archive:
            reason = "箱子不存在或已归档"
        elif not box.target_order_uid:
            reason = "箱子尚未分配订单"
        elif order is None or order.archive:
            reason = "箱子所属订单不存在或已归档"
        else:
            customer_ids = {row.id for row in order.customers}
            same_customer = payment.partner_id in customer_ids if customer_ids else order.customer_name == payment.partner_name
            if not same_customer:
                reason = "箱子所属订单与收付款客户不一致"
        if reason:
            unresolved.append({**reference, "reason": reason})
        else:
            resolved.setdefault(order.uid, {"order_uid": order.uid, "order_number": order.order_id or order.uid,
                "customer_id": payment.partner_id, "box_uids": []})["box_uids"].append(box.uid)
    return {"packing_order_references": list(resolved.values()), "packing_order_uids": list(resolved),
        "unresolved_packing_boxes": unresolved}


def _validate_opening_payment(session, partner_type, direction, payment_date, is_opening):
    if not is_opening:
        return
    if direction != _normal_direction(partner_type):
        raise ValueError("期初结算仅支持客户预收或供应商预付")
    _validate_opening(session, "customer_invoice" if partner_type == "customer" else "vendor_bill", payment_date, True)


def create_payment(body, actor):
    def change(session):
        values = _payment_values(session, body)
        _payment_entry_values_allowed(values, actor)
        actor_id, actor_name = _payment_actor(actor)
        payment = FinancePayment(**values, number=f"PAY-{uuid.uuid4().hex[:16].upper()}", status="draft", version=1,
            created_by_id=actor_id, created_by_name=actor_name, created_at=_now(), updated_at=_now(), requires_submission=not _payment_finance(actor))
        session.add(payment)
        session.flush()
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "create", after=result)
        return result
    return _run(actor, "payment.create", body, change, authorize=_payment_actor, replay_guard=_payment_replay_guard)


def update_payment(payment_id, body, actor):
    def change(session):
        payment = _lock_financial_row(session, FinancePayment, payment_id)
        _payment_access(payment, actor)
        _version(payment, body)
        if payment.status != "draft":
            raise FinanceConflictError("仅收付款草稿可以修改")
        before = payment_dict(session, payment)
        values = _payment_values(session, body, payment)
        _payment_entry_values_allowed(values, actor)
        for field, value in values.items():
            setattr(payment, field, value)
        _touch(payment)
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "update", before, result, body.get("reason"))
        return result
    return _run(actor, f"payment.{payment_id}.update", body, change, authorize=_payment_actor, replay_guard=_payment_replay_guard)


def submit_payment(payment_id, body, actor):
    def change(session):
        payment = _lock_financial_row(session, FinancePayment, payment_id)
        _payment_access(payment, actor)
        _version(payment, body)
        if payment.status != "draft":
            raise FinanceConflictError("仅草稿可以提交财务确认")
        if payment.is_opening:
            raise ValueError("期初资金请通过财务期初核准流程处理")
        account = _row(session, FinanceAccount, payment.account_id, locked=True)
        if not account.active:
            raise ValueError("资金账户已停用，请先修改账户")
        before = payment_dict(session, payment)
        actor_id, actor_name = _payment_actor(actor)
        payment.status, payment.submitted_at = "pending", _now()
        payment.submitted_by_id, payment.submitted_by_name = actor_id, actor_name
        payment.reviewed_at, payment.reviewed_by_id, payment.reviewed_by_name, payment.review_remark = None, None, None, None
        _touch(payment)
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "submit", before, result)
        return result
    return _run(actor, f"payment.{payment_id}.submit", body, change, authorize=_payment_actor, replay_guard=_payment_replay_guard)


def return_payment(payment_id, body, actor):
    def change(session):
        payment = _lock_financial_row(session, FinancePayment, payment_id)
        _version(payment, body)
        if payment.status != "pending":
            raise FinanceConflictError("仅待财务确认的收付款可以退回")
        reason = _text(body.get("reason"), "退回原因", 2000, required=True)
        reviewer_id, reviewer_name = _actor(actor)
        if payment.created_by_id == reviewer_id:
            raise PermissionError("登记人不能审核自己提交的收付款")
        before = payment_dict(session, payment)
        payment.status, payment.reviewed_at, payment.review_remark = "draft", _now(), reason
        payment.reviewed_by_id, payment.reviewed_by_name = reviewer_id, reviewer_name
        _touch(payment)
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "return", before, result, reason)
        return result
    return _run(actor, f"payment.{payment_id}.return", body, change)


def post_payment(payment_id, body, actor):
    def change(session):
        from services.finance_accounting_service import post_payment as accounting_post
        payment = _lock_financial_row(session, FinancePayment, payment_id)
        _version(payment, body)
        if payment.status not in {"draft", "pending"}:
            raise FinanceConflictError("仅草稿或待财务确认的收付款可以生效")
        if payment.status == "draft" and payment.requires_submission:
            raise FinanceConflictError("业务员草稿尚未提交，请先由登记人提交财务确认")
        reviewer_id, reviewer_name = _actor(actor)
        if payment.status == "pending" and payment.created_by_id == reviewer_id:
            raise PermissionError("登记人不能审核自己提交的收付款")
        _partner(session, payment.partner_type, payment.partner_id, active=True, locked=True)
        _validate_opening_payment(session, payment.partner_type, payment.direction, payment.payment_date, payment.is_opening)
        account = _row(session, FinanceAccount, payment.account_id, locked=True)
        if not account.active:
            raise ValueError("资金账户已停用")
        if payment.direction != _normal_direction(payment.partner_type):
            available = _refundable_balance(session, payment.partner_type, payment.partner_id)
            if payment.amount > available:
                raise ValueError(f"退款金额超过可退余额 {_str(available)} CNY，请先核对预收预付或贷项")
            if any(payment.amount > _refundable_balance(session, payment.partner_type, payment.partner_id, as_of=point)
                for point in _balance_checkpoints(session, payment.partner_type, payment.partner_id, payment.payment_date)):
                raise ValueError("退款日期会造成历史可退余额不足，请核对实际资金日期")
        before = payment_dict(session, payment)
        payment.status, payment.posted_at = "posted", _now()
        payment.reviewed_at, payment.reviewed_by_id, payment.reviewed_by_name = payment.posted_at, reviewer_id, reviewer_name
        payment.review_remark = _text(body.get("reason"), "确认说明", 2000) or None
        _touch(payment)
        session.flush()
        accounting_post(session, payment, actor)
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "post", before, result, body.get("reason"))
        return result
    return _run(actor, f"payment.{payment_id}.post", body, change)


def cancel_payment(payment_id, body, actor):
    def change(session):
        payment = _lock_financial_row(session, FinancePayment, payment_id)
        _payment_access(payment, actor)
        _version(payment, body)
        if payment.status != "draft":
            raise FinanceConflictError("仅草稿可以取消；生效资金请先撤销核销再冲销")
        reason = _text(body.get("reason"), "取消原因", 2000, required=True)
        before = payment_dict(session, payment)
        payment.status, payment.cancelled_at, payment.cancellation_reason = "cancelled", _now(), reason
        _touch(payment)
        result = payment_dict(session, payment)
        _audit(session, actor, "finance_payment", payment.id, "cancel", before, result, reason)
        return result
    return _run(actor, f"payment.{payment_id}.cancel", body, change, authorize=_payment_actor, replay_guard=_payment_replay_guard)


def reverse_payment(payment_id, body, actor):
    return _run(actor, f"payment.{payment_id}.reverse", body,
        lambda session: _reverse_payment(session, payment_id, body, actor))


def _reverse_payment(session, payment_id, body, actor, *, allow_legacy=False):
    from services.finance_accounting_service import reverse_payment as accounting_reverse
    payment = _lock_financial_row(session, FinancePayment, payment_id)
    _version(payment, body)
    if not allow_legacy:
        from data.finance.legacy import FinanceLegacyLink
        if session.query(FinanceLegacyLink.id).filter_by(payment_id=payment_id, status="active").first():
            raise FinanceConflictError("该期初单据属于旧账接入，请在旧账接入记录使用撤销接入，保留完整迁移链")
    if payment.status != "posted":
        raise FinanceConflictError("仅已生效收付款可以冲销")
    if _payment_allocated(session, payment.id) > 0:
        raise FinanceConflictError("请先撤销该资金记录的全部核销")
    if payment.direction == _normal_direction(payment.partner_type) and _refundable_balance(session, payment.partner_type, payment.partner_id) < payment.amount:
        raise FinanceConflictError("该预收预付款已用于退款，请先核实并处理关联退款后再冲销")
    reason = _text(body.get("reason"), "冲销原因", 2000, required=True)
    reversal_date = _date(body.get("payment_date") or _today(), "冲销日期")
    if reversal_date < payment.payment_date:
        raise ValueError("冲销日期不能早于原收付款日期")
    if payment.direction == _normal_direction(payment.partner_type) and any(
        payment.amount > _refundable_balance(session, payment.partner_type, payment.partner_id, as_of=point)
        for point in _balance_checkpoints(session, payment.partner_type, payment.partner_id, reversal_date)
    ):
        raise ValueError("冲销日期会使历史已退款资金失去来源，请核对原收付款日期")
    # A reversal cannot erase cash before its last historical allocation.
    allocations = session.query(FinanceAllocation).filter_by(payment_id=payment.id).all()
    if any(row.reversal_date and row.reversal_date > reversal_date for row in allocations):
        raise ValueError("资金冲销日期不能早于核销撤销日期")
    before = payment_dict(session, payment)
    accounting_reverse(session, payment, actor, reversal_date, reason)
    payment.status, payment.reversed_at, payment.reversal_date, payment.reversal_reason = "reversed", _now(), reversal_date, reason
    _touch(payment)
    result = payment_dict(session, payment)
    _audit(session, actor, "finance_payment", payment.id, "reverse", before, result, reason)
    return result


def get_payment(payment_id, actor):
    _payment_actor(actor)
    with SessionFactory() as session:
        payment = _row(session, FinancePayment, payment_id)
        _payment_access(payment, actor)
        return payment_dict(session, payment)


def list_payments(actor, **filters):
    actor_id, _ = _payment_actor(actor)
    with SessionFactory() as session:
        query = session.query(FinancePayment)
        if not _payment_finance(actor):
            query = query.filter(FinancePayment.created_by_id == actor_id, FinancePayment.partner_type == "customer", FinancePayment.is_opening.is_(False))
        elif filters.get("created_by_id"):
            query = query.filter(FinancePayment.created_by_id == _id(filters["created_by_id"], "登记人"))
        for field in ("status", "direction", "partner_type", "partner_id", "account_id"):
            if filters.get(field):
                query = query.filter(getattr(FinancePayment, field) == filters[field])
        if filters.get("q"):
            value = f"%{filters['q']}%"
            query = query.filter(or_(FinancePayment.number.ilike(value), FinancePayment.partner_name.ilike(value), FinancePayment.reference.ilike(value)))
        if filters.get("date_from"):
            query = query.filter(FinancePayment.payment_date >= _date(filters["date_from"]))
        if filters.get("date_to"):
            query = query.filter(FinancePayment.payment_date <= _date(filters["date_to"]))
        rows = [payment_dict(session, row) for row in query.order_by(FinancePayment.id.desc()).all()]
        if str(filters.get("open_only", "")) in {"1", "true", "True"}:
            rows = [row for row in rows if row["status"] == "posted" and Decimal(row["unallocated_amount"]) > 0]
        return _page(rows, filters.get("page"), filters.get("page_size"))


PAYMENT_ORDER_FIELDS = (
    "transportation", "receiver", "receiver_phone", "mail", "country", "province",
    "city", "address", "en_name", "cn_name", "post_code", "zip_code", "tag_all",
    "create_date", "update_date", "total_weight", "cargo_count",
)
PAYMENT_ORDER_SEARCH_FIELDS = (
    "uid", "order_id", "customer_name", "order_date",
    *(field for field in PAYMENT_ORDER_FIELDS if field not in {"total_weight", "cargo_count"}),
)


def _payment_order_option(row, customer):
    """Operational order-list fields; no customer contacts or financial data."""
    return {
        **{field: getattr(row, field) for field in PAYMENT_ORDER_FIELDS},
        "uid": row.uid, "order_id": row.order_id or row.uid,
        "order_uid": row.uid, "order_number": row.order_id or row.uid,
        "customer_id": customer.id, "customer_name": customer.name,
        "order_date": row.create_date or row.order_date,
    }


def payment_options(kind, actor, **filters):
    """Business-entry lookup data, without financial balances/costs."""
    from data.DB import OrderTable
    _payment_actor(actor)
    with SessionFactory() as session:
        query_text = str(filters.get("q") or "").strip()
        if kind == "customers":
            query = session.query(CustomerTable)
            if query_text:
                query = query.filter(CustomerTable.name.ilike(f"%{query_text}%"))
            rows = [{"id": row.id, "name": row.name} for row in query.order_by(CustomerTable.name.asc()).all()]
        elif kind == "accounts":
            query = session.query(FinanceAccount).filter(FinanceAccount.active.is_(True), FinanceAccount.currency == "CNY")
            if query_text:
                query = query.filter(FinanceAccount.name.ilike(f"%{query_text}%"))
            rows = [{key: getattr(row, key) for key in ("id", "name", "account_type", "account_number", "currency")}
                for row in query.order_by(FinanceAccount.name.asc()).all()]
        elif kind == "orders":
            customer = _row(session, CustomerTable, filters.get("customer_id"))
            query = session.query(OrderTable).filter(OrderTable.archive.is_(False), or_(
                OrderTable.customers.any(CustomerTable.id == customer.id),
                ~OrderTable.customers.any() & (OrderTable.customer_name == customer.name)))
            if query_text:
                query = query.filter(or_(*(getattr(OrderTable, field).ilike(f"%{query_text}%")
                    for field in PAYMENT_ORDER_SEARCH_FIELDS)))
            page = max(int(filters.get("page") or 1), 1)
            page_size = min(max(int(filters.get("page_size") or 30), 1), 200)
            total = query.count()
            orders = query.order_by(OrderTable.create_date.desc(), OrderTable.uid.desc()).offset(
                (page - 1) * page_size).limit(page_size).all()
            return {"items": [_payment_order_option(row, customer) for row in orders],
                "total": total, "page": page, "page_size": page_size}
        elif kind == "packing-boxes":
            from data.DB import CargoTable
            from data.packing.PackingList import PackingListTable
            customer = _row(session, CustomerTable, filters.get("customer_id"))
            query = session.query(CargoTable, PackingListTable).join(
                PackingListTable, CargoTable.packing_list_uid == PackingListTable.uid).filter(
                or_(PackingListTable.customer_id == customer.id, PackingListTable.customer_id.is_(None)),
                PackingListTable.archive.is_(False), CargoTable.archive.is_(False))
            if query_text:
                query = query.filter(or_(PackingListTable.list_number.ilike(f"%{query_text}%"),
                    CargoTable.transfer_id.ilike(f"%{query_text}%"), CargoTable.item_name.ilike(f"%{query_text}%"),
                    CargoTable.uid.ilike(f"%{query_text}%")))
            if filters.get("packing_list_uid"):
                query = query.filter(PackingListTable.uid == filters["packing_list_uid"])
            page = max(int(filters.get("page") or 1), 1)
            page_size = min(max(int(filters.get("page_size") or 30), 1), 200)
            total = query.count()
            pairs = query.order_by(PackingListTable.create_date.desc(), PackingListTable.uid.desc(),
                CargoTable.box_number.asc(), CargoTable.uid.asc()).offset((page - 1) * page_size).limit(page_size).all()
            return {"items": [_payment_packing_box_option(box, packing) for box, packing in pairs],
                "total": total, "page": page, "page_size": page_size}
        else:
            raise LookupError("收付款选项不存在")
        return _page(rows, filters.get("page"), filters.get("page_size"))


def _allocation_type(payment=None, credit=None):
    if credit:
        return "customer_invoice" if credit.document_type == "customer_credit" else "vendor_bill"
    return {("incoming", "customer"): "customer_invoice", ("outgoing", "vendor"): "vendor_bill",
        ("outgoing", "customer"): "customer_credit", ("incoming", "vendor"): "vendor_credit"}[(payment.direction, payment.partner_type)]


def _allocate(session, actor, *, payment, credit, targets, allocation_date, reason):
    from services.finance_accounting_service import validate_accounting_date
    validate_accounting_date(session, allocation_date)
    source = payment or credit
    if source.status != "posted":
        raise FinanceConflictError("核销来源必须已生效")
    source_date = payment.payment_date if payment else credit.document_date
    if allocation_date < source_date or any(allocation_date < row.document_date for row, _ in targets):
        raise ValueError("核销日期不能早于收付款或账单日期")
    source_total = payment.amount if payment else credit.total_amount
    source_used = _payment_allocated(session, payment.id) if payment else _document_allocated(session, credit.id)
    if sum((amount for _, amount in targets), ZERO) > source_total - source_used:
        raise ValueError("核销金额超过可用余额")
    consumes_available_funds = credit is not None or payment.direction == _normal_direction(payment.partner_type)
    if consumes_available_funds and sum((amount for _, amount in targets), ZERO) > _refundable_balance(session, source.partner_type, source.partner_id):
        raise ValueError("往来余额已用于退款，可核销余额不足")
    if consumes_available_funds and any(sum((amount for _, amount in targets), ZERO) > _refundable_balance(session, source.partner_type, source.partner_id, as_of=point)
        for point in _balance_checkpoints(session, source.partner_type, source.partner_id, allocation_date)):
        raise ValueError("该核销日期会占用历史上已用于退款的余额")
    # Backdating a new allocation must also respect intermediate historical
    # balances, otherwise a later-reversed allocation could overdraw an as-of.
    source_history = session.query(FinanceAllocation).filter(
        FinanceAllocation.payment_id == payment.id if payment else or_(FinanceAllocation.credit_document_id == credit.id, FinanceAllocation.document_id == credit.id)).all()
    checkpoints = {allocation_date} | {r.allocation_date for r in source_history if r.allocation_date >= allocation_date}
    requested = sum((amount for _, amount in targets), ZERO)
    if any(sum((r.amount for r in source_history if _effective_allocation(r, point)), ZERO) + requested > source_total for point in checkpoints):
        raise ValueError("该核销日期会造成历史可用余额不足")
    source_before = payment_dict(session, payment) if payment else document_dict(session, credit)
    actor_id, actor_name = _actor(actor)
    rows = []
    for document, amount in targets:
        if (document.status != "posted" or document.document_type != _allocation_type(payment, credit)
            or document.partner_type != source.partner_type or document.partner_id != source.partner_id or document.currency != source.currency):
            raise ValueError("只能核销同一往来单位、币种和方向的已生效账单")
        if amount > document.total_amount - _document_allocated(session, document.id):
            raise ValueError(f"账单 {document.number} 可核销余额不足")
        history = session.query(FinanceAllocation).filter(or_(FinanceAllocation.document_id == document.id, FinanceAllocation.credit_document_id == document.id)).all()
        points = {allocation_date} | {r.allocation_date for r in history if r.allocation_date >= allocation_date}
        if any(sum((r.amount for r in history if _effective_allocation(r, point)), ZERO) + amount > document.total_amount for point in points):
            raise ValueError(f"账单 {document.number} 在该日期的历史余额不足")
        before = document_dict(session, document)
        row = FinanceAllocation(payment_id=payment.id if payment else None, credit_document_id=credit.id if credit else None,
            document_id=document.id, document_number=document.number, amount=amount, status="active", version=1,
            allocation_date=allocation_date, reason=reason, created_by_id=actor_id, created_by_name=actor_name, created_at=_now())
        session.add(row)
        _touch(document)
        session.flush()
        result = _allocation_dict(session, row)
        _audit(session, actor, "finance_allocation", row.id, "create", after=result, reason=reason)
        _audit(session, actor, "finance_document", document.id, "allocate", before, document_dict(session, document), reason)
        rows.append(result)
    _touch(source)
    session.flush()
    source_after = payment_dict(session, payment) if payment else document_dict(session, credit)
    _audit(session, actor, "finance_payment" if payment else "finance_document", source.id, "allocate", source_before, source_after, reason)
    return rows


def create_allocations(body, actor):
    def change(session):
        payment_id, credit_id = body.get("payment_id"), body.get("credit_document_id")
        if bool(payment_id) == bool(credit_id):
            raise ValueError("必须且只能选择一笔收付款或贷项作为核销来源")
        source = _lock_financial_row(session, FinancePayment if payment_id else FinanceDocument, payment_id or credit_id)
        _version(source, body)
        if credit_id and session.get(FinanceOrderDocument, credit_id):
            raise FinanceConflictError("订单调减贷项请在订单应收中处理，不能直接转作其他账单核销")
        if credit_id and source.document_type not in {"customer_credit", "vendor_credit"}:
            raise ValueError("核销来源必须为贷项")
        values = body.get("allocations")
        if not isinstance(values, list) or not values or len(values) > 200:
            raise ValueError("请提供 1 至 200 条核销明细")
        prepared = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("核销明细无效")
            prepared.append((_id(value.get("document_id")), _decimal(value.get("amount"), "核销金额", positive=True)))
        if len({row_id for row_id, _ in prepared}) != len(prepared):
            raise ValueError("核销目标账单不能重复")
        targets = [(_row(session, FinanceDocument, row_id, locked=True), amount) for row_id, amount in sorted(prepared)]
        if any(session.get(FinanceOrderDocument, row.id) for row, _ in targets):
            raise FinanceConflictError("订单应收账单请使用核销订单，核对最新报价及可核销余额")
        result = _allocate(session, actor, payment=source if payment_id else None, credit=source if credit_id else None,
            targets=targets, allocation_date=_date(body.get("allocation_date") or _today(), "核销日期"),
            reason=_text(body.get("reason"), "核销备注", 2000))
        return {"items": result, "source": payment_dict(session, source) if payment_id else document_dict(session, source)}
    return _run(actor, "allocation.create", body, change)


def reverse_allocation(allocation_id, body, actor):
    def change(session):
        from services.finance_accounting_service import validate_accounting_date
        initial = _row(session, FinanceAllocation, allocation_id)
        source = _lock_financial_row(session, FinancePayment if initial.payment_id else FinanceDocument, initial.payment_id or initial.credit_document_id)
        document = _row(session, FinanceDocument, initial.document_id, locked=True)
        row = _row(session, FinanceAllocation, allocation_id, locked=True)
        _version(row, body)
        if row.status != "active":
            raise FinanceConflictError("该核销已经撤销")
        reason = _text(body.get("reason"), "撤销原因", 2000, required=True)
        reversal_date = _date(body.get("reversal_date") or _today(), "撤销日期")
        if reversal_date < row.allocation_date:
            raise ValueError("撤销日期不能早于核销日期")
        validate_accounting_date(session, reversal_date)
        before = _allocation_dict(session, row)
        document_before = document_dict(session, document)
        source_before = payment_dict(session, source) if row.payment_id else document_dict(session, source)
        row.status, row.reversed_at, row.reversal_date, row.reversal_reason = "reversed", _now(), reversal_date, reason
        _touch(row)
        _touch(document)
        _touch(source)
        session.flush()
        result = _allocation_dict(session, row)
        _audit(session, actor, "finance_allocation", row.id, "reverse", before, result, reason)
        _audit(session, actor, "finance_document", document.id, "unallocate", document_before, document_dict(session, document), reason)
        source_after = payment_dict(session, source) if row.payment_id else document_dict(session, source)
        _audit(session, actor, "finance_payment" if row.payment_id else "finance_document", source.id, "unallocate", source_before, source_after, reason)
        return result
    return _run(actor, f"allocation.{allocation_id}.reverse", body, change)


def list_allocations(actor, **filters):
    _actor(actor)
    with SessionFactory() as session:
        query = session.query(FinanceAllocation)
        for field in ("payment_id", "document_id", "credit_document_id", "status"):
            if filters.get(field):
                query = query.filter(getattr(FinanceAllocation, field) == filters[field])
        return _page([_allocation_dict(session, row) for row in query.order_by(FinanceAllocation.id.desc()).all()], filters.get("page"), filters.get("page_size"))


def _master_dict(row):
    fields = ("id", "name", "memo", "active", "version", "created_at", "updated_at")
    result = {field: getattr(row, field) for field in fields}
    for field in (("contact", "phone") if isinstance(row, FinanceVendor) else ("account_type", "account_number", "currency")):
        result[field] = getattr(row, field)
    return result


def _master_values(model, body, existing=None):
    def field(name, maximum, default="", required=False):
        return _text(body.get(name, getattr(existing, name) if existing else default), name, maximum, required)
    active = body.get("active", existing.active if existing else True)
    if not isinstance(active, bool):
        raise ValueError("启用状态必须为 true 或 false")
    result = dict(name=field("name", 256, required=True), memo=field("memo", 5000), active=active)
    if model is FinanceVendor:
        result.update(contact=field("contact", 128), phone=field("phone", 64))
    else:
        account_type = body.get("account_type", existing.account_type if existing else "bank")
        if account_type not in {"bank", "cash", "other"}:
            raise ValueError("资金账户类型无效")
        result.update(account_type=account_type, account_number=field("account_number", 128), currency=_currency(body))
    return result


def save_master(kind, body, actor, row_id=None):
    if kind not in {"vendors", "accounts"}:
        raise ValueError("基础资料类型无效")
    model = FinanceVendor if kind == "vendors" else FinanceAccount
    def change(session):
        row = _row(session, model, row_id, locked=True) if row_id else None
        before = _master_dict(row) if row else None
        if row:
            _version(row, body)
        values = _master_values(model, body, row)
        if row and model is FinanceAccount:
            from data.finance.accounting import FinanceBankTransaction, FinanceJournalLine
            used = (session.query(FinancePayment.id).filter(FinancePayment.account_id == row.id, FinancePayment.status.in_(["posted", "reversed"])).first()
                or session.query(FinanceJournalLine.id).filter_by(fund_account_id=row.id).first()
                or session.query(FinanceBankTransaction.id).filter_by(account_id=row.id).first())
            if used and any(values[field] != getattr(row, field) for field in ("account_type", "account_number", "currency")):
                raise FinanceConflictError("已有收付款、会计凭证或银行流水的账户不能修改账号、类型或币种，请新建账户")
        if row:
            for field, value in values.items():
                setattr(row, field, value)
            _touch(row)
        else:
            row = model(**values, version=1, created_at=_now(), updated_at=_now())
            session.add(row)
        session.flush()
        result = _master_dict(row)
        _audit(session, actor, "finance_vendor" if kind == "vendors" else "finance_account", row.id,
            "update" if before else "create", before, result, body.get("reason"))
        return result
    return _run(actor, f"{kind}.{row_id or 'new'}.save", body, change)


def _payment_effective(payment, as_of):
    return payment.payment_date <= as_of and (payment.status == "posted" or (payment.status == "reversed" and payment.reversal_date > as_of))


def _journal_account_balances(session, as_of):
    from data.finance.accounting import FinanceJournalEntry, FinanceJournalLine
    rows = session.query(FinanceJournalLine.fund_account_id,
        func.sum(FinanceJournalLine.debit - FinanceJournalLine.credit)).join(
        FinanceJournalEntry, FinanceJournalEntry.id == FinanceJournalLine.entry_id).filter(
        FinanceJournalEntry.status.in_(["posted", "reversed"]), FinanceJournalEntry.entry_date <= as_of,
        FinanceJournalLine.fund_account_id.isnot(None)).group_by(FinanceJournalLine.fund_account_id).all()
    return {account_id: _money(balance) for account_id, balance in rows}


def list_masters(kind, actor, **filters):
    _actor(actor)
    if kind not in {"vendors", "accounts"}:
        raise ValueError("基础资料类型无效")
    model = FinanceVendor if kind == "vendors" else FinanceAccount
    with SessionFactory() as session:
        query = session.query(model)
        if filters.get("q"):
            query = query.filter(model.name.ilike(f"%{filters['q']}%"))
        if str(filters.get("active", "")) in {"true", "1"}:
            query = query.filter(model.active.is_(True))
        items = [_master_dict(row) for row in query.order_by(model.id.desc()).all()]
        if kind == "accounts":
            balances = _journal_account_balances(session, _today())
            for item in items:
                item["balance"] = _str(balances.get(item["id"], ZERO))
        return _page(items, filters.get("page"), filters.get("page_size"))


def list_partners(actor, partner_type="customer", query="", include_inactive=False):
    _actor(actor)
    if partner_type not in {"customer", "vendor"}:
        raise ValueError("往来单位类型无效")
    model = CustomerTable if partner_type == "customer" else FinanceVendor
    with SessionFactory() as session:
        rows = session.query(model)
        if query:
            rows = rows.filter(model.name.ilike(f"%{query}%"))
        if partner_type == "vendor" and str(include_inactive).lower() not in {"1", "true"}:
            rows = rows.filter(FinanceVendor.active.is_(True))
        values = [{"id": row.id, "name": row.name, "partner_type": partner_type} for row in rows.order_by(model.name.asc()).all()]
        return {"items": values, "total": len(values)}


def dashboard(actor, as_of=None):
    from services.finance_legacy_service import reconciliation_count
    _actor(actor)
    as_of = _date(as_of or _today())
    with SessionFactory() as session:
        documents = session.query(FinanceDocument).order_by(FinanceDocument.id.desc()).all()
        payments = session.query(FinancePayment).order_by(FinancePayment.id.desc()).all()
        totals = {key: ZERO for key in ("receivable", "payable", "customer_credit", "vendor_credit", "customer_advances", "vendor_prepayments",
            "posted_receipts", "posted_payments", "account_balance", "overdue_receivable", "overdue_payable")}
        for document in documents:
            if document.status != "posted" or document.document_date > as_of:
                continue
            residual = document.total_amount - _document_allocated(session, document.id, as_of)
            key = {"customer_invoice": "receivable", "vendor_bill": "payable", "customer_credit": "customer_credit", "vendor_credit": "vendor_credit"}[document.document_type]
            totals[key] += residual
            if key in {"receivable", "payable"} and document.due_date < as_of:
                totals[f"overdue_{key}"] += residual
        balances = {}
        for document in documents:
            if document.status == "posted" and document.document_date <= as_of and document.document_type.endswith("credit"):
                key = (document.partner_type, document.partner_id)
                balances.setdefault(key, {"advance": ZERO, "credit": ZERO, "refund": ZERO})["credit"] += document.total_amount - _document_allocated(session, document.id, as_of)
        for payment in payments:
            if not _payment_effective(payment, as_of):
                continue
            if not payment.is_opening:
                totals["posted_receipts" if payment.direction == "incoming" else "posted_payments"] += payment.amount
            key = (payment.partner_type, payment.partner_id)
            bucket = "advance" if payment.direction == _normal_direction(payment.partner_type) else "refund"
            balances.setdefault(key, {"advance": ZERO, "credit": ZERO, "refund": ZERO})[bucket] += payment.amount - _payment_allocated(session, payment.id, as_of)
        totals["customer_credit"], totals["vendor_credit"] = ZERO, ZERO
        for (partner_type, _), balance in balances.items():
            net_advance = max(balance["advance"] - balance["refund"], ZERO)
            net_credit = max(balance["credit"] - max(balance["refund"] - balance["advance"], ZERO), ZERO)
            totals["customer_advances" if partner_type == "customer" else "vendor_prepayments"] += net_advance
            totals["customer_credit" if partner_type == "customer" else "vendor_credit"] += net_credit
        totals["account_balance"] = sum(_journal_account_balances(session, as_of).values(), ZERO)
        return {"as_of": as_of, **{key: _str(value) for key, value in totals.items()},
            "legacy_reconciliation_required": reconciliation_count(session, as_of),
            "draft_documents": sum(row.status == "draft" for row in documents), "draft_payments": sum(row.status == "draft" for row in payments),
            "pending_payments": sum(row.status == "pending" for row in payments),
            "recent_documents": [document_dict(session, row, include_lines=False, as_of=as_of) for row in documents[:8]],
            "recent_payments": [payment_dict(session, row, as_of=as_of) for row in payments[:8]],
            "scope": "independent_finance_ledger", "currency": "CNY"}


def aging(actor, partner_type="customer", as_of=None):
    _actor(actor)
    if partner_type not in {"customer", "vendor"}:
        raise ValueError("往来单位类型无效")
    as_of = _date(as_of or _today())
    fields = ("current", "days_1_30", "days_31_60", "days_61_90", "days_over_90", "total")
    totals = {field: ZERO for field in fields}
    with SessionFactory() as session:
        documents = session.query(FinanceDocument).filter_by(partner_type=partner_type,
            document_type="customer_invoice" if partner_type == "customer" else "vendor_bill", status="posted").filter(FinanceDocument.document_date <= as_of).order_by(FinanceDocument.due_date.asc()).all()
        partners = {}
        for document in documents:
            residual = document.total_amount - _document_allocated(session, document.id, as_of)
            if residual <= 0:
                continue
            days = (date.fromisoformat(as_of) - date.fromisoformat(document.due_date)).days
            bucket = "current" if days <= 0 else "days_1_30" if days <= 30 else "days_31_60" if days <= 60 else "days_61_90" if days <= 90 else "days_over_90"
            partner = partners.setdefault(document.partner_id, {"partner_id": document.partner_id, "partner_name": document.partner_name,
                **{field: ZERO for field in fields}, "documents": []})
            partner[bucket] += residual
            partner["total"] += residual
            totals[bucket] += residual
            totals["total"] += residual
            partner["documents"].append({**document_dict(session, document, include_lines=False, as_of=as_of), "overdue_days": max(days, 0), "bucket": bucket})
        return {"as_of": as_of, "partner_type": partner_type, "totals": {key: _str(value) for key, value in totals.items()},
            "items": [{**partner, **{field: _str(partner[field]) for field in fields}} for partner in partners.values()]}


def history(kind, row_id, actor, page=1, page_size=50):
    from utils.audit import load_audit_logs
    # Authorize and verify existence before exposing any audit snapshot.
    if kind == "documents":
        get_document(row_id, actor)
    elif kind == "payments":
        get_payment(row_id, actor)
    elif kind in {"vendors", "accounts"}:
        _actor(actor)
        with SessionFactory() as session:
            _row(session, FinanceVendor if kind == "vendors" else FinanceAccount, row_id)
    else:
        raise ValueError("单据类型无效")
    target_type = {"documents": "finance_document", "payments": "finance_payment", "vendors": "finance_vendor", "accounts": "finance_account"}[kind]
    result = load_audit_logs(page=page, page_size=page_size, target_type=target_type, target_id=str(row_id))
    return {**result, "history_complete": True, "notice": "本单据自创建起的修改、生效和核销记录与业务在同一事务保存。"}
