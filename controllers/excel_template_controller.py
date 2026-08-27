"""Excel export template management APIs."""

import json
import os
import time

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from Auth import allow, verify
from data.database import SessionFactory
from data.DB import ExcelTemplateTable

excel_template_bp = Blueprint("excel_template", __name__, url_prefix="/api")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "excel_templates")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"xlsx", "xls"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _template_to_dict(record):
    return {
        "id": record.id,
        "mode_key": record.mode_key,
        "label": record.label,
        "template_type": record.template_type,
        "config": record.config,
        "template_file": record.template_file,
        "single_order_only": record.single_order_only,
        "requires_valid_quote": bool(record.requires_valid_quote),
        "create_date": record.create_date,
        "update_date": record.update_date,
    }


@excel_template_bp.get("/excel-templates")
@verify
def get_excel_templates():
    """获取所有非归档的 Excel 导出模板。所有已登录用户可访问。"""
    with SessionFactory() as session:
        records = (
            session.query(ExcelTemplateTable)
            .filter(ExcelTemplateTable.archive == False)  # noqa: E712
            .order_by(ExcelTemplateTable.id.desc())
            .all()
        )
        data = [_template_to_dict(r) for r in records]
    return jsonify({"code": 200, "data": data})


@excel_template_bp.get("/excel-templates/<int:record_id>")
@verify
@allow(role="admin")
def get_excel_template_detail(record_id: int):
    """获取单个模板详情。仅管理员。"""
    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.id == record_id,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "模板不存在"}), 404
        return jsonify({"code": 200, "data": _template_to_dict(record)})


@excel_template_bp.post("/excel-templates")
@verify
@allow(role="admin")
def create_excel_template():
    """新增 Excel 导出模板。仅管理员。"""
    body = request.get_json() or {}
    mode_key = (body.get("mode_key") or "").strip()
    label = (body.get("label") or "").strip()
    template_type = (body.get("template_type") or "").strip()
    config = body.get("config") or "{}"
    single_order_only = bool(body.get("single_order_only", False))
    requires_valid_quote = bool(body.get("requires_valid_quote", True))

    if not mode_key:
        return jsonify({"code": 400, "msg": "mode_key 不能为空"}), 400
    if not label:
        return jsonify({"code": 400, "msg": "label 不能为空"}), 400
    if template_type not in ("column", "cell"):
        return jsonify({"code": 400, "msg": "template_type 必须为 column 或 cell"}), 400

    if template_type == "cell":
        single_order_only = True

    now = time.strftime("%Y-%m-%d %H:%M")
    record = ExcelTemplateTable(
        mode_key=mode_key,
        label=label,
        template_type=template_type,
        config=json.dumps(config) if isinstance(config, dict) else str(config),
        single_order_only=single_order_only,
        requires_valid_quote=requires_valid_quote,
        create_date=now,
        update_date=now,
    )

    with SessionFactory() as session:
        existing = (
            session.query(ExcelTemplateTable)
            .filter(ExcelTemplateTable.mode_key == mode_key)
            .first()
        )
        if existing:
            return jsonify({"code": 400, "msg": "mode_key 已存在"}), 400
        session.add(record)
        session.commit()
        return jsonify({"code": 200, "data": _template_to_dict(record)})


@excel_template_bp.put("/excel-templates/<int:record_id>")
@verify
@allow(role="admin")
def update_excel_template(record_id: int):
    """修改 Excel 导出模板配置。仅管理员。"""
    body = request.get_json() or {}
    label = (body.get("label") or "").strip()
    template_type = (body.get("template_type") or "").strip()
    config = body.get("config")
    single_order_only = body.get("single_order_only")
    requires_valid_quote = body.get("requires_valid_quote")

    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.id == record_id,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "模板不存在"}), 404

        if label:
            record.label = label
        if template_type in ("column", "cell"):
            record.template_type = template_type
            if template_type == "cell":
                record.single_order_only = True
            elif single_order_only is not None:
                record.single_order_only = bool(single_order_only)
        elif single_order_only is not None:
            record.single_order_only = bool(single_order_only)

        if requires_valid_quote is not None:
            record.requires_valid_quote = bool(requires_valid_quote)

        if config is not None:
            record.config = json.dumps(config) if isinstance(config, dict) else str(config)

        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()
        return jsonify({"code": 200, "data": _template_to_dict(record)})


@excel_template_bp.post("/excel-templates/<int:record_id>/archive")
@verify
@allow(role="admin")
def archive_excel_template(record_id: int):
    """归档 Excel 导出模板。仅管理员。"""
    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.id == record_id,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "模板不存在"}), 404

        record.archive = True
        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()
        return jsonify({"code": 200, "msg": "已归档"})


@excel_template_bp.delete("/excel-templates/<int:record_id>")
@verify
@allow(role="admin")
def delete_excel_template(record_id: int):
    """删除 Excel 导出模板。仅管理员。"""
    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(ExcelTemplateTable.id == record_id)
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "模板不存在"}), 404

        session.delete(record)
        session.commit()
        return jsonify({"code": 200, "msg": "已删除"})


@excel_template_bp.post("/excel-templates/<int:record_id>/upload")
@verify
@allow(role="admin")
def upload_excel_template_file(record_id: int):
    """上传单元格模式所需的 .xlsx/.xls 模板文件。仅管理员。"""
    if "file" not in request.files:
        return jsonify({"code": 400, "msg": "未找到文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"code": 400, "msg": "未选择文件"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"code": 400, "msg": "仅支持 .xlsx 或 .xls 文件"}), 400

    with SessionFactory() as session:
        record = (
            session.query(ExcelTemplateTable)
            .filter(
                ExcelTemplateTable.id == record_id,
                ExcelTemplateTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if record is None:
            return jsonify({"code": 404, "msg": "模板不存在"}), 404

        ext = file.filename.rsplit(".", 1)[1].lower()
        filename = secure_filename(f"{record.mode_key}_template.{ext}")
        filepath = os.path.join(UPLOAD_DIR, filename)
        file.save(filepath)

        record.template_file = filename
        record.update_date = time.strftime("%Y-%m-%d %H:%M")
        session.commit()
        return jsonify({"code": 200, "data": {"template_file": filename}})
