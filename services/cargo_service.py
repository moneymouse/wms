import json
import logging
import os
import uuid
from threading import Thread

import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.utils import column_index_from_string

from data.database import SessionFactory
from data.DB import (
    CargoTable,
    ExcelTemplateTable,
    ensure_order_receipt_unlocked,
)
from utils.l7track import getTrackInfo, registerTrack

logger = logging.getLogger(__name__)

# Excel 导出相关常量
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "excel_templates")


def add_cargos_to_order(order_uid: str, cargo_delta: int) -> dict:
    """在同一事务内锁定订单、检查收据锁并批量新增普通包裹。"""
    with SessionFactory() as session:
        order = ensure_order_receipt_unlocked(session, order_uid)
        cargo_count = int(order.cargo_count or 0)
        next_count = cargo_count + cargo_delta
        created = []
        for index in range(cargo_count + 1, next_count + 1):
            cargo = CargoTable(
                uid=uuid.uuid4().hex,
                origin_id=f"{order.order_id}-{index}",
                status=0,
                tag=f"{order.tag_all}_{index}",
                target_order_uid=order_uid,
            )
            session.add(cargo)
            created.append(cargo)
        order.cargo_count = next_count
        session.flush()
        data = [
            {
                column.name: getattr(row, column.name)
                for column in CargoTable.__table__.columns
            }
            for row in created
        ]
        cargo_ids = [
            row[0]
            for row in session.query(CargoTable.uid)
            .filter(
                CargoTable.target_order_uid == order_uid,
                CargoTable.archive == False,  # noqa: E712
            )
            .all()
        ]
        session.commit()
        return {"data": data, "cargo_id_list": cargo_ids}


def _get_template(mode_key: str):
    """从数据库获取 Excel 模板配置。"""
    with SessionFactory() as session:
        return (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.mode_key == mode_key,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )


def _build_document_id(label: str, data: dict) -> str:
    """通用 document_id 构建逻辑。"""
    country = data.get("country", "")
    zip_code = data.get("zip_code", "111")
    order_id = data.get("order_id", "000")[-3:]
    return f"{label}{country}{zip_code}({order_id})"


def _load_workbook_from_path(path: str):
    """加载 Excel 模板文件，兼容 .xlsx 和 .xls 格式。"""
    if path.lower().endswith(".xls"):
        import xlrd
        xls_book = xlrd.open_workbook(path)
        wb = Workbook()
        # 移除默认创建的空白 sheet
        wb.remove(wb.active)
        for sheet_idx in range(xls_book.nsheets):
            xls_sheet = xls_book.sheet_by_index(sheet_idx)
            ws = wb.create_sheet(title=xls_sheet.name)
            for row in range(xls_sheet.nrows):
                for col in range(xls_sheet.ncols):
                    ws.cell(row=row + 1, column=col + 1, value=xls_sheet.cell_value(row, col))
        return wb
    return load_workbook(filename=path)


def _apply_weight_adjustment(cargo_items: list) -> list:
    """对货物列表中的重量应用统一调整规则。"""
    for item in cargo_items:
        w = item.get("weight")
        if w is not None:
            try:
                item["weight"] = int(0.99 * float(w) * 10) / 10
            except (ValueError, TypeError):
                item["weight"] = 0
    return cargo_items


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
            if tag not in data:
                # Ignore records that are not part of current order payload.
                continue

            latest_sub_status = track_info["latest_status"]["sub_status"]

            # Packing-list boxes use status as business state (0 pending outbound / 1 outbound).
            # Do not overwrite it with 17track sub status text.
            # if not data[tag].get("packing_list_uid"):
            # cargo_model.update(tag, {"status": latest_sub_status})
            data[tag].update(
                {
                    **(
                        {"status": latest_sub_status}
                        if not data[tag].get("packing_list_uid")
                        else {}
                    ),
                    "track_status": latest_sub_status,
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
    # kehu 模式保持现有硬编码逻辑（纯文本输出）
    if mode == "kehu":
        cargo_map: dict = {}
        for order_uid in uid_list:
            order = order_model.read(order_uid)
            for cargo_uid in order["cargo_uid_list"]:
                cargo_res = cargo_model.read(cargo_uid)
                if cargo_res is None:
                    continue
                cargo_res.update(order)
                cargo_map[cargo_uid] = cargo_res
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

    # 从数据库查询模板配置
    template_record = _get_template(mode)
    if template_record is None:
        return None, "Template not found", False

    template_config = json.loads(template_record.config)

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

    if request_cargo_list:
        cargo_map = {
            uid: cargo_map[uid] for uid in request_cargo_list if uid in cargo_map
        }

    cargo_items = list(cargo_map.values())
    if not cargo_items:
        return None, "No cargo data", False

    # ========================== 旧格式兼容 ==========================
    # 旧格式包含 reference_table + columns，使用 pandas 导出
    if "reference_table" in template_config and "columns" in template_config:
        cargos = pd.DataFrame(cargo_items)
        cargos["weight"] = cargos["weight"].apply(
            lambda x: int(0.99 * float(x) * 10) / 10 if x else 0
        )

        columns = template_config.get("columns", [])
        reference_table = template_config.get("reference_table", {})
        result_df = pd.DataFrame(columns=columns)
        for label, name in reference_table.items():
            result_df[label] = cargos.get(name, pd.Series())

        document_id = _build_document_id(template_record.label, cargo_items[0])
        result_df.to_excel(f"excels/{document_id}.xlsx", index=False)
        return document_id, None, False

    # ========================== 新格式导出 ==========================
    column_mappings = template_config.get("column_mappings", {})
    cell_mappings = template_config.get("cell_mappings", [])

    # 只有单元格映射且无列映射时，限制单订单
    if cell_mappings and not column_mappings and len(uid_list) > 1:
        return None, "Exceed Order Count Limitation", False

    # 确定是否有模板文件
    template_path = None
    if template_record.template_file:
        template_path = os.path.join(_TEMPLATE_DIR, template_record.template_file)
        if not os.path.exists(template_path):
            return None, "Template file missing", False

    # 加载或创建工作簿
    if template_path:
        wb = _load_workbook_from_path(template_path)
    else:
        wb = Workbook()
    ws = wb.active

    # 填充单元格映射（固定单元格）
    if cell_mappings:
        order_msg = order_model.read(uid_list[0]) if uid_list else {}
        for mapping in cell_mappings:
            cell_ref = mapping.get("cell")
            field = mapping.get("field")
            if cell_ref and field:
                ws[cell_ref] = order_msg.get(field, "")

    # 填充列映射（从第 2 行开始逐行写入，保留第 1 行表头）
    if column_mappings:
        cargo_items = _apply_weight_adjustment(cargo_items)
        data_start_row = 2 if template_path else 1
        col_indices = {
            col: column_index_from_string(col)
            for col in column_mappings.keys()
        }
        for i, cargo in enumerate(cargo_items):
            row = data_start_row + i
            for col_letter, field in column_mappings.items():
                col_idx = col_indices[col_letter]
                ws.cell(row=row, column=col_idx, value=cargo.get(field, ""))

    document_id = _build_document_id(template_record.label, cargo_items[0])
    wb.save(filename=f"excels/{document_id}.xlsx")
    wb.close()
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
