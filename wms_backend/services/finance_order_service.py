"""Finance-owned order allocation; operational references never move money.

Live quotations are previewed on reads. Only an explicit financial operation
posts their difference, through immutable invoices/credit notes in one transaction.
"""
import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import or_
from data.DB import OrderTable
from data.finance.ledger import FinanceAllocation, FinanceDocument, FinanceDocumentLine, FinancePayment
from data.finance.legacy import FinanceLegacyLink, FinanceLegacyEvidence
from data.finance.order_settlement import FinanceOrderSettlement, FinanceOrderDocument
from services import finance_ledger_service as ledger
from services import finance_legacy_service as legacy


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _documents(session, order_uid, link=None):
    ids = [row.document_id for row in session.query(FinanceOrderDocument).filter_by(order_uid=order_uid)]
    if link and link.document_id and link.document_id not in ids:
        ids.append(link.document_id)
    return session.query(FinanceDocument).filter(FinanceDocument.id.in_(ids)).order_by(FinanceDocument.id).all() if ids else []


def _preview(session, order_uid, *, locked=False):
    source, _, blockers = legacy._source(session, order_uid, locked=locked)
    # Legacy difference tasks are not financial facts. Their amount is already
    # in the current quote; never add it a second time to an order receivable.
    blockers = [text for text in blockers if "未处理差价任务" not in text]
    state = session.get(FinanceOrderSettlement, order_uid)
    link = session.query(FinanceLegacyLink).filter_by(order_uid=order_uid, status="active").first()
    receipts_hash = _hash(source["receipts"])
    has_legacy_money = Decimal(source["received_amount"]) != 0 or Decimal(source["settlement_difference"]) != 0
    offset = Decimal(state.legacy_offset) if state else ledger.ZERO
    if not state and link and session.query(FinanceLegacyEvidence.id).filter_by(link_id=link.id).first():
        blockers.append("旧账已有人工对账凭据，请先核准其订单应收归属")
    if state:
        if state.customer_id != source["customer_id"]:
            blockers.append("订单客户已变化，请财务先核准原客户账款归属")
        if state.legacy_receipts_hash != receipts_hash:
            blockers.append("旧收款来源已变化，请先完成旧账对账，不能再次自动计算")
        if state.legacy_link_id and (not link or link.id != state.legacy_link_id):
            blockers.append("旧账接入基线已撤销或替换，请先核准订单应收")
    elif has_legacy_money:
        # A cutover blocker must not hide cash that was already received.
        offset = Decimal(source["received_amount"]) + Decimal(source["settlement_difference"])
        if not link:
            blockers.append("历史已审收款须先通过旧账净余额接入，避免重复计入资金和收入")
        else:
            baseline = json.loads(link.source_snapshot)
            if _hash(baseline["receipts"]) != receipts_hash:
                blockers.append("旧收款已变化，请先完成旧账对账")
            # Historical excess is already held as a customer opening advance;
            # it is not a second order-specific refund entitlement.
            offset = min(Decimal(baseline["receivable_amount"]),
                         Decimal(baseline["received_amount"]) + Decimal(baseline["settlement_difference"]))
    documents = _documents(session, order_uid, link)
    document_ids = [row.id for row in documents]
    unknown = session.query(FinanceDocument.id).outerjoin(FinanceDocumentLine).filter(
        or_(FinanceDocumentLine.order_uid == order_uid, FinanceDocument.original_document_id.in_(document_ids or [-1])),
        FinanceDocument.document_type.in_(["customer_invoice", "customer_credit"]),
        FinanceDocument.status == "posted", ~FinanceDocument.id.in_(document_ids or [-1])).first()
    if unknown:
        blockers.append("订单已有其他已入账账单，请先核准归属，不能重复生成应收")
    if any(row.status != "posted" or row.reversed_by_id for row in documents):
        blockers.append("关联应收账单状态已变化，请先核对原单据")
    allocations = session.query(FinanceAllocation).filter(FinanceAllocation.document_id.in_(document_ids or [-1])).order_by(FinanceAllocation.id).all()
    applied = ledger.ZERO
    for allocation in allocations:
        if allocation.status == "active" and allocation.payment_id:
            payment = session.get(FinancePayment, allocation.payment_id)
            if payment and payment.status == "posted":
                applied += allocation.amount * (1 if payment.direction == "incoming" else -1)
    desired = Decimal(source["receivable_amount"]) - offset
    recognized = sum((row.total_amount * (-1 if row.document_type == "customer_credit" else 1)
                      for row in documents if row.status == "posted"), ledger.ZERO)
    # Net-only migration cannot invent the original gross invoice necessary to
    # credit historical paid income. Keep that correction in reviewed cutover.
    if link and desired < 0:
        blockers.append("调减涉及旧账已收部分，请先通过旧账对账核准应退凭据")
    digest = _hash({"source": source, "legacy_offset": str(offset),
                    "link": [link.id, link.version, link.source_hash] if link else None,
                    "state_version": state.version if state else None,
                    "documents": [[row.id, row.version, row.status] for row in documents],
                    "allocations": [[row.id, row.version, row.status, str(row.amount)] for row in allocations]})
    signed = desired - applied
    return {"order_uid": order_uid, "order_number": source["order_number"],
            "customer_id": source["customer_id"], "customer_name": source["customer_name"],
            "receivable_amount": ledger._str(source["receivable_amount"]),
            "legacy_settled_amount": ledger._str(offset), "allocated_amount": ledger._str(applied),
            "receivable_balance": ledger._str(max(signed, ledger.ZERO)),
            "refundable_amount": ledger._str(max(-signed, ledger.ZERO)),
            "sync_delta": ledger._str(desired - recognized), "source_hash": digest,
            "can_allocate": not blockers, "blockers": list(dict.fromkeys(blockers)),
            "documents": [ledger.document_dict(session, row, include_lines=False) for row in documents],
            "source": source}


