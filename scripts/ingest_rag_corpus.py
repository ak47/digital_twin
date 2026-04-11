#!/usr/bin/env -S uv run python
"""
Upload local files to the Terraform corpus GCS bucket, create a Vertex RAG corpus,
import those objects, then print the resource name for Cloud Run.

Requires: uv sync (or uv sync --extra dev) — google-cloud-aiplatform, google-cloud-storage
Auth: gcloud auth application-default login

Example:
  cd /path/to/digital_twin
  uv run python scripts/ingest_rag_corpus.py \\
    --project-id digital-twin-492318 \\
    --files ./knowledge.txt ./Profile.pdf

Default --region is us-central1. If Google blocks RAG there, stderr describes a backup path
(Terraform rag_corpus_ingest_region + ingest --region); see terraform/README.md → RAG backup.

Before create_corpus, the script calls UpdateRagEngineConfig if the regional RAG Engine is still
unprovisioned (or not yet Serverless): Spanner tier from TF_VAR_rag_engine_deployment_mode
(SPANNER_BASIC / SPANNER_SCALED, default) or Serverless from TF_VAR_rag_engine_deployment_mode=SERVERLESS
(vertexai.preview.rag). Legacy: TF_VAR_rag_engine_tier=BASIC|SCALED maps to SPANNER_*.

If rag.import_files fails with 500 after upload: terraform apply (RAG Engine + corpus bucket IAM);
see terraform/README.md → RAG.

Any failed_rag_files_count from Vertex always exits 1. An all-skipped import (imported=0, skipped>0)
is success: the corpus already had those URIs; the script prints a short conclusion line.
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


def _is_rag_corpus_busy_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "other operations running on the ragcorpus" in msg


def _extract_rag_operation_ids(exc: BaseException) -> list[str]:
    m = re.search(r"Operation IDs are:\s*\[([^\]]+)\]", str(exc), flags=re.IGNORECASE)
    if not m:
        return []
    return [op.strip() for op in m.group(1).split(",") if op.strip()]


def _wait_for_vertex_operations(
    op_ids: list[str],
    *,
    project_id: str,
    region: str,
    timeout_seconds: int,
) -> bool:
    """Best-effort wait for blocking Vertex operation ids to finish."""
    if not op_ids:
        return False
    deadline = time.time() + max(0, timeout_seconds)
    while time.time() < deadline:
        pending: list[str] = []
        for op_id in op_ids:
            r = subprocess.run(
                [
                    "gcloud",
                    "ai",
                    "operations",
                    "describe",
                    op_id,
                    "--region",
                    region,
                    "--project",
                    project_id,
                    "--format=value(done,error.code,error.message)",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode != 0:
                # If we cannot inspect, keep waiting using timeout budget.
                pending.append(op_id)
                continue
            out = (r.stdout or "").strip()
            done_flag = out.split(";")[0].strip().lower() if out else ""
            if done_flag not in ("true", "1", "yes"):
                pending.append(op_id)
        if not pending:
            return True
        print(
            f"Waiting for blocking Vertex operation(s): {', '.join(pending)}",
            file=sys.stderr,
        )
        time.sleep(15)
    return False


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


def _dump_import_result_sink(uri: str, project_id: str, *, max_bytes: int = 96 * 1024) -> None:
    """Print gs://… NDJSON written by Vertex import_result_sink (best-effort)."""
    if not uri.startswith("gs://"):
        return
    tail = uri[5:]
    slash = tail.find("/")
    if slash < 0:
        return
    bucket_name, blob_path = tail[:slash], tail[slash + 1 :]
    try:
        from google.cloud import storage

        client = storage.Client(project=project_id)
        blob = client.bucket(bucket_name).blob(blob_path)
        if not blob.exists():
            print(
                f"import_result_sink not found yet ({uri!r}) — LRO may have failed before flush.\n"
                f"Try: gcloud storage cat {uri!r}",
                file=sys.stderr,
            )
            return
        data = blob.download_as_bytes(timeout=120)
    except Exception as e:
        print(
            f"Could not read import_result_sink ({uri!r}): {e}\n"
            f"Try: gcloud storage cat {uri!r}",
            file=sys.stderr,
        )
        return
    text = data[:max_bytes].decode("utf-8", errors="replace")
    print(f"\n--- import_result_sink ({uri}) ---\n{text}", file=sys.stderr)
    if len(data) > max_bytes:
        print(f"... truncated ({len(data)} bytes total)", file=sys.stderr)


