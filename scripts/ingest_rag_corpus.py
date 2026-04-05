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
    --region europe-west4 \\
    --files ./knowledge.txt ./Profile.pdf

Note: RAG Engine in us-central1 (and us-east1 / us-east4) is allowlist-only for many new
projects. Default --region is europe-west4 (GA). Gemini can stay in us-central1; the API
reads the corpus region from RAG_CORPUS_RESOURCE for retrieval.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


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
        default="europe-west4",
        help=(
            "Vertex location for RAG corpus create/import. "
            "us-central1 / us-east1 / us-east4 are allowlist-only for many new projects; "
            "try europe-west4 or europe-west3. GCS bucket can stay in any region."
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
    args = parser.parse_args()

    if not args.project_id.strip():
        raise SystemExit("Set --project-id or GOOGLE_CLOUD_PROJECT or TF_VAR_project_id.")

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

    vertexai.init(project=args.project_id, location=args.region)

    embedding_model_config = rag.RagEmbeddingModelConfig(
        vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
            publisher_model="publishers/google/models/text-embedding-005"
        )
    )
    rag_corpus = rag.create_corpus(
        display_name=args.display_name,
        backend_config=rag.RagVectorDbConfig(
            rag_embedding_model_config=embedding_model_config,
        ),
    )

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
    )

    resource = rag_corpus.name
    print("")
    print("RAG corpus is ready. Wire the API with:")
    print("")
    print(f"  export TF_VAR_rag_corpus_resource_name={resource!r}")
    print("")
    print("Cloud Run / GitHub Actions variable RAG_CORPUS_RESOURCE: same string, no TF_VAR_ prefix.")
    print("")
    print(f"(Corpus Vertex location: {args.region} — retrieval uses this; GCP_REGION can stay us-central1 for Gemini.)")
    print("")


if __name__ == "__main__":
    main()
