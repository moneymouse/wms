"""Reviewed current-day cutover of legacy order balances, never historical revenue."""
import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import or_

from data.database import SessionFactory
from data.DB import CargoTable, OrderTable, OrderQuoteVersionTable, OrderPriceAdjustmentTable, PaymentReceiptTable, PaymentReceiptItemTable
from data.finance.accounting import FinanceSettings
from data.finance.ledger import FinanceAllocation, FinanceDocument, FinancePayment
from data.finance.legacy import FinanceLegacyEvidence, FinanceLegacyLink
from services import finance_ledger_service as ledger
from services import receivable_service


NOTICE = "这是旧订单当前报价、货重及已审收款的切换日快照，不是历史总账。只迁核准净余额；旧收款不会再次入账。接入后订单和旧收款仍可操作，来源变化必须在接入记录中对账，系统不会自动重复记账。"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source(session, order_uid, *, locked=False):
    order_uid = ledger._text(order_uid, "旧订单UID", 32, required=True)
    query = session.query(OrderTable).filter_by(uid=order_uid)
    order = (query.populate_existing().with_for_update() if locked else query).first()
    if order is None:
        raise LookupError("旧订单不存在")
    blockers = []
    if order.archive:
        blockers.append("旧订单已归档，不能自动认定其账款已结清；请人工核准")
    customers = list(order.customers)
    customer = customers[0] if len(customers) == 1 else None
    if customer is None:
        blockers.append("旧订单必须明确关联一个客户，不能仅按客户名称推断")
    cargo_query = session.query(CargoTable).filter_by(target_order_uid=order_uid).order_by(CargoTable.uid.asc())
    cargos = (cargo_query.populate_existing().with_for_update() if locked else cargo_query).all()
    quote_query = session.query(OrderQuoteVersionTable).filter_by(order_uid=order_uid).order_by(OrderQuoteVersionTable.id.asc())
    quotes = (quote_query.populate_existing().with_for_update() if locked else quote_query).all()
    effective = [row for row in quotes if not row.archive and row.is_final and row.status in {"adopted", "approved"}]
    if len(effective) != 1:
        blockers.append("旧订单必须有且仅有一个有效报价")
    if any(row.status == "pending" and not row.archive for row in quotes):
        blockers.append("存在待审核报价，请先完成原报价审批")
    quote = effective[0] if len(effective) == 1 else None
    quote_data = None
    receivable = ledger.ZERO
    if quote is not None:
        pricing = receivable_service.quote_pricing_state(session, quote)
        receivable = ledger._money(pricing["receivable_amount"])
        quote_data = {"id": quote.id, "version_no": quote.version_no, "effective_date": quote.effective_date,
            "unit_price": ledger._str(receivable_service.quote_price(quote), ledger.FOUR), "surcharge": ledger._str(quote.surcharge),
            "weight": ledger._str(pricing["weight_snapshot"], Decimal("0.001")),
            "billing_weight": ledger._str(pricing["billing_weight"], Decimal("0.001")), "receivable_amount": ledger._str(receivable)}
    receipt_query = session.query(PaymentReceiptItemTable, PaymentReceiptTable).join(PaymentReceiptTable,
        PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id).filter(PaymentReceiptItemTable.order_uid == order_uid).order_by(PaymentReceiptItemTable.id.asc())
    receipt_rows = (receipt_query.populate_existing().with_for_update() if locked else receipt_query).all()
    received, waived, receipts = ledger.ZERO, ledger.ZERO, []
    for item, receipt in receipt_rows:
        receipts.append({"item_id": item.id, "receipt_id": receipt.id, "receipt_number": receipt.receipt_no,
            "customer_id": receipt.customer_id, "status": receipt.status, "settlement_status": receipt.settlement_status,
            "amount": ledger._str(item.amount), "settlement_difference": ledger._str(item.settlement_difference),
            "archived": bool(item.archive), "receipt_date": receipt.receipt_date, "review_date": receipt.review_date,
            "reviewer_name": receipt.reviewer_name})
        if item.archive:
            if receipt.status == "approved":
                blockers.append("旧订单存在已归档的已审收款明细，不能自动漏算历史资金")
            continue
        if customer and receipt.customer_id != customer.id:
            blockers.append("旧收款客户与订单当前客户不一致")
        if receipt.status == "pending":
            blockers.append("存在待审核收款，请先完成原收款审核")
        elif receipt.status == "approved":
            if receipt.settlement_status == "settled" and item.settlement_difference is None:
                blockers.append("已结清收款缺少减免快照，需要人工核准结清差额")
            received += ledger._money(item.amount)
            waived += ledger._money(item.settlement_difference)
        elif receipt.status != "rejected":
            blockers.append("存在无法识别状态的旧收款")
    adjustment_query = session.query(OrderPriceAdjustmentTable).filter_by(order_uid=order_uid).order_by(OrderPriceAdjustmentTable.id.asc())
    adjustment_rows = (adjustment_query.populate_existing().with_for_update() if locked else adjustment_query).all()
    adjustments = [{"id": row.id, "status": row.status, "direction": row.direction, "delta_amount": ledger._str(row.delta_amount), "archived": bool(row.archive)} for row in adjustment_rows]
    # Quote differences are already included in receivable_amount. Importing
    # the reviewed net balance transfers those tasks, never invents new cash.
    source = {"order_uid": order.uid, "order_number": order.order_id or order.uid, "order_archived": bool(order.archive),
        "customer_id": customer.id if customer else None, "customer_name": customer.name if customer else order.customer_name,
        "quote": quote_data, "receipts": receipts, "adjustments": adjustments,
        "cargos": [{"uid": row.uid, "weight": ledger._str(row.weight, Decimal("0.001")), "archived": bool(row.archive)} for row in cargos],
        "receivable_amount": ledger._str(receivable), "received_amount": ledger._str(received),
        "settlement_difference": ledger._str(waived), "signed_balance": ledger._str(receivable - received - waived)}
    digest = hashlib.sha256(_json(source).encode()).hexdigest()
    return source, digest, list(dict.fromkeys(blockers))


