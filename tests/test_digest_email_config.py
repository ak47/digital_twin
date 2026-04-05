"""Digest email provider selection (Gmail only)."""

import pytest

from digital_twin import session_digest


@pytest.fixture(autouse=True)
def _digest_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "sessions-bucket")
    monkeypatch.setenv("RESUME_BOT_DIGEST_EMAIL_TO", "owner@example.com")


def test_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GMAIL_DELEGATED_USER", raising=False)
    monkeypatch.delenv("GMAIL_SERVICE_ACCOUNT_JSON", raising=False)
    assert session_digest.digest_email_provider() == ""
    assert not session_digest.digest_feature_configured()


def test_gmail_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAIL_DELEGATED_USER", "resume-bot@no-ego.net")
    monkeypatch.setenv("GMAIL_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    assert session_digest.digest_email_provider() == "gmail"
    assert session_digest.digest_feature_configured()
