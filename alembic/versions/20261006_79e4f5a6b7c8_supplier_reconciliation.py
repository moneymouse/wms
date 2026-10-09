"""Supplier reconciliation source files, exceptions and payable draft links.

Revision ID: 79e4f5a6b7c8
Revises: 68d3e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT

revision = "79e4f5a6b7c8"
down_revision = "68d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    json_text = sa.Text().with_variant(LONGTEXT(), "mysql")
    op.create_table("supplier_reconciliation_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(40), nullable=False, unique=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("finance_vendors.id"), nullable=False),
        sa.Column("vendor_name", sa.String(256), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_bytes", sa.LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("passed_rows", sa.Integer(), nullable=False),
        sa.Column("exception_rows", sa.Integer(), nullable=False),
        sa.Column("passed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_valid_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("vendor_id", "period", "file_hash", name="uq_supplier_reconciliation_file"))
    op.create_index("ix_supplier_reconciliation_vendor_period", "supplier_reconciliation_batches", ["vendor_id", "period"])
    op.create_table("supplier_reconciliation_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("supplier_reconciliation_batches.id"), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("raw_json", json_text, nullable=False),
        sa.Column("original_number", sa.String(256), nullable=False),
        sa.Column("waybill_number", sa.String(256), nullable=False),
        sa.Column("weight", sa.Numeric(18, 3)),
        sa.Column("final_fee", sa.Numeric(18, 2)),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parse_issues_json", json_text, nullable=False),
        sa.Column("issues_json", json_text, nullable=False),
        sa.Column("fingerprint", sa.String(64)),
        sa.Column("cargo_uid", sa.String(32)),
        sa.Column("order_uid", sa.String(32)),
        sa.Column("order_number", sa.String(128)),
        sa.Column("system_weight", sa.Numeric(18, 3)),
        sa.Column("system_waybill", sa.String(256)),
        sa.Column("weight_difference", sa.Numeric(18, 3)),
        sa.Column("match_snapshot_json", json_text),
        sa.Column("finance_document_id", sa.Integer(), sa.ForeignKey("finance_documents.id")),
        sa.Column("finance_document_line_id", sa.Integer(), sa.ForeignKey("finance_document_lines.id"), unique=True),
        sa.UniqueConstraint("batch_id", "source_row", name="uq_supplier_reconciliation_source_row"))
    op.create_index("ix_supplier_reconciliation_fingerprint", "supplier_reconciliation_rows", ["fingerprint"])
    op.create_index("ix_supplier_reconciliation_batch_status", "supplier_reconciliation_rows", ["batch_id", "status"])
    op.create_index("ix_supplier_reconciliation_document", "supplier_reconciliation_rows", ["finance_document_id"])
    op.create_index("ix_supplier_reconciliation_cargo", "supplier_reconciliation_rows", ["cargo_uid", "system_waybill"])


def downgrade():
    op.drop_index("ix_supplier_reconciliation_cargo", table_name="supplier_reconciliation_rows")
    op.drop_index("ix_supplier_reconciliation_document", table_name="supplier_reconciliation_rows")
    op.drop_index("ix_supplier_reconciliation_batch_status", table_name="supplier_reconciliation_rows")
    op.drop_index("ix_supplier_reconciliation_fingerprint", table_name="supplier_reconciliation_rows")
    op.drop_table("supplier_reconciliation_rows")
    op.drop_index("ix_supplier_reconciliation_vendor_period", table_name="supplier_reconciliation_batches")
    op.drop_table("supplier_reconciliation_batches")
