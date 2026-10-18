"""Uploader-checked paper submissions and isolated recognition candidates."""
import json
import logging
import math
import re
import threading
import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from Auth import get_payload_roles
from data import database
from data.DB import CargoTable, GoodsNameTable
from data.intake import IntakePhotoTable, IntakeTable, PaperPhotoCleanupTable
from data.packing.PackingList import PackingListTable, PackingListModel, BoxModel, BoxWorkerTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import paper_photo_storage

STAFF_READ_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
WORKER_ROLES = {"worker", "employee"}
SUBMIT_ROLES = STAFF_READ_ROLES | WORKER_ROLES
MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_TOTAL_PHOTO_BYTES = 24 * 1024 * 1024
MAX_ITEM_DETAILS = 100


class IntakeError(ValueError):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.status = status
        self.data = data


def now():
    return datetime.now().isoformat(timespec="seconds")


def require_role(payload):
    if not set(get_payload_roles(payload)).intersection(SUBMIT_ROLES):
        raise IntakeError("没有纸单回传操作权限", 403)
    if not payload.get("user_id"):
        raise IntakeError("登录身份无效", 401)


def load_record(session, uid, payload, lock=False, owner_only=False):
    require_role(payload)
    query = session.query(IntakeTable).filter_by(uid=uid)
    if lock:
        query = query.with_for_update()
    record = query.first()
    if record is None or record.status in {"deleted", "deleting"}:
        raise IntakeError("回传记录不存在", 404)
    if record.submitted_by != payload["user_id"]:
        staff_history = record.status == "confirmed" and bool(set(get_payload_roles(payload)).intersection(STAFF_READ_ROLES))
        if owner_only or not staff_history:
            raise IntakeError("只能查看或核对自己的上传记录", 403)
    return record


def _paper_identity(record, draft, candidate):
    # A saved review (including an intentionally blank operator) wins over AI.
    reviewed = "operator_name" in draft or bool(draft.get("boxes")) or record.status == "confirmed"
    mark = (draft.get("mark") if reviewed else "") or candidate.get("mark") or draft.get("mark") or record.mark_hint
    operator = draft["operator_name"] if "operator_name" in draft else candidate.get("operator_name", "")
    return mark or "", operator or ""


def _photo_filename(photo, display_name):
    basename = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", display_name).strip(". ")[:64] or "纸单"
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[photo.mime_type]
    return f"{basename}-{photo.position + 1:02d}{suffix}"


def serialize(record):
    fields = ("uid", "submitted_by", "submitted_by_name", "created_at", "operation_at", "mark_hint", "note", "status", "version", "confirmed_by", "confirmed_at", "packing_list_uid", "recognition_status", "recognition_error")
    result = {key: getattr(record, key) for key in fields}
    result["draft"] = json.loads(record.draft_json)
    result["draft_is_manual"] = "worker_ids" in result["draft"] or "operator_name" in result["draft"] or bool(result["draft"].get("boxes"))
    result["recognition_result"] = json.loads(record.recognition_result_json) if record.recognition_result_json else None
    mark, operator = _paper_identity(record, result["draft"], result["recognition_result"] or {})
    result["display_name"] = mark or f"纸单-{record.uid[:8]}"
    result["operator_name"] = operator
    result["photos"] = [{"uid": photo.uid, "filename": _photo_filename(photo, result["display_name"]), "original_filename": photo.filename, "mime_type": photo.mime_type, "url": f"/api/intakes/{record.uid}/photos/{photo.uid}"} for photo in record.photos]
    return result


def _text(value, field, limit):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise IntakeError(f"{field}须为不超过{limit}字的文字")
    return value.strip()


def _approved_workers(session):
    return session.query(UserTable).filter(
        UserTable.status == "approved",
        UserTable.roles.any(RoleTable.name.in_(WORKER_ROLES)),
    )


def list_workers(payload):
    require_role(payload)
    with database.SessionFactory() as session:
        workers = _approved_workers(session).order_by(UserTable.name, UserTable.id).all()
        return [{"id": worker.id, "name": worker.name} for worker in workers]


def _normalize_worker_ids(worker_ids):
    if not isinstance(worker_ids, list):
        raise IntakeError("操作工人须为ID列表")
    normalized = []
    for worker_id in worker_ids:
        if isinstance(worker_id, bool) or not isinstance(worker_id, int) or not 0 < worker_id <= 2147483647:
            raise IntakeError("操作工人ID须为正整数")
        if worker_id not in normalized:
            normalized.append(worker_id)
    if len(normalized) > BoxModel.MAX_WORKERS:
        raise IntakeError(f"每箱最多绑定{BoxModel.MAX_WORKERS}位操作工人")
    return normalized


