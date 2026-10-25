import json
import logging
from io import BytesIO

from flask import Blueprint, jsonify, make_response, request, send_file

from Auth import get_payload_roles, get_token_payload, verify, allow
from data import order_model, cargo_model
from data.packing import box_model
from data.DB import CargoTable
from data.database import SessionFactory
from PDF import PDF
from services.cargo_service import (
    get_cargo_with_tracking,
    generate_excel,
    parse_waybill_file,
    apply_waybill_table,
    background_register,
)
from utils.log import log
from utils.audit import record_audit
from services import receivable_service
from services.number_generation_service import (
    GENERATION_ROLES,
    NumberGenerationError,
    generate_original_number,
    generation_options,
)
from services.order_edit_policy import OrderEditConflictError
from services.outbound_service import (
    WaybillImportResult, confirm_outbound, parse_confirm_outbound,
    update_cargo_details, undo_outbound,
)

cargo_bp = Blueprint("cargo", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

CARGO_SHIP_ROLES = ["admin", "store_manager", "salesperson", "clerk"]
BOX_EDIT_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
BOX_ASSIGN_ROLES = {"admin", "store_manager", "salesperson", "clerk"}
BOX_WEIGH_ROLES = {"admin", "store_manager", "salesperson", "worker"}
CARGO_UPDATE_FIELDS = {
    "origin_id",
    "transfer_id",
    "tag",
    "count",
    "weight",
    "real_en_name",
    "price",
    "waybill_id",
    "item_name",
    "item_details",
    "remark",
    "box_number",
    "piece_count",
}
CARGO_FORBIDDEN_UPDATE_FIELDS = {
    "uid",
    "target_order_uid",
    "packing_list_uid",
    "status",
    "date",
    "archive",
    "bonus_item_id",
    "bonus_assigned",
    "bonus_assigned_by",
    "bonus_assigned_date",
}


def _has_box_ids(cargo_ids) -> bool:
    normalized = [str(uid) for uid in (cargo_ids or []) if uid]
    if not normalized:
        return False
    with SessionFactory() as session:
        return (
            session.query(CargoTable.uid)
            .filter(
                CargoTable.uid.in_(normalized),
                CargoTable.packing_list_uid.isnot(None),
            )
            .first()
            is not None
        )


def _can_mutate_box_ids(cargo_ids, allowed_roles) -> bool:
    if not _has_box_ids(cargo_ids):
        return True
    roles = set(get_payload_roles(get_token_payload() or {}))
    return bool(roles.intersection(set(allowed_roles)))


def _can_update_box_transfers(transfer_ids) -> bool:
    normalized = [str(value).strip() for value in (transfer_ids or []) if str(value).strip()]
    if not normalized:
        return True
    with SessionFactory() as session:
        has_boxes = (
            session.query(CargoTable.uid)
            .filter(
                CargoTable.transfer_id.in_(normalized),
                CargoTable.packing_list_uid.isnot(None),
            )
            .first()
            is not None
        )
    if not has_boxes:
        return True
    return bool(
        set(get_payload_roles(get_token_payload() or {})).intersection(BOX_EDIT_ROLES)
    )


def _waybill_upload_response(code, msg, cargo_count=0, success_list=None, cargo_list=None):
    return jsonify(
        {
            "code": code,
            "msg": msg,
            "cargo_count": cargo_count,
            "success_list": success_list or [],
            "cargo_list": cargo_list or {},
        }
    )


def _get_valid_excel_modes():
    """动态获取所有有效的导出模板 mode_key（含硬编码的 kehu）。"""
    from data.database import SessionFactory
    from data.DB import ExcelTemplateTable

    modes = {"kehu"}
    with SessionFactory() as session:
        records = (
            session.query(ExcelTemplateTable.mode_key)
            .filter(ExcelTemplateTable.archive == False)  # noqa: E712
            .all()
        )
        modes.update(r.mode_key for r in records)
    return modes


def _template_requires_valid_quote(mode):
    if mode == "kehu":
        return False
    from data.database import SessionFactory
    from data.DB import ExcelTemplateTable

    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.mode_key == mode,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )
        return bool(record and record.requires_valid_quote)


# 获取订单下的货物列表（含已保存的 webhook 物流状态，不触发外部查询）
@cargo_bp.get("/orders/<string:uid>/cargo")
@verify
@allow()
def get_cargo_list(uid):
    cargo_list, err = get_cargo_with_tracking(uid, order_model, cargo_model)
    if cargo_list is None:
        return jsonify({"code": 404, "msg": err}), 404
    if err:
        return jsonify({"code": 500, "msg": err, "data": cargo_list})
    return jsonify({"code": 200, "data": cargo_list})


