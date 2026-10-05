"""Quotation, payment receipt and accounts-receivable domain services."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import time
from typing import Iterable, Optional

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased, selectinload

from Auth import get_payload_roles
from data.database import SessionFactory
from data.DB import (
    CargoTable,
    OrderPriceAdjustmentTable,
    OrderQuoteVersionTable,
    OrderTable,
    PaymentReceiptItemTable,
    PaymentReceiptTable,
    SalesFollowupBonusRateTable,
    TransportationModeTable,
    lock_order_for_update,
    order_has_receipt_history,
)
from data.customer.Customer import CustomerTable


MONEY = Decimal("0.01")
UNIT_PRICE = Decimal("0.0001")
WEIGHT = Decimal("0.001")
PAYMENT_METHODS = {"cash", "bank_transfer", "wechat", "alipay", "other"}
SETTLEMENT_STATUSES = {"settled", "unsettled"}
SETTLEMENT_THRESHOLD = Decimal("30.00")
EFFECTIVE_QUOTE_STATUSES = {"adopted", "approved"}


class QuoteConflictError(ValueError):
    """Raised when a new quote conflicts with committed receipt amounts."""



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


def billing_weight(value) -> Decimal:
    return weight(value).to_integral_value(rounding=ROUND_CEILING)


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


def current_order_billing_weight(session, order_uid: str) -> Decimal:
    cargo_weights = (
        session.query(CargoTable.weight)
        .filter(
            CargoTable.target_order_uid == order_uid,
            CargoTable.archive == False,  # noqa: E712
        )
        .all()
    )
    return weight(sum((billing_weight(row[0]) for row in cargo_weights), Decimal("0")))


def calculate_receivable(weight_snapshot, price, surcharge) -> Decimal:
    return money(billing_weight(weight_snapshot) * unit_price(price) + money(surcharge))


def quote_price(quote: OrderQuoteVersionTable):
    price = quote.unit_price
    if price is None or (money(price) == 0 and money(quote.quoted_price) != 0):
        price = quote.quoted_price
    return price


def quote_pricing_state(session, quote: OrderQuoteVersionTable) -> dict:
    """Return live pricing for active quotes; snapshots are audit-only fields."""
    current_weight = current_order_weight(session, quote.order_uid)
    current_billing_weight = current_order_billing_weight(session, quote.order_uid)
    stored_weight = weight(quote.weight_snapshot)
    stored_billing_weight = weight(
        quote.billing_weight_snapshot
        if quote.billing_weight_snapshot is not None
        else billing_weight(stored_weight)
    )
    uses_live_weight = (
        quote.status == "pending"
        or (quote.is_final and quote.status in EFFECTIVE_QUOTE_STATUSES)
    )
    effective_weight = current_weight if uses_live_weight else stored_weight
    effective_billing_weight = (
        current_billing_weight if uses_live_weight else stored_billing_weight
    )
    receivable = (
        calculate_receivable(effective_billing_weight, quote_price(quote), quote.surcharge)
        if uses_live_weight
        else money(quote.receivable_amount)
    )
    return {
        "current_weight": current_weight,
        "current_billing_weight": current_billing_weight,
        "weight_snapshot": effective_weight,
        "billing_weight": effective_billing_weight,
        "receivable_amount": receivable,
    }


def get_current_quote(session, order_uid: str, *, for_update=False) -> Optional[OrderQuoteVersionTable]:
    query = (
        session.query(OrderQuoteVersionTable)
        .filter(
            OrderQuoteVersionTable.order_uid == order_uid,
            OrderQuoteVersionTable.archive == False,  # noqa: E712
            OrderQuoteVersionTable.is_final == True,  # noqa: E712
            OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
        )
        .order_by(OrderQuoteVersionTable.version_no.desc())
    )
    if for_update:
        query = query.populate_existing().with_for_update()
    return query.first()


def quote_to_dict(session, quote: OrderQuoteVersionTable) -> dict:
    pricing = quote_pricing_state(session, quote)
    current_weight = pricing["current_weight"]
    snapshot = pricing["weight_snapshot"]
    is_effective = bool(
        quote.is_final
        and quote.status in EFFECTIVE_QUOTE_STATUSES
    )
    if quote.status == "pending":
        validity_status = "pending"
    elif quote.status == "rejected":
        validity_status = "rejected"
    elif not quote.is_final:
        validity_status = "superseded"
    else:
        validity_status = "effective"

    p = quote_price(quote)
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
        "billing_weight": decimal_json(pricing["billing_weight"], WEIGHT),
        "current_weight": decimal_json(current_weight, WEIGHT),
        "receivable_amount": decimal_json(pricing["receivable_amount"]),
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
            PaymentReceiptItemTable.archive == False,  # noqa: E712
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


def _locked_receipt_allocations(session, order_uids, exclude_receipt_id=None):
    """Read current receipt state after locking all affected orders in UID order.

    Locking reads avoid stale repeatable-read snapshots after waiting for an
    order lock. Every receipt mutation follows orders -> adjustments -> receipts.
    """
    items = (
        session.query(
            PaymentReceiptItemTable.receipt_id,
            PaymentReceiptItemTable.order_uid,
            PaymentReceiptItemTable.amount,
            PaymentReceiptItemTable.settlement_difference,
            PaymentReceiptItemTable.adjustment_id,
        )
        .filter(
            PaymentReceiptItemTable.order_uid.in_(order_uids),
            PaymentReceiptItemTable.archive == False,  # noqa: E712
        )
        .order_by(PaymentReceiptItemTable.id.asc())
        .with_for_update()
        .all()
    )
    # Different orders can share a receipt header. Lock those headers explicitly
    # by ID rather than relying on a join's query plan to acquire sorted locks.
    receipts = {}
    for receipt_id in sorted({item.receipt_id for item in items}):
        receipts[receipt_id] = (
            session.query(
                PaymentReceiptTable.receipt_no,
                PaymentReceiptTable.status,
                PaymentReceiptTable.settlement_status,
            )
            .filter(PaymentReceiptTable.id == receipt_id)
            .with_for_update()
            .one()
        )
    result = {
        uid: {
            "approved": Decimal("0.00"),
            "pending": Decimal("0.00"),
            "settlement_difference": Decimal("0.00"),
            "pending_receipts": [],
            "pending_settled_receipts": [],
            "settled_receipts": [],
            "approved_settled": False,
            "adjustments": {},
        }
        for uid in order_uids
    }
    for item in items:
        receipt = receipts[item.receipt_id]
        if item.receipt_id == exclude_receipt_id or receipt.status not in {"pending", "approved"}:
            continue
        state = result[item.order_uid]
        state[receipt.status] += money(item.amount)
        if item.adjustment_id is not None:
            adjustment_totals = state["adjustments"].setdefault(
                item.adjustment_id,
                {"approved": Decimal("0.00"), "pending": Decimal("0.00")},
            )
            adjustment_totals[receipt.status] += money(item.amount)
        if receipt.status == "approved":
            state["settlement_difference"] += money(
                item.settlement_difference or 0
            )
        label = receipt.receipt_no or str(item.receipt_id)
        if receipt.status == "pending":
            state["pending_receipts"].append(label)
            if receipt.settlement_status == "settled":
                state["pending_settled_receipts"].append(label)
        if receipt.settlement_status == "settled":
            state["settled_receipts"].append(label)
            state["approved_settled"] |= receipt.status == "approved"
    return result


def _locked_price_adjustments(session, order_uids):
    """Receipt mutations lock orders, adjustments, then existing receipts."""
    return {
        adjustment.id: adjustment
        for adjustment in (
            session.query(OrderPriceAdjustmentTable)
            .filter(
                OrderPriceAdjustmentTable.order_uid.in_(order_uids),
                OrderPriceAdjustmentTable.archive == False,  # noqa: E712
            )
            .order_by(OrderPriceAdjustmentTable.id.asc())
            .populate_existing()
            .with_for_update()
            .all()
        )
    }


def _collection_available(adjustment, allocations, adjustment_totals, receivable):
    if (
        adjustment.status != "pending"
        or adjustment.direction != "collect"
        or money(adjustment_totals.get("pending", 0)) > 0
        or allocations["pending_settled_receipts"]
    ):
        return Decimal("0.00")
    adjustment_remaining = money(
        adjustment.delta_amount
        - adjustment_totals.get("approved", Decimal("0.00"))
        - adjustment_totals.get("pending", Decimal("0.00"))
    )
    order_remaining = money(
        receivable
        - allocations["approved"]
        - allocations["settlement_difference"]
        - allocations["pending"]
    )
    return max(min(adjustment_remaining, order_remaining), Decimal("0.00"))


def _price_adjustment_receipt_totals(session, order_uids):
    """Read list-page cash totals in one query without taking mutation locks."""
    allocations = {
        uid: {
            "approved": Decimal("0.00"),
            "pending": Decimal("0.00"),
            "settlement_difference": Decimal("0.00"),
            "pending_settled_receipts": False,
            "adjustments": {},
        }
        for uid in order_uids
    }
    rows = (
        session.query(
            PaymentReceiptItemTable.order_uid,
            PaymentReceiptItemTable.adjustment_id,
            PaymentReceiptTable.status,
            PaymentReceiptTable.settlement_status,
            func.sum(PaymentReceiptItemTable.amount).label("amount"),
            func.sum(PaymentReceiptItemTable.settlement_difference).label("difference"),
        )
        .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
        .filter(
            PaymentReceiptItemTable.order_uid.in_(order_uids),
            PaymentReceiptItemTable.archive == False,  # noqa: E712
            PaymentReceiptTable.status.in_(["pending", "approved"]),
        )
        .group_by(
            PaymentReceiptItemTable.order_uid,
            PaymentReceiptItemTable.adjustment_id,
            PaymentReceiptTable.status,
            PaymentReceiptTable.settlement_status,
        )
        .all()
    )
    for uid, adjustment_id, status, settlement_status, amount, difference in rows:
        totals = allocations[uid]
        totals[status] += money(amount)
        if status == "approved":
            totals["settlement_difference"] += money(difference)
        if status == "pending" and settlement_status == "settled":
            totals["pending_settled_receipts"] = True
        if adjustment_id is not None:
            adjustment_totals = totals["adjustments"].setdefault(
                adjustment_id,
                {"approved": Decimal("0.00"), "pending": Decimal("0.00")},
            )
            adjustment_totals[status] += money(amount)
    return allocations


def _price_adjustment_dict(adjustment, order, quote, current_quote, customer, operator, allocations, receivable):
    adjustment_totals = allocations["adjustments"].get(adjustment.id, {})
    available = _collection_available(adjustment, allocations, adjustment_totals, receivable)
    blocked_reason = None
    if adjustment.direction != "collect":
        blocked_reason = "退款差价请由财务处理"
    elif adjustment.status != "pending":
        blocked_reason = "该差价已处理"
    elif not operator["roles"].intersection({"salesperson", "admin"}):
        blocked_reason = "无权创建收款单"
    elif customer is None:
        blocked_reason = "订单未关联有效客户"
    elif current_quote is None:
        blocked_reason = "订单尚无有效报价"
    elif "admin" not in operator["roles"] and current_quote.quoter_id != operator["id"]:
        blocked_reason = "订单不属于你的跟单范围"
    elif adjustment_totals.get("pending", 0) > 0:
        blocked_reason = "该差价已有待审核补收单"
    elif allocations["pending_settled_receipts"]:
        blocked_reason = "订单存在待审核结清收据"
    elif available <= 0:
        blocked_reason = "订单暂无可补收余额"
    if blocked_reason:
        available = Decimal("0.00")
    return {
        "id": adjustment.id,
        "order_uid": adjustment.order_uid,
        "order_id": order.order_id or order.uid,
        "customer_id": customer.id if customer else None,
        "customer_name": customer.name if customer else order.customer_name,
        "previous_quote_id": adjustment.previous_quote_id,
        "new_quote_id": adjustment.new_quote_id,
        "old_receivable": decimal_json(adjustment.old_receivable),
        "new_receivable": decimal_json(adjustment.new_receivable),
        "delta_amount": decimal_json(adjustment.delta_amount),
        "direction": adjustment.direction,
        "status": adjustment.status,
        "quoter_id": quote.quoter_id,
        "quoter_name": quote.quoter_name,
        "approved_received": decimal_json(adjustment_totals.get("approved", 0)),
        "pending_amount": decimal_json(adjustment_totals.get("pending", 0)),
        "available_amount": decimal_json(available),
        "collection_blocked_reason": blocked_reason,
        "create_date": adjustment.create_date,
    }


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


def normalize_quote_payload(body: dict) -> dict:
    """Validate and normalize quote input for controllers and services."""
    if not isinstance(body, dict):
        raise ValueError("报价字段格式不正确")
    raw_unit_price = body.get("unit_price", body.get("quoted_price"))
    if raw_unit_price is None:
        raise ValueError("每公斤单价不能为空")

    normalized_unit_price = unit_price(raw_unit_price)
    normalized_surcharge = money(body.get("surcharge", 0))
    if normalized_unit_price < 0 or normalized_surcharge < 0:
        raise ValueError("每公斤单价和附加费不能小于 0")
    return {
        "unit_price": normalized_unit_price,
        "surcharge": normalized_surcharge,
        "quote_remark": (body.get("quote_remark") or "").strip() or None,
    }


def _create_price_adjustment(
    session,
    *,
    order_uid: str,
    previous_quote: Optional[OrderQuoteVersionTable],
    previous_receivable,
    new_quote: OrderQuoteVersionTable,
    new_receivable,
    creator: dict,
    now: str,
) -> Optional[OrderPriceAdjustmentTable]:
    """Create exactly one pending debit/credit task for an effective re-quote."""
    if previous_quote is None or not order_has_receipt_history(session, order_uid):
        return None
    existing = (
        session.query(OrderPriceAdjustmentTable)
        .filter(OrderPriceAdjustmentTable.new_quote_id == new_quote.id)
        .first()
    )
    if existing is not None:
        return existing
    old_amount = money(previous_receivable)
    next_amount = money(new_receivable)
    delta = money(next_amount - old_amount)
    if delta == 0:
        return None
    adjustment = OrderPriceAdjustmentTable(
        order_uid=order_uid,
        previous_quote_id=previous_quote.id,
        new_quote_id=new_quote.id,
        old_receivable=old_amount,
        new_receivable=next_amount,
        delta_amount=delta,
        direction="collect" if delta > 0 else "refund",
        status="pending",
        creator_id=new_quote.quoter_id or creator.get("id"),
        creator_name=new_quote.quoter_name or creator.get("name") or "系统",
        create_date=now,
    )
    session.add(adjustment)
    session.flush()
    return adjustment


def create_order_quote(
    order_uid: str,
    body: dict,
    operator_payload: dict,
    allow_on_behalf: bool = False,
) -> dict:
    """Create one quote version and attribute it to the order's salesman."""
    normalized = normalize_quote_payload(body)
    quote_unit_price = normalized["unit_price"]
    surcharge = normalized["surcharge"]
    quote_remark = normalized["quote_remark"]
    operator = _operator(operator_payload)
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    with SessionFactory() as session:
        order = (
            session.query(OrderTable)
            .filter(
                OrderTable.uid == order_uid,
                OrderTable.archive == False,  # noqa: E712
            )
            .with_for_update()
            .first()
        )
        if order is None:
            raise LookupError("订单不存在")
        lock_order_for_update(session, order_uid, order=order)
        from data.order_version import record_mutation, snapshot_order

        order_before = snapshot_order(session, order_uid)
        if order.salesman_id is None:
            raise ValueError("订单尚未分配业务员，无法报价")
        if (
            not allow_on_behalf
            and (operator["id"] is None or str(order.salesman_id) != str(operator["id"]))
        ):
            raise PermissionError("仅当前订单的业务员可以报价")

        assigned_salesman = order.salesman
        if assigned_salesman is not None:
            quoter_id = assigned_salesman.id
            quoter_name = assigned_salesman.name
        elif operator["id"] is not None and str(order.salesman_id) == str(operator["id"]):
            quoter_id = order.salesman_id
            quoter_name = operator["name"]
        else:
            raise LookupError("订单业务员不存在，无法报价")

        transportation_name = (order.transportation or "").strip()
        mode = None
        if transportation_name:
            mode = (
                session.query(TransportationModeTable)
                .filter(TransportationModeTable.name == transportation_name)
                .first()
            )

        transportation_mode_id = mode.id if mode else None
        quote_transportation_name = mode.name if mode else transportation_name
        channel_cost = float(mode.cost or 0) if mode else 0
        min_price = float(mode.min_price or 0) if mode else 0
        weight_snapshot = current_order_weight(session, order_uid)
        billing_weight_snapshot = current_order_billing_weight(session, order_uid)
        receivable_amount = calculate_receivable(
            billing_weight_snapshot, quote_unit_price, surcharge
        )
        previous_quote = get_current_quote(session, order_uid, for_update=True)
        previous_receivable = (
            quote_pricing_state(session, previous_quote)["receivable_amount"]
            if previous_quote is not None
            else None
        )

        status = "adopted" if quote_unit_price >= unit_price(min_price) else "pending"
        is_final = status == "adopted"
        if is_final:
            (
                session.query(OrderQuoteVersionTable)
                .filter(OrderQuoteVersionTable.order_uid == order_uid)
                .update({"is_final": False})
            )
            order.transportation = quote_transportation_name
            order.update_date = now

        latest_version = (
            session.query(OrderQuoteVersionTable.version_no)
            .filter(OrderQuoteVersionTable.order_uid == order_uid)
            .order_by(OrderQuoteVersionTable.version_no.desc())
            .first()
        )
        quote = OrderQuoteVersionTable(
            order_uid=order_uid,
            version_no=(latest_version[0] if latest_version else 0) + 1,
            transportation_mode_id=transportation_mode_id,
            transportation_name=quote_transportation_name,
            channel_cost=channel_cost,
            min_price=min_price,
            unit_price=quote_unit_price,
            surcharge=surcharge,
            weight_snapshot=weight_snapshot,
            billing_weight_snapshot=billing_weight_snapshot,
            receivable_amount=receivable_amount,
            quoted_price=float(quote_unit_price),
            status=status,
            is_final=is_final,
            quote_remark=quote_remark,
            quoter_id=quoter_id,
            quoter_name=quoter_name,
            create_date=now,
            effective_date=now if is_final else None,
        )
        session.add(quote)
        session.flush()
        if is_final:
            _create_price_adjustment(
                session,
                order_uid=order_uid,
                previous_quote=previous_quote,
                previous_receivable=previous_receivable,
                new_quote=quote,
                new_receivable=receivable_amount,
                creator=operator,
                now=now,
            )
        record_mutation(
            session,
            order_uid,
            before=order_before,
            after=snapshot_order(session, order_uid),
            action="order_transportation_updated",
            summary="报价流程更新订单运输方式",
            operator_payload=operator_payload,
        )
        session.commit()
        session.refresh(quote)
        result = quote_to_dict(session, quote)
        if is_final:
            result["order_transportation"] = order.transportation
        return result


