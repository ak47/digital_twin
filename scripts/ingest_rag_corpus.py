#!/usr/bin/env python3
"""
Upload local files to the Terraform corpus GCS bucket, create a Vertex RAG corpus,
import those objects, then print the resource name for Cloud Run.

Requires: pip install -e .  (google-cloud-aiplatform, google-cloud-storage)
Auth: gcloud auth application-default login

Example:
  cd /path/to/digital_twin
  python3 scripts/ingest_rag_corpus.py \\
    --project-id digital-twin-492318 \\
    --files ./knowledge.txt ./Profile.pdf

Default --region is us-central1. If Google blocks RAG there, stderr describes a backup path
(Terraform rag_corpus_ingest_region + ingest --region); see terraform/README.md → RAG backup.

Before create_corpus, the script calls UpdateRagEngineConfig (Basic or Scaled from TF_VAR_rag_engine_tier,
default BASIC) if the regional RAG Engine is still unprovisioned — same API Google’s error text refers to.

If rag.import_files fails with 500 after upload: terraform apply (RAG Engine + corpus bucket IAM);
see terraform/README.md → RAG.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from google.api_core import exceptions as gcp_exceptions

# When us-central1 RAG is allowlist-blocked, Google points you at other supported regions; this is
# the usual GA choice for ingest. Cloud Run / Gemini can stay us-central1; retrieval uses the
# region embedded in RAG_CORPUS_RESOURCE (see rag_vertex.py).
BACKUP_RAG_REGION = "europe-west4"


def _is_rag_region_allowlist_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "allowlisted" in msg and "rag engine" in msg


def _is_rag_engine_unprovisioned_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "unprovisioned" in msg and "rag engine" in msg


def _terraform_corpus_bucket(repo_root: Path) -> str:
    tf_dir = repo_root / "terraform"
    # Terraform expects -chdir=DIR as one argv token (not "-chdir" "DIR").
    r = subprocess.run(
        ["terraform", f"-chdir={tf_dir}", "output", "-raw", "corpus_bucket_name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        raise SystemExit(
            "Could not read terraform output corpus_bucket_name. "
            "Pass --bucket BUCKET or run from repo root after terraform apply."
        )
    name = (r.stdout or "").strip()
    if not name:
        raise SystemExit("corpus_bucket_name output is empty.")
    return name


def _upload(
    project_id: str,
    bucket_name: str,
    gcs_prefix: str,
    local_paths: list[Path],
) -> list[str]:
    from google.cloud import storage

    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    gs_uris: list[str] = []
    for p in local_paths:
        if not p.is_file():
            raise SystemExit(f"Not a file: {p}")
        dest = f"{gcs_prefix.strip('/')}/{p.name}"
        blob = bucket.blob(dest)
        blob.upload_from_filename(str(p))
        uri = f"gs://{bucket_name}/{dest}"
        gs_uris.append(uri)
        print(f"Uploaded {p} -> {uri}")
    return gs_uris


def _desired_rag_managed_db_tier():
    """Match Terraform default `rag_engine_tier` (variables.tf): BASIC unless TF_VAR_rag_engine_tier=SCALED."""
    from vertexai import rag

    raw = (os.environ.get("TF_VAR_rag_engine_tier") or "BASIC").strip().upper()
    if raw == "SCALED":
        return rag.Scaled(), "Scaled"
    return rag.Basic(), "Basic"


def _ensure_vertex_rag_engine_ready(project_id: str, region: str) -> None:
    """PATCH RagEngineConfig to Basic/Scaled when API still reports unprovisioned (common after create drift)."""
    from vertexai import rag

    name = f"projects/{project_id}/locations/{region}/ragEngineConfig"
    tier_obj, tier_label = _desired_rag_managed_db_tier()

    try:
        cfg = rag.get_rag_engine_config(name=name)
        t = cfg.rag_managed_db_config.tier if cfg.rag_managed_db_config else None
        if isinstance(t, (rag.Basic, rag.Scaled)):
            return
    except ValueError:
        # API shape not mapped by SDK (e.g. transitional states) — drive tier with PATCH.
        pass
    except gcp_exceptions.NotFound:
        pass

    print(
        f"Vertex RAG Engine in {region!r} needs an active managed DB tier; "
        f"UpdateRagEngineConfig → {tier_label} (waits for LRO)…",
        file=sys.stderr,
    )
    rag.update_rag_engine_config(
        rag_engine_config=rag.RagEngineConfig(
            name=name,
            rag_managed_db_config=rag.RagManagedDbConfig(tier=tier_obj),
        ),
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Upload corpus files and ingest into Vertex RAG.")
    parser.add_argument(
        "--project-id",
        default=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("TF_VAR_project_id", ""),
        help="GCP project id (or set GOOGLE_CLOUD_PROJECT / TF_VAR_project_id)",
    )
    parser.add_argument(
        "--region",
        default="us-central1",
        help=(
            "Vertex location for RAG corpus create/import; must match a region where "
            "google_vertex_ai_rag_engine_config exists (default: same as Terraform var.region)."
        ),
    )
    parser.add_argument(
        "--bucket",
        default="",
        help="Corpus GCS bucket name; if omitted, uses terraform output corpus_bucket_name",
    )
    parser.add_argument(
        "--prefix",
        default="rag-sources",
        help="Object prefix inside the corpus bucket (default rag-sources)",
    )
    parser.add_argument(
        "--display-name",
        default="digital-twin-knowledge",
        help="Display name for the new RAG corpus",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        type=Path,
        help="Local files to upload (e.g. knowledge.txt Profile.pdf)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Skip GCS upload; --files are ignored. Import gs://bucket/prefix/ only.",
    )
    parser.add_argument(
        "--import-result-sink",
        default="",
        help=(
            "Optional gs://bucket/path/unique.ndjson (object must not exist). "
            "Vertex writes per-file import status — useful when debugging failed imports."
        ),
    )
    parser.add_argument(
        "--import-retries",
        type=int,
        default=3,
        help="Retries for rag.import_files on 5xx (default 3).",
    )
    parser.add_argument(
        "--corpus-resource-name",
        default="",
        help=(
            "Skip create_corpus; import into this full RagCorpus resource name "
            "(projects/.../locations/REGION/ragCorpora/ID). Vertex location is taken from the name "
            "when possible; otherwise use --region."
        ),
    )
    args = parser.parse_args()

    if not args.project_id.strip():
        raise SystemExit("Set --project-id or GOOGLE_CLOUD_PROJECT or TF_VAR_project_id.")

    pid = args.project_id.strip()
    if pid.upper() == "YOUR_PROJECT_ID" or pid in ("<project-id>", "PROJECT_ID", "my-gcp-project"):
        raise SystemExit(
            f"--project-id was left as a documentation placeholder ({pid!r}). "
            "Use your real GCP project id (e.g. gcloud config get-value project) or export "
            "GOOGLE_CLOUD_PROJECT. It must match the project where Vertex AI RAG and the corpus "
            "bucket live (see RAG_CORPUS_RESOURCE / terraform outputs)."
        )

    bucket = args.bucket.strip()
    if not bucket:
        bucket = _terraform_corpus_bucket(repo_root)

    import vertexai
    from vertexai import rag

    prefix = args.prefix.strip().strip("/")

    if args.skip_upload:
        import_paths = [f"gs://{bucket}/{prefix}"]
        print(f"Importing from prefix {import_paths[0]} (no upload)")
    else:
        paths = [p.resolve() for p in args.files]
        _upload(args.project_id, bucket, prefix, paths)
        import_paths = [f"gs://{bucket}/{prefix}"]

    def _vertex_location_from_corpus_resource(name: str) -> str | None:
        m = re.search(r"/locations/([^/]+)/ragCorpora/", name)
        return m.group(1) if m else None

    corpus_existing = args.corpus_resource_name.strip()
    vertex_location = (
        _vertex_location_from_corpus_resource(corpus_existing) or args.region
        if corpus_existing
        else args.region
    )

    vertexai.init(project=args.project_id, location=vertex_location)

    # Re-ingest (--corpus-resource-name): skip get/update RagEngineConfig. GitHub Actions SAs often
    # have permission to import_files but not aiplatform.ragEngineConfigs.get; the engine must
    # already be provisioned for an existing corpus. First-time create_corpus still runs ensure below
    # (and retries call it on unprovisioned errors).
    if not corpus_existing:
        _ensure_vertex_rag_engine_ready(args.project_id, vertex_location)

    embedding_model_config = rag.RagEmbeddingModelConfig(
        vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
            publisher_model="publishers/google/models/text-embedding-005"
        )
    )

    def _exit_rag_region_allowlist(attempted_region: str) -> None:
        print(
            f"RAG corpus creation was rejected in {attempted_region!r}. "
            "Google restricts RAG Engine to allowlisted projects in some regions (often us-central1).\n",
            file=sys.stderr,
        )
        if attempted_region.lower() != BACKUP_RAG_REGION.lower():
            print(
                "Backup plan (corpus + retrieval in another supported region; API/Gemini stay us-central1):\n"
                f"  1) In terraform.tfvars: rag_corpus_ingest_region = \"{BACKUP_RAG_REGION}\"\n"
                "  2) cd terraform && terraform apply\n"
                f"  3) python3 scripts/ingest_rag_corpus.py --project-id YOUR_ID "
                f'--region {BACKUP_RAG_REGION} --files "./rag-sources/knowledge.txt" "./rag-sources/Profile.pdf"\n'
                "  4) Set rag_corpus_resource_name (Terraform) and RAG_CORPUS_RESOURCE (GitHub) to the "
                "printed resource name, then terraform apply / deploy.\n"
                "\n"
                "Supported regions: https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/rag-overview#supported-regions\n",
                file=sys.stderr,
            )
        print(
            "To use RAG in us-central1 instead, contact the channel in Google’s error "
            "(e.g. vertex-ai-rag-engine-support@google.com) to request allowlisting.\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if corpus_existing:
        rag_corpus = SimpleNamespace(name=corpus_existing)
        print(
            f"Using existing corpus {corpus_existing} (Vertex location {vertex_location}).",
            file=sys.stderr,
        )
    else:
        rag_corpus = None
        for corpus_try in range(2):
            try:
                rag_corpus = rag.create_corpus(
                    display_name=args.display_name,
                    backend_config=rag.RagVectorDbConfig(
                        rag_embedding_model_config=embedding_model_config,
                    ),
                )
                break
            except gcp_exceptions.InvalidArgument as e:
                if _is_rag_region_allowlist_error(e):
                    _exit_rag_region_allowlist(args.region)
                raise
            except gcp_exceptions.FailedPrecondition as e:
                if _is_rag_engine_unprovisioned_error(e) and corpus_try == 0:
                    print(
                        "create_corpus: still unprovisioned; re-applying tier and retrying once after 30s…",
                        file=sys.stderr,
                    )
                    _ensure_vertex_rag_engine_ready(args.project_id, vertex_location)
                    time.sleep(30)
                    continue
                raise
            except RuntimeError as e:
                cause = e.__cause__
                if cause is not None and _is_rag_region_allowlist_error(cause):
                    _exit_rag_region_allowlist(args.region)
                if (
                    cause is not None
                    and _is_rag_engine_unprovisioned_error(cause)
                    and corpus_try == 0
                ):
                    print(
                        "create_corpus: still unprovisioned; re-applying tier and retrying once after 30s…",
                        file=sys.stderr,
                    )
                    _ensure_vertex_rag_engine_ready(args.project_id, vertex_location)
                    time.sleep(30)
                    continue
                raise
        if rag_corpus is None:
            raise SystemExit("rag.create_corpus failed after retry.")

    sink = args.import_result_sink.strip()
    import_kw: dict = {}
    if sink:
        import_kw["import_result_sink"] = sink

    for attempt in range(max(1, args.import_retries)):
        if attempt:
            delay = min(60, 5 * (2 ** (attempt - 1)))
            print(f"Import retry {attempt + 1}/{args.import_retries} after {delay}s...", file=sys.stderr)
            time.sleep(delay)
        try:
            rag.import_files(
                rag_corpus.name,
                import_paths,
                transformation_config=rag.TransformationConfig(
                    chunking_config=rag.ChunkingConfig(
                        chunk_size=512,
                        chunk_overlap=100,
                    ),
                ),
                max_embedding_requests_per_min=1000,
                timeout=3600,
                **import_kw,
            )
            break
        except (gcp_exceptions.InternalServerError, gcp_exceptions.ServiceUnavailable):
            if attempt >= args.import_retries - 1:
                tail = f"\nPer-file import details: {sink}" if sink else ""
                print(
                    f"RAG import failed after {args.import_retries} attempt(s).{tail}\n"
                    "Fix: terraform apply (RAG Engine in --region + corpus bucket IAM for "
                    "Vertex AI Service Agent). See terraform/README.md → RAG.",
                    file=sys.stderr,
                )
                raise

    resource = rag_corpus.name
    print("")
    print("RAG import finished.")
    if corpus_existing:
        print(f"Corpus unchanged: {resource!r} (re-ingest only; no TF_VAR / env update needed).")
    else:
        print("Wire the API with:")
        print("")
        print(f"  export TF_VAR_rag_corpus_resource_name={resource!r}")
        print("")
        print("Cloud Run / GitHub Actions variable RAG_CORPUS_RESOURCE: same string, no TF_VAR_ prefix.")
    print("")
    print(
        f"(Corpus Vertex location: {vertex_location} — retrieval uses this; Gemini uses GCP_REGION from the app.)"
    )
    print("")


if __name__ == "__main__":
    main()
