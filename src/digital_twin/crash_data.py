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
- `{fq}.ca_crashes` — California CCRS 2025 crashes (~275K rows). Key columns include `Collision_Id`, `Report_Number`, `Crash_Date_Time`, `City_Name`, `County_Code`, `Collision_Type_Description`, `NumberInjured`, `NumberKilled`, `Weather_1`, `HitRun`, `Latitude`, `Longitude`, `Primary_Road`. Column names use underscores (BigQuery V2 sanitization of the raw CSV headers).
- `{fq}.ca_parties` — California parties/vehicles per collision (~535K rows). Join on `Collision_Id`.
- `{fq}.ca_injuredwitnesspassengers` — injured persons (~329K rows). Join on `Collision_Id`.

Rules:
- Use **only** SELECT queries via the tool for live stats.
- Prefer aggregations (`COUNT`, `GROUP BY`) over returning raw rows.
- If unsure of exact column names, query `INFORMATION_SCHEMA.COLUMNS` for the table first.
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
    for table in _TABLES:
        if table in safe_sql and f"{dataset_id}.{table}" not in safe_sql:
            safe_sql = re.sub(
                rf"(?i)\b{re.escape(table)}\b",
                f"`{project_id}.{dataset_id}.{table}`",
                safe_sql,
            )

    try:
        from google.cloud import bigquery
    except ImportError:
        return json.dumps({"error": "google-cloud-bigquery is not installed."})

    client = bigquery.Client(project=project_id)
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=_MAX_BYTES_BILLED)
    try:
        job = client.query(safe_sql, job_config=job_config)
        rows = list(job.result(max_results=max_rows + 1))
    except Exception as e:
        logger.warning("crash_data query failed: %s", e)
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
