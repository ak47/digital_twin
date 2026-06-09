#!/usr/bin/env python3
"""Run a readonly crash-data SQL query locally (same path as the digital twin tool).

Usage:
  export GCP_PROJECT_ID=your-project
  export CRASH_DATA_BQ_DATASET=vehicle_crashes
  uv run python scripts/debug_crash_query.py "SELECT COUNT(*) AS n FROM ca_crashes"
"""

from __future__ import annotations

import json
import os
import sys

from digital_twin.crash_data import execute_query


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: debug_crash_query.py '<SQL SELECT>'", file=sys.stderr)
        return 1

    project = (os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    dataset = (os.environ.get("CRASH_DATA_BQ_DATASET") or "vehicle_crashes").strip()
    if not project:
        print("Set GCP_PROJECT_ID to the project that owns vehicle_crashes (e.g. digital-twin-492318).", file=sys.stderr)
        return 1

    try:
        import google.auth

        _, adc_project = google.auth.default()
        if adc_project and adc_project != project:
            print(
                f"note: ADC default project is {adc_project}; using GCP_PROJECT_ID={project} for BigQuery.",
                file=sys.stderr,
            )
    except Exception:
        pass

    sql = " ".join(args)
    result = execute_query(project, dataset, sql)
    print(json.dumps(json.loads(result), indent=2, default=str))
    return 0 if '"error"' not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
