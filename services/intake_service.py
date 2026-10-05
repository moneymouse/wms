"""Transactional review workflow and isolated recognition candidates."""
import json
import logging
import math
import re
import threading
from datetime import datetime, timedelta
from io import BytesIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from Auth import get_payload_roles
from data import database
from data.DB import CargoTable
from data.intake import IntakePhotoTable, IntakeTable
from data.packing.PackingList import PackingListTable, BoxModel, BoxWorkerTable
from data.user.Role import RoleTable
from data.user.User import UserTable

REVIEW_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
WORKER_ROLES = {"worker", "employee"}
SUBMIT_ROLES = REVIEW_ROLES | WORKER_ROLES
MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_TOTAL_PHOTO_BYTES = 24 * 1024 * 1024


class IntakeError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now().isoformat(timespec="seconds")


def require_role(payload, review=False):
    if not set(get_payload_roles(payload)).intersection(REVIEW_ROLES if review else SUBMIT_ROLES):
        raise IntakeError("没有纸单回传操作权限", 403)
    if not payload.get("user_id"):
        raise IntakeError("登录身份无效", 401)


def load_record(session, uid, payload, lock=False):
    require_role(payload)
    query = session.query(IntakeTable).filter_by(uid=uid)
    if lock:
        query = query.with_for_update()
    record = query.first()
    if record is None:
        raise IntakeError("回传记录不存在", 404)
    if not set(get_payload_roles(payload)).intersection(REVIEW_ROLES) and record.submitted_by != payload["user_id"]:
        raise IntakeError("只能查看自己的回传记录", 403)
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
    require_role(payload, review=True)
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
    candidate["worker_ids"] = []
    operator_name = candidate.get("operator_name")
    names = list(dict.fromkeys(name.strip() for name in re.split(r"[、，,;；]", operator_name or "") if name.strip())) if isinstance(operator_name, str) else []
    if not names:
        candidate["warnings"].append("未识别到可绑定的纸单操作人员，请手动选择真实工人")
        return candidate
    if len(names) > BoxModel.MAX_WORKERS:
        candidate["warnings"].append(f"纸单操作人员超过{BoxModel.MAX_WORKERS}位，请人工核对并选择工人")
        return candidate
    workers_by_name = {}
    for worker in _approved_workers(session).all():
        workers_by_name.setdefault(worker.name.strip(), []).append(worker.id)
    matched = []
    for name in names:
        ids = workers_by_name.get(name, [])
        if not ids:
            candidate["warnings"].append(f"纸单操作人员“{name}”未匹配到已批准工人，请手动选择")
        elif len(ids) > 1:
            candidate["warnings"].append(f"纸单操作人员“{name}”存在同名工人，请手动选择")
        else:
            matched.append(ids[0])
    # A partially matched multi-person signature must not silently omit someone.
    if len(matched) == len(names):
        candidate["worker_ids"] = matched
    return candidate


def my_packing_lists(payload, page=1, page_size=20, mark=None):
    """Return ownership-scoped metadata for manual lists and paper submissions."""
    require_role(payload)
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    mark_filter = _text(mark, "查询唛头", 64).casefold()
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
        pending = session.query(IntakeTable.uid, IntakeTable.created_at, IntakeTable.mark_hint, IntakeTable.draft_json, IntakeTable.recognition_result_json).filter(
            IntakeTable.submitted_by == payload["user_id"],
            IntakeTable.status == "pending",
            IntakeTable.packing_list_uid.is_(None),
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
                "status": "pending_review",
                "created_at": row.created_at,
                "box_count": len(effective.get("boxes") or []),
                "packing_list_uid": None,
            })
        if mark_filter:
            items = [item for item in items if mark_filter in item["mark"].casefold()]
        items.sort(key=lambda item: ((item["created_at"] or "").replace("T", " "), item["uid"]), reverse=True)
        total = len(items)
        return {"items": items[(page - 1) * page_size:page * page_size], "total": total, "page": page, "page_size": page_size}


