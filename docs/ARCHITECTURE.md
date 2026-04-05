# Architecture

This document describes how the **digital-twin-api** service fits into the no-ego stack, what it depends on at runtime, and how changes reach production.

## System context

```mermaid
flowchart TB
    subgraph clients["Clients"]
        Web["no-ego.net widget\n(Gatsby site)"]
        Dev["Local dev\n(localhost:8000/8001)"]
    end

    subgraph gcp["Google Cloud (Terraform-managed)"]
        CR["Cloud Run service\ndigital-twin-api"]
        AR["Artifact Registry\nDocker images"]
        GCS_S["GCS bucket\nsessions JSON\n(optional)"]
        GCS_C["GCS bucket\ncorpus / RAG source\n(infra)"]
        Vertex["Vertex AI\nGemini model"]
        subgraph vertex_rag["Vertex RAG (infra)"]
            RAG["RAG engine config\n(BASIC tier default)"]
        end
    end

    subgraph github["GitHub"]
        GHA["Actions: build, push,\nupdate Cloud Run"]
    end

    Web -->|HTTPS SSE + JSON\nCORS + X-Session-Id| CR
    Dev -->|same API| CR
    GHA --> AR
    GHA --> CR
    CR -->|generate_content_stream| Vertex
    CR -->|retrieval_query\nwhen RAG_CORPUS_RESOURCE set| RAG
    CR -->|read/write session blobs\nwhen bucket set| GCS_S
    GCS_C -->|upload + import\ninto corpus| RAG
```

**Notes**

- **Sessions**: If `GCS_SESSIONS_BUCKET` is unset, chat history stays in **process memory** only (lost on scale/cold start).
- **Knowledge in answers**: **System instruction** from `system.md` only. Biography files live in the **corpus bucket**, are **imported into a Vertex RAG corpus**, and are merged per turn via **`rag.retrieval_query`** when **`RAG_CORPUS_RESOURCE`** is set (`rag_vertex.py` + `llm.py`).

## Deployment pipeline

```mermaid
flowchart LR
    subgraph repo["This repository"]
        Src["src/digital_twin/**\nDockerfile\npyproject.toml"]
    end

    Push["Push to main\n(or workflow_dispatch)"] --> GHA[".github/workflows/deploy-api.yml"]
    Src --> GHA
    GHA --> Build["docker build\nlinux/amd64"]
    Build --> PushImg["docker push\nREGION-docker.pkg.dev/.../api:SHA"]
    PushImg --> Deploy["gcloud run deploy\n→ new revision"]
```

Authentication uses **Workload Identity Federation** from GitHub Actions into GCP (see `docs/WORKING.md`).

## In-process architecture (API service)

```mermaid
flowchart TB
    subgraph fastapi["FastAPI app (main.py)"]
        MW["CORS middleware"]
        H["GET/HEAD /health"]
        G["GET /api/chat\n(load history)"]
        P["POST /api/chat\n(SSE stream)"]
    end

    RL["rate_limit\nper client IP\n(in-memory window)"]
    SS["session_store\nUUID sessions\nGCS or memory"]
    LLM["llm + rag_vertex\nRAG retrieval + Vertex `google-genai`\nstream_reply"]

    MW --> G
    MW --> P
    P --> RL
    P --> SS
    P --> LLM
    G --> SS
    LLM --> SS
```

- **Rate limiting** is **per Cloud Run instance** (in-memory); under multiple instances, effective limits scale with replicas.
- **POST /api/chat** runs model generation and persistence off the event loop via `asyncio.to_thread` so the server stays responsive while calling blocking SDK code.

## Chat request flow (POST)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant RL as rate_limit
    participant SS as session_store
    participant V as Vertex Gemini
    participant R as Vertex RAG

    C->>API: POST /api/chat JSON {prompt}\nHeader X-Session-Id (optional)
    API->>RL: check_rate_limit(ip)
    RL-->>API: ok or 429
    API->>SS: load_messages(session_id)
    SS-->>API: prior turns
    API->>R: retrieval_query (if corpus configured)
    R-->>API: text chunks
    API->>V: generate_content_stream\n(system + RAG context + history + prompt)
    V-->>API: text chunks
    API-->>C: text/event-stream\n(data: {"text": ...})\n then complete
    API->>SS: save_messages(session_id, updated history)
```

## Repository layout (concise)

| Path | Role |
|------|------|
| `src/digital_twin/main.py` | HTTP API, SSE assembly |
| `src/digital_twin/llm.py` | `system.md` + optional RAG context; Vertex Gemini streaming |
| `src/digital_twin/rag_vertex.py` | `rag.retrieval_query` into corpus |
| `src/digital_twin/session_store.py` | Session JSON in GCS or memory |
| `src/digital_twin/rate_limit.py` | Per-IP RPM limit |
| `src/digital_twin/prompts/` | `system.md` only in git; local uploads gitignored |
| `terraform/` | Cloud Run, buckets, Vertex/RAG infra, IAM, registry |
| `.github/workflows/deploy-api.yml` | CI/CD to Artifact Registry + Cloud Run |

For day-to-day operations and secrets, see `docs/WORKING.md`.
