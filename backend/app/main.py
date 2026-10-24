"""FastAPI entrypoint for MediSentinel."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import check_db_connection, get_db
from app.routers import cases, references, scans


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    """Create and configure the MediSentinel FastAPI application."""
    settings = custom_settings or get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)

    application = FastAPI(
        title="MediSentinel API",
        version="0.1.0",
        description=(
            "Medicine-price compliance intelligence prototype for India. "
            "Surfaces potential discrepancies against NPPA ceiling references "
            "for human review."
        ),
    )
    application.state.settings = settings

    allow_all = "*" in settings.cors_origins
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else settings.cors_origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve captured listing screenshots from /storage/evidence/<filename>
    application.mount(
        "/storage/evidence",
        StaticFiles(directory=str(settings.evidence_dir)),
        name="evidence",
    )

    application.include_router(references.router)
    application.include_router(scans.router)
    application.include_router(cases.router)

    @application.get("/health", tags=["system"])
    @application.get("/api/health", tags=["system"])
    def health_check(db: Session = Depends(get_db)) -> JSONResponse:
        """Return service readiness, DB connectivity, and compliance wording notice."""
        db_status = "connected"
        status_code = 200
        try:
            check_db_connection(db)
        except SQLAlchemyError:
            db_status = "unreachable"
            status_code = 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if status_code == 200 else "degraded",
                "service": "medisentinel-backend",
                "database": db_status,
                "environment": settings.app_env,
                "scanner_mode": settings.scanner_mode,
                "discrepancy_tolerance_percent": settings.discrepancy_tolerance_percent,
                "evidence_mount": "/storage/evidence",
                "compliance_notice": (
                    "Outputs represent potential discrepancies only and require "
                    "human verification; all findings are advisory triage records."
                ),
            },
        )

    return application


app = create_app()