def _validate_worker_ids(session, worker_ids, complete=False):
    if complete and not worker_ids:
        raise IntakeError("确认前请至少选择一位真实操作工人")
    if worker_ids:
        valid_ids = {worker.id for worker in _approved_workers(session).filter(UserTable.id.in_(worker_ids)).all()}
        if valid_ids != set(worker_ids):
            raise IntakeError("操作工人须为已批准的工人账号，请刷新工人列表后重新选择")


def _bind_recognition_workers(session, candidate):
    candidate = dict(candidate)
    warnings = candidate.get("warnings")
    candidate["warnings"] = list(warnings) if isinstance(warnings, list) else []
    workers_by_name = {}
    for worker in _approved_workers(session).all():
        workers_by_name.setdefault(worker.name.strip(), []).append(worker.id)
    def bind_names(operator_name, label):
        names = list(dict.fromkeys(name.strip() for name in re.split(r"[、，,;；]", operator_name or "") if name.strip())) if isinstance(operator_name, str) else []
        if not names:
            candidate["warnings"].append(f"未识别到可绑定的{label}操作人员，请手动选择真实工人")
            return []
        if len(names) > BoxModel.MAX_WORKERS:
            candidate["warnings"].append(f"{label}操作人员超过{BoxModel.MAX_WORKERS}位，请人工核对并选择工人")
            return []
        matched = []
        for name in names:
            ids = workers_by_name.get(name, [])
            if not ids:
                candidate["warnings"].append(f"{label}操作人员“{name}”未匹配到已批准工人，请手动选择")
            elif len(ids) > 1:
                candidate["warnings"].append(f"{label}操作人员“{name}”存在同名工人，请手动选择")
            else:
                matched.append(ids[0])
        # Partial matching must not silently omit a named worker.
        return matched if len(matched) == len(names) else []
    # Kept as a legacy candidate hint; per-box selections are authoritative.
    source_boxes = candidate.get("boxes") or []
    needs_paper_workers = not source_boxes or any("worker_ids" not in row and "operator_name" not in row for row in source_boxes)
    candidate["worker_ids"] = bind_names(candidate.get("operator_name"), "纸单") if candidate.get("operator_name") or needs_paper_workers else []
    boxes = []
    for index, source in enumerate(source_boxes, 1):
        row = dict(source)
        if "worker_ids" in row:
            try:
                row["worker_ids"] = _normalize_worker_ids(row["worker_ids"])
                _validate_worker_ids(session, row["worker_ids"])
            except IntakeError:
                row["worker_ids"] = []
                candidate["warnings"].append(f"第{index}箱操作人员ID无效或不是已批准工人，请手动选择")
        elif "operator_name" in row:
            row["worker_ids"] = bind_names(row["operator_name"], f"第{index}箱")
        else:
            # Only missing per-box evidence may inherit the paper signature.
            row["worker_ids"] = list(candidate["worker_ids"])
        boxes.append(row)
    candidate["boxes"] = boxes
    return candidate