@cargo_bp.post("/orders/<string:uid>/cargo/<string:cargo_uid>/generate-original-number")
@verify
@allow(role=GENERATION_ROLES)
@log(desc="Generate original number.", is_json=True)
def generate_original_number_route(uid, cargo_uid):
    try:
        options = generation_options(request.get_json(silent=True) if request.data else {})
        result = generate_original_number(uid, cargo_uid, get_token_payload() or {}, **options)
        return jsonify({"code": 200, "msg": "原单号已生成", "data": result})
    except NumberGenerationError as exc:
        return jsonify({"code": exc.code, "msg": str(exc)}), exc.code
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409


# 获取所有货物的转运号 / 运单号（用于查询）
@cargo_bp.get("/cargo")
@verify
@allow()
def get_cargo():
    result = {}
    for order in order_model.read():
        data_list = []
        for cargo_uid in order["cargo_uid_list"]:
            cargo = cargo_model.read(cargo_uid)
            if cargo is None:
                continue
            data_list.append(
                {
                    "transfer_id": cargo.get("transfer_id", "") or "",
                    "waybill_id": cargo.get("waybill_id", "") or "",
                }
            )
        result[order["uid"]] = data_list
    return jsonify({"code": 200, "data": result})


# 批量归档货物
@cargo_bp.post("/cargo/archive")
@allow()
@verify
@log(desc="Archive cargo.", is_json=True)
def archive_cargo():
    cargo_ids = json.loads(request.data)["cargo_id_list"]
    if not _can_mutate_box_ids(cargo_ids, BOX_EDIT_ROLES):
        return jsonify({"code": 403, "msg": "Permission denied"}), 403
    try:
        cargo_model.mutate_many(cargo_ids, "archive")
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


# 批量删除货物
@cargo_bp.delete("/cargo")
@allow()
@verify
@log(desc="Delete cargo.", is_json=True)
def delete_cargo():
    cargo_ids = json.loads(request.data)["cargo_id_list"]
    if not _can_mutate_box_ids(cargo_ids, BOX_EDIT_ROLES):
        return jsonify({"code": 403, "msg": "Permission denied"}), 403
    try:
        cargo_model.mutate_many(cargo_ids, "delete")
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


@cargo_bp.post("/cargo/unbind")
@allow()
@verify
@log(desc="Unbind cargo from order.", is_json=True)
def unbind_cargo_from_order():
    payload = json.loads(request.data or "{}")
    cargo_id_list = payload.get("cargo_id_list") or []

    if not isinstance(cargo_id_list, list) or len(cargo_id_list) == 0:
        return jsonify({"code": 400, "msg": "cargo_id_list is required"}), 400
    if not _can_mutate_box_ids(cargo_id_list, BOX_ASSIGN_ROLES):
        return jsonify({"code": 403, "msg": "Permission denied"}), 403

    try:
        result = cargo_model.mutate_many(cargo_id_list, "unbind")
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409

    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {
                "success": result["success"],
                "failed": result["failed"],
            },
        }
    )


# 更新货物信息（运单号变更时后台注册 17track）
@cargo_bp.put("/cargo/<string:uid>")
@allow()
@verify
@log(desc="Update cargo.", is_json=True)
def update_cargo(uid):
    update_data = request.get_json() or {}
    if not isinstance(update_data, dict):
        return jsonify({"code": 400, "msg": "invalid request payload"}), 400
    forbidden = sorted(set(update_data).intersection(CARGO_FORBIDDEN_UPDATE_FIELDS))
    if forbidden:
        return jsonify({"code": 400, "msg": f"不允许修改字段: {', '.join(forbidden)}"}), 400
    try:
        supplement = parse_confirm_outbound(update_data.get("confirm_outbound", True))
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
    update_data = {key: value for key, value in update_data.items() if key in CARGO_UPDATE_FIELDS}
    cargo_record = cargo_model.read(uid)
    if cargo_record is None:
        return jsonify({"code": 404, "msg": "cargo not found"}), 404
    roles = set(get_payload_roles(get_token_payload() or {}))
    requests_outbound = supplement and bool(str(update_data.get("waybill_id") or "").strip())
    if (cargo_record.get("packing_list_uid") or requests_outbound) and not roles.intersection(CARGO_SHIP_ROLES):
        return jsonify({"code": 403, "msg": "Permission denied"}), 403
    if cargo_record.get("packing_list_uid"):
        if "real_en_name" in update_data:
            update_data["item_name"] = update_data.pop("real_en_name")
        if "count" in update_data:
            update_data["piece_count"] = update_data.pop("count")
    try:
        result = update_cargo_details(
            uid, update_data, confirm_outbound=supplement, source="cargo_details",
            operator=get_token_payload() or {},
        )
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"code": 403, "msg": str(exc)}), 403
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
    if result["waybill_changed"] and result["new_waybill_id"]:
        background_register(uid, result["new_waybill_id"])
    return jsonify({"code": 200, "msg": "success"})


