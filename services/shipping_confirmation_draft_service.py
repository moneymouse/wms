"""Drafts keep box selections and print overrides without changing shipment facts."""

import json
import uuid
from datetime import datetime

from Auth import get_payload_roles
from data.DB import CargoTable, OrderTable, TransportationModeTable
from data.customer.Customer import CustomerTable
from data.database import SessionFactory
from data.packing.PackingList import PackingListTable
from data.packing.shipping_confirmation import ShippingConfirmationDraftTable
from services.customer_access import current_user_id
from services.shipping_confirmation_service import AGENT_NAMES, ShippingConfirmationError, _uid_list
from utils.audit import record_audit


DRAFT_ROLES = ["admin", "store_manager", "salesperson", "clerk"]
MAX_BOXES = 500


def _text(value, field, limit, default=""):
    if value is None:
        value = default
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ShippingConfirmationError(f"{field} 须为不超过 {limit} 字的文本")
    return value.strip()


def _body(body):
    if not isinstance(body, dict):
        raise ShippingConfirmationError("请求须为 JSON 对象")
    return body


def _actor_id(actor):
    user_id = current_user_id(actor)
    if not user_id:
        raise ShippingConfirmationError("登录用户身份无效", 403)
    return user_id


def _global(actor):
    return bool(set(get_payload_roles(actor)).intersection({"admin", "store_manager"}))


def _draft(session, uid, actor):
    row = session.query(ShippingConfirmationDraftTable).filter_by(uid=uid, archive=False).first()
    if row is None:
        raise ShippingConfirmationError("出货单草稿不存在或已删除", 404)
    if not _global(actor) and row.creator_id != _actor_id(actor):
        raise ShippingConfirmationError("无权访问此出货单草稿", 403)
    return row


def _version(body):
    value = _body(body).get("expected_version")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ShippingConfirmationError("请提供草稿当前版本 expected_version")
    return value


def _hydrate(session, entries, *, strict=False):
    uids = [entry["cargo_uid"] for entry in entries]
    rows = session.query(CargoTable, PackingListTable, CustomerTable, OrderTable).join(
        PackingListTable, CargoTable.packing_list_uid == PackingListTable.uid
    ).outerjoin(CustomerTable, PackingListTable.customer_id == CustomerTable.id).outerjoin(
        OrderTable, CargoTable.target_order_uid == OrderTable.uid
    ).filter(CargoTable.uid.in_(uids)).all() if uids else []
    by_uid = {box.uid: (box, packing, customer, order) for box, packing, customer, order in rows}
    channels = {order.transportation for _, _, _, order in rows if order and not order.archive and order.transportation}
    modes = session.query(TransportationModeTable).filter(TransportationModeTable.name.in_(channels)).all() if channels else []
    agents = {mode.name: AGENT_NAMES.get((mode.channel_group or "").strip(), (mode.channel_group or "").strip()) for mode in modes}
    result = []
    for entry in entries:
        item = dict(entry)
        matched = by_uid.get(entry["cargo_uid"])
        available = bool(matched and not matched[0].archive and not matched[1].archive)
        if strict and not available:
            raise ShippingConfirmationError(f"箱子不存在或装箱单已归档：{entry['cargo_uid']}", 404)
        item["available"] = available
        if matched:
            box, packing, customer, order = matched
            item.update(
                packing_list_uid=packing.uid, list_number=packing.list_number,
                box_number=box.box_number, tag=box.tag if box.tag and box.tag != "init" else f"{packing.list_number}-{box.box_number or ''}",
                transfer_id=box.transfer_id or "", weight=box.weight or 0,
                customer_id=packing.customer_id,
                customer_name=(customer.name if customer else None) or (order.customer_name if order else None) or "",
                target_order_uid=box.target_order_uid, order_id=order.order_id if order else None,
            )
            item.setdefault("agent_name", agents.get(order.transportation, "") if order and not order.archive else "")
        item.setdefault("agent_name", "")
        item.setdefault("remarks", "")
        result.append(item)
    return result


def _entries(session, value):
    if not isinstance(value, list) or len(value) > MAX_BOXES:
        raise ShippingConfirmationError(f"entries 须为列表，最多 {MAX_BOXES} 箱")
    selected, seen = [], set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ShippingConfirmationError("箱子条目须为 JSON 对象")
        uid = _text(entry.get("cargo_uid"), "cargo_uid", 32)
        if not uid:
            raise ShippingConfirmationError("请选择有效箱子")
        if uid in seen:
            raise ShippingConfirmationError(f"草稿中箱子不可重复：{uid}")
        seen.add(uid)
        item = {"cargo_uid": uid, "remarks": _text(entry.get("remarks"), "备注", 2000)}
        if "agent_name" in entry:
            item["agent_name"] = _text(entry.get("agent_name"), "渠道代理", 128)
        selected.append(item)
    # Save verified display snapshots to explain an unavailable box on reopening.
    return _hydrate(session, selected, strict=True)


