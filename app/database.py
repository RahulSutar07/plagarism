"""Database engine and session management.

Connects to PostgreSQL (e.g. Supabase) or falls back cleanly to SQLite for local development
and testing without requiring external infrastructure.
"""
from __future__ import annotations

import logging
import socket
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

settings = get_settings()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = (PROJECT_ROOT / "plagiarism_dev.db").as_posix()

db_url = settings.database_url
connect_args = {}

def _is_service_reachable(url_str: str, timeout_s: float = 0.3) -> bool:
    try:
        parsed = urlparse(url_str)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except (socket.timeout, OSError):
        return False

# Quick reachability check for remote/local PostgreSQL
is_pg = "postgresql" in db_url or "postgres" in db_url
if is_pg and not _is_service_reachable(db_url, timeout_s=0.25):
    logger.info("PostgreSQL service at configured URL is unreachable. Instant fallback to SQLite.")
    db_url = f"sqlite:///{DEFAULT_SQLITE_PATH}"
    connect_args = {"check_same_thread": False}
elif is_pg:
    connect_args = {"connect_timeout": 2, "timeout": 2.0}
elif "sqlite" in db_url:
    connect_args = {"check_same_thread": False}

# Attempt engine creation with fallback to SQLite for local standalone execution
try:
    engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
    # Test connection
    with engine.connect() as conn:
        pass
except Exception:
    logger.warning("Could not connect to configured database_url '%s'. Falling back to local SQLite.", db_url)
    db_url = f"sqlite:///{DEFAULT_SQLITE_PATH}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize database tables according to SQLAlchemy metadata."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
