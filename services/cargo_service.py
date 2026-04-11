import datetime
import logging
from threading import Thread

import pandas as pd
from openpyxl import load_workbook

from data import formatter
from utils.l7track import getTrackInfo, registerTrack

logger = logging.getLogger(__name__)

# Excel 导出相关常量
_SINGLE_ORDER_MODES = {"jinfeiqi", "jinlong", "xinghang", "WE"}

_MODE_LABEL = {
    "jifei": "极飞",
    "tongcang": "统仓",
    "huanshitong": "环世",
    "jinfeiqi": "金飞",
    "jinlong": "金龙",
    "xinghang": "星航",
    "tongcangups": "统仓(UPS)",
    "yaxuan": "亚轩",
    "WE": "亚轩(WE)",
}

_CELL_MAP = {
    "jinfeiqi": [
        ("B3", "order_id"),
        ("H3", "receiver"),
        ("H5", "country"),
        ("O5", "zip_code"),
        ("H6", "address"),
        ("H7", "city"),
        ("F7", "province"),
        ("H8", "receiver_phone"),
    ],
    "jinlong": [
        ("C9", "order_id"),
        ("C7", "receiver"),
        ("C4", "country"),
        ("C6", "zip_code"),
        ("C3", "address"),
        ("C5", "city"),
        ("C8", "receiver_phone"),
    ],
    "xinghang": [
        ("B1", "order_id"),
        ("B6", "country"),
        ("B10", "receiver"),
        ("B11", "receiver_phone"),
        ("B12", "zip_code"),
        ("B13", "province"),
        ("D13", "mail"),
        ("B14", "city"),
        ("B15", "address"),
    ],
    "WE": [
        ("C2", "order_id"),
        ("F5", "receiver"),
        ("F6", "address"),
        ("F7", "receiver_phone"),
        ("F8", "zip_code"),
    ],
}


def get_cargo_with_tracking(uid: str, order_model, cargo_model):
    """
    获取订单下所有货物并查询最新物流状态。
    返回 (cargo_list, error_msg)。error_msg 不为 None 时表示查询物流时出错，
    但 cargo_list 仍返回本地数据。
    """
    order = order_model.read(uid)
    if order is None:
        return None, "Order Not Found"

    data: dict = {}
    waybill_ids: list = []
    for cargo_uid in order["cargo_uid_list"]:
        cargo = cargo_model.read(cargo_uid)
        if cargo is None:
            continue
        data[cargo_uid] = cargo
        if cargo.get("waybill_id"):
            waybill_ids.append(cargo["waybill_id"])

    try:
        for track_infos in getTrackInfo(waybill_ids):
            track_info = track_infos["track_info"]
            if track_info["latest_status"]["status"] == "NotFound":
                continue
            tag = str(track_infos["tag"])
            cargo_model.update(
                tag, {"status": track_info["latest_status"]["sub_status"]}
            )
            data[tag].update(
                {
                    "status": track_info["latest_status"]["sub_status"],
                    "desc": track_info["latest_status"]["sub_status_descr"],
                    "events": track_info["tracking"]["providers"][0]["events"],
                    "track_info": track_info,
                }
            )
    except Exception as e:
        logger.error("get_cargo_with_tracking: %s", e)
        return list(data.values()), "Get Track Error"

    return list(data.values()), None


