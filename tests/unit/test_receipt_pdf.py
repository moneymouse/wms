from utils.receipt_pdf import build_receipt_pdf
from utils.quote_pdf import build_quote_pdf


def _receipt(status, item_count=3):
    items = [
        {
            "order_id": f"ERP-{index:04d}",
            "receivable_snapshot": 134.57,
            "received_before": 80,
            "amount": 10,
            "remaining_after": 44.57,
        }
        for index in range(item_count)
    ]
    return {
        "receipt_no": "RCPT-20260827-000001",
        "customer_name": "测试客户 Test Customer",
        "receipt_date": "2026-08-27",
        "payment_method": "bank_transfer",
        "status": status,
        "creator_name": "业务员 Salesperson",
        "reviewer_name": "财务 Finance" if status != "pending" else None,
        "review_date": "2026-08-27 16:00:00" if status != "pending" else None,
        "review_remark": "审核意见 Review notes" if status != "pending" else None,
        "remark": "双语长备注 Long bilingual remarks for wrapping verification",
        "items": items,
        "total_amount": 10 * item_count,
    }


def test_all_receipt_states_generate_portable_embedded_font_pdf():
    for status in ("pending", "approved", "rejected"):
        content = build_receipt_pdf(_receipt(status)).getvalue()
        assert content.startswith(b"%PDF-")
        assert len(content) > 10000
        assert b"DroidSansFallback" in content
        assert b"STSong" not in content


def test_receipt_pdf_repeats_table_header_across_pages():
    content = build_receipt_pdf(_receipt("pending", item_count=34)).getvalue()
    assert b"/Count 2" in content


def test_quote_pdf_uses_same_portable_embedded_font():
    content = build_quote_pdf(
        {
            "order_id": "ERP-001",
            "customer_name": "测试客户",
            "receiver": "收件人",
            "country": "中国",
            "city": "深圳",
            "address": "测试地址",
        },
        {
            "version_no": 1,
            "transportation_name": "测试渠道",
            "weight_snapshot": 10.5,
            "unit_price": 12.34,
            "surcharge": 5,
            "receivable_amount": 134.57,
            "quoter_name": "业务员",
            "create_date": "2026-08-27 10:00:00",
            "effective_date": "2026-08-27 10:00:00",
        },
    ).getvalue()
    assert content.startswith(b"%PDF-")
    assert b"DroidSansFallback" in content
    assert b"STSong" not in content
