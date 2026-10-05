"""Generate the printable A4 handwritten packing-list template.

Usage: python scripts/generate_paper_intake_template.py [--output PATH] [--font PATH]
Requires reportlab and a Chinese TrueType font (TTC collections are supported).
"""

from argparse import ArgumentParser
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BACKEND_ROOT / "static/templates/paper-packing-list-a4.pdf"
FONT_NAME = "PackingListChinese"
FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def register_chinese_font(font_path=None):
    """Embed a system Chinese font so the PDF prints consistently."""
    paths = (font_path,) if font_path else FONT_CANDIDATES
    errors = []
    for path in paths:
        if not Path(path).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(path), subfontIndex=0))
            return
        except Exception as error:
            errors.append(f"{path}: {error}")
    details = "; ".join(errors) or "No supported Chinese TrueType font found."
    raise RuntimeError(f"Use --font to supply a Chinese TTF/TTC font. {details}")


def generate_template(output_path, font_path=None):
    register_chinese_font(font_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = A4
    margin = 12 * mm
    right = page_width - margin
    content_width = right - margin
    document = canvas.Canvas(str(output_path), pagesize=A4, pageCompression=1)
    document.setTitle("迅达货运装箱单 - A4 手写模板")
    document.setAuthor("迅达货运仓储管理系统")
    document.setSubject("每页一唛头；操作人员与逐箱品名、件数和重量填写模板")
    document.setStrokeColorRGB(0, 0, 0)
    document.setFillColorRGB(0, 0, 0)

    def text(x, y, value, size=11):
        document.setFont(FONT_NAME, size)
        document.drawString(x, y, value)

    def centered(x, y, value, size=11):
        document.setFont(FONT_NAME, size)
        document.drawCentredString(x, y, value)

    centered(page_width / 2, page_height - 21 * mm, "迅达货运装箱单", 21)
    centered(page_width / 2, page_height - 28 * mm, "每页只填写一个唛头，请使用黑色或蓝色笔清晰填写", 9)

    # A large, isolated shipping-mark field helps both workers and OCR.
    mark_bottom = page_height - 49 * mm
    mark_height = 15 * mm
    mark_label_width = 25 * mm
    document.setLineWidth(0.8)
    document.rect(margin, mark_bottom, content_width, mark_height)
    document.line(margin + mark_label_width, mark_bottom, margin + mark_label_width,
                  mark_bottom + mark_height)
    centered(margin + mark_label_width / 2, mark_bottom + 5.3 * mm, "唛  头", 14)

    meta_y = page_height - 58 * mm
    text(margin, meta_y, "作业日期：", 10)
    document.setLineWidth(0.5)
    document.line(margin + 19 * mm, meta_y - 2, margin + 70 * mm, meta_y - 2)
    text(margin + 76 * mm, meta_y, "操作人员 / 装箱人：", 10)
    document.line(margin + 112 * mm, meta_y - 2, margin + 143 * mm, meta_y - 2)
    text(margin + 147 * mm, meta_y, "第____页 / 共____页", 9)

    table_top = page_height - 65 * mm
    row_height = 9.1 * mm
    row_count = 18
    table_height = (row_count + 1) * row_height
    table_bottom = table_top - table_height
    widths = (22 * mm, 73 * mm, 22 * mm, 32 * mm, content_width - 149 * mm)
    headers = ("箱号", "品名", "件数", "重量（kg）", "备注")

    document.setLineWidth(0.8)
    document.rect(margin, table_bottom, content_width, table_height)
    cursor_x = margin
    for width, header in zip(widths, headers):
        centered(cursor_x + width / 2, table_top - row_height / 2 - 4, header, 11)
        cursor_x += width
        if cursor_x < right - 0.1:
            document.setLineWidth(0.55)
            document.line(cursor_x, table_bottom, cursor_x, table_top)
    for row in range(1, row_count + 1):
        line_y = table_top - row * row_height
        document.setLineWidth(0.8 if row == 1 else 0.45)
        document.line(margin, line_y, right, line_y)

    total_y = table_bottom - 9 * mm
    text(margin, total_y, "合计箱数：________", 10)
    text(margin + 47 * mm, total_y, "合计件数：________", 10)
    text(margin + 95 * mm, total_y, "合计重量：________ kg", 10)
    text(margin + 148 * mm, total_y, "核对人：________", 10)

    notes_y = total_y - 10 * mm
    text(margin, notes_y, "填写说明", 10)
    notes = (
        "1. 每箱一行，箱号连续且不可漏填；件数、重量须逐箱填写。",
        "2. 连续箱品名相同，请写“同上”或“〃”；更换商品时重新写完整品名。",
        "3. 跨页首行须重写完整品名；每页填写唛头、操作人员和页码。",
        "4. 上传时拍全纸面，保持平整清晰，避免反光、遮挡和裁切。",
    )
    for index, note in enumerate(notes, start=1):
        text(margin, notes_y - index * 5 * mm, note, 9)
    document.showPage()
    document.save()
    return output_path


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=Path, help="Chinese TrueType font (TTF or TTC).")
    arguments = parser.parse_args()
    print(generate_template(arguments.output, arguments.font))
