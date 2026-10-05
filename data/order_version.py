"""Append-only order version history and reconstruction helpers.

The history tables deliberately do not reference live orders, cargos or users so
that a hard-deleted business record never makes its audit trail disappear.
"""

from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from typing import Any, Iterable, Optional

from flask import has_request_context
from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, func, or_
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship, selectinload

from data.database import Base, SessionFactory
from data.DB import CargoTable, OrderTable
from data.packing.PackingList import BoxWorkerTable, PackingListTable


JSON_TEXT = Text().with_variant(mysql.LONGTEXT(), "mysql")


class OrderVersionTable(Base):
    __tablename__ = "order_versions"
    __table_args__ = (
        UniqueConstraint("order_uid", "version_no", name="uq_order_versions_uid_no"),
        Index("idx_order_versions_uid_created", "order_uid", "created_at"),
        Index("idx_order_versions_deleted", "deleted", "created_at"),
        Index("idx_order_versions_correlation", "correlation_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_uid = Column(String(32), nullable=False)
    version_no = Column(Integer, nullable=False)
    action = Column(String(64), nullable=False)
    summary = Column(String(512), nullable=False)
    operator_id = Column(Integer, nullable=True)
    operator_name = Column(String(128), nullable=True)
    operator_roles = Column(JSON_TEXT, nullable=False, default="[]")
    reason = Column(String(512), nullable=True)
    correlation_id = Column(String(64), nullable=False)
    created_at = Column(String(32), nullable=False)
    order_id = Column(String(128), nullable=True)
    customer_name = Column(String(256), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False, server_default=false())

    changes = relationship(
        "OrderVersionChangeTable",
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="OrderVersionChangeTable.sequence_no",
    )


class OrderVersionChangeTable(Base):
    __tablename__ = "order_version_changes"
    __table_args__ = (
        UniqueConstraint("version_id", "sequence_no", name="uq_order_version_changes_seq"),
        Index("idx_order_version_changes_entity", "entity_type", "entity_uid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(
        Integer,
        ForeignKey("order_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_no = Column(Integer, nullable=False)
    entity_type = Column(String(32), nullable=False)
    entity_uid = Column(String(32), nullable=False)
    operation = Column(String(16), nullable=False)
    before_data = Column(JSON_TEXT, nullable=True)
    after_data = Column(JSON_TEXT, nullable=True)

    version = relationship("OrderVersionTable", back_populates="changes")


ORDER_SNAPSHOT_FIELDS = (
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
    "total_weight",
    "cargo_count",
    "archive",
    "post_code",
    "zip_code",
    "order_date",
    "tag_all",
)

CARGO_SNAPSHOT_FIELDS = (
    "origin_id",
    "transfer_id",
    "tag",
    "count",
    "weight",
    "real_en_name",
    "price",
    "status",
    "archive",
    "date",
    "waybill_id",
    "target_order_uid",
    "packing_list_uid",
    "item_name",
    "remark",
    "box_number",
    "piece_count",
    "box_status",
)


def _json_default(value: Any):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


def _load(value: Optional[str]) -> Any:
    if value in (None, ""):
        return None
    return json.loads(value)


def _parse_item_details(raw: Any) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return deepcopy(raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def normalize_operator(payload: Optional[dict] = None) -> dict:
    if payload is None and has_request_context():
        try:
            from Auth import get_payload_roles, get_token_payload

            payload = get_token_payload() or {}
            roles = get_payload_roles(payload)
        except Exception:
            payload, roles = {}, []
    else:
        payload = payload or {}
        try:
            from Auth import get_payload_roles

            roles = get_payload_roles(payload)
        except Exception:
            raw_roles = payload.get("roles") or payload.get("role") or []
            roles = [raw_roles] if isinstance(raw_roles, str) else list(raw_roles)
    return {
        "id": payload.get("user_id") or payload.get("id"),
        "name": payload.get("name") or payload.get("username") or payload.get("phone"),
        "roles": sorted(set(roles)),
    }


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def snapshot_order(session, order_uid: str, *, lock: bool = False) -> Optional[dict]:
    query = session.query(OrderTable).filter(OrderTable.uid == order_uid)
    if lock:
        query = query.with_for_update()
    order = query.first()
    if order is None:
        return None

    order_data = {field: getattr(order, field) for field in ORDER_SNAPSHOT_FIELDS}
    order_data["uid"] = order.uid
    order_data["salesman"] = (
        {"id": order.salesman.id, "name": order.salesman.name}
        if order.salesman is not None
        else None
    )
    order_data["customers"] = sorted(
        ({"id": customer.id, "name": customer.name} for customer in order.customers),
        key=lambda row: row["id"],
    )

    cargos = (
        session.query(CargoTable)
        .filter(CargoTable.target_order_uid == order_uid)
        .order_by(CargoTable.uid.asc())
        .all()
    )
    packing_uids = sorted({row.packing_list_uid for row in cargos if row.packing_list_uid})
    marks = {}
    if packing_uids:
        marks = dict(
            session.query(PackingListTable.uid, PackingListTable.list_number)
            .filter(PackingListTable.uid.in_(packing_uids))
            .all()
        )
    worker_rows = []
    if cargos:
        worker_rows = (
            session.query(BoxWorkerTable)
            .filter(BoxWorkerTable.box_uid.in_([row.uid for row in cargos]))
            .order_by(BoxWorkerTable.box_uid.asc(), BoxWorkerTable.worker_id.asc())
            .all()
        )
    workers_by_box: dict[str, list] = {}
    for worker_link in worker_rows:
        workers_by_box.setdefault(worker_link.box_uid, []).append(
            {
                "worker_id": worker_link.worker_id,
                "worker_name": worker_link.worker.name if worker_link.worker else None,
            }
        )

    cargo_data, box_data = [], []
    for cargo in cargos:
        item = {field: getattr(cargo, field) for field in CARGO_SNAPSHOT_FIELDS}
        item["uid"] = cargo.uid
        item["item_details"] = _parse_item_details(cargo.item_details)
        if cargo.packing_list_uid:
            item["mark"] = marks.get(cargo.packing_list_uid)
            item["workers"] = workers_by_box.get(cargo.uid, [])
            box_data.append(item)
        else:
            cargo_data.append(item)

    return {
        "order": order_data,
        "cargos": cargo_data,
        "boxes": box_data,
        "deleted": False,
    }


def _entities(snapshot: Optional[dict]) -> dict[tuple[str, str], dict]:
    if not snapshot:
        return {}
    result: dict[tuple[str, str], dict] = {}
    order = snapshot.get("order")
    if order:
        result[("order", str(order["uid"]))] = order
    for key, entity_type in (("cargos", "cargo"), ("boxes", "box")):
        for item in snapshot.get(key) or []:
            result[(entity_type, str(item["uid"]))] = item
    return result


def calculate_changes(before: Optional[dict], after: Optional[dict]) -> list[dict]:
    before_entities = _entities(before)
    after_entities = _entities(after)
    entity_order = {"order": 0, "cargo": 1, "box": 2}
    keys = sorted(
        set(before_entities) | set(after_entities),
        key=lambda key: (entity_order.get(key[0], 99), key[1]),
    )
    result = []
    for entity_type, entity_uid in keys:
        old = before_entities.get((entity_type, entity_uid))
        new = after_entities.get((entity_type, entity_uid))
        if old is None:
            result.append({
                "entity_type": entity_type,
                "entity_uid": entity_uid,
                "operation": "create",
                "before_data": None,
                "after_data": deepcopy(new),
            })
            continue
        if new is None:
            result.append({
                "entity_type": entity_type,
                "entity_uid": entity_uid,
                "operation": "delete",
                "before_data": deepcopy(old),
                "after_data": None,
            })
            continue
        changed_fields = sorted(
            field for field in set(old) | set(new) if old.get(field) != new.get(field)
        )
        if changed_fields:
            result.append({
                "entity_type": entity_type,
                "entity_uid": entity_uid,
                "operation": "update",
                "before_data": {field: deepcopy(old.get(field)) for field in changed_fields},
                "after_data": {field: deepcopy(new.get(field)) for field in changed_fields},
            })
    return result


def _metadata_snapshot(before: Optional[dict], after: Optional[dict]) -> dict:
    source = (after or {}).get("order") or (before or {}).get("order") or {}
    return {
        "order_id": source.get("order_id"),
        "customer_name": source.get("customer_name"),
    }


def append_version(
    session,
    order_uid: str,
    *,
    before: Optional[dict],
    after: Optional[dict],
    action: str,
    summary: str,
    operator_payload: Optional[dict] = None,
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
    force: bool = False,
) -> Optional[OrderVersionTable]:
    changes = calculate_changes(before, after)
    if not changes and not force:
        return None

    latest_version = (
        session.query(OrderVersionTable.version_no)
        .filter(OrderVersionTable.order_uid == order_uid)
        .order_by(OrderVersionTable.version_no.desc())
        .with_for_update()
        .first()
    )
    current_no = latest_version[0] if latest_version else 0
    operator = normalize_operator(operator_payload)
    metadata = _metadata_snapshot(before, after)
    version = OrderVersionTable(
        order_uid=order_uid,
        version_no=int(current_no) + 1,
        action=action,
        summary=summary,
        operator_id=operator["id"],
        operator_name=operator["name"],
        operator_roles=_dump(operator["roles"]) or "[]",
        reason=(reason or "").strip() or None,
        correlation_id=correlation_id or new_correlation_id(),
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        order_id=metadata["order_id"],
        customer_name=metadata["customer_name"],
        deleted=bool(after is None or bool((after or {}).get("deleted"))),
    )
    session.add(version)
    session.flush()
    for sequence_no, change in enumerate(changes, 1):
        session.add(OrderVersionChangeTable(
            version_id=version.id,
            sequence_no=sequence_no,
            entity_type=change["entity_type"],
            entity_uid=change["entity_uid"],
            operation=change["operation"],
            before_data=_dump(change["before_data"]),
            after_data=_dump(change["after_data"]),
        ))
    session.flush()
    return version


def ensure_baseline(
    session,
    order_uid: str,
    snapshot: Optional[dict] = None,
    *,
    operator_payload: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> Optional[OrderVersionTable]:
    exists = (
        session.query(OrderVersionTable.id)
        .filter(OrderVersionTable.order_uid == order_uid)
        .order_by(OrderVersionTable.version_no.desc())
        .with_for_update()
        .first()
    )
    if exists is not None:
        return None
    snapshot = snapshot if snapshot is not None else snapshot_order(session, order_uid)
    if snapshot is None:
        return None
    return append_version(
        session,
        order_uid,
        before=None,
        after=snapshot,
        action="baseline_import",
        summary="导入订单基线",
        operator_payload=operator_payload,
        correlation_id=correlation_id,
        force=True,
    )


def record_mutation(
    session,
    order_uid: str,
    *,
    before: Optional[dict],
    after: Optional[dict],
    action: str,
    summary: str,
    operator_payload: Optional[dict] = None,
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Optional[OrderVersionTable]:
    correlation_id = correlation_id or new_correlation_id()
    # Existing rows upgraded before the release may reach a write path before the
    # deployment backfill. Seed V1 in the very same transaction as the mutation.
    if before is not None:
        ensure_baseline(
            session,
            order_uid,
            before,
            operator_payload=operator_payload,
            correlation_id=correlation_id,
        )
    return append_version(
        session,
        order_uid,
        before=before,
        after=after,
        action=action,
        summary=summary,
        operator_payload=operator_payload,
        reason=reason,
        correlation_id=correlation_id,
    )


def create_order_version(
    session,
    order_uid: str,
    snapshot: dict,
    *,
    operator_payload: Optional[dict] = None,
) -> OrderVersionTable:
    return append_version(
        session,
        order_uid,
        before=None,
        after=snapshot,
        action="order_created",
        summary="创建订单",
        operator_payload=operator_payload,
        force=True,
    )


def change_to_dict(change: OrderVersionChangeTable, *, include_values: bool = True) -> dict:
    before = _load(change.before_data)
    after = _load(change.after_data)
    data = {
        "sequence_no": change.sequence_no,
        "entity_type": change.entity_type,
        "entity_uid": change.entity_uid,
        "operation": change.operation,
        "fields": sorted(set((before or {}).keys()) | set((after or {}).keys())),
    }
    if include_values:
        data["before_data"] = before
        data["after_data"] = after
    return data


def version_to_dict(version: OrderVersionTable, *, include_changes: bool = False) -> dict:
    data = {
        "id": version.id,
        "order_uid": version.order_uid,
        "version_no": version.version_no,
        "action": version.action,
        "summary": version.summary,
        "operator_id": version.operator_id,
        "operator_name": version.operator_name,
        "operator_roles": _load(version.operator_roles) or [],
        "reason": version.reason,
        "correlation_id": version.correlation_id,
        "created_at": version.created_at,
        "order_id": version.order_id,
        "customer_name": version.customer_name,
        "deleted": bool(version.deleted),
        "change_count": len(version.changes),
        "change_summary": [change_to_dict(change, include_values=False) for change in version.changes],
    }
    if include_changes:
        data["changes"] = [change_to_dict(change) for change in version.changes]
    return data


def _empty_snapshot() -> dict:
    return {"order": None, "cargos": [], "boxes": [], "deleted": False}


def _apply_change(snapshot: dict, change: OrderVersionChangeTable) -> None:
    entity_type = change.entity_type
    before = _load(change.before_data)
    after = _load(change.after_data)
    if entity_type == "order":
        if change.operation == "create":
            snapshot["order"] = deepcopy(after)
        elif change.operation == "delete":
            snapshot["order"] = None
            snapshot["deleted"] = True
        else:
            snapshot["order"] = snapshot.get("order") or {"uid": change.entity_uid}
            snapshot["order"].update(deepcopy(after or {}))
        return

    list_name = "boxes" if entity_type == "box" else "cargos"
    rows = snapshot[list_name]
    index = next((idx for idx, row in enumerate(rows) if str(row.get("uid")) == change.entity_uid), None)
    if change.operation == "create":
        rows.append(deepcopy(after))
    elif change.operation == "delete":
        if index is not None:
            rows.pop(index)
    elif index is not None:
        rows[index].update(deepcopy(after or {}))
    else:
        rows.append({"uid": change.entity_uid, **deepcopy(after or {})})
    rows.sort(key=lambda row: str(row.get("uid") or ""))


def reconstruct_snapshot(session, order_uid: str, version_no: int) -> tuple[dict, Optional[dict]]:
    rows = (
        session.query(OrderVersionTable)
        .filter(
            OrderVersionTable.order_uid == order_uid,
            OrderVersionTable.version_no <= version_no,
        )
        .order_by(OrderVersionTable.version_no.asc())
        .all()
    )
    snapshot = _empty_snapshot()
    last_existing = None
    for version in rows:
        if snapshot.get("order") is not None:
            last_existing = deepcopy(snapshot)
        for change in version.changes:
            _apply_change(snapshot, change)
    if snapshot.get("order") is not None:
        last_existing = deepcopy(snapshot)
    return snapshot, last_existing


def list_versions(order_uid: str, page: int = 1, page_size: int = 20) -> dict:
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    with SessionFactory() as session:
        query = (
            session.query(OrderVersionTable)
            .options(selectinload(OrderVersionTable.changes))
            .filter(OrderVersionTable.order_uid == order_uid)
        )
        total = query.count()
        rows = (
            query.order_by(OrderVersionTable.version_no.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [version_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def get_version_detail(order_uid: str, version_no: int) -> Optional[dict]:
    with SessionFactory() as session:
        version = (
            session.query(OrderVersionTable)
            .options(selectinload(OrderVersionTable.changes))
            .filter(
                OrderVersionTable.order_uid == order_uid,
                OrderVersionTable.version_no == version_no,
            )
            .first()
        )
        if version is None:
            return None
        snapshot, previous_snapshot = reconstruct_snapshot(session, order_uid, version_no)
        data = version_to_dict(version, include_changes=True)
        data["snapshot"] = snapshot
        if snapshot.get("deleted"):
            data["last_existing_snapshot"] = previous_snapshot
        return data


def current_version_no(session, order_uid: str) -> int:
    return int(
        session.query(func.max(OrderVersionTable.version_no))
        .filter(OrderVersionTable.order_uid == order_uid)
        .scalar()
        or 0
    )


def list_historical_orders(
    *,
    deleted_only: bool = True,
    query_text: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), 100)
    with SessionFactory() as session:
        latest = (
            session.query(
                OrderVersionTable.order_uid.label("order_uid"),
                func.max(OrderVersionTable.version_no).label("version_no"),
            )
            .group_by(OrderVersionTable.order_uid)
            .subquery()
        )
        query = session.query(OrderVersionTable).options(
            selectinload(OrderVersionTable.changes)
        ).join(
            latest,
            (OrderVersionTable.order_uid == latest.c.order_uid)
            & (OrderVersionTable.version_no == latest.c.version_no),
        )
        if deleted_only:
            query = query.filter(OrderVersionTable.deleted == True)  # noqa: E712
        q = (query_text or "").strip()
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                OrderVersionTable.order_uid.ilike(like),
                OrderVersionTable.order_id.ilike(like),
                OrderVersionTable.customer_name.ilike(like),
            ))
        total = query.count()
        rows = (
            query.order_by(OrderVersionTable.created_at.desc(), OrderVersionTable.order_uid.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "items": [version_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def backfill_baselines(session, order_uids: Optional[Iterable[str]] = None) -> dict:
    query = session.query(OrderTable.uid).order_by(OrderTable.uid.asc())
    if order_uids is not None:
        query = query.filter(OrderTable.uid.in_(list(order_uids)))
    uids = [row[0] for row in query.all()]
    created = 0
    skipped = 0
    correlation_id = new_correlation_id()
    for order_uid in uids:
        snapshot = snapshot_order(session, order_uid, lock=True)
        if ensure_baseline(session, order_uid, snapshot, correlation_id=correlation_id):
            created += 1
        else:
            skipped += 1
    return {"orders": len(uids), "created": created, "skipped": skipped}
