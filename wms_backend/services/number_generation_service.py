"""Generate and save internal tracking numbers only on an explicit action."""

import secrets
import re
import time
from contextlib import contextmanager

from sqlalchemy import text

from Auth import get_payload_roles
from data.DB import CargoTable, OrderTable
from data.database import SessionFactory
from data.order_version import record_mutation, snapshot_order
from data.packing.PackingList import PackingListTable
from services.order_edit_policy import (
    ORIGINAL_NUMBER_IMMUTABLE_MESSAGE,
    OrderEditConflictError,
    cargo_original_number_editable,
)


GENERATION_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
MAX_GENERATION_ATTEMPTS = 100
GENERATION_LOCK_NAME = "wms:auto-generated-number:v1"
_UNSET = object()
MULTI_PIECE_NUMBER = re.compile(r"^(D8[0-9]{8}L)-([1-9][0-9]*)$")


class NumberGenerationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def generation_options(body):
    """Accept an optional saved value, never caller-supplied numbers or fields."""
    if not isinstance(body, dict) or set(body) - {"expected_value"}:
        raise NumberGenerationError(400, "请求只能包含 expected_value")
    if "expected_value" in body:
        value = body["expected_value"]
        if value is not None and not isinstance(value, str):
            raise NumberGenerationError(400, "expected_value 必须为字符串或 null")
    return body


def packing_generation_options(body):
    """Validate a batch selection and optional optimistic concurrency values."""
    if not isinstance(body, dict) or set(body) - {"box_uids", "expected_values", "multi_piece"}:
        raise NumberGenerationError(400, "请求只能包含 box_uids、expected_values 和 multi_piece")
    multi_piece = body.get("multi_piece", False)
    if not isinstance(multi_piece, bool):
        raise NumberGenerationError(400, "multi_piece 必须为布尔值")
    box_uids = body.get("box_uids")
    if not isinstance(box_uids, list) or not box_uids or any(
        not isinstance(uid, str) or not uid.strip() for uid in box_uids
    ):
        raise NumberGenerationError(400, "box_uids 必须为非空的箱子 UID 数组")
    if len(set(box_uids)) != len(box_uids):
        raise NumberGenerationError(400, "box_uids 不能重复")
    expected = body.get("expected_values")
    if "expected_values" in body and (
        not isinstance(expected, dict)
        or set(expected) != set(box_uids)
        or any(value is not None and not isinstance(value, str) for value in expected.values())
    ):
        raise NumberGenerationError(400, "expected_values 必须包含每个所选箱子的字符串或 null 原单号")
    return {"box_uids": box_uids, "expected_values": expected, "multi_piece": multi_piece}


@contextmanager
def _generation_session():
    """Serialize generators across workers without adding a unique constraint.

    MySQL advisory locks belong to a connection, not a transaction. Pin that
    connection until the write commits/rolls back and the lock is released.
    SQLite obtains its write lock before any reads with BEGIN IMMEDIATE.
    """
    with SessionFactory() as probe:
        engine = probe.get_bind()
    with engine.connect() as connection:
        dialect = connection.dialect.name
        locked = False
        try:
            if dialect in {"mysql", "mariadb"}:
                acquired = connection.execute(
                    text("SELECT GET_LOCK(:name, 10)"),
                    {"name": GENERATION_LOCK_NAME},
                ).scalar()
                if acquired != 1:
                    raise NumberGenerationError(503, "号码生成繁忙，请稍后重试")
                locked = True
                # Start the business transaction after taking the lock so its
                # repeatable-read snapshot includes the previous generator.
                connection.commit()
            elif dialect != "sqlite":
                raise NumberGenerationError(503, "当前数据库暂不支持自动生成号码")

            with SessionFactory(bind=connection) as session:
                try:
                    if dialect == "sqlite":
                        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        finally:
            if locked:
                try:
                    connection.rollback()
                    released = connection.execute(
                        text("SELECT RELEASE_LOCK(:name)"),
                        {"name": GENERATION_LOCK_NAME},
                    ).scalar()
                    connection.commit()
                    if released != 1:
                        connection.invalidate()
                except Exception:
                    # Never return a connection holding a named lock to the
                    # pool, including when cleanup follows a failed write.
                    connection.invalidate()


def _authorize(operator_payload):
    if not GENERATION_ROLES.intersection(get_payload_roles(operator_payload)):
        raise NumberGenerationError(403, "Permission denied")