def _rag_deployment_mode() -> str:
    """Align with Terraform var rag_engine_deployment_mode (TF_VAR_rag_engine_deployment_mode)."""
    raw = (
        os.environ.get("TF_VAR_rag_engine_deployment_mode")
        or os.environ.get("RAG_ENGINE_DEPLOYMENT_MODE")
        or ""
    ).strip().upper()
    if raw in ("SPANNER_BASIC", "SPANNER_SCALED", "SERVERLESS"):
        return raw
    # Legacy: removed Terraform var rag_engine_tier — still honor for local one-off runs.
    legacy = (os.environ.get("TF_VAR_rag_engine_tier") or "BASIC").strip().upper()
    if legacy == "SCALED":
        return "SPANNER_SCALED"
    return "SPANNER_BASIC"


def _desired_spanner_tier():
    """Spanner mode only: Basic vs Scaled."""
    from vertexai import rag

    if _rag_deployment_mode() == "SPANNER_SCALED":
        return rag.Scaled(), "Scaled"
    return rag.Basic(), "Basic"


def _ensure_vertex_rag_engine_serverless(project_id: str, region: str) -> None:
    """PATCH RagEngineConfig to Serverless (Vertex AI preview API; documented us-central1-only)."""
    from vertexai.preview import rag as pr

    name = f"projects/{project_id}/locations/{region}/ragEngineConfig"
    if region.strip() != "us-central1":
        print(
            f"Warning: Vertex RAG Serverless is documented as us-central1-only; using region {region!r}.",
            file=sys.stderr,
        )

    try:
        cfg = pr.get_rag_engine_config(name=name)
        mdc = cfg.rag_managed_db_config
        if mdc and mdc.mode is not None and isinstance(mdc.mode, pr.Serverless):
            return
    except (RuntimeError, ValueError, gcp_exceptions.NotFound):
        pass

    print(
        f"Vertex RAG Engine in {region!r}: UpdateRagEngineConfig → Serverless (waits for LRO)…",
        file=sys.stderr,
    )
    pr.update_rag_engine_config(
        rag_engine_config=pr.RagEngineConfig(
            name=name,
            rag_managed_db_config=pr.RagManagedDbConfig(mode=pr.Serverless()),
        ),
    )


