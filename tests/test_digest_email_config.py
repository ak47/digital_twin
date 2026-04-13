"""Digest email provider selection (Gmail only)."""

import pytest

from digital_twin import session_digest
from digital_twin.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _digest_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "sessions-bucket")
    monkeypatch.setenv("RESUME_BOT_DIGEST_EMAIL_TO", "owner@example.com")
    reset_settings_cache()


def test_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GMAIL_DELEGATED_USER", raising=False)
    monkeypatch.delenv("GMAIL_SERVICE_ACCOUNT_JSON", raising=False)
    reset_settings_cache()
    assert session_digest.digest_email_provider() == ""
    assert not session_digest.digest_feature_configured()


def test_gmail_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAIL_DELEGATED_USER", "resume-bot@example.com")
    monkeypatch.setenv("GMAIL_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    reset_settings_cache()
    assert session_digest.digest_email_provider() == "gmail"
    assert session_digest.digest_feature_configured()
