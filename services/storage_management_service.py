"""Inspect and explicitly remove private paper photos without changing cargo history."""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from data import database
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable, PaperPhotoCleanupTable
from data.packing.PackingList import PackingListTable
from services import paper_photo_storage as photo_storage


STORAGE_ROLES = ["admin", "store_manager"]
DEFAULT_DAYS = 90
LOCAL_TIMEZONE = timezone(timedelta(hours=8))


class StorageManagementError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _integer(value, name, default, maximum):
    if value is None:
        return default
    text = str(value)
    if isinstance(value, bool) or len(text) > 16 or not re.fullmatch(r"[0-9]+", text):
        raise StorageManagementError(f"{name}须为整数")
    number = int(text)
    if not 1 <= number <= maximum:
        raise StorageManagementError(f"{name}须介于1和{maximum}之间")
    return number


def parse_days(value=None):
    return _integer(value, "保留天数", DEFAULT_DAYS, 3650)


def current_time():
    return datetime.now(LOCAL_TIMEZONE).replace(tzinfo=None)


def _shipped_at(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip())
        if result.tzinfo is not None:
            result = result.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
        return result
    except (ValueError, OverflowError):
        return None


def _last_eligible_shipment(boxes, cutoff):
    if not boxes:
        return None
    dates = []
    for box in boxes:
        shipped_at = _shipped_at(box.date)
        if box.status != 1 or shipped_at is None or shipped_at > cutoff:
            return None
        dates.append(shipped_at)
    return max(dates)


def _existing_files(paths):
    result = {}
    for path in set(paths):
        if not path:
            continue
        try:
            size = photo_storage.file_size(path)
        except (OSError, ValueError):
            size = None
        if size is not None:
            result[path] = size
    return result


def _json_object(value):
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_mark(source, draft, candidate):
    # Match paper intake identity: a saved review wins over the AI candidate.
    status = getattr(source, "intake_status", getattr(source, "status", None))
    reviewed = "operator_name" in draft or bool(draft.get("boxes")) or status == "confirmed"
    choices = ((draft.get("mark") if reviewed else None), candidate.get("mark"),
               draft.get("mark"), source.mark_hint)
    return next((mark for mark in choices if isinstance(mark, str) and mark.strip()), "")


def _cleanup_reason(source, boxes, now):
    if source.intake_status == "deleted":
        return "纸单来源已删除"
    if source.intake_status != "confirmed" or not source.packing_list_uid:
        return "纸单上传尚未完成"
    if not source.formal_uid:
        return "关联装箱单不存在"
    if not boxes:
        return "装箱单没有箱子"
    if any(box.status != 1 for box in boxes):
        return "尚有箱子未出货"
    if any(_shipped_at(box.date) is None for box in boxes):
        return "出货时间不完整"
    if _last_eligible_shipment(boxes, now - timedelta(days=DEFAULT_DAYS)) is None:
        return f"最后出货未满{DEFAULT_DAYS}天"
    return ""


