"""Load the order and box fields used by shipping confirmation PDFs."""

from data.database import SessionFactory
from data.DB import CargoTable, OrderTable, TransportationModeTable


AGENT_NAMES = {"极飞": "JF", "统仓": "TC", "JF": "JF", "TC": "TC", "YX": "YX"}


class ShippingConfirmationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _uid_list(value, field, *, required=False):
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise ShippingConfirmationError(f"{field} 必须为列表")
    if required and not value:
        raise ShippingConfirmationError("请选择需要导出的订单")

    result = []
    seen = set()
    for uid in value:
        if not isinstance(uid, str) or not uid.strip():
            raise ShippingConfirmationError(f"{field} 包含无效编号")
        uid = uid.strip()
        if uid not in seen:
            seen.add(uid)
            result.append(uid)
    return result


def load_shipping_confirmation_details(uid_list, cargo_list=None):
    """Keep selected-order order and optionally limit boxes to selected cargos."""
    order_uids = _uid_list(uid_list, "uid_list", required=True)
    cargo_uids = _uid_list(cargo_list, "cargo_list")

    with SessionFactory() as session:
        orders = (
            session.query(OrderTable)
            .filter(OrderTable.uid.in_(order_uids), OrderTable.archive.is_(False))
            .all()
        )
        order_map = {order.uid: order for order in orders}
        for uid in order_uids:
            if uid not in order_map:
                raise ShippingConfirmationError(f"订单不存在或已归档：{uid}", 404)

        channel_names = {order.transportation for order in orders if order.transportation}
        modes = (
            session.query(TransportationModeTable)
            .filter(TransportationModeTable.name.in_(channel_names))
            .all()
        ) if channel_names else []
        # Archived modes remain meaningful for orders that already use them.
        agent_by_channel = {}
        for mode in modes:
            group = (mode.channel_group or "").strip()
            agent_by_channel[mode.name] = AGENT_NAMES.get(group, group)

        query = session.query(CargoTable).filter(
            CargoTable.target_order_uid.in_(order_uids), CargoTable.archive.is_(False)
        )
        if cargo_uids:
            query = query.filter(CargoTable.uid.in_(cargo_uids))
        cargos = query.order_by(CargoTable.create_date, CargoTable.uid).all()
        if not cargos:
            raise ShippingConfirmationError("没有可导出的箱子")

        boxes_by_order = {uid: [] for uid in order_uids}
        for cargo in cargos:
            boxes_by_order[cargo.target_order_uid].append({
                "uid": cargo.uid,
                "tag": cargo.tag or "",
                "transfer_id": cargo.transfer_id or "",
            })
        if cargo_uids:
            selected_rank = {uid: index for index, uid in enumerate(cargo_uids)}
            for boxes in boxes_by_order.values():
                boxes.sort(key=lambda box: selected_rank[box["uid"]])

        details = []
        for uid in order_uids:
            boxes = boxes_by_order[uid]
            if cargo_uids and not boxes:
                continue
            order = order_map[uid]
            details.append({
                "uid": uid,
                "order_id": order.order_id or "",
                "customer_name": order.customer_name or "",
                "agent_name": agent_by_channel.get(order.transportation, ""),
                "boxes": boxes,
            })
        return details
