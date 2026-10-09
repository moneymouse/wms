"""Transactional delivery and recipient-scoped inbox operations.

Business services call send_message with their existing session. Delivery and
the triggering business change commit or roll back together; this module never
commits that caller-owned transaction. Reading a notice does not finish a task.
"""

from datetime import datetime
import hashlib
from urllib.parse import urlsplit
import uuid

from sqlalchemy.exc import IntegrityError

from data.database import SessionFactory
from data.message import MessageTable
from data.user.User import UserTable


class MessageConflictError(ValueError):
    """An event key was reused for different notification content."""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _id(value, field):
    text = str(value)
    if isinstance(value, bool) or not text.isascii() or not text.isdigit() or not 1 <= int(value) <= 2147483647:
        raise ValueError(f"{field}无效")
    return int(value)


def _text(value, field, maximum, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field}必须为文字")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(f"{field}不能为空且不得超过 {maximum} 字" if required else f"{field}不得超过 {maximum} 字")
    return value or None


def _action_path(value):
    if isinstance(value, str) and any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("处理页面必须为站内路径")
    path = _text(value, "处理页面", 1024)
    if path is None:
        return None
    # Notifications may navigate inside the app only, including query strings.
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise ValueError("处理页面必须为站内路径")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise ValueError("处理页面必须为站内路径")
    return path


