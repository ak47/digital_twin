from __future__ import annotations

import json
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response as StarletteResponse

from digital_twin import admin_auth, family_auth, family_routes
from digital_twin.main import app
from digital_twin.settings import reset_settings_cache

MANIFEST = {
    "generated_at": "2026-06-11T00:00:00Z",
    "galleries": [
        {
            "name": "amsterdam",
            "title": "Amsterdam",
            "description": "Trip photos",
            "order": 2,
            "items": [
                {
                    "caption": "Canal at dusk",
                    "thumb": "galleries/amsterdam/thumbs/dsc0042.gif",
                    "full": "galleries/amsterdam/full/dsc0042.jpg",
                },
                {
                    "caption": None,
                    "thumb": "galleries/amsterdam/full/dsc0099.jpg",
                    "full": "galleries/amsterdam/full/dsc0099.jpg",
                },
            ],
        },
        {
            "name": "xmas2003",
            "title": "Xmas 2003",
            "description": None,
            "order": 1,
            "items": [
                {
                    "caption": "Tree",
                    "thumb": "galleries/xmas2003/thumbs/tree.gif",
                    "full": "galleries/xmas2003/full/tree.jpg",
                }
            ],
        },
    ],
    "videos": [
        {
            "title": "Honey Plays Ball",
            "description": "Honey Plays Ball",
            "date": "2003-12-23",
            "video": "videos/HoneyPlaysBall.mp4",
            "poster": "videos/HoneyPlaysBall.jpg",
        }
    ],
}


class FakeBlob:
    def __init__(self, name: str, signed_calls: list[dict]):
        self.name = name
        self._signed_calls = signed_calls

    def download_as_bytes(self) -> bytes:
        if self.name == "manifest.json":
            return json.dumps(MANIFEST).encode()
        raise FileNotFoundError(self.name)

    def generate_signed_url(self, **kwargs) -> str:
        self._signed_calls.append({"name": self.name, **kwargs})
        return f"https://signed.example/{self.name}?sig=fake"


class FakeBucket:
    def __init__(self):
        self.signed_calls: list[dict] = []

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(name, self.signed_calls)


@pytest.fixture
def fake_bucket(monkeypatch) -> FakeBucket:
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-secret-key-for-admin")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "admin@example.com")
    monkeypatch.setenv("FAMILY_ALLOWED_EMAILS", "fam@example.com")
    monkeypatch.setenv("FAMILY_MEDIA_BUCKET", "fake-family-bucket")
    reset_settings_cache()
    bucket = FakeBucket()
    monkeypatch.setattr(family_routes, "_bucket", lambda: bucket)
    monkeypatch.setattr(family_routes, "_signing_credentials", lambda: None)
    family_routes.reset_manifest_cache()
    yield bucket
    family_routes.reset_manifest_cache()
    reset_settings_cache()


def _client_with_cookie(email: str) -> TestClient:
    resp = StarletteResponse()
    family_auth.set_session_cookie(resp, email)
    cookie_val = (
        resp.headers.get("set-cookie", "")
        .split(f"{family_auth.COOKIE_NAME}=")[1]
        .split(";")[0]
    )
    client = TestClient(app)
    client.cookies.set(family_auth.COOKIE_NAME, cookie_val)
    return client


@pytest.fixture
def family_client(fake_bucket) -> TestClient:
    return _client_with_cookie("fam@example.com")


class TestMe:
    def test_me_allowed(self, family_client) -> None:
        r = family_client.get("/family/me")
        assert r.status_code == 200
        assert r.json() == {"email": "fam@example.com", "allowed": True}

    def test_me_denied_email_reports_allowed_false(self, fake_bucket) -> None:
        r = _client_with_cookie("stranger@example.com").get("/family/me")
        assert r.status_code == 200
        assert r.json() == {"email": "stranger@example.com", "allowed": False}

    def test_me_unauthenticated(self, fake_bucket) -> None:
        assert TestClient(app).get("/family/me").status_code == 401


class TestGalleries:
    def test_index_ordered_with_fields(self, family_client) -> None:
        r = family_client.get("/family/galleries")
        assert r.status_code == 200
        galleries = r.json()["galleries"]
        assert [g["name"] for g in galleries] == ["xmas2003", "amsterdam"]
        assert galleries[1] == {
            "name": "amsterdam",
            "title": "Amsterdam",
            "description": "Trip photos",
            "count": 2,
        }

    def test_gallery_detail_signed_urls(self, family_client, fake_bucket) -> None:
        r = family_client.get("/family/galleries/amsterdam")
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == "Amsterdam"
        assert len(body["items"]) == 2
        first = body["items"][0]
        assert first["caption"] == "Canal at dusk"
        assert first["thumb_url"].startswith("https://signed.example/")
        assert first["full_url"].startswith("https://signed.example/")
        assert body["items"][1]["caption"] is None

    def test_signed_url_parameters(self, family_client, fake_bucket) -> None:
        family_client.get("/family/galleries/amsterdam")
        assert fake_bucket.signed_calls, "no signed URLs were generated"
        for call in fake_bucket.signed_calls:
            assert call["method"] == "GET"
            assert call["version"] == "v4"
            assert call["expiration"] <= timedelta(minutes=15)

    def test_unknown_gallery_404(self, family_client) -> None:
        assert family_client.get("/family/galleries/nope").status_code == 404

    def test_unauthenticated_401(self, fake_bucket) -> None:
        assert TestClient(app).get("/family/galleries").status_code == 401