def create_intake(payload, files, form):
    require_role(payload)
    if not 1 <= len(files) <= MAX_PHOTOS:
        raise IntakeError(f"请选择1至{MAX_PHOTOS}张照片")
    photos = []
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
        photos.append(IntakePhotoTable(uid=uuid4().hex, position=position, filename=_text(file.filename or "照片", "文件名", 256), mime_type=mime, data=data))
    mark_hint = _text(form.get("mark_hint"), "唛头提示", 64)
    operation_at = _text(form.get("operation_at"), "现场时间", 32) or None
    if operation_at:
        try:
            datetime.fromisoformat(operation_at)
        except ValueError:
            raise IntakeError("现场时间格式无效")
    with database.SessionFactory() as session:
        record = IntakeTable(uid=uuid4().hex, submitted_by=payload["user_id"], submitted_by_name=str(payload.get("name") or payload["user_id"]), created_at=now(), operation_at=operation_at, mark_hint=mark_hint, note=_text(form.get("note"), "备注", 512), draft_json=json.dumps({"mark": mark_hint, "boxes": []}, ensure_ascii=False), photos=photos)
        session.add(record)
        job_args = _prepare_recognition(record)
        session.commit()
        result = serialize(record)
    if not _launch_recognition(job_args):
        return get_intake(payload, result["uid"])
    return result


def list_intakes(payload, status=None, page=1, page_size=20, packing_list_uid=None, mark=None):
    require_role(payload)
    if status and status not in {"pending", "confirmed"}:
        raise IntakeError("回传状态无效")
    with database.SessionFactory() as session:
        query = session.query(IntakeTable)
        if not set(get_payload_roles(payload)).intersection(REVIEW_ROLES):
            query = query.filter_by(submitted_by=payload["user_id"])
        if status:
            query = query.filter_by(status=status)
        if packing_list_uid:
            query = query.filter_by(packing_list_uid=packing_list_uid)
        if mark:
            mark = _text(mark, "查询唛头", 64)
            pattern = "%" + mark.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            # JSON_EXTRACT is supported by both the SQLite preview and MySQL.
            query = query.filter(or_(
                IntakeTable.mark_hint.ilike(pattern, escape="\\"),
                func.json_extract(IntakeTable.draft_json, "$.mark").ilike(pattern, escape="\\"),
                func.json_extract(IntakeTable.recognition_result_json, "$.mark").ilike(pattern, escape="\\"),
            ))
        total = query.count()
        items = query.order_by(IntakeTable.created_at.desc(), IntakeTable.uid.desc()).offset((page - 1) * page_size).limit(page_size).all()
        if any([_expire_recognition(item) for item in items]):
            session.commit()
        return {"items": [serialize(item) for item in items], "total": total, "page": page, "page_size": page_size}


def _expire_recognition(record):
    # In-process jobs cannot survive a restart. Lists also make retry possible.
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
        if with_filename:
            mark, _ = _paper_identity(record, json.loads(record.draft_json), json.loads(record.recognition_result_json or "{}"))
            return photo.data, photo.mime_type, _photo_filename(photo, mark or f"纸单-{record.uid[:8]}")
        return photo.data, photo.mime_type


def _check_edit(record, version):
    if record.status != "pending":
        raise IntakeError("已确认回传不能修改草稿", 409)
    if isinstance(version, bool) or not isinstance(version, int) or version != record.version:
        raise IntakeError("回传已被更新，请刷新后重试（本地未保存内容请先保留）", 409)


def normalize_draft(draft, complete=False):
    if not isinstance(draft, dict) or not isinstance(draft.get("boxes"), list):
        raise IntakeError("草稿须包含箱子列表")
    boxes = draft["boxes"]
    if len(boxes) > 500:
        raise IntakeError("单次回传最多500箱")
    mark = _text(draft.get("mark"), "唛头", 64)
    normalized = []
    seen = set()
    if complete and (not mark or not boxes):
        raise IntakeError("确认前请填写唛头并至少录入一箱")
    for index, row in enumerate(boxes, 1):
        if not isinstance(row, dict):
            raise IntakeError(f"第{index}行格式无效")
        item = {key: row.get(key) for key in ("box_number", "item_name", "count", "weight")}
        item["item_name"] = _text(item["item_name"], f"第{index}行品名", 256)
        # Incomplete scalar values remain editable, but nested data is rejected.
        for key in ("box_number", "count", "weight"):
            if isinstance(item[key], (list, dict, bool)):
                raise IntakeError(f"第{index}行{key}格式无效")
            if isinstance(item[key], str) and len(item[key]) > 32:
                raise IntakeError(f"第{index}行数字过长")
            if isinstance(item[key], float) and not math.isfinite(item[key]):
                raise IntakeError(f"第{index}行数字须为有限值")
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
    return {"mark": mark, "operator_name": _text(draft.get("operator_name"), "操作人员", 128), "worker_ids": _normalize_worker_ids(draft.get("worker_ids", [])), "boxes": normalized}


