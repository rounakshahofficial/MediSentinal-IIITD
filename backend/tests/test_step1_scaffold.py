"""Step 1 tests: Alembic schema, 5 ORM models, CSV seed script, health & evidence routes."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import Base, build_engine, get_db
from app.main import create_app
from app.models import Case, CaseStatus, Listing, Match, MatchStatus, ReferencePrice, Review
from scripts.seed_references import seed_reference_prices


def test_alembic_migrations_create_and_drop_all_five_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_test.db"
    db_url = f"sqlite:///{db_path}"

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(alembic_cfg, "head")
    test_engine = build_engine(db_url)
    tables = set(inspect(test_engine).get_table_names())
    assert {
        "reference_prices",
        "listings",
        "matches",
        "cases",
        "reviews",
    }.issubset(tables)

    command.downgrade(alembic_cfg, "base")
    tables_after_down = set(inspect(test_engine).get_table_names()) - {"alembic_version"}
    assert tables_after_down == set()

    command.upgrade(alembic_cfg, "head")
    assert "cases" in set(inspect(test_engine).get_table_names())
    test_engine.dispose()


def test_seed_references_loads_six_rows_idempotently(tmp_path: Path) -> None:
    test_engine = build_engine(f"sqlite:///{tmp_path / 'seed_test.db'}")
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    csv_path = BACKEND_DIR / "data" / "reference_prices.csv"
    with TestSession() as session:
        first_run = seed_reference_prices(session, csv_path=csv_path)
        assert first_run["inserted"] == 6
        assert first_run["updated"] == 0
        assert first_run["has_unverified_sample"] is True

        second_run = seed_reference_prices(session, csv_path=csv_path)
        assert second_run["inserted"] == 0
        assert second_run["updated"] == 6

        count = session.scalar(select(func.count()).select_from(ReferencePrice))
        assert count == 6

    test_engine.dispose()


def test_five_models_relationships_and_status_constraints(tmp_path: Path) -> None:
    test_engine = build_engine(f"sqlite:///{tmp_path / 'models_test.db'}")
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    with TestSession() as session:
        seed_reference_prices(session, csv_path=BACKEND_DIR / "data" / "reference_prices.csv")
        ref = session.scalar(
            select(ReferencePrice).where(
                ReferencePrice.strength == "10 mg",
                ReferencePrice.dosage_form == "tablet",
            )
        )
        assert ref is not None

        listing = Listing(
            site="1mg",
            url="https://www.1mg.com/drugs/example-atorva-10",
            product_name="Atorva 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw="strip of 10 tablets",
            mrp=Decimal("78.50"),
            selling_price=Decimal("69.00"),
            raw_json={"title": "Atorva 10 Tablet"},
            screenshot_path="/storage/evidence/sample_1mg_atorva10.svg",
        )
        session.add(listing)
        session.flush()

        match = Match(
            listing_id=listing.id,
            reference_id=ref.id,
            parsed_ingredient="Atorvastatin",
            parsed_strength="10 mg",
            parsed_form="tablet",
            units_in_pack=10,
            confidence=0.98,
            status=MatchStatus.MATCHED.value,
            reasons=["Exact ingredient + strength + dosage_form match"],
        )
        case = Case(
            listing_id=listing.id,
            reference_id=ref.id,
            observed_per_unit=Decimal("7.8500"),
            selling_per_unit=Decimal("6.9000"),
            allowed_per_unit=Decimal("6.3952"),
            discrepancy_percent=Decimal("22.75"),
            formula="allowed = 5.7100 * (1 + 12.00/100) = 6.3952; observed = 78.50 / 10 = 7.8500",
            reference_version=ref.version,
            calculation_reasons=["MRP per unit exceeds allowed per unit above 1.0% tolerance"],
            is_recurrent=False,
            priority_score=74.5,
            priority_reasons=["+35 discrepancy > 20%", "+25 high match confidence"],
            status=CaseStatus.POTENTIAL_DISCREPANCY.value,
        )
        session.add_all([match, case])
        session.flush()

        review = Review(
            case_id=case.id,
            action="confirm",
            note="Verified screenshot pack size and MRP.",
            reviewer="analyst@medisentinel.in",
        )
        session.add(review)
        session.commit()

        loaded_case = session.get(Case, case.id)
        assert loaded_case is not None
        assert loaded_case.listing.product_name == "Atorva 10 Tablet"
        assert loaded_case.reference is not None
        assert len(loaded_case.reviews) == 1

    # Verify the DB-level CheckConstraint rejects an invalid legal-conclusion status.
    with TestSession() as bad_session:
        bad_listing = Listing(
            site="netmeds",
            url="https://example.com/item",
            product_name="Test Tab",
            raw_json={},
        )
        bad_session.add(bad_listing)
        bad_session.flush()
        bad_session.add(
            Case(
                listing_id=bad_listing.id,
                status="invalid_legal_conclusion",  # Rejected by ck_cases_status
            )
        )
        with pytest.raises(IntegrityError):
            bad_session.commit()

    test_engine.dispose()


def test_health_and_evidence_routes_with_db_dependency(tmp_path: Path) -> None:
    test_engine = build_engine(f"sqlite:///{tmp_path / 'api_test.db'}")
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "proof.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8"
    )

    settings = Settings(
        app_env="test",
        scanner_mode="mock",
        discrepancy_tolerance_percent=1.0,
        evidence_dir=evidence_dir,
        cached_scans_dir=tmp_path / "cached_scans",
        data_dir=tmp_path / "data",
    )
    app = create_app(settings)

    def _override_db() -> Session:  # type: ignore[misc]
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    for route in ("/health", "/api/health"):
        resp = client.get(route)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "connected"
        assert "potential discrepancies" in body["compliance_notice"].lower()

    evidence_resp = client.get("/storage/evidence/proof.svg")
    assert evidence_resp.status_code == 200
    assert "<svg" in evidence_resp.text

    test_engine.dispose()
