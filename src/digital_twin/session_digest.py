"""After idle period, email session transcripts via Google Workspace Gmail (domain-wide delegation)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_tz_name = (
    os.environ.get("RESUME_BOT_DIGEST_TIMEZONE", "America/Los_Angeles").strip()
    or "America/Los_Angeles"
)
try:
    _DIGEST_DISPLAY_TZ = ZoneInfo(_tz_name)
except Exception:
    _DIGEST_DISPLAY_TZ = ZoneInfo("America/Los_Angeles")
    logger.warning(
        "Invalid RESUME_BOT_DIGEST_TIMEZONE=%r; using America/Los_Angeles",
        _tz_name,
    )

_SESSION_JSON = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.json$", re.I
)


def _parse_iso(s: str | None) -> datetime | None:
    if not s or not str(s).strip():
        return None
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _format_digest_timestamp(utc_dt: datetime) -> str:
    """Wall time for email subject / attachment (default US Pacific)."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(_DIGEST_DISPLAY_TZ).strftime("%Y-%m-%d %H:%M %Z")


_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _gmail_service_account_json() -> str:
    raw = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        return raw
    path = os.environ.get("GMAIL_SERVICE_ACCOUNT_KEY_FILE", "").strip()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            logger.warning("Could not read GMAIL_SERVICE_ACCOUNT_KEY_FILE: %s", e)
    return ""


def _gmail_configured() -> bool:
    return bool(
        os.environ.get("GMAIL_DELEGATED_USER", "").strip()
        and _gmail_service_account_json()
    )


def digest_email_provider() -> str:
    """'gmail' or ''."""
    if _gmail_configured():
        return "gmail"
    return ""


def digest_feature_configured() -> bool:
    return bool(
        os.environ.get("GCS_SESSIONS_BUCKET", "").strip()
        and os.environ.get("RESUME_BOT_DIGEST_EMAIL_TO", "").strip()
        and digest_email_provider() != ""
    )


def _digest_recipients() -> list[str]:
    raw = os.environ.get("RESUME_BOT_DIGEST_EMAIL_TO", "").strip()
    return [e.strip() for e in raw.split(",") if e.strip()]


def _idle_delta() -> timedelta:
    try:
        minutes = int(os.environ.get("RESUME_BOT_DIGEST_IDLE_MINUTES", "60").strip())
    except ValueError:
        minutes = 60
    return timedelta(minutes=max(1, minutes))


def _scan_interval_s() -> float:
    try:
        return float(os.environ.get("RESUME_BOT_DIGEST_SCAN_INTERVAL_SECONDS", "300").strip())
    except ValueError:
        return 300.0


def transcript_attachment_text(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    exported_at_utc: datetime | None = None,
) -> str:
    when = exported_at_utc if exported_at_utc is not None else _utc_now()
    lines = [
        f"Session: {session_id}",
        f"Exported: {_format_digest_timestamp(when)}",
        "",
    ]
    for m in messages:
        role = (m.get("role") or "?").strip()
        text = (m.get("text") or "").strip()
        lines.append(f"--- {role} ---")
        lines.append(text if text else "(empty)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def should_send_idle_digest(
    *,
    now: datetime,
    last_activity: datetime,
    idle_digest_sent_at: str | None,
    has_messages: bool,
    idle: timedelta,
) -> bool:
    if not has_messages:
        return False
    if now - last_activity < idle:
        return False
    sent = _parse_iso(idle_digest_sent_at)
    if sent is not None and sent >= last_activity:
        return False
    return True


def _send_gmail_digest(
    *,
    to_emails: list[str],
    subject: str,
    attachment_filename: str,
    attachment_text: str,
) -> None:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    delegated = os.environ["GMAIL_DELEGATED_USER"].strip()
    sa_json = _gmail_service_account_json()
    if not sa_json:
        raise RuntimeError("Gmail digest: missing service account JSON")
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=[_GMAIL_SEND_SCOPE],
    )
    creds = creds.with_subject(delegated)

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = delegated
    msg["To"] = ", ".join(to_emails)
    msg.attach(
        MIMEText(
            "Resume bot session transcript is attached.\n",
            "plain",
            "utf-8",
        )
    )
    att = MIMEBase("application", "octet-stream")
    att.set_payload(attachment_text.encode("utf-8"))
    encoders.encode_base64(att)
    att.add_header(
        "Content-Disposition",
        f'attachment; filename="{attachment_filename}"',
    )
    msg.attach(att)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _send_digest_email(
    *,
    to_emails: list[str],
    subject: str,
    attachment_filename: str,
    attachment_text: str,
) -> None:
    provider = digest_email_provider()
    if provider == "gmail":
        _send_gmail_digest(
            to_emails=to_emails,
            subject=subject,
            attachment_filename=attachment_filename,
            attachment_text=attachment_text,
        )
    else:
        raise RuntimeError("No digest email provider configured (Gmail only)")