class TestVideos:
    def test_videos_signed(self, family_client) -> None:
        r = family_client.get("/family/videos")
        assert r.status_code == 200
        videos = r.json()["videos"]
        assert len(videos) == 1
        v = videos[0]
        assert v["title"] == "Honey Plays Ball"
        assert v["date"] == "2003-12-23"
        assert v["video_url"].startswith("https://signed.example/videos/")
        assert v["poster_url"].startswith("https://signed.example/videos/")


class TestLogout:
    def test_logout_clears_cookie(self, family_client) -> None:
        r = family_client.post("/family/logout")
        assert r.status_code == 204
        assert f'{family_auth.COOKIE_NAME}="";' in r.headers.get(
            "set-cookie", ""
        ) or f"{family_auth.COOKIE_NAME}=;" in r.headers.get("set-cookie", "")


class TestAccessControl:
    """US3: refusal, empty allowlist, cookie non-interchangeability (routes)."""

    def test_denied_email_403_on_content(self, fake_bucket) -> None:
        client = _client_with_cookie("stranger@example.com")
        assert client.get("/family/galleries").status_code == 403
        assert client.get("/family/galleries/amsterdam").status_code == 403
        assert client.get("/family/videos").status_code == 403

    def test_empty_allowlist_admin_still_implicitly_allowed(
        self, fake_bucket, monkeypatch
    ) -> None:
        monkeypatch.setenv("FAMILY_ALLOWED_EMAILS", "")
        reset_settings_cache()
        assert _client_with_cookie("fam@example.com").get("/family/galleries").status_code == 403
        assert _client_with_cookie("admin@example.com").get("/family/galleries").status_code == 200

    def test_admin_cookie_rejected_on_family_routes(self, fake_bucket) -> None:
        resp = StarletteResponse()
        admin_auth.set_session_cookie(resp, "admin@example.com")
        cookie_val = resp.headers.get("set-cookie", "").split("dt_admin=")[1].split(";")[0]
        client = TestClient(app)
        client.cookies.set(family_auth.COOKIE_NAME, cookie_val)
        assert client.get("/family/galleries").status_code == 401
        client2 = TestClient(app)
        client2.cookies.set("dt_admin", cookie_val)
        assert client2.get("/family/me").status_code == 401

    def test_family_cookie_rejected_on_admin_routes(self, family_client) -> None:
        cookie_val = family_client.cookies.get(family_auth.COOKIE_NAME)
        client = TestClient(app)
        client.cookies.set("dt_admin", cookie_val)
        assert client.get("/admin/me").status_code == 401


class TestAuditLog:
    """US3: every content listing emits a structured access-log entry."""

    def _records(self, caplog):
        return [
            r
            for r in caplog.records
            if getattr(r, "event", "") == "family_archive_access"
        ]

    def test_index_emits_audit_entry_with_connection_fields(
        self, family_client, caplog
    ) -> None:
        with caplog.at_level(logging.INFO):
            family_client.get(
                "/family/galleries",
                headers={
                    "X-Forwarded-For": "203.0.113.7, 70.32.1.1",
                    "User-Agent": "TestBrowser/1.0",
                    "Referer": "https://no-ego.net/family/",
                },
            )
        records = self._records(caplog)
        assert len(records) == 1
        fields = records[0].event_fields
        assert fields["email"] == "fam@example.com"
        assert fields["resource"] == "index"
        assert fields["ip"] == "203.0.113.7"
        assert fields["user_agent"] == "TestBrowser/1.0"
        assert fields["referer"] == "https://no-ego.net/family/"

    def test_gallery_and_videos_emit_named_resources(self, family_client, caplog) -> None:
        with caplog.at_level(logging.INFO):
            family_client.get("/family/galleries/amsterdam")
            family_client.get("/family/videos")
        resources = [r.event_fields["resource"] for r in self._records(caplog)]
        assert resources == ["amsterdam", "videos"]

    def test_missing_headers_never_block_request_or_log(
        self, family_client, caplog
    ) -> None:
        with caplog.at_level(logging.INFO):
            r = family_client.get("/family/galleries")
        assert r.status_code == 200
        records = self._records(caplog)
        assert len(records) == 1
        fields = records[0].event_fields
        assert fields["referer"] is None
        # TestClient supplies defaults for client host/UA; the contract is
        # simply that absence must not raise or block.
        assert "ip" in fields and "user_agent" in fields

    def test_user_agent_truncated(self, family_client, caplog) -> None:
        with caplog.at_level(logging.INFO):
            family_client.get(
                "/family/galleries", headers={"User-Agent": "x" * 1000}
            )
        fields = self._records(caplog)[0].event_fields
        assert len(fields["user_agent"]) == 256

    def test_me_does_not_emit_audit_entry(self, family_client, caplog) -> None:
        with caplog.at_level(logging.INFO):
            family_client.get("/family/me")
        assert self._records(caplog) == []
