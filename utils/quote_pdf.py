from io import BytesIO
from typing import Any, Dict
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


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
        fontName="STSong-Light",
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
            Paragraph(f"<b>订单号:</b> {_text(order.get('order_id'))}", base),
            Paragraph(f"<b>报价版本:</b> V{_text(quote.get('version_no'))}", right),
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

    rows = [
        ["项目", "内容"],
        ["客户", _text(order.get("customer_name")) or "-"],
        ["收件人", _text(order.get("receiver")) or "-"],
        ["国家/城市", f"{_text(order.get('country'))} / {_text(order.get('city'))}"],
        ["地址", _text(order.get("address")) or "-"],
        ["最终货运渠道", _text(quote.get("transportation_name")) or "-"],
        ["报价金额", _money(quote.get("quoted_price"))],
        ["报价人", _text(quote.get("quoter_name")) or "-"],
        ["报价时间", _text(quote.get("create_date")) or "-"],
        ["审核人", _text(quote.get("reviewer_name")) or "-"],
        ["审核时间", _text(quote.get("review_date")) or "-"],
    ]

    table = Table(rows, colWidths=[42 * mm, 136 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
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
    story.append(Paragraph("本报价单以系统最终采纳报价为准。", base))

    doc.build(story)
    buffer.seek(0)
    return buffer
