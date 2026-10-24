"""Step 7 tests for downloadable WeasyPrint evidence dossiers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import Base, build_engine, get_db
from app.main import create_app
from app.pdf import build_dossier_html, render_dossier_pdf
from app.schemas import CaseDossierRead


def _make_test_client(tmp_path: Path) -> tuple[TestClient, object, Settings]:
    engine = build_engine(f"sqlite:///{tmp_path / 'step7_pdf.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        app_env="test",
        scanner_mode="mock",
        discrepancy_tolerance_percent=1.0,
        data_dir=BACKEND_DIR / "data",
        cached_scans_dir=BACKEND_DIR / "data" / "cached_scans",
        evidence_dir=BACKEND_DIR.parent / "storage" / "evidence",
    )
    app = create_app(settings)

    def _override_db() -> Session:  # type: ignore[misc]
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app), engine, settings


def test_dossier_html_contains_listing_evidence_reference_formula_history_and_reviews(
    tmp_path: Path,
) -> None:
    client, engine, settings = _make_test_client(tmp_path)
    try:
        scan = client.post("/scans")
        assert scan.status_code == 200
        recurrent = client.get("/cases", params={"recurrent_only": "true"}).json()[0]
        case_id = recurrent["id"]

        review = client.post(
            f"/cases/{case_id}/review",
            json={
                "action": "confirm",
                "reviewer": "pdf.analyst@medisentinel.in",
                "note": "Verified screenshot, pack of 10, and listed MRP.",
            },
        )
        assert review.status_code == 200
        dossier = CaseDossierRead.model_validate(review.json())

        html = build_dossier_html(dossier, settings.evidence_dir)
        assert "Atorva 10 Tablet" in html
        assert dossier.listing.url in html
        assert "data:image/svg+xml;base64," in html
        assert dossier.reference is not None
        assert dossier.reference.source_order in html
        assert dossier.formula is not None and dossier.formula in html
        assert "Case #1" not in html  # History renders the prior identifier in its table as '#1'.
        assert f"#{dossier.prior_cases[0].case_id}" in html
        assert "pdf.analyst@medisentinel.in" in html
        assert "Verified screenshot, pack of 10, and listed MRP." in html
        assert "Confirm for review · Dismiss · Request more evidence" in html
        assert "potential discrepancy" in html.lower()

        # The real renderer must remain operational both with native WeasyPrint
        # libraries and in lean preview images that use the deterministic fallback.
        pdf = render_dossier_pdf(dossier, settings.evidence_dir)
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 4_000
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_download_dossier_pdf_headers_content_alias_and_missing_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, _settings = _make_test_client(tmp_path)
    try:
        # Keep the endpoint test independent from host-level Pango/Cairo packages while
        # asserting that the route passes a complete dossier into the WeasyPrint adapter.
        from app.routers import cases as cases_router

        rendered_case_ids: list[int] = []

        def _fake_render(dossier: CaseDossierRead, evidence_dir: Path) -> bytes:
            assert evidence_dir == BACKEND_DIR.parent / "storage" / "evidence"
            assert dossier.listing.product_name
            assert dossier.reference is not None
            rendered_case_ids.append(dossier.id)
            return b"%PDF-1.7\n" + (b"0" * 11_000) + b"\n%%EOF"

        monkeypatch.setattr(cases_router, "render_dossier_pdf", _fake_render)

        assert client.post("/scans").status_code == 200
        case_id = client.get("/cases").json()[0]["id"]

        response = client.get(f"/cases/{case_id}/dossier.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="medisentinel-case-{case_id}-dossier.pdf"'
        )
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content.startswith(b"%PDF-")
        assert len(response.content) > 10_000

        alias = client.get(f"/api/cases/{case_id}/dossier.pdf")
        assert alias.status_code == 200
        assert alias.content.startswith(b"%PDF-")
        assert rendered_case_ids == [case_id, case_id]

        missing = client.get("/cases/99999/dossier.pdf")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Case #99999 not found."

        schema = client.get("/openapi.json").json()
        pdf_operation = schema["paths"]["/cases/{case_id}/dossier.pdf"]["get"]
        assert "application/pdf" in pdf_operation["responses"]["200"]["content"]
        assert "/api/cases/{case_id}/dossier.pdf" not in schema["paths"]
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_dossier_html_escapes_reviewer_supplied_content(tmp_path: Path) -> None:
    client, engine, settings = _make_test_client(tmp_path)
    try:
        assert client.post("/scans").status_code == 200
        case_id = client.get("/cases").json()[0]["id"]
        review = client.post(
            f"/cases/{case_id}/review",
            json={
                "action": "needs_more_evidence",
                "reviewer": "reviewer@example.in",
                "note": "<script>alert('unsafe')</script>",
            },
        )
        assert review.status_code == 200
        html = build_dossier_html(
            CaseDossierRead.model_validate(review.json()),
            settings.evidence_dir,
        )
        assert "<script>alert" not in html
        assert "&lt;script&gt;alert" in html
    finally:
        engine.dispose()  # type: ignore[attr-defined]
