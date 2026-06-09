from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from digital_twin.db import get_engine, reset_engine_cache
from digital_twin.settings import reset_settings_cache


def test_alembic_upgrade_head(tmp_path: Path, monkeypatch) -> None:
    db_file = tmp_path / "alembic-test.db"
    url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)
    reset_engine_cache()
    reset_settings_cache()

    monkeypatch.setenv("ALEMBIC_CONFIGURE_LOGGING", "0")

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")

    reset_engine_cache()
    import os

    os.environ["DATABASE_URL"] = url
    reset_settings_cache()
    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "conversations",
        "messages",
        "owner_settings",
        "archive_messages",
    } <= tables
