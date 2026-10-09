"""Durable, transaction-bound replay receipts for MCP mutations."""
import time

from sqlalchemy import Column, Integer, String, Text, UniqueConstraint

from data.database import Base


IDEMPOTENCY_CONSTRAINT = "uq_mcp_idempotency_identity"


class McpIdempotencyTable(Base):
    __tablename__ = "mcp_idempotency"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_id_hash", "tool_name", "key_hash",
            name=IDEMPOTENCY_CONSTRAINT,
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    # URL client identifiers and keys remain case-sensitive and fit MySQL indexes.
    client_id_hash = Column(String(64), nullable=False)
    tool_name = Column(String(32), nullable=False)
    key_hash = Column(String(64), nullable=False)
    arguments_hash = Column(String(64), nullable=False)
    result_json = Column(Text, nullable=True)
    created_at = Column(Integer, nullable=False, default=lambda: int(time.time()))
