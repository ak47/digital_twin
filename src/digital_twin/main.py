"""
FastAPI entrypoint for Cloud Run.

Env (injected by Terraform / Cloud Run):
  PORT                    — Cloud Run sets this (default 8080 locally)
  CORS_ALLOWED_ORIGINS    — comma-separated browser origins (set from Terraform; required in Cloud Run)
  GCS_CORPUS_BUCKET       — corpus bucket (upload sources; import into a RAG corpus separately)
  RAG_CORPUS_RESOURCE     — full ragCorpora/... name; includes region (e.g. .../locations/us-central1/...).
                            Retrieval uses that region; Gemini still uses GCP_REGION (may differ if you use a backup RAG region).
  RAG_TOP_K               — optional retrieval count (default 8)
  RAG_VECTOR_DISTANCE_THRESHOLD — optional; if set, passed to RAG filter
  GCS_SESSIONS_BUCKET     — session JSON blobs (optional; in-memory if unset)
  GCP_PROJECT_ID, GCP_REGION — Vertex Gemini
  GEMINI_MODEL            — optional, default gemini-2.5-flash (Vertex)
  GEMINI_TEMPERATURE      — optional, default 0.2 (lower reduces invented detail)
  GET /                   — includes llm_model alongside service + docs (for About page)
  RATE_LIMIT_REQUESTS_PER_MINUTE — default 30
  SYSTEM_PROMPT_PATH      — override path to system.md

Idle session digest email is not run inside this API process. Use Terraform Cloud Run Job +
Cloud Scheduler (see terraform/digest_job.tf and README).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from digital_twin import llm, rate_limit, session_store
from digital_twin.metrics import record_latency_ms, sized_label
from digital_twin.observability import log_event, report_exception, setup_logging
from digital_twin.settings import get_settings
from digital_twin.structured_logging import clear_request_context, set_request_context, update_session_context

logger = logging.getLogger(__name__)
setup_logging(level=logging.INFO)

SESSION_HEADER = "X-Session-Id"

# When CORS_ALLOWED_ORIGINS is unset/empty, do not invent production origins (Terraform requires explicit cors_allowed_origins).
# Local dev still gets localhost below; Cloud Run should always set CORS_ALLOWED_ORIGINS from Terraform.
_DEFAULT_CORS_ORIGINS: tuple[str, ...] = ()

# Always merged in so local Gatsby (`gatsby develop`, often :8000 / :8001) can call deployed API.
_LOCAL_DEV_ORIGINS = (
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
)


def _cors_origins() -> list[str]:
    raw = get_settings().cors_allowed_origins
    if not raw:
        base = list(_DEFAULT_CORS_ORIGINS)
    else:
        base = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    if not base:
        base = list(_DEFAULT_CORS_ORIGINS)
    seen = set(base)
    for o in _LOCAL_DEV_ORIGINS:
        if o not in seen:
            base.append(o)
            seen.add(o)
    return base


# Terraform/CI pass comma-separated origins; gcloud --update-env-vars breaks on commas unless a
# custom delimiter is used (see deploy workflow).

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


def _trace_id_from_header(request: Request) -> str | None:
    header = (request.headers.get("x-cloud-trace-context") or "").strip()
    if not header:
        return None
    return header.split("/", 1)[0] or None


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
    trace_id = _trace_id_from_header(request)
    set_request_context(request_id=request_id, trace_id=trace_id, session_id=None)
    try:
        response = await call_next(request)
    finally:
        clear_request_context()
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/health", response_class=JSONResponse)
def health() -> dict[str, str]:
    """Liveness/readiness; always application/json when this app handles the request."""
    return {"status": "ok"}


@app.head("/health")
def health_head() -> Response:
    return Response(status_code=200, media_type="application/json")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "digital-twin-api",
        "docs": "/docs",
        "llm_model": llm.gemini_model_id(),
        "llm_provider": "vertex",
    }


def _resolve_session_id_or_400(x_session_id: str | None) -> str:
    validated = session_store.validate_session_id(x_session_id)
    if x_session_id and x_session_id.strip() and not validated:
        raise HTTPException(status_code=400, detail="Invalid X-Session-Id (expected UUID).")
    return validated or session_store.new_session_id()


def _json_with_session_id(*, sid: str, body: dict[str, object]) -> JSONResponse:
    resp = JSONResponse(content=body)
    resp.headers[SESSION_HEADER] = sid
    return resp


@app.get("/api/chat")
def chat_history(
    request: Request,
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
) -> JSONResponse:
    sid = _resolve_session_id_or_400(x_session_id)
    update_session_context(sid)
    messages = session_store.load_messages(sid)
    body = {"messages": messages}
    return _json_with_session_id(sid=sid, body=body)


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

    sid = _resolve_session_id_or_400(x_session_id)
    update_session_context(sid)

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
        total_start = time.perf_counter()

        def run_model() -> str:
            return "".join(llm.stream_reply(history[:-1], prompt))

        model_start = time.perf_counter()
        model_status = "ok"
        try:
            text = await asyncio.to_thread(run_model)
        except Exception as e:
            model_status = "error"
            log_event(
                event="chat_model_invocation_failed",
                severity=logging.ERROR,
                message="Model invocation failed",
                logger=logger,
                where="chat_post.run_model",
                error_code="chat_model_inference_error",
                exception_message=str(e),
                session_id=sid,
                exc_info=True,
            )
            report_exception(e, context={"where": "chat_post.run_model"})
            text = f"(Temporary error: {e!s})"
        finally:
            try:
                mode_raw = (os.environ.get("RAG_ENGINE_DEPLOYMENT_MODE") or "").strip().upper()
                rag_mode = (
                    "serverless"
                    if mode_raw == "SERVERLESS"
                    else "spanner"
                    if mode_raw.startswith("SPANNER")
                    else "unknown"
                )
                record_latency_ms(
                    "chat_model_latency_ms",
                    (time.perf_counter() - model_start) * 1000.0,
                    labels={
                        "status": model_status,
                        "gemini_model": (os.environ.get("GEMINI_MODEL") or "").strip() or "unknown",
                        "gemini_location": (os.environ.get("GEMINI_LOCATION") or os.environ.get("GCP_REGION") or "").strip()
                        or "unknown",
                        "rag_mode": rag_mode,
                    },
                )
            except Exception:
                pass

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
            log_event(
                event="chat_session_persist_failed",
                severity=logging.ERROR,
                message="Session save failed",
                logger=logger,
                where="chat_post.persist_session",
                error_code="chat_session_persist_error",
                exception_message=str(e),
                session_id=sid,
                exc_info=True,
            )
            report_exception(e, context={"where": "chat_post.persist_session"})
            yield f"data: {json.dumps({'warning': 'session not saved', 'detail': str(e)})}\n\n".encode()

        try:
            mode_raw = (os.environ.get("RAG_ENGINE_DEPLOYMENT_MODE") or "").strip().upper()
            rag_mode = (
                "serverless"
                if mode_raw == "SERVERLESS"
                else "spanner"
                if mode_raw.startswith("SPANNER")
                else "unknown"
            )
            record_latency_ms(
                "chat_total_latency_ms",
                (time.perf_counter() - total_start) * 1000.0,
                labels={
                    "status": "ok" if model_status == "ok" else "error",
                    "gemini_model": (os.environ.get("GEMINI_MODEL") or "").strip() or "unknown",
                    "rag_mode": rag_mode,
                    "output_chars": sized_label(len(assistant_msg)),
                },
            )
        except Exception:
            pass

        log_event(
            event="chat_request_completed",
            severity=logging.INFO,
            message="Chat request stream completed",
            logger=logger,
            status=model_status,
            session_id=sid,
            output_chars=len(assistant_msg),
        )
        yield f"data: {json.dumps({'complete': True})}\n\n".encode()

    headers = {SESSION_HEADER: sid}
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers=headers,
    )