def list_orders(actor, **filters):
    ledger._actor(actor)
    with ledger.SessionFactory() as session:
        query = session.query(OrderTable).filter(OrderTable.archive.is_(False))
        if filters.get("partner_id"):
            from data.customer.Customer import CustomerTable
            query = query.filter(OrderTable.customers.any(CustomerTable.id == ledger._id(filters["partner_id"])))
        packing_references = None
        if filters.get("payment_id"):
            payment = ledger._row(session, FinancePayment, filters["payment_id"])
            if payment.partner_type != "customer":
                raise ValueError("仅客户收付款可以按装箱单查询订单")
            if filters.get("partner_id") and ledger._id(filters["partner_id"]) != payment.partner_id:
                raise ValueError("收付款与查询客户不一致")
            packing_references = ledger._payment_packing_order_references(session, payment)
            query = query.filter(OrderTable.uid.in_(packing_references["packing_order_uids"]))
        if filters.get("q"):
            text = f"%{filters['q']}%"
            query = query.filter(or_(OrderTable.uid.ilike(text), OrderTable.order_id.ilike(text), OrderTable.customer_name.ilike(text)))
        page, size = max(int(filters.get("p") or 1), 1), min(max(int(filters.get("s") or 20), 1), 200)
        total = query.count()
        orders = query.order_by(OrderTable.create_date.desc(), OrderTable.uid).offset((page-1)*size).limit(size).all()
        return {"items": [_preview(session, row.uid) for row in orders], "total": total, "page": page, "page_size": size,
                **(packing_references or {})}


def reconciliation_count(session, date_to):
    count = 0
    for state in session.query(FinanceOrderSettlement).filter(FinanceOrderSettlement.created_at < date_to + " 99"):
        try:
            current = _preview(session, state.order_uid)
            count += bool(current["blockers"]) or Decimal(current["sync_delta"]) != 0
        except LookupError:
            count += 1
    return count


