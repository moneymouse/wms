"""Explicit outbound actions, composed with pure updates in one transaction.

All callers lock orders before cargo, use the same guards and preserve the
first outbound date and cost. Tracking registration belongs after commit.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime

from flask import has_request_context

from data.DB import (
    BoxCostRecordTable, CargoOutboundRecordTable, CargoTable, OrderTable,
    TransportationModeTable,
)
from data.order_version import (
    new_correlation_id, normalize_operator, record_mutation, snapshot_order,
)
from services.order_edit_policy import OrderEditConflictError, cargo_is_outbound_or_later, cargo_currently_outbound

OUTBOUND_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
logger = logging.getLogger(__name__)


@dataclass
class WaybillImportResult:
    registered: list = field(default_factory=list)
    successful: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def parse_confirm_outbound(value=True):
    """Accept booleans in JSON and true/false form fields; reject typos."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError("confirm_outbound must be true or false")


def _occurred_at(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 32 or not ("T" in value or " " in value):
        raise ValueError("occurred_at must be an ISO datetime")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("occurred_at must be an ISO datetime")
    return value


def _lock_cargos(session, uids):
    """Resolve ownership, lock sorted orders, then re-read/lock sorted cargo."""
    uids = sorted(set(uids))
    candidates = session.query(CargoTable.uid, CargoTable.target_order_uid).filter(
        CargoTable.uid.in_(uids)
    ).all()
    owners = {row.uid: row.target_order_uid for row in candidates}
    if set(owners) != set(uids):
        raise LookupError("货物不存在")
    order_uids = sorted({uid for uid in owners.values() if uid})
    if order_uids:
        session.query(OrderTable).filter(OrderTable.uid.in_(order_uids)).order_by(
            OrderTable.uid.asc()
        ).populate_existing().with_for_update().all()
    rows = session.query(CargoTable).filter(CargoTable.uid.in_(uids)).order_by(
        CargoTable.uid.asc()
    ).populate_existing().with_for_update().all()
    if {row.uid for row in rows} != set(uids):
        raise LookupError("货物不存在或已删除，请刷新后重试")
    packing_uids = sorted({row.packing_list_uid for row in rows if row.packing_list_uid})
    if packing_uids:
        from data.packing.PackingList import PackingListTable
        session.query(PackingListTable).filter(PackingListTable.uid.in_(packing_uids)).order_by(
            PackingListTable.uid.asc()
        ).populate_existing().with_for_update().all()
    for row in rows:
        if row.target_order_uid != owners[row.uid]:
            raise OrderEditConflictError("货物归属已变化，请刷新后重试")
        if row.archive:
            raise ValueError("已归档货物不能修改或出库")
    return rows, order_uids


def _guard_outbound(session, cargo):
    if not cargo.target_order_uid:
        raise ValueError("货物必须先归属订单才能出库")
    order = session.query(OrderTable).filter_by(uid=cargo.target_order_uid).first()
    if order is None or order.archive:
        raise ValueError("出库订单不存在或已归档")
    if cargo.packing_list_uid:
        from data.packing.PackingList import PackingListTable
        packing = session.query(PackingListTable).filter_by(
            uid=cargo.packing_list_uid
        ).with_for_update().first()
        if packing is None or packing.archive:
            raise ValueError("装箱单不存在或已归档")
        customers = {customer.id for customer in order.customers}
        if packing.customer_id is not None and customers and packing.customer_id not in customers:
            order_customer_ids = ", ".join(str(customer_id) for customer_id in sorted(customers))
            raise ValueError(
                "箱子与订单的客户归属不一致"
                f"（原单号：{cargo.transfer_id or '未填写'}；"
                f"装箱单：{packing.list_number or packing.uid}；"
                f"箱号：{cargo.box_number or '未填写'}；"
                f"订单号：{order.order_id or order.uid}；"
                f"装箱单客户ID：{packing.customer_id}；"
                f"订单客户ID：{order_customer_ids}）"
            )
    try:
        weight = float(cargo.weight or 0)
    except (TypeError, ValueError):
        weight = 0
    if not math.isfinite(weight) or weight <= 0:
        raise ValueError("出库前货物重量必须大于0")
    return order


def freeze_box_cost(session, cargo, recorded_at):
    """Freeze the current shipment's cost, retaining any earlier archived costs."""
    if not cargo.packing_list_uid:
        return
    order = _guard_outbound(session, cargo)
    if session.query(BoxCostRecordTable.id).filter_by(box_uid=cargo.uid, archive=False).first():
        raise OrderEditConflictError("箱子已有成本快照，不能覆盖原成本")
    name = str(order.transportation or "").strip()
    mode = session.query(TransportationModeTable).filter_by(
        name=name, archive=False
    ).first() if name else None
    cost = float(mode.cost) if mode else 0.0
    weight = float(cargo.weight)
    session.add(BoxCostRecordTable(
        box_uid=cargo.uid, packing_list_uid=cargo.packing_list_uid,
        order_uid=order.uid, transportation_mode_id=mode.id if mode else None,
        transportation_name=mode.name if mode else name,
        waybill_id=str(cargo.waybill_id or "").strip(), weight=weight,
        unit_cost=cost, total_cost=round(cost * weight, 4), create_date=recorded_at,
    ))


def confirm_in_session(session, cargo, *, occurred_at=None, source="explicit", operator=None):
    """Confirm a locked row; caller owns transaction and order versioning."""
    actor = normalize_operator(operator)
    # Trusted jobs may call without a request/operator. External action contexts
    # always carry roles and must pass this check even if HTTP already authorized.
    if (operator is not None or has_request_context()) and not OUTBOUND_ROLES.intersection(actor["roles"]):
        raise PermissionError("Permission denied")
    if cargo_is_outbound_or_later(cargo.status):
        return False
    _guard_outbound(session, cargo)
    occurred_at = _occurred_at(occurred_at)
    now = time.strftime("%Y-%m-%d %H:%M")
    # Row locks serialize MySQL. A conditional write also protects SQLite,
    # whose FOR UPDATE is a no-op, and detects a concurrently changed status.
    old_status = cargo.status
    changed = session.query(CargoTable).filter(
        CargoTable.uid == cargo.uid,
        CargoTable.status == old_status if old_status is not None else CargoTable.status.is_(None),
        CargoTable.target_order_uid == cargo.target_order_uid,
        CargoTable.archive == False,  # noqa: E712
    ).update({"status": 1, "date": now, "update_date": now}, synchronize_session=False)
    if changed != 1:
        raise OrderEditConflictError("货物出库状态已变化，请刷新后重试")
    freeze_box_cost(session, cargo, now)
    cargo.status = 1
    cargo.date = now
    cargo.update_date = now
    session.add(CargoOutboundRecordTable(
        cargo_uid=cargo.uid, order_uid=cargo.target_order_uid,
        occurred_at=occurred_at, recorded_at=now, source=source,
        operator_id=actor["id"], operator_name=actor["name"],
    ))
    return True


def _versions(session, before, *, action, operator=None, shipped=False):
    session.flush()
    correlation = new_correlation_id()
    for uid, snapshot in before.items():
        record_mutation(
            session, uid, before=snapshot, after=snapshot_order(session, uid),
            action=action, summary=("登记货物出库" if action == "cargo_outbound" else
                                  "更新货物资料并登记出库" if shipped else "更新货物资料"),
            correlation_id=correlation, operator_payload=operator,
        )


def update_cargo_details(uid, data, *, model=None, confirm_outbound=False,
                         source="details", operator=None, occurred_at=None):
    """Pure update by default; compatibility callers explicitly request composition."""
    from data import DB
    from data.packing import box_model
    with DB.SessionFactory() as session:
        try:
            rows, order_uids = _lock_cargos(session, [uid])
            cargo = rows[0]
            if model is box_model and not cargo.packing_list_uid:
                raise LookupError("箱子不存在")
            old_waybill = str(cargo.waybill_id or "").strip()
            before = {oid: snapshot_order(session, oid) for oid in order_uids}
            model = model or (box_model if cargo.packing_list_uid else DB.cargo_model)
            if cargo.packing_list_uid:
                model.update(uid, data, session=session, record_version=False, return_details=True)
            else:
                model.update(uid, data, session=session, record_version=False)
            shipped = False
            # Only a submitted, nonempty number requests legacy supplemental registration.
            if confirm_outbound and "waybill_id" in data and str(cargo.waybill_id or "").strip():
                shipped = confirm_in_session(session, cargo, source=source, operator=operator,
                                             occurred_at=occurred_at)
            new_waybill = str(cargo.waybill_id or "").strip()
            _versions(session, before, action="box_updated" if cargo.packing_list_uid else "cargo_updated", operator=operator, shipped=shipped)
            result = {"updated": True, "old_waybill_id": old_waybill,
                      "new_waybill_id": new_waybill, "waybill_changed": old_waybill != new_waybill,
                      "outbound_confirmed": shipped}
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise


def confirm_outbound(uids, *, occurred_at=None, source="explicit", operator=None):
    """Atomic batch confirmation, including cargo without a waybill number."""
    from data import DB
    occurred_at = _occurred_at(occurred_at)
    with DB.SessionFactory() as session:
        try:
            rows, order_uids = _lock_cargos(session, uids)
            before = {oid: snapshot_order(session, oid) for oid in order_uids}
            confirmed = [row.uid for row in rows if confirm_in_session(
                session, row, occurred_at=occurred_at, source=source, operator=operator
            )]
            _versions(session, before, action="cargo_outbound", operator=operator)
            session.commit()
            return {"confirmed": confirmed, "unchanged": [row.uid for row in rows if row.uid not in confirmed]}
        except Exception:
            session.rollback()
            raise


def undo_outbound(uid, *, operator=None):
    """Return cargo/boxes to stock, retaining shipment, financial and version facts."""
    from data import DB
    actor = normalize_operator(operator)
    if (operator is not None or has_request_context()) and not set(actor["roles"]).intersection({"admin", "store_manager"}):
        raise PermissionError("只有管理员或店长可以撤销出库")
    with DB.SessionFactory() as session:
        try:
            rows, order_uids = _lock_cargos(session, [uid])
            cargo = rows[0]
            if not cargo_currently_outbound(cargo):
                raise ValueError("包裹当前未出库，无需撤销")
            before = {order_uid: snapshot_order(session, order_uid) for order_uid in order_uids}
            old_status = cargo.status
            now = time.strftime("%Y-%m-%d %H:%M")
            changed = session.query(CargoTable).filter(
                CargoTable.uid == uid,
                CargoTable.status == old_status if old_status is not None else CargoTable.status.is_(None),
                CargoTable.target_order_uid == cargo.target_order_uid,
                CargoTable.archive == False,  # noqa: E712
            ).update({"status": 0, "date": None, "waybill_id": "", "update_date": now}, synchronize_session=False)
            if changed != 1:
                raise OrderEditConflictError("包裹出库状态已变化，请刷新后重试")
            cargo.status, cargo.date, cargo.waybill_id, cargo.update_date = 0, None, "", now
            session.query(BoxCostRecordTable).filter(
                BoxCostRecordTable.box_uid == uid, BoxCostRecordTable.archive == False,  # noqa: E712
            ).update({"archive": True}, synchronize_session=False)
            session.flush()
            correlation_id = new_correlation_id()
            for order_uid in order_uids:
                record_mutation(session, order_uid, before=before[order_uid], after=snapshot_order(session, order_uid),
                                action="box_shipment_undone" if cargo.packing_list_uid else "cargo_shipment_undone",
                                summary="撤销箱子出库" if cargo.packing_list_uid else "撤销包裹出库",
                                operator_payload=operator, correlation_id=correlation_id)
            session.commit()
            return {"uid": uid, "status": 0, "date": None, "waybill_id": ""}
        except Exception:
            session.rollback()
            raise


def update_waybill_table(session_factory, transfer_map, *, confirm_outbound=True,
                         operator=None, return_details=False):
    """Commit each order independently and report only its failed import items."""
    result = WaybillImportResult()
    normalized = {}
    for original, waybill in (transfer_map or {}).items():
        original = str(original or "").strip()
        waybill = str(waybill or "").strip()
        if not original:
            result.failed.append({
                "uid": None, "order_uid": None, "order_id": "",
                "transfer_id": original, "waybill_id": waybill,
                "code": 400, "reason": "原单号未填写",
            })
        else:
            normalized[original] = waybill
    if not normalized:
        return result if return_details else result.registered

    # Resolve the submitted rows once; every order then owns its own transaction.
    with session_factory() as session:
        candidates = session.query(
            CargoTable.uid, CargoTable.target_order_uid, CargoTable.transfer_id,
        ).filter(CargoTable.transfer_id.in_(normalized)).order_by(CargoTable.uid.asc()).all()
        order_uids = {row.target_order_uid for row in candidates if row.target_order_uid}
        order_numbers = dict(session.query(OrderTable.uid, OrderTable.order_id).filter(
            OrderTable.uid.in_(order_uids)
        ).all()) if order_uids else {}

    groups = {}
    matched = set()
    for candidate in candidates:
        original = str(candidate.transfer_id or "").strip()
        if original not in normalized:
            continue
        matched.add(original)
        item = {
            "uid": candidate.uid, "order_uid": candidate.target_order_uid,
            "order_id": order_numbers.get(candidate.target_order_uid) or candidate.target_order_uid or "",
            "transfer_id": original, "waybill_id": normalized[original],
        }
        # Unassigned cargo have no shared order and are isolated individually.
        key = (candidate.target_order_uid, None if candidate.target_order_uid else candidate.uid)
        groups.setdefault(key, []).append(item)
    for original, waybill in normalized.items():
        if original in matched:
            continue
        result.failed.append({
            "uid": None, "order_uid": None, "order_id": "",
            "transfer_id": original, "waybill_id": waybill,
            "code": 404 if waybill else 400,
            "reason": "系统未找到该原单号" if waybill else "转单号未填写",
        })

    for (expected_order_uid, _), items in groups.items():
        try:
            with session_factory() as session:
                try:
                    rows, order_uids = _lock_cargos(session, [item["uid"] for item in items])
                    expected_items = {item["uid"]: item for item in items}
                    for row in rows:
                        if row.target_order_uid != expected_order_uid:
                            raise OrderEditConflictError("货物归属已变化，请刷新后重试")
                        if str(row.transfer_id or "").strip() != expected_items[row.uid]["transfer_id"]:
                            raise OrderEditConflictError("原单号已变化，请刷新后重试")
                        if not expected_items[row.uid]["waybill_id"]:
                            raise ValueError(f"原单号 {row.transfer_id} 的转单号未填写")
                    before = {oid: snapshot_order(session, oid) for oid in order_uids}
                    register = []
                    shipped = False
                    now = time.strftime("%Y-%m-%d %H:%M")
                    for row in rows:
                        next_waybill = expected_items[row.uid]["waybill_id"]
                        if next_waybill != str(row.waybill_id or "").strip():
                            row.waybill_id = next_waybill
                            row.update_date = now
                            register.append((row.uid, next_waybill))
                        if confirm_outbound:
                            shipped = confirm_in_session(session, row, source="waybill_import", operator=operator) or shipped
                    _versions(session, before, action="waybills_imported", operator=operator, shipped=shipped)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            result.registered.extend(register)
            result.successful.extend(items)
        except Exception as error:
            if isinstance(error, PermissionError):
                code = 403
            elif isinstance(error, OrderEditConflictError):
                code = 409
            elif isinstance(error, LookupError):
                code = 404
            elif isinstance(error, ValueError):
                code = 400
            else:
                code = 500
                logger.exception("Waybill import failed for order %s", expected_order_uid)
            result.failed.extend({**item, "code": code, "reason": str(error)} for item in items)
    return result if return_details else result.registered