def _preview(session, order_uid, cutoff_date, *, locked=False):
    cutoff_date = ledger._date(cutoff_date or ledger._today(), "切换日期")
    source, digest, blockers = _source(session, order_uid, locked=locked)
    if source["quote"] and str(source["quote"].get("effective_date") or "")[:10] > cutoff_date:
        blockers.append("有效报价日期晚于切换日，不能提前迁入")
    if any(row["status"] == "approved" and (row["receipt_date"] or "") > cutoff_date for row in source["receipts"]):
        blockers.append("存在晚于切换日的收款日期，请先核准资金实际发生日期")
    if any(Decimal(source[key]) < 0 for key in ("receivable_amount", "received_amount", "settlement_difference")):
        blockers.append("旧来源存在负应收、负实收或负减免数据，请人工核准")
    settings = session.get(FinanceSettings, 1)
    if settings is None:
        blockers.append("请先完成新账簿建账设置")
    else:
        if cutoff_date != settings.opening_date:
            blockers.append("切换日期必须等于新账簿建账日期")
        if settings.opening_confirmed:
            blockers.append("期初余额已确认，不能继续接入旧订单期初余额")
    if cutoff_date != ledger._today():
        blockers.append("实时货重不能可靠还原历史余额；只支持今天的切换日，历史余额请人工核准录入期初")
    from data.finance.accounting import FinancePeriod
    period = session.query(FinancePeriod).filter(FinancePeriod.date_from <= cutoff_date, FinancePeriod.date_to >= cutoff_date).first()
    if period is None or period.status != "open":
        blockers.append("切换日没有开放的会计期间")
    existing = session.query(FinanceLegacyLink).filter_by(order_uid=order_uid).first()
    if existing and existing.status == "active":
        blockers.append("该订单已有接入基线，不能重复迁入；请查看接入记录并对账")
    from data.finance.order_settlement import FinanceOrderSettlement
    if session.get(FinanceOrderSettlement, order_uid):
        blockers.append("该订单已进入统一订单应收，不能再次迁入期初余额")
    balance = Decimal(source["signed_balance"])
    return {"order_uid": source["order_uid"], "order_number": source["order_number"], "customer_id": source["customer_id"],
        "customer_name": source["customer_name"], "cutoff_date": cutoff_date, "snapshot_at": ledger._now(), "source_hash": digest,
        "source": source, "import_kind": "receivable" if balance > 0 else "advance" if balance < 0 else "settled",
        "amount": ledger._str(abs(balance)), "can_import": not blockers, "blockers": blockers,
        "existing_link_id": existing.id if existing else None, "notice": NOTICE,
        "due_date_notice": "旧系统没有可靠到期日；默认以切换日作暂定到期日，若有原始凭据可在确认导入时填写真实到期日。"}


