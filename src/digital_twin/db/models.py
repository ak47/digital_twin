"""SQLAlchemy ORM models for conversation persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_VISITOR_NAME = "Rando"


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    visitor_name: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_VISITOR_NAME)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    needs_attention: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_escalation_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_conversation_id", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Any | None] = mapped_column(JSON)
    needs_attention_row: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_by_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnerSettingsRow(Base):
    __tablename__ = "owner_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    additional_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArchiveMessageRow(Base):
    __tablename__ = "archive_messages"
    __table_args__ = (
        Index("idx_archive_messages_archived_at", "archived_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Any | None] = mapped_column(JSON)
    needs_attention_row: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_by_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
