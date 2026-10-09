"""add excel_templates table

Revision ID: 9a8b7c6d5e4f
Revises: 8f7e6d5c4b3a
Create Date: 2026-04-28 14:00:00.000000
"""

import json
import os
import shutil
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9a8b7c6d5e4f"
down_revision: Union[str, None] = "8f7e6d5c4b3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 excel_templates 表
    op.create_table(
        "excel_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mode_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("template_type", sa.String(length=32), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("template_file", sa.String(length=256), nullable=True),
        sa.Column("single_order_only", sa.Boolean(), default=False),
        sa.Column("archive", sa.Boolean(), default=False),
        sa.Column("create_date", sa.String(length=32), nullable=True),
        sa.Column("update_date", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mode_key"),
    )

    # 种子数据：列模式模板
    now = "2026-04-28 14:00"
    column_templates = [
        {
            "mode_key": "jifei",
            "label": "极飞",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["客户单号", "转单号", "运输方式", "目的国家", "收件人姓名", "州,省", "城市", "联系地址",
                            "收件人电话", "收件人邮箱", "收件人邮编", "重量", "海关报关品名1", "出口海关编码",
                            "配货信息1", "申报价值1", "申报品数量1"],
                "reference_table": {"客户单号": "transfer_id", "运输方式": "transportation", "目的国家": "country",
                                    "收件人姓名": "receiver", "州,省": "province", "城市": "city", "联系地址": "address",
                                    "收件人电话": "receiver_phone",
                                    "收件人邮箱": "mail", "收件人邮编": "zip_code", "重量": "weight",
                                    "海关报关品名1": "real_en_name",
                                    "申报价值1": "price", "申报品数量1": "count", "出口海关编码": "post_code",
                                    "转单号": "waybill_id"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "tongcang",
            "label": "统仓",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["客户单号", "转单号", "运输方式", "目的国家", "寄件人公司名", "寄件人姓名", "寄件人地址",
                            "寄件人电话", "寄件人邮编", "寄件人传真", "收件人公司名", "收件人姓名", "州,省",
                            "城市", "联系地址", "收件人电话", "收件人邮箱", "收件人邮编", "收件人传真", "订单备注", "重量",
                            "海关报关品名1", "配货信息1", "申报价值1", "申报品数量1", "配货备注1", "海关报关品名2",
                            "配货信息2", "申报价值2", "申报品数量2", "配货备注2", "海关报关品名3", "配货信息3", "申报价值3",
                            "申报品数量3", "配货备注3", "海关报关品名4", "配货信息4", "申报价值4", "申报品数量4",
                            "配货备注4", "海关报关品名5", "配货信息5", "申报价值5", "申报品数量5", "配货备注5"],
                "reference_table": {"客户单号": "transfer_id", "运输方式": "transportation", "目的国家": "country",
                                    "收件人姓名": "receiver", "州,省": "province", "城市": "city", "联系地址": "address",
                                    "收件人电话": "receiver_phone",
                                    "收件人邮箱": "mail", "收件人邮编": "zip_code", "收件人传真": "", "订单备注": "",
                                    "重量": "weight", "海关报关品名1": "real_en_name",
                                    "申报价值1": "price", "申报品数量1": "count"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "huanshitong",
            "label": "环世通",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["订单号码", "转单号码", "指定路线", "目的国家", "寄件公司", "寄件人", "寄件电话", "寄件地址",
                            "寄件国家", "寄件州/省", "寄件城市", "寄件邮编", "寄件邮箱", "收件公司",
                            "收件人", "收件州/省", "收件城市", "收件地址", "收件电话", "收件邮箱", "收件邮编", "备注", "件数",
                            "重量", "申报币别", "英文品名1", "中文品名1", "数量1", "单价1", "海关编码1",
                            "英文品名2", "中文品名2", "数量2", "单价2", "海关编码2", "英文品名3", "中文品名3", "数量3", "单价3",
                            "海关编码3", "英文品名4", "中文品名4", "数量4", "单价4", "海关编码4", "英文品名5",
                            "中文品名5", "数量5", "单价5", "海关编码5", "税号类型", "税号/IOSS", "收件EORI"],
                "reference_table": {"订单号码": "transfer_id", "指定路线": "transportation", "目的国家": "country",
                                    "收件人": "receiver", "收件州/省": "province", "收件城市": "city", "收件地址": "address",
                                    "收件电话": "receiver_phone",
                                    "收件邮箱": "mail", "收件邮编": "zip_code", "备注": "", " 重量": "weight",
                                    "中文品名1": "cn_name", "英文品名1": "real_en_name"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "tongcangups",
            "label": "统仓(UPS)",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["客户单号", "转单号", "运输方式", "目的国家", "收件人姓名", "州,省", "城市", "联系地址",
                            "收件人电话", "收件人邮箱", "收件人邮编", "重量", "长", "宽", "高", "海关报关品名1",
                            "配货信息1", "申报价值1", "申报品数量1"],
                "reference_table": {"客户单号": "transfer_id", "运输方式": "transportation", "目的国家": "country",
                                    "收件人姓名": "receiver", "州,省": "province", "城市": "city", "联系地址": "address",
                                    "收件人电话": "receiver_phone",
                                    "收件人邮箱": "mail", "收件人邮编": "zip_code", "重量": "weight",
                                    "海关报关品名1": "real_en_name",
                                    "申报价值1": "price", "申报品数量1": "count", "配货信息1": "cn_name",
                                    "转单号": "waybill_id"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "yaxuan",
            "label": "亚轩",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["客户单号", "销售产品", "目的国家", "收件人", "收件省/州", "收件城市", "收件邮编", "收件地址",
                            "收件电话", "重量", "件数", "类型", "长", "宽", "高", "英文品名1", "中文品名1", "申报数量1",
                            "申报单价1", "申报总价值1"],
                "reference_table": {"客户单号": "transfer_id", "销售产品": "transportation", "目的国家": "country",
                                    "收件人": "receiver", "收件省/州": "province", "收件城市": "city", "收件邮编": "zip_code",
                                    "收件地址": "address", "收件电话": "receiver_phone", "重量": "weight",
                                    "英文品名1": "real_en_name", "申报数量1": "count", "申报单价1": "price"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "jinlong_kuaidi",
            "label": "金龙快递",
            "template_type": "column",
            "single_order_only": False,
            "config": json.dumps({
                "columns": ["运输渠道", "原单号", "运单号码", "目的地", "件数", "重量", "货物类型", "包装类型",
                            "主要货物中文品名", "备注", "寄件人", "寄件公司",
                            "寄件地址", "寄件电话", "收件人", "收件公司", "收件地址", "收件城市", "收件洲/省", "收件邮编",
                            "收件电话", "英文品名1", "中文品名1",
                            "材质1", "用途1", "海关编码1", "数量1", "单价1", "币别1", "英文品名2", "中文品名2", "材质2",
                            "用途2", "海关编码2", "数量2", "单价2",
                            "币别2"],
                "reference_table": {"原单号": "transfer_id", "运输渠道": "transportation", "目的地": "country",
                                    "收件人": "receiver", "收件省/州": "province", "收件城市": "city", "收件邮编": "zip_code",
                                    "收件地址": "address", "收件电话": "receiver_phone", "重量": "weight",
                                    "主要货物中文品名": "cn_name", "中文品名1": "cn_name", "英文品名1": "real_en_name",
                                    "数量1": "count", "单价1": "price"},
            }),
            "template_file": None,
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
    ]

    # 种子数据：单元格模式模板
    cell_templates = [
        {
            "mode_key": "jinfeiqi",
            "label": "金飞",
            "template_type": "cell",
            "single_order_only": True,
            "config": json.dumps({
                "cell_mappings": [
                    {"cell": "B3", "field": "order_id"},
                    {"cell": "H3", "field": "receiver"},
                    {"cell": "H5", "field": "country"},
                    {"cell": "O5", "field": "zip_code"},
                    {"cell": "H6", "field": "address"},
                    {"cell": "H7", "field": "city"},
                    {"cell": "F7", "field": "province"},
                    {"cell": "H8", "field": "receiver_phone"},
                ],
            }),
            "template_file": "jinfeiqi_template.xlsx",
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "jinlong",
            "label": "金龙",
            "template_type": "cell",
            "single_order_only": True,
            "config": json.dumps({
                "cell_mappings": [
                    {"cell": "C9", "field": "order_id"},
                    {"cell": "C7", "field": "receiver"},
                    {"cell": "C4", "field": "country"},
                    {"cell": "C6", "field": "zip_code"},
                    {"cell": "C3", "field": "address"},
                    {"cell": "C5", "field": "city"},
                    {"cell": "C8", "field": "receiver_phone"},
                ],
            }),
            "template_file": "jinlong_template.xlsx",
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "xinghang",
            "label": "星航",
            "template_type": "cell",
            "single_order_only": True,
            "config": json.dumps({
                "cell_mappings": [
                    {"cell": "B1", "field": "order_id"},
                    {"cell": "B6", "field": "country"},
                    {"cell": "B10", "field": "receiver"},
                    {"cell": "B11", "field": "receiver_phone"},
                    {"cell": "B12", "field": "zip_code"},
                    {"cell": "B13", "field": "province"},
                    {"cell": "D13", "field": "mail"},
                    {"cell": "B14", "field": "city"},
                    {"cell": "B15", "field": "address"},
                ],
            }),
            "template_file": "xinghang_template.xlsx",
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
        {
            "mode_key": "WE",
            "label": "亚轩(WE)",
            "template_type": "cell",
            "single_order_only": True,
            "config": json.dumps({
                "cell_mappings": [
                    {"cell": "C2", "field": "order_id"},
                    {"cell": "F5", "field": "receiver"},
                    {"cell": "F6", "field": "address"},
                    {"cell": "F7", "field": "receiver_phone"},
                    {"cell": "F8", "field": "zip_code"},
                ],
            }),
            "template_file": "WE_template.xlsx",
            "archive": False,
            "create_date": now,
            "update_date": now,
        },
    ]

    excel_templates_table = sa.table(
        "excel_templates",
        sa.column("mode_key", sa.String(length=64)),
        sa.column("label", sa.String(length=128)),
        sa.column("template_type", sa.String(length=32)),
        sa.column("single_order_only", sa.Boolean()),
        sa.column("config", sa.Text()),
        sa.column("template_file", sa.String(length=256)),
        sa.column("archive", sa.Boolean()),
        sa.column("create_date", sa.String(length=32)),
        sa.column("update_date", sa.String(length=32)),
    )

    op.bulk_insert(
        excel_templates_table,
        column_templates + cell_templates,
    )

    # 复制单元格模式所需的模板文件到 uploads 目录
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(base_dir, "static")
    dst_dir = os.path.join(base_dir, "uploads", "excel_templates")
    os.makedirs(dst_dir, exist_ok=True)

    for fname in ["jinfeiqi_template.xlsx", "jinlong_template.xlsx",
                  "xinghang_template.xlsx", "WE_template.xlsx"]:
        src = os.path.join(src_dir, fname)
        dst = os.path.join(dst_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)


def downgrade() -> None:
    op.drop_table("excel_templates")