def preview(actor, order_uid, cutoff_date=None):
    ledger._actor(actor)
    with SessionFactory() as session:
        return _preview(session, order_uid, cutoff_date)


def list_orders(actor, **filters):
    ledger._actor(actor)
    with SessionFactory() as session:
        query = session.query(OrderTable).filter(OrderTable.archive.is_(False))
        if filters.get("q"):
            value = f"%{filters['q']}%"
            query = query.filter(or_(OrderTable.uid.ilike(value), OrderTable.order_id.ilike(value), OrderTable.customer_name.ilike(value)))
        page, size = max(int(filters.get("p") or 1), 1), min(max(int(filters.get("s") or 20), 1), 200)
        total = query.count()
        rows = query.order_by(OrderTable.create_date.desc(), OrderTable.uid.desc()).offset((page-1)*size).limit(size).all()
        return {"items": [{"order_uid": row.uid, "order_number": row.order_id or row.uid, "customer_name": row.customer_name} for row in rows], "total": total, "page": page, "page_size": size}


def _link_dict(session, row):
    fields = ("id", "order_uid", "order_number", "customer_id", "customer_name", "cutoff_date", "import_kind", "document_id", "payment_id",
        "source_hash", "version", "imported_at", "last_reconciled_at", "created_by_id", "created_by_name", "reason", "revoked_at", "revoke_reason")
    result = {field: getattr(row, field) for field in fields}
    result["amount"] = ledger._str(row.amount)
    baseline = json.loads(row.source_snapshot)
    result["baseline"] = baseline
    try:
        current, digest, blockers = _source(session, row.order_uid)
        unavailable = bool(blockers)
    except LookupError:
        current, digest, blockers, unavailable = None, None, ["源订单已删除，原财务基线和凭证仍保留，需要人工核对"], True
    evidence = session.query(FinanceLegacyEvidence).filter_by(link_id=row.id).all()
    proof_issues = []
    unreviewed_credit_ids = []
    required_documents = []
    evidence_document_ids = {proof.document_id for proof in evidence if proof.document_id}
    document_origins = {row.document_id} if row.document_id else set()
    if row.payment_id:
        origin = session.get(FinancePayment, row.payment_id)
        if origin is None or origin.status != "posted":
            unavailable = True
            blockers.append("接入生成的期初预收已冲销或失效，必须人工核准期初更正；不能用本期普通收款冒充恢复期初")
    if row.document_id:
        origin = session.get(FinanceDocument, row.document_id)
        if origin is None or origin.status != "posted":
            unavailable = True
            blockers.append("接入生成的期初账单已失效，必须人工核准期初更正")
    for proof in evidence:
        model, key = (FinanceDocument, proof.document_id) if proof.document_id else (FinancePayment, proof.payment_id)
        target = session.get(model, key)
        snapshot = json.loads(proof.snapshot)
        if target is None or target.status != snapshot.get("status"):
            proof_issues.append(f"已关联的新账簿{'账单' if proof.document_id else '收付款'} #{key} 已冲销或失效，请补齐匹配的新凭证后重新对账")
        if proof.document_id:
            document_origins.add(proof.document_id)
    for credit in session.query(FinanceDocument).filter(FinanceDocument.original_document_id.in_(document_origins), FinanceDocument.status == "posted").all():
        if credit.id not in evidence_document_ids:
            unreviewed_credit_ids.append(credit.id)
            required_documents.append({"id": credit.id, "number": credit.number, "amount": ledger._str(credit.total_amount)})
            proof_issues.append(f"对账依据账单新增贷项 {credit.number}（-{ledger._str(credit.total_amount)} CNY），本次对账必须包含此贷项")
    blockers += proof_issues
    required_doc, required_cash = _required_effects(session, row, current) if current else (None, None)
    result.update(current_source_hash=digest, drift=digest != row.source_hash or bool(proof_issues) or unavailable,
        status="source_unavailable" if unavailable else "reconciliation_required" if digest != row.source_hash or proof_issues else "current",
        current_preview={"source": current, "source_hash": digest, "blockers": blockers},
        delta={key: ledger._str(Decimal(current[key]) - Decimal(baseline[key])) for key in ("receivable_amount", "received_amount", "settlement_difference", "signed_balance")} if current else None,
        required_document_ids=unreviewed_credit_ids,
        required_documents=required_documents, required_document_amount=ledger._str(required_doc) if required_doc is not None else None,
        required_payment_amount=ledger._str(required_cash) if required_cash is not None else None,
        evidence=[{"document_id": proof.document_id, "payment_id": proof.payment_id, "effect_amount": ledger._str(proof.effect_amount), "snapshot": json.loads(proof.snapshot)} for proof in evidence], notice=NOTICE)
    revoke_blockers = _revoke_blockers(session, row)
    result.update(link_status=row.status, can_revoke=not revoke_blockers, revoke_blockers=revoke_blockers)
    if row.status == "revoked":
        result.update(status="revoked", drift=False, required_document_ids=[], required_documents=[])
    return result


