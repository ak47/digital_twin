"""Vertex AI RAG Engine: retrieval_query only (chunks merged into the prompt)."""

from __future__ import annotations

import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_vertex_init_key: tuple[str, str, str] | None = None

_CORPUS_LOC = re.compile(r"^projects/[^/]+/locations/([^/]+)/ragCorpora/")
_CORPUS_PROJECT = re.compile(r"^projects/([^/]+)/")


def _corpus_project_id(corpus_resource_name: str) -> str | None:
    """Project id or number embedded in the corpus resource name (authoritative for retrieval)."""
    m = _CORPUS_PROJECT.match(corpus_resource_name.strip())
    return m.group(1) if m else None


def _vertex_location_for_corpus(corpus_resource_name: str, fallback_region: str) -> str:
    """RAG retrieval must use the corpus's region (may differ from GCP_REGION / Gemini region)."""
    m = _CORPUS_LOC.match(corpus_resource_name.strip())
    return m.group(1) if m else fallback_region.strip() or "us-central1"


def fetch_rag_context(
    project: str,
    region: str,
    corpus_resource_name: str,
    query: str,
) -> str:
    """
    Return retrieved chunk text for this user query, or empty string if disabled / error.

    corpus_resource_name: full resource, e.g.
    projects/PROJECT/locations/us-central1/ragCorpora/CORPUS_ID
    """
    corpus_resource_name = corpus_resource_name.strip()
    if not corpus_resource_name or not query.strip():
        return ""

    start = time.perf_counter()
    status = "ok"
    context_count = 0
    context_chars = 0

    try:
        import vertexai
        from vertexai import rag
    except ImportError:
        logger.warning("google-cloud-aiplatform not installed; RAG retrieval skipped")
        return ""

    global _vertex_init_key
    # Retrieval must use the corpus resource's project; GCP_PROJECT_ID on Cloud Run can drift
    # (wrong secret, different deploy) while RAG_CORPUS_RESOURCE still points at another project.
    corpus_project = (_corpus_project_id(corpus_resource_name) or project or "").strip()
    if not corpus_project:
        logger.warning("RAG corpus resource missing projects/ segment; retrieval skipped")
        return ""
    if project.strip() and corpus_project != project.strip():
        logger.info(
            "RAG corpus project %s differs from app GCP_PROJECT_ID %s; using corpus project for Vertex",
            corpus_project,
            project.strip(),
        )
    vloc = _vertex_location_for_corpus(corpus_resource_name, region)
    key = (corpus_project, vloc, corpus_resource_name)
    if _vertex_init_key != key:
        vertexai.init(project=corpus_project, location=vloc)
        _vertex_init_key = key

    top_k = int(os.environ.get("RAG_TOP_K", "8"))
    thresh_raw = os.environ.get("RAG_VECTOR_DISTANCE_THRESHOLD", "").strip()

    try:
        if thresh_raw:
            try:
                threshold = float(thresh_raw)
                cfg = rag.RagRetrievalConfig(
                    top_k=top_k,
                    filter=rag.Filter(vector_distance_threshold=threshold),
                )
            except ValueError:
                cfg = rag.RagRetrievalConfig(top_k=top_k)
        else:
            cfg = rag.RagRetrievalConfig(top_k=top_k)

        resp = rag.retrieval_query(
            rag_resources=[
                rag.RagResource(
                    rag_corpus=corpus_resource_name,
                )
            ],
            text=query,
            rag_retrieval_config=cfg,
        )
    except Exception as e:
        logger.exception("rag.retrieval_query failed: %s", e)
        status = "error"
        _record_rag_latency(
            ms=(time.perf_counter() - start) * 1000.0,
            status=status,
            corpus_resource_name=corpus_resource_name,
            vloc=vloc,
            gemini_region=region,
            top_k=top_k,
            context_count=0,
            context_chars=0,
        )
        return ""

    if resp.contexts and resp.contexts.contexts:
        for c in resp.contexts.contexts:
            text = (c.text or "").strip()
            if not text:
                continue
            context_count += 1
            context_chars += len(text)

    if not resp.contexts or not resp.contexts.contexts:
        _record_rag_latency(
            ms=(time.perf_counter() - start) * 1000.0,
            status=status,
            corpus_resource_name=corpus_resource_name,
            vloc=vloc,
            gemini_region=region,
            top_k=top_k,
            context_count=0,
            context_chars=0,
        )
        return ""

    parts: list[str] = []
    for c in resp.contexts.contexts:
        text = (c.text or "").strip()
        if not text:
            continue
        label = (c.source_display_name or c.source_uri or "document").strip()
        parts.append(f"### {label}\n{text}")

    if not parts:
        _record_rag_latency(
            ms=(time.perf_counter() - start) * 1000.0,
            status=status,
            corpus_resource_name=corpus_resource_name,
            vloc=vloc,
            gemini_region=region,
            top_k=top_k,
            context_count=context_count,
            context_chars=context_chars,
        )
        return ""
    _record_rag_latency(
        ms=(time.perf_counter() - start) * 1000.0,
        status=status,
        corpus_resource_name=corpus_resource_name,
        vloc=vloc,
        gemini_region=region,
        top_k=top_k,
        context_count=context_count,
        context_chars=context_chars,
    )
    return "## Retrieved documents (RAG)\n\n" + "\n\n".join(parts)


def _rag_mode_label() -> str:
    raw = (os.environ.get("RAG_ENGINE_DEPLOYMENT_MODE") or "").strip().upper()
    if raw == "SERVERLESS":
        return "serverless"
    if raw.startswith("SPANNER"):
        return "spanner"
    return "unknown"


def _record_rag_latency(
    *,
    ms: float,
    status: str,
    corpus_resource_name: str,
    vloc: str,
    gemini_region: str,
    top_k: int,
    context_count: int,
    context_chars: int,
) -> None:
    try:
        from digital_twin.metrics import record_latency_ms, sized_label

        record_latency_ms(
            "rag_retrieval_latency_ms",
            ms,
            labels={
                "rag_mode": _rag_mode_label(),
                "rag_location": vloc,
                "gemini_location": (os.environ.get("GEMINI_LOCATION") or gemini_region or "").strip()
                or "unknown",
                "gemini_model": (os.environ.get("GEMINI_MODEL") or "").strip() or "unknown",
                "rag_top_k": str(top_k),
                "status": status,
                "rag_context_count": str(max(0, int(context_count))),
                "rag_context_chars": sized_label(context_chars),
            },
        )
    except Exception:
        # Metrics must be best-effort only.
        return
