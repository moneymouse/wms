"""Order-scoped exceptions, follow-up history, and transactional notices."""

from datetime import datetime
import hashlib
import json
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from data.DB import CargoTable, OrderTable
from data.database import SessionFactory
from data.order_exception import OrderExceptionHistoryTable, OrderExceptionTable
from data.user.User import UserTable
from services.message_service import MessageConflictError, send_message


class ExceptionConflictError(ValueError):
    """The business state or an idempotent request conflicts with this action."""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _text(value, field, maximum, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field}必须为文字")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field}不能为空且不得超过 {maximum} 字")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise ValueError(f"{field}包含无效字符")
    return text


def _id(value, field):
    text = str(value)
    if isinstance(value, bool) or not text.isascii() or not text.isdigit() or not 1 <= int(value) <= 2147483647:
        raise ValueError(f"{field}无效")
    return int(value)


def _actor(session, actor):
    actor = actor or {}
    try:
        user_id = _id(actor.get("user_id") or actor.get("id") or actor.get("uid"), "员工编号")
    except (ValueError, AttributeError) as exc:
        raise PermissionError("无法识别当前员工") from exc
    user = session.get(UserTable, user_id)
    if user is None or user.status != "approved":
        raise PermissionError("当前员工没有异常订单访问权限")
    return user, {role.name for role in user.roles}


def _owner(session, order):
    owner = session.get(UserTable, order.salesman_id) if order.salesman_id else None
    if owner is None or owner.status != "approved" or not {role.name for role in owner.roles}.intersection({"salesperson", "admin"}):
        raise ExceptionConflictError("订单没有有效业务员，请先指定已审批的业务负责人")
    return owner


def _reader(session, actor):
    user, roles = _actor(session, actor)
    if not roles.intersection({"salesperson", "admin"}):
        raise PermissionError("仅业务员或管理员可以查看异常订单")
    return user, roles


def _body(body, allowed):
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为 JSON 对象")
    if set(body) - set(allowed):
        raise ValueError("请求包含不支持的异常字段")
    return body


def _digest(values):
    encoded = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event(action, source, event_key, actor_id=None):
    key = _text(event_key, "事件编号", 128)
    return f"exception:{action}:{source}:{_digest([actor_id, key])}"


def _replay(session, key, digest):
    history = session.query(OrderExceptionHistoryTable).filter_by(event_key=key).with_for_update().first()
    if history is None:
        return None
    if history.request_digest != digest:
        raise ExceptionConflictError("事件编号已用于另一项异常操作，请刷新后重试")
    # Match the current history read under MySQL REPEATABLE READ. A plain
    # session.get could see a pre-registration snapshot or an old case status.
    case = session.query(OrderExceptionTable).filter_by(uid=history.exception_uid).populate_existing().with_for_update().first()
    if case is None:
        raise ExceptionConflictError("异常历史对应的记录不存在")
    return case


def _history(session, case, *, key, digest, action, note, source, actor=None, tracking_status=None):
    session.add(OrderExceptionHistoryTable(
        uid=uuid.uuid4().hex, exception_uid=case.uid, event_key=key,
        request_digest=digest, action=action, note=note, source=source,
        actor_id=actor.id if actor else None, actor_name=actor.name if actor else None,
        tracking_status=tracking_status, created_at=_now(),
    ))
    session.flush()


