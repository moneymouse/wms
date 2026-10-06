import time
from typing import Any, Dict

from contextlib import nullcontext

from flask import has_request_context
from sqlalchemy import Integer, Float, or_

import data
from Auth import get_payload_roles
from data.DB import CargoTable, OrderTable, RecordExist
from data.customer.Customer import CustomerTable
from data.database import SessionFactory
from data.order_version import current_version_no
from data.user.User import UserTable, user_model
from services import receivable_service
from services.order_edit_policy import build_edit_policy
from services.customer_access import can_view_order_customer_contact


# Build a mapping of field names to their SQLAlchemy column types
_ORDER_FIELD_TYPES = {c.name: type(c.type) for c in OrderTable.__table__.columns}

ORDER_LIST_EXCLUDED_FIELDS = {"archive", "salesman_id", "cargo_count", "create_date"}
ORDER_SEARCH_FIELDS = (
    "uid", "order_id", "customer_name", "transportation", "receiver",
    "receiver_phone", "mail", "country", "province", "city", "address",
    "en_name", "cn_name", "post_code", "zip_code", "order_date",
    "update_date", "tag_all",
)


class BusinessError(ValueError):
    """Business failure with the existing REST envelope and HTTP status."""

    def __init__(self, code: int, msg: str, *, uid=None, http_status=None):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.uid = uid
        self.http_status = code if http_status is None else http_status

    def to_dict(self):
        result = {"code": self.code, "msg": self.msg}
        if self.uid is not None:
            result["uid"] = self.uid
        return result


def create_order(record: dict, operator_payload: dict, session=None) -> dict:
    """Create an order with REST semantics, or join the caller's transaction.

    Without a session the receiver, order + V1, and optional quote retain their
    separate transactions. With a session nothing commits, rolls back or closes
    it; any failure must cause the caller to roll back its complete transaction.
    """
    if not isinstance(record, dict):
        raise BusinessError(400, "请求须为 JSON 对象")
    record = record.copy()
    payload = operator_payload or {}
    quote_payload = record.pop("quote", None)
    if quote_payload is not None:
        try:
            receivable_service.normalize_quote_payload(quote_payload)
        except ValueError as exc:
            raise BusinessError(400, str(exc)) from exc

    raw_salesman_id = record.get("salesman_id")
    if raw_salesman_id not in [None, "", 0, "0"]:
        try:
            salesman_id = int(raw_salesman_id)
        except (TypeError, ValueError) as exc:
            raise BusinessError(400, "Invalid salesman_id") from exc
        salesman = (
            user_model.get_by_id(salesman_id)
            if session is None
            else session.query(UserTable).filter_by(id=salesman_id).first()
        )
        if salesman is None:
            raise BusinessError(404, "Salesman not found")
        record["salesman_id"] = salesman_id
    else:
        salesman_id = payload.get("user_id") or payload.get("id")
        if salesman_id is not None:
            record["salesman_id"] = salesman_id
    if quote_payload is not None and salesman_id is None:
        raise BusinessError(400, "提供报价时必须指定业务员")

    customer_name = str(record.get("customer_name", "") or "").strip()
    raw_customer_id = record.get("customer_id")
    customer_id = None
    if raw_customer_id not in [None, "", 0, "0"]:
        try:
            customer_id = int(raw_customer_id)
        except (TypeError, ValueError) as exc:
            raise BusinessError(400, "Invalid customer_id") from exc
    if customer_id or customer_name:
        with (SessionFactory() if session is None else nullcontext(session)) as lookup:
            query = lookup.query(CustomerTable)
            customer = (
                query.filter_by(id=customer_id).first()
                if customer_id else query.filter_by(name=customer_name).first()
            )
            if customer is None:
                target = f"ID:{customer_id}" if customer_id else customer_name
                raise BusinessError(404, f"Customer '{target}' not found")
            record["customer_id"] = customer.id
            record["customer_name"] = customer.name

    if session is None:
        # Preserve legacy callers that patch the data facade and model methods.
        data.add_customer_record(record)
    else:
        data.add_customer_record(record, session=session)
    record["order_date"] = time.strftime("%Y-%m-%d %H:%M")
    try:
        if session is None:
            if has_request_context():
                order_uid = data.order_model.create(record)
            else:
                order_uid = data.order_model.create(record, operator_payload=payload)
        else:
            order_uid = data.order_model.create(
                record, session=session, operator_payload=payload
            )
    except RecordExist as exc:
        raise BusinessError(
            500, "Record Existed", http_status=200 if session is None else 500
        ) from exc

    quote_result = None
    if quote_payload is not None:
        try:
            kwargs = {} if session is None else {"session": session}
            quote_result = receivable_service.create_order_quote(
                order_uid=order_uid, body=quote_payload,
                operator_payload=payload, allow_on_behalf=True, **kwargs,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            if session is None:
                raise BusinessError(
                    500, f"订单已创建，但报价生成失败：{exc}", uid=order_uid
                ) from exc
            raise BusinessError(500, f"报价生成失败：{exc}") from exc

    result = {
        "code": 200,
        "msg": "创建成功并已生成报价" if quote_result else "success",
        "uid": order_uid,
    }
    if quote_result:
        result["data"] = {"quote": quote_result}
    return result


def _apply_order_search(query, query_param):
    if not query_param:
        return query
    primary = str(query_param).split("-", 1)[0].strip()
    keywords = [key.strip() for key in str(query_param).splitlines() if key.strip()]
    conditions = []
    if primary:
        like = f"%{primary}%"
        conditions.extend(
            getattr(OrderTable, field).ilike(like) for field in ORDER_SEARCH_FIELDS
        )
        conditions.append(OrderTable.salesman.has(UserTable.name.ilike(like)))
    for keyword in keywords:
        like = f"%{keyword}%"
        conditions.append(OrderTable.cargos.any(or_(
            CargoTable.transfer_id.ilike(like), CargoTable.waybill_id.ilike(like)
        )))
    return query.filter(or_(*conditions)) if conditions else query


def list_orders(p=1, s=30, sf="create_date", so=1, q="") -> dict:
    """Return the same paginated global, unarchived order list as REST."""
    page = max(p - 1, 0)
    page_size = min(max(s, 1), 200)
    column = getattr(OrderTable, sf, None) if sf in _ORDER_FIELD_TYPES else None
    column = column if column is not None else OrderTable.create_date
    with SessionFactory() as session:
        query = _apply_order_search(
            session.query(OrderTable).filter(OrderTable.archive == False), q  # noqa: E712
        )
        total = query.count()
        rows = (
            query.order_by(column.desc() if so == 1 else column.asc())
            .offset(page * page_size).limit(page_size).all()
        )
        return {
            "code": 200,
            "data": [{
                col.name: getattr(row, col.name)
                for col in OrderTable.__table__.columns
                if col.name not in ORDER_LIST_EXCLUDED_FIELDS
            } for row in rows],
            "total": total,
        }


def get_order(uid: str, operator_payload: dict) -> dict:
    """Return order details and permissions for an explicitly supplied actor."""
    detail = data.order_model.read(uid)
    if detail is not None:
        payload = operator_payload or {}
        with SessionFactory() as session:
            try:
                detail.update(build_edit_policy(
                    session, uid, get_payload_roles(payload),
                    payload.get("user_id") or payload.get("id"),
                ))
                detail["current_version"] = current_version_no(session, uid)
            except LookupError:
                # Compatibility with old mocked/legacy order readers.
                pass
    return {"code": 200, "data": detail}


def get_order_customer_contact(uid: str, operator_payload: dict) -> dict:
    """Read contacts using the current order assignment, independent of creator."""
    with SessionFactory() as session:
        order = session.query(OrderTable).filter(
            OrderTable.uid == uid, OrderTable.archive.is_(False)
        ).first()
        if order is None:
            raise BusinessError(404, "Order not found")
        if not can_view_order_customer_contact(order, operator_payload):
            raise BusinessError(403, "Permission denied")
        customer = order.customers[0] if order.customers else None
        if customer is None:
            return {"code": 200, "data": None}
        return {
            "code": 200,
            "data": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone or "",
                "wechat": customer.wechat or "",
            },
        }


