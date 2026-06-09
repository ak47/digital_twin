"""PostgreSQL conversation persistence (messages, inbox, settings, archive)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from digital_twin.db import (
    DEFAULT_VISITOR_NAME,
    ArchiveMessageRow,
    Base,
    ConversationRow,
    MessageRow,
    OwnerSettingsRow,
    get_db_session,
    init_schema_for_tests,
    ping as _db_ping,
    reset_engine_cache,
)
from digital_twin.settings import get_settings
from digital_twin.time_utils import utc_now

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 20_000
MAX_INSTRUCTIONS_CHARS = 32_000
ESCALATION_MARKER = "<<ESCALATE>>"


def is_database_enabled() -> bool:
    return bool(get_settings().database_url.strip())


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def clamp_message(text_in: str) -> str:
    if len(text_in) <= MAX_MESSAGE_CHARS:
        return text_in
    note = " [...message truncated]"
    return text_in[: MAX_MESSAGE_CHARS - len(note)] + note


def format_timestamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def message_to_dict(row: MessageRow, *, visitor_name: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "conversation_id": str(row.conversation_id),
        "conversation_name": visitor_name,
        "role": row.role,
        "content": row.content,
        "tool_calls": row.tool_calls,
        "needs_attention": row.needs_attention_row,
        "read": row.read_by_owner,
        "created_at": format_timestamp(row.created_at),
    }


def legacy_message_to_dict(row: MessageRow) -> dict[str, Any]:
    role = "user" if row.role == "visitor" else "assistant" if row.role == "twin" else "owner"
    return {"role": role, "text": row.content, "id": row.id}


def ensure_conversation(
    conversation_id: str,
    *,
    visitor_name: str | None = None,
) -> uuid.UUID:
    cid = uuid.UUID(conversation_id)
    now = utc_now()
    with get_db_session() as session:
        row = session.get(ConversationRow, cid)
        if row is None:
            name = (visitor_name or "").strip() or DEFAULT_VISITOR_NAME
            row = ConversationRow(
                id=cid,
                visitor_name=name,
                last_activity_at=now,
                needs_attention=False,
                created_at=now,
            )
            session.add(row)
        elif visitor_name and visitor_name.strip() and row.visitor_name == DEFAULT_VISITOR_NAME:
            row.visitor_name = visitor_name.strip()
            row.last_activity_at = now
        else:
            row.last_activity_at = now
        session.commit()
    return cid


def insert_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    visitor_name: str | None = None,
    tool_calls: list | None = None,
    needs_attention: bool = False,
    read_by_owner: bool | None = None,
) -> dict[str, Any]:
    cid = ensure_conversation(conversation_id, visitor_name=visitor_name)
    now = utc_now()
    if read_by_owner is None:
        read_by_owner = role in ("owner", "twin")
    row = MessageRow(
        conversation_id=cid,
        role=role,
        content=content,
        tool_calls=tool_calls,
        needs_attention_row=needs_attention,
        read_by_owner=read_by_owner,
        created_at=now,
    )
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        assert conv is not None
        session.add(row)
        conv.last_activity_at = now
        if needs_attention:
            conv.needs_attention = True
        session.commit()
        session.refresh(row)
        return message_to_dict(row, visitor_name=conv.visitor_name)


def get_messages(conversation_id: str, *, after_id: int | None = None) -> list[dict[str, Any]]:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return []
        q = (
            select(MessageRow)
            .where(MessageRow.conversation_id == cid)
            .order_by(MessageRow.id.asc())
        )
        if after_id is not None:
            q = q.where(MessageRow.id > after_id)
        rows = session.scalars(q).all()
        return [message_to_dict(r, visitor_name=conv.visitor_name) for r in rows]


def load_legacy_messages(conversation_id: str) -> list[dict[str, Any]]:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return []
        rows = session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == cid)
            .order_by(MessageRow.id.asc())
        ).all()
        return [legacy_message_to_dict(r) for r in rows]


def list_conversations() -> list[dict[str, Any]]:
    with get_db_session() as session:
        convs = session.scalars(
            select(ConversationRow).order_by(ConversationRow.last_activity_at.desc())
        ).all()
        summaries: list[dict[str, Any]] = []
        for conv in convs:
            msgs = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conv.id)
                .order_by(MessageRow.id.asc())
            ).all()
            if not msgs:
                continue
            last = msgs[-1]
            unread = any(not m.read_by_owner and m.role in ("visitor", "twin") for m in msgs)
            summaries.append(
                {
                    "conversation_id": str(conv.id),
                    "conversation_name": conv.visitor_name,
                    "preview": (last.content or "")[:120],
                    "last_created_at": format_timestamp(last.created_at),
                    "last_id": last.id,
                    "message_count": len(msgs),
                    "unread": unread,
                    "needs_attention": conv.needs_attention,
                }
            )
        return summaries


def open_conversation(conversation_id: str) -> list[dict[str, Any]]:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return []
        conv.needs_attention = False
        rows = session.scalars(
            select(MessageRow).where(MessageRow.conversation_id == cid)
        ).all()
        for row in rows:
            row.read_by_owner = True
            row.needs_attention_row = False
        session.commit()
        rows = sorted(rows, key=lambda r: r.id)
        return [message_to_dict(r, visitor_name=conv.visitor_name) for r in rows]


def insert_owner_message(conversation_id: str, content: str) -> dict[str, Any]:
    return insert_message(
        conversation_id,
        "owner",
        clamp_message(content),
        read_by_owner=True,
        needs_attention=False,
    )


def resolve_conversation(conversation_id: str) -> None:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return
        conv.needs_attention = False
        rows = session.scalars(select(MessageRow).where(MessageRow.conversation_id == cid)).all()
        for row in rows:
            row.needs_attention_row = False
        session.commit()


def set_needs_attention(conversation_id: str, *, flag: bool = True) -> None:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return
        conv.needs_attention = flag
        session.commit()


def should_send_escalation_email(conversation_id: str) -> bool:
    cid = uuid.UUID(conversation_id)
    debounce_min = get_settings().escalation_email_debounce_minutes
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None or not conv.needs_attention:
            return False
        if conv.last_escalation_email_at is None:
            return True
        delta = utc_now() - _aware(conv.last_escalation_email_at)
        return delta >= timedelta(minutes=debounce_min)


def mark_escalation_email_sent(conversation_id: str) -> None:
    cid = uuid.UUID(conversation_id)
    with get_db_session() as session:
        conv = session.get(ConversationRow, cid)
        if conv is None:
            return
        conv.last_escalation_email_at = utc_now()
        session.commit()


def get_additional_instructions() -> tuple[str, datetime | None]:
    with get_db_session() as session:
        row = session.get(OwnerSettingsRow, 1)
        if row is None:
            return "", None
        return row.additional_instructions, row.updated_at


def save_additional_instructions(content: str) -> tuple[str, str]:
    if len(content) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(f"Instructions exceed {MAX_INSTRUCTIONS_CHARS} characters")
    now = utc_now()
    with get_db_session() as session:
        row = session.get(OwnerSettingsRow, 1)
        if row is None:
            row = OwnerSettingsRow(id=1, additional_instructions=content, updated_at=now)
            session.add(row)
        else:
            row.additional_instructions = content
            row.updated_at = now
        session.commit()
        return content, format_timestamp(now)


def count_messages_in_last_minute(conversation_id: str) -> int:
    cid = uuid.UUID(conversation_id)
    since = utc_now() - timedelta(seconds=60)
    with get_db_session() as session:
        return session.scalar(
            select(func.count())
            .select_from(MessageRow)
            .where(
                MessageRow.conversation_id == cid,
                MessageRow.role == "visitor",
                MessageRow.created_at >= since,
            )
        ) or 0


def export_messages_jsonl() -> str:
    lines: list[str] = []
    with get_db_session() as session:
        rows = session.scalars(select(MessageRow).order_by(MessageRow.id.asc())).all()
        for row in rows:
            conv = session.get(ConversationRow, row.conversation_id)
            payload = message_to_dict(row, visitor_name=conv.visitor_name if conv else None)
            lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def archive_conversation(conversation_id: str) -> None:
    cid = uuid.UUID(conversation_id)
    now = utc_now()
    with get_db_session() as session:
        rows = session.scalars(
            select(MessageRow).where(MessageRow.conversation_id == cid).order_by(MessageRow.id)
        ).all()
        for row in rows:
            session.add(
                ArchiveMessageRow(
                    id=row.id,
                    conversation_id=row.conversation_id,
                    role=row.role,
                    content=row.content,
                    tool_calls=row.tool_calls,
                    needs_attention_row=row.needs_attention_row,
                    read_by_owner=row.read_by_owner,
                    created_at=row.created_at,
                    archived_at=now,
                )
            )
            session.delete(row)
        conv = session.get(ConversationRow, cid)
        if conv is not None:
            session.delete(conv)
        session.commit()


def restore_conversation(conversation_id: str) -> None:
    cid = uuid.UUID(conversation_id)
    now = utc_now()
    with get_db_session() as session:
        archived = session.scalars(
            select(ArchiveMessageRow)
            .where(ArchiveMessageRow.conversation_id == cid)
            .order_by(ArchiveMessageRow.id)
        ).all()
        if not archived:
            return
        conv = session.get(ConversationRow, cid)
        if conv is None:
            conv = ConversationRow(
                id=cid,
                visitor_name=DEFAULT_VISITOR_NAME,
                last_activity_at=now,
                needs_attention=False,
                created_at=now,
            )
            session.add(conv)
        for a in archived:
            session.add(
                MessageRow(
                    id=a.id,
                    conversation_id=a.conversation_id,
                    role=a.role,
                    content=a.content,
                    tool_calls=a.tool_calls,
                    needs_attention_row=a.needs_attention_row,
                    read_by_owner=a.read_by_owner,
                    created_at=a.created_at,
                )
            )
            session.delete(a)
        session.commit()


def bulk_archive_idle(hours: int = 72) -> int:
    cutoff = utc_now() - timedelta(hours=hours)
    with get_db_session() as session:
        convs = session.scalars(
            select(ConversationRow).where(ConversationRow.last_activity_at < cutoff)
        ).all()
        ids = [str(c.id) for c in convs]
    for cid in ids:
        archive_conversation(cid)
    return len(ids)


def list_archived_conversations() -> list[dict[str, Any]]:
    with get_db_session() as session:
        rows = session.scalars(
            select(ArchiveMessageRow).order_by(ArchiveMessageRow.archived_at.desc())
        ).all()
        grouped: dict[uuid.UUID, list[ArchiveMessageRow]] = {}
        for row in rows:
            grouped.setdefault(row.conversation_id, []).append(row)
        summaries = []
        for cid, msgs in grouped.items():
            msgs = sorted(msgs, key=lambda m: m.id)
            last = msgs[-1]
            summaries.append(
                {
                    "conversation_id": str(cid),
                    "conversation_name": DEFAULT_VISITOR_NAME,
                    "preview": (last.content or "")[:120],
                    "last_created_at": format_timestamp(last.created_at),
                    "last_id": last.id,
                    "message_count": len(msgs),
                    "unread": False,
                    "needs_attention": False,
                    "archived": True,
                }
            )
        summaries.sort(key=lambda s: s["last_created_at"], reverse=True)
        return summaries


def strip_escalation_marker(text: str) -> tuple[str, bool]:
    if ESCALATION_MARKER in text:
        return text.replace(ESCALATION_MARKER, "").strip(), True
    return text, False


def health_check() -> bool:
    if not is_database_enabled():
        return False
    try:
        ok = _db_ping()
        if not ok:
            logger.warning("Database health check failed")
        return ok
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return False


# Backward-compatible re-exports (tests, Alembic env).
__all__ = [
    "ArchiveMessageRow",
    "Base",
    "ConversationRow",
    "DEFAULT_VISITOR_NAME",
    "MessageRow",
    "OwnerSettingsRow",
    "get_db_session",
    "init_schema_for_tests",
    "reset_engine_cache",
]
