"""Google OAuth admin authentication with email allowlist and signed session cookie."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from fastapi import Cookie, HTTPException, Request, Response
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)

COOKIE_NAME = "dt_admin"
OAUTH_PENDING_COOKIE = "dt_admin_oauth"
OAUTH_PENDING_MAX_AGE_SECONDS = 600
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


@dataclass(frozen=True, slots=True)
class AdminSession:
    email: str


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().admin_session_secret
    if not secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(secret, salt="digital-twin-admin")


def _oauth_pending_serializer() -> URLSafeTimedSerializer:
    secret = get_settings().admin_session_secret
    if not secret:
        raise RuntimeError("ADMIN_SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(secret, salt="digital-twin-admin-oauth-pending")


def session_max_age() -> int:
    return get_settings().admin_session_max_age_seconds


def is_email_allowlisted(email: str) -> bool:
    allowed = get_settings().admin_allowed_emails
    if not allowed:
        return False
    return email.strip().lower() in allowed


def oauth_callback_authorization_response(request: Request) -> str:
    """Build the OAuth callback URL for token exchange.

    Cloud Run terminates TLS at the load balancer, so ``request.url`` is often
    ``http://…`` internally. oauthlib rejects that with InsecureTransportError.
    Use the configured redirect URI (always https in production) plus the query
    string Google appended on redirect.
    """
    redirect_uri = get_settings().admin_oauth_redirect_uri
    if not redirect_uri:
        raise RuntimeError("ADMIN_OAUTH_REDIRECT_URI is not configured")
    query = request.url.query
    if query:
        return f"{redirect_uri}?{query}"
    return redirect_uri


def oauth_flow(*, code_verifier: str | None = None, state: str | None = None) -> Flow:
    s = get_settings()
    if not s.google_oauth_client_id or not s.google_oauth_client_secret:
        raise RuntimeError("Google OAuth client credentials are not configured")
    if not s.admin_oauth_redirect_uri:
        raise RuntimeError("ADMIN_OAUTH_REDIRECT_URI is not configured")
    flow_kwargs: dict[str, object] = {"redirect_uri": s.admin_oauth_redirect_uri}
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
    if not constant_time_compare(stored_state, state.strip()):
        raise HTTPException(status_code=400, detail="OAuth state mismatch; sign in again")
    return code_verifier


def clear_oauth_pending_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_PENDING_COOKIE)


def set_session_cookie(response: Response, email: str) -> None:
    token = _serializer().dumps({"email": email.strip().lower()})
    max_age = session_max_age()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def _cookie_secure() -> bool:
    import os

    return os.environ.get("K_SERVICE", "").strip() != ""


def load_session(token: str | None) -> AdminSession | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=session_max_age())
    except (BadSignature, SignatureExpired):
        return None
    email = (data.get("email") or "").strip().lower()
    if not email or not is_email_allowlisted(email):
        return None
    return AdminSession(email=email)


def require_admin(dt_admin: str | None = Cookie(default=None)) -> AdminSession:
    session = load_session(dt_admin)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


def constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
