from __future__ import annotations

import time

import pytest
from fastapi import Response
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
