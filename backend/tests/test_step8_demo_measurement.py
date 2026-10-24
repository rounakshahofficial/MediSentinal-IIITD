"""Step 8 tests: cached fallback switch and ground-truth measurements."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import Base, build_engine, get_db
from app.main import create_app
from scripts.measure_ground_truth import GroundTruthRow, load_ground_truth, measure


def _make_test_client(tmp_path: Path, *, env_fallback: bool = False) -> tuple[TestClient, object]:
    engine = build_engine(f"sqlite:///{tmp_path / 'step8.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        app_env="test",
        scanner_mode="mock",
        cached_run_fallback=env_fallback,
        tinyfish_api_key="",
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


def test_api_cached_run_fallback_switch_discloses_demo_source(tmp_path: Path) -> None:
    client, engine = _make_test_client(tmp_path)
    try:
        # A live mode cannot initialize without an API key, so the explicit switch
        # deterministically falls back to all three cached site snapshots.
        response = client.post(
            "/scans",
            json={
                "medicine_family": "atorvastatin",
                "scanner_mode": "tinyfish_rest",
                "use_cached_fallback": True,
            },
        )
        assert response.status_code == 200
        summary = response.json()
        assert summary["requested_scanner_mode"] == "tinyfish_rest"
        assert summary["scanner_mode"] == "tinyfish_rest+mock_fallback"
        assert summary["fallback_used"] is True
        assert summary["fallback_sites"] == ["1mg", "pharmeasy", "netmeds"]
        assert summary["failed_sites"] == []
        assert summary["listings_ingested"] == 10
        assert summary["matched_count"] == 7

        logs = client.get("/scans/logs").json()
        assert len(logs) == 3
        assert {log["scanner_mode"] for log in logs} == {"mock"}

        # Turning the switch off preserves the live-mode configuration error.
        no_fallback = client.post(
            "/scans",
            json={
                "scanner_mode": "tinyfish_rest",
                "use_cached_fallback": False,
            },
        )
        assert no_fallback.status_code == 400
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_environment_default_enables_cached_fallback_when_request_omits_switch(
    tmp_path: Path,
) -> None:
    client, engine = _make_test_client(tmp_path, env_fallback=True)
    try:
        response = client.post(
            "/scans",
            json={"scanner_mode": "tinyfish_sdk"},
        )
        assert response.status_code == 200
        assert response.json()["fallback_used"] is True
        assert response.json()["requested_scanner_mode"] == "tinyfish_sdk"
    finally:
        engine.dispose()  # type: ignore[attr-defined]


def test_manual_ground_truth_measurement_metrics_and_false_positive_count(
    tmp_path: Path,
) -> None:
    client, engine = _make_test_client(tmp_path)
    try:
        assert client.post("/scans").status_code == 200
        rows = load_ground_truth(BACKEND_DIR / "data" / "manual_ground_truth.example.csv")
        assert len(rows) == 10

        with Session(engine) as db:  # type: ignore[arg-type]
            perfect = measure(rows, db)
        assert perfect["metrics"] == {
            "extraction_rate": 1.0,
            "match_accuracy": 1.0,
            "flag_precision": 1.0,
        }
        assert perfect["counts"]["true_positive_flags"] == 5

        # Manual relabel: one currently positive system finding is marked negative.
        relabelled = [replace(rows[0], expected_flag=False), *rows[1:]]
        with Session(engine) as db:  # type: ignore[arg-type]
            changed = measure(relabelled, db)
        assert changed["counts"]["true_positive_flags"] == 4
        assert changed["counts"]["false_positive_flags"] == 1
        assert changed["metrics"]["flag_precision"] == 0.8

        missing = GroundTruthRow(
            row_number=99,
            site="1mg",
            url="https://www.1mg.com/drugs/manually-labelled-missing-listing",
            observed_at=None,
            expected_ingredient="Atorvastatin",
            expected_strength="10 mg",
            expected_dosage_form="tablet",
            expected_units_in_pack=10,
            expected_match_status="matched",
            expected_flag=False,
        )
        with Session(engine) as db:  # type: ignore[arg-type]
            incomplete = measure([*rows, missing], db)
        assert incomplete["counts"]["extracted_ground_truth_rows"] == 10
        assert incomplete["metrics"]["extraction_rate"] == round(10 / 11, 6)
    finally:
        engine.dispose()  # type: ignore[attr-defined]