def save_draft(payload, uid, version, draft):
    require_role(payload, review=True)
    normalized = normalize_draft(draft)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True)
            _check_edit(record, version)
            _validate_worker_ids(session, normalized["worker_ids"])
            record.draft_json = json.dumps(normalized, ensure_ascii=False, allow_nan=False)
            # Saving identical contents must still advance the version.
            record.version += 1
            session.commit()
            return serialize(record)
    except StaleDataError:
        raise IntakeError("回传已被更新，请刷新后重试", 409)


def _new_box(packing_uid, mark, row, timestamp):
    uid = uuid4().hex
    return CargoTable(uid=uid, origin_id=f"BOX-{uid}", tag=BoxModel()._build_box_tag(mark, row["box_number"]), transfer_id="", waybill_id="", target_order_uid=None, count=row["count"], piece_count=row["count"], item_name=row["item_name"], real_en_name=row["item_name"], item_details=json.dumps([{"item_name": row["item_name"], "piece_count": row["count"], "customs_code": ""}], ensure_ascii=False), box_number=row["box_number"], weight=row["weight"], price=0.0, status=0, box_status="pending", archive=False, packing_list_uid=packing_uid, create_date=timestamp)


def confirm_intake(payload, uid, version):
    require_role(payload, review=True)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True)
            if record.status == "confirmed":
                return serialize(record)
            _check_edit(record, version)
            draft = normalize_draft(json.loads(record.draft_json), complete=True)
            _validate_worker_ids(session, draft["worker_ids"], complete=True)
            # Match the existing canonical mark, while refusing its auto-rename policy.
            mark = draft["mark"].upper()
            if session.query(PackingListTable.uid).filter(PackingListTable.list_number == mark).first():
                raise IntakeError(f"唛头{mark}已存在，请核对批次；系统不会自动改名或合并", 409)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            packing_uid = uuid4().hex
            session.add(PackingListTable(uid=packing_uid, list_number=mark, creator_id=record.submitted_by, photos="[]", status="completed", create_date=timestamp, archive=False))
            session.flush()
            for row in draft["boxes"]:
                box = _new_box(packing_uid, mark, row, timestamp)
                session.add(box)
                session.flush()
                for worker_id in draft["worker_ids"]:
                    session.add(BoxWorkerTable(box_uid=box.uid, worker_id=worker_id, create_date=timestamp))
                session.flush()
            record.status = "confirmed"
            record.packing_list_uid = packing_uid
            record.confirmed_by = payload["user_id"]
            record.confirmed_at = now()
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
        from services.intake_recognition import recognize_paper_photos
        candidate = recognize_paper_photos(images, mark_hint=mark_hint)
        with database.SessionFactory() as session:
            candidate = _bind_recognition_workers(session, candidate)
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
                if record is None or record.recognition_job_uid != job_uid or record.recognition_status != "running":
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
    images = [{"data": photo.data, "mime_type": photo.mime_type, "filename": photo.filename} for photo in record.photos]
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
            if record and record.recognition_job_uid == job_args[1] and record.recognition_status == "running":
                record.recognition_status = "failed"
                record.recognition_error = "照片已回传，自动识别暂时无法启动，请核对人员重试"
                record.recognition_job_uid = None
                session.commit()
        return False


def start_recognition(payload, uid, version):
    require_role(payload, review=True)
    try:
        with database.SessionFactory() as session:
            record = load_record(session, uid, payload, lock=True)
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
