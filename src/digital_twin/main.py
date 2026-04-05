"""
FastAPI entrypoint for Cloud Run.

Env (injected by Terraform / Cloud Run):
  PORT                    — Cloud Run sets this (default 8080 locally)
  CORS_ALLOWED_ORIGINS    — comma-separated, e.g. https://no-ego.net,https://www.no-ego.net
  GCS_CORPUS_BUCKET       — reserved for RAG (unused in this module yet)
  GCS_SESSIONS_BUCKET     — session JSON blobs (optional; in-memory if unset)
  GCP_PROJECT_ID, GCP_REGION — Vertex Gemini
  GEMINI_MODEL            — optional, default gemini-2.5-flash (Vertex)
  RATE_LIMIT_REQUESTS_PER_MINUTE — default 30
  SYSTEM_PROMPT_PATH      — override path to system.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from digital_twin import llm, rate_limit, session_store

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SESSION_HEADER = "X-Session-Id"

# When CORS_ALLOWED_ORIGINS is unset/empty, use the same defaults as Terraform (widget on no-ego).
_DEFAULT_CORS_ORIGINS = (
    "https://no-ego.net",
    "https://www.no-ego.net",
)

# Always merged in so local Gatsby (`gatsby develop`, often :8000 / :8001) can call deployed API.
_LOCAL_DEV_ORIGINS = (
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        base = list(_DEFAULT_CORS_ORIGINS)
    else:
        base = [o.strip() for o in raw.split(",") if o.strip()]
    seen = set(base)
    for o in _LOCAL_DEV_ORIGINS:
        if o not in seen:
            base.append(o)
            seen.add(o)
    return base


app = FastAPI(title="digital-twin-api", version="0.2.0")

_origins = _cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[SESSION_HEADER],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.head("/health")
def health_head() -> Response:
    return Response(status_code=200)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "digital-twin-api", "docs": "/docs"}


@app.get("/api/chat")
def chat_history(
    request: Request,
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> JSONResponse:
    validated = session_store.validate_session_id(x_session_id)
    if x_session_id and x_session_id.strip() and not validated:
        raise HTTPException(status_code=400, detail="Invalid X-Session-Id (expected UUID).")

    sid = validated or session_store.new_session_id()
    messages = session_store.load_messages(sid)
    body = {"messages": messages}
    resp = JSONResponse(content=body)
    resp.headers[SESSION_HEADER] = sid
    return resp


@app.post("/api/chat")
async def chat_post(
    request: Request,
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> StreamingResponse:
    rate_limit.check_rate_limit(
        rate_limit.client_ip(
            lambda k: request.headers.get(k),
            request.client.host if request.client else None,
        )
    )

    validated = session_store.validate_session_id(x_session_id)
    if x_session_id and x_session_id.strip() and not validated:
        raise HTTPException(status_code=400, detail="Invalid X-Session-Id (expected UUID).")

    sid = validated or session_store.new_session_id()

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing or empty prompt.")

    history = [dict(m) for m in session_store.load_messages(sid)]
    history.append({"role": "user", "text": prompt})

    async def events() -> AsyncIterator[bytes]:
        pieces: list[str] = []

        def run_model() -> str:
            return "".join(llm.stream_reply(history[:-1], prompt))

        try:
            text = await asyncio.to_thread(run_model)
        except Exception as e:
            logger.exception("Model invocation failed: %s", e)
            text = f"(Temporary error: {e!s})"

        pieces.append(text)
        chunk_size = 48
        for i in range(0, len(text), chunk_size):
            frag = text[i : i + chunk_size]
            yield f"data: {json.dumps({'text': frag})}\n\n".encode()

        assistant_msg = "".join(pieces)
        final_history = history + [{"role": "assistant", "text": assistant_msg}]

        def persist() -> None:
            session_store.save_messages(sid, final_history)

        try:
            await asyncio.to_thread(persist)
        except Exception as e:
            logger.exception("Session save failed: %s", e)
            yield f"data: {json.dumps({'warning': 'session not saved', 'detail': str(e)})}\n\n".encode()

        yield f"data: {json.dumps({'complete': True})}\n\n".encode()

    headers = {SESSION_HEADER: sid}
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers=headers,
    )