def filter_orders(order_list: list, query_param: str, cargo_model) -> list:
    """
    按关键词过滤订单（同时检索订单字段与关联货物的 transfer_id / waybill_id）。
    query_param 为空时原样返回。
    """
    if not query_param:
        return order_list

    keywords = [k.strip().lower() for k in query_param.splitlines() if k.strip()]
    primary = str(query_param).split("-", 1)[0].lower()

    # 订单中实际可用于搜索的字段（排除内部/无用字段）
    _SEARCHABLE_FIELDS = [
        "uid",
        "order_id",
        "customer_name",
        "transportation",
        "receiver",
        "receiver_phone",
        "mail",
        "country",
        "province",
        "city",
        "address",
        "en_name",
        "cn_name",
        "post_code",
        "zip_code",
        "order_date",
        "update_date",
        "tag_all",
    ]

    def order_matches(order: Dict[str, Any]) -> bool:
        for field in _SEARCHABLE_FIELDS:
            val = order.get(field)
            if val is not None and primary in str(val).lower():
                return True
        for c_uid in order.get("cargo_uid_list", []):
            c = cargo_model.read(c_uid)
            if not c:
                continue
            transfer = (
                str(c.get("transfer_id")).lower()
                if c.get("transfer_id") is not None
                else None
            )
            waybill = (
                str(c.get("waybill_id")).lower()
                if c.get("waybill_id") is not None
                else None
            )
            for k in keywords:
                if transfer and k in transfer:
                    return True
                if waybill and k in waybill:
                    return True
        return False

    return [o for o in order_list if order_matches(o)]


def sort_orders(order_list: list, sorted_field: str, sorted_order: int) -> list:
    """
    对订单列表排序。sorted_order: 1 = 降序，0 = 升序。
    """
    if not sorted_field:
        return order_list

    reverse = sorted_order == 1
    field_type = _ORDER_FIELD_TYPES.get(sorted_field)

    def sort_key(x):
        value = x.get(sorted_field, "")
        # Numeric fields
        if field_type in (Integer, Float):
            if value is None:
                return float("-inf") if reverse else float("inf")
            try:
                return float(value)
            except Exception:
                return float("-inf") if reverse else float("inf")
        # Date fields (detected by field name suffix)
        elif sorted_field.endswith("_date"):
            if value is None:
                return 0
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    return time.mktime(time.strptime(value, fmt))
                except Exception:
                    continue
            return 0
        # String fields
        if value is None:
            return ""
        return str(value)

    return sorted(order_list, key=sort_key, reverse=reverse)
