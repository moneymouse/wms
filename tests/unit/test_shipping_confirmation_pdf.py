"""Verify cut boundaries, whole-order pagination, and every printed box."""

import base64
import re
import zlib

import pytest
from reportlab.pdfgen.canvas import Canvas

from utils import shipping_confirmation_pdf as pdf


def _order(number, count=2):
    return {
        "uid": f"UID-{number}",
        "order_id": f"ORDER-{number}",
        "customer_name": "测试客户 & <贸易公司>",
        "agent_name": "JF",
        "boxes": [
            {"tag": f"MARK-{number}-{index:03d}", "transfer_id": f"TRACK-{number}-{index:03d}"}
            for index in range(count)
        ],
    }


def _content_streams(content):
    streams = []
    for encoded in re.findall(rb"stream\r?\n(.*?)endstream", content, flags=re.DOTALL):
        try:
            decoded = zlib.decompress(base64.a85decode(encoded.strip(), adobe=True))
        except (ValueError, zlib.error):
            continue
        if b"BT" in decoded:
            streams.append(decoded)
    return b"\n".join(streams)


@pytest.fixture
def print_geometry(monkeypatch):
    geometry = {"cards": [], "cuts": [], "frames": []}
    draw_card = pdf._draw_card

    def record_card(canvas, card, x, top, row_height):
        geometry["cards"].append((canvas.getPageNumber(), x, top - row_height, pdf.CARD_WIDTH, row_height))
        draw_card(canvas, card, x, top, row_height)

    class RecordingCanvas(Canvas):
        def line(self, x1, y1, x2, y2):
            if self._strokeColorObj == pdf.CUT_COLOR:
                geometry["cuts"].append((self.getPageNumber(), x1, y1, x2, y2))
            return super().line(x1, y1, x2, y2)

        def rect(self, x, y, width, height, stroke=1, fill=0):
            if stroke and not fill:
                geometry["frames"].append((x, y, width, height))
            return super().rect(x, y, width, height, stroke=stroke, fill=fill)

    monkeypatch.setattr(pdf, "_draw_card", record_card)
    monkeypatch.setattr(pdf, "Canvas", RecordingCanvas)
    return geometry


def test_each_order_uses_a_full_width_row_and_embedded_font(print_geometry):
    content = pdf.build_shipping_confirmation_pdf([_order(1, 1), _order(2, 4)]).getvalue()
    assert content.startswith(b"%PDF-")
    assert b"DroidSansFallback" in content
    assert b"STSong" not in content
    first, second = print_geometry["cards"]
    assert first[0] == second[0] == 1
    assert first[1] == second[1] == pytest.approx(pdf.PAGE_MARGIN)
    assert first[3] == second[3] == pytest.approx(pdf.A4[0] - 2 * pdf.PAGE_MARGIN)
    assert first[2] - (second[2] + second[4]) == pytest.approx(pdf.CUT_GAP)
    printed = _content_streams(content)
    assert b"ORDER-1" in printed and b"ORDER-2" in printed
    assert b"TRACK-1-000" in printed and b"TRACK-2-003" in printed


def test_many_orders_paginate_without_splitting_or_leaving_page(print_geometry):
    orders = [_order(index, 4) for index in range(20)]
    printed = _content_streams(pdf.build_shipping_confirmation_pdf(orders).getvalue())
    cut_rectangles = print_geometry["cards"]
    assert len(cut_rectangles) == len(orders)
    assert max(rect[0] for rect in cut_rectangles) > 1
    for _, x, y, width, height in cut_rectangles:
        assert x >= pdf.PAGE_MARGIN - 0.01
        assert y >= pdf.PAGE_MARGIN - 0.01
        assert x + width <= pdf.A4[0] - pdf.PAGE_MARGIN + 0.01
        assert y + height <= pdf.A4[1] - pdf.PAGE_MARGIN + 0.01
    for order in orders:
        assert printed.count(f"{order['order_id']})".encode()) == 1
        for box in order["boxes"]:
            assert printed.count(f"({box['transfer_id']})".encode()) == 1


def test_oversized_order_repeats_context_and_preserves_every_box(print_geometry):
    order = _order("LARGE", 110)
    content = pdf.build_shipping_confirmation_pdf([order]).getvalue()
    printed = _content_streams(content)
    cut_rectangles = print_geometry["cards"]
    assert len(cut_rectangles) >= 3
    assert printed.count(b"ORDER-LARGE)") == len(cut_rectangles)
    assert printed.count(b"(JF)") == len(cut_rectangles)
    assert printed.count(b"Original No.") == len(cut_rectangles)
    for box in order["boxes"]:
        assert printed.count(f"({box['transfer_id']})".encode()) == 1
    assert all(rect[2] >= pdf.PAGE_MARGIN - 0.01 for rect in cut_rectangles)


def test_long_values_wrap_and_unassigned_agent_stays_empty(print_geometry):
    order = _order("LONG", 1)
    order["agent_name"] = ""
    order["customer_name"] = "长客户名称" * 25 + " & <Company>"
    order["boxes"][0] = {"tag": "M" * 128, "transfer_id": "T" * 256}
    content = pdf.build_shipping_confirmation_pdf([order]).getvalue()
    printed = _content_streams(content)
    assert b"(JF)" not in printed
    assert re.search(rb"\(M{10,}\)", printed)
    assert re.search(rb"\(T{10,}\)", printed)
    cut_rectangles = print_geometry["cards"]
    assert len(cut_rectangles) == 1
    assert cut_rectangles[0][2] >= pdf.PAGE_MARGIN


def test_empty_order_keeps_its_identity_in_a_mixed_batch():
    printed = _content_streams(pdf.build_shipping_confirmation_pdf([_order("EMPTY", 0), _order(2)]).getvalue())
    assert b"ORDER-EMPTY" in printed
    assert b"TRACK-2-001" in printed


def test_horizontal_cut_lines_stay_in_gaps_without_card_frames(print_geometry):
    pdf.build_shipping_confirmation_pdf([_order(index, 2) for index in range(20)])
    assert not print_geometry["frames"]
    cards = print_geometry["cards"]
    cuts = print_geometry["cuts"]
    pages = {card[0] for card in cards}
    for page in pages:
        page_cards = [card for card in cards if card[0] == page]
        page_cuts = [cut for cut in cuts if cut[0] == page]
        verticals = [cut for cut in page_cuts if cut[1] == cut[3]]
        horizontals = [cut for cut in page_cuts if cut[2] == cut[4]]
        assert not verticals
        assert len(horizontals) == len(page_cards)
        for horizontal in horizontals:
            assert horizontal[1] < pdf.PAGE_MARGIN
            assert horizontal[3] > pdf.A4[0] - pdf.PAGE_MARGIN
            for _, _, bottom, _, height in page_cards:
                assert not bottom < horizontal[2] < bottom + height


def test_export_embeds_the_larger_title_body_and_label_font_sizes():
    printed = _content_streams(pdf.build_shipping_confirmation_pdf([_order(1)]).getvalue())
    assert b"18 Tf 23 TL" in printed
    assert b"12 Tf 16 TL" in printed
    assert b"11 Tf 15 TL" in printed
    assert b"10 Tf 14 TL" in printed


def test_title_is_only_shipping_note():
    card = pdf._order_cards(_order(1), pdf._styles())[0]
    assert card.flowables[0].getPlainText() == "出货单"
    assert all("XUNDA" not in item.getPlainText() for item in card.flowables if hasattr(item, "getPlainText"))


def test_empty_export_is_rejected():
    with pytest.raises(ValueError, match="请先选择"):
        pdf.build_shipping_confirmation_pdf([])
