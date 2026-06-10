from __future__ import annotations

import socket
import subprocess
import threading
import time

import pytest

from sqlalchemy.engine import make_url

from digital_twin.migrate import database_url_via_proxy, wait_for_tcp


def test_database_url_via_proxy_rewrites_unix_socket() -> None:
    raw = "postgresql+psycopg://user:secret123@/digital_twin?host=/cloudsql/p:r:i"
    rewritten = database_url_via_proxy(raw, port=5433)
    parsed = make_url(rewritten)
    assert parsed.username == "user"
    assert parsed.password == "secret123"
    assert "secret123" in rewritten
    assert "***" not in rewritten.split("@", 1)[0]
    assert parsed.host == "127.0.0.1"
    assert parsed.port == 5433
    assert parsed.database == "digital_twin"


def test_wait_for_tcp_succeeds_when_port_opens() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        def accept_once() -> None:
            conn, _ = sock.accept()
            conn.close()

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        wait_for_tcp("127.0.0.1", port, timeout_seconds=5.0)


def test_wait_for_tcp_times_out() -> None:
    with pytest.raises(TimeoutError):
        wait_for_tcp("127.0.0.1", 1, timeout_seconds=0.6)


def test_cloud_sql_proxy_subprocess_uses_devnull_not_pipe() -> None:
    """Regression: PIPE without readers can block cloud-sql-proxy on CI."""
    proc = subprocess.Popen(
        ["sleep", "0.1"],
        stdout=subprocess.DEVNULL,
        stderr=None,
        start_new_session=True,
    )
    proc.wait(timeout=5)
    assert proc.returncode == 0
