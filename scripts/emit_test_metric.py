#!/usr/bin/env python3
"""
Emit a single custom metric point to Cloud Monitoring.

Use this to sanity-check IAM + metric ingestion after deploying.

Example (from a machine with ADC targeting the Cloud Run service account, or from Cloud Run itself):
  export GCP_PROJECT_ID="digital-twin-492318"
  export GCP_REGION="us-central1"
  export K_SERVICE="digital-twin-api"
  export K_REVISION="manual"
  python3 scripts/emit_test_metric.py
"""

from __future__ import annotations

import os
import time

from digital_twin.metrics import record_latency_ms


def main() -> None:
    record_latency_ms(
        "metrics_smoke_latency_ms",
        123.0,
        labels={
            "status": "ok",
            "note": "smoke",
            "service": os.environ.get("K_SERVICE", "unknown"),
        },
    )
    # Give client libs a moment to flush in some environments.
    time.sleep(0.2)
    print("ok")


if __name__ == "__main__":
    main()

