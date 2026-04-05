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
        CR["Cloud Run\n digital-twin-api"]
        AR["Artifact Registry\nDocker images"]
        GCS_S["GCS: sessions bucket\nJSON per session\n(optional)"]
        GCS_C["GCS: corpus bucket\ncurated files\n(e.g. rag-sources/)"]
        Vertex["Vertex AI\nGemini\n(google-genai)"]
        subgraph vertex_rag["Vertex RAG Engine"]
            RAGCfg["RAG engine config\nper region\n(BASIC default)"]
            Corpus["RagCorpus\n(imported GCS URIs)"]
        end
        SM["Secret Manager\noptional: SA JSON\nfor Gmail digest"]
        Gmail["Gmail API\nsend as delegated\nWorkspace user"]
    end

    subgraph github["GitHub Actions"]
        DeployWF["deploy-api.yml\npush main / dispatch"]
        IngestWF["ingest-rag-corpus.yml\nworkflow_dispatch only"]
    end

    subgraph repo["Repository (operators)"]
        IngestPy["scripts/ingest_rag_corpus.py\nupload + corpus + import"]
        RagSrc["rag-sources/**\n(e.g. knowledge.txt)"]
    end

    Web -->|HTTPS JSON + SSE\nCORS + X-Session-Id| CR
    Dev --> CR
    DeployWF --> AR
    DeployWF --> CR
    IngestWF -->|"WIF auth; pip -e .;\npython scripts/ingest_rag_corpus.py"| Corpus
    RagSrc -->|"local ingest or\ngsutil cp → bucket"| GCS_C
    GCS_C -->|"import_files"| Corpus
    RAGCfg -.->|"provisions DB tier"| Corpus
    CR -->|generate_content_stream\nGCP_REGION| Vertex
    CR -->|retrieval_query\nregion from corpus resource name| Corpus
    CR -->|read/write when bucket set| GCS_S
    CR -.->|optional: list blobs,\nconditional send + CAS update| GCS_S
    CR -.->|when digest enabled:\nGMAIL_SERVICE_ACCOUNT_JSON| SM
    CR -.->|domain-wide delegation| Gmail
    IngestPy --> GCS_C
    IngestPy --> Corpus
```

**Notes**

- **Sessions**: If `GCS_SESSIONS_BUCKET` is unset, history stays in **process memory** (lost on recycle/scale-out). Session JSON in GCS includes **`last_activity_at`** (set on each save) for digest eligibility.
- **Idle session digest (optional)**: When **`GCS_SESSIONS_BUCKET`**, **`RESUME_BOT_DIGEST_EMAIL_TO`**, and **Gmail** credentials are all configured, the app starts a **background loop** (`session_digest.digest_loop`) on startup. It periodically scans session blobs under the sessions prefix; after **`RESUME_BOT_DIGEST_IDLE_MINUTES`** (default 60) without activity, it emails a **plain-text transcript attachment** via **Gmail API** using a **service account** with **domain-wide delegation** as **`GMAIL_DELEGATED_USER`**. Successful sends set **`idle_digest_sent_at`** on the blob with **generation-match (CAS)** to reduce duplicate sends. **Requires GCS** (not in-memory sessions). With **multiple Cloud Run instances**, rare duplicate digests are possible unless you cap instances (see **`README.md`**).
- **RAG is optional**: If `RAG_CORPUS_RESOURCE` is unset, answers use **`system.md` only** (no retrieval). When set, `rag_vertex.fetch_rag_context` runs **`vertexai.rag.retrieval_query`**, formats chunks, and **`llm.stream_reply`** appends them to the system instruction before calling Gemini.
- **Two regions**: **Gemini** uses **`GCP_REGION`** (default `us-central1` on Cloud Run). **Retrieval** initializes Vertex in the **location embedded in `RAG_CORPUS_RESOURCE`** (e.g. `.../locations/europe-west4/ragCorpora/...` when using a backup ingest region). See `rag_vertex.py` and `terraform/README.md` (RAG backup region).
- **Tuning**: **`RAG_TOP_K`**, optional **`RAG_VECTOR_DISTANCE_THRESHOLD`** (see `main.py` / `.env.example`).
- **`RAG_CORPUS_RESOURCE` on Cloud Run**: Set via Terraform **`rag_corpus_resource_name`** → env on the service. **Deploy API** can also pass repository **Variable** `RAG_CORPUS_RESOURCE` on each deploy (`gcloud run services update` merges env vars); keep this aligned with the corpus you actually imported.
- **Terraform remote state**: Optional GCS backend — copy `terraform/backend.tf.example` to `backend.tf` after creating a state bucket (`terraform/versions.tf`).

## Deployment pipeline (API image)

```mermaid
flowchart LR
    subgraph trigger["Trigger"]
        Push["Push to main\n(paths: src/**, Dockerfile,\npyproject.toml, workflow)"]
        WD["workflow_dispatch"]
    end

    subgraph gha["deploy-api.yml"]
        Auth["WIF: secrets\nGCP_WORKLOAD_IDENTITY_PROVIDER,\nGCP_SERVICE_ACCOUNT_EMAIL,\nGCP_PROJECT_ID"]
        Build["docker build\nlinux/amd64"]
        PushImg["docker push\nREGION-docker.pkg.dev/.../api:SHA"]
        Upd["gcloud run services update\nimage + env vars"]
    end

    Push --> gha
    WD --> gha
    Auth --> Build --> PushImg --> Upd
