from fastapi.testclient import TestClient

from digital_twin.main import app


def test_root_includes_llm_metadata() -> None:
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "digital-twin-api"
    assert data["docs"] == "/docs"
    assert data["llm_model"] == "gemini-2.5-flash"
    assert data["llm_provider"] == "vertex"