def _revoke_blockers(session, row):
    from data.finance.accounting import FinancePeriod
    blockers = []
    from data.finance.order_settlement import FinanceOrderSettlement
    if session.get(FinanceOrderSettlement, row.order_uid):
        blockers.append("该订单已由统一订单应收接管，不能撤销其旧账基线")
    if row.status != "active":
        blockers.append("此接入已撤销")
    settings = session.get(FinanceSettings, 1)
    if settings is None or settings.opening_confirmed:
        blockers.append("期初已确认或建账设置缺失，不能撤销接入")
    period = session.query(FinancePeriod).filter(FinancePeriod.date_from <= row.cutoff_date, FinancePeriod.date_to >= row.cutoff_date).first()
    if period is None or period.status != "open":
        blockers.append("接入日期所在期间必须开放")
    if session.query(FinanceLegacyEvidence.id).filter_by(link_id=row.id).first():
        blockers.append("已有后续对账证据，不能撤回原切换基线")
    if row.document_id:
        document = session.get(FinanceDocument, row.document_id)
        if document is None or document.status != "posted" or document.reversed_by_id:
            blockers.append("原期初账单状态异常，需要人工核准重建期初")
        if session.query(FinanceAllocation.id).filter_by(document_id=row.document_id, status="active").first():
            blockers.append("原期初账单仍有核销，请先撤销核销")
        if session.query(FinanceDocument.id).filter_by(original_document_id=row.document_id, status="posted").first():
            blockers.append("原期初账单已有生效贷项，请通过对账处理变更")
    if row.payment_id:
        payment = session.get(FinancePayment, row.payment_id)
        if payment is None or payment.status != "posted":
            blockers.append("原期初预收状态异常，需要人工核准重建期初")
        if session.query(FinanceAllocation.id).filter_by(payment_id=row.payment_id, status="active").first():
            blockers.append("原期初预收仍有核销，请先撤销核销")
        if payment and ledger._refundable_balance(session, "customer", row.customer_id) < payment.amount:
            blockers.append("原期初预收已被退款占用，不能直接撤销")
    return blockers