```

On deploy, **environment variables** are applied with a **custom delimiter** (`^;^`) so **`CORS_ALLOWED_ORIGINS`** can contain commas. Optional repository **Variables** include **`RAG_CORPUS_RESOURCE`**, **`CORS_ALLOWED_ORIGINS`**, and for the digest feature **`RESUME_BOT_DIGEST_EMAIL_TO`**, **`GMAIL_DELEGATED_USER`**, **`GMAIL_SECRET_NAME`** (Secret Manager **secret id**). When Gmail variables are set alongside **`RESUME_BOT_DIGEST_EMAIL_TO`**, the workflow adds **`--set-secrets=GMAIL_SERVICE_ACCOUNT_JSON=GMAIL_SECRET_NAME:latest`** so the runtime receives the SA JSON without putting it in plain env (see `.github/workflows/deploy-api.yml`).

Secret names and copying Terraform outputs into GitHub are documented in **`terraform/README.md`** and helper **`scripts/print-github-actions-secrets.sh`**.

## RAG corpus lifecycle

Typical operator flow (details in **`terraform/README.md`** → RAG):

```mermaid
flowchart LR
    subgraph create["First-time / full ingest"]
        A["scripts/ingest_rag_corpus.py\n--project-id … --files …"]
        A --> B["Upload to corpus bucket"]
        B --> C["create_corpus + import_files"]
        C --> D["Print RAG_CORPUS_RESOURCE\n→ tfvars / GitHub Variable / .env"]
    end

    subgraph refresh["Re-import after gs:// changes"]
        E["Upload new objects\ne.g. gsutil cp rag-sources/* …"]
        F["GitHub: Ingest RAG corpus\nOR local script\n--skip-upload --files …"]
        E --> F
    end
```

- **`.github/workflows/ingest-rag-corpus.yml`**: Manual dispatch only. Requires the same **secrets** as Deploy API plus repository **Variables** **`CORPUS_BUCKET_NAME`** and **`RAG_CORPUS_RESOURCE`**; optional **`RAG_INGEST_REGION`** (default **`europe-west4`** if not inferable). The checked-in step runs **`ingest_rag_corpus.py`** with **`--skip-upload`** (assumes objects already in the bucket); adjust **`--files`** in the workflow if you need different globs.
- **Local full ingest**: **`pip install -e .`**, ADC (`gcloud auth application-default login`), then **`scripts/ingest_rag_corpus.py`** (can create corpus, upload, import, and optionally ensure RAG engine tier — see script docstring).

## Idle session digest (email)

Background feature in **`session_digest.py`**, started from FastAPI **`lifespan`** in **`main.py`** when **`session_digest.digest_feature_configured()`** is true.

```mermaid
flowchart TB
    subgraph startup["App lifespan"]
        L["FastAPI startup"]
        C{"digest_feature_configured?"}
        Loop["session_digest.digest_loop\nasync sleep + to_thread scan"]
        L --> C
        C -->|yes| Loop
        C -->|no| Idle["no background task"]
    end

    subgraph scan["scan_and_send_idle_digests (per tick)"]
        List["List GCS blobs\nprefix sessions/"]
        Each["For each session JSON"]
        Check["Idle since last_activity_at?\nnot already emailed for this activity?"]
        Mail["_send_digest_email →\nGmail API users.messages.send"]
        CAS["Rewrite JSON:\nidle_digest_sent_at +\nif_generation_match"]
        List --> Each --> Check
        Check -->|send| Mail --> CAS
    end

    Loop --> scan