def _business_id(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("业务编号必须为文字或整数")
    return _text(str(value), "业务编号", 128)


def _deduplicated(existing, values):
    if any(getattr(existing, field) != value for field, value in values.items()):
        raise MessageConflictError("事件编号已用于另一条消息，请为新的业务事件使用新的编号")
    return existing


def send_message(session, *, recipient_id, title, body, category="system", source_name="系统",
                 action_path=None, business_type=None, business_id=None, event_key=None):
    """Queue a notice in a caller-owned transaction and return its ORM row.

    A stable event_key makes repeated delivery to the same employee idempotent.
    Different employees receive separate rows. Omit it only for one-off notices.
    """
    recipient_id = _id(recipient_id, "收件人")
    values = {
        "recipient_id": recipient_id,
        "title": _text(title, "标题", 200, required=True),
        "body": _text(body, "正文", 10000, required=True),
        "category": _text(category, "消息分类", 64, required=True),
        "source_name": _text(source_name, "消息来源", 128, required=True),
        "action_path": _action_path(action_path),
        "business_type": _text(business_type, "业务类型", 64),
        "business_id": _business_id(business_id),
        "event_key": _text(event_key, "事件编号", 128),
    }
    if session.get(UserTable, recipient_id) is None:
        raise LookupError("收件人不存在")
    key = values["event_key"]
    if key is not None:
        existing = session.query(MessageTable).filter_by(recipient_id=recipient_id, event_key=key).first()
        if existing is not None:
            return _deduplicated(existing, values)
    message = MessageTable(uid=uuid.uuid4().hex, created_at=_now(), **values)
    try:
        # The unique constraint also protects delivery by concurrent processes.
        # A savepoint keeps that conflict from rolling back the business change.
        with session.begin_nested():
            session.add(message)
            session.flush()
    except IntegrityError:
        if key is None:
            raise
        # A locking read sees a concurrent winner under MySQL REPEATABLE READ.
        existing = session.query(MessageTable).filter_by(
            recipient_id=recipient_id, event_key=key,
        ).with_for_update().first()
        if existing is None:
            raise
        return _deduplicated(existing, values)
    return message


def send_http_message(body, actor):
    """Generic, authenticated delivery for trusted operator/service accounts."""
    if not isinstance(body, dict):
        raise ValueError("请求内容必须为 JSON 对象")
    if "source_name" in body:
        raise ValueError("消息来源由当前发送员工确定，不能指定 source_name")
    allowed = {"recipient_id", "title", "body", "category", "action_path", "business_type", "business_id", "event_key"}
    if set(body) - allowed:
        raise ValueError("请求包含不支持的消息字段")
    with SessionFactory() as session:
        sender_id = _recipient(session, actor)
        sender = session.get(UserTable, sender_id)
        if not {role.name for role in sender.roles}.intersection({"admin", "store_manager", "finance", "clerk"}):
            raise PermissionError("仅管理员、仓库管理员、财务或文员可以发送站内消息")
        recipient_id = _id(body.get("recipient_id"), "收件人")
        recipient = session.get(UserTable, recipient_id)
        if recipient is None:
            raise LookupError("收件人不存在")
        if recipient.status != "approved":
            raise ValueError("收件员工尚未审批通过")
        event_key = _text(body.get("event_key"), "事件编号", 128, required=True)
        values = {key: value for key, value in body.items() if key not in {"recipient_id", "event_key"}}
        values.setdefault("title", None)
        values.setdefault("body", None)
        message = send_message(
            session, recipient_id=recipient_id, source_name=sender.name,
            event_key=f"http:{sender_id}:{hashlib.sha256(event_key.encode('utf-8')).hexdigest()}",
            **values,
        )
        session.commit()
        return message.to_dict()


def _recipient(session, actor):
    """Resolve trusted identity once; every read/update scopes by this id."""
    actor = actor or {}
    try:
        user_id = _id(actor.get("user_id") or actor.get("id") or actor.get("uid"), "员工编号")
    except ValueError as exc:
        raise PermissionError("无法识别当前员工") from exc
    user = session.get(UserTable, user_id)
    if user is None or user.status != "approved":
        raise PermissionError("当前员工没有收件箱访问权限")
    return user_id


def _query(session, user_id):
    return session.query(MessageTable).filter(MessageTable.recipient_id == user_id)


def _unread(session, user_id):
    return _query(session, user_id).filter(MessageTable.read_at.is_(None)).count()


def list_messages(actor, *, page=1, page_size=20, status="all"):
    page = _id(page, "页码")
    page_size = min(_id(page_size, "每页条数"), 100)
    if status not in {"all", "unread", "read"}:
        raise ValueError("消息状态无效")
    with SessionFactory() as session:
        user_id = _recipient(session, actor)
        query = _query(session, user_id)
        if status == "unread":
            query = query.filter(MessageTable.read_at.is_(None))
        elif status == "read":
            query = query.filter(MessageTable.read_at.is_not(None))
        total = query.count()
        items = query.order_by(MessageTable.created_at.desc(), MessageTable.uid.desc()).offset(
            (page - 1) * page_size,
        ).limit(page_size).all()
        return {
            "items": [item.to_dict() for item in items], "total": total,
            "page": page, "page_size": page_size, "unread_count": _unread(session, user_id),
        }


def unread_count(actor):
    with SessionFactory() as session:
        return {"unread_count": _unread(session, _recipient(session, actor))}


def _message(session, user_id, uid):
    message = _query(session, user_id).filter(MessageTable.uid == uid).first()
    if message is None:
        # Same response for another employee's id and a nonexistent id.
        raise LookupError("消息不存在")
    return message


def get_message(uid, actor):
    with SessionFactory() as session:
        return _message(session, _recipient(session, actor), uid).to_dict()


def mark_read(uid, actor):
    with SessionFactory() as session:
        user_id = _recipient(session, actor)
        message = _message(session, user_id, uid)
        # Conditional update preserves the first read timestamp on retries.
        _query(session, user_id).filter(
            MessageTable.uid == uid, MessageTable.read_at.is_(None),
        ).update({MessageTable.read_at: _now()}, synchronize_session=False)
        session.commit()
        session.refresh(message)
        return message.to_dict()


def mark_all_read(actor):
    with SessionFactory() as session:
        user_id = _recipient(session, actor)
        updated = _query(session, user_id).filter(MessageTable.read_at.is_(None)).update(
            {MessageTable.read_at: _now()}, synchronize_session=False,
        )
        session.commit()
        return {"updated_count": updated, "unread_count": _unread(session, user_id)}
