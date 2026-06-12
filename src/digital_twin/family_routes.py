"""Family archive API: OAuth, gallery/video listings with V4 signed URLs, audit log.

Media lives in a private GCS bucket (uniform bucket-level access, no public
IAM). Clients only ever see V4 signed URLs (GET, <= 15 min). Every content
listing emits a structured ``family_archive_access`` log entry (email,
resource, timestamp, client IP, user agent, referer) via structured_logging.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from digital_twin import family_auth
from digital_twin.observability import log_event
from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/family", tags=["family"])

SIGNED_URL_EXPIRY = timedelta(minutes=15)
USER_AGENT_MAX_LEN = 256

_manifest_cache: dict | None = None


def _bucket():
    from google.cloud import storage

    bucket_name = get_settings().family_media_bucket
    if not bucket_name:
        raise RuntimeError("FAMILY_MEDIA_BUCKET is not configured")
    return storage.Client().bucket(bucket_name)


def _signing_credentials():
    """Credentials usable for V4 signing on Cloud Run (IAM signBlob).

    The Cloud Run runtime service account has no exportable private key, so
    key-based signing is unavailable; impersonating itself routes signing
    through the IAM signBlob API (requires roles/iam.serviceAccountTokenCreator
    on its own SA). Returns None when default credentials can sign natively
    (e.g. a local service-account key), letting the storage client handle it.
    """
    import google.auth
    from google.auth import impersonated_credentials
    from google.auth.transport import requests as google_requests
    from google.oauth2 import service_account

    credentials, _ = google.auth.default()
    if isinstance(credentials, service_account.Credentials):
        return None
    sa_email = getattr(credentials, "service_account_email", "") or ""
    if sa_email in ("", "default"):
        credentials.refresh(google_requests.Request())
        sa_email = getattr(credentials, "service_account_email", "") or ""
    if sa_email in ("", "default"):
        raise RuntimeError("Cannot resolve service account email for URL signing")
    return impersonated_credentials.Credentials(
        source_credentials=credentials,
        target_principal=sa_email,
        target_scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        lifetime=3600,
    )


def _signed_url(bucket, key: str) -> str:
    kwargs: dict = {
        "version": "v4",
        "expiration": SIGNED_URL_EXPIRY,
        "method": "GET",
    }
    credentials = _signing_credentials()
    if credentials is not None:
        kwargs["credentials"] = credentials
    return bucket.blob(key).generate_signed_url(**kwargs)


def _load_manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        raw = _bucket().blob("manifest.json").download_as_bytes()
        _manifest_cache = json.loads(raw)
    return _manifest_cache


def reset_manifest_cache() -> None:
    global _manifest_cache
    _manifest_cache = None


def _client_ip(request: Request) -> str | None:
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop
    return request.client.host if request.client else None


def _log_access(request: Request, email: str, resource: str) -> None:
    user_agent = (request.headers.get("user-agent") or "").strip() or None
    if user_agent and len(user_agent) > USER_AGENT_MAX_LEN:
        user_agent = user_agent[:USER_AGENT_MAX_LEN]
    log_event(
        event="family_archive_access",
        severity=logging.INFO,
        message=f"Family archive access: {resource}",
        logger=logger,
        email=email,
        resource=resource,
        ip=_client_ip(request),
        user_agent=user_agent,
        referer=(request.headers.get("referer") or "").strip() or None,
    )


@router.get("/login")
def login() -> RedirectResponse:
    try:
        flow = family_auth.oauth_flow()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    auth_url, state = flow.authorization_url(
        access_type="online",
        include_granted_scopes="true",
        prompt="select_account",
    )
    if not flow.code_verifier:
        raise HTTPException(status_code=500, detail="OAuth PKCE verifier missing")
    response = RedirectResponse(auth_url)
    family_auth.set_oauth_pending_cookie(
        response,
        state=state,
        code_verifier=flow.code_verifier,
    )
    return response


@router.get("/oauth/callback")
def oauth_callback(request: Request) -> RedirectResponse:
    callback_state = request.query_params.get("state") or ""
    code_verifier = family_auth.load_oauth_pending(
        callback_state,
        request.cookies.get(family_auth.OAUTH_PENDING_COOKIE),
    )
    try:
        flow = family_auth.oauth_flow(code_verifier=code_verifier, state=callback_state)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    flow.fetch_token(
        authorization_response=family_auth.oauth_callback_authorization_response(request)
    )
    creds = flow.credentials
    if not creds or not creds.id_token:
        raise HTTPException(status_code=401, detail="OAuth token missing")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    s = get_settings()
    info = id_token.verify_oauth2_token(
        creds.id_token,
        google_requests.Request(),
        s.google_oauth_client_id,
    )
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Email not provided by Google")
    if not family_auth.is_family_allowed(email):
        # Cookie is still set so /family/me can report the denied state;
        # content endpoints enforce the allowlist per request.
        log_event(
            event="family_auth_allowlist_denied",
            severity=logging.WARNING,
            message="Family login by non-allowlisted email",
            logger=logger,
            email=email,
        )
    redirect = s.family_ui_redirect_url or "/"
    response = RedirectResponse(redirect, status_code=302)
    family_auth.clear_oauth_pending_cookie(response)
    family_auth.set_session_cookie(response, email)
    return response


@router.get("/me")
def me(
    session: family_auth.FamilySession = Depends(family_auth.require_family),
) -> dict:
    return {"email": session.email, "allowed": session.allowed}


@router.get("/galleries")
def list_galleries(
    request: Request,
    session: family_auth.FamilySession = Depends(family_auth.require_family_allowed),
) -> dict:
    manifest = _load_manifest()
    galleries = sorted(manifest.get("galleries", []), key=lambda g: g.get("order", 0))
    _log_access(request, session.email, "index")
    return {
        "galleries": [
            {
                "name": g["name"],
                "title": g.get("title"),
                "description": g.get("description"),
                "count": len(g.get("items", [])),
            }
            for g in galleries
        ]
    }


@router.get("/galleries/{name}")
def get_gallery(
    name: str,
    request: Request,
    session: family_auth.FamilySession = Depends(family_auth.require_family_allowed),
) -> dict:
    manifest = _load_manifest()
    gallery = next(
        (g for g in manifest.get("galleries", []) if g["name"] == name), None
    )
    if gallery is None:
        raise HTTPException(status_code=404, detail="Unknown gallery")
    bucket = _bucket()
    _log_access(request, session.email, name)
    return {
        "name": gallery["name"],
        "title": gallery.get("title"),
        "description": gallery.get("description"),
        "items": [
            {
                "caption": item.get("caption"),
                "thumb_url": _signed_url(bucket, item["thumb"]),
                "full_url": _signed_url(bucket, item["full"]),
            }
            for item in gallery.get("items", [])
        ],
    }


@router.get("/videos")
def list_videos(
    request: Request,
    session: family_auth.FamilySession = Depends(family_auth.require_family_allowed),
) -> dict:
    manifest = _load_manifest()
    bucket = _bucket()
    _log_access(request, session.email, "videos")
    return {
        "videos": [
            {
                "title": v.get("title"),
                "description": v.get("description"),
                "date": v.get("date"),
                "video_url": _signed_url(bucket, v["video"]),
                "poster_url": _signed_url(bucket, v["poster"]),
            }
            for v in manifest.get("videos", [])
        ]
    }


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    response = Response(status_code=204)
    family_auth.clear_session_cookie(response)
    return response
