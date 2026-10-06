"""Payment facts and packing-box snapshots; notes remain separate from allocations."""
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.pdf_fonts import register_pdf_font


STATUS = {"draft": "草稿 · 尚未提交财务", "pending": "待财务确认 · 尚未确认入账", "posted": "财务已确认入账",
    "cancelled": "已取消 · 无效记录", "reversed": "已冲销 · 原记录保留"}


def build_finance_payment_pdf(payment):
    stream = BytesIO()
    font = register_pdf_font()
    style = ParagraphStyle("FinancePayment", fontName=font, fontSize=10, leading=15, wordWrap="CJK")
    title = ParagraphStyle("FinancePaymentTitle", parent=style, fontSize=17, leading=24, alignment=1)
    def text(value):
        return Paragraph(escape(str(value if value is not None else "—")).replace("\n", "<br/>"), style)
    document = SimpleDocTemplate(stream, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm, title=str(payment.get("number") or "收付款凭证"))
    direction = "收款" if payment.get("direction") == "incoming" else "付款"
    rows = [
        ("凭证编号", payment.get("number")), ("状态", STATUS.get(payment.get("status"), payment.get("status"))),
        ("客户 / 往来单位", payment.get("partner_name")), ("资金日期", payment.get("payment_date")),
        (f"实际{direction}金额", f"{Decimal(str(payment.get('amount') or 0)):,.2f} CNY"),
        ("收付款账户", payment.get("account_name")), ("资金凭据号", payment.get("reference")),
        ("登记人", payment.get("created_by_name")), ("提交时间", payment.get("submitted_at")),
        ("财务确认人", payment.get("reviewed_by_name")), ("财务确认 / 退回时间", payment.get("reviewed_at")),
    ]
    table = Table([[text(label), text(value or "—")] for label, value in rows], colWidths=[43*mm, 131*mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), .35, colors.lightgrey),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story = [Paragraph(f"迅达货运{direction}凭证", title), Spacer(1, 7*mm), table, Spacer(1, 6*mm)]
    for label, value in (("财务意见", payment.get("review_remark")), ("备注", payment.get("memo"))):
        if value:
            story.extend([text(label), text(value), Spacer(1, 4*mm)])
    if payment.get("reference_orders"):
        story.append(text("备注订单（仅为说明，不代表已核销或订单结清）"))
        references = LongTable([[text(row.get("order_number") or row.get("order_uid"))] for row in payment["reference_orders"]], colWidths=[174*mm])
        references.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.extend([Spacer(1, 2*mm), references, Spacer(1, 5*mm)])
    if payment.get("reference_packing_boxes"):
        story.append(text("备注装箱单箱子（登记时快照，订单结算以财务核销为准）"))
        rows = [[text(value) for value in ("装箱单 / 唛头", "箱号", "原单号", "品名", "重量(kg)")]]
        rows.extend([[text(value) for value in (row.get("list_number"), row.get("box_number"),
            row.get("transfer_id") or "—", row.get("item_name") or "—", row.get("weight"))]
            for row in payment["reference_packing_boxes"]])
        boxes = LongTable(rows, colWidths=[46*mm, 15*mm, 49*mm, 43*mm, 21*mm], repeatRows=1)
        boxes.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f2f5")),
            ("GRID", (0, 0), (-1, -1), .35, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.extend([Spacer(1, 2*mm), boxes, Spacer(1, 5*mm)])
    story.append(text("本凭证记录收付款金额及账户；订单结算以财务核销记录为准，报价和货重变化不会改写本笔资金。"))
    if payment.get("status") != "posted":
        story.append(text("当前状态不能作为财务已确认到账或付款的证明。"))
    if payment.get("is_opening"):
        story.append(text("本记录为期初余额，不代表本期实际资金流入或流出。"))
    def page_number(canvas, doc):
        canvas.setFont(font, 8)
        canvas.drawRightString(A4[0]-18*mm, 9*mm, f"第 {doc.page} 页")
    document.build(story, onFirstPage=page_number, onLaterPages=page_number)
    stream.seek(0)
    return stream
