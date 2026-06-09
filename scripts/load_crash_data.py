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
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from io import StringIO
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
_CA_TABLE_IDS = frozenset({"ca_crashes", "ca_parties", "ca_injuredwitnesspassengers"})


def normalize_redirect_url(url: str) -> str:
    """Fix data.ca.gov redirects that break AWS SigV4 presigned URLs in urllib."""
    return url.replace("s3.amazonaws.com:443", "s3.amazonaws.com")


def _download_opener() -> urllib.request.OpenerDirector:
    class _OpenDataRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
            return super().redirect_request(
                req, fp, code, msg, headers, normalize_redirect_url(newurl)
            )

    return urllib.request.build_opener(_OpenDataRedirectHandler())


def download_file(url: str, dest: Path, *, opener: urllib.request.OpenerDirector | None = None) -> int:
    """Stream url to dest; return bytes written."""
    client = opener or _download_opener()
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with client.open(req, timeout=600) as resp, dest.open("wb") as out:
        total = 0
        while True:
            chunk = resp.read(_DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)
    return total


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
        try:
            size = download_file(url, dest)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Download failed for {filename}: HTTP {exc.code} from {url}"
            ) from exc
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


def split_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got {gcs_uri!r}")
    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    return bucket_name, blob_name


def sanitize_column_name(name: str, *, index: int) -> str:
    """Approximate BigQuery column-name V2 sanitization for CSV headers."""
    text = name.replace("\t", " ").strip()
    text = re.sub(r"[^0-9A-Za-z_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = f"col_{index}"
    if text[0].isdigit():
        text = f"col_{text}"
    return text


def unique_column_names(raw_names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for index, raw in enumerate(raw_names):
        base = sanitize_column_name(raw, index=index)
        count = seen.get(base, 0) + 1
        seen[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out


def parse_csv_header_line(header_line: str) -> list[str]:
    return next(csv.reader(StringIO(header_line.lstrip("\ufeff"))))


def string_schema_from_header_line(header_line: str) -> list[bigquery.SchemaField]:
    columns = unique_column_names(parse_csv_header_line(header_line))
    return [bigquery.SchemaField(name, "STRING") for name in columns]


def read_csv_header_line_from_gcs(gcs_uri: str, *, storage_client: storage.Client | None = None) -> str:
    bucket_name, blob_name = split_gcs_uri(gcs_uri)
    client = storage_client or storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    chunk = blob.download_as_bytes(start=0, end=262144)
    return chunk.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def read_csv_header_line_from_path(path: Path) -> str:
    with path.open("rb") as handle:
        chunk = handle.read(262144)
    return chunk.split(b"\n", 1)[0].decode("utf-8-sig", errors="replace")


def load_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    gcs_uri: str,
    *,
    local_csv: Path | None = None,
    storage_client: storage.Client | None = None,
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
        column_name_character_map="V2",
    )
    if table_id in _CA_TABLE_IDS:
        # CCRS exports use tab-padded headers and human-readable datetimes like
        # "1/10/2025 8:28:00 AM" that autodetect rejects. Load all columns as STRING.
        if local_csv is not None and local_csv.is_file():
            header_line = read_csv_header_line_from_path(local_csv)
        else:
            header_line = read_csv_header_line_from_gcs(
                gcs_uri, storage_client=storage_client
            )
        job_config.autodetect = False
        job_config.schema = string_schema_from_header_line(header_line)
        print(f"  using STRING schema ({len(job_config.schema)} columns)")
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
    gcs_client = storage.Client()

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
        local_csv = None
        if args.source_dir is not None:
            candidate = args.source_dir / filename
            if candidate.is_file():
                local_csv = candidate
        load_table(
            bq,
            args.project_id,
            args.dataset,
            table_id,
            gcs_uri,
            local_csv=local_csv,
            storage_client=gcs_client,
        )

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