def my_packing_lists(payload, page=1, page_size=20, mark=None, status=None):
    """Return ownership-scoped metadata for manual lists and paper submissions."""
    require_role(payload)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    mark_filter = _text(mark, "查询唛头", 64).casefold()
    if status is not None and status not in {"uploading", "draft", "completed"}:
        raise IntakeError("装箱单状态须为上传中、草稿或已完成")
    with database.SessionFactory() as session:
        formal = session.query(
            PackingListTable.uid, PackingListTable.list_number,
            PackingListTable.status, PackingListTable.create_date,
            func.count(CargoTable.uid).label("box_count"),
        ).outerjoin(CargoTable, (CargoTable.packing_list_uid == PackingListTable.uid) & (CargoTable.archive == False)).filter(
            PackingListTable.creator_id == payload["user_id"],
            PackingListTable.archive == False,
        ).group_by(PackingListTable.uid, PackingListTable.list_number, PackingListTable.status, PackingListTable.create_date).all()
        paper_by_packing_uid = dict(session.query(IntakeTable.packing_list_uid, IntakeTable.uid).filter(
            IntakeTable.packing_list_uid.in_([row.uid for row in formal]),
            IntakeTable.status == "confirmed",
        ).all()) if formal else {}
        items = [{
            "uid": paper_by_packing_uid.get(row.uid, row.uid),
            "mark": row.list_number,
            "source": "paper" if row.uid in paper_by_packing_uid else "manual",
            "status": "completed" if row.status == "completed" else "draft",
            "created_at": row.create_date,
            "box_count": row.box_count,
            "packing_list_uid": row.uid,
        } for row in formal]
        pending = session.query(IntakeTable.uid, IntakeTable.created_at, IntakeTable.mark_hint, IntakeTable.draft_json, IntakeTable.recognition_result_json, IntakeTable.version, IntakeTable.status).filter(
            IntakeTable.submitted_by == payload["user_id"],
            IntakeTable.status.in_(("pending", "deleting")),
            IntakeTable.packing_list_uid.is_(None),
            IntakeTable.confirmed_by.is_(None),
            IntakeTable.confirmed_at.is_(None),
        ).all()
        for row in pending:
            draft = json.loads(row.draft_json)
            candidate = json.loads(row.recognition_result_json or "{}")
            manual = "worker_ids" in draft or "operator_name" in draft or bool(draft.get("boxes"))
            effective = draft if manual else candidate
            items.append({
                "uid": row.uid,
                "mark": effective.get("mark") or draft.get("mark") or row.mark_hint or "",
                "source": "paper",
                "status": "uploading",
                "created_at": row.created_at,
                "box_count": len(effective.get("boxes") or []),
                "packing_list_uid": None,
                "version": row.version,
                "can_delete": True,
                "photo_cleanup_pending": row.status == "deleting",
            })
        if mark_filter:
            items = [item for item in items if mark_filter in item["mark"].casefold()]
        if status:
            items = [item for item in items if item["status"] == status]
        items.sort(key=lambda item: ((item["created_at"] or "").replace("T", " "), item["uid"]), reverse=True)
        total = len(items)
        return {"items": items[(page - 1) * page_size:page * page_size], "total": total, "page": page, "page_size": page_size}


def _intake_cleanup_paths(session, uid):
    return [path for (path,) in session.query(PaperPhotoCleanupTable.storage_path).filter(
        PaperPhotoCleanupTable.storage_path.startswith(f"{uid}/", autoescape=True),
    ).all()]


def _check_intake_deletion(record, payload):
    if record.submitted_by != payload["user_id"]:
        raise IntakeError("只能删除自己的未完成上传", 403)
    if (record.status not in {"pending", "deleting"} or record.packing_list_uid is not None
            or record.confirmed_by is not None or record.confirmed_at is not None):
        raise IntakeError("已核对或已转为正式装箱单的上传不能在此删除", 409)


def _intake_cleanup_error():
    return IntakeError("纸单已停止上传，删除清理尚未完成；请重试删除", 503,
                       {"deleted": True, "photo_cleanup_pending": True})


def _finish_intake_deletion(payload, uid, paths):
    try:
        paper_photo_storage.drain_photo_cleanup(factory=database.SessionFactory, storage_paths=paths)
        with database.SessionFactory() as session:
            record = session.query(IntakeTable).filter_by(uid=uid).with_for_update().first()
            if record is None:
                return {"deleted": True, "photo_cleanup_pending": False}
            _check_intake_deletion(record, payload)
            if record.status != "deleting" or record.photos or _intake_cleanup_paths(session, uid):
                raise _intake_cleanup_error()
            session.delete(record)
            session.commit()
    except IntakeError:
        raise
    except StaleDataError:
        # Another retry may have finished deleting this tombstone already.
        try:
            with database.SessionFactory() as session:
                if session.get(IntakeTable, uid) is None:
                    return {"deleted": True, "photo_cleanup_pending": False}
        except Exception:
            logging.getLogger(__name__).exception("Could not verify concurrent paper deletion")
        raise _intake_cleanup_error()
    except Exception:
        # A removed file or a lost commit acknowledgement is safe to retry:
        # the durable queue and the owner-scoped tombstone survive rollback.
        logging.getLogger(__name__).exception("Unfinished paper deletion needs retry")
        raise _intake_cleanup_error()
    return {"deleted": True, "photo_cleanup_pending": False}


