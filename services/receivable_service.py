"""Quotation, payment receipt and accounts-receivable domain services."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import time
from typing import Iterable, Optional

from sqlalchemy import func, or_

from Auth import get_payload_roles
from data.database import SessionFactory
from data.DB import (
    CargoTable,
    OrderQuoteVersionTable,
    OrderTable,
    PaymentReceiptItemTable,
    PaymentReceiptTable,
    SalesFollowupBonusRateTable,
)
from data.customer.Customer import CustomerTable


MONEY = Decimal("0.01")
UNIT_PRICE = Decimal("0.0001")
WEIGHT = Decimal("0.001")
PAYMENT_METHODS = {"cash", "bank_transfer", "wechat", "alipay", "other"}
EFFECTIVE_QUOTE_STATUSES = {"adopted", "approved"}


def decimal_value(value, precision=MONEY, field="amount") -> Decimal:
    try:
        result = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 格式不正确") from exc
    return result.quantize(precision, rounding=ROUND_HALF_UP)


def money(value) -> Decimal:
    return decimal_value(value, MONEY)


def unit_price(value) -> Decimal:
    return decimal_value(value, UNIT_PRICE, "unit_price")


def weight(value) -> Decimal:
    return decimal_value(value, WEIGHT, "weight")


def decimal_json(value, precision=MONEY) -> float:
    return float(decimal_value(value, precision))


def current_order_weight(session, order_uid: str) -> Decimal:
    total = (
        session.query(func.coalesce(func.sum(CargoTable.weight), 0))
        .filter(
            CargoTable.target_order_uid == order_uid,
            CargoTable.archive == False,  # noqa: E712
        )
        .scalar()
    )
    return weight(total)


def calculate_receivable(weight_snapshot, price, surcharge) -> Decimal:
    return money(weight(weight_snapshot) * unit_price(price) + money(surcharge))


def get_current_quote(session, order_uid: str) -> Optional[OrderQuoteVersionTable]:
    return (
        session.query(OrderQuoteVersionTable)
        .filter(
            OrderQuoteVersionTable.order_uid == order_uid,
            OrderQuoteVersionTable.is_final == True,  # noqa: E712
            OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
        )
        .order_by(OrderQuoteVersionTable.version_no.desc())
        .first()
    )


def quote_is_fresh(session, quote: Optional[OrderQuoteVersionTable]) -> bool:
    if quote is None:
        return False
    return current_order_weight(session, quote.order_uid) == weight(quote.weight_snapshot)


def quote_to_dict(session, quote: OrderQuoteVersionTable) -> dict:
    current_weight = current_order_weight(session, quote.order_uid)
    snapshot = weight(quote.weight_snapshot)
    is_effective = bool(
        quote.is_final
        and quote.status in EFFECTIVE_QUOTE_STATUSES
        and current_weight == snapshot
    )
    if quote.status == "pending":
        validity_status = "pending"
    elif quote.status == "rejected":
        validity_status = "rejected"
    elif not quote.is_final:
        validity_status = "superseded"
    elif current_weight != snapshot:
        validity_status = "stale"
    else:
        validity_status = "effective"

    p = quote.unit_price
    if p is None or (money(p) == 0 and money(quote.quoted_price) != 0):
        p = quote.quoted_price
    return {
        "id": quote.id,
        "order_uid": quote.order_uid,
        "version_no": quote.version_no,
        "transportation_mode_id": quote.transportation_mode_id,
        "transportation_name": quote.transportation_name,
        "channel_cost": float(quote.channel_cost or 0),
        "min_price": float(quote.min_price or 0),
        "unit_price": decimal_json(p, UNIT_PRICE),
        "quoted_price": decimal_json(p, UNIT_PRICE),
        "surcharge": decimal_json(quote.surcharge),
        "weight_snapshot": decimal_json(snapshot, WEIGHT),
        "current_weight": decimal_json(current_weight, WEIGHT),
        "receivable_amount": decimal_json(quote.receivable_amount),
        "status": quote.status,
        "is_final": bool(quote.is_final),
        "is_effective": is_effective,
        "validity_status": validity_status,
        "quote_remark": quote.quote_remark,
        "review_remark": quote.review_remark,
        "quoter_id": quote.quoter_id,
        "quoter_name": quote.quoter_name,
        "reviewer_id": quote.reviewer_id,
        "reviewer_name": quote.reviewer_name,
        "create_date": quote.create_date,
        "review_date": quote.review_date,
        "effective_date": quote.effective_date,
    }


def get_order_quote_state(order_uid: str) -> dict:
    with SessionFactory() as session:
        quote = get_current_quote(session, order_uid)
        if quote is None:
            return {"order_uid": order_uid, "is_effective": False, "validity_status": "unquoted"}
        return quote_to_dict(session, quote)


def _allocation_totals(session, order_uid: str, exclude_receipt_id=None) -> dict:
    query = (
        session.query(PaymentReceiptTable.status, func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0))
        .join(PaymentReceiptItemTable, PaymentReceiptItemTable.receipt_id == PaymentReceiptTable.id)
        .filter(
            PaymentReceiptItemTable.order_uid == order_uid,
            PaymentReceiptTable.status.in_(["pending", "approved"]),
        )
    )
    if exclude_receipt_id is not None:
        query = query.filter(PaymentReceiptTable.id != exclude_receipt_id)
    rows = query.group_by(PaymentReceiptTable.status).all()
    totals = {"approved": Decimal("0.00"), "pending": Decimal("0.00")}
    for status, amount in rows:
        totals[status] = money(amount)
    return totals


def get_committed_receipt_amount(session, order_uid: str) -> Decimal:
    totals = _allocation_totals(session, order_uid)
    return money(totals["approved"] + totals["pending"])


def _customer_matches_order(order: OrderTable, customer: CustomerTable) -> bool:
    linked_ids = {item.id for item in order.customers}
    return customer.id in linked_ids or (
        not linked_ids and (order.customer_name or "").strip() == (customer.name or "").strip()
    )


def _operator(payload: dict) -> dict:
    return {
        "id": payload.get("user_id") or payload.get("id"),
        "name": payload.get("name") or payload.get("username") or payload.get("phone") or "",
        "roles": set(get_payload_roles(payload)),
    }


def list_receivable_orders(customer_id: int, operator_payload: dict, query_text="") -> list:
    operator = _operator(operator_payload)
    with SessionFactory() as session:
        customer = session.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
        if customer is None:
            raise ValueError("客户不存在")
        query = session.query(OrderTable).filter(OrderTable.archive == False)  # noqa: E712
        if query_text:
            like = f"%{query_text.strip()}%"
            query = query.filter(or_(OrderTable.order_id.ilike(like), OrderTable.customer_name.ilike(like)))
        orders = query.order_by(OrderTable.create_date.desc()).all()
        result = []
        for order in orders:
            if not _customer_matches_order(order, customer):
                continue
            quote = get_current_quote(session, order.uid)
            if quote is None or not quote_is_fresh(session, quote):
                continue
            if "admin" not in operator["roles"] and quote.quoter_id != operator["id"]:
                continue
            allocations = _allocation_totals(session, order.uid)
            receivable = money(quote.receivable_amount)
            available = money(receivable - allocations["approved"] - allocations["pending"])
            if available <= 0:
                continue
            result.append({
                "uid": order.uid,
                "order_id": order.order_id,
                "customer_id": customer.id,
                "customer_name": customer.name,
                "quoter_id": quote.quoter_id,
                "quoter_name": quote.quoter_name,
                "effective_date": quote.effective_date,
                "weight_snapshot": decimal_json(quote.weight_snapshot, WEIGHT),
                "receivable_amount": decimal_json(receivable),
                "approved_received": decimal_json(allocations["approved"]),
                "pending_amount": decimal_json(allocations["pending"]),
                "available_amount": decimal_json(available),
            })
        return result


def create_receipt(body: dict, operator_payload: dict) -> dict:
    operator = _operator(operator_payload)
    if not operator["id"]:
        raise ValueError("无法识别创建人")
    if not operator["roles"].intersection({"salesperson", "admin"}):
        raise PermissionError("无权创建收款单")

    try:
        customer_id = int(body.get("customer_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("请选择客户") from exc
    receipt_date = str(body.get("receipt_date") or "").strip()
    try:
        datetime.strptime(receipt_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("收款日期必须为 YYYY-MM-DD") from exc
    payment_method = str(body.get("payment_method") or "").strip()
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("付款方式无效")
    item_payloads = body.get("items") or []
    if not isinstance(item_payloads, list) or not item_payloads:
        raise ValueError("请至少选择一笔订单")
    order_uids = [str(item.get("order_uid") or "").strip() for item in item_payloads]
    if any(not uid for uid in order_uids) or len(set(order_uids)) != len(order_uids):
        raise ValueError("订单明细无效或重复")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionFactory() as session:
        customer = session.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
        if customer is None:
            raise ValueError("客户不存在")
        orders = (
            session.query(OrderTable)
            .filter(OrderTable.uid.in_(order_uids), OrderTable.archive == False)  # noqa: E712
            .with_for_update()
            .all()
        )
        order_map = {order.uid: order for order in orders}
        if len(order_map) != len(order_uids):
            raise ValueError("部分订单不存在或已归档")

        prepared = []
        for item in item_payloads:
            order = order_map[item["order_uid"]]
            if not _customer_matches_order(order, customer):
                raise ValueError(f"订单 {order.order_id or order.uid} 不属于所选客户")
            quote = get_current_quote(session, order.uid)
            if quote is None:
                raise ValueError(f"订单 {order.order_id or order.uid} 尚无有效报价")
            if not quote_is_fresh(session, quote):
                raise ValueError(f"订单 {order.order_id or order.uid} 重量已变更，请重新报价")
            if "admin" not in operator["roles"] and quote.quoter_id != operator["id"]:
                raise PermissionError(f"订单 {order.order_id or order.uid} 不属于你的跟单范围")
            amount = money(item.get("amount"))
            if amount <= 0:
                raise ValueError(f"订单 {order.order_id or order.uid} 的本次收款必须大于 0")
            allocations = _allocation_totals(session, order.uid)
            receivable = money(quote.receivable_amount)
            available = money(receivable - allocations["approved"] - allocations["pending"])
            if amount > available:
                raise ValueError(
                    f"订单 {order.order_id or order.uid} 最多可收 {available:.2f} CNY"
                )
            prepared.append((order, receivable, allocations, available, amount))

        receipt = PaymentReceiptTable(
            customer_id=customer.id,
            customer_name=customer.name,
            receipt_date=receipt_date,
            payment_method=payment_method,
            remark=(body.get("remark") or "").strip() or None,
            status="pending",
            creator_id=operator["id"],
            creator_name=operator["name"],
            create_date=now,
            update_date=now,
        )
        session.add(receipt)
        session.flush()
        receipt.receipt_no = f"RCPT-{receipt_date.replace('-', '')}-{receipt.id:06d}"
        for order, receivable, allocations, available, amount in prepared:
            session.add(PaymentReceiptItemTable(
                receipt_id=receipt.id,
                order_uid=order.uid,
                order_id=order.order_id or order.uid,
                receivable_snapshot=receivable,
                received_before=allocations["approved"],
                amount=amount,
                remaining_after=money(available - amount),
            ))
        session.commit()
        return get_receipt_detail(receipt.id, operator_payload, session=session)


def _receipt_items(session, receipt_id: int) -> list:
    rows = (
        session.query(PaymentReceiptItemTable)
        .filter(PaymentReceiptItemTable.receipt_id == receipt_id)
        .order_by(PaymentReceiptItemTable.id.asc())
        .all()
    )
    return [{
        "id": row.id,
        "order_uid": row.order_uid,
        "order_id": row.order_id,
        "receivable_snapshot": decimal_json(row.receivable_snapshot),
        "received_before": decimal_json(row.received_before),
        "amount": decimal_json(row.amount),
        "remaining_after": decimal_json(row.remaining_after),
    } for row in rows]


def _receipt_dict(session, receipt: PaymentReceiptTable, include_items=False) -> dict:
    data = {
        "id": receipt.id,
        "receipt_no": receipt.receipt_no,
        "customer_id": receipt.customer_id,
        "customer_name": receipt.customer_name,
        "receipt_date": receipt.receipt_date,
        "payment_method": receipt.payment_method,
        "remark": receipt.remark,
        "status": receipt.status,
        "creator_id": receipt.creator_id,
        "creator_name": receipt.creator_name,
        "reviewer_id": receipt.reviewer_id,
        "reviewer_name": receipt.reviewer_name,
        "review_remark": receipt.review_remark,
        "review_date": receipt.review_date,
        "create_date": receipt.create_date,
        "update_date": receipt.update_date,
    }
    if include_items:
        data["items"] = _receipt_items(session, receipt.id)
        data["total_amount"] = decimal_json(sum((money(row["amount"]) for row in data["items"]), Decimal("0")))
    return data


def get_receipt_detail(receipt_id: int, operator_payload: dict, session=None) -> dict:
    owns_session = session is None
    session = session or SessionFactory()
    try:
        operator = _operator(operator_payload)
        receipt = session.query(PaymentReceiptTable).filter(PaymentReceiptTable.id == receipt_id).first()
        if receipt is None:
            raise LookupError("收款单不存在")
        if not operator["roles"].intersection({"admin", "finance"}) and receipt.creator_id != operator["id"]:
            raise PermissionError("无权查看该收款单")
        return _receipt_dict(session, receipt, include_items=True)
    finally:
        if owns_session:
            session.close()


def list_receipts(operator_payload: dict, status=None, page=1, page_size=20, query_text="") -> dict:
    operator = _operator(operator_payload)
    with SessionFactory() as session:
        query = session.query(PaymentReceiptTable)
        if not operator["roles"].intersection({"admin", "finance"}):
            query = query.filter(PaymentReceiptTable.creator_id == operator["id"])
        if status:
            query = query.filter(PaymentReceiptTable.status == status)
        if query_text:
            like = f"%{query_text.strip()}%"
            query = query.filter(or_(PaymentReceiptTable.receipt_no.ilike(like), PaymentReceiptTable.customer_name.ilike(like)))
        total = query.count()
        rows = (
            query.order_by(PaymentReceiptTable.create_date.desc(), PaymentReceiptTable.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = []
        for row in rows:
            item = _receipt_dict(session, row, include_items=True)
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}


def review_receipt(receipt_id: int, action: str, review_remark: str, operator_payload: dict) -> dict:
    operator = _operator(operator_payload)
    if not operator["roles"].intersection({"admin", "finance"}):
        raise PermissionError("无权审核收款单")
    if action not in {"approve", "reject"}:
        raise ValueError("action 必须为 approve 或 reject")
    if action == "reject" and not (review_remark or "").strip():
        raise ValueError("驳回时必须填写审核意见")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionFactory() as session:
        receipt = (
            session.query(PaymentReceiptTable)
            .filter(PaymentReceiptTable.id == receipt_id)
            .with_for_update()
            .first()
        )
        if receipt is None:
            raise LookupError("收款单不存在")
        if receipt.creator_id == operator["id"]:
            raise PermissionError("创建人不能审核自己的收款单")
        if receipt.status != "pending":
            raise ValueError("该收款单已经审核")
        if action == "approve":
            items = session.query(PaymentReceiptItemTable).filter_by(receipt_id=receipt.id).all()
            for item in items:
                quote = get_current_quote(session, item.order_uid)
                if quote is None or not quote_is_fresh(session, quote):
                    raise ValueError(f"订单 {item.order_id} 报价已失效，请驳回后重新登记")
                if money(quote.receivable_amount) != money(item.receivable_snapshot):
                    raise ValueError(f"订单 {item.order_id} 应收已变化，请驳回后重新登记")
                allocations = _allocation_totals(session, item.order_uid, exclude_receipt_id=receipt.id)
                available = money(money(quote.receivable_amount) - allocations["approved"] - allocations["pending"])
                if money(item.amount) > available:
                    raise ValueError(f"订单 {item.order_id} 可收余额不足，请驳回后重新登记")
        receipt.status = "approved" if action == "approve" else "rejected"
        receipt.reviewer_id = operator["id"]
        receipt.reviewer_name = operator["name"]
        receipt.review_remark = (review_remark or "").strip() or None
        receipt.review_date = now
        receipt.update_date = now
        session.commit()
        return _receipt_dict(session, receipt, include_items=True)


def accounts_receivable_ledger(
    as_of: str,
    page=1,
    page_size=20,
    customer_id=None,
    owner_id=None,
    settlement_status=None,
    query_text="",
) -> dict:
    try:
        datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("as_of 必须为 YYYY-MM-DD") from exc
    cutoff = f"{as_of} 23:59:59"
    with SessionFactory() as session:
        quote_rows = (
            session.query(OrderQuoteVersionTable)
            .filter(
                OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
                OrderQuoteVersionTable.effective_date.isnot(None),
                OrderQuoteVersionTable.effective_date <= cutoff,
            )
            .order_by(
                OrderQuoteVersionTable.order_uid.asc(),
                OrderQuoteVersionTable.effective_date.desc(),
                OrderQuoteVersionTable.version_no.desc(),
            )
            .all()
        )
        latest_quotes = {}
        for quote in quote_rows:
            latest_quotes.setdefault(quote.order_uid, quote)

        approved_rows = (
            session.query(PaymentReceiptItemTable.order_uid, func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0))
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(PaymentReceiptTable.status == "approved", PaymentReceiptTable.review_date <= cutoff)
            .group_by(PaymentReceiptItemTable.order_uid)
            .all()
        )
        approved_map = {uid: money(amount) for uid, amount in approved_rows}
        pending_rows = (
            session.query(PaymentReceiptItemTable.order_uid, func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0))
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(
                PaymentReceiptTable.create_date <= cutoff,
                or_(
                    PaymentReceiptTable.status == "pending",
                    PaymentReceiptTable.review_date > cutoff,
                ),
            )
            .group_by(PaymentReceiptItemTable.order_uid)
            .all()
        )
        pending_map = {uid: money(amount) for uid, amount in pending_rows}
        orders = session.query(OrderTable).filter(OrderTable.uid.in_(latest_quotes.keys())).all() if latest_quotes else []
        rows = []
        for order in orders:
            quote = latest_quotes[order.uid]
            customer = order.customers[0] if order.customers else None
            if customer_id and (customer is None or customer.id != customer_id):
                continue
            if owner_id and quote.quoter_id != owner_id:
                continue
            if query_text:
                text = query_text.lower()
                if text not in (order.order_id or "").lower() and text not in (order.customer_name or "").lower():
                    continue
            receivable = money(quote.receivable_amount)
            received = approved_map.get(order.uid, Decimal("0.00"))
            outstanding = money(max(receivable - received, Decimal("0.00")))
            status = "paid" if outstanding == 0 else ("partial" if received > 0 else "unpaid")
            if settlement_status and settlement_status != status:
                continue
            current_quote = get_current_quote(session, order.uid)
            is_current_stale = bool(
                quote.is_final and current_quote is not None and current_quote.id == quote.id and not quote_is_fresh(session, quote)
            )
            rows.append({
                "order_uid": order.uid,
                "order_id": order.order_id,
                "customer_id": customer.id if customer else None,
                "customer_name": customer.name if customer else order.customer_name,
                "quoter_id": quote.quoter_id,
                "quoter_name": quote.quoter_name,
                "effective_date": quote.effective_date,
                "weight_snapshot": decimal_json(quote.weight_snapshot, WEIGHT),
                "unit_price": decimal_json(quote.unit_price, UNIT_PRICE),
                "surcharge": decimal_json(quote.surcharge),
                "receivable_amount": decimal_json(receivable),
                "received_amount": decimal_json(received),
                "outstanding_amount": decimal_json(outstanding),
                "pending_amount": decimal_json(pending_map.get(order.uid, 0)),
                "settlement_status": status,
                "quote_stale": is_current_stale,
            })
        rows.sort(key=lambda item: (item["effective_date"] or "", item["order_id"] or ""), reverse=True)
        totals = {
            "receivable_amount": decimal_json(sum((money(row["receivable_amount"]) for row in rows), Decimal("0"))),
            "received_amount": decimal_json(sum((money(row["received_amount"]) for row in rows), Decimal("0"))),
            "outstanding_amount": decimal_json(sum((money(row["outstanding_amount"]) for row in rows), Decimal("0"))),
            "pending_amount": decimal_json(sum((money(row["pending_amount"]) for row in rows), Decimal("0"))),
            "order_count": len(rows),
        }
        total = len(rows)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "totals": totals, "total": total, "page": page, "page_size": page_size}


def list_sales_bonus_rates() -> list:
    with SessionFactory() as session:
        rows = session.query(SalesFollowupBonusRateTable).order_by(SalesFollowupBonusRateTable.effective_from.desc()).all()
        return [{
            "id": row.id,
            "rate_per_kg": decimal_json(row.rate_per_kg, UNIT_PRICE),
            "effective_from": row.effective_from,
            "remark": row.remark,
            "creator_id": row.creator_id,
            "creator_name": row.creator_name,
            "create_date": row.create_date,
        } for row in rows]


def create_sales_bonus_rate(body: dict, operator_payload: dict) -> dict:
    operator = _operator(operator_payload)
    rate = unit_price(body.get("rate_per_kg"))
    if rate < 0:
        raise ValueError("跟单奖金费率不能小于 0")
    effective_from = str(body.get("effective_from") or "").strip()
    try:
        datetime.strptime(effective_from, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("生效日期必须为 YYYY-MM-DD") from exc
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionFactory() as session:
        if session.query(SalesFollowupBonusRateTable).filter_by(effective_from=effective_from).first():
            raise ValueError("该生效日期已经存在费率版本")
        row = SalesFollowupBonusRateTable(
            rate_per_kg=rate,
            effective_from=effective_from,
            remark=(body.get("remark") or "").strip() or None,
            creator_id=operator["id"],
            creator_name=operator["name"],
            create_date=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {
            "id": row.id,
            "rate_per_kg": decimal_json(row.rate_per_kg, UNIT_PRICE),
            "effective_from": row.effective_from,
            "remark": row.remark,
            "creator_id": row.creator_id,
            "creator_name": row.creator_name,
            "create_date": row.create_date,
        }


def _rate_for_date(rates: Iterable[SalesFollowupBonusRateTable], effective_date: str):
    day = (effective_date or "")[:10]
    for rate in rates:
        if rate.effective_from <= day:
            return rate
    return None


def salesperson_followup_bonus(worker_id: int, month: str) -> dict:
    with SessionFactory() as session:
        rates = session.query(SalesFollowupBonusRateTable).order_by(SalesFollowupBonusRateTable.effective_from.desc()).all()
        quote_rows = (
            session.query(OrderQuoteVersionTable, OrderTable)
            .join(OrderTable, OrderTable.uid == OrderQuoteVersionTable.order_uid)
            .filter(
                OrderQuoteVersionTable.quoter_id == worker_id,
                OrderQuoteVersionTable.is_final == True,  # noqa: E712
                OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
                OrderQuoteVersionTable.effective_date.like(f"{month}-%"),
                OrderTable.archive == False,  # noqa: E712
            )
            .order_by(OrderQuoteVersionTable.effective_date.asc(), OrderTable.order_id.asc())
            .all()
        )
        orders = []
        total_weight = Decimal("0.000")
        estimated_bonus = Decimal("0.00")
        for quote, order in quote_rows:
            if not quote_is_fresh(session, quote):
                continue
            applied_rate = _rate_for_date(rates, quote.effective_date)
            rate_value = unit_price(applied_rate.rate_per_kg if applied_rate else 0)
            quote_weight = weight(quote.weight_snapshot)
            order_bonus = money(quote_weight * rate_value)
            orders.append({
                "order_uid": order.uid,
                "order_id": order.order_id,
                "effective_date": quote.effective_date,
                "weight": decimal_json(quote_weight, WEIGHT),
                "rate_per_kg": decimal_json(rate_value, UNIT_PRICE),
                "estimated_bonus": decimal_json(order_bonus),
            })
            total_weight += quote_weight
            estimated_bonus += order_bonus
        return {
            "order_count": len(orders),
            "total_weight": decimal_json(total_weight, WEIGHT),
            "estimated_bonus": decimal_json(estimated_bonus),
            "orders": orders,
            "rate_configured": all(row["rate_per_kg"] > 0 for row in orders) if orders else bool(rates),
        }
