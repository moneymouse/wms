from io import BytesIO
from typing import Any, Dict
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.pdf_fonts import register_pdf_font


PDF_FONT = register_pdf_font()


def _text(value: Any) -> str:
    return escape(str(value or "").strip())


def _money(value: Any) -> str:
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def build_quote_pdf(order: Dict[str, Any], quote: Dict[str, Any]) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    base = ParagraphStyle(
        "Base",
        fontName=PDF_FONT,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#333333"),
    )
    title = ParagraphStyle(
        "Title",
        parent=base,
        fontSize=20,
        leading=28,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1f497d"),
    )
    right = ParagraphStyle("Right", parent=base, alignment=TA_RIGHT)

    story = [
        Paragraph("<b>迅达货运报价单 / XUNDA QUOTATION</b>", title),
        Spacer(1, 8 * mm),
    ]
    header = Table(
        [[
            Paragraph(f"<b>订单号 / Order No.:</b> {_text(order.get('order_id'))}", base),
            Paragraph(f"<b>报价版本 / Quote Version:</b> V{_text(quote.get('version_no'))}", right),
        ]],
        colWidths=[89 * mm, 89 * mm],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#1f497d")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 8 * mm))

    billing_weight = quote.get("billing_weight") or 0

    raw_rows = [
        ["项目 / Item", "内容 / Details"],
        ["客户 / Customer", _text(order.get("customer_name")) or "-"],
        ["收件人 / Receiver", _text(order.get("receiver")) or "-"],
        ["国家/城市 / Country/City", f"{_text(order.get('country'))} / {_text(order.get('city'))}"],
        ["地址 / Address", _text(order.get("address")) or "-"],
        ["货运渠道 / Shipping Channel", _text(quote.get("transportation_name")) or "-"],
        ["计费重量 / Billing Weight", f"{float(billing_weight):.0f} kg"],
        ["每公斤单价 / Unit Price", f"{float(quote.get('unit_price') or 0):.4f} CNY/kg"],
        ["附加费 / Surcharge", f"{_money(quote.get('surcharge'))} CNY"],
        ["应收账款 / Receivable", f"{_money(quote.get('receivable_amount'))} CNY"],
        ["报价人 / Quoted By", _text(quote.get("quoter_name")) or "-"],
        ["报价时间 / Quote Time", _text(quote.get("create_date")) or "-"],
        ["生效时间 / Effective Time", _text(quote.get("effective_date")) or "-"],
        ["审核人 / Reviewed By", _text(quote.get("reviewer_name")) or "-"],
    ]
    rows = [
        [
            Paragraph(f"<b>{left}</b>" if index == 0 else left, base),
            Paragraph(f"<b>{right_value}</b>" if index == 0 else right_value, base),
        ]
        for index, (left, right_value) in enumerate(raw_rows)
    ]

    table = Table(rows, colWidths=[58 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f497d")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#fafafa")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(table)
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "应收账款 = 计费重量 x 每公斤单价 + 附加费。订单重量变化后需重新报价。 / "
        "Receivable = billing weight x unit price + surcharge. A new quote is required after any weight change.",
        base,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer
