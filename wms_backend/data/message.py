"""Recipient-owned inbox entries shared by all business services."""

from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from data.database import Base


class MessageTable(Base):
    __tablename__ = "inbox_messages"
    __table_args__ = (
        UniqueConstraint("recipient_id", "event_key", name="uq_inbox_recipient_event"),
        Index("ix_inbox_recipient_created", "recipient_id", "created_at", "uid"),
        Index("ix_inbox_recipient_read", "recipient_id", "read_at"),
    )

    uid = Column(String(32), primary_key=True)
    recipient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(64), nullable=False)
    source_name = Column(String(128), nullable=False)
    action_path = Column(String(1024))
    business_type = Column(String(64))
    business_id = Column(String(128))
    event_key = Column(String(128))
    created_at = Column(String(32), nullable=False)
    read_at = Column(String(32))

    def to_dict(self):
        return {
            "uid": self.uid,
            "recipient_id": self.recipient_id,
            "title": self.title,
            "body": self.body,
            "category": self.category,
            "source_name": self.source_name,
            "action_path": self.action_path,
            "business_type": self.business_type,
            "business_id": self.business_id,
            "created_at": self.created_at,
            "read_at": self.read_at,
            "is_read": self.read_at is not None,
        }