def import_balance(body, actor):
    def change(session):
        if body.get("confirmed") is not True:
            raise ValueError("请明确确认：已核对净余额，历史收款不会再次入账，接入后旧来源变化需要对账")
        reason = ledger._text(body.get("reason"), "核准依据", 2000, required=True)
        order_uid = ledger._text(body.get("order_uid"), "旧订单UID", 32, required=True)
        result = _preview(session, order_uid, body.get("cutoff_date"), locked=True)
        if not result["can_import"]:
            raise ledger.FinanceConflictError("；".join(result["blockers"]))
        if body.get("source_hash") != result["source_hash"]:
            raise ledger.FinanceConflictError("旧订单余额或来源已变化，请重新预览并确认")
        transfer_adjustments(session, order_uid, actor, reason)
        result = _preview(session, order_uid, body.get("cutoff_date"), locked=True)
        actor_id, actor_name = ledger._actor(actor)
        now = ledger._now()
        row = session.query(FinanceLegacyLink).filter_by(order_uid=order_uid).with_for_update().first()
        before = _link_dict(session, row) if row else None
        if row is None:
            row = FinanceLegacyLink(order_uid=order_uid, version=1)
        else:
            if row.status != "revoked":
                raise ledger.FinanceConflictError("订单已有有效接入，不能重复迁入")
            ledger._touch(row)
        values = dict(order_number=result["order_number"], customer_id=result["customer_id"], customer_name=result["customer_name"],
            cutoff_date=result["cutoff_date"], import_kind=result["import_kind"], amount=Decimal(result["amount"]), source_hash=result["source_hash"],
            source_snapshot=_json(result["source"]), imported_at=now, last_reconciled_at=now, created_by_id=actor_id, created_by_name=actor_name,
            reason=reason, status="active", document_id=None, payment_id=None, revoked_at=None, revoke_reason=None)
        for key, value in values.items():
            setattr(row, key, value)
        memo = f"旧订单 {row.order_number} 核准净余额期初接入。已审收款及减免不重复入账。依据：{reason}"
        if row.import_kind == "receivable":
            values = ledger._document_values(session, {"document_type": "customer_invoice", "partner_id": row.customer_id,
                "is_opening": True, "document_date": row.cutoff_date, "due_date": body.get("due_date") or row.cutoff_date,
                "reference": row.order_number, "memo": memo})
            doc = FinanceDocument(**values, number=f"OPEN-{uuid.uuid4().hex[:16].upper()}", status="draft", version=1,
                created_by_id=actor_id, created_by_name=actor_name, created_at=now, updated_at=now)
            lines = ledger._lines(session, [{"description": "核准未收期初余额（净额迁移）", "unit_price": result["amount"], "quantity": 1, "tax_rate": 0, "order_uid": order_uid}])
            ledger._set_lines(doc, lines)
            session.add(doc)
            session.flush()
            draft = ledger.document_dict(session, doc)
            ledger._audit(session, actor, "finance_document", doc.id, "create", after=draft, reason=memo)
            ledger._post_document(session, doc, actor)
            ledger._audit(session, actor, "finance_document", doc.id, "post", draft, ledger.document_dict(session, doc), reason)
            row.document_id = doc.id
        elif row.import_kind == "advance":
            values = ledger._payment_values(session, {"direction": "incoming", "partner_type": "customer", "partner_id": row.customer_id,
                "account_id": body.get("account_id"), "payment_date": row.cutoff_date, "amount": result["amount"],
                "is_opening": True, "reference": row.order_number, "memo": memo})
            payment = FinancePayment(**values, number=f"OPENPAY-{uuid.uuid4().hex[:16].upper()}", status="draft", version=1,
                created_by_id=actor_id, created_by_name=actor_name, created_at=now, updated_at=now)
            session.add(payment)
            session.flush()
            draft = ledger.payment_dict(session, payment)
            ledger._audit(session, actor, "finance_payment", payment.id, "create", after=draft, reason=memo)
            payment.status, payment.posted_at = "posted", ledger._now()
            ledger._touch(payment)
            session.flush()
            from services.finance_accounting_service import post_payment
            post_payment(session, payment, actor)
            ledger._audit(session, actor, "finance_payment", payment.id, "post", draft, ledger.payment_dict(session, payment), reason)
            row.payment_id = payment.id
        session.add(row)
        session.flush()
        row.last_reconciled_at = ledger._now()
        serialized = _link_dict(session, row)
        ledger._audit(session, actor, "finance_legacy_link", row.id, "legacy_reimport" if before else "legacy_import", before=before, after=serialized, reason=reason)
        return serialized
    return ledger._run(actor, "legacy.import", body, change)