def delete_intake(payload, uid, version, *, _conflict_retry=True):
    """Revoke an uploader's unfinished source before deleting its private files."""
    require_role(payload)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise IntakeError("请刷新未完成上传列表后重新确认删除", 409)
    try:
        with database.SessionFactory() as session:
            record = session.query(IntakeTable).filter_by(uid=uid).with_for_update().first()
            # A repeated request after successful physical deletion is harmless.
            if record is None:
                return {"deleted": True, "photo_cleanup_pending": False}
            _check_intake_deletion(record, payload)
            if record.status == "pending":
                _check_edit(record, version)
                photos = list(record.photos)
                for photo in photos:
                    suffix = paper_photo_storage.EXTENSIONS.get(photo.mime_type)
                    expected = f"{record.uid}/{photo.uid}.{suffix}"
                    if suffix is None or photo.storage_path != expected:
                        raise IntakeError("照片存储归属异常，请联系管理员检查后重试", 409)
                record.status = "deleting"
                record.recognition_job_uid = None
                record.recognition_started_at = None
                record.recognition_status = "idle"
                record.recognition_error = None
                record.recognition_result_json = None
                # Win the version comparison before removing photo metadata.
                # Concurrent confirmation must roll back its inventory writes.
                session.flush()
                paper_photo_storage.queue_photo_deletion(session, photos)
                record.photos.clear()
                session.commit()
            # Retries use the original confirmed version; a tombstone cannot
            # be edited or completed, so they only finish the same deletion.
            paths = _intake_cleanup_paths(session, uid)
    except IntakeError:
        raise
    except (StaleDataError, IntegrityError):
        if _conflict_retry:
            return delete_intake(payload, uid, version, _conflict_retry=False)
        raise IntakeError("上传状态或版本已变化，请刷新后重新确认删除", 409)
    except Exception:
        # If COMMIT succeeded but its acknowledgement was lost, expose the
        # retryable state instead of claiming that nothing was changed.
        try:
            with database.SessionFactory() as session:
                committed = session.query(IntakeTable).filter_by(uid=uid).first()
                if committed is not None and committed.status == "deleting":
                    _check_intake_deletion(committed, payload)
                    raise _intake_cleanup_error()
        except IntakeError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("Could not verify paper deletion commit")
        raise
    return _finish_intake_deletion(payload, uid, paths)


def create_intake(payload, files, form):
    require_role(payload)
    if not 1 <= len(files) <= MAX_PHOTOS:
        raise IntakeError(f"请选择1至{MAX_PHOTOS}张照片")
    incoming = []
    total_bytes = 0
    for position, file in enumerate(files):
        data = file.read(MAX_PHOTO_BYTES + 1)
        if not data or len(data) > MAX_PHOTO_BYTES:
            raise IntakeError("每张照片须小于10MB且不能为空")
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_PHOTO_BYTES:
            raise IntakeError("照片合计不能超过24MB，请压缩或拆分回传", 413)
        try:
            with Image.open(BytesIO(data)) as image:
                fmt = image.format
                image.verify()
            mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(fmt)
            if not mime:
                raise IntakeError("照片仅支持JPEG、PNG和WebP，请转换后重试")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
            raise IntakeError("照片内容损坏或格式不支持，请重新选择")
        incoming.append((position, _text(file.filename or "照片", "文件名", 256), mime, data))
    mark_hint = _text(form.get("mark_hint"), "唛头提示", 64)
    operation_at = _text(form.get("operation_at"), "现场时间", 32) or None
    if operation_at:
        try:
            datetime.fromisoformat(operation_at)
        except ValueError:
            raise IntakeError("现场时间格式无效")
    note = _text(form.get("note"), "备注", 512)
    intake_uid = uuid4().hex
    photos = []
    committed = False
    try:
        for position, filename, mime, data in incoming:
            photo_uid = uuid4().hex
            photo = IntakePhotoTable(
                uid=photo_uid, position=position, filename=filename, mime_type=mime,
                storage_path=f"{intake_uid}/{photo_uid}.{paper_photo_storage.EXTENSIONS[mime]}",
                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            )
            # Include attempted writes so a partial disk failure is cleaned too.
            photos.append(photo)
            paper_photo_storage.save_bytes(intake_uid, photo_uid, mime, data)
        with database.SessionFactory() as session:
            record = IntakeTable(uid=intake_uid, submitted_by=payload["user_id"], submitted_by_name=str(payload.get("name") or payload["user_id"]), created_at=now(), operation_at=operation_at, mark_hint=mark_hint, note=note, draft_json=json.dumps({"mark": mark_hint, "boxes": []}, ensure_ascii=False), photos=photos)
            session.add(record)
            job_args = _prepare_recognition(record)
            session.commit()
            committed = True
            result = serialize(record)
    except Exception:
        if not committed:
            try:
                # A commit can succeed while its acknowledgement is lost. Check
                # persisted references before deleting any attempted upload.
                with database.SessionFactory() as session:
                    active = set(path for (path,) in session.query(IntakePhotoTable.storage_path).filter(
                        IntakePhotoTable.storage_path.in_([photo.storage_path for photo in photos]),
                    ).all()) if photos else set()
                failed = []
                for photo in photos:
                    if photo.storage_path in active:
                        continue
                    try:
                        paper_photo_storage.delete_file(photo.storage_path)
                    except OSError:
                        failed.append(photo)
                if failed:
                    # Preserve retries when the filesystem is temporarily unwritable.
                    with database.SessionFactory() as session:
                        paper_photo_storage.queue_photo_deletion(session, failed)
                        session.commit()
            except Exception:
                # An unavailable database leaves the files intact. Prefer an
                # orphan over deleting a photograph whose commit is uncertain.
                logging.getLogger(__name__).exception("Failed to verify or clean interrupted paper photo upload")
        raise
    if not _launch_recognition(job_args):
        return get_intake(payload, result["uid"])
    return result