@cargo_bp.post("/cargo/<string:uid>/undo-outbound")
@verify
@allow(role=["admin", "store_manager"])
@log(desc="Undo cargo outbound.")
def undo_cargo_outbound(uid):
    try:
        result = undo_outbound(uid, operator=get_token_payload() or {})
        return jsonify({"code": 200, "msg": "已撤销出库，原出库和成本历史保留", "data": result})
    except PermissionError as exc:
        return jsonify({"code": 403, "msg": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400


@cargo_bp.put("/cargo/<string:uid>/outbound")
@verify
@allow(role=CARGO_SHIP_ROLES)
@log(desc="Confirm cargo outbound.", is_json=True)
def register_outbound(uid):
    data = request.get_json(silent=True) if request.data else {}
    if not isinstance(data, dict) or set(data) - {"occurred_at"}:
        return jsonify({"code": 400, "msg": "only occurred_at may be supplied"}), 400
    try:
        result = confirm_outbound([uid], occurred_at=data.get("occurred_at"),
                                  source="explicit", operator=get_token_payload() or {})
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"code": 403, "msg": str(exc)}), 403
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
    return jsonify({"code": 200, "data": result})


# 出货（标记已发货）
@cargo_bp.post("/cargo/<string:uid>/output")
@verify
@allow(role=CARGO_SHIP_ROLES)
@log(desc="Output cargo.")
def output(uid):
    return jsonify({"code": 410, "msg": "旧出库接口已停用，请录入转单号补登记，或调用 PUT /api/cargo/<uid>/outbound"}), 410


# 录入货物重量和件数
@cargo_bp.post("/cargo/<string:uid>/input")
@verify
@allow()
@log(desc="Record cargo property.", is_json=True)
def record_input(uid):
    record = json.loads(request.data)
    if not (record.get("weight") and record.get("count")):
        return jsonify({"code": 404, "msg": "lack param"})
    cargo_record = cargo_model.read(uid)
    if cargo_record is None:
        return jsonify({"code": 404, "msg": "cargo not found"}), 404
    if cargo_record.get("packing_list_uid"):
        roles = set(get_payload_roles(get_token_payload() or {}))
        if not roles.intersection(BOX_WEIGH_ROLES):
            return jsonify({"code": 403, "msg": "Permission denied"}), 403
        try:
            box_model.update(uid, {"weight": record.get("weight")})
        except OrderEditConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        except ValueError as exc:
            return jsonify({"code": 400, "msg": str(exc)}), 400
        return jsonify({"code": 200, "msg": "success"})
    try:
        cargo_model.update(
            uid, {"weight": record.get("weight", 0), "count": record.get("count", 0)}
        )
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


# 下载货物标签 PDF
@cargo_bp.get("/cargo/pdf/<string:cargo_list>")
@allow()
def download_pdf(cargo_list):
    pdf = PDF()
    for i, cargo_id in enumerate(cargo_list.split("_")):
        cargo = cargo_model.read(cargo_id)
        if cargo is None:
            continue
        order = order_model.read(cargo["target_order_id"])
        pdf.render(
            order["receiver"],
            cargo["origin_id"],
            order["customer_name"],
            order["receiver_phone"],
            cargo["tag"],
            i,
        )
    return send_file(pdf.get_bytes_io(), mimetype="application/pdf")


# 下载已生成的 Excel 文件
@cargo_bp.get("/cargo/excel/<string:document_id>")
@verify
@allow()
def download_excel(document_id):
    return send_file(f"excels/{document_id}.xlsx", mimetype="application/vnd.ms-excel")


