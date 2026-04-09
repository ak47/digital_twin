from __future__ import annotations

import logging
import os
from typing import Any

_BOOTSTRAPPED = False
_error_client = None


def _running_on_gcp() -> bool:
    # Cloud Run sets K_SERVICE; local dev typically does not.
    if os.environ.get("K_SERVICE"):
        return True
    # Also treat GAE/Cloud Functions style envs as “on GCP”.
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT"):
        return True
    return False


def setup_logging(*, level: int = logging.INFO) -> None:
    """Initialize Cloud Logging integration when running on GCP.

    Locally, this falls back to standard Python logging.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    # Keep a baseline config so local runs/tests have logs even if the Cloud Logging
    # client is unavailable.
    logging.basicConfig(level=level)

    if _running_on_gcp():
        try:
            from google.cloud import logging as cloud_logging  # type: ignore

            client = cloud_logging.Client()
            client.setup_logging(log_level=level)
        except Exception:
            # Never crash the service/job if observability isn't configured.
            logging.getLogger(__name__).exception("Failed to initialize Cloud Logging client")

    _BOOTSTRAPPED = True


def report_exception(exc: BaseException, *, context: dict[str, Any] | None = None) -> None:
    """Explicitly report an exception to Cloud Error Reporting when on GCP.

    This is most useful for caught exceptions where the app degrades gracefully
    but you still want visibility (e.g., model invocation failures).
    """
    global _error_client

    if not _running_on_gcp():
        return

    try:
        if _error_client is None:
            from google.cloud import error_reporting  # type: ignore

            _error_client = error_reporting.Client()
        # error_reporting.Client.report_exception uses sys.exc_info if no arg,
        # but we may be outside except scope. report() accepts strings; instead,
        # we log + report_exception best-effort by re-raising is too invasive.
        #
        # So: attach context via structured log and still call report_exception()
        # inside an active exception scope when possible.
        if context:
            logging.getLogger(__name__).error(
                "Reporting exception (context=%s): %s",
                context,
                repr(exc),
            )
        # Best-effort: if we're currently handling an exception, this will pick it up.
        _error_client.report_exception()
    except Exception:
        logging.getLogger(__name__).exception("Failed to report exception to Error Reporting")

