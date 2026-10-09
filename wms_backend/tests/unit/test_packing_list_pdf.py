"""装箱单 PDF 内容测试。"""

from reportlab.platypus import Table

from utils.packing_list_pdf import _build_packing_list_story


def test_packing_list_pdf_total_row_sums_printed_piece_counts():
    detail = {
        "list_number": "PL-001",
        "customer_name": "客户A",
        "boxes": [
            {
                "box_number": "1",
                "weight": 2.1,
                "piece_count": 99,
                "item_details": [
                    {"item_name": "衣服", "piece_count": 2},
                    {"item_name": "鞋", "piece_count": 3},
                ],
            },
            {
                "box_number": "2",
                "weight": 1,
                "item_name": "帽子",
                "piece_count": 4,
            },
        ],
    }

    story = _build_packing_list_story(detail)
    packing_table = next(item for item in reversed(story) if isinstance(item, Table))

    assert packing_table._cellvalues[-1] == [
        "总计 / TOTAL",
        "4",
        "件数合计 / Total Qty: 9",
        "",
    ]
