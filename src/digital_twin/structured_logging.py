from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return repr(value)


def _service_name() -> str:
    return os.environ.get("K_SERVICE", "").strip() or "digital-twin-api"


def _environment_name() -> str:
    if os.environ.get("K_SERVICE"):
        return "cloud_run"
    return os.environ.get("APP_ENV", "").strip() or "local"


def set_request_context(*, request_id: str | None, trace_id: str | None, session_id: str | None) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)
    _session_id.set(session_id)


def update_session_context(session_id: str | None) -> None:
    _session_id.set(session_id)


def clear_request_context() -> None:
    _request_id.set(None)
    _trace_id.set(None)
    _session_id.set(None)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.trace_id = _trace_id.get()
        record.session_id = _session_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_name = getattr(record, "event", None)
        payload: dict[str, Any] = {
            "event": event_name or record.name.replace(".", "_"),
            "severity": record.levelname,
            "service": _service_name(),
            "env": _environment_name(),
            "timestamp": datetime.now(UTC).isoformat(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "session_id": getattr(record, "session_id", None),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = _json_safe(value)

        event_fields = getattr(record, "event_fields", None)
        if isinstance(event_fields, dict):
            for key, value in event_fields.items():
                if key not in payload:
                    payload[key] = _json_safe(value)

        if record.exc_info:
            exc_type = record.exc_info[0].__name__ if record.exc_info[0] else None
            exc_message = str(record.exc_info[1]) if record.exc_info[1] else None
            payload["error_type"] = payload.get("error_type") or exc_type
            payload["exception_message"] = payload.get("exception_message") or exc_message
            payload["stacktrace"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack_info"] = record.stack_info

        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_root_logger(*, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
