"""Role permissions and protection for outbound cargo and box identities."""

from __future__ import annotations

from typing import Iterable, Optional

from data.DB import (
    BoxCostRecordTable,
    CargoOutboundRecordTable,
    OrderTable,
    order_fully_outbound,
)


OUTBOUND_WEIGHT_IMMUTABLE_MESSAGE = (
    "货物已出库，重量不可修改；如需调整重量，请使用新的原单号创建包裹"
)
BOX_IDENTITY_IMMUTABLE_MESSAGE = "箱子已有出库历史，箱号不可修改"
ORIGINAL_NUMBER_IMMUTABLE_MESSAGE = "箱子当前已出库，原单号不可修改；请先撤销出库"
CARGO_REMOVAL_OUTBOUND_MESSAGE = "包裹已出库，不能移除、删除或归档；请先撤销出库"


class OrderEditConflictError(ValueError):
    """The requested mutation conflicts with an outbound fact or concurrent edit."""


PENDING_CARGO_STATUSES = {
    "",
    "0",
    "pending",
    "pending_assign",
    "pending_outbound",
    "in_stock",
    "instock",
}


def cargo_is_outbound_or_later(status) -> bool:
    """Return whether a persisted or tracking status is outbound or later."""
    if status is None:
        return False
    try:
        return float(status) >= 1
    except (TypeError, ValueError):
        normalized = str(status).strip().lower()
        return normalized not in PENDING_CARGO_STATUSES


def cargo_currently_outbound(cargo) -> bool:
    """Current shipment state only; reentry clears status/date but keeps history."""
    return cargo_is_outbound_or_later(cargo.status) or bool(str(cargo.date or "").strip())


def ensure_cargo_removable(cargo) -> None:
    """Call after locking and refreshing the actual cargo row in this transaction."""
    if cargo_currently_outbound(cargo):
        raise OrderEditConflictError(f"{CARGO_REMOVAL_OUTBOUND_MESSAGE}（{cargo.transfer_id or cargo.uid}）")


def box_identity_editable(session, box, *, for_update=False) -> bool:
    """Keep a shipped box's number fixed, including after reentry.

    Historical costs include archived rows, so legacy shipments without a
    dedicated outbound record remain protected after they return to stock.
    """
    if not box.packing_list_uid:
        return True
    if cargo_is_outbound_or_later(box.status) or str(box.date or "").strip():
        return False
    outbound_records = session.query(CargoOutboundRecordTable.id).filter(
        CargoOutboundRecordTable.cargo_uid == box.uid
    )
    costs = session.query(BoxCostRecordTable.id).filter(
        BoxCostRecordTable.box_uid == box.uid
    )
    if for_update:
        # A locking read sees shipments committed while this transaction was
        # waiting for the box lock, even under MySQL repeatable read.
        return (
            outbound_records.with_for_update().first() is None
            and costs.with_for_update().first() is None
        )
    return not (
        session.query(
            outbound_records.exists() | costs.exists()
        ).scalar()
    )


def cargo_original_number_editable(cargo) -> bool:
    """Reentry restores a box's original number editing without erasing history."""
    return not cargo.packing_list_uid or not cargo_currently_outbound(cargo)


def ensure_box_identity_editable(session, box, changes) -> None:
    """Reject real identifier changes before any part of an update is saved."""
    if not box.packing_list_uid:
        return
    number_changed = False
    if "box_number" in changes:
        current_number, next_number = box.box_number, changes["box_number"]
        try:
            current_number, next_number = int(current_number), int(next_number)
        except (TypeError, ValueError):
            pass
        number_changed = current_number != next_number
    if number_changed and not box_identity_editable(session, box, for_update=True):
        raise OrderEditConflictError(BOX_IDENTITY_IMMUTABLE_MESSAGE)
    if (
        "transfer_id" in changes
        and str(box.transfer_id or "").strip() != str(changes["transfer_id"] or "").strip()
        and not cargo_original_number_editable(box)
    ):
        raise OrderEditConflictError(ORIGINAL_NUMBER_IMMUTABLE_MESSAGE)


def ensure_outbound_weight_editable(
    status,
    *,
    current_weight,
    next_weight,
) -> None:
    """Prevent changing the weight of outbound and post-outbound cargo."""
    if not cargo_is_outbound_or_later(status):
        return

    try:
        unchanged = float(current_weight) == float(next_weight)
    except (TypeError, ValueError):
        unchanged = current_weight == next_weight
    if not unchanged:
        raise OrderEditConflictError(OUTBOUND_WEIGHT_IMMUTABLE_MESSAGE)


def build_edit_policy(
    session,
    order_uid: str,
    roles: Optional[Iterable[str]] = None,
    current_user_id: Optional[int] = None,
) -> dict:
    order = (
        session.query(OrderTable.uid, OrderTable.salesman_id)
        .filter(OrderTable.uid == order_uid)
        .first()
    )
    if order is None:
        raise LookupError("订单不存在")
    fully_outbound = order_fully_outbound(session, order_uid)
    roles = set(roles or [])
    box_editor = bool(
        roles.intersection({"admin", "store_manager", "salesperson", "clerk"})
    )
    box_creator = bool(
        roles.intersection({"admin", "store_manager", "salesperson", "worker"})
    )
    box_assigner = bool(
        roles.intersection({"admin", "store_manager", "salesperson", "clerk"})
    )
    authenticated_order_editor = bool(roles)
    salesman_editor = bool(
        "admin" in roles
        or (current_user_id is not None and order.salesman_id == current_user_id)
    )
    policy = {
        "order_fields": authenticated_order_editor,
        "transportation": authenticated_order_editor,
        "order_weight": authenticated_order_editor,
        "salesman": salesman_editor,
        "customer_assignment": authenticated_order_editor,
        "cargo_content": authenticated_order_editor,
        "cargo_weight": authenticated_order_editor,
        "box_content": box_editor,
        "box_weight": box_creator,
        "tracking_numbers": box_editor,
        "box_workers": box_editor,
        "box_membership": box_assigner,
        "archive_or_delete": authenticated_order_editor,
    }
    policy.update({
        "fully_outbound": fully_outbound,
    })
    return {
        "edit_policy": policy,
    }
