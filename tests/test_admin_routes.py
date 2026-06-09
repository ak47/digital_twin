from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response as StarletteResponse

from digital_twin import admin_auth, conversation_store
from digital_twin.main import app
from digital_twin.settings import reset_settings_cache


@pytest.fixture
def admin_client(monkeypatch, sqlite_db):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-key-for-admin")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "owner@example.com")
    reset_settings_cache()

    resp = StarletteResponse()
    admin_auth.set_session_cookie(resp, "owner@example.com")
    cookie_val = resp.headers.getlist("set-cookie")[0].split("dt_admin=")[1].split(";")[0]

    client = TestClient(app)
    client.cookies.set("dt_admin", cookie_val)
    return client


def test_admin_me(admin_client) -> None:
    r = admin_client.get("/admin/me")
    assert r.status_code == 200
    assert r.json()["email"] == "owner@example.com"


def test_admin_inbox_and_thread(admin_client) -> None:
    cid = str(uuid.uuid4())
    conversation_store.insert_message(cid, "visitor", "hello from visitor")
    conversation_store.insert_message(cid, "twin", "twin reply")

    listing = admin_client.get("/admin/conversations")
    assert listing.status_code == 200
    data = listing.json()
    assert len(data) == 1
    assert data[0]["conversation_id"] == cid

    thread = admin_client.get(f"/admin/conversations/{cid}")
    assert thread.status_code == 200
    body = thread.json()
    assert len(body["messages"]) == 2


def test_admin_reply_and_resolve(admin_client) -> None:
    cid = str(uuid.uuid4())
    conversation_store.insert_message(cid, "visitor", "need help")

    reply = admin_client.post(
        f"/admin/conversations/{cid}/messages",
        json={"content": "Owner answer"},
    )
    assert reply.status_code == 200
    assert reply.json()["role"] == "owner"

    resolved = admin_client.post(f"/admin/conversations/{cid}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["ok"] is True


def test_admin_unauthenticated() -> None:
    client = TestClient(app)
    assert client.get("/admin/me").status_code == 401


def test_admin_instructions_get_put(admin_client) -> None:
    empty = admin_client.get("/admin/instructions")
    assert empty.status_code == 200
    assert empty.json()["content"] == ""

    saved = admin_client.put("/admin/instructions", json={"content": "Be extra concise."})
    assert saved.status_code == 200
    assert saved.json()["content"] == "Be extra concise."

    again = admin_client.get("/admin/instructions")
    assert again.json()["content"] == "Be extra concise."