def _new_document(session, state, preview, amount, document_date, actor, reason, original=None):
    actor_id, actor_name = ledger._actor(actor)
    kind = "customer_credit" if amount < 0 else "customer_invoice"
    amount = abs(amount)
    now = ledger._now()
    document = FinanceDocument(number=f"{ledger.PREFIX[kind]}-{uuid.uuid4().hex[:16].upper()}",
        document_type=kind, is_opening=False, partner_type="customer", partner_id=state.customer_id,
        partner_name=preview["customer_name"], document_date=document_date, due_date=document_date,
        currency="CNY", reference=state.order_number, memo=reason, status="draft", version=1,
        original_document_id=original.id if original else None,
        created_by_id=actor_id, created_by_name=actor_name, created_at=now, updated_at=now)
    ledger._set_lines(document, [FinanceDocumentLine(sequence=1, description="订单应收调减" if original else "订单应收确认",
        quantity=1, unit_price=amount, tax_rate=0, subtotal=amount, tax_amount=0, total_amount=amount,
        order_uid=state.order_uid, order_number=state.order_number)])
    session.add(document)
    session.flush()
    ledger._audit(session, actor, "finance_document", document.id, "create", after=ledger.document_dict(session, document), reason=reason)
    before = ledger.document_dict(session, document)
    ledger._post_document(session, document, actor, allow_order_adjustment=True)
    session.add(FinanceOrderDocument(document_id=document.id, order_uid=state.order_uid,
        source_hash=preview["source_hash"], source_snapshot=_json(preview["source"])))
    session.flush()
    ledger._audit(session, actor, "finance_document", document.id, "post", before, ledger.document_dict(session, document), reason)
    return document


def _net_credits(session, documents, document_date, actor, reason):
    invoices = [row for row in documents if row.document_type == "customer_invoice"]
    for credit in [row for row in documents if row.document_type == "customer_credit"]:
        remaining = credit.total_amount - ledger._document_allocated(session, credit.id)
        targets = []
        for invoice in invoices:
            amount = min(remaining, invoice.total_amount - ledger._document_allocated(session, invoice.id))
            if amount > 0:
                targets.append((invoice, amount))
                remaining -= amount
        if targets:
            ledger._allocate(session, actor, payment=None, credit=credit, targets=targets,
                             allocation_date=document_date, reason=reason)


def _sync(session, order_uid, source_hash, document_date, actor, reason):
    if document_date != ledger._today():
        raise ValueError("订单实时应收只能按今天的报价确认及核销，历史账款请使用已核准的账单")
    preview = _preview(session, order_uid, locked=True)
    if not source_hash or source_hash != preview["source_hash"]:
        raise ledger.FinanceConflictError("订单报价、余额或核销记录已变化，请刷新后重新确认")
    if preview["blockers"]:
        raise ledger.FinanceConflictError("；".join(preview["blockers"]))
    ledger._partner(session, "customer", preview["customer_id"], locked=True)
    state = session.get(FinanceOrderSettlement, order_uid)
    link = session.query(FinanceLegacyLink).filter_by(order_uid=order_uid, status="active").first()
    if state is None:
        state = FinanceOrderSettlement(order_uid=order_uid, order_number=preview["order_number"],
            customer_id=preview["customer_id"], legacy_link_id=link.id if link else None,
            legacy_offset=Decimal(preview["legacy_settled_amount"]), legacy_receipts_hash=_hash(preview["source"]["receipts"]),
            version=1, created_at=ledger._now(), updated_at=ledger._now())
        session.add(state)
        session.flush()
        if link and link.document_id:
            session.add(FinanceOrderDocument(document_id=link.document_id, order_uid=order_uid,
                source_hash=preview["source_hash"], source_snapshot=_json(preview["source"])))
            session.flush()
    delta = Decimal(preview["sync_delta"])
    documents = _documents(session, order_uid)
    if delta > 0:
        documents.append(_new_document(session, state, preview, delta, document_date, actor, reason))
    elif delta < 0:
        remaining = -delta
        for original in [row for row in reversed(documents) if row.document_type == "customer_invoice"]:
            credited = sum((row.total_amount for row in session.query(FinanceDocument).filter_by(
                original_document_id=original.id, status="posted")), ledger.ZERO)
            value = min(remaining, original.total_amount - credited)
            if value > 0:
                documents.append(_new_document(session, state, preview, -value, document_date, actor, reason, original))
                remaining -= value
        if remaining > 0:
            raise ledger.FinanceConflictError("调减金额超过已确认原账单，请先核准旧账应退凭据")
    _net_credits(session, documents, document_date, actor, reason)
    state.version += 1
    state.updated_at = ledger._now()
    if link:
        before_link = legacy._link_dict(session, link)
        previous_ids = {item["id"] for item in preview["documents"]}
        for document in documents:
            if document.id not in previous_ids:
                session.add(FinanceLegacyEvidence(link_id=link.id, document_id=document.id,
                    effect_amount=document.total_amount * (-1 if document.document_type == "customer_credit" else 1),
                    snapshot=_json(ledger.document_dict(session, document)), created_at=ledger._now()))
        legacy.transfer_adjustments(session, order_uid, actor, reason)
        current, digest, _ = legacy._source(session, order_uid)
        link.source_hash, link.source_snapshot, link.last_reconciled_at = digest, _json(current), ledger._now()
        ledger._touch(link)
        session.flush()
        ledger._audit(session, actor, "finance_legacy_link", link.id, "legacy_reconcile", before_link, legacy._link_dict(session, link), reason)
    session.flush()
    after = _preview(session, order_uid)
    ledger._audit(session, actor, "finance_order_settlement", order_uid, "order_receivable_sync", preview, after, reason)
    return after