def transfer_adjustments(session, order_uid, actor, reason):
    """Retire a legacy task only with an explicit finance cutover/sync."""
    for row in session.query(OrderPriceAdjustmentTable).filter_by(order_uid=order_uid, status="pending", archive=False).with_for_update().all():
        before = {"status": row.status, "delta_amount": ledger._str(row.delta_amount), "order_uid": order_uid}
        row.status = "resolved"
        ledger._audit(session, actor, "order_price_adjustment", row.id, "legacy_adjustment_transfer", before,
            {**before, "status": "resolved", "resolution": "差价已纳入统一订单应收，未产生收付款"}, reason)
    session.flush()


def get_link(row_id, actor):
    ledger._actor(actor)
    with SessionFactory() as session:
        return _link_dict(session, ledger._row(session, FinanceLegacyLink, row_id))


def list_links(actor, **filters):
    ledger._actor(actor)
    with SessionFactory() as session:
        query = session.query(FinanceLegacyLink)
        if filters.get("q"):
            value = f"%{filters['q']}%"
            query = query.filter(or_(FinanceLegacyLink.order_uid.ilike(value), FinanceLegacyLink.order_number.ilike(value), FinanceLegacyLink.customer_name.ilike(value)))
        rows = [_link_dict(session, row) for row in query.order_by(FinanceLegacyLink.id.desc()).all()]
        if filters.get("status") == "drift":
            rows = [row for row in rows if row["status"] not in {"current", "revoked"}]
        elif filters.get("status") == "current":
            rows = [row for row in rows if row["status"] == "current"]
        elif filters.get("status") == "revoked":
            rows = [row for row in rows if row["status"] == "revoked"]
        return ledger._page(rows, filters.get("p"), filters.get("s"))


def reconciliation_count(session, as_of=None):
    """Closing-check hook; caller already holds the accounting settings lock."""
    query = session.query(FinanceLegacyLink).filter_by(status="active")
    if as_of:
        query = query.filter(FinanceLegacyLink.cutoff_date <= ledger._date(as_of))
    return sum(_link_dict(session, row)["status"] != "current" for row in query.all())


def _required_effects(session, link, current):
    baseline = json.loads(link.source_snapshot)
    doc = Decimal(current["receivable_amount"]) - Decimal(baseline["receivable_amount"]) - Decimal(current["settlement_difference"]) + Decimal(baseline["settlement_difference"])
    cash = Decimal(current["received_amount"]) - Decimal(baseline["received_amount"])
    for proof in session.query(FinanceLegacyEvidence).filter_by(link_id=link.id).all():
        target = session.get(FinanceDocument if proof.document_id else FinancePayment, proof.document_id or proof.payment_id)
        effect = ledger.ZERO
        if target is not None and target.status == "posted":
            effect = target.total_amount * (1 if target.document_type == "customer_invoice" else -1) if proof.document_id else target.amount * (1 if target.direction == "incoming" else -1)
        if proof.document_id:
            doc -= effect - proof.effect_amount
        else:
            cash -= effect - proof.effect_amount
    return doc, cash