def list_intakes(payload, status=None, page=1, page_size=20, packing_list_uid=None, mark=None):
    require_role(payload)
    if not packing_list_uid:
        raise IntakeError("待核对纸质单功能已移除，请在上传完成前自行核对", 410)
    packing_list_uid = _text(packing_list_uid, "装箱单ID", 32)
    with database.SessionFactory() as session:
        packing_list = session.query(PackingListTable).filter_by(uid=packing_list_uid, archive=False).first()
        if packing_list is None:
            raise IntakeError("装箱单不存在", 404)
        if not set(get_payload_roles(payload)).intersection(STAFF_READ_ROLES) and packing_list.creator_id != payload["user_id"]:
            raise IntakeError("只能查看自己创建的装箱单", 403)
        # This lookup is only for the source photos on a completed formal list.
        records = session.query(IntakeTable).filter_by(packing_list_uid=packing_list_uid, status="confirmed").all()
        return {"items": [serialize(record) for record in records], "total": len(records), "page": 1, "page_size": 20}


def _expire_recognition(record):
    # In-process jobs cannot survive a restart. Opening a submission enables retry.
    if record.recognition_status == "running" and record.recognition_started_at and datetime.fromisoformat(record.recognition_started_at) < datetime.now() - timedelta(minutes=5):
        record.recognition_status = "failed"
        record.recognition_error = "识别任务超时或服务已重启，请重试"
        record.recognition_job_uid = None
        return True
    return False


def get_intake(payload, uid):
    with database.SessionFactory() as session:
        record = load_record(session, uid, payload)
        if _expire_recognition(record):
            session.commit()
        return serialize(record)


def get_photo(payload, uid, photo_uid, with_filename=False):
    with database.SessionFactory() as session:
        record = load_record(session, uid, payload)
        photo = session.query(IntakePhotoTable).filter_by(uid=photo_uid, intake_uid=uid).first()
        if photo is None:
            raise IntakeError("照片不存在", 404)
        try:
            data = paper_photo_storage.read_bytes(photo)
        except FileNotFoundError:
            raise IntakeError("照片文件不存在或已清理", 404)
        if with_filename:
            mark, _ = _paper_identity(record, json.loads(record.draft_json), json.loads(record.recognition_result_json or "{}"))
            return data, photo.mime_type, _photo_filename(photo, mark or f"纸单-{record.uid[:8]}")
        return data, photo.mime_type


def _check_edit(record, version):
    if record.status != "pending":
        raise IntakeError("已确认回传不能修改草稿", 409)
    if isinstance(version, bool) or not isinstance(version, int) or version != record.version:
        raise IntakeError("回传已被更新，请刷新后重试（本地未保存内容请先保留）", 409)


def _editable_number(value, label):
    # A draft may retain incomplete scalar values for the uploader to correct.
    if isinstance(value, (list, dict, bool)):
        raise IntakeError(f"{label}格式无效")
    if isinstance(value, str) and len(value) > 32:
        raise IntakeError(f"{label}数字过长")
    if isinstance(value, float) and not math.isfinite(value):
        raise IntakeError(f"{label}数字须为有限值")


def _positive_integer(value):
    return not isinstance(value, bool) and bool(re.fullmatch(r"[1-9][0-9]*", str(value))) and int(value) <= 2147483647


