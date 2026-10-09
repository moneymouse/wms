"""Persistent, versioned box selections for shipping confirmation printing."""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects import mysql

from data.database import Base


class ShippingConfirmationDraftTable(Base):
    __tablename__ = "shipping_confirmation_drafts"

    uid = Column(String(32), primary_key=True)
    title = Column(String(128), nullable=False)
    entries_json = Column(Text().with_variant(mysql.LONGTEXT(), "mysql"), nullable=False)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(String(32), nullable=False)
    updated_at = Column(String(32), nullable=False)
    archive = Column(Boolean, nullable=False, default=False)
