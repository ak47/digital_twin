#!/usr/bin/env python3
"""Upload NYC/CA crash CSVs to GCS and load them into BigQuery.

GitHub Actions (recommended): workflow **Load crash data** downloads public CSVs,
uploads to the Terraform-managed bucket, and loads BigQuery tables. No local steps.

  # Manual / local (optional)
  uv run python scripts/load_crash_data.py \\
    --project-id YOUR_PROJECT_ID \\
    --bucket "$(terraform -chdir=terraform output -raw crash_data_bucket_name)" \\
    --download
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from google.cloud import bigquery, storage

# Local filename -> BigQuery table id
FILE_TABLE_MAP: dict[str, str] = {
    "Motor_Vehicle_Collisions_-_Crashes_20251007.csv": "nyc_crashes",
    "2025crashes.csv": "ca_crashes",
    "2025parties.csv": "ca_parties",
    "2025injuredwitnesspassengers.csv": "ca_injuredwitnesspassengers",
}

# NYC Open Data: Motor Vehicle Collisions - Crashes (dataset id h9gi-nx95)
NYC_CRASHES_DOWNLOAD_URL = (
    "https://data.cityofnewyork.us/api/views/h9gi-nx95/rows.csv?accessType=DOWNLOAD"
)

CA_CCRS_PACKAGE_API = "https://data.ca.gov/api/3/action/package_show?id=ccrs"

# data.ca.gov resource display name -> local canonical filename
CA_RESOURCE_NAME_TO_FILE: dict[str, str] = {
    "Crashes_2025": "2025crashes.csv",
    "Parties_2025": "2025parties.csv",
    "InjuredWitnessPassengers_2025": "2025injuredwitnesspassengers.csv",
}

# Used when the CKAN API is unreachable
CA_FALLBACK_URLS: dict[str, str] = {
    "2025crashes.csv": (
        "https://data.ca.gov/dataset/80c6a49d-c6b3-40ba-86d8-379c9741b4be/resource/"
        "9f4fc839-122d-4595-a146-43bc4ed16f46/download/crashes_2025.csv"
    ),
    "2025parties.csv": (
        "https://data.ca.gov/dataset/80c6a49d-c6b3-40ba-86d8-379c9741b4be/resource/"
        "a2676918-a825-4b77-8e5c-6eadb38d6b1a/download/parties_2025.csv"
    ),
    "2025injuredwitnesspassengers.csv": (
        "https://data.ca.gov/dataset/80c6a49d-c6b3-40ba-86d8-379c9741b4be/resource/"
        "10184ea3-7411-42d8-87a6-17039b58f04b/download/injuredwitnesspassengers_2025.csv"
    ),
}

_USER_AGENT = "digital-twin-crash-loader/1.0"
GCS_PREFIX = "crash-sources"
_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024


def resolve_download_urls() -> dict[str, str]:
    """Resolve open-data download URLs for all canonical CSV files."""
    urls: dict[str, str] = {
        "Motor_Vehicle_Collisions_-_Crashes_20251007.csv": NYC_CRASHES_DOWNLOAD_URL,
    }

    try:
        req = urllib.request.Request(
            CA_CCRS_PACKAGE_API,
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        for resource in payload.get("result", {}).get("resources", []):
            name = (resource.get("name") or "").strip()
            local_name = CA_RESOURCE_NAME_TO_FILE.get(name)
            url = (resource.get("url") or "").strip()
            if local_name and url:
                urls[local_name] = url
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        print(f"warning: California URL lookup failed ({exc}); using fallback URLs")

    for local_name, fallback_url in CA_FALLBACK_URLS.items():
        urls.setdefault(local_name, fallback_url)

    missing = [name for name in FILE_TABLE_MAP if name not in urls]
    if missing:
        raise RuntimeError(f"Missing download URLs for: {', '.join(missing)}")
    return urls


def download_sources(dest_dir: Path, urls: dict[str, str] | None = None) -> Path:
    """Download canonical CSV files from open-data URLs into dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    source_urls = urls or resolve_download_urls()
    for filename in FILE_TABLE_MAP:
        url = source_urls[filename]
        dest = dest_dir / filename
        print(f"Downloading {url}")
        print(f"  -> {dest}")
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as out:
                while True:
                    chunk = resp.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Download failed for {filename}: HTTP {exc.code} from {url}"
            ) from exc
        size = dest.stat().st_size
        if size == 0:
            raise RuntimeError(f"Download failed for {filename}: empty file from {url}")
        print(f"  saved {size:,} bytes")
    return dest_dir


def upload_sources(source_dir: Path, bucket_name: str) -> list[str]:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    uris: list[str] = []
    for filename in FILE_TABLE_MAP:
        local_path = source_dir / filename
        if not local_path.is_file():
            raise FileNotFoundError(f"Missing source file: {local_path}")
        blob_name = f"{GCS_PREFIX}/{filename}"
        blob = bucket.blob(blob_name)
        print(f"Uploading {local_path} -> gs://{bucket_name}/{blob_name}")
        blob.upload_from_filename(str(local_path))
        uris.append(f"gs://{bucket_name}/{blob_name}")
    return uris


def load_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    gcs_uri: str,
) -> None:
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,
        allow_jagged_rows=True,
        ignore_unknown_values=True,
    )
    print(f"Loading {gcs_uri} -> {table_ref}")
    job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    job.result()
    table = client.get_table(table_ref)
    print(f"  loaded {table.num_rows:,} rows into {table_ref}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset", default="vehicle_crashes")
    parser.add_argument("--bucket", required=True, help="GCS bucket from terraform output crash_data_bucket_name")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Local directory containing the four crash CSV files (required unless --skip-upload)",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Load from gs://bucket/crash-sources/ without uploading local files",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download CSVs from NYC Open Data / data.ca.gov before upload (implies not --skip-upload)",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("/tmp/crash-sources"),
        help="Directory for --download (default: /tmp/crash-sources)",
    )
    args = parser.parse_args(argv)

    if args.download:
        args.skip_upload = False
        download_sources(args.download_dir)
        args.source_dir = args.download_dir

    if not args.skip_upload and not args.source_dir:
        parser.error("--source-dir, --download, or --skip-upload is required")

    bq = bigquery.Client(project=args.project_id)

    for filename, table_id in FILE_TABLE_MAP.items():
        gcs_uri = f"gs://{args.bucket}/{GCS_PREFIX}/{filename}"
        if not args.skip_upload:
            if args.source_dir is None:
                parser.error("--source-dir is required unless --skip-upload is set")
            local_path = args.source_dir / filename
            if not local_path.is_file():
                print(f"error: missing {local_path}", file=sys.stderr)
                return 1

    if not args.skip_upload:
        assert args.source_dir is not None
        upload_sources(args.source_dir, args.bucket)

    for filename, table_id in FILE_TABLE_MAP.items():
        gcs_uri = f"gs://{args.bucket}/{GCS_PREFIX}/{filename}"
        load_table(bq, args.project_id, args.dataset, table_id, gcs_uri)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