def _all_photo_groups(session, query=""):
    """Show every source that has photo records, regardless of shipment or disk loss."""
    rows = session.query(
        IntakeTable.uid.label("intake_uid"), IntakeTable.status.label("intake_status"),
        IntakeTable.packing_list_uid, IntakeTable.mark_hint, IntakeTable.draft_json,
        IntakeTable.recognition_result_json,
        PackingListTable.uid.label("formal_uid"), PackingListTable.list_number,
        PackingListTable.archive.label("packing_archived"),
        IntakePhotoTable.storage_path,
    ).join(IntakePhotoTable, IntakePhotoTable.intake_uid == IntakeTable.uid).outerjoin(
        PackingListTable, PackingListTable.uid == IntakeTable.packing_list_uid,
    ).all()
    paths_by_source = defaultdict(list)
    sources = {}
    for row in rows:
        sources[row.intake_uid] = row
        paths_by_source[row.intake_uid].append(row.storage_path)
    boxes_by_list = defaultdict(list)
    formal_uids = {row.formal_uid for row in sources.values() if row.formal_uid}
    if formal_uids:
        for box in session.query(CargoTable.packing_list_uid, CargoTable.status, CargoTable.date).filter(
            CargoTable.packing_list_uid.in_(formal_uids),
        ).all():
            boxes_by_list[box.packing_list_uid].append(box)
    now = current_time()
    items = []
    for intake_uid, source in sources.items():
        draft = _json_object(source.draft_json)
        candidate = _json_object(source.recognition_result_json)
        number = source.list_number or _source_mark(source, draft, candidate) or f"纸单-{intake_uid[:8]}"
        if query and query.casefold() not in number.casefold():
            continue
        paths = paths_by_source[intake_uid]
        files = _existing_files(paths)
        boxes = boxes_by_list[source.formal_uid]
        dates = [_shipped_at(box.date) for box in boxes if box.status == 1]
        shipped_at = max((date for date in dates if date is not None), default=None)
        reviewed = "operator_name" in draft or bool(draft.get("boxes")) or source.intake_status == "confirmed"
        draft_boxes = (draft if reviewed else candidate).get("boxes") or []
        reason = _cleanup_reason(source, boxes, now)
        detail_url, detail_label = None, None
        if source.formal_uid and not source.packing_archived and source.intake_status != "deleted":
            detail_url = f"/packing-lists/{source.formal_uid}"
            detail_label = "查看装箱单"
        items.append({
            "uid": source.formal_uid or intake_uid, "intake_uid": intake_uid,
            "packing_list_uid": source.formal_uid, "list_number": number,
            "archived": bool(source.packing_archived),
            "detail_url": detail_url, "detail_label": detail_label,
            "photo_count": len(paths), "photo_bytes": sum(files.values()),
            "missing_photo_count": sum(path not in files for path in paths),
            "box_count": len(boxes) if source.formal_uid else (len(draft_boxes) if isinstance(draft_boxes, list) else 0),
            "last_shipped_at": shipped_at.isoformat(sep=" ", timespec="seconds") if shipped_at else None,
            "days_since_shipped": (now - shipped_at).days if shipped_at else None,
            "can_delete_photos": True, "deletion_warning": reason, "cleanup_reason": reason,
        })
    return sorted(items, key=lambda item: (item["list_number"].casefold(), item["intake_uid"]))


def storage_summary(days=None):
    parse_days(days)  # Validate the legacy parameter; it no longer filters photo groups.
    files = dict(photo_storage.iter_files())
    with database.SessionFactory() as session:
        groups = _all_photo_groups(session)
        eligible = [group for group in groups if not group["deletion_warning"] and group["photo_count"] > group["missing_photo_count"]]
        queued = session.query(PaperPhotoCleanupTable.storage_path).all()
        pending_files = _existing_files(path for (path,) in queued)
    return {
        "total_bytes": sum(files.values()), "total_files": len(files),
        "photo_groups": len(groups),
        "eligible_bytes": sum(item["photo_bytes"] for item in eligible),
        "eligible_files": sum(item["photo_count"] - item["missing_photo_count"] for item in eligible),
        "eligible_packing_lists": len(eligible),
        "pending_cleanup_files": len(queued),
        "pending_cleanup_bytes": sum(pending_files.values()),
    }


def list_packing_list_photos(page=None, page_size=None, q=None, days=None):
    parse_days(days)  # Old clients may send this parameter, but all sources remain visible.
    page = _integer(page, "页码", 1, 100000)
    page_size = _integer(page_size, "每页数量", 20, 100)
    if q is not None and not isinstance(q, str):
        raise StorageManagementError("搜索条件须为文本")
    if len(q or "") > 64 or any(ord(char) < 32 for char in (q or "")):
        raise StorageManagementError("搜索条件最多64字且不能包含控制字符")
    query = (q or "").strip()
    with database.SessionFactory() as session:
        items = _all_photo_groups(session, query)
    offset = (page - 1) * page_size
    return {"items": items[offset:offset + page_size], "total": len(items),
            "page": page, "page_size": page_size}


