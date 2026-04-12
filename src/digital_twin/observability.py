from __future__ import annotations

import logging
import os
from typing import Any

from digital_twin.structured_logging import configure_root_logger, get_logger

_BOOTSTRAPPED = False
_error_client = None
_logger = get_logger(__name__)


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

    # Always emit structured JSON logs from stdout/stderr for consistency across
    # local runs, tests, and Cloud Run.
    configure_root_logger(level=level)

    if _running_on_gcp():
        try:
            from google.cloud import logging as cloud_logging  # type: ignore

            client = cloud_logging.Client()
            client.setup_logging(log_level=level)
            # Keep exactly one deterministic root handler to avoid duplicate
            # messages when Cloud Logging client config attaches additional handlers.
            configure_root_logger(level=level)
        except Exception:
            # Never crash the service/job if observability isn't configured.
            _logger.exception(
                "Failed to initialize Cloud Logging client",
                extra={"event": "cloud_logging_bootstrap_failed"},
            )

    _BOOTSTRAPPED = True


def log_event(
    *,
    event: str,
    severity: int = logging.INFO,
    message: str = "",
    logger: logging.Logger | None = None,
    exc_info: Any | None = None,
    **fields: Any,
) -> None:
    active_logger = logger or _logger
    active_logger.log(
        severity,
        message or event,
        extra={"event": event, "event_fields": fields},
        exc_info=exc_info,
    )


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
        fields = dict(context or {})
        fields.setdefault("error_type", type(exc).__name__)
        fields.setdefault("exception_message", str(exc))
        fields.setdefault("error_code", "unhandled_exception")
        log_event(
            event="exception_reported",
            severity=logging.ERROR,
            message="Reporting exception to Cloud Error Reporting",
            logger=_logger,
            **fields,
        )
        # Best-effort: if we're currently handling an exception, this will pick it up.
        _error_client.report_exception()
    except Exception:
        _logger.exception(
            "Failed to report exception to Error Reporting",
            extra={"event": "error_reporting_failed", "event_fields": {"error_code": "error_reporting_write_failed"}},
        )

