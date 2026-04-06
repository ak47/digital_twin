"""Persist chat sessions as JSON in GCS (or in-memory when bucket unset)."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from digital_twin.settings import get_settings
from digital_twin.time_utils import utc_now_iso

logger = logging.getLogger(__name__)

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
    prefix = get_settings().gcs_sessions_prefix.strip().strip("/")
    return f"{prefix}/{session_id}.json"


def load_messages(session_id: str) -> list[dict[str, Any]]:
    bucket_name = get_settings().gcs_sessions_bucket
    if not bucket_name:
        return [dict(m) for m in _memory.get(session_id, [])]

    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(_blob_path(session_id))
        if not blob.exists():
            return []
        data = json.loads(blob.download_as_text(encoding="utf-8"))
        raw = data.get("messages")
        if isinstance(raw, list):
            return [dict(m) for m in raw]
        return []
    except Exception as e:
        logger.exception("GCS load failed for session %s: %s", session_id, e)
        return []


def save_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    bucket_name = get_settings().gcs_sessions_bucket
    if not bucket_name:
        _memory[session_id] = [dict(m) for m in messages]
        return

    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(bucket_name).blob(_blob_path(session_id))
        doc: dict[str, Any] = {}
        if blob.exists():
            try:
                loaded = json.loads(blob.download_as_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    doc.update(loaded)
            except Exception:
                doc = {}

        doc["messages"] = [dict(m) for m in messages]
        doc["last_activity_at"] = utc_now_iso()
        sent = doc.get("idle_digest_sent_at")
        if sent is not None and not isinstance(sent, str):
            doc["idle_digest_sent_at"] = None
        elif "idle_digest_sent_at" not in doc:
            doc["idle_digest_sent_at"] = None

        blob.upload_from_string(
            json.dumps(doc, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.exception("GCS save failed for session %s: %s", session_id, e)
        raise