def _check_expected(current, expected):
    if expected is not _UNSET and str(current or "") != str(expected or ""):
        raise OrderEditConflictError("号码已被修改，请刷新后重试")


def _lock_order(session, order_uid):
    order = session.query(OrderTable).filter_by(uid=order_uid).with_for_update().first()
    if order is None or order.archive:
        raise NumberGenerationError(404, "订单不存在或已归档")
    return order


def _unused_number(session):
    for _ in range(MAX_GENERATION_ATTEMPTS):
        # Both generated fields use D/L around the existing nine-digit body.
        # Preserve leading zeroes and share one collision pool across fields.
        candidate = f"D8{secrets.randbelow(100_000_000):08d}L"
        if session.query(OrderTable.uid).filter_by(order_id=candidate).first():
            continue
        if session.query(CargoTable.uid).filter_by(transfer_id=candidate).first():
            continue
        # A multi-piece master remains reserved while any of its children exist.
        if session.query(CargoTable.uid).filter(CargoTable.transfer_id.startswith(candidate + "-", autoescape=True)).first():
            continue
        if session.query(OrderTable.uid).filter(OrderTable.order_id.startswith(candidate + "-", autoescape=True)).first():
            continue
        return candidate
    raise NumberGenerationError(503, "暂时无法生成未使用的号码，请重试")


def _save_number(session, order, target, field, operator_payload):
    before = snapshot_order(session, order.uid)
    number = _unused_number(session)
    setattr(target, field, number)
    target.update_date = time.strftime("%Y-%m-%d %H:%M")
    session.flush()
    version = record_mutation(
        session, order.uid, before=before, after=snapshot_order(session, order.uid),
        action="order_number_generated" if field == "order_id" else "original_number_generated",
        summary="自动生成订单号" if field == "order_id" else "自动生成原单号",
        operator_payload=operator_payload,
    )
    return {
        "uid": target.uid,
        "order_uid": order.uid,
        field: number,
        "current_version": version.version_no,
    }


def generate_order_number(order_uid, operator_payload, *, expected_value=_UNSET):
    _authorize(operator_payload)
    with _generation_session() as session:
        order = _lock_order(session, order_uid)
        _check_expected(order.order_id, expected_value)
        return _save_number(session, order, order, "order_id", operator_payload)


def generate_original_number(order_uid, cargo_uid, operator_payload, *, expected_value=_UNSET):
    _authorize(operator_payload)
    with _generation_session() as session:
        # Use the same order -> cargo -> packing-list lock order as other
        # mutations, and verify membership after taking the cargo lock.
        order = _lock_order(session, order_uid)
        cargo = session.query(CargoTable).filter_by(uid=cargo_uid).with_for_update().first()
        if cargo is None or cargo.archive:
            raise NumberGenerationError(404, "货物不存在或已归档")
        if cargo.target_order_uid != order_uid:
            raise OrderEditConflictError("货物不属于当前订单，请刷新后重试")
        if cargo.packing_list_uid:
            packing = session.query(PackingListTable).filter_by(
                uid=cargo.packing_list_uid
            ).with_for_update().first()
            if packing is None or packing.archive:
                raise NumberGenerationError(409, "装箱单不存在或已归档")
            if not cargo_original_number_editable(cargo):
                raise OrderEditConflictError(ORIGINAL_NUMBER_IMMUTABLE_MESSAGE)
        _check_expected(cargo.transfer_id, expected_value)
        return _save_number(session, order, cargo, "transfer_id", operator_payload)


