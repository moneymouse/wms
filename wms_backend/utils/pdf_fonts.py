"""Portable PDF font registration shared by printable ERP documents."""

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


PDF_FONT_NAME = "WMS-DroidSansFallback"
PDF_FONT_PATH = (
    Path(__file__).resolve().parent
    / "assets"
    / "fonts"
    / "DroidSansFallback.ttf"
)


def register_pdf_font() -> str:
    """Register the bundled Apache-2.0 CJK font once and return its name."""
    if PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(PDF_FONT_PATH)))
    return PDF_FONT_NAME

