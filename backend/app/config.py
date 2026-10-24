"""Application configuration loaded from environment variables (.env)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

ScannerMode = Literal["mock", "tinyfish_rest", "tinyfish_sdk"]


def _resolve_dir(raw_path: str) -> Path:
    """Resolve relative paths against backend/ so cwd never breaks file lookup."""
    path = Path(raw_path)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def _normalize_db_url(raw_url: str) -> str:
    """Anchor relative SQLite file paths to backend/; leave Postgres/in-memory URLs intact."""
    prefix = "sqlite:///./"
    if raw_url.startswith(prefix):
        db_file = (BACKEND_DIR / raw_url[len(prefix) :]).resolve()
        return f"sqlite:///{db_file}"
    return raw_url


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a strict, predictable boolean environment switch."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    """Typed runtime settings for MediSentinel."""

    app_env: str = Field(default="development")
    database_url: str = Field(
        default="postgresql+psycopg://medisentinel:medisentinel_dev@localhost:5432/medisentinel"
    )
    scanner_mode: ScannerMode = Field(default="mock")
    tinyfish_api_key: str = Field(default="")
    tinyfish_api_url: str = Field(
        default="https://agent.tinyfish.ai/v1/automation/run-sse"
    )
    scanner_timeout_seconds: float = Field(default=90.0, gt=0.0, le=600.0)
    scanner_max_retries: int = Field(default=3, ge=1, le=10)
    scanner_backoff_seconds: float = Field(default=1.5, ge=0.0, le=60.0)
    cached_run_fallback: bool = Field(default=False)
    discrepancy_tolerance_percent: float = Field(default=1.0, ge=0.0, le=50.0)
    data_dir: Path = Field(default=BACKEND_DIR / "data")
    cached_scans_dir: Path = Field(default=BACKEND_DIR / "data" / "cached_scans")
    evidence_dir: Path = Field(default=BACKEND_DIR.parent / "storage" / "evidence")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache validated settings from environment variables."""
    raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]

    settings = Settings(
        app_env=os.getenv("APP_ENV", "development"),
        database_url=_normalize_db_url(
            os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://medisentinel:medisentinel_dev@localhost:5432/medisentinel",
            )
        ),
        scanner_mode=os.getenv("SCANNER_MODE", "mock"),  # type: ignore[arg-type]
        tinyfish_api_key=os.getenv("TINYFISH_API_KEY", ""),
        tinyfish_api_url=os.getenv(
            "TINYFISH_API_URL",
            "https://agent.tinyfish.ai/v1/automation/run-sse",
        ),
        scanner_timeout_seconds=float(os.getenv("SCANNER_TIMEOUT_SECONDS", "90.0")),
        scanner_max_retries=int(os.getenv("SCANNER_MAX_RETRIES", "3")),
        scanner_backoff_seconds=float(os.getenv("SCANNER_BACKOFF_SECONDS", "1.5")),
        cached_run_fallback=_env_bool("CACHED_RUN_FALLBACK", False),
        discrepancy_tolerance_percent=float(
            os.getenv("DISCREPANCY_TOLERANCE_PERCENT", "1.0")
        ),
        data_dir=_resolve_dir(os.getenv("DATA_DIR", "./data")),
        cached_scans_dir=_resolve_dir(
            os.getenv("CACHED_SCANS_DIR", "./data/cached_scans")
        ),
        evidence_dir=_resolve_dir(os.getenv("EVIDENCE_DIR", "../storage/evidence")),
        cors_origins=origins or ["http://localhost:5173"],
    )
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.cached_scans_dir.mkdir(parents=True, exist_ok=True)
    return settings