def _ensure_vertex_rag_engine_ready(project_id: str, region: str) -> None:
    """PATCH RagEngineConfig: Serverless or Spanner Basic/Scaled when still inactive / wrong mode."""
    if _rag_deployment_mode() == "SERVERLESS":
        _ensure_vertex_rag_engine_serverless(project_id, region)
        return

    from vertexai import rag

    name = f"projects/{project_id}/locations/{region}/ragEngineConfig"
    tier_obj, tier_label = _desired_spanner_tier()

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
            "Vertex location for RAG corpus create/import. For Spanner mode, Terraform must have "
            "google_vertex_ai_rag_engine_config in this region. For SERVERLESS, use us-central1 "
            "(documented region for Serverless RAG)."
        ),
    )
    parser.add_argument(
        "--rag-engine-deployment-mode",
        default="",
        metavar="MODE",
        help="Override TF_VAR_rag_engine_deployment_mode: SPANNER_BASIC, SPANNER_SCALED, or SERVERLESS.",
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
        "--import-path",
        action="append",
        default=[],
        metavar="GS_URI",
        help=(
            "Optional explicit import URI (repeatable), e.g. gs://bucket/rag-sources/knowledge.txt. "
            "When set, these URIs are imported instead of the default gs://bucket/prefix/ path."
        ),
    )
    parser.add_argument(
        "--import-retries",
        type=int,
        default=3,
        help="Retries for rag.import_files on transient 5xx and corpus-locked errors (default 3).",
    )
    parser.add_argument(
        "--max-embedding-requests-per-min",
        type=int,
        default=1000,
        help="Vertex import max_embedding_requests_per_min (default 1000). Lower for stability if imports 500.",
    )
    parser.add_argument(
        "--corpus-busy-timeout-seconds",
        type=int,
        default=900,
        help="Max seconds to wait for blocking RagCorpus operations before giving up (default 900).",
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

    mode_override = (args.rag_engine_deployment_mode or "").strip().upper()
    if mode_override:
        if mode_override not in ("SPANNER_BASIC", "SPANNER_SCALED", "SERVERLESS"):
            raise SystemExit(
                "--rag-engine-deployment-mode must be SPANNER_BASIC, SPANNER_SCALED, or SERVERLESS."
            )
        os.environ["RAG_ENGINE_DEPLOYMENT_MODE"] = mode_override

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
    # Vertex treats GCS "directory" imports as a prefix; trailing / avoids ambiguous object-vs-prefix URIs.
    gcs_dir = f"gs://{bucket}/{prefix}/" if prefix else f"gs://{bucket}/"

    explicit_import_paths = [u.strip() for u in args.import_path if u.strip()]
    if explicit_import_paths:
        bad = [u for u in explicit_import_paths if not u.startswith("gs://")]
        if bad:
            raise SystemExit(f"--import-path must be gs:// URIs. Invalid: {', '.join(bad)}")

    if args.skip_upload:
        import_paths = explicit_import_paths or [gcs_dir]
        if explicit_import_paths:
            print(f"Importing explicit URI(s): {', '.join(import_paths)} (no upload)")
        else:
            print(f"Importing from prefix {import_paths[0]} (no upload)")
    else:
        paths = [p.resolve() for p in args.files]
        _upload(args.project_id, bucket, prefix, paths)
        import_paths = explicit_import_paths or [gcs_dir]
        if explicit_import_paths:
            print(f"Importing explicit URI(s): {', '.join(import_paths)}")

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
                f"  3) uv run python scripts/ingest_rag_corpus.py --project-id YOUR_ID "
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

    imp = skp = fail = 0
    for attempt in range(max(1, args.import_retries)):
        if attempt:
            delay = min(60, 5 * (2 ** (attempt - 1)))
            print(f"Import retry {attempt + 1}/{args.import_retries} after {delay}s...", file=sys.stderr)
            time.sleep(delay)
        try:
            import_resp = rag.import_files(
                rag_corpus.name,
                import_paths,
                transformation_config=rag.TransformationConfig(
                    chunking_config=rag.ChunkingConfig(
                        chunk_size=512,
                        chunk_overlap=100,
                    ),
                ),
                max_embedding_requests_per_min=args.max_embedding_requests_per_min,
                timeout=3600,
                **import_kw,
            )
            imp = int(getattr(import_resp, "imported_rag_files_count", 0) or 0)
            skp = int(getattr(import_resp, "skipped_rag_files_count", 0) or 0)
            fail = int(getattr(import_resp, "failed_rag_files_count", 0) or 0)
            print(
                f"Vertex import result: imported={imp}, skipped={skp}, failed={fail}",
                file=sys.stderr,
            )
            if fail:
                print(
                    "::error::RAG import reported failed_rag_files_count=%s — corpus was not fully updated. "
                    "See --import-result-sink or the Vertex console for this corpus."
                    % fail,
                    file=sys.stderr,
                )
                if sink:
                    _dump_import_result_sink(sink, args.project_id)
                raise SystemExit(1)
            break
        except gcp_exceptions.FailedPrecondition as e:
            if _is_rag_corpus_busy_error(e):
                op_ids = _extract_rag_operation_ids(e)
                waited = _wait_for_vertex_operations(
                    op_ids,
                    project_id=args.project_id,
                    region=vertex_location,
                    timeout_seconds=args.corpus_busy_timeout_seconds,
                )
                if waited:
                    print("Blocking operation(s) finished; retrying import now...", file=sys.stderr)
                    continue
                if attempt < args.import_retries - 1:
                    lock_delay = min(180, 20 * (attempt + 1))
                    op_hint = f" (operation IDs: {', '.join(op_ids)})" if op_ids else ""
                    print(
                        f"Corpus has another import/update in progress{op_hint}; waiting {lock_delay}s and retrying...",
                        file=sys.stderr,
                    )
                    time.sleep(lock_delay)
                    continue
                op_ref = ", ".join(op_ids) if op_ids else "unknown"
                print(
                    "RAG corpus is still busy after retries.\n"
                    f"Blocking operation IDs: {op_ref}\n"
                    "Wait for that operation to complete, then re-run ingest.\n"
                    "Tip: check status in Vertex AI console (RAG > Operations) or with "
                    "'gcloud ai operations describe OPERATION_ID --region us-central1 --project YOUR_PROJECT_ID'.",
                    file=sys.stderr,
                )
            raise
        except RuntimeError as e:
            cause = e.__cause__
            if cause is not None and isinstance(cause, gcp_exceptions.FailedPrecondition) and _is_rag_corpus_busy_error(cause):
                op_ids = _extract_rag_operation_ids(cause)
                waited = _wait_for_vertex_operations(
                    op_ids,
                    project_id=args.project_id,
                    region=vertex_location,
                    timeout_seconds=args.corpus_busy_timeout_seconds,
                )
                if waited:
                    print("Blocking operation(s) finished; retrying import now...", file=sys.stderr)
                    continue
                if attempt < args.import_retries - 1:
                    lock_delay = min(180, 20 * (attempt + 1))
                    op_hint = f" (operation IDs: {', '.join(op_ids)})" if op_ids else ""
                    print(
                        f"Corpus has another import/update in progress{op_hint}; waiting {lock_delay}s and retrying...",
                        file=sys.stderr,
                    )
                    time.sleep(lock_delay)
                    continue
                op_ref = ", ".join(op_ids) if op_ids else "unknown"
                print(
                    "RAG corpus is still busy after retries.\n"
                    f"Blocking operation IDs: {op_ref}\n"
                    "Wait for that operation to complete, then re-run ingest.\n"
                    "Tip: check status in Vertex AI console (RAG > Operations) or with "
                    "'gcloud ai operations describe OPERATION_ID --region us-central1 --project YOUR_PROJECT_ID'.",
                    file=sys.stderr,
                )
            raise
        except gcp_exceptions.PermissionDenied as e:
            msg = str(e).lower()
            if "ragfiles.import" in msg or "rag_files.import" in msg:
                print(
                    "RAG import was denied (aiplatform.ragFiles.import).\n"
                    "Fix: the identity in your ADC token must have roles/aiplatform.user (or equivalent) "
                    "on the GCP project that OWNS the corpus in --corpus-resource-name "
                    "(projects/<id>/locations/… — <id> is often a project number).\n"
                    "GitHub Actions: set GCP_SERVICE_ACCOUNT_EMAIL to terraform output "
                    "github_actions_deployer_email, GCP_PROJECT_ID to the same project, terraform apply "
                    "(github_deploy_vertex_user + corpus_github_deploy_object_viewer), then re-run.\n"
                    "If the token identity already matches that SA, wait a few minutes for IAM propagation.",
                    file=sys.stderr,
                )
            raise
        except (gcp_exceptions.InternalServerError, gcp_exceptions.ServiceUnavailable):
            if attempt >= args.import_retries - 1:
                tail = f"\nPer-file import details: {sink}" if sink else ""
                print(
                    f"RAG import failed after {args.import_retries} attempt(s).{tail}\n"
                    "Fix: terraform apply (RAG Engine in --region + corpus bucket IAM for "
                    "Vertex AI Service Agent). See terraform/README.md → RAG.",
                    file=sys.stderr,
                )
                if sink:
                    _dump_import_result_sink(sink, args.project_id)
                raise

    resource = rag_corpus.name
    print("", file=sys.stderr)
    if imp > 0:
        conclusion = (
            f"Conclusion: success — {imp} new file(s) indexed, {skp} skipped (already in corpus)."
        )
    elif skp > 0:
        conclusion = (
            "Conclusion: success — no new URIs; corpus already contained those objects (idempotent). "
            "If you only overwrote blobs in place, embeddings may still be stale — rename objects or "
            "remove RagFiles in Vertex, then re-import."
        )
    else:
        conclusion = (
            "Conclusion: import call finished with no imported or skipped files — "
            "check that the GCS prefix has objects and matches this corpus."
        )
    print(conclusion, file=sys.stderr)
    print("", file=sys.stderr)
    print("RAG import finished.")
    if corpus_existing:
        print(f"Corpus unchanged: {resource!r} (re-ingest only; no TF_VAR / env update needed).")
    else:
        print("Wire the API with:")
        print("")
        print(f"  export TF_VAR_rag_corpus_resource_name={resource!r}")
        print("")
        print(
            "Cloud Run: set TF_VAR_rag_corpus_resource_name (terraform apply) — same string as RAG_CORPUS_RESOURCE."
        )
    print("")
    print(
        f"(Corpus Vertex location: {vertex_location} — retrieval uses this; Gemini uses GCP_REGION from the app.)"
    )
    print("")


if __name__ == "__main__":
    main()
