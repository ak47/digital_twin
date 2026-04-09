"""One-shot entrypoint for Cloud Run Job: email stale session digests (GCS + Gmail)."""

from __future__ import annotations

import logging
import sys

from digital_twin.observability import report_exception, setup_logging
from digital_twin.session_digest import digest_feature_configured, scan_and_send_idle_digests

logger = logging.getLogger(__name__)


def main() -> int:
    setup_logging(level=logging.INFO)
    if not digest_feature_configured():
        logger.warning("Session digest not configured (missing GCS bucket, recipients, or Gmail); exiting 0.")
        return 0
    try:
        scan_and_send_idle_digests()
    except Exception as e:
        logger.exception("scan_and_send_idle_digests failed")
        report_exception(e, context={"where": "run_session_digest"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
