import json
import logging

from fastapi.testclient import TestClient

from digital_twin.main import app
from digital_twin.structured_logging import JsonFormatter


def test_json_formatter_emits_required_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="digital_twin.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"
    encoded = formatter.format(record)
    payload = json.loads(encoded)

    for key in ("event", "severity", "service", "env", "timestamp", "request_id", "trace_id", "session_id"):
        assert key in payload
    assert payload["event"] == "test_event"
    assert payload["severity"] == "INFO"


def test_chat_model_failure_emits_structured_error_event(monkeypatch, caplog) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("digital_twin.llm.stream_reply", _boom)
    caplog.set_level(logging.INFO)

    c = TestClient(app)
    response = c.post("/api/chat", json={"prompt": "hello"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id")

    failure_events = [record for record in caplog.records if getattr(record, "event", None) == "chat_model_invocation_failed"]
    assert failure_events
    event = failure_events[-1]
    assert event.levelname == "ERROR"
    assert getattr(event, "request_id", None)
    assert getattr(event, "session_id", None)
