from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response
from itsdangerous import URLSafeTimedSerializer

from digital_twin import admin_auth
from digital_twin.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-key-for-admin")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "owner@example.com,other@example.com")
    monkeypatch.setenv("ADMIN_SESSION_MAX_AGE_SECONDS", "7200")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_allowlist_pass_and_fail() -> None:
    assert admin_auth.is_email_allowlisted("owner@example.com") is True
    assert admin_auth.is_email_allowlisted("stranger@example.com") is False


def test_session_cookie_round_trip() -> None:
    response = Response()
    admin_auth.set_session_cookie(response, "owner@example.com")
    token = response.headers.get("set-cookie", "")
    assert "dt_admin=" in token
    cookie_val = token.split("dt_admin=")[1].split(";")[0]
    session = admin_auth.load_session(cookie_val)
    assert session is not None
    assert session.email == "owner@example.com"


def test_session_expires_after_max_age(monkeypatch) -> None:
    monkeypatch.setattr(admin_auth, "session_max_age", lambda: 1)
    ser = URLSafeTimedSerializer("test-secret-key-for-admin", salt="digital-twin-admin")
    token = ser.dumps({"email": "owner@example.com"})
    time.sleep(2)
    assert admin_auth.load_session(token) is None


def test_non_allowlisted_email_in_token_rejected() -> None:
    ser = URLSafeTimedSerializer("test-secret-key-for-admin", salt="digital-twin-admin")
    token = ser.dumps({"email": "stranger@example.com"})
    assert admin_auth.load_session(token) is None


def test_oauth_callback_authorization_response_uses_configured_https_uri(monkeypatch) -> None:
    monkeypatch.setenv(
        "ADMIN_OAUTH_REDIRECT_URI",
        "https://digital-twin.example/admin/auth/google/callback",
    )
    reset_settings_cache()
    request = MagicMock()
    request.url.query = "state=abc&code=xyz"
    assert (
        admin_auth.oauth_callback_authorization_response(request)
        == "https://digital-twin.example/admin/auth/google/callback?state=abc&code=xyz"
    )


def test_oauth_pending_cookie_round_trip() -> None:
    response = Response()
    admin_auth.set_oauth_pending_cookie(
        response,
        state="oauth-state-123",
        code_verifier="pkce-verifier-456",
    )
    cookie_val = response.headers.get("set-cookie", "")
    assert "dt_admin_oauth=" in cookie_val
    token = cookie_val.split("dt_admin_oauth=")[1].split(";")[0]
    assert admin_auth.load_oauth_pending("oauth-state-123", token) == "pkce-verifier-456"


def test_oauth_pending_rejects_state_mismatch() -> None:
    response = Response()
    admin_auth.set_oauth_pending_cookie(
        response,
        state="expected-state",
        code_verifier="pkce-verifier",
    )
    token = response.headers.get("set-cookie", "").split("dt_admin_oauth=")[1].split(";")[0]
    with pytest.raises(HTTPException) as exc:
        admin_auth.load_oauth_pending("wrong-state", token)
    assert exc.value.status_code == 400
