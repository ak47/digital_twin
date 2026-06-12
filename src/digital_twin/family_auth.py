"""Google OAuth family authentication: separate allowlist + signed session cookie.

Modeled on admin_auth.py with the cookie name and itsdangerous salts swapped so
family and admin sessions are cryptographically non-interchangeable. Unlike the
admin loader, a family session stays valid for non-allowlisted emails — the
allowlist is enforced per request (``ensure_allowed``) so ``/family/me`` can
report the polite "not on the list" state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Cookie, HTTPException, Request, Response
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "dt_family"
OAUTH_PENDING_COOKIE = "dt_family_oauth"
OAUTH_PENDING_MAX_AGE_SECONDS = 600
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


@dataclass(frozen=True, slots=True)
class FamilySession:
    email: str
    allowed: bool


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().admin_session_secret
    if not secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(secret, salt="digital-twin-family")


def _oauth_pending_serializer() -> URLSafeTimedSerializer:
    secret = get_settings().admin_session_secret
    if not secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(secret, salt="digital-twin-family-oauth-pending")


def session_max_age() -> int:
    return get_settings().admin_session_max_age_seconds


def is_family_allowed(email: str) -> bool:
    """Family allowlist membership; admin emails are implicitly allowed."""
    normalized = email.strip().lower()
    if not normalized:
        return False
    s = get_settings()
    return normalized in s.family_allowed_emails or normalized in s.admin_allowed_emails


def oauth_callback_authorization_response(request: Request) -> str:
    """Build the OAuth callback URL for token exchange (see admin_auth)."""
    redirect_uri = get_settings().family_oauth_redirect_uri
    if not redirect_uri:
        raise RuntimeError("FAMILY_OAUTH_REDIRECT_URI is not configured")
    query = request.url.query
    if query:
        return f"{redirect_uri}?{query}"
    return redirect_uri


def oauth_flow(*, code_verifier: str | None = None, state: str | None = None) -> Flow:
    s = get_settings()
    if not s.google_oauth_client_id or not s.google_oauth_client_secret:
        raise RuntimeError("Google OAuth client credentials are not configured")
    if not s.family_oauth_redirect_uri:
        raise RuntimeError("FAMILY_OAUTH_REDIRECT_URI is not configured")
    flow_kwargs: dict[str, object] = {"redirect_uri": s.family_oauth_redirect_uri}
    if code_verifier is not None:
        flow_kwargs["code_verifier"] = code_verifier
        flow_kwargs["autogenerate_code_verifier"] = False
    if state is not None:
        flow_kwargs["state"] = state
    return Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        **flow_kwargs,
    )


def set_oauth_pending_cookie(response: Response, *, state: str, code_verifier: str) -> None:
    token = _oauth_pending_serializer().dumps(
        {"state": state, "code_verifier": code_verifier},
    )
    response.set_cookie(
        OAUTH_PENDING_COOKIE,
        token,
        max_age=OAUTH_PENDING_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def load_oauth_pending(state: str, token: str | None) -> str:
    if not token:
        raise HTTPException(status_code=400, detail="OAuth session expired; sign in again")
    try:
        data = _oauth_pending_serializer().loads(token, max_age=OAUTH_PENDING_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired) as e:
        raise HTTPException(status_code=400, detail="OAuth session expired; sign in again") from e
    stored_state = (data.get("state") or "").strip()
    code_verifier = (data.get("code_verifier") or "").strip()
    if not stored_state or not code_verifier:
        raise HTTPException(status_code=400, detail="OAuth session invalid; sign in again")
    import secrets

    if not secrets.compare_digest(stored_state, state.strip()):
        raise HTTPException(status_code=400, detail="OAuth state mismatch; sign in again")
    return code_verifier


def clear_oauth_pending_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_PENDING_COOKIE)


def set_session_cookie(response: Response, email: str) -> None:
    token = _serializer().dumps({"email": email.strip().lower()})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=session_max_age(),
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def _cookie_secure() -> bool:
    import os

    return os.environ.get("K_SERVICE", "").strip() != ""


def load_session(token: str | None) -> FamilySession | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=session_max_age())
    except (BadSignature, SignatureExpired):
        return None
    email = (data.get("email") or "").strip().lower()
    if not email:
        return None
    return FamilySession(email=email, allowed=is_family_allowed(email))


def require_family(dt_family: str | None = Cookie(default=None)) -> FamilySession:
    session = load_session(dt_family)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


def ensure_allowed(session: FamilySession | None) -> FamilySession:
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not session.allowed:
        raise HTTPException(status_code=403, detail="Email not on the family list")
    return session


def require_family_allowed(
    dt_family: str | None = Cookie(default=None),
) -> FamilySession:
    return ensure_allowed(load_session(dt_family))