def generate_excel(
    mode: str, uid_list: list, request_cargo_list: list, order_model, cargo_model
):
    """
    生成 Excel 导出文件。
    - 模板类（单订单）模式：填写模板后保存，返回 (document_id, None, False)
    - kehu 模式：返回纯文本，返回 (text, None, True)
    - 通用模式：生成 xlsx，返回 (document_id, None, False)
    - 出错：返回 (None, error_msg, False)

    第三个返回值 is_plain_text 供 Controller 判断响应格式。
    """
    if mode in _SINGLE_ORDER_MODES:
        if len(uid_list) > 1:
            return None, "Exceed Order Count Limitation", False
        order_msg = order_model.read(uid_list[0])
        wb = load_workbook(filename=f"static/{mode}_template.xlsx")
        ws = wb.active
        for cell_ref, field in _CELL_MAP[mode]:
            ws[cell_ref] = order_msg[field]
        document_id = (
            _MODE_LABEL[mode]
            + order_msg.get("country", "")
            + order_msg.get("zip_code", "1111")
            + "("
            + order_msg.get("order_id", "000")[-3:]
            + ")"
        )
        wb.save(filename=f"excels/{document_id}.xlsx")
        wb.close()
        return document_id, None, False

    # 收集所有货物（合并订单信息）
    cargo_map: dict = {}
    for order_uid in uid_list:
        order = order_model.read(order_uid)
        for cargo_uid in order["cargo_uid_list"]:
            cargo_res = cargo_model.read(cargo_uid)
            if cargo_res is None:
                continue
            cargo_res.update(order)
            cargo_map[cargo_uid] = cargo_res

    if mode == "kehu":
        result: dict = {}
        for c in cargo_map.values():
            key = f"{c['receiver']}({c['customer_name']})"
            waybill_id = c.get("waybill_id")
            if waybill_id is None:
                continue
            result.setdefault(key, []).append(waybill_id)
        lines = []
        for k, v in result.items():
            lines.append(k)
            lines.extend(v)
        return "\n".join(lines), None, True

    if request_cargo_list:
        cargo_map = {
            uid: cargo_map[uid] for uid in request_cargo_list if uid in cargo_map
        }

    cargo_items = list(cargo_map.values())
    cargos = pd.DataFrame(cargo_items)
    cargos["weight"] = cargos["weight"].apply(
        lambda x: int(0.99 * float(x) * 10) / 10 if x else 0
    )

    template = formatter[mode]
    result_df = pd.DataFrame(columns=template["columns"])
    for label, name in template["reference_table"].items():
        result_df[label] = cargos.get(name, pd.Series())

    document_id = (
        _MODE_LABEL[mode]
        + cargo_items[0].get("country", "")
        + cargo_items[0].get("zip_code", "111")
        + "("
        + cargo_items[0].get("order_id", "000")[-3:]
        + ")"
    )
    result_df.to_excel(f"excels/{document_id}.xlsx", index=False)
    return document_id, None, False


def parse_waybill_file(fp, filename: str) -> dict:
    """
    解析上传的转运单文件（txt 或 Excel），
    返回 transfer_id -> waybill_id 映射字典。
    """
    table: dict = {}
    if filename.split(".")[-1].strip() == "txt":
        fp.seek(0)
        while line := fp.stream.readline():
            transfer_id, waybill_id = line.split(b",")
            table[transfer_id.decode().strip()] = waybill_id.decode().strip()
    else:
        buffer_df = pd.read_excel(
            fp,
            usecols=["a", "b"],
            converters={"a": lambda v: str(v).strip(), "b": lambda v: str(v).strip()},
        ).fillna(False)
        table = dict(buffer_df.to_numpy())
    return table


def apply_waybill_table(cargo_model, transfer_map: dict):
    """
    将转运单映射批量写入货物记录并在 17track 注册。
    返回 (register_list, error_exception)。
    即使 17track 注册失败，register_list 仍包含所有已更新的记录，
    error 不为 None 时调用方可检查 error.args[0] 获取 17track 错误详情。
    """
    register_list = []
    for cargo_uid, cargo in cargo_model.data_point.items():
        transfer_id = cargo.get("transfer_id")
        if transfer_id and transfer_map.get(str(transfer_id)):
            waybill_id = transfer_map[str(transfer_id)]
            update_payload = {"waybill_id": waybill_id}

            # 装箱单箱子兼容旧系统：status=0 表示待出库。
            if cargo.get("packing_list_uid"):
                if cargo.get("target_order_uid") and int(cargo.get("status") or 0) != 1:
                    update_payload["status"] = 0
            else:
                # 兼容旧货物流程：转单号上传即出库。
                update_payload.update(
                    {
                        "status": 1,
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                )

            cargo_model.update(cargo_uid, update_payload)
            register_list.append((cargo_uid, waybill_id))
    try:
        registerTrack(register_list)
        return register_list, None
    except Exception as e:
        logger.error("apply_waybill_table: 17track registration failed: %s", e)
        return register_list, e


def background_register(uid: str, waybill_id: str) -> None:
    """后台线程异步注册单条追踪号，避免阻塞请求。"""

    def _run():
        try:
            registerTrack([(uid, waybill_id)])
        except Exception as e:
            logger.error("background_register failed: %s", e)

    Thread(target=_run, daemon=True).start()
