"""Vertex Gemini (Flash) text generation; optional when ADC / project unavailable."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from digital_twin import rag_vertex
from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)


def gemini_model_id() -> str:
    """Resolved Vertex model id (GEMINI_MODEL or default); used by chat and public metadata."""
    return get_settings().gemini_model

# Filled on first use: env vars, else metadata (Cloud Run when CI omitted GCP_PROJECT_ID).
_resolved_project_id: str | None = None


def _resolve_gcp_project() -> str:
    global _resolved_project_id
    if _resolved_project_id is not None:
        return _resolved_project_id
    for key in ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT"):
        v = os.environ.get(key, "").strip()
        if v:
            _resolved_project_id = v
            return v
    # Cloud Run sets K_SERVICE; metadata has project id even if deploy omitted env.
    if os.environ.get("K_SERVICE", "").strip():
        try:
            req = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/project/project-id",
                headers={"Metadata-Flavor": "Google"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                pid = resp.read().decode().strip()
                if pid:
                    _resolved_project_id = pid
                    return pid
        except (OSError, urllib.error.URLError) as e:
            logger.warning("metadata project-id lookup failed: %s", e)
    _resolved_project_id = ""
    return ""


def _prompts_dir() -> Path:
    env_path = os.environ.get("SYSTEM_PROMPT_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve().parent
    return Path(__file__).resolve().parent / "prompts"


def _load_system_instruction() -> str:
    env_path = os.environ.get("SYSTEM_PROMPT_PATH", "").strip()
    path = Path(env_path) if env_path else _prompts_dir() / "system.md"
    try:
        with path.open(encoding="utf-8") as f:
            base = f.read().strip()
    except OSError:
        base = (
            "You answer as Andrew in the first person (I, me, my) from the materials "
            "you are given. Be accurate and concise."
        )
    return base


def stream_reply(
    history: list[dict[str, Any]],
    user_text: str,
) -> Iterator[str]:
    """
    Yield text fragments. Uses Vertex when project id is known (env or Cloud Run metadata)
    and google-genai works; otherwise yields a single fallback string.
    """
    s = get_settings()
    project = _resolve_gcp_project()
    # Preview publisher models are frequently only served from the global location on Vertex.
    # If GEMINI_LOCATION is set, respect it. Otherwise default previews to global.
    location = (
        s.gemini_location
        or ("global" if "-preview" in s.gemini_model else s.gcp_region)
    )
    system = _load_system_instruction()

    if not project:
        yield (
            "(Vertex not configured: set GCP_PROJECT_ID on the service, or run on Cloud Run.) "
            f"You asked: {user_text[:500]!r}"
        )
        return

    corpus = s.rag_corpus_resource
    if corpus:
        rag_block = rag_vertex.fetch_rag_context(
            project, s.gcp_region, corpus, user_text
        )
        if rag_block:
            system = f"{system}\n\n---\n\n{rag_block}"

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai not installed")
        yield "Model unavailable (missing dependency)."
        return

    try:
        client = genai.Client(vertexai=True, project=project, location=location)
    except Exception as e:
        logger.warning("Genai client init failed: %s", e)
        yield f"(Model unavailable: {e!s})"
        return

    contents: list[types.Content] = []
    for m in history:
        role = m.get("role")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        grole = "user" if role == "user" else "model"
        contents.append(
            types.Content(role=grole, parts=[types.Part.from_text(text=text)])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
    )

    try:
        stream = client.models.generate_content_stream(
            model=s.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=s.max_output_tokens,
            ),
        )
        for chunk in stream:
            t = getattr(chunk, "text", None)
            if t:
                yield t
    except Exception as e:
        logger.exception("generate_content_stream failed: %s", e)
        yield f"(Generation error: {e!s})"
