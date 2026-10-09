"""Readable, cuttable shipping confirmations with one order per A4 row."""

from dataclasses import dataclass
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from utils.pdf_fonts import register_pdf_font


PDF_FONT = register_pdf_font()
PAGE_MARGIN = 12 * mm
CUT_GAP = 6 * mm
CARD_PADDING = 2.5 * mm
CARD_WIDTH = A4[0] - 2 * PAGE_MARGIN
PAGE_CONTENT_HEIGHT = A4[1] - 2 * PAGE_MARGIN
BLUE = colors.HexColor("#1f497d")
CUT_COLOR = colors.HexColor("#94a3b8")


def _text(value: Any) -> str:
    return escape(str(value if value is not None else "").strip()).replace("\n", "<br/>")


def _styles():
    base = ParagraphStyle(
        "ShippingConfirmationBase",
        fontName=PDF_FONT,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#333333"),
        wordWrap="CJK",
    )
    return {
        "base": base,
        "title": ParagraphStyle(
            "ShippingConfirmationTitle", parent=base, fontSize=18,
            leading=23, alignment=TA_CENTER, textColor=BLUE,
        ),
        "identity": ParagraphStyle(
            "ShippingConfirmationIdentity", parent=base, fontSize=10,
            leading=14, textColor=colors.HexColor("#64748b"),
        ),
        "heading": ParagraphStyle(
            "ShippingConfirmationHeading", parent=base, fontSize=11,
            leading=15, alignment=TA_CENTER, textColor=BLUE,
        ),
    }


def _header(order, styles, continuation=""):
    width = CARD_WIDTH - 2 * CARD_PADDING
    identity = f"{_text(order.get('identity_label') or '订单 / Order')}: {_text(order.get('identity_value') or order.get('order_id') or order.get('uid'))}"
    if continuation:
        identity += f"<br/>{continuation}"
    metadata_rows = [
        [Paragraph("客户名", styles["base"]), Paragraph(_text(order.get("customer_name")), styles["base"])],
        [Paragraph("代理名", styles["base"]), Paragraph(_text(order.get("agent_name")), styles["base"])],
    ]
    if order.get("remarks"):
        metadata_rows.append([Paragraph("备注", styles["base"]), Paragraph(_text(order["remarks"]), styles["base"])])
    metadata = Table(
        metadata_rows,
        colWidths=[24 * mm, width - 24 * mm],
    )
    metadata.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEBELOW", (0, -1), (-1, -1), 0.7, BLUE),
    ]))
    return [
        Paragraph("出货单", styles["title"]),
        Spacer(1, 1 * mm),
        Paragraph(identity, styles["identity"]),
        Spacer(1, 0.5 * mm),
        metadata,
        Spacer(1, 1.5 * mm),
    ]


def _mark_group(box):
    list_number = str(box.get("list_number") or "").strip()
    if list_number:
        return list_number
    tag = str(box.get("tag") or "").strip()
    mark, separator, box_number = tag.rpartition("_")
    return mark if mark and separator and box_number.isdecimal() else tag


def _box_table(boxes, styles):
    width = CARD_WIDTH - 2 * CARD_PADDING
    rows = [[
        Paragraph("唛头 / Mark", styles["heading"]),
        Paragraph("原单号 / Original No.", styles["heading"]),
    ]]
    rows.extend([
        Paragraph(_text(box.get("tag")), styles["base"]),
        Paragraph(_text(box.get("transfer_id")), styles["base"]),
    ] for box in boxes)
    table = Table(rows, colWidths=[width * 0.42, width * 0.58], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f8")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9d9")),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    for row, (box, next_box) in enumerate(zip(boxes, boxes[1:]), start=1):
        if _mark_group(box) != _mark_group(next_box):
            table.setStyle(TableStyle([
                ("LINEBELOW", (0, row), (-1, row), 1.2, BLUE),
            ]))
    return table


@dataclass
class _Card:
    flowables: list
    height: float


def _card(flowables):
    width = CARD_WIDTH - 2 * CARD_PADDING
    height = sum(item.wrap(width, PAGE_CONTENT_HEIGHT)[1] for item in flowables)
    return _Card(flowables, height + 2 * CARD_PADDING)


def _order_cards(order, styles):
    """Keep an order whole unless it exceeds the printable height of a page."""
    boxes = order.get("boxes") or []
    table = _box_table(boxes, styles)
    header = _header(order, styles)
    complete = _card(header + [table])
    if complete.height <= PAGE_CONTENT_HEIGHT:
        return [complete]

    # Reserve a continuation line before splitting, so every piece can carry
    # customer, agent, order identity, and column headings after cutting.
    continued_header = _header(order, styles, "续单 / Part: 1/1")
    header_height = _card(continued_header).height
    table_height = PAGE_CONTENT_HEIGHT - header_height
    if table_height <= 20 * mm:
        raise ValueError("代理、备注或装箱单编号过长，请缩短后打印")
    remaining = table
    parts = []
    width = CARD_WIDTH - 2 * CARD_PADDING
    while remaining is not None:
        if remaining.wrap(width, PAGE_CONTENT_HEIGHT)[1] <= table_height:
            parts.append(remaining)
            break
        split = remaining.split(width, table_height)
        if len(split) < 2:
            raise ValueError("单箱字段过长，无法完整放入出货确认单")
        parts.append(split[0])
        remaining = split[1]
    return [
        _card(_header(order, styles, f"续单 / Part: {index + 1}/{len(parts)}") + [part])
        for index, part in enumerate(parts)
    ]


def _draw_card(canvas, card, x, top, row_height):
    canvas.saveState()
    cursor = top - CARD_PADDING
    width = CARD_WIDTH - 2 * CARD_PADDING
    for item in card.flowables:
        _, height = item.wrap(width, PAGE_CONTENT_HEIGHT)
        cursor -= height
        item.drawOn(canvas, x + CARD_PADDING, cursor)
    canvas.restoreState()


def _draw_cut_lines(canvas, row_bottoms):
    """Separate full-width shipping notes with horizontal dashed cut lines."""
    if not row_bottoms:
        return
    canvas.saveState()
    canvas.setStrokeColor(CUT_COLOR)
    canvas.setLineWidth(0.4)
    canvas.setDash(2, 3)
    for bottom in row_bottoms:
        y = bottom - CUT_GAP / 2
        canvas.line(PAGE_MARGIN - CUT_GAP / 2, y, A4[0] - PAGE_MARGIN + CUT_GAP / 2, y)
    canvas.restoreState()


def build_shipping_confirmation_pdf(details: list[dict]) -> BytesIO:
    if not details:
        raise ValueError("请先选择要导出的订单")
    styles = _styles()
    cards = [card for order in details for card in _order_cards(order, styles)]
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.setTitle("出货单")
    top = A4[1] - PAGE_MARGIN
    row_bottoms = []
    for card in cards:
        row_height = card.height
        if top - row_height < PAGE_MARGIN - 0.01:
            _draw_cut_lines(canvas, row_bottoms)
            canvas.showPage()
            top = A4[1] - PAGE_MARGIN
            row_bottoms = []
        _draw_card(canvas, card, PAGE_MARGIN, top, row_height)
        row_bottoms.append(top - row_height)
        top -= row_height + CUT_GAP
    _draw_cut_lines(canvas, row_bottoms)
    canvas.save()
    buffer.seek(0)
    return buffer
