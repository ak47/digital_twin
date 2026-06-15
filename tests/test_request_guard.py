from fastapi.testclient import TestClient

from digital_twin.main import app
from digital_twin.request_guard import is_allowed_path


def test_is_allowed_path_public_routes() -> None:
    assert is_allowed_path("/")
    assert is_allowed_path("/health")
    assert is_allowed_path("/api/chat")
    assert is_allowed_path("/admin/me")
    assert is_allowed_path("/family/galleries")


def test_is_allowed_path_rejects_probes() -> None:
    assert not is_allowed_path("/mg.php")
    assert not is_allowed_path("/wp-admin")
    assert not is_allowed_path("/.env")
    assert not is_allowed_path("/phpmyadmin/index.php")


def test_probe_paths_return_404_without_server_error() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    for path in ("/mg.php", "/wp-login.php", "/.git/config"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
        assert response.headers.get("X-Request-Id")
