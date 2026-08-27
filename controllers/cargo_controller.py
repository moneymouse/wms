import json
import logging
from io import BytesIO

from flask import Blueprint, jsonify, make_response, request, send_file

from Auth import verify, allow
from data import order_model, cargo_model
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

cargo_bp = Blueprint("cargo", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

CARGO_SHIP_ROLES = ["admin", "store_manager", "salesperson", "clerk"]


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


# 获取订单下的货物列表（含实时物流状态）
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
    for cargo_id in json.loads(request.data)["cargo_id_list"]:
        cargo_model.archive(cargo_id)
    return jsonify({"code": 200, "msg": "success"})


# 批量删除货物
@cargo_bp.delete("/cargo")
@allow()
@verify
@log(desc="Delete cargo.", is_json=True)
def delete_cargo():
    for cargo_id in json.loads(request.data)["cargo_id_list"]:
        cargo_model.delete(cargo_id)
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

    success_ids = []
    failed_ids = []

    for cargo_id in cargo_id_list:
        if not cargo_id:
            continue
        if cargo_model.unbind_from_order(cargo_id):
            success_ids.append(cargo_id)
        else:
            failed_ids.append(cargo_id)

    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "data": {
                "success": success_ids,
                "failed": failed_ids,
            },
        }
    )


# 更新货物信息（运单号变更时后台注册 17track）
@cargo_bp.put("/cargo/<string:uid>")
@allow()
@verify
@log(desc="Update cargo.", is_json=True)
def update_cargo(uid):
    update_data = json.loads(request.data)
    cargo_record = cargo_model.read(uid)
    if cargo_record is None:
        return jsonify({"code": 404, "msg": "cargo not found"}), 404

    old_waybill = cargo_record.get("waybill_id")

    new_waybill = update_data.get("waybill_id")

    try:
        cargo_model.update(uid, update_data)
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e)}), 400
    if new_waybill and new_waybill != old_waybill:
        background_register(uid, new_waybill)
    return jsonify({"code": 200, "msg": "success"})


# 出货（标记已发货）
@cargo_bp.post("/cargo/<string:uid>/output")
@verify
@allow(role=CARGO_SHIP_ROLES)
@log(desc="Output cargo.")
def output(uid):
    return jsonify({"code": 410, "msg": "请通过记录转单号完成出货"}), 410


# 录入货物重量和件数
@cargo_bp.post("/cargo/<string:uid>/input")
@verify
@allow()
@log(desc="Record cargo property.", is_json=True)
def record_input(uid):
    record = json.loads(request.data)
    if not (record.get("weight") and record.get("count")):
        return jsonify({"code": 404, "msg": "lack param"})
    cargo_model.update(
        uid, {"weight": record.get("weight", 0), "count": record.get("count", 0)}
    )
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
        return make_response(404)

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
        register_list, track_err = apply_waybill_table(cargo_model, transfer_map)
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

    if track_err:
        e_body = track_err.args[0] if track_err.args else {}
        if isinstance(e_body, dict) and e_body.get("code") == 502:
            return jsonify(
                {
                    "code": 502,
                    "msg": "17track rejected",
                    "rejected": e_body["data"],
                    "cargo_count": len(register_list),
                    "success_list": register_list,
                    "cargo_list": transfer_map,
                }
            )
        return jsonify(
            {
                "code": 500,
                "msg": "Register Error",
                "cargo_count": len(register_list),
                "success_list": register_list,
                "cargo_list": transfer_map,
            }
        )

    return jsonify(
        {
            "code": 200,
            "msg": "success",
            "cargo_count": len(register_list),
            "cargo_list": transfer_map,
            "success_list": register_list,
        }
    )
