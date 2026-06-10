"""Run Alembic migrations (local, CI, or operator use)."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fetch_secret_database_url(secret_id: str, project_id: str) -> str:
    result = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret_id}",
            f"--project={project_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def database_url_via_proxy(raw_url: str, *, host: str = "127.0.0.1", port: int = 5432) -> str:
    """Rewrite a Cloud Run unix-socket DATABASE_URL for TCP via Cloud SQL Auth Proxy."""
    url = make_url(raw_url)
    database = url.database or ""
    # str(URL) hides the password as ***; render_as_string preserves credentials for connect.
    return url.set(
        host=host,
        port=port,
        database=database,
        query={},
    ).render_as_string(hide_password=False)


def _redact_database_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable>"


def wait_for_tcp(host: str, port: int, *, timeout_seconds: float = 60.0) -> None:
    """Wait until host:port accepts TCP connections (Cloud SQL Auth Proxy ready)."""
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if time.monotonic() > deadline:
            break
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as e:
            last_error = e
            time.sleep(0.5)
    raise TimeoutError(
        f"Timed out waiting for {host}:{port} ({last_error})"
    ) from last_error


def _start_cloud_sql_proxy(instance: str, port: int = 5432) -> subprocess.Popen[bytes]:
    proxy_bin = os.environ.get("CLOUD_SQL_PROXY_BIN", "cloud-sql-proxy")
    # Do not capture stdout/stderr to PIPE — an unread pipe can fill and block the proxy.
    proc = subprocess.Popen(
        [proxy_bin, instance, f"--port={port}"],
        stdout=subprocess.DEVNULL,
        stderr=None,
        start_new_session=True,
    )
    return proc


def resolve_database_url() -> str | None:
    """Resolve DATABASE_URL for migration; returns None when migrations should be skipped."""
    direct = os.environ.get("DATABASE_URL", "").strip()
    if direct:
        return direct

    secret_id = os.environ.get("CONVERSATION_DATABASE_URL_SECRET_ID", "").strip()
    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    if secret_id and project_id:
        return _fetch_secret_database_url(secret_id, project_id)

    return None


def upgrade_head() -> int:
    """Apply all pending Alembic revisions. Skips cleanly when DB is not configured."""
    raw_url = resolve_database_url()
    if not raw_url:
        logger.info("DATABASE_URL not configured; skipping migrations")
        return 0

    instance = os.environ.get("CLOUD_SQL_CONNECTION_NAME", "").strip()
    proxy_proc: subprocess.Popen[bytes] | None = None
    migrate_url = raw_url

    try:
        if instance:
            proxy_port = int(os.environ.get("CLOUD_SQL_PROXY_PORT", "5432"))
            logger.info("Starting Cloud SQL Auth Proxy for %s on port %s", instance, proxy_port)
            proxy_proc = _start_cloud_sql_proxy(instance, proxy_port)
            wait_for_tcp("127.0.0.1", proxy_port)
            migrate_url = database_url_via_proxy(raw_url, port=proxy_port)
            logger.info("Proxy ready; database URL %s", _redact_database_url(migrate_url))

        os.environ["DATABASE_URL"] = migrate_url
        os.environ["ALEMBIC_CONFIGURE_LOGGING"] = "0"

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", migrate_url.replace("%", "%%"))
        logger.info("Running alembic upgrade head")
        command.upgrade(cfg, "head")
        logger.info("Alembic upgrade head completed")
        return 0
    finally:
        if proxy_proc is not None:
            if proxy_proc.poll() is None:
                proxy_proc.terminate()
                try:
                    proxy_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proxy_proc.kill()
            elif proxy_proc.returncode != 0:
                logger.error("cloud-sql-proxy exited with code %s", proxy_proc.returncode)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        code = upgrade_head()
    except subprocess.CalledProcessError as e:
        logger.error("Migration subprocess failed: %s", e.stderr or e.stdout or e)
        traceback.print_exc()
        raise SystemExit(1) from e
    except SystemExit:
        raise
    except BaseException as e:
        logger.error("Migration failed: %s", e)
        traceback.print_exc()
        raise SystemExit(1) from e
    else:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
