import json

from fastapi.testclient import TestClient

from digital_twin.main import SESSION_HEADER, app


def _sse_events(raw: str) -> list[dict]:
    events: list[dict] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :].strip()
        if not payload:
            continue
        events.append(json.loads(payload))
    return events


def test_chat_post_streams_and_sets_session_header(monkeypatch) -> None:
    # Make sure we don't hit Vertex in tests.
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "")  # force in-memory sessions

    c = TestClient(app)
    r = c.post("/api/chat", json={"prompt": "hello"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")
    assert r.headers.get(SESSION_HEADER)
    assert r.headers.get("X-Request-Id")

    events = _sse_events(r.text)
    assert any("text" in e for e in events)
    assert any(e.get("complete") is True for e in events)