def register_exception(session, *, order_uid, cargo_uid=None, reason, source, event_key,
                       actor=None, tracking_status=None, expected_waybill_id=None):
    """Register an event in the caller's transaction; never commit or close it.

    Lock the order before its case so assignment and simultaneous callbacks are
    serialized. An event key survives resolution and prevents retries reopening
    a case. Different events reuse an open case for the same order/parcel scope.
    """
    order_uid = _text(order_uid, "订单编号", 32)
    cargo_uid = _text(cargo_uid, "包裹编号", 32, required=False)
    reason = _text(reason, "异常理由", 2000)
    expected_waybill_id = _text(expected_waybill_id, "预期转单号", 256, required=False)
    if source not in {"manual", "17track"}:
        raise ValueError("异常来源无效")
    tracking_status = _text(tracking_status, "物流状态", 64, required=False)
    # Preserve caller-owned pending changes before locked populate_existing
    # reads; the project factory deliberately has autoflush disabled.
    session.flush()
    user, roles = _actor(session, actor) if source == "manual" else (None, set())
    order = session.query(OrderTable).filter_by(uid=order_uid).populate_existing().with_for_update().first()
    if order is None:
        raise LookupError("订单不存在")
    if source == "manual":
        if not roles.intersection({"admin", "clerk", "salesperson"}):
            raise PermissionError("仅文员、业务员或管理员可以登记异常")
        if not roles.intersection({"admin", "clerk"}) and order.salesman_id != user.id:
            raise PermissionError("只能登记本人负责订单的异常")
    owner = _owner(session, order)
    cargo = None
    if cargo_uid:
        cargo = session.query(CargoTable).filter_by(uid=cargo_uid).populate_existing().with_for_update().first()
        if cargo is None or cargo.target_order_uid != order.uid or cargo.archive:
            raise LookupError("包裹不存在或不属于此订单")
        if expected_waybill_id is not None and (cargo.waybill_id or "").strip() != expected_waybill_id:
            raise ExceptionConflictError("包裹转单号已变化，请刷新后重试")
    elif expected_waybill_id is not None:
        raise ValueError("核对转单号需要指定包裹")
    key = _event("registered", source, event_key, user.id if user else None)
    digest = _digest({"action": "registered", "order_uid": order_uid, "cargo_uid": cargo_uid,
                      "note": reason, "source": source, "actor_id": user.id if user else None,
                      "tracking_status": tracking_status})
    replay = _replay(session, key, digest)
    if replay is not None:
        return replay
    try:
        # The savepoint covers the case, history and notice as one unit. The
        # surrounding business transaction remains owned by the caller.
        with session.begin_nested():
            case = session.query(OrderExceptionTable).filter_by(
                order_uid=order_uid, cargo_uid=cargo_uid, status="open",
            ).order_by(OrderExceptionTable.created_at.asc()).with_for_update().first()
            now = _now()
            if case is None:
                case = OrderExceptionTable(
                    uid=uuid.uuid4().hex, order_uid=order_uid, order_id=order.order_id,
                    cargo_uid=cargo_uid, origin_id=cargo.origin_id if cargo else None,
                    transfer_id=cargo.transfer_id if cargo else None,
                    waybill_id=cargo.waybill_id if cargo else None, salesman_id=owner.id,
                    salesman_name=owner.name, reason=reason, source=source, status="open",
                    created_at=now, updated_at=now,
                )
                session.add(case)
                session.flush()
            else:
                case.updated_at = now
            _history(session, case, key=key, digest=digest, action="registered", note=reason,
                     source=source, actor=user, tracking_status=tracking_status)
            scope = f"订单 {order.order_id or order.uid}"
            if cargo:
                scope += f" / 包裹 {cargo.transfer_id or cargo.origin_id or cargo.uid}"
            send_message(
                session, recipient_id=owner.id, title="订单异常待跟进", body=f"{scope}\n{reason}",
                category="order_exception", source_name=user.name if user else "17TRACK",
                action_path=f"/order-exceptions?exception_uid={case.uid}",
                business_type="order_exception", business_id=case.uid, event_key=key,
            )
    except MessageConflictError as exc:
        raise ExceptionConflictError(str(exc)) from exc
    except IntegrityError:
        # A reused key from another order can race despite per-order locking.
        replay = _replay(session, key, digest)
        if replay is None:
            raise
        return replay
    return case


def _summary(case, order, user):
    own_open = case.status == "open" and order.salesman_id == user.id
    owner = order.salesman
    return {
        "uid": case.uid, "order_uid": case.order_uid, "order_id": case.order_id,
        "cargo_uid": case.cargo_uid, "origin_id": case.origin_id, "transfer_id": case.transfer_id,
        "waybill_id": case.waybill_id,
        "salesman_id": order.salesman_id, "salesman_name": owner.name if owner else None,
        "reason": case.reason, "source": case.source, "status": case.status,
        "created_at": case.created_at, "updated_at": case.updated_at, "resolved_at": case.resolved_at,
        "can_followup": own_open, "can_resolve": own_open,
    }


def _detail(session, case, order, user):
    data = _summary(case, order, user)
    data["history"] = [history.to_dict() for history in session.query(OrderExceptionHistoryTable).filter_by(
        exception_uid=case.uid,
    ).order_by(OrderExceptionHistoryTable.created_at.asc(), OrderExceptionHistoryTable.uid.asc()).all()]
    return data