# 生成 Excel 导出文件
@cargo_bp.post("/cargo/excel/<string:mode>")
@verify
@allow()
@log(desc="Export proxy's template excel.", is_json=True)
def generate_excel_route(mode="jifei"):
    if mode not in _get_valid_excel_modes():
        return jsonify({"code": 404, "reason": "mode not found"})

    request_data = json.loads(request.data)
    uid_list = request_data["uid_list"]
    if not uid_list:
        return jsonify({"code": 200})

    requires_valid_quote = _template_requires_valid_quote(mode)
    if requires_valid_quote:
        blocked_orders = []
        for order_uid in uid_list:
            state = receivable_service.get_order_quote_state(order_uid)
            if not state.get("is_effective"):
                order = order_model.read(order_uid) or {}
                blocked_orders.append({
                    "uid": order_uid,
                    "order_id": order.get("order_id") or order_uid,
                    "reason": state.get("validity_status") or "unquoted",
                })
        if blocked_orders:
            record_audit(
                event_type="supplier_export",
                target_type="orders",
                target_id=",".join(str(item["uid"]) for item in blocked_orders),
                action="export_blocked_invalid_quote",
                after_data={"mode": mode, "blocked_orders": blocked_orders},
                remark="供应商导出因报价无效被拦截",
            )
            return jsonify({
                "code": 409,
                "msg": "部分订单尚无有效报价或重量已变化",
                "data": {"blocked_orders": blocked_orders},
            }), 409

    request_cargo_list = request_data.get("cargo_list", None)
    result, err, is_plain_text = generate_excel(
        mode, uid_list, request_cargo_list, order_model, cargo_model
    )

    if err:
        return jsonify({"code": 500, "msg": err})
    if requires_valid_quote:
        record_audit(
            event_type="supplier_export",
            target_type="orders",
            target_id=",".join(str(uid) for uid in uid_list),
            action="export_supplier_orders",
            after_data={"mode": mode, "order_uids": uid_list},
            remark="供应商转单文件已导出",
        )
    if is_plain_text:
        return result  # kehu 模式返回纯文本
    return jsonify({"code": 200, "data": {"document_id": result}})


# 上传转运单，批量更新运单号并发货
@cargo_bp.post("/order/upload/<mode>")
@verify
@allow()
@log(desc="Upload waybill list.")
def upload_order(mode):
    if mode != "transfer_table":
        return make_response("", 404)

    import_result = WaybillImportResult()
    register_list = []
    transfer_map = {}
    try:
        if "file" not in request.files:
            return _waybill_upload_response(400, "未找到上传文件"), 400

        fp = request.files["file"]
        filename = (request.form.get("filename") or "").strip()
        if not filename:
            return _waybill_upload_response(400, "文件名不能为空"), 400

        transfer_map = parse_waybill_file(fp, filename)
        if not _can_update_box_transfers(transfer_map.keys()):
            return _waybill_upload_response(403, "Permission denied"), 403
        supplement = parse_confirm_outbound(request.form.get("confirm_outbound", "true"))
        if supplement and not set(get_payload_roles(get_token_payload() or {})).intersection(CARGO_SHIP_ROLES):
            return _waybill_upload_response(403, "Permission denied"), 403
        import_result, track_err = apply_waybill_table(
            cargo_model, transfer_map, confirm_outbound=supplement,
            operator=get_token_payload() or {}, return_details=True,
        )
        register_list = import_result.registered
    except PermissionError as e:
        return _waybill_upload_response(403, str(e), cargo_list=transfer_map), 403
    except OrderEditConflictError as e:
        return (
            _waybill_upload_response(409, str(e), cargo_list=transfer_map),
            409,
        )
    except ValueError as e:
        return (
            _waybill_upload_response(400, str(e), cargo_list=transfer_map),
            400,
        )
    except Exception as e:
        logger.exception("upload_order failed")
        return (
            _waybill_upload_response(
                500,
                f"上传转单号失败: {e}",
                cargo_count=len(register_list),
                success_list=register_list,
                cargo_list=transfer_map,
            ),
            500,
        )

    response = {
        "code": 200,
        "msg": "success",
        "cargo_count": len(import_result.successful),
        "cargo_list": transfer_map,
        "success_list": [(item["uid"], item["waybill_id"]) for item in import_result.successful],
        "success_items": import_result.successful,
        "failed_list": import_result.failed,
        "tracking_error": None,
    }
    if import_result.failed:
        response["code"] = 207 if import_result.successful else 400
        response["msg"] = (
            "部分订单上传失败，其他订单已保存" if import_result.successful else "所有记录均未上传成功"
        )

    if track_err:
        e_body = track_err.args[0] if track_err.args else {}
        if isinstance(e_body, dict) and e_body.get("code") == 502:
            response.update({"code": 502, "msg": "17track rejected", "rejected": e_body.get("data", [])})
        else:
            response.update({"code": 500, "msg": "Register Error"})
        response["tracking_error"] = {"code": response["code"], "reason": response["msg"]}
        return jsonify(response)

    return jsonify(response), 400 if response["code"] == 400 else 200