```

**Configuration (all required to enable)**

| Variable / secret | Role |
|-------------------|------|
| `GCS_SESSIONS_BUCKET` | Session persistence (digest does not run on in-memory-only mode). |
| `RESUME_BOT_DIGEST_EMAIL_TO` | Comma-separated recipient inbox(es). |
| `GMAIL_DELEGATED_USER` | Workspace user the SA impersonates (sender). |
| `GMAIL_SERVICE_ACCOUNT_JSON` | SA key JSON (production: from Secret Manager via deploy **`--set-secrets`**). |
| `GMAIL_SERVICE_ACCOUNT_KEY_FILE` | Local dev: path to SA JSON instead of inline env. |

One of **`GMAIL_SERVICE_ACCOUNT_JSON`** or **`GMAIL_SERVICE_ACCOUNT_KEY_FILE`** must be available at runtime (with **`GMAIL_DELEGATED_USER`**).

**Optional tuning**: `RESUME_BOT_DIGEST_IDLE_MINUTES` (default 60), `RESUME_BOT_DIGEST_SCAN_INTERVAL_SECONDS` (default 300), `RESUME_BOT_DIGEST_TIMEZONE` (subject/attachment display time, default `America/Los_Angeles`), `GCS_SESSIONS_PREFIX` (default `sessions`).

**Runbook**: Workspace admin setup, Gmail API enablement, Secret Manager, and GitHub Variables are in **`README.md`** → *Idle session digest*.

## In-process architecture (API service)

```mermaid
flowchart TB
    subgraph fastapi["FastAPI app (main.py)"]
        MW["CORS middleware"]
        H["GET/HEAD /health"]
        G["GET /api/chat\n(load history)"]
        P["POST /api/chat\n(SSE stream)"]
        Life["lifespan:\noptional digest_loop task"]
    end

    RL["rate_limit\nper client IP\n(in-memory window)"]
    SS["session_store\nUUID sessions\nGCS or memory"]
    Dig["session_digest\nGCS scan + Gmail"]

    subgraph llm_pipe["llm.stream_reply (llm.py)"]
        RAG["rag_vertex.fetch_rag_context\nretrieval_query →\nformatted block"]
        GEN["google-genai\nGemini generate_content_stream"]
        RAG --> GEN
    end

    Life -.->|if configured| Dig
    MW --> G
    MW --> P
    P --> RL
    P --> SS
    P --> llm_pipe
    G --> SS
```

**`llm.stream_reply`** runs **`rag_vertex.fetch_rag_context`** first when **`RAG_CORPUS_RESOURCE`** is set (merges chunks into the system instruction), then calls **`google.genai`** with **`GCP_REGION`** for the model client. Session **save** after the stream is handled in **`main.py`**, not inside **`llm.py`**.

- **Rate limiting** is **per Cloud Run instance**; more replicas mean higher aggregate allowance unless you add shared state.
- **POST /api/chat** uses **`asyncio.to_thread`** for model work and session persistence so the event loop stays responsive.

## Chat request flow (POST)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant RL as rate_limit
    participant SS as session_store
    participant R as Vertex RAG
    participant V as Vertex Gemini

    C->>API: POST /api/chat JSON {prompt}\nHeader X-Session-Id (optional)
    API->>RL: check_rate_limit(ip)
    RL-->>API: ok or 429
    API->>SS: load_messages(session_id)
    SS-->>API: prior turns
    API->>R: retrieval_query\n(corpus location from resource name)\noptional if RAG_CORPUS_RESOURCE unset
    R-->>API: context chunks → system augmentation
    API->>V: generate_content_stream\n(system + history + prompt)\nGemini region = GCP_REGION
    V-->>API: text chunks
    API-->>C: text/event-stream\n(data: {"text": ...})\n then complete
    API->>SS: save_messages(session_id, updated history)
```

## Repository layout (concise)

| Path | Role |
|------|------|
| `src/digital_twin/main.py` | HTTP API, SSE, env wiring |
| `src/digital_twin/llm.py` | System prompt; optional RAG block; Vertex Gemini streaming |
| `src/digital_twin/rag_vertex.py` | `vertexai.rag.retrieval_query` + chunk formatting |
| `src/digital_twin/session_store.py` | Session JSON in GCS or memory; **`last_activity_at`** on save |
| `src/digital_twin/session_digest.py` | Idle digest: GCS scan, Gmail send, **`idle_digest_sent_at`** + CAS |
| `src/digital_twin/rate_limit.py` | Per-IP RPM limit |
| `src/digital_twin/prompts/` | `system.md` (packaged in wheel) |
| `rag-sources/` | Curated corpus files for upload / ingest (e.g. `knowledge.txt`) |
| `scripts/ingest_rag_corpus.py` | Upload to corpus bucket, corpus create/import, CLI |
| `scripts/print-github-actions-secrets.sh` | Helper to print Terraform outputs for GitHub secrets |
| `terraform/` | Cloud Run, buckets, RAG engine, IAM, Artifact Registry, optional WIF |
| `terraform/backend.tf.example` | Template for GCS remote state |
| `.github/workflows/deploy-api.yml` | Build/push image, update Cloud Run |
| `.github/workflows/ingest-rag-corpus.yml` | Manual RAG re-import from bucket |

Runtime dependencies include **`google-genai`** (Gemini), **`google-cloud-aiplatform`** (Vertex RAG / ingest), **`google-api-python-client`** and **`google-auth`** (Gmail digest). See `pyproject.toml`.

For day-to-day operations, secrets, and backlog items, see **`docs/WORKING.md`** and **`docs/REMAINING_WORK.md`**.
