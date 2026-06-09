"""Shared pytest fixtures."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from digital_twin import conversation_store
from digital_twin.settings import reset_settings_cache


@pytest.fixture
def sqlite_db(monkeypatch, tmp_path: Path):
    """File-backed SQLite database for conversation_store tests."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_file}")
    reset_settings_cache()
    conversation_store.reset_engine_cache()
    conversation_store.init_schema_for_tests()
    yield
    conversation_store.reset_engine_cache()
    reset_settings_cache()
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def conversation_id() -> str:
    return str(uuid.uuid4())
