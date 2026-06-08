"""Vertex Gemini (Flash) text generation; optional when ADC / project unavailable."""

from __future__ import annotations

import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from digital_twin import crash_data, rag_vertex
from digital_twin.metrics import record_latency_ms, sized_label
from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_CRASH_TOOL_ROUNDS = 4

# When RAG is configured but retrieval returns no chunks, the model must not fill gaps from priors.
_RAG_EMPTY_RETRIEVAL_BLOCK = """## Retrieved documents (RAG)

**No passages were retrieved for this query.** Do not invent or infer biographical facts (projects, employers, dates, skills, hobbies, infrastructure, tools, or similar) not supported by retrieved materials. Say that the materials do not cover this, or suggest the user rephrase."""


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
            "You answer in the first person (I, me, my). Only state facts "
            "supported by Retrieved documents (RAG) in the system message; cite sources; "
            "do not invent facts. Be concise."
        )
    return base


def _build_system_instruction(base: str, *, rag_block: str | None, project: str, dataset: str) -> str:
    parts = [base]
    if rag_block:
        parts.extend(["---", rag_block])
    if dataset:
        parts.extend(["---", crash_data.schema_instruction(project, dataset)])
    return "\n\n".join(parts)


def _history_to_contents(history: list[dict[str, Any]], user_text: str) -> list[Any]:
    from google.genai import types

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
    return contents


def _generate_with_crash_tools(
    client: Any,
    model: str,
    contents: list[Any],
    config: Any,
    *,
    project: str,
    dataset: str,
) -> str:
    from google.genai import types

    for _ in range(_MAX_CRASH_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            return "(No model response.)"

        parts = candidate.content.parts or []
        function_calls = [p for p in parts if getattr(p, "function_call", None)]
        if not function_calls:
            text = getattr(response, "text", None)
            return (text or "").strip() or "(Empty model response.)"

        contents.append(candidate.content)
        tool_parts: list[Any] = []
        for part in function_calls:
            fc = part.function_call
            name = getattr(fc, "name", "") or ""
            args = dict(getattr(fc, "args", None) or {})
            if name != "query_crash_data":
                tool_parts.append(
                    types.Part.from_function_response(
                        name=name or "unknown_tool",
                        response={"error": f"Unknown tool: {name}"},
                    )
                )
                continue
            result = crash_data.execute_query(
                project,
                dataset,
                str(args.get("sql") or ""),
            )
            tool_parts.append(
                types.Part.from_function_response(
                    name="query_crash_data",
                    response={"result": result},
                )
            )
        contents.append(types.Content(role="user", parts=tool_parts))

    return "(Could not finish crash data query within the allowed tool rounds.)"


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
    corpus = s.rag_corpus_resource
    # Preview publisher models are frequently only served from the global location on Vertex.
    # If GEMINI_LOCATION is set, respect it. Otherwise default previews to global.
    location = (
        s.gemini_location
        or ("global" if "-preview" in s.gemini_model else s.gcp_region)
    )

    if not project:
        yield (
            "(Vertex not configured: set GCP_PROJECT_ID on the service, or run on Cloud Run.) "
            f"You asked: {user_text[:500]!r}"
        )
        return

    system = _load_system_instruction()
    rag_block: str | None = None

    if corpus:
        rag_block = rag_vertex.fetch_rag_context(
            project, s.gcp_region, corpus, user_text
        )
        rag_block = rag_block or _RAG_EMPTY_RETRIEVAL_BLOCK

    crash_dataset = s.crash_data_bq_dataset
    system = _build_system_instruction(
        system,
        rag_block=rag_block,
        project=project,
        dataset=crash_dataset,
    )

    gen_start = time.perf_counter()
    status = "ok"
    out_chars = 0

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

    contents = _history_to_contents(history, user_text)

    if crash_dataset:
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="query_crash_data",
                        description=(
                            "Run a readonly BigQuery Standard SQL SELECT against NYC and "
                            "California motor vehicle crash tables."
                        ),
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "sql": types.Schema(
                                    type="STRING",
                                    description="BigQuery Standard SQL SELECT statement.",
                                )
                            },
                            required=["sql"],
                        ),
                    )
                ]
            )
        ]
        tool_config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=s.max_output_tokens,
            temperature=s.gemini_temperature,
            tools=tools,
        )
        try:
            text = _generate_with_crash_tools(
                client,
                s.gemini_model,
                contents,
                tool_config,
                project=project,
                dataset=crash_dataset,
            )
            out_chars = len(text)
            yield text
        except Exception as e:
            status = "error"
            logger.exception("generate_content with crash tools failed: %s", e)
            yield f"(Generation error: {e!s})"
        finally:
            _record_gemini_latency(gen_start, status, out_chars, corpus, s, location)
        return

    try:
        stream = client.models.generate_content_stream(
            model=s.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=s.max_output_tokens,
                temperature=s.gemini_temperature,
            ),
        )
        for chunk in stream:
            t = getattr(chunk, "text", None)
            if t:
                out_chars += len(t)
                yield t
    except Exception as e:
        status = "error"
        logger.exception("generate_content_stream failed: %s", e)
        yield f"(Generation error: {e!s})"
    finally:
        _record_gemini_latency(gen_start, status, out_chars, corpus, s, location)


def _record_gemini_latency(
    gen_start: float,
    status: str,
    out_chars: int,
    corpus: str,
    s: Any,
    location: str,
) -> None:
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
            "gemini_generate_latency_ms",
            (time.perf_counter() - gen_start) * 1000.0,
            labels={
                "rag_mode": rag_mode,
                "gemini_location": location or "unknown",
                "rag_location": (
                    rag_vertex._vertex_location_for_corpus(corpus, s.gcp_region)  # noqa: SLF001
                    if corpus
                    else "disabled"
                ),
                "gemini_model": s.gemini_model or "unknown",
                "rag_top_k": str(int(os.environ.get("RAG_TOP_K", "8"))),
                "status": status,
                "output_chars": sized_label(out_chars),
            },
        )
    except Exception:
        pass