def _session_id_from_blob_name(name: str, prefix: str) -> str | None:
    # name like "sessions/uuid.json"
    p = prefix.strip().strip("/")
    if not name.startswith(f"{p}/"):
        return None
    tail = name[len(p) + 1 :]
    if not _SESSION_JSON.match(tail):
        return None
    return tail[:-5]


def scan_and_send_idle_digests() -> None:
    if not digest_feature_configured():
        return

    bucket_name = os.environ.get("GCS_SESSIONS_BUCKET", "").strip()
    prefix = os.environ.get("GCS_SESSIONS_PREFIX", "sessions").strip().strip("/")
    to_emails = _digest_recipients()
    if not to_emails:
        return

    try:
        from google.cloud import storage
    except ImportError:
        logger.warning("google-cloud-storage not available; digest scan skipped")
        return

    idle = _idle_delta()
    now = _utc_now()
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    prefix_slash = f"{prefix}/"

    for blob in client.list_blobs(bucket_name, prefix=prefix_slash):
        if not blob.name or not blob.name.endswith(".json"):
            continue
        sid = _session_id_from_blob_name(blob.name, prefix)
        if not sid:
            continue

        try:
            blob.reload()
        except Exception as e:
            logger.warning("digest: reload %s: %s", blob.name, e)
            continue

        gen = blob.generation
        try:
            raw = json.loads(blob.download_as_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("digest: read %s: %s", blob.name, e)
            continue

        messages = raw.get("messages")
        if not isinstance(messages, list) or not messages:
            continue

        last_activity = _parse_iso(raw.get("last_activity_at"))
        if last_activity is None:
            u = blob.updated
            if u is None:
                continue
            if u.tzinfo is None:
                last_activity = u.replace(tzinfo=UTC)
            else:
                last_activity = u.astimezone(UTC)

        idle_digest_sent_at = raw.get("idle_digest_sent_at")
        if isinstance(idle_digest_sent_at, str):
            pass
        else:
            idle_digest_sent_at = None

        if not should_send_idle_digest(
            now=now,
            last_activity=last_activity,
            idle_digest_sent_at=idle_digest_sent_at,
            has_messages=True,
            idle=idle,
        ):
            continue

        send_moment = _utc_now()
        attachment = transcript_attachment_text(sid, messages, exported_at_utc=send_moment)
        subj_time = _format_digest_timestamp(send_moment)
        subject = f"resume bot chat {subj_time}"
        local = send_moment.astimezone(_DIGEST_DISPLAY_TZ)
        filename = f"resume-bot-chat-{sid[:8]}-{local:%Y%m%d-%H%M}.txt"

        try:
            _send_digest_email(
                to_emails=to_emails,
                subject=subject,
                attachment_filename=filename,
                attachment_text=attachment,
            )
        except Exception as e:
            logger.exception("digest: email failed for session %s: %s", sid, e)
            continue

        raw["idle_digest_sent_at"] = _utc_now_iso()
        raw.setdefault("messages", messages)
        raw.setdefault("last_activity_at", last_activity.isoformat().replace("+00:00", "Z"))

        try:
            blob.upload_from_string(
                json.dumps(raw, ensure_ascii=False, indent=2),
                content_type="application/json; charset=utf-8",
                if_generation_match=gen,
            )
            logger.info("digest: emailed session %s", sid)
        except Exception as e:
            logger.exception(
                "digest: GCS CAS failed for session %s (duplicate instance?): %s", sid, e
            )


async def digest_loop() -> None:
    interval = _scan_interval_s()
    while True:
        try:
            await asyncio.to_thread(scan_and_send_idle_digests)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("digest scan loop error")
        await asyncio.sleep(interval)
