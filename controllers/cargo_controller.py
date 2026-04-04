import json
import time
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

cargo_bp = Blueprint("cargo", __name__, url_prefix="/api")

_VALID_EXCEL_MODES = {
    "jifei",
    "tongcang",
    "huanshitong",
    "jinfeiqi",
    "jinlong",
    "xinghang",
    "tongcangups",
    "yaxuan",
    "kehu",
    "jinlong_kuaidi",
    "WE",
}


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


# 批量删除货物
@cargo_bp.delete("/cargo")
@allow()
@verify
@log(desc="Delete cargo.", is_json=True)
def delete_cargo():
    for cargo_id in json.loads(request.data)["cargo_id_list"]:
        cargo_model.delete(cargo_id)
    return jsonify({"code": 200, "msg": "success"})


# 更新货物信息（运单号变更时后台注册 17track）
@cargo_bp.put("/cargo/<string:uid>")
@allow()
@verify
@log(desc="Update cargo.", is_json=True)
def update_cargo(uid):
    update_data = json.loads(request.data)
    old_waybill = cargo_model.read(uid).get("waybill_id")
    cargo_model.update(uid, update_data)
    new_waybill = update_data.get("waybill_id")
    if new_waybill and new_waybill != old_waybill:
        background_register(uid, new_waybill)
    return jsonify({"code": 200, "msg": "success"})


# 出货（标记已发货）
@cargo_bp.post("/cargo/<string:uid>/output")
@allow()
@log(desc="Output cargo.")
def output(uid):
    cargo_model.update(uid, {"status": 1, "date": time.strftime("%Y-%m-%d %H:%M")})
    cargo = cargo_model.read(uid, except_fields=["price", "status", "archive"])
    order = order_model.read(
        cargo["origin_id"].split("-")[0], _fields=["customer_name"]
    )
    cargo.update(order)
    return jsonify({"code": 200, "data": cargo})


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
    if mode not in _VALID_EXCEL_MODES:
        return jsonify({"code": 404, "reason": "mode not found"})

    request_data = json.loads(request.data)
    uid_list = request_data["uid_list"]
    if not uid_list:
        return jsonify({"code": 200})

    request_cargo_list = request_data.get("cargo_list", None)
    result, err, is_plain_text = generate_excel(
        mode, uid_list, request_cargo_list, order_model, cargo_model
    )

    if err:
        return jsonify({"code": 500, "msg": err})
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

    fp = request.files["file"]
    filename = request.form["filename"]
    transfer_map = parse_waybill_file(fp, filename)
    register_list, track_err = apply_waybill_table(cargo_model, transfer_map)

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
