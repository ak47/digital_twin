The API’s default **system prompt** is **`src/digital_twin/prompts/system.md`** (bundled in the Docker image).

**Biography / LinkedIn / long narrative:** do **not** commit those here — upload to the **Terraform corpus GCS bucket** and **import into Vertex RAG** (see **`docs/WORKING.md`**). Local `knowledge.txt` / `Profile.pdf` paths are **gitignored** for convenience when copying to `gsutil`.
