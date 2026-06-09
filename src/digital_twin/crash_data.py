"""Readonly BigQuery access for NYC and California motor vehicle crash datasets."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|drop|create|merge|truncate|alter|grant|revoke|"
    r"call|execute|export|load|copy|begin|commit|rollback|set|declare|with\s+recursive"
    r")\b",
    re.IGNORECASE,
)

_DEFAULT_ROW_LIMIT = 100
_MAX_BYTES_BILLED = 500_000_000  # 500 MB per query

_TABLES = (
    "nyc_crashes",
    "ca_crashes",
    "ca_parties",
    "ca_injuredwitnesspassengers",
)


def _qualify_table_names(sql: str, project_id: str, dataset_id: str) -> str:
    """Qualify bare crash table ids in FROM/JOIN clauses (not string literals)."""
    if "INFORMATION_SCHEMA" in sql.upper():
        return sql
    qualified = sql
    for table in _TABLES:
        fq = f"`{project_id}.{dataset_id}.{table}`"
        if fq in qualified:
            continue
        qualified = re.sub(
            rf"(?i)\b(FROM|JOIN)\s+{re.escape(table)}\b",
            rf"\1 {fq}",
            qualified,
        )
    return qualified


def validate_readonly_sql(sql: str, *, max_rows: int = _DEFAULT_ROW_LIMIT) -> str:
    """Return sanitized SELECT SQL with a row cap when missing."""
    text = (sql or "").strip()
    if not text:
        raise ValueError("SQL query is empty.")
    if ";" in text.rstrip(";"):
        raise ValueError("Multiple SQL statements are not allowed.")
    text = text.rstrip(";").strip()
    if not re.match(r"(?is)^select\b", text):
        raise ValueError("Only SELECT queries are allowed.")
    if _FORBIDDEN.search(text):
        raise ValueError("Query contains disallowed SQL keywords.")
    if not re.search(r"(?is)\blimit\b", text):
        text = f"{text}\nLIMIT {max_rows}"
    return text


def schema_instruction(project_id: str, dataset_id: str) -> str:
    """System prompt block describing BigQuery tables for the model."""
    fq = f"`{project_id}.{dataset_id}"
    return f"""## Crash data (BigQuery tool)

When the user asks about NYC or California motor vehicle crashes, crash hotspots, borough trends, collision types, injuries, or related analytics, call **`query_crash_data`** with BigQuery Standard SQL instead of guessing numbers.

Tables (fully qualified):
- `{fq}.nyc_crashes` — NYC Open Data collisions (~2.2M rows, 2013–2024). Key columns include `CRASH_DATE`, `BOROUGH`, `LATITUDE`, `LONGITUDE`, `ON_STREET_NAME`, `NUMBER_OF_PERSONS_INJURED`, `NUMBER_OF_PERSONS_KILLED`, `NUMBER_OF_CYCLIST_INJURED`, `NUMBER_OF_PEDESTRIANS_INJURED`, `CONTRIBUTING_FACTOR_VEHICLE_1`, `COLLISION_ID`.
- `{fq}.ca_crashes` — California CCRS 2025 crashes (~398K rows). All columns loaded as **STRING**. Uses **underscore** names: `Collision_Id`, `Report_Number`, `Crash_Date_Time` (e.g. `1/10/2025 8:28:00 AM`), `City_Name`, `Collision_Type_Description`, `NumberInjured`, `NumberKilled`, `Weather_1`, `HitRun`, `Latitude`, `Longitude`, `PrimaryRoad` (not `Primary_Road`). Use `PARSE_TIMESTAMP('%m/%d/%Y %I:%M:%S %p', Crash_Date_Time)` for date filters.
- `{fq}.ca_parties` — California parties/vehicles per collision (~535K rows). All STRING. Uses **PascalCase** names (no underscores): `CollisionId`, `PartyId`, `PartyType`, `Vehicle1TypeDesc`, `Vehicle2TypeDesc`, `Vehicle1Make`, `Vehicle2Make`, `StreetOrHighwayName`. **Join:** `ca_crashes.Collision_Id = ca_parties.CollisionId` (note the different column spellings).
- `{fq}.ca_injuredwitnesspassengers` — injured persons (~329K rows). PascalCase: `CollisionId`, `InjuredWitPassId`, `ExtentOfInjuryCode`, `InjuredPersonType`. **Join:** `ca_crashes.Collision_Id = ca_injuredwitnesspassengers.CollisionId`.

Rules:
- Use **only** SELECT queries via the tool for live stats.
- Prefer aggregations (`COUNT`, `GROUP BY`) over returning raw rows.
- California tables are all STRING — use `SAFE_CAST(... AS INT64)` for numeric aggregates; parse dates with `PARSE_TIMESTAMP` as shown above.
- Do **not** query `INFORMATION_SCHEMA` — column names are listed above. After one failed query, fix column names and answer; do not burn multiple rounds on schema discovery.
- Motorcycle crashes in CA: filter `ca_parties.Vehicle1TypeDesc = 'Motorcycle'` or `Vehicle2TypeDesc = 'Motorcycle'` (exact value, not `LIKE '%MOTORCYCLE%'`).
- Always include a reasonable `LIMIT` (the tool adds one if missing).
- Answer crash questions in the first person as things **I** know from building this dataset and querying it.
- Do **not** use crash query results as biographical facts about my career unless the user is asking about this project specifically.
- If the tool fails or the dataset is unavailable, say you cannot query the live data right now; do not invent statistics."""


def execute_query(
    project_id: str,
    dataset_id: str,
    sql: str,
    *,
    max_rows: int = _DEFAULT_ROW_LIMIT,
) -> str:
    """Run a validated readonly query and return JSON text for the model."""
    if not project_id or not dataset_id:
        return json.dumps({"error": "Crash data BigQuery dataset is not configured."})

    safe_sql = validate_readonly_sql(sql, max_rows=max_rows)
    safe_sql = _qualify_table_names(safe_sql, project_id, dataset_id)

    try:
        from google.cloud import bigquery
        import google.auth
    except ImportError:
        return json.dumps({"error": "google-cloud-bigquery is not installed."})

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if hasattr(credentials, "with_quota_project"):
        credentials = credentials.with_quota_project(project_id)
    client = bigquery.Client(project=project_id, credentials=credentials)
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=_MAX_BYTES_BILLED)
    try:
        job = client.query(safe_sql, job_config=job_config)
        rows = list(job.result(max_results=max_rows + 1))
    except Exception as e:
        logger.warning(
            "crash_data query failed",
            extra={"event": "crash_data_query_failed", "sql": safe_sql, "error": str(e)},
        )
        return json.dumps({"error": str(e), "sql": safe_sql})

    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]

    payload: dict[str, Any] = {
        "row_count": len(rows),
        "rows": [dict(row.items()) for row in rows],
        "sql": safe_sql,
    }
    if truncated:
        payload["truncated"] = True
    return json.dumps(payload, default=str)
