"""Admin API: OAuth, inbox, owner replies, instructions, archive."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from digital_twin import admin_auth, conversation_store
from digital_twin.observability import log_event
from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class HumanMessageRequest(BaseModel):
    content: str


class InstructionsBody(BaseModel):
    content: str


@router.get("/auth/google")
def auth_google() -> RedirectResponse:
    try:
        flow = admin_auth.oauth_flow()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account",
    )
    if not flow.code_verifier:
        raise HTTPException(status_code=500, detail="OAuth PKCE verifier missing")
    response = RedirectResponse(auth_url)
    admin_auth.set_oauth_pending_cookie(
        response,
        state=state,
        code_verifier=flow.code_verifier,
    )
    return response


@router.get("/auth/google/callback")
def auth_google_callback(request: Request) -> RedirectResponse:
    callback_state = request.query_params.get("state") or ""
    code_verifier = admin_auth.load_oauth_pending(
        callback_state,
        request.cookies.get(admin_auth.OAUTH_PENDING_COOKIE),
    )
    try:
        flow = admin_auth.oauth_flow(code_verifier=code_verifier, state=callback_state)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    flow.fetch_token(
        authorization_response=admin_auth.oauth_callback_authorization_response(request)
    )
    creds = flow.credentials
    if not creds or not creds.id_token:
        raise HTTPException(status_code=401, detail="OAuth token missing")
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests

    s = get_settings()
    info = id_token.verify_oauth2_token(
        creds.id_token,
        google_requests.Request(),
        s.google_oauth_client_id,
    )
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Email not provided by Google")
    if not admin_auth.is_email_allowlisted(email):
        log_event(
            event="admin_auth_allowlist_denied",
            severity=logging.WARNING,
            message="Admin login denied: email not on allowlist",
            logger=logger,
            email=email,
        )
        raise HTTPException(status_code=403, detail="Email not authorized for admin access")
    redirect = s.admin_ui_redirect_url or "/"
    response = RedirectResponse(redirect, status_code=302)
    admin_auth.clear_oauth_pending_cookie(response)
    admin_auth.set_session_cookie(response, email)
    return response


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    admin_auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(session: admin_auth.AdminSession = Depends(admin_auth.require_admin)) -> dict:
    return {"authenticated": True, "email": session.email}


@router.get("/conversations")
def admin_list_conversations(
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> list[dict]:
    return conversation_store.list_conversations()


@router.get("/conversations/{conversation_id}")
def admin_get_conversation(
    conversation_id: str,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict:
    rows = conversation_store.open_conversation(conversation_id)
    name = rows[0].get("conversation_name") if rows else None
    return {
        "conversation_id": conversation_id,
        "conversation_name": name,
        "messages": rows,
    }


@router.post("/conversations/{conversation_id}/messages")
def admin_post_message(
    conversation_id: str,
    body: HumanMessageRequest,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict:
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")
    return conversation_store.insert_owner_message(conversation_id, content)


@router.post("/conversations/{conversation_id}/resolve")
def admin_resolve(
    conversation_id: str,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict[str, bool]:
    conversation_store.resolve_conversation(conversation_id)
    return {"ok": True}


@router.get("/instructions")
def get_instructions(
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict:
    content, updated = conversation_store.get_additional_instructions()
    updated_at = None
    if updated is not None:
        updated_at = conversation_store.format_timestamp(updated)
    return {"content": content, "updated_at": updated_at}


@router.put("/instructions")
def put_instructions(
    body: InstructionsBody,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict:
    try:
        content, updated_at = conversation_store.save_additional_instructions(body.content or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"content": content, "updated_at": updated_at}


@router.get("/conversations/export")
def export_conversations(
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> PlainTextResponse:
    data = conversation_store.export_messages_jsonl()
    return PlainTextResponse(
        data,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="conversations.jsonl"'},
    )


@router.get("/archive")
def list_archive(
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> list[dict]:
    return conversation_store.list_archived_conversations()


@router.post("/conversations/{conversation_id}/archive")
def archive_one(
    conversation_id: str,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict[str, bool]:
    conversation_store.archive_conversation(conversation_id)
    return {"ok": True}


@router.post("/archive/{conversation_id}/restore")
def restore_one(
    conversation_id: str,
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict[str, bool]:
    conversation_store.restore_conversation(conversation_id)
    return {"ok": True}


@router.post("/archive/bulk")
def archive_bulk(
    _session: admin_auth.AdminSession = Depends(admin_auth.require_admin),
) -> dict[str, int]:
    count = conversation_store.bulk_archive_idle(hours=72)
    return {"archived": count}