def _evidence(session, link, body, current):
    def ids(key):
        values = body.get(key, [])
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("对账依据必须为不超过 100 个单据编号的列表")
        result = [ledger._id(value) for value in values]
        if len(result) != len(set(result)):
            raise ValueError("对账依据编号不能重复")
        return sorted(result)
    documents, payments, doc_effect, cash_effect = [], [], ledger.ZERO, ledger.ZERO
    for kind, values in (("document", ids("related_document_ids")), ("payment", ids("related_payment_ids"))):
        model = FinanceDocument if kind == "document" else FinancePayment
        for value in values:
            row = ledger._row(session, model, value, locked=True)
            if row.partner_type != "customer" or row.partner_id != link.customer_id or row.status != "posted" or row.is_opening:
                raise ValueError("对账依据必须是同一客户已生效的非期初单据")
            if not row.posted_at or row.posted_at <= link.last_reconciled_at:
                raise ValueError("只能关联上次核对之后生效的新单据，不能重复利用历史凭证")
            column = FinanceLegacyEvidence.document_id if kind == "document" else FinanceLegacyEvidence.payment_id
            if session.query(FinanceLegacyEvidence.id).filter(column == row.id).first():
                raise ledger.FinanceConflictError("该单据已经用于旧账接入对账，不能重复使用")
            if kind == "document":
                if row.document_type not in {"customer_invoice", "customer_credit"}:
                    raise ValueError("账单依据必须是客户账单或客户贷项")
                effect = row.total_amount * (1 if row.document_type == "customer_invoice" else -1)
                doc_effect += effect
                documents.append((row, effect))
            else:
                effect = row.amount * (1 if row.direction == "incoming" else -1)
                cash_effect += effect
                payments.append((row, effect))
    baseline = json.loads(link.source_snapshot)
    expected_doc = Decimal(current["receivable_amount"]) - Decimal(baseline["receivable_amount"]) - Decimal(current["settlement_difference"]) + Decimal(baseline["settlement_difference"])
    expected_cash = Decimal(current["received_amount"]) - Decimal(baseline["received_amount"])
    prior_effects = []
    for proof in session.query(FinanceLegacyEvidence).filter_by(link_id=link.id).all():
        model, key = (FinanceDocument, proof.document_id) if proof.document_id else (FinancePayment, proof.payment_id)
        target = ledger._row(session, model, key, locked=True)
        if target.status == "posted":
            current_effect = target.total_amount * (1 if target.document_type == "customer_invoice" else -1) if proof.document_id else target.amount * (1 if target.direction == "incoming" else -1)
        else:
            current_effect = ledger.ZERO
        if proof.document_id:
            expected_doc -= current_effect - proof.effect_amount
        else:
            expected_cash -= current_effect - proof.effect_amount
        prior_effects.append((proof, target, current_effect))
    if doc_effect != expected_doc or cash_effect != expected_cash:
        raise ValueError(f"新账簿依据不匹配：账单净变化应为 {ledger._str(expected_doc)}，收款净变化应为 {ledger._str(expected_cash)} CNY")
    return documents, payments, prior_effects