def delete_packing_list_photos(uid, days=None):
    parse_days(days)  # Kept for old clients; retention is now a confirmation warning.
    with database.SessionFactory() as session:
        # Shipment and undo operations lock cargos; use the same deterministic order.
        boxes = session.query(CargoTable).filter_by(packing_list_uid=uid).order_by(
            CargoTable.uid,
        ).with_for_update().all()
        packing_list = session.query(PackingListTable).filter_by(uid=uid).with_for_update().first()
        if packing_list is None:
            raise StorageManagementError("装箱单不存在", 404)
        # A box may have been added before the parent lock was acquired. Its FK
        # now prevents another insertion; reread every box under the row locks.
        boxes = session.query(CargoTable).filter_by(packing_list_uid=uid).order_by(
            CargoTable.uid,
        ).populate_existing().with_for_update().all()
        sources = session.query(IntakeTable).filter_by(
            packing_list_uid=uid,
        ).order_by(IntakeTable.uid).with_for_update().all()
        # Lock photo rows as well before transferring their ownership to the queue.
        photos = session.query(IntakePhotoTable).filter(
            IntakePhotoTable.intake_uid.in_([source.uid for source in sources]),
        ).order_by(IntakePhotoTable.uid).with_for_update().all() if sources else []
        photo_storage.queue_photo_deletion(session, photos, packing_list_uid=uid)
        for source in sources:
            source.photos.clear()
        session.commit()
    return photo_storage.drain_photo_cleanup(factory=database.SessionFactory, packing_list_uid=uid)


def _intake_photo_name(record, packing_list=None):
    return (packing_list.list_number if packing_list else None) or _source_mark(
        record, _json_object(record.draft_json), _json_object(record.recognition_result_json),
    ) or f"纸单-{record.uid[:8]}"


def _photo_filename(photo, list_number):
    basename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", list_number).strip(". ") or "纸单"
    suffix = photo_storage.EXTENSIONS.get(photo.mime_type)
    return f"{basename}-{photo.position + 1:02d}.{suffix}" if suffix else photo.filename


def list_intake_photos(uid):
    with database.SessionFactory() as session:
        source = session.query(IntakeTable).filter_by(uid=uid).first()
        if source is None:
            raise StorageManagementError("纸单来源不存在", 404)
        packing_list = session.get(PackingListTable, source.packing_list_uid) if source.packing_list_uid else None
        list_number = _intake_photo_name(source, packing_list)
        return {"intake_uid": source.uid, "list_number": list_number, "photos": [{
            "uid": photo.uid, "filename": _photo_filename(photo, list_number),
            "original_filename": photo.filename, "mime_type": photo.mime_type,
            "url": f"/api/storage/intakes/{source.uid}/photos/{photo.uid}",
            "missing": photo_storage.file_size(photo.storage_path) is None,
        } for photo in source.photos]}


def get_intake_photo(uid, photo_uid):
    with database.SessionFactory() as session:
        source = session.query(IntakeTable).filter_by(uid=uid).first()
        if source is None:
            raise StorageManagementError("纸单来源不存在", 404)
        photo = session.query(IntakePhotoTable).filter_by(uid=photo_uid, intake_uid=uid).first()
        if photo is None:
            raise StorageManagementError("照片不存在", 404)
        try:
            data = photo_storage.read_bytes(photo)
        except FileNotFoundError:
            raise StorageManagementError("照片文件不存在或已清理", 404)
        except (OSError, ValueError):
            raise StorageManagementError("照片文件不可用", 409)
        packing_list = session.get(PackingListTable, source.packing_list_uid) if source.packing_list_uid else None
        return data, photo.mime_type, _photo_filename(photo, _intake_photo_name(source, packing_list))


def delete_intake_photos(uid, days=None):
    parse_days(days)
    with database.SessionFactory() as session:
        source = session.query(IntakeTable).filter_by(uid=uid).with_for_update().first()
        if source is None:
            raise StorageManagementError("纸单来源不存在", 404)
        photos = session.query(IntakePhotoTable).filter_by(intake_uid=uid).order_by(
            IntakePhotoTable.uid,
        ).with_for_update().all()
        photo_storage.queue_photo_deletion(session, photos, packing_list_uid=source.packing_list_uid)
        # Include earlier failed attempts so the same source deletion can be retried.
        queued_paths = [path for (path,) in session.query(PaperPhotoCleanupTable.storage_path).filter(
            PaperPhotoCleanupTable.storage_path.startswith(f"{source.uid}/", autoescape=True),
        ).all()]
        paths = set(queued_paths) | {photo.storage_path for photo in photos}
        source.photos.clear()
        session.commit()
    return photo_storage.drain_photo_cleanup(factory=database.SessionFactory, storage_paths=paths)


def retry_photo_cleanup():
    return photo_storage.drain_photo_cleanup(factory=database.SessionFactory)