def sync_order(order_uid, body, actor):
    day = ledger._date(body.get("document_date") or ledger._today())
    reason = ledger._text(body.get("reason"), "确认说明", 2000, required=True)
    return ledger._run(actor, f"order.{order_uid}.sync", body,
        lambda session: _sync(session, order_uid, body.get("source_hash"), day, actor, reason))


def allocate_orders(body, actor):
    def change(session):
        payment = ledger._lock_financial_row(session, FinancePayment, body.get("payment_id"))
        ledger._version(payment, body)
        if payment.partner_type != "customer" or payment.status != "posted":
            raise ValueError("仅已确认的客户收付款可以核销订单")
        day = ledger._date(body.get("allocation_date") or ledger._today(), "核销日期")
        reason = ledger._text(body.get("reason"), "核销说明", 2000) or "财务确认订单应收并核销"
        values = body.get("allocations")
        if not isinstance(values, list) or not values or len(values) > 200:
            raise ValueError("请选择 1 至 200 笔订单")
        prepared = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("核销明细无效")
            prepared.append((ledger._text(value.get("order_uid"), "订单", 32, required=True),
                ledger._decimal(value.get("amount"), "核销金额", positive=True), value.get("source_hash")))
        if len({uid for uid, _, _ in prepared}) != len(prepared):
            raise ValueError("核销订单不能重复")
        packing_only = body.get("packing_only", False)
        if not isinstance(packing_only, bool):
            raise ValueError("装箱单核销范围必须为 true 或 false")
        if packing_only:
            associated = ledger._payment_packing_order_references(session, payment)["packing_order_uids"]
            if any(uid not in associated for uid, _, _ in prepared):
                raise ledger.FinanceConflictError("备注箱子的订单归属已变化，请刷新后重新选择核销订单")
        targets = []
        for uid, amount, digest in sorted(prepared):
            preview = _preview(session, uid, locked=True)
            if preview["customer_id"] != payment.partner_id:
                raise ValueError("只能核销同一客户的订单")
            limit = Decimal(preview["receivable_balance"] if payment.direction == "incoming" else preview["refundable_amount"])
            if amount > limit:
                raise ValueError("核销金额超过订单当前可核销余额")
            _sync(session, uid, digest, day, actor, reason)
            remaining = amount
            kind = "customer_invoice" if payment.direction == "incoming" else "customer_credit"
            for document in _documents(session, uid):
                if document.document_type != kind:
                    continue
                value = min(remaining, document.total_amount - ledger._document_allocated(session, document.id))
                if value > 0:
                    targets.append((document, value))
                    remaining -= value
            if remaining:
                raise ledger.FinanceConflictError("订单余额与已入账账单不一致，请先核准应收")
        result = ledger._allocate(session, actor, payment=payment, credit=None, targets=targets, allocation_date=day, reason=reason)
        return {"items": result, "source": ledger.payment_dict(session, payment)}
    return ledger._run(actor, "order.allocation.create", body, change)
