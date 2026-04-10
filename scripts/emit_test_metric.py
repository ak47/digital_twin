#!/usr/bin/env -S uv run python
"""
Emit a single custom metric point to Cloud Monitoring.

Example (local ADC; must set project id — metadata is not available on a laptop):

  uv sync --extra dev
  export GOOGLE_CLOUD_PROJECT="digital-twin-492318"
  METRICS_DEBUG=1 uv run python scripts/emit_test_metric.py --verbose

On Cloud Run, project id can come from metadata if env is omitted.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from digital_twin.metrics import default_context, record_latency_ms  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Write one smoke metric to Cloud Monitoring.")
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Log context + METRICS_DEBUG-style details (set METRICS_DEBUG=1 for API errors).",
    )
    args = p.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)
        os.environ.setdefault("METRICS_DEBUG", "1")

    ctx = default_context()
    if args.verbose:
        logging.getLogger(__name__).info(
            "metric context: project_id=%r region=%r service=%r revision=%r",
            ctx.project_id,
            ctx.region,
            ctx.service,
            ctx.revision,
        )

    ok = record_latency_ms(
        "metrics_smoke_latency_ms",
        123.0,
        labels={
            "status": "ok",
            "note": "smoke",
            "service": os.environ.get("K_SERVICE", "unknown"),
        },
    )
    time.sleep(0.2)
    print("ok" if ok else "failed (see logs; try METRICS_DEBUG=1 or --verbose)")
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
