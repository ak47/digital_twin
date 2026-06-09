import json

from fastapi.testclient import TestClient

from digital_twin.main import SESSION_HEADER, app
from digital_twin.settings import reset_settings_cache


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


def test_chat_post_persists_to_database(monkeypatch, sqlite_db) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCS_SESSIONS_BUCKET", raising=False)

    c = TestClient(app)
    r = c.post("/api/chat", json={"prompt": "hello db", "visitor_name": "Tester"})
    assert r.status_code == 200
    sid = r.headers.get(SESSION_HEADER)
    assert sid

    history = c.get("/api/chat", headers={SESSION_HEADER: sid})
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "hello db"


def test_chat_post_streams_and_sets_session_header(monkeypatch) -> None:
    # Make sure we don't hit Vertex in tests.
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "")  # force in-memory sessions
    reset_settings_cache()

    c = TestClient(app)
    r = c.post("/api/chat", json={"prompt": "hello"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")
    assert r.headers.get(SESSION_HEADER)
    assert r.headers.get("X-Request-Id")

    events = _sse_events(r.text)
    assert any("text" in e for e in events)
    assert any(e.get("complete") is True for e in events)