def create_exception(body, actor):
    body = _body(body, {"order_uid", "cargo_uid", "reason", "event_key"})
    with SessionFactory() as session:
        case = register_exception(session, order_uid=body.get("order_uid"), cargo_uid=body.get("cargo_uid"),
                                  reason=body.get("reason"), source="manual", event_key=body.get("event_key"), actor=actor)
        user, roles = _actor(session, actor)
        order = session.get(OrderTable, case.order_uid)
        can_read = "admin" in roles or ("salesperson" in roles and order.salesman_id == user.id)
        if can_read:
            data = _summary(case, order, user)
        else:
            # A clerk may append a new registration to a private existing case.
            # Return only a receipt, never its earlier reason or metadata.
            data = {"uid": case.uid, "order_uid": case.order_uid, "cargo_uid": case.cargo_uid}
        session.commit()
        return data


def list_exceptions(actor, *, page=1, page_size=20, status="all", salesman_id=None):
    page = _id(page, "页码")
    page_size = min(_id(page_size, "每页条数"), 100)
    if status not in {"all", "open", "resolved"}:
        raise ValueError("异常状态无效")
    with SessionFactory() as session:
        user, roles = _reader(session, actor)
        owner_id = user.id
        if salesman_id is not None:
            if "admin" not in roles:
                raise PermissionError("仅管理员可以切换业务员")
            owner_id = _id(salesman_id, "业务员编号")
            owner = session.get(UserTable, owner_id)
            if owner is None or owner.status != "approved" or not {role.name for role in owner.roles}.intersection({"salesperson", "admin"}):
                raise ValueError("业务员无效")
        query = session.query(OrderExceptionTable, OrderTable).join(
            OrderTable, OrderTable.uid == OrderExceptionTable.order_uid,
        ).filter(OrderTable.salesman_id == owner_id)
        if status != "all":
            query = query.filter(OrderExceptionTable.status == status)
        total = query.count()
        rows = query.order_by(OrderExceptionTable.created_at.desc(), OrderExceptionTable.uid.desc()).offset(
            (page - 1) * page_size,
        ).limit(page_size).all()
        return {"items": [_summary(case, order, user) for case, order in rows], "total": total,
                "page": page, "page_size": page_size, "salesman_id": owner_id}


def _case(session, uid, user, roles, *, lock=False):
    uid = _text(uid, "异常编号", 32)
    candidate = session.get(OrderExceptionTable, uid)
    if candidate is None:
        raise LookupError("异常记录不存在")
    query = session.query(OrderTable).filter_by(uid=candidate.order_uid)
    order = query.populate_existing().with_for_update().first() if lock else query.first()
    if order is None or ("admin" not in roles and order.salesman_id != user.id):
        raise LookupError("异常记录不存在")
    if lock:
        candidate = session.query(OrderExceptionTable).filter_by(uid=uid).populate_existing().with_for_update().first()
    return candidate, order


def get_exception(uid, actor):
    with SessionFactory() as session:
        user, roles = _reader(session, actor)
        case, order = _case(session, uid, user, roles)
        return _detail(session, case, order, user)


def _mutate(uid, body, actor, *, action):
    body = _body(body, {"note", "event_key"})
    note = _text(body.get("note", "手动标记已解决" if action == "resolved" else None), "跟进记录", 2000)
    with SessionFactory() as session:
        user, roles = _reader(session, actor)
        case, order = _case(session, uid, user, roles, lock=True)
        if order.salesman_id != user.id:
            raise PermissionError("只能跟进或解决本人负责的异常订单")
        key = _event(action, "manual", body.get("event_key"), user.id)
        digest = _digest({"action": action, "uid": case.uid, "note": note, "actor_id": user.id})
        replay = _replay(session, key, digest)
        if replay is None:
            if case.status != "open":
                raise ExceptionConflictError("异常已解决，不能继续记录跟进")
            try:
                with session.begin_nested():
                    case.updated_at = _now()
                    if action == "resolved":
                        case.status = "resolved"
                        case.resolved_at = case.updated_at
                        case.resolved_by_id = user.id
                    _history(session, case, key=key, digest=digest, action=action, note=note, source="manual", actor=user)
            except IntegrityError:
                if _replay(session, key, digest) is None:
                    raise
        data = _detail(session, case, order, user)
        session.commit()
        return data


def add_followup(uid, body, actor):
    return _mutate(uid, body, actor, action="followup")


def resolve_exception(uid, body, actor):
    return _mutate(uid, body, actor, action="resolved")


def salespeople(actor):
    with SessionFactory() as session:
        user, roles = _reader(session, actor)
        if "admin" not in roles:
            raise PermissionError("仅管理员可以切换业务员")
        users = session.query(UserTable).filter(
            UserTable.status == "approved",
            or_(UserTable.roles.any(name="salesperson"), UserTable.id == user.id),
        ).order_by(UserTable.name.asc(), UserTable.id.asc()).all()
        return [{"id": employee.id, "name": employee.name} for employee in users]
