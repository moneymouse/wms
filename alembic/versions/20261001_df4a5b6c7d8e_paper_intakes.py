"""Persist paper intake drafts and protected source photos.

Revision ID: df4a5b6c7d8e
Revises: ce3f4a5b6c7d
"""
from alembic import op
import sqlalchemy as sa

revision = "df4a5b6c7d8e"
down_revision = "ce3f4a5b6c7d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paper_intakes",
        sa.Column("uid", sa.String(32), primary_key=True),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_by_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("operation_at", sa.String(32)),
        sa.Column("mark_hint", sa.String(64), nullable=False),
        sa.Column("note", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("draft_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.String(32)),
        sa.Column("packing_list_uid", sa.String(32), sa.ForeignKey("packing_lists.uid"), unique=True),
        sa.Column("recognition_status", sa.String(24), nullable=False),
        sa.Column("recognition_error", sa.String(512)),
        sa.Column("recognition_result_json", sa.Text()),
        sa.Column("recognition_started_at", sa.String(32)),
        sa.Column("recognition_job_uid", sa.String(32)),
    )
    op.create_index("ix_paper_intakes_submitted_by", "paper_intakes", ["submitted_by"])
    op.create_index("ix_paper_intakes_status", "paper_intakes", ["status"])
    op.create_table(
        "paper_intake_photos",
        sa.Column("uid", sa.String(32), primary_key=True),
        sa.Column("intake_uid", sa.String(32), sa.ForeignKey("paper_intakes.uid"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(length=16777216), nullable=False),
    )
    op.create_index("ix_paper_intake_photos_intake_uid", "paper_intake_photos", ["intake_uid"])


def downgrade():
    op.drop_table("paper_intake_photos")
    op.drop_table("paper_intakes")