def list_price_adjustments(
    operator_payload: dict,
    *,
    status: Optional[str] = "pending",
    query_text: str = "",
    page: int = 1,
    page_size: int = 20,
    adjustment_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    order_uid: Optional[str] = None,
) -> dict:
    """List audit-linked re-quote deltas without treating them as cash."""
    operator = _operator(operator_payload)
    if not operator["roles"].intersection({"salesperson", "admin", "finance"}):
        raise PermissionError("无权查看差价单")
    if status not in {None, "", "pending", "resolved", "cancelled"}:
        raise ValueError("差价单状态无效")
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 200)
    with SessionFactory() as session:
        current_quote = aliased(OrderQuoteVersionTable)
        query = (
            session.query(
                OrderPriceAdjustmentTable,
                OrderTable,
                OrderQuoteVersionTable,
                current_quote,
            )
            .join(
                OrderTable,
                OrderTable.uid == OrderPriceAdjustmentTable.order_uid,
            )
            .join(
                OrderQuoteVersionTable,
                OrderQuoteVersionTable.id == OrderPriceAdjustmentTable.new_quote_id,
            )
            .outerjoin(
                current_quote,
                and_(
                    current_quote.order_uid == OrderTable.uid,
                    current_quote.archive == False,  # noqa: E712
                    current_quote.is_final == True,  # noqa: E712
                    current_quote.status.in_(EFFECTIVE_QUOTE_STATUSES),
                ),
            )
            .options(selectinload(OrderTable.customers))
            .filter(OrderTable.archive == False)  # noqa: E712
            .filter(OrderPriceAdjustmentTable.archive == False)  # noqa: E712
            .filter(OrderQuoteVersionTable.archive == False)  # noqa: E712
        )
        if status:
            query = query.filter(OrderPriceAdjustmentTable.status == status)
        if adjustment_id is not None:
            query = query.filter(OrderPriceAdjustmentTable.id == adjustment_id)
        elif "admin" not in operator["roles"] and "finance" not in operator["roles"]:
            query = query.filter(current_quote.quoter_id == operator["id"])
        elif owner_id is not None:
            query = query.filter(current_quote.quoter_id == owner_id)
        normalized_order_uid = str(order_uid or "").strip()
        if normalized_order_uid:
            query = query.filter(OrderTable.uid == normalized_order_uid)
        normalized_query = str(query_text or "").strip()
        if normalized_query:
            like = f"%{normalized_query}%"
            query = query.filter(
                or_(
                    OrderTable.order_id.ilike(like),
                    OrderTable.customer_name.ilike(like),
                )
            )
        total = query.count()
        rows = (
            query.order_by(
                OrderPriceAdjustmentTable.create_date.desc(),
                OrderPriceAdjustmentTable.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        if adjustment_id is not None:
            if not rows:
                raise LookupError("差价单不存在")
            current = rows[0][3]
            if not operator["roles"].intersection({"admin", "finance"}) and (
                current is None or current.quoter_id != operator["id"]
            ):
                raise PermissionError("无权查看该差价单")
        order_uids = {order.uid for _, order, _, _ in rows}
        allocations = _price_adjustment_receipt_totals(session, order_uids)
        billing_weights = dict(
            session.query(
                CargoTable.target_order_uid,
                func.coalesce(func.sum(func.ceil(CargoTable.weight)), 0),
            )
            .filter(
                CargoTable.target_order_uid.in_(order_uids),
                CargoTable.archive == False,  # noqa: E712
            )
            .group_by(CargoTable.target_order_uid)
            .all()
        )
        customer_names = {
            order.customer_name for _, order, _, _ in rows
            if not order.customers and order.customer_name
        }
        customers_by_name = {
            customer.name: customer
            for customer in session.query(CustomerTable).filter(CustomerTable.name.in_(customer_names)).all()
        }
        return {
            "items": [
                _price_adjustment_dict(
                    adjustment, order, quote, current,
                    order.customers[0] if order.customers else customers_by_name.get(order.customer_name),
                    operator, allocations[order.uid],
                    calculate_receivable(billing_weights.get(order.uid, 0), quote_price(current), current.surcharge)
                    if current is not None else Decimal("0.00"),
                )
                for adjustment, order, quote, current in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def get_price_adjustment_detail(adjustment_id: int, operator_payload: dict) -> dict:
    return list_price_adjustments(
        operator_payload, status=None, adjustment_id=adjustment_id,
    )["items"][0]


def list_receivable_orders(
    customer_id: Optional[int],
    operator_payload: dict,
    query_text="",
    page=1,
    page_size=20,
    date_from=None,
    date_to=None,
    owner_id=None,
    order_uid=None,
) -> dict:
    operator = _operator(operator_payload)
    for name, value in (("date_from", date_from), ("date_to", date_to)):
        if value is not None:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d")
                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError
            except ValueError as exc:
                raise ValueError(f"{name} 必须为 YYYY-MM-DD") from exc
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from 不能晚于 date_to")
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    with SessionFactory() as session:
        selected_customer = None
        if customer_id is not None:
            selected_customer = session.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
        if customer_id is not None and selected_customer is None:
            raise ValueError("客户不存在")
        receipt_stats = (
            session.query(
                PaymentReceiptItemTable.order_uid.label("order_uid"),
                func.coalesce(func.sum(case(
                    (PaymentReceiptTable.status == "approved", PaymentReceiptItemTable.amount),
                    else_=0,
                )), 0).label("approved"),
                func.coalesce(func.sum(case(
                    (PaymentReceiptTable.status == "pending", PaymentReceiptItemTable.amount),
                    else_=0,
                )), 0).label("pending"),
                func.coalesce(func.sum(case(
                    (
                        PaymentReceiptTable.status == "approved",
                        func.coalesce(PaymentReceiptItemTable.settlement_difference, 0),
                    ),
                    else_=0,
                )), 0).label("settlement_difference"),
                func.max(case(
                    (and_(
                        PaymentReceiptTable.status == "pending",
                        PaymentReceiptTable.settlement_status == "settled",
                    ), 1),
                    else_=0,
                )).label("pending_settled"),
            )
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(PaymentReceiptItemTable.archive == False)  # noqa: E712
            .group_by(PaymentReceiptItemTable.order_uid)
            .subquery()
        )
        cargo_stats = (
            session.query(
                CargoTable.target_order_uid.label("order_uid"),
                func.coalesce(func.sum(CargoTable.weight), 0).label("raw_weight"),
                func.coalesce(func.sum(func.ceil(CargoTable.weight)), 0).label("billing_weight"),
            )
            .filter(
                CargoTable.archive == False,  # noqa: E712
                CargoTable.target_order_uid.isnot(None),
            )
            .group_by(CargoTable.target_order_uid)
            .subquery()
        )
        approved_expr = func.coalesce(receipt_stats.c.approved, 0)
        pending_expr = func.coalesce(receipt_stats.c.pending, 0)
        settlement_difference_expr = func.coalesce(
            receipt_stats.c.settlement_difference, 0
        )
        current_weight_expr = func.coalesce(cargo_stats.c.raw_weight, 0)
        current_billing_weight_expr = func.coalesce(cargo_stats.c.billing_weight, 0)
        quote_price_expr = case(
            (
                and_(
                    OrderQuoteVersionTable.unit_price == 0,
                    OrderQuoteVersionTable.quoted_price != 0,
                ),
                OrderQuoteVersionTable.quoted_price,
            ),
            else_=OrderQuoteVersionTable.unit_price,
        )
        live_receivable_expr = func.round(
            current_billing_weight_expr * quote_price_expr
            + OrderQuoteVersionTable.surcharge,
            2,
        )
        query = (
            session.query(
                OrderTable,
                OrderQuoteVersionTable,
                approved_expr.label("approved"),
                pending_expr.label("pending"),
                settlement_difference_expr.label("settlement_difference"),
                current_weight_expr.label("current_weight"),
                current_billing_weight_expr.label("current_billing_weight"),
                live_receivable_expr.label("effective_receivable"),
            )
            .join(
                OrderQuoteVersionTable,
                and_(
                    OrderQuoteVersionTable.order_uid == OrderTable.uid,
                    OrderQuoteVersionTable.archive == False,  # noqa: E712
                    OrderQuoteVersionTable.is_final == True,  # noqa: E712
                    OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
                ),
            )
            .outerjoin(receipt_stats, receipt_stats.c.order_uid == OrderTable.uid)
            .outerjoin(cargo_stats, cargo_stats.c.order_uid == OrderTable.uid)
            .options(selectinload(OrderTable.customers))
            .filter(
                OrderTable.archive == False,  # noqa: E712
            )
        )
        if "admin" not in operator["roles"]:
            query = query.filter(OrderQuoteVersionTable.quoter_id == operator["id"])
        elif owner_id is not None:
            query = query.filter(OrderQuoteVersionTable.quoter_id == owner_id)
        normalized_order_uid = str(order_uid or "").strip()
        if normalized_order_uid:
            query = query.filter(OrderTable.uid == normalized_order_uid)
        if date_from:
            query = query.filter(OrderTable.create_date >= f"{date_from} 00:00:00")
        if date_to:
            query = query.filter(OrderTable.create_date <= f"{date_to} 23:59:59")
        if selected_customer is not None:
            query = query.filter(or_(
                OrderTable.customers.any(CustomerTable.id == selected_customer.id),
                and_(
                    ~OrderTable.customers.any(),
                    OrderTable.customer_name == selected_customer.name,
                ),
            ))
        if query_text:
            like = f"%{query_text.strip()}%"
            query = query.filter(or_(OrderTable.order_id.ilike(like), OrderTable.customer_name.ilike(like)))
        query = query.filter(
            live_receivable_expr
            > approved_expr + settlement_difference_expr + pending_expr
        )
        query = query.filter(
            func.coalesce(receipt_stats.c.pending_settled, 0) == 0
        )

        total = query.count()
        rows = (
            query.order_by(OrderTable.create_date.desc(), OrderTable.uid.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        result = []
        for (
            order,
            quote,
            approved_value,
            pending_value,
            settlement_difference_value,
            current_weight,
            current_billing_weight,
            effective_receivable,
        ) in rows:
            allocations = {
                "approved": money(approved_value),
                "pending": money(pending_value),
                "settlement_difference": money(settlement_difference_value),
            }
            effective_weight = weight(current_weight)
            effective_billing_weight = weight(current_billing_weight)
            receivable = money(effective_receivable)
            available = money(
                receivable
                - allocations["approved"]
                - allocations["settlement_difference"]
                - allocations["pending"]
            )
            customer = selected_customer or (order.customers[0] if order.customers else None)
            if customer is None and order.customer_name:
                customer = (
                    session.query(CustomerTable)
                    .filter(CustomerTable.name == order.customer_name)
                    .first()
                )
            result.append({
                "uid": order.uid,
                "order_id": order.order_id,
                "create_date": order.create_date,
                "customer_id": customer.id if customer else None,
                "customer_name": customer.name if customer else order.customer_name,
                "quoter_id": quote.quoter_id,
                "quoter_name": quote.quoter_name,
                "effective_date": quote.effective_date,
                "weight_snapshot": decimal_json(effective_weight, WEIGHT),
                "billing_weight": decimal_json(effective_billing_weight, WEIGHT),
                "receivable_amount": decimal_json(receivable),
                "approved_received": decimal_json(allocations["approved"]),
                "pending_amount": decimal_json(allocations["pending"]),
                "settlement_difference": decimal_json(
                    allocations["settlement_difference"]
                ),
                "available_amount": decimal_json(available),
            })
        return {
            "items": result,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


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
    settlement_status = body.get("settlement_status")
    if "settlement_status" in body and (
        not isinstance(settlement_status, str)
        or settlement_status not in SETTLEMENT_STATUSES
    ):
        raise ValueError("结清状态必须为 settled 或 unsettled")
    item_payloads = body.get("items") or []
    if not isinstance(item_payloads, list) or not item_payloads:
        raise ValueError("请至少选择一笔订单")
    order_uids = [str(item.get("order_uid") or "").strip() for item in item_payloads]
    if any(not uid for uid in order_uids) or len(set(order_uids)) != len(order_uids):
        raise ValueError("订单明细无效或重复")
    adjustment_ids = []
    for item in item_payloads:
        adjustment_id = item.get("adjustment_id")
        if adjustment_id is not None:
            if (
                isinstance(adjustment_id, bool)
                or not isinstance(adjustment_id, (str, int))
                or not str(adjustment_id).isdigit()
                or int(adjustment_id) <= 0
            ):
                raise ValueError("差价单编号无效")
            adjustment_id = int(adjustment_id)
        adjustment_ids.append(adjustment_id)
    if any(adjustment_id is not None for adjustment_id in adjustment_ids):
        if len(item_payloads) != 1:
            raise ValueError("差价补收单只能包含一笔差价明细")
        if settlement_status == "settled":
            raise ValueError("差价补收必须选择未结清，不能豁免剩余差价")
        settlement_status = "unsettled"

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionFactory() as session:
        orders = (
            session.query(OrderTable)
            .filter(OrderTable.uid.in_(order_uids), OrderTable.archive == False)  # noqa: E712
            .order_by(OrderTable.uid.asc())
            .with_for_update()
            .all()
        )
        order_map = {order.uid: order for order in orders}
        if len(order_map) != len(order_uids):
            raise ValueError("部分订单不存在或已归档")
        customer = session.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
        if customer is None:
            raise ValueError("客户不存在")
        price_adjustments = _locked_price_adjustments(session, order_uids)
        allocation_map = _locked_receipt_allocations(session, order_uids)

        prepared = []
        settlement_remaining = Decimal("0.00")
        for item, order_uid, adjustment_id in zip(item_payloads, order_uids, adjustment_ids):
            order = order_map[order_uid]
            if not _customer_matches_order(order, customer):
                raise ValueError(f"订单 {order.order_id or order.uid} 不属于所选客户")
            quote = get_current_quote(session, order.uid, for_update=True)
            if quote is None:
                raise ValueError(f"订单 {order.order_id or order.uid} 尚无有效报价")
            pricing = quote_pricing_state(session, quote)
            if "admin" not in operator["roles"] and quote.quoter_id != operator["id"]:
                raise PermissionError(f"订单 {order.order_id or order.uid} 不属于你的跟单范围")
            if not order_has_receipt_history(session, order.uid):
                quote.weight_snapshot = pricing["weight_snapshot"]
                quote.billing_weight_snapshot = pricing["billing_weight"]
                quote.receivable_amount = pricing["receivable_amount"]
                session.flush()
            amount = money(item.get("amount"))
            if amount <= 0:
                raise ValueError(f"订单 {order.order_id or order.uid} 的本次收款必须大于 0")
            allocations = allocation_map[order.uid]
            receivable = pricing["receivable_amount"]
            available = money(
                receivable
                - allocations["approved"]
                - allocations["settlement_difference"]
                - allocations["pending"]
            )
            if allocations["pending_settled_receipts"] or (
                allocations["approved_settled"] and available <= 0
            ):
                raise ValueError(f"订单 {order.order_id or order.uid} 已结清或存在待审核结清收据，不能重复收款")
            if amount > available:
                raise ValueError(
                    f"订单 {order.order_id or order.uid} 最多可收 {available:.2f} CNY"
                )
            if adjustment_id is not None:
                adjustment = price_adjustments.get(adjustment_id)
                if adjustment is None or adjustment.order_uid != order.uid:
                    raise ValueError("差价单不存在、已归档或不属于所选订单")
                if adjustment.status != "pending" or adjustment.direction != "collect":
                    raise ValueError("仅待处理的补收差价可以登记收款")
                adjustment_totals = allocations["adjustments"].get(adjustment_id, {})
                if adjustment_totals.get("pending", 0) > 0:
                    raise ValueError("该差价已有待审核补收单，不能重复收款")
                adjustment_available = _collection_available(
                    adjustment, allocations, adjustment_totals, receivable
                )
                if amount > adjustment_available:
                    raise ValueError(f"该差价最多可补收 {adjustment_available:.2f} CNY")
            prepared.append((order, receivable, allocations, available, amount, adjustment_id))
            # The default reflects actual received income, not pending reservations.
            settlement_remaining += money(
                receivable
                - allocations["approved"]
                - allocations["settlement_difference"]
                - amount
            )

        if settlement_status is None:
            settlement_status = (
                "settled" if settlement_remaining < SETTLEMENT_THRESHOLD else "unsettled"
            )

        receipt = PaymentReceiptTable(
            customer_id=customer.id,
            customer_name=customer.name,
            receipt_date=receipt_date,
            payment_method=payment_method,
            remark=(body.get("remark") or "").strip() or None,
            status="pending",
            settlement_status=settlement_status,
            creator_id=operator["id"],
            creator_name=operator["name"],
            create_date=now,
            update_date=now,
        )
        session.add(receipt)
        session.flush()
        receipt.receipt_no = f"RCPT-{receipt_date.replace('-', '')}-{receipt.id:06d}"
        for order, receivable, allocations, available, amount, adjustment_id in prepared:
            session.add(PaymentReceiptItemTable(
                receipt_id=receipt.id,
                order_uid=order.uid,
                adjustment_id=adjustment_id,
                order_id=order.order_id or order.uid,
                receivable_snapshot=receivable,
                received_before=allocations["approved"],
                amount=amount,
                remaining_after=money(available - amount),
            ))
        session.commit()
        return get_receipt_detail(receipt.id, operator_payload, session=session)


def _receipt_items(session, receipt: PaymentReceiptTable) -> list:
    rows = (
        session.query(PaymentReceiptItemTable)
        .filter(PaymentReceiptItemTable.receipt_id == receipt.id)
        .order_by(PaymentReceiptItemTable.id.asc())
        .all()
    )
    preview = receipt.status == "pending" and receipt.settlement_status == "settled"
    approved = {}
    if preview and rows:
        approved = dict(
            session.query(
                PaymentReceiptItemTable.order_uid,
                func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0),
            )
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(
                PaymentReceiptItemTable.order_uid.in_([row.order_uid for row in rows]),
                PaymentReceiptTable.status == "approved",
            )
            .group_by(PaymentReceiptItemTable.order_uid)
            .all()
        )
    return [{
        "id": row.id,
        "order_uid": row.order_uid,
        "adjustment_id": row.adjustment_id,
        "order_id": row.order_id,
        "receivable_snapshot": decimal_json(row.receivable_snapshot),
        "received_before": decimal_json(row.received_before),
        "amount": decimal_json(row.amount),
        "remaining_after": decimal_json(row.remaining_after),
        "archive": bool(row.archive),
        "settlement_difference": (
            decimal_json(row.settlement_difference)
            if row.settlement_difference is not None else None
        ),
        "preview_settlement_difference": (
            decimal_json(max(
                money(row.receivable_snapshot) - money(approved.get(row.order_uid, 0)) - money(row.amount),
                Decimal("0.00"),
            )) if preview else None
        ),
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
        "settlement_status": receipt.settlement_status,
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
        data["items"] = _receipt_items(session, receipt)
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


def list_receipts(
    operator_payload: dict, status=None, page=1, page_size=20, query_text="", owner_id=None,
) -> dict:
    operator = _operator(operator_payload)
    with SessionFactory() as session:
        receipt_totals = (
            session.query(
                PaymentReceiptItemTable.receipt_id.label("receipt_id"),
                func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0).label("total_amount"),
            )
            .group_by(PaymentReceiptItemTable.receipt_id)
            .subquery()
        )
        query = (
            session.query(
                PaymentReceiptTable,
                func.coalesce(receipt_totals.c.total_amount, 0).label("total_amount"),
            )
            .outerjoin(receipt_totals, receipt_totals.c.receipt_id == PaymentReceiptTable.id)
        )
        if not operator["roles"].intersection({"admin", "finance"}):
            query = query.filter(PaymentReceiptTable.creator_id == operator["id"])
        elif owner_id is not None:
            query = query.filter(PaymentReceiptTable.creator_id == owner_id)
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
        for row, total_amount in rows:
            item = _receipt_dict(session, row, include_items=False)
            item["total_amount"] = decimal_json(total_amount)
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
    with SessionFactory() as session:
        # Receipt membership never changes. Read IDs first, then use the same
        # order -> adjustment -> receipt lock sequence, including for rejections.
        order_uids = [row[0] for row in (
            session.query(PaymentReceiptItemTable.order_uid)
            .filter(PaymentReceiptItemTable.receipt_id == receipt_id)
            .order_by(PaymentReceiptItemTable.order_uid.asc())
            .all()
        )]
        (
            session.query(OrderTable)
            .filter(OrderTable.uid.in_(order_uids))
            .order_by(OrderTable.uid.asc())
            .populate_existing()
            .with_for_update()
            .all()
        )
        price_adjustments = _locked_price_adjustments(session, order_uids)
        allocation_map = _locked_receipt_allocations(
            session, order_uids, exclude_receipt_id=receipt_id
        )
        receipt = (
            session.query(PaymentReceiptTable)
            .filter(PaymentReceiptTable.id == receipt_id)
            .populate_existing()
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
            receivables = {}
            items = (
                session.query(PaymentReceiptItemTable)
                .filter_by(receipt_id=receipt.id)
                .order_by(PaymentReceiptItemTable.order_uid.asc())
                .populate_existing()
                .with_for_update()
                .all()
            )
            for item in items:
                allocations = allocation_map[item.order_uid]
                if receipt.settlement_status == "settled" and allocations["pending_receipts"]:
                    blockers = "、".join(allocations["pending_receipts"])
                    raise ValueError(f"订单 {item.order_id} 存在其他待审核收据 {blockers}，请先审核或驳回，再批准结清")
            for item in items:
                quote = get_current_quote(session, item.order_uid, for_update=True)
                if quote is None:
                    raise ValueError(f"订单 {item.order_id} 尚无有效报价，请驳回后重新登记")
                receivable = quote_pricing_state(session, quote)["receivable_amount"]
                receivables[item.order_uid] = receivable
                if money(receivable) != money(item.receivable_snapshot):
                    raise ValueError(f"订单 {item.order_id} 应收已变化，请驳回后重新登记")
                allocations = allocation_map[item.order_uid]
                available = money(
                    receivable
                    - allocations["approved"]
                    - allocations["settlement_difference"]
                    - allocations["pending"]
                )
                if allocations["approved_settled"] and available <= 0:
                    raise ValueError(f"订单 {item.order_id} 已结清，请驳回本收据")
                if money(item.amount) > available:
                    raise ValueError(f"订单 {item.order_id} 可收余额不足，请驳回后重新登记")
                if item.adjustment_id is not None:
                    adjustment = price_adjustments.get(item.adjustment_id)
                    if (
                        adjustment is None
                        or adjustment.order_uid != item.order_uid
                        or adjustment.status != "pending"
                        or adjustment.direction != "collect"
                    ):
                        raise ValueError("关联差价已处理或不可补收，请驳回本收据")
                    if receipt.settlement_status != "unsettled":
                        raise ValueError("差价补收不能豁免剩余差价，请驳回本收据")
                    adjustment_totals = allocations["adjustments"].get(item.adjustment_id, {})
                    adjustment_remaining = money(
                        adjustment.delta_amount
                        - adjustment_totals.get("approved", Decimal("0.00"))
                        - adjustment_totals.get("pending", Decimal("0.00"))
                    )
                    if money(item.amount) > adjustment_remaining:
                        raise ValueError("关联差价可补收余额不足，请驳回本收据")
                item.settlement_difference = (
                    money(max(
                        receivable
                        - allocations["approved"]
                        - allocations["settlement_difference"]
                        - money(item.amount),
                        Decimal("0.00"),
                    ))
                    if receipt.settlement_status == "settled"
                    else (Decimal("0.00") if receipt.settlement_status == "unsettled" else None)
                )
        # The accounting cutoff uses the actual review time, after any wait
        # for order locks and validation (which can cross midnight).
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        receipt.status = "approved" if action == "approve" else "rejected"
        receipt.reviewer_id = operator["id"]
        receipt.reviewer_name = operator["name"]
        receipt.review_remark = (review_remark or "").strip() or None
        receipt.review_date = now
        receipt.update_date = now
        if action == "approve":
            for item in items:
                allocations = allocation_map[item.order_uid]
                if item.adjustment_id is not None:
                    adjustment = price_adjustments[item.adjustment_id]
                    approved_received = money(
                        allocations["adjustments"].get(item.adjustment_id, {}).get("approved", 0)
                        + item.amount
                    )
                    if approved_received >= money(adjustment.delta_amount):
                        adjustment.status = "resolved"
                order_remaining = money(
                    receivables[item.order_uid]
                    - allocations["approved"]
                    - allocations["settlement_difference"]
                    - item.amount
                    - (item.settlement_difference or 0)
                )
                if order_remaining <= 0:
                    for adjustment in price_adjustments.values():
                        if (
                            adjustment.order_uid == item.order_uid
                            and adjustment.status == "pending"
                            and adjustment.direction == "collect"
                        ):
                            adjustment.status = "resolved"
        session.commit()
        return _receipt_dict(session, receipt, include_items=True)


def accounts_receivable_ledger(
    as_of: str = None,
    page=1,
    page_size=20,
    customer_id=None,
    owner_id=None,
    settlement_status=None,
    query_text="",
    date_from=None,
    date_to=None,
) -> dict:
    date_to = date_to or as_of or datetime.now().strftime("%Y-%m-%d")
    try:
        end_date = datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date_to 必须为 YYYY-MM-DD") from exc

    start_cutoff = None
    if date_from:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date_from 必须为 YYYY-MM-DD") from exc
        if start_date > end_date:
            raise ValueError("date_from 不能晚于 date_to")
        start_cutoff = f"{date_from} 00:00:00"

    cutoff = f"{date_to} 23:59:59"
    with SessionFactory() as session:
        quote_rows = (
            session.query(OrderQuoteVersionTable)
            .filter(
                OrderQuoteVersionTable.status.in_(EFFECTIVE_QUOTE_STATUSES),
                OrderQuoteVersionTable.archive == False,  # noqa: E712
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
            session.query(
                PaymentReceiptItemTable.order_uid,
                func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0),
                func.coalesce(func.sum(PaymentReceiptItemTable.settlement_difference), 0),
            )
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(
                PaymentReceiptItemTable.archive == False,  # noqa: E712
                PaymentReceiptTable.status == "approved",
                PaymentReceiptTable.review_date <= cutoff,
            )
            .group_by(PaymentReceiptItemTable.order_uid)
            .all()
        )
        approved_map = {uid: money(amount) for uid, amount, _ in approved_rows}
        settlement_difference_map = {uid: money(difference) for uid, _, difference in approved_rows}
        pending_rows = (
            session.query(PaymentReceiptItemTable.order_uid, func.coalesce(func.sum(PaymentReceiptItemTable.amount), 0))
            .join(PaymentReceiptTable, PaymentReceiptTable.id == PaymentReceiptItemTable.receipt_id)
            .filter(
                PaymentReceiptItemTable.archive == False,  # noqa: E712
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
        orders = (
            session.query(OrderTable)
            .filter(
                OrderTable.uid.in_(latest_quotes.keys()),
                OrderTable.archive == False,  # noqa: E712
            )
            .all()
            if latest_quotes
            else []
        )
        rows = []
        for order in orders:
            quote = latest_quotes[order.uid]
            if start_cutoff and quote.effective_date < start_cutoff:
                continue
            customer = order.customers[0] if order.customers else None
            if customer_id and (customer is None or customer.id != customer_id):
                continue
            if owner_id and quote.quoter_id != owner_id:
                continue
            if query_text:
                text = query_text.lower()
                if text not in (order.order_id or "").lower() and text not in (order.customer_name or "").lower():
                    continue
            pricing = quote_pricing_state(session, quote)
            receivable = pricing["receivable_amount"]
            received = approved_map.get(order.uid, Decimal("0.00"))
            settlement_difference = settlement_difference_map.get(
                order.uid, Decimal("0.00")
            )
            signed_balance = money(receivable - received - settlement_difference)
            outstanding = money(max(signed_balance, Decimal("0.00")))
            refund_due = money(max(-signed_balance, Decimal("0.00")))
            status = (
                "refund_due"
                if refund_due > 0
                else ("paid" if outstanding == 0 else ("partial" if received > 0 else "unpaid"))
            )
            if settlement_status and settlement_status != status:
                continue
            rows.append({
                "order_uid": order.uid,
                "order_id": order.order_id,
                "customer_id": customer.id if customer else None,
                "customer_name": customer.name if customer else order.customer_name,
                "quoter_id": quote.quoter_id,
                "quoter_name": quote.quoter_name,
                "effective_date": quote.effective_date,
                "weight_snapshot": decimal_json(pricing["weight_snapshot"], WEIGHT),
                "billing_weight": decimal_json(pricing["billing_weight"], WEIGHT),
                "unit_price": decimal_json(quote.unit_price, UNIT_PRICE),
                "surcharge": decimal_json(quote.surcharge),
                "receivable_amount": decimal_json(receivable),
                "received_amount": decimal_json(received),
                "outstanding_amount": decimal_json(outstanding),
                "refund_due": decimal_json(refund_due),
                "signed_balance": decimal_json(signed_balance),
                "settlement_difference": decimal_json(settlement_difference),
                "pending_amount": decimal_json(pending_map.get(order.uid, 0)),
                "settlement_status": status,
            })
        rows.sort(key=lambda item: (item["effective_date"] or "", item["order_id"] or ""), reverse=True)
        totals = {
            "receivable_amount": decimal_json(sum((money(row["receivable_amount"]) for row in rows), Decimal("0"))),
            "received_amount": decimal_json(sum((money(row["received_amount"]) for row in rows), Decimal("0"))),
            "outstanding_amount": decimal_json(sum((money(row["outstanding_amount"]) for row in rows), Decimal("0"))),
            "refund_due": decimal_json(sum((money(row["refund_due"]) for row in rows), Decimal("0"))),
            "settlement_difference": decimal_json(sum((money(row["settlement_difference"]) for row in rows), Decimal("0"))),
            "pending_amount": decimal_json(sum((money(row["pending_amount"]) for row in rows), Decimal("0"))),
            "order_count": len(rows),
        }
        total = len(rows)
        start = (page - 1) * page_size
        return {
            "items": rows[start:start + page_size],
            "totals": totals,
            "total": total,
            "page": page,
            "page_size": page_size,
            "date_from": date_from,
            "date_to": date_to,
        }


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
                OrderQuoteVersionTable.archive == False,  # noqa: E712
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
            pricing = quote_pricing_state(session, quote)
            applied_rate = _rate_for_date(rates, quote.effective_date)
            rate_value = unit_price(applied_rate.rate_per_kg if applied_rate else 0)
            quote_weight = pricing["weight_snapshot"]
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
