from __future__ import annotations

import pytest
from fastapi import HTTPException
from itsdangerous import URLSafeTimedSerializer
from starlette.responses import Response

from digital_twin import admin_auth, family_auth
from digital_twin.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-key-for-admin")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "admin@example.com")
    monkeypatch.setenv("FAMILY_ALLOWED_EMAILS", "fam@example.com,Aunt@Example.COM")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _family_cookie(email: str) -> str:
    response = Response()
    family_auth.set_session_cookie(response, email)
    header = response.headers.get("set-cookie", "")
    assert f"{family_auth.COOKIE_NAME}=" in header
    return header.split(f"{family_auth.COOKIE_NAME}=")[1].split(";")[0]


class TestAllowlistMatrix:
    def test_family_email_allowed(self) -> None:
        assert family_auth.is_family_allowed("fam@example.com") is True

    def test_admin_email_implicitly_allowed(self) -> None:
        assert family_auth.is_family_allowed("admin@example.com") is True

    def test_stranger_denied(self) -> None:
        assert family_auth.is_family_allowed("stranger@example.com") is False

    def test_match_is_case_insensitive(self) -> None:
        assert family_auth.is_family_allowed("AUNT@example.com") is True
        assert family_auth.is_family_allowed("  Fam@Example.com ") is True

    def test_empty_family_list_only_admins_pass(self, monkeypatch) -> None:
        monkeypatch.setenv("FAMILY_ALLOWED_EMAILS", "")
        reset_settings_cache()
        assert family_auth.is_family_allowed("fam@example.com") is False
        assert family_auth.is_family_allowed("admin@example.com") is True


class TestFamilySessionCookie:
    def test_cookie_round_trip(self) -> None:
        token = _family_cookie("fam@example.com")
        session = family_auth.load_session(token)
        assert session is not None
        assert session.email == "fam@example.com"
        assert session.allowed is True

    def test_session_valid_for_non_allowlisted_email(self) -> None:
        # The callback sets the cookie even for denied emails so /family/me
        # can report the denied state; allowlist is enforced per request.
        token = _family_cookie("stranger@example.com")
        session = family_auth.load_session(token)
        assert session is not None
        assert session.allowed is False

    def test_require_family_allowed_rejects_denied_session(self) -> None:
        token = _family_cookie("stranger@example.com")
        session = family_auth.load_session(token)
        with pytest.raises(HTTPException) as exc:
            family_auth.ensure_allowed(session)
        assert exc.value.status_code == 403


class TestCookieSeparation:
    """Family and admin sessions must be cryptographically non-interchangeable."""

    def test_family_token_rejected_by_admin_loader(self) -> None:
        token = _family_cookie("admin@example.com")
        assert admin_auth.load_session(token) is None

    def test_admin_token_rejected_by_family_loader(self) -> None:
        response = Response()
        admin_auth.set_session_cookie(response, "admin@example.com")
        token = response.headers.get("set-cookie", "").split("dt_admin=")[1].split(";")[0]
        assert family_auth.load_session(token) is None

    def test_salts_differ_even_with_shared_secret(self) -> None:
        admin_ser = URLSafeTimedSerializer("test-secret-key-for-admin", salt="digital-twin-admin")
        forged = admin_ser.dumps({"email": "admin@example.com"})
        assert family_auth.load_session(forged) is None

    def test_cookie_names_differ(self) -> None:
        assert family_auth.COOKIE_NAME != admin_auth.COOKIE_NAME
        assert family_auth.COOKIE_NAME == "dt_family"
