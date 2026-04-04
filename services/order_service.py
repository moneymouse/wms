import time
from typing import Any, Dict

from sqlalchemy import Integer, Float

from data.DB import OrderTable


# Build a mapping of field names to their SQLAlchemy column types
_ORDER_FIELD_TYPES = {c.name: type(c.type) for c in OrderTable.__table__.columns}


def filter_orders(order_list: list, query_param: str, cargo_model) -> list:
    """
    按关键词过滤订单（同时检索订单字段与关联货物的 transfer_id / waybill_id）。
    query_param 为空时原样返回。
    """
    if not query_param:
        return order_list

    keywords = [k.strip().lower() for k in query_param.splitlines() if k.strip()]
    primary = str(query_param).split("-", 1)[0].lower()

    def order_matches(order: Dict[str, Any]) -> bool:
        for val in order.values():
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