def _normalize_box_items(item, row, index, complete):
    if "item_details" in row:
        details = row["item_details"]
        if not isinstance(details, list):
            raise IntakeError(f"第{index}行品名明细须为列表")
    else:
        # Older candidates can contain several names but only a combined count.
        # Keep that total as a reference and require real per-item quantities.
        names = [name.strip() for name in re.split(r"[、，,;；\n]", item["item_name"]) if name.strip()]
        if len(names) <= 1:
            return
        details = [{"item_name": name, "piece_count": None, "customs_code": ""} for name in names]
    if len(details) > MAX_ITEM_DETAILS:
        raise IntakeError(f"第{index}行每箱最多{MAX_ITEM_DETAILS}个品名")
    if complete and not details:
        raise IntakeError(f"第{index}行请至少填写一种品名及件数")
    normalized = []
    for detail_index, source in enumerate(details, 1):
        label = f"第{index}行第{detail_index}个品名"
        if not isinstance(source, dict):
            raise IntakeError(f"{label}明细格式无效")
        name = _text(source.get("item_name"), label, 256)
        customs_code = _text(source.get("customs_code"), f"{label}海关编码", 64)
        quantity = source.get("piece_count")
        _editable_number(quantity, f"{label}件数")
        if quantity is None or (isinstance(quantity, str) and not quantity.strip()):
            quantity = None
        if complete and not name:
            raise IntakeError(f"{label}不能为空")
        if _positive_integer(quantity):
            quantity = int(quantity)
        elif complete:
            raise IntakeError(f"{label}件数须为正整数")
        normalized.append({"item_name": name, "piece_count": quantity, "customs_code": customs_code})
    item["item_details"] = normalized
    item["item_name"] = _text("、".join(detail["item_name"] for detail in normalized if detail["item_name"]), f"第{index}行品名", 256)
    if normalized and all(_positive_integer(detail["piece_count"]) for detail in normalized):
        item["count"] = sum(detail["piece_count"] for detail in normalized)
    else:
        # A paper's total cannot reveal how many pieces belong to each product.
        item["count"] = int(item["count"]) if _positive_integer(item["count"]) else None
    item["piece_count"] = item["count"]


def normalize_draft(draft, complete=False):
    if not isinstance(draft, dict) or not isinstance(draft.get("boxes"), list):
        raise IntakeError("草稿须包含箱子列表")
    boxes = draft["boxes"]
    if len(boxes) > 500:
        raise IntakeError("单次回传最多500箱")
    mark = _text(draft.get("mark"), "唛头", 64)
    needs_legacy_workers = not boxes or any(isinstance(row, dict) and "worker_ids" not in row for row in boxes)
    legacy_workers = _normalize_worker_ids(draft.get("worker_ids", [])) if needs_legacy_workers else []
    normalized = []
    seen = set()
    if complete and (not mark or not boxes):
        raise IntakeError("确认前请填写唛头并至少录入一箱")
    for index, row in enumerate(boxes, 1):
        if not isinstance(row, dict):
            raise IntakeError(f"第{index}行格式无效")
        item = {key: row.get(key) for key in ("box_number", "item_name", "count", "weight")}
        try:
            item["worker_ids"] = _normalize_worker_ids(row["worker_ids"] if "worker_ids" in row else legacy_workers)
        except IntakeError as exc:
            raise IntakeError(f"第{index}行：{exc}") from None
        item["item_name"] = _text(item["item_name"], f"第{index}行品名", 256)
        if "remark" in row:
            item["remark"] = _text(row["remark"], f"第{index}行备注", 512)
        for key in ("box_number", "count", "weight"):
            _editable_number(item[key], f"第{index}行{key}")
        _normalize_box_items(item, row, index, complete)
        if complete:
            for key, label in (("box_number", "箱号"), ("count", "件数")):
                value = str(item[key] if item[key] is not None else "")
                if not re.fullmatch(r"[1-9][0-9]*", value) or int(value) > 2147483647:
                    raise IntakeError(f"第{index}行{label}须为正整数（当前系统箱号不支持字母或前导零）")
                item[key] = int(value)
            if item["box_number"] in seen:
                raise IntakeError(f"箱号{item['box_number']}重复，请对照纸单核对")
            seen.add(item["box_number"])
            if not item["item_name"]:
                raise IntakeError(f"第{index}行缺少品名")
            try:
                item["weight"] = float(item["weight"])
            except (TypeError, ValueError):
                raise IntakeError(f"第{index}行重量须为正数")
            if not math.isfinite(item["weight"]) or item["weight"] <= 0:
                raise IntakeError(f"第{index}行重量须为正数")
        normalized.append(item)
    return {"mark": mark, "operator_name": _text(draft.get("operator_name"), "操作人员", 128), "boxes": normalized}


