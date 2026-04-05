"""Vertex AI RAG Engine: retrieval_query only (chunks merged into the prompt)."""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_vertex_init_key: tuple[str, str, str] | None = None

_CORPUS_LOC = re.compile(r"^projects/[^/]+/locations/([^/]+)/ragCorpora/")


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

    try:
        import vertexai
        from vertexai import rag
    except ImportError:
        logger.warning("google-cloud-aiplatform not installed; RAG retrieval skipped")
        return ""

    global _vertex_init_key
    vloc = _vertex_location_for_corpus(corpus_resource_name, region)
    key = (project, vloc, corpus_resource_name)
    if _vertex_init_key != key:
        vertexai.init(project=project, location=vloc)
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
        return ""

    if not resp.contexts or not resp.contexts.contexts:
        return ""

    parts: list[str] = []
    for c in resp.contexts.contexts:
        text = (c.text or "").strip()
        if not text:
            continue
        label = (c.source_display_name or c.source_uri or "document").strip()
        parts.append(f"### {label}\n{text}")

    if not parts:
        return ""
    return "## Retrieved documents (RAG)\n\n" + "\n\n".join(parts)
