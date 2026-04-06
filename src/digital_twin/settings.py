"""Centralized environment parsing (cached) for predictable configuration.

This intentionally stays lightweight: it avoids import-time snapshots in other modules,
while keeping configuration discoverable and testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    cors_allowed_origins: str

    gcs_sessions_bucket: str
    gcs_sessions_prefix: str

    rate_limit_requests_per_minute: int

    gcp_region: str
    rag_corpus_resource: str

    gemini_model: str
    gemini_location: str
    max_output_tokens: int

    resume_bot_digest_email_to: str
    resume_bot_digest_idle_minutes: int
    resume_bot_digest_timezone: str

    gmail_delegated_user: str
    gmail_service_account_json: str
    gmail_service_account_key_file: str


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    rpm = _env_int("RATE_LIMIT_REQUESTS_PER_MINUTE", 30)
    rpm = max(1, rpm)

    idle = _env_int("RESUME_BOT_DIGEST_IDLE_MINUTES", 60)
    idle = max(1, idle)

    max_tokens = _env_int("MAX_OUTPUT_TOKENS", 2048)
    max_tokens = max(1, max_tokens)

    return Settings(
        cors_allowed_origins=_env("CORS_ALLOWED_ORIGINS", ""),
        gcs_sessions_bucket=_env("GCS_SESSIONS_BUCKET", ""),
        gcs_sessions_prefix=_env("GCS_SESSIONS_PREFIX", "sessions").strip("/"),
        rate_limit_requests_per_minute=rpm,
        gcp_region=_env("GCP_REGION", "us-central1") or "us-central1",
        rag_corpus_resource=_env("RAG_CORPUS_RESOURCE", ""),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash",
        # Vertex publisher models are not always available in every region. Many preview models are
        # served from the global location even when your app runs regionally.
        gemini_location=_env("GEMINI_LOCATION", ""),
        max_output_tokens=max_tokens,
        resume_bot_digest_email_to=_env("RESUME_BOT_DIGEST_EMAIL_TO", ""),
        resume_bot_digest_idle_minutes=idle,
        resume_bot_digest_timezone=_env(
            "RESUME_BOT_DIGEST_TIMEZONE", "America/Los_Angeles"
        )
        or "America/Los_Angeles",
        gmail_delegated_user=_env("GMAIL_DELEGATED_USER", ""),
        gmail_service_account_json=_env("GMAIL_SERVICE_ACCOUNT_JSON", ""),
        gmail_service_account_key_file=_env("GMAIL_SERVICE_ACCOUNT_KEY_FILE", ""),
    )


def reset_settings_cache() -> None:
    """For tests: force re-read of environment variables."""
    get_settings.cache_clear()

