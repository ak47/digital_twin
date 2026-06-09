"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from digital_twin.db.models import Base
from digital_twin.settings import get_settings

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url.strip()
        if not url:
            raise RuntimeError("DATABASE_URL is not configured")
        connect_args: dict[str, object] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_db_session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def init_schema_for_tests() -> None:
    """Create tables in the current engine (SQLite tests)."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def reset_engine_cache() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def ping() -> bool:
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