def generate_packing_original_numbers(
    packing_uid, box_uids, operator_payload, *, expected_values=None, multi_piece=False,
):
    """Generate only the selected boxes, including boxes not yet in an order.

    Validate and lock the whole selection before allocating anything. Assigned
    boxes retain order history, while every number is persisted in one batch
    transaction so an invalid or stale box cannot leave a partial result.
    """
    _authorize(operator_payload)
    body = {"box_uids": box_uids, "multi_piece": multi_piece}
    if expected_values is not None:
        body["expected_values"] = expected_values
    options = packing_generation_options(body)
    with _generation_session() as session:
        memberships = dict(session.query(CargoTable.uid, CargoTable.target_order_uid).filter(
            CargoTable.uid.in_(options["box_uids"])
        ).all())
        order_uids = sorted({value for value in memberships.values() if value})
        for order_uid in order_uids:
            _lock_order(session, order_uid)
        boxes = session.query(CargoTable).filter(
            CargoTable.uid.in_(options["box_uids"])
        ).order_by(CargoTable.uid).with_for_update().populate_existing().all()
        packing = session.query(PackingListTable).filter_by(
            uid=packing_uid
        ).with_for_update().first()
        if packing is None or packing.archive:
            raise NumberGenerationError(404, "装箱单不存在或已归档")
        if len(boxes) != len(options["box_uids"]) or any(box.archive for box in boxes):
            raise NumberGenerationError(404, "所选箱子不存在或已归档")
        for box in boxes:
            if box.packing_list_uid != packing_uid:
                raise OrderEditConflictError("所选箱子不属于当前装箱单，请刷新后重试")
            if box.target_order_uid != memberships[box.uid]:
                raise OrderEditConflictError("箱子的订单归属已变更，请刷新后重试")
            if not cargo_original_number_editable(box):
                raise OrderEditConflictError(ORIGINAL_NUMBER_IMMUTABLE_MESSAGE)
            if options["expected_values"] is not None:
                _check_expected(box.transfer_id, options["expected_values"][box.uid])

        if not multi_piece and any(str(box.transfer_id or "").strip() for box in boxes):
            raise NumberGenerationError(409, "所选箱子已有原单号，不能替换；一票多件请勾选后仅为空号箱子追加")
        new_numbers = _multi_piece_numbers(session, boxes) if multi_piece else None
        changed_order_uids = {box.target_order_uid for box in boxes
                              if new_numbers is None or box.uid in new_numbers}
        before = {order_uid: snapshot_order(session, order_uid) for order_uid in order_uids
                  if order_uid in changed_order_uids}
        generated = {}
        for box in boxes:
            if new_numbers is None or box.uid in new_numbers:
                box.transfer_id = _unused_number(session) if new_numbers is None else new_numbers[box.uid]
                box.update_date = time.strftime("%Y-%m-%d %H:%M")
            # This session disables autoflush; each candidate must see earlier
            # numbers in the same batch before checking for collisions.
            session.flush()
            generated[box.uid] = {
                "uid": box.uid, "order_uid": box.target_order_uid,
                "transfer_id": box.transfer_id,
            }
        for order_uid in before:
            version = record_mutation(
                session, order_uid, before=before[order_uid],
                after=snapshot_order(session, order_uid), action="original_number_generated",
                summary="生成一票多件原单号" if multi_piece else "批量自动生成装箱单原单号", operator_payload=operator_payload,
            )
            for box in boxes:
                if box.target_order_uid == order_uid:
                    generated[box.uid]["current_version"] = version.version_no
        return {
            "packing_list_uid": packing_uid, "generated_count": len(boxes) if new_numbers is None else len(new_numbers),
            "boxes": [generated[box_uid] for box_uid in options["box_uids"]],
        }


def _multi_piece_numbers(session, boxes):
    """Infer one existing master and append without replacing saved identities."""
    masters = set()
    for box in boxes:
        if not str(box.transfer_id or "").strip():
            continue
        match = MULTI_PIECE_NUMBER.fullmatch(box.transfer_id)
        if match is None:
            raise NumberGenerationError(409, "所选箱子包含普通原单号，不能直接生成一票多件")
        masters.add(match[1])
    if len(masters) > 1:
        raise NumberGenerationError(409, "所选箱子属于不同主单号，请选择同一票的箱子")
    empty = [box for box in boxes if not str(box.transfer_id or "").strip()]
    if not empty:
        return {}
    master = next(iter(masters)) if masters else _unused_number(session)
    # Include unselected and archived boxes and the shared order-number pool.
    used = [value for (value,) in session.query(CargoTable.transfer_id).filter(
        CargoTable.transfer_id.startswith(master + "-", autoescape=True)).all()]
    used += [value for (value,) in session.query(OrderTable.order_id).filter(
        OrderTable.order_id.startswith(master + "-", autoescape=True)).all()]
    last = max((int(match[2]) for value in used
                if (match := MULTI_PIECE_NUMBER.fullmatch(value))), default=0)
    return {box.uid: f"{master}-{last + index}"
            for index, box in enumerate(sorted(empty, key=lambda box: (box.box_number or 0, box.uid)), start=1)}