def acknowledge(row_id, body, actor):
    def change(session):
        link = ledger._row(session, FinanceLegacyLink, row_id, locked=True)
        from data.finance.order_settlement import FinanceOrderSettlement
        if session.get(FinanceOrderSettlement, link.order_uid):
            raise ledger.FinanceConflictError("该订单已由统一订单应收管理，请在那里确认报价变化，避免重复对账")
        ledger._version(link, body)
        if link.status != "active":
            raise ledger.FinanceConflictError("已撤销的接入不能确认对账，请重新预览并接入")
        reason = ledger._text(body.get("reason"), "对账依据说明", 2000, required=True)
        source, digest, blockers = _source(session, link.order_uid, locked=True)
        if blockers:
            raise ledger.FinanceConflictError("；".join(blockers))
        if source["customer_id"] != link.customer_id:
            raise ledger.FinanceConflictError("旧订单客户已变化，不能把另一客户金额直接覆盖原基线")
        if body.get("source_hash") != digest:
            raise ledger.FinanceConflictError("来源在核对期间已变化，请刷新差异后重新确认")
        before = _link_dict(session, link)
        if before["status"] == "source_unavailable":
            raise ledger.FinanceConflictError("；".join(before["current_preview"]["blockers"]))
        if digest == link.source_hash and not before["drift"]:
            raise ledger.FinanceConflictError("当前来源与核对基线一致，无需重复确认")
        documents, payments, prior_effects = _evidence(session, link, body, source)
        if not set(before["required_document_ids"]).issubset({row.id for row, _ in documents}):
            raise ValueError("请把原对账依据新增的全部贷项纳入本次核对，不能只确认旧来源")
        for proof, target, effect in prior_effects:
            proof.effect_amount = effect
            proof.snapshot = _json(ledger.document_dict(session, target) if proof.document_id else ledger.payment_dict(session, target))
        for row, effect in documents:
            session.add(FinanceLegacyEvidence(link_id=link.id, document_id=row.id, effect_amount=effect,
                snapshot=_json(ledger.document_dict(session, row)), created_at=ledger._now()))
        for row, effect in payments:
            session.add(FinanceLegacyEvidence(link_id=link.id, payment_id=row.id, effect_amount=effect,
                snapshot=_json(ledger.payment_dict(session, row)), created_at=ledger._now()))
        link.source_hash, link.source_snapshot, link.last_reconciled_at = digest, _json(source), ledger._now()
        ledger._touch(link)
        session.flush()
        after = _link_dict(session, link)
        ledger._audit(session, actor, "finance_legacy_link", link.id, "legacy_reconcile", before, after, reason)
        return after
    return ledger._run(actor, f"legacy.{row_id}.acknowledge", body, change)


def revoke(row_id, body, actor):
    def change(session):
        from services.finance_accounting_service import validate_accounting_date
        link = ledger._row(session, FinanceLegacyLink, row_id, locked=True)
        ledger._version(link, body)
        reason = ledger._text(body.get("reason"), "撤销接入原因", 2000, required=True)
        blockers = _revoke_blockers(session, link)
        if blockers:
            raise ledger.FinanceConflictError("；".join(blockers))
        validate_accounting_date(session, link.cutoff_date)
        before = _link_dict(session, link)
        if link.document_id:
            document = ledger._row(session, FinanceDocument, link.document_id, locked=True)
            ledger._reverse_document(session, document.id, {"version": document.version, "document_date": link.cutoff_date, "reason": reason}, actor, allow_legacy=True)
        if link.payment_id:
            payment = ledger._row(session, FinancePayment, link.payment_id, locked=True)
            ledger._reverse_payment(session, payment.id, {"version": payment.version, "payment_date": link.cutoff_date, "reason": reason}, actor, allow_legacy=True)
        link.status, link.revoked_at, link.revoke_reason = "revoked", ledger._now(), reason
        ledger._touch(link)
        session.flush()
        result = _link_dict(session, link)
        ledger._audit(session, actor, "finance_legacy_link", link.id, "legacy_revoke", before, result, reason)
        return result
    return ledger._run(actor, f"legacy.{row_id}.revoke", body, change)


def history(row_id, actor, page=1, page_size=50):
    from utils.audit import load_audit_logs
    get_link(row_id, actor)
    return {**load_audit_logs(target_type="finance_legacy_link", target_id=str(row_id), page=page, page_size=page_size),
        "history_complete": True, "notice": "接入快照、核准依据和后续对账历史完整保存；未导入旧系统未知历史。"}
