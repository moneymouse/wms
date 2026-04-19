import math
from io import BytesIO
from typing import Any, Dict, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

# 注册字体
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _build_item_qty_text(box: Dict[str, Any]) -> str:
    details = (
        box.get("item_details") if isinstance(box.get("item_details"), list) else []
    )
    normalized_details: List[str] = []

    for row in details:
        if not isinstance(row, dict):
            continue
        name = _normalize_text(row.get("item_name"))
        try:
            qty = int(row.get("piece_count") or 0)
        except (TypeError, ValueError):
            qty = 0
        if name:
            normalized_details.append(f"{name}*{qty}")

    if normalized_details:
        return ", ".join(normalized_details)

    fallback_name = _normalize_text(box.get("item_name"))
    try:
        fallback_qty = int(box.get("piece_count") or 0)
    except (TypeError, ValueError):
        fallback_qty = 0

    return f"{fallback_name}*{fallback_qty}" if fallback_name else "-"


def build_packing_list_pdf(detail: Dict[str, Any]) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    # --- 样式定义 (已调大字体和行距) ---
    base_style = ParagraphStyle(
        name="Base",
        fontName="STSong-Light",
        fontSize=11.5,  # 字体从 10 调大到 11.5
        leading=16,  # 行距从 14 调大到 16，避免多行文字粘连
        textColor=colors.HexColor("#333333"),
    )

    title_style = ParagraphStyle(
        name="MainTitle",
        parent=base_style,
        fontSize=20,  # 标题从 18 调大到 20
        leading=26,
        alignment=TA_CENTER,
    )

    list_number = (
        _normalize_text(detail.get("list_number") or detail.get("mark")) or "-"
    )
    customer_name = _normalize_text(detail.get("customer_name"))

    story = []

    # 顶部公司名放大至 16
    company_style = ParagraphStyle(
        "H",
        parent=base_style,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1f497d"),
    )
    story.append(Paragraph("<b>XUNDA PACKING LIST</b>", company_style))
    story.append(Spacer(1, 6 * mm))

    # 文档大标题
    story.append(Paragraph("装 箱 单 / PACKING LIST", title_style))
    story.append(Spacer(1, 8 * mm))

    # 头部信息
    header_left = f"<b>客户 / Customer:</b> {customer_name}"
    header_right = f"<b>唛头 / Mark:</b> {list_number}"
    header_table = Table(
        [
            [
                Paragraph(header_left, base_style),
                Paragraph(
                    header_right,
                    ParagraphStyle("R", parent=base_style, alignment=TA_RIGHT),
                ),
            ]
        ],
        colWidths=[91 * mm, 91 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#1f497d")),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),  # 增加底边距
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 8 * mm))

    # 表格数据处理
    rows = [
        ["箱号\nBox No.", "重量(kg)\nWeight", "品名*件数\nItem*Qty", "备注\nRemark"]
    ]

    total_weight = 0
    boxes = detail.get("boxes") or []

    for box in boxes:
        box_number = _normalize_text(box.get("box_number")) or "-"

        # 重量处理：进一取整
        weight_val = box.get("weight")
        display_weight = "-"
        if weight_val is not None and str(weight_val).strip() != "":
            try:
                rounded_w = math.ceil(float(weight_val))
                display_weight = str(rounded_w)
                total_weight += rounded_w
            except (TypeError, ValueError):
                display_weight = _normalize_text(weight_val)

        item_qty = _build_item_qty_text(box)
        remark = _normalize_text(box.get("remark")) or "-"

        # 用 base_style 包装，继承了 11.5 的字号和 16 的行距
        rows.append(
            [
                box_number,
                display_weight,
                Paragraph(item_qty, base_style),
                Paragraph(remark, base_style),
            ]
        )

    # 添加总计行
    rows.append(["总计 / TOTAL", str(total_weight), "", ""])

    # 表格样式
    table = Table(rows, colWidths=[25 * mm, 30 * mm, 75 * mm, 52 * mm], repeatRows=1)

    table_style_list = [
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 11.5),  # 全局基础字号 11.5
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # --- 表头样式 ---
        ("FONTSIZE", (0, 0), (-1, 0), 12),  # 表头字号再大一点: 12
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f8")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 10),  # 表头内边距加大
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        # --- 数据对齐 ---
        ("ALIGN", (0, 1), (1, -1), "CENTER"),
        ("ALIGN", (2, 1), (3, -1), "LEFT"),
        # --- 单元格边距 ---
        ("TOPPADDING", (0, 1), (-1, -1), 8),  # 数据行上下边距加大，防止显得局促
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # --- 线条 ---
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.HexColor("#1f497d")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.HexColor("#1f497d")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        # --- 总计行特别样式 ---
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f4f6f8")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, colors.HexColor("#1f497d")),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.HexColor("#1f497d")),
    ]

    table.setStyle(TableStyle(table_style_list))

    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer
