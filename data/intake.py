"""Paper intake stays outside inventory until its uploader checks and completes it."""
from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import deferred, relationship

from data.database import Base


class IntakeTable(Base):
    __tablename__ = "paper_intakes"

    uid = Column(String(32), primary_key=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    submitted_by_name = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    operation_at = Column(String(32))
    mark_hint = Column(String(64), nullable=False, default="")
    note = Column(String(512), nullable=False, default="")
    status = Column(String(16), nullable=False, default="pending", index=True)
    draft_json = Column(Text, nullable=False, default='{"mark":"","boxes":[]}')
    version = Column(Integer, nullable=False, default=1)
    confirmed_by = Column(Integer, ForeignKey("users.id"))
    confirmed_at = Column(String(32))
    packing_list_uid = Column(String(32), ForeignKey("packing_lists.uid"), unique=True)
    recognition_status = Column(String(24), nullable=False, default="idle")
    recognition_error = Column(String(512))
    recognition_result_json = Column(Text)
    recognition_started_at = Column(String(32))
    recognition_job_uid = Column(String(32))
    photos = relationship("IntakePhotoTable", cascade="all, delete-orphan", order_by="IntakePhotoTable.position")

    # Updates and confirmation also compare versions on databases without row locks.
    __mapper_args__ = {"version_id_col": version}


class IntakePhotoTable(Base):
    __tablename__ = "paper_intake_photos"

    uid = Column(String(32), primary_key=True)
    intake_uid = Column(String(32), ForeignKey("paper_intakes.uid"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    filename = Column(String(256), nullable=False)
    mime_type = Column(String(64), nullable=False)
    data = deferred(Column(LargeBinary(length=16777216), nullable=False))
