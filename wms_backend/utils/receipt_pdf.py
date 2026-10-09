"""Bilingual payment receipt PDF renderer."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.pdf_fonts import register_pdf_font


PDF_FONT = register_pdf_font()

STATUS_LABELS = {
    "pending": "待审核 / Pending Review",
    "approved": "已生效 / Approved",
    "rejected": "已驳回 / Rejected - 无效 / Void",
}
SETTLEMENT_LABELS = {
    "settled": "已结清 / Settled",
    "unsettled": "未结清 / Unsettled",
}
PAYMENT_METHOD_LABELS = {
    "cash": "现金 / Cash",
    "bank_transfer": "银行转账 / Bank Transfer",
    "wechat": "微信 / WeChat Pay",
    "alipay": "支付宝 / Alipay",
    "other": "其他 / Other",
}


def _text(value):
    return escape(str(value or "").strip())


def _money(value):
    try:
        return f"{float(value or 0):,.2f} CNY"
    except (TypeError, ValueError):
        return "0.00 CNY"


def build_receipt_pdf(receipt: dict) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Payment Receipt {receipt.get('receipt_no') or ''}",
    )
    base = ParagraphStyle(
        "ReceiptBase",
        fontName=PDF_FONT,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#263238"),
    )
    title = ParagraphStyle(
        "ReceiptTitle",
        parent=base,
        fontSize=19,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#164e63"),
    )
    right = ParagraphStyle("ReceiptRight", parent=base, alignment=TA_RIGHT)
    cell = ParagraphStyle("ReceiptCell", parent=base, fontSize=8, leading=11)
    amount_cell = ParagraphStyle("ReceiptAmount", parent=cell, alignment=TA_RIGHT)
    heading_cell = ParagraphStyle(
        "ReceiptHeading", parent=cell, alignment=TA_CENTER, textColor=colors.white,
    )
    receipt_status = receipt.get("status")
    show_preview = receipt_status == "pending" and receipt.get("settlement_status") == "settled"
    difference_key = "preview_settlement_difference" if show_preview else "settlement_difference"
    show_difference = show_preview or any(
        item.get("settlement_difference") is not None for item in receipt.get("items") or []
    )
    difference_heading = "预计结清差额\nEstimated Difference" if show_preview else "结清差额\nSettlement Difference"
    status_style = ParagraphStyle(
        "ReceiptStatus",
        parent=base,
        fontSize=10.5,
        leading=15,
        alignment=TA_CENTER,
        textColor=(
            colors.HexColor("#15803d")
            if receipt.get("status") == "approved"
            else colors.HexColor("#b45309")
            if receipt.get("status") == "pending"
            else colors.HexColor("#b91c1c")
        ),
    )
    story = [
        Paragraph("<b>迅达货运收款单 / XUNDA PAYMENT RECEIPT</b>", title),
        Spacer(1, 3 * mm),
        Paragraph(f"<b>{_text(STATUS_LABELS.get(receipt.get('status'), receipt.get('status')))}</b>", status_style),
        Spacer(1, 6 * mm),
    ]

    header = Table(
        [[
            Paragraph(f"<b>收款单号 / Receipt No.:</b> {_text(receipt.get('receipt_no'))}", base),
            Paragraph(f"<b>收款日期 / Receipt Date:</b> {_text(receipt.get('receipt_date'))}", right),
        ]],
        colWidths=[91 * mm, 91 * mm],
    )
    header.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#164e63")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 5 * mm))

    info_rows = [
        [Paragraph(f"<b>{label}</b>", base), Paragraph(value or "-", base)]
        for label, value in [
            ("客户 / Customer", _text(receipt.get("customer_name"))),
            ("结清状态 / Settlement", _text(SETTLEMENT_LABELS.get(
                receipt.get("settlement_status"), "历史未设置 / Not recorded"
            ))),
            ("付款方式 / Payment Method", _text(PAYMENT_METHOD_LABELS.get(receipt.get("payment_method"), receipt.get("payment_method")))),
            ("创建人 / Created By", _text(receipt.get("creator_name"))),
            ("审核人 / Reviewed By", _text(receipt.get("reviewer_name"))),
            ("审核时间 / Review Time", _text(receipt.get("review_date"))),
            ("备注 / Remarks", _text(receipt.get("remark"))),
            ("审核意见 / Review Notes", _text(receipt.get("review_remark"))),
        ]
    ]
    info = Table(info_rows, colWidths=[55 * mm, 127 * mm])
    info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(info)
    story.append(Spacer(1, 6 * mm))

    item_rows = [[
        "订单号\nOrder No.",
        "应收\nReceivable",
        "此前已收\nPreviously Paid",
        "本次收款\nThis Receipt",
        "可收余额快照\nAvailable Snapshot",
    ]]
    if show_difference:
        item_rows[0].append(difference_heading)
    for item in receipt.get("items") or []:
        row = [
            item.get("order_id") or "-",
            _money(item.get("receivable_snapshot")),
            _money(item.get("received_before")),
            _money(item.get("amount")),
            _money(item.get("remaining_after")),
        ]
        if show_difference:
            value = item.get(difference_key)
            row.append(_money(value) if value is not None else "-")
        item_rows.append(row)
    total_row = ["合计 / Total", "", "", _money(receipt.get("total_amount")), ""]
    if show_difference:
        differences = [item.get(difference_key) for item in receipt.get("items") or []]
        total_row.append(_money(sum(float(value) for value in differences if value is not None)))
    item_rows.append(total_row)
    item_rows = [
        [Paragraph(_text(value).replace("\n", "<br/>"), heading_cell if row_index == 0 else cell if column == 0 else amount_cell)
         for column, value in enumerate(row)]
        for row_index, row in enumerate(item_rows)
    ]
    widths = [37, 29, 29, 29, 29, 29] if show_difference else [42, 35, 35, 35, 35]
    items = LongTable(item_rows, repeatRows=1, colWidths=[value * mm for value in widths])
    items.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#164e63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#cbd5e1")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.1, colors.HexColor("#164e63")),
        ("FONTNAME", (0, -1), (-1, -1), PDF_FONT),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(items)
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(
        "本收款单的财务效力以所示审核状态为准。 / The accounting validity of this receipt is determined by the review status shown above.",
        base,
    ))
    if receipt.get("settlement_status") == "settled":
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "结清须经审核通过后生效；结清差额不计入实际收入。 / Settlement takes effect only after approval; the settlement difference is not actual income.",
            base,
        ))
    if show_preview:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "预计结清差额未扣除其他待审核收款；最终差额以审核通过时为准。 / Estimates exclude other pending receipts and are finalized on approval.",
            base,
        ))

    def add_page_number(canvas, document):
        canvas.saveState()
        canvas.setFont(PDF_FONT, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"第 {document.page} 页 / Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer
