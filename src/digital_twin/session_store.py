"""Persist chat sessions as JSON in GCS (or in-memory when bucket unset)."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_BUCKET = os.environ.get("GCS_SESSIONS_BUCKET", "").strip()
_PREFIX = os.environ.get("GCS_SESSIONS_PREFIX", "sessions").strip().strip("/")
_memory: dict[str, list[dict[str, Any]]] = {}

_SESSION_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)


def new_session_id() -> str:
    return str(uuid.uuid4())


def validate_session_id(sid: str | None) -> str | None:
    if sid is None or not sid.strip():
        return None
    s = sid.strip()
    if _SESSION_ID_RE.match(s):
        return s
    logger.warning("Rejected malformed session id (expected uuid)")
    return None


def _blob_path(session_id: str) -> str:
    return f"{_PREFIX}/{session_id}.json"


def load_messages(session_id: str) -> list[dict[str, Any]]:
    if not _BUCKET:
        return [dict(m) for m in _memory.get(session_id, [])]

    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(_BUCKET).blob(_blob_path(session_id))
        if not blob.exists():
            return []
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        raw = data.get("messages")
        return raw if isinstance(raw, list) else []
    except Exception as e:
        logger.exception("GCS load failed for session %s: %s", session_id, e)
        return []


def save_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    body = {"messages": messages}
    if not _BUCKET:
        _memory[session_id] = [dict(m) for m in messages]
        return

    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(_BUCKET).blob(_blob_path(session_id))
        blob.upload_from_string(
            json.dumps(body, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.exception("GCS save failed for session %s: %s", session_id, e)
        raise