def _validate_box_workers(session, boxes, complete=False):
    for index, row in enumerate(boxes, 1):
        try:
            _validate_worker_ids(session, row["worker_ids"], complete=complete)
        except IntakeError as exc:
            raise IntakeError(f"第{index}行：{exc}") from None


def save_draft(payload, uid, version, draft):
    require_role(payload)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True, owner_only=True)
            _check_edit(record, version)
            normalized = normalize_draft(draft)
            _validate_box_workers(session, normalized["boxes"])
            if not normalized["boxes"] and "worker_ids" in draft:
                _validate_worker_ids(session, _normalize_worker_ids(draft["worker_ids"]))
            record.draft_json = json.dumps(normalized, ensure_ascii=False, allow_nan=False)
            # Saving identical contents must still advance the version.
            record.version += 1
            session.commit()
            return serialize(record)
    except StaleDataError:
        raise IntakeError("回传已被更新，请刷新后重试", 409)


def _new_box(packing_uid, mark, row, timestamp):
    uid = uuid4().hex
    details = row["item_details"] if "item_details" in row else [{"item_name": row["item_name"], "piece_count": row["count"], "customs_code": ""}]
    return CargoTable(uid=uid, origin_id=f"BOX-{uid}", tag=BoxModel()._build_box_tag(mark, row["box_number"]), transfer_id="", waybill_id="", target_order_uid=None, count=row["count"], piece_count=row["count"], item_name=row["item_name"], real_en_name=row["item_name"], item_details=json.dumps(details, ensure_ascii=False), remark=row.get("remark") or None, box_number=row["box_number"], weight=row["weight"], price=0.0, status=0, box_status="pending", archive=False, packing_list_uid=packing_uid, create_date=timestamp)


def _recognition_mark(session, candidate):
    """Show the same available mark as manual creation without reserving it."""
    candidate = dict(candidate)
    model = PackingListModel()
    original = model._normalize_mark(candidate.get("mark"))
    candidate.pop("original_mark", None)
    if original:
        candidate["mark"] = model._generate_unique_list_number(original, session)
        if candidate["mark"] != original:
            candidate["original_mark"] = original
            candidate["warnings"] = [*candidate.get("warnings", []), f"唛头{original}已存在，已自动改为{candidate['mark']}"]
    return candidate


def _confirmation_mark(session, record, draft):
    model = PackingListModel()
    mark = model._normalize_mark(draft["mark"])
    candidate = json.loads(record.recognition_result_json or "{}")
    # A candidate is only a preview. If another upload has since taken it,
    # allocate from the original mark to avoid stacking the date twice.
    if (
        candidate.get("original_mark") and mark == candidate.get("mark")
        and session.query(PackingListTable.uid).filter_by(list_number=mark).first()
    ):
        mark = candidate["original_mark"]
    return model._generate_unique_list_number(mark, session)


def confirm_intake(payload, uid, version, reviewed=False, *, _mark_attempt=0):
    require_role(payload)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True, owner_only=True)
            if reviewed is not True:
                raise IntakeError("请先对照纸质单检查并确认识别结果")
            if record.status == "confirmed":
                return serialize(record)
            _check_edit(record, version)
            if record.recognition_status == "running":
                raise IntakeError("识别尚未完成，请等待后检查识别结果再完成上传", 409)
            stored_draft = json.loads(record.draft_json)
            draft = normalize_draft(stored_draft, complete=True)
            _validate_box_workers(session, draft["boxes"], complete=True)
            mark = _confirmation_mark(session, record, draft)
            draft["mark"] = mark
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            packing_uid = uuid4().hex
            session.add(PackingListTable(uid=packing_uid, list_number=mark, creator_id=record.submitted_by, photos="[]", status="draft", create_date=timestamp, archive=False))
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                # The unique index arbitrates simultaneous uploads of the
                # same mark. Retry from a fresh transaction and revalidate the
                # uploader's saved version before allocating the next suffix.
                if _mark_attempt < 2:
                    return confirm_intake(payload, uid, version, reviewed, _mark_attempt=_mark_attempt + 1)
                raise
            for row in draft["boxes"]:
                box = _new_box(packing_uid, mark, row, timestamp)
                session.add(box)
                session.flush()
                for worker_id in row["worker_ids"]:
                    session.add(BoxWorkerTable(box_uid=box.uid, worker_id=worker_id, create_date=timestamp))
                session.flush()
            record.status = "confirmed"
            record.packing_list_uid = packing_uid
            record.confirmed_by = payload["user_id"]
            record.confirmed_at = now()
            record.draft_json = json.dumps({**stored_draft, "mark": mark}, ensure_ascii=False, allow_nan=False)
            session.commit()
            return serialize(record)
    except (StaleDataError, IntegrityError):
        # A concurrent confirmation can have committed while this one waited.
        result = get_intake(payload, uid)
        if result["status"] == "confirmed":
            return result
        raise IntakeError("唛头或回传版本发生冲突，请刷新后核对", 409)