def _summary(row):
    return {
        "uid": row.uid, "title": row.title, "version": row.version,
        "creator_id": row.creator_id, "created_at": row.created_at, "updated_at": row.updated_at,
        "box_count": len(json.loads(row.entries_json)),
    }


def _detail(session, row):
    return {**_summary(row), "entries": _hydrate(session, json.loads(row.entries_json))}


def hydrate_shipping_boxes(cargo_uids):
    uids = _uid_list(cargo_uids, "cargo_uids")
    if not uids:
        raise ShippingConfirmationError("请选择需要添加的箱子")
    if len(uids) > MAX_BOXES:
        raise ShippingConfirmationError(f"最多选择 {MAX_BOXES} 箱")
    with SessionFactory() as session:
        return {"items": _hydrate(session, [{"cargo_uid": uid} for uid in uids], strict=True)}


def list_shipping_drafts(actor):
    user_id = _actor_id(actor)
    with SessionFactory() as session:
        query = session.query(ShippingConfirmationDraftTable).filter_by(archive=False)
        if not _global(actor):
            query = query.filter_by(creator_id=user_id)
        return {"items": [_summary(row) for row in query.order_by(ShippingConfirmationDraftTable.updated_at.desc()).all()]}


def get_shipping_draft(uid, actor):
    with SessionFactory() as session:
        return _detail(session, _draft(session, uid, actor))


def save_shipping_draft(body, actor, uid=None):
    body = _body(body)
    user_id = _actor_id(actor)
    title = _text(body.get("title"), "草稿名称", 128) or "出货单草稿"
    with SessionFactory() as session:
        try:
            row = _draft(session, uid, actor) if uid else None
            expected = _version(body) if row else None
            if row and row.version != expected:
                raise ShippingConfirmationError("草稿已被其他操作更新，请重新打开后再修改", 409)
            entries = _entries(session, body.get("entries"))
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            values = {"title": title, "entries_json": json.dumps(entries, ensure_ascii=False), "updated_at": now}
            before = _summary(row) if row else None
            if row:
                changed = session.query(ShippingConfirmationDraftTable).filter_by(
                    uid=uid, version=expected, archive=False
                ).update({**values, "version": expected + 1}, synchronize_session=False)
                if changed != 1:
                    raise ShippingConfirmationError("草稿已被其他操作更新，请重新打开后再修改", 409)
                session.refresh(row)
            else:
                row = ShippingConfirmationDraftTable(
                    uid=uuid.uuid4().hex, creator_id=user_id, version=1,
                    created_at=now, archive=False, **values,
                )
                session.add(row)
                session.flush()
            record_audit("shipping_confirmation", "shipping_confirmation_draft", row.uid,
                         action="draft_updated" if uid else "draft_created", before_data=before,
                         after_data={**_summary(row), "entries": entries}, session=session, operator_payload=actor)
            result = _detail(session, row)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise


def delete_shipping_draft(uid, body, actor):
    expected = _version(body)
    with SessionFactory() as session:
        try:
            row = _draft(session, uid, actor)
            before = _summary(row)
            changed = session.query(ShippingConfirmationDraftTable).filter_by(uid=uid, version=expected, archive=False).update(
                {"archive": True, "version": expected + 1}, synchronize_session=False
            )
            if changed != 1:
                raise ShippingConfirmationError("草稿已被其他操作更新，请重新打开后再修改", 409)
            record_audit("shipping_confirmation", "shipping_confirmation_draft", uid, action="draft_deleted",
                         before_data=before, after_data={"archive": True}, session=session, operator_payload=actor)
            session.commit()
            return {"uid": uid}
        except Exception:
            session.rollback()
            raise


def _print_groups(entries):
    if not entries:
        raise ShippingConfirmationError("请至少选择一个箱子")
    groups = {}
    for entry in entries:
        key = (entry.get("customer_id") or entry.get("customer_name") or entry["packing_list_uid"], entry["agent_name"], entry["remarks"])
        if key not in groups:
            groups[key] = {
                "uid": str(len(groups) + 1), "customer_name": entry.get("customer_name", ""),
                "agent_name": entry["agent_name"], "remarks": entry["remarks"],
                "identity_label": "装箱单 / Packing", "identity_numbers": [], "boxes": [],
            }
        group = groups[key]
        if entry["list_number"] not in group["identity_numbers"]:
            group["identity_numbers"].append(entry["list_number"])
        group["boxes"].append({"uid": entry["cargo_uid"], "tag": entry["tag"], "transfer_id": entry["transfer_id"]})
    for group in groups.values():
        group["identity_value"] = ", ".join(group.pop("identity_numbers"))
    return list(groups.values())


def load_packing_shipping_details(body):
    with SessionFactory() as session:
        entries = _entries(session, _body(body).get("entries"))
        return _print_groups(entries)


def load_draft_shipping_details(uid, body, actor):
    expected = _version(body)
    with SessionFactory() as session:
        row = _draft(session, uid, actor)
        if row.version != expected:
            raise ShippingConfirmationError("草稿已更新，请重新打开后打印", 409)
        entries = _hydrate(session, json.loads(row.entries_json), strict=True)
        return _print_groups(entries)
