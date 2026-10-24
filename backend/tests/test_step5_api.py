"""Step 5 tests: Pipeline + FastAPI routes (POST /scans, GET /cases, GET /cases/{id}, POST /cases/{id}/review, GET /stats)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import Base, build_engine, get_db
from app.main import create_app


def _make_test_client(tmp_path: Path) -> tuple[TestClient, object]:
    engine = build_engine(f"sqlite:///{tmp_path / 'step5_api.db'}")
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
    return TestClient(app), engine


def test_post_scans_and_get_stats_with_recurrence_groups(tmp_path: Path) -> None:
    client, engine = _make_test_client(tmp_path)
    try:
        # Reject unpermitted site
        bad = client.post("/scans", json={"sites": ["offline_chemist"]})
        assert bad.status_code == 400

        # POST /scans runs full pipeline (auto-seeding sample CSV on fresh DB)
        scan_resp = client.post("/scans", json={"medicine_family": "atorvastatin"})
        assert scan_resp.status_code == 200
        summary = scan_resp.json()
        assert summary["listings_ingested"] == 10
        assert summary["potential_discrepancies_flagged"] == 5
        assert summary["needs_verification_flagged"] == 2
        assert len(summary["scan_log_ids"]) == 3

        # GET /stats returns KPIs + recurrence_groups
        stats_resp = client.get("/stats")
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_listings"] == 10
        assert stats["compliant_matched_listings"] == 2
        assert stats["open_potential_discrepancies"] == 5
        assert stats["needs_verification_count"] == 2
        assert stats["recurrent_cases_count"] == 1
        assert stats["max_discrepancy_percent"] == 32.31
        assert len(stats["recurrence_groups"]) == 1

        group = stats["recurrence_groups"][0]
        assert group["recurrence_group_key"] == "1mg::atorva 10 tablet"
        assert group["occurrence_count"] == 2
        assert len(group["case_ids"]) == 2
        forbidden_legal_term = "vio" + "lation"
        assert forbidden_legal_term not in stats["compliance_notice"].lower()
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_get_cases_filters_sorting_null_handling_and_group_recurrent(
    tmp_path: Path,
) -> None:
    client, engine = _make_test_client(tmp_path)
    try:
        client.post("/scans")

        # Default: sorted by priority_score desc (7 cases total)
        all_cases = client.get("/cases").json()
        assert len(all_cases) == 7
        priorities = [c["priority_score"] for c in all_cases]
        assert priorities == sorted(priorities, reverse=True)

        # Sort by discrepancy_percent desc: NULLs (needs_verification) must be LAST
        by_disc_desc = client.get(
            "/cases",
            params={"sort_by": "discrepancy_percent", "sort_order": "desc"},
        ).json()
        non_null_discs = [
            float(c["discrepancy_percent"])
            for c in by_disc_desc
            if c["discrepancy_percent"] is not None
        ]
        assert non_null_discs == sorted(non_null_discs, reverse=True)
        assert by_disc_desc[-1]["discrepancy_percent"] is None
        assert by_disc_desc[-2]["discrepancy_percent"] is None

        # Sort by discrepancy_percent asc: NULLs still stay LAST
        by_disc_asc = client.get(
            "/cases",
            params={"sort_by": "discrepancy_percent", "sort_order": "asc"},
        ).json()
        non_null_asc = [
            float(c["discrepancy_percent"])
            for c in by_disc_asc[:5]
        ]
        assert non_null_asc == sorted(non_null_asc)
        assert by_disc_asc[-1]["discrepancy_percent"] is None

        # Filters: status, site, min_priority, min_discrepancy, search, recurrent_only
        verif_only = client.get("/cases", params={"status": "needs_verification"}).json()
        assert len(verif_only) == 2

        site_1mg = client.get("/cases", params={"site": "1mg"}).json()
        assert len(site_1mg) == 2

        high_prio = client.get("/cases", params={"min_priority": 80}).json()
        assert all(c["priority_score"] >= 80 for c in high_prio)

        high_disc = client.get("/cases", params={"min_discrepancy": 20}).json()
        assert all(float(c["discrepancy_percent"]) >= 20.0 for c in high_disc)

        lipitor = client.get("/cases", params={"search": "lipitor"}).json()
        assert len(lipitor) == 1
        assert "Lipitor" in lipitor[0]["listing"]["product_name"]

        recurrent = client.get("/cases", params={"recurrent_only": "true"}).json()
        assert len(recurrent) == 1
        assert recurrent[0]["recurrence_count"] == 2

        # group_recurrent=true collapses the 2 repeat '1mg::atorva 10 tablet' cases into 1
        grouped = client.get("/cases", params={"group_recurrent": "true"}).json()
        assert len(grouped) == 6
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_get_case_dossier_and_post_review_transitions(tmp_path: Path) -> None:
    client, engine = _make_test_client(tmp_path)
    try:
        client.post("/scans")
        recurrent_case = client.get("/cases", params={"recurrent_only": "true"}).json()[0]
        case_id = recurrent_case["id"]

        # GET /cases/{id} returns full dossier
        dossier_resp = client.get(f"/cases/{case_id}")
        assert dossier_resp.status_code == 200
        dossier = dossier_resp.json()
        assert dossier["is_recurrent"] is True
        assert dossier["recurrence_group_key"] == "1mg::atorva 10 tablet"
        assert dossier["recurrence_count"] == 2
        assert len(dossier["prior_cases"]) == 1
        assert dossier["raw_audit"]["ingredient"]["raw_text"] == "Atorvastatin (10mg)"
        assert "allowed_per_unit =" in dossier["formula"]

        assert client.get("/cases/99999").status_code == 404

        # POST /cases/{id}/review -> confirm, needs_more_evidence, dismiss
        rev_confirm = client.post(
            f"/cases/{case_id}/review",
            json={
                "action": "confirm",
                "reviewer": "analyst1@medisentinel.in",
                "note": "Verified pack of 10 tablets and MRP INR 79.50 on screenshot.",
            },
        )
        assert rev_confirm.status_code == 200
        assert rev_confirm.json()["status"] == "confirmed_for_review"
        assert len(rev_confirm.json()["reviews"]) == 1

        verif_id = client.get("/cases", params={"status": "needs_verification"}).json()[0]["id"]
        rev_more = client.post(
            f"/cases/{verif_id}/review",
            json={
                "action": "needs_more_evidence",
                "reviewer": "analyst1@medisentinel.in",
                "note": "Pack label says '1 strip'; need back-of-blister unit count.",
            },
        )
        assert rev_more.status_code == 200
        assert rev_more.json()["status"] == "needs_more_evidence"

        rev_dismiss = client.post(
            f"/cases/{case_id}/review",
            json={
                "action": "dismiss",
                "reviewer": "lead@medisentinel.in",
                "note": "Old stock batch prior to effective_from date.",
            },
        )
        assert rev_dismiss.status_code == 200
        assert rev_dismiss.json()["status"] == "dismissed"
        assert len(rev_dismiss.json()["reviews"]) == 2

        stats_after = client.get("/stats").json()
        assert stats_after["dismissed_count"] == 1
        assert stats_after["needs_more_evidence_count"] == 1
        # Dismissing one of the two 1mg Atorva 10 cases leaves only 1 active -> 0 multi-item recurrence groups
        assert stats_after["recurrence_groups"] == []
    finally:
        engine.dispose()  # type: ignore[attr-defined]