def run_recognition(uid, job_uid, images, mark_hint):
    try:
        with database.SessionFactory() as session:
            record = session.query(IntakeTable).filter_by(uid=uid).first()
            if record is None or record.status != "pending" or record.recognition_job_uid != job_uid or record.recognition_status != "running":
                return
            goods_name_hints = [name for (name,) in session.query(GoodsNameTable.name).filter(
                GoodsNameTable.lang.in_(("cn", "en")),
            ).order_by(case((GoodsNameTable.lang == "cn", 0), else_=1), GoodsNameTable.id).limit(400).all()]
        from services.intake_recognition import recognize_paper_photos
        candidate = recognize_paper_photos(images, mark_hint=mark_hint, goods_name_hints=goods_name_hints)
        with database.SessionFactory() as session:
            candidate = _bind_recognition_workers(session, candidate)
            candidate = _recognition_mark(session, candidate)
        result_json = json.dumps(candidate, ensure_ascii=False, allow_nan=False)
        status, error = "succeeded", None
    except Exception as exc:
        logging.getLogger(__name__).warning("Paper recognition failed: %s", type(exc).__name__)
        result_json, status, error = None, "failed", str(exc)[:512]
    # A simultaneous human save can advance the optimistic version on SQLite.
    # Reload and persist only the candidate; never rerun the provider request.
    for attempt in range(3):
        try:
            with database.SessionFactory() as session:
                record = session.query(IntakeTable).filter_by(uid=uid).with_for_update().first()
                if record is None or record.status != "pending" or record.recognition_job_uid != job_uid or record.recognition_status != "running":
                    return
                record.recognition_status = status
                record.recognition_error = error
                record.recognition_result_json = result_json
                session.commit()
                return
        except StaleDataError:
            if attempt == 2:
                logging.getLogger(__name__).exception("Failed to persist paper recognition status after concurrent edits")
        except Exception:
            logging.getLogger(__name__).exception("Failed to persist paper recognition status")
            return


def _prepare_recognition(record):
    job_uid = uuid4().hex
    images = [{"data": paper_photo_storage.read_bytes(photo), "mime_type": photo.mime_type, "filename": photo.filename} for photo in record.photos]
    record.recognition_status = "running"
    record.recognition_error = None
    record.recognition_result_json = None
    record.recognition_job_uid = job_uid
    record.recognition_started_at = now()
    return record.uid, job_uid, images, record.mark_hint


def _launch_recognition(job_args):
    try:
        threading.Thread(target=run_recognition, args=job_args, daemon=True).start()
        return True
    except Exception:
        logging.getLogger(__name__).exception("Failed to start paper recognition task")
        with database.SessionFactory() as session:
            record = session.query(IntakeTable).filter_by(uid=job_args[0]).with_for_update().first()
            if record and record.status == "pending" and record.recognition_job_uid == job_args[1] and record.recognition_status == "running":
                record.recognition_status = "failed"
                record.recognition_error = "照片已暂存，自动识别暂时无法启动，请重试或手动填写核对"
                record.recognition_job_uid = None
                session.commit()
        return False


def start_recognition(payload, uid, version):
    require_role(payload)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True, owner_only=True)
            _check_edit(record, version)
            if record.recognition_status == "running":
                return serialize(record)
            job_args = _prepare_recognition(record)
            session.commit()
            result = serialize(record)
        if not _launch_recognition(job_args):
            return get_intake(payload, uid)
        return result
    except StaleDataError:
        raise IntakeError("回传已被更新，请刷新后重试", 409)
