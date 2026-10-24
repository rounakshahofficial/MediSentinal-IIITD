"""SQLAlchemy 2.x database engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all MediSentinel ORM models."""


def build_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy 2.x Engine configured for PostgreSQL (or SQLite fallback)."""
    is_sqlite = database_url.startswith("sqlite")
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": not is_sqlite}
    if is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    db_engine = create_engine(database_url, **engine_kwargs)

    if is_sqlite:
        @event.listens_for(db_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return db_engine


engine: Engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a transactional database session per FastAPI request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection(db: Session) -> bool:
    """Execute a lightweight SELECT 1 probe to verify database connectivity."""
    db.execute(text("SELECT 1"))
    return True
