"""Ownership rules for customer management and order contact access."""

from Auth import get_payload_roles


def current_user_id(payload):
    """Normalize the authenticated identity without accepting client body fields."""
    payload = payload or {}
    value = payload.get("user_id") or payload.get("id") or payload.get("uid")
    if isinstance(value, bool):
        return None
    try:
        user_id = int(value)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def has_global_customer_access(payload):
    return bool(set(get_payload_roles(payload)).intersection({"admin", "store_manager"}))


def customer_creator_scope(payload):
    """None means global access; zero fails closed for a missing identity."""
    if has_global_customer_access(payload):
        return None
    return current_user_id(payload) or 0


def can_view_order_customer_contact(order, payload):
    if has_global_customer_access(payload):
        return True
    user_id = current_user_id(payload)
    return (
        "salesperson" in get_payload_roles(payload)
        and user_id is not None
        and order.salesman_id == user_id
    )
