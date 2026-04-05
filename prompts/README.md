The API’s default **system prompt** is **`src/digital_twin/prompts/system.md`** (bundled in the Docker image).

**Biography / LinkedIn / long narrative:** do **not** commit those here — use **`scripts/ingest_rag_corpus.py`** (upload + RAG import) or `gsutil` + Vertex console; see **`terraform/README.md` → RAG**. Local `knowledge.txt` / `Profile.pdf` are **gitignored**.
