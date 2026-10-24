"""Step 3 tests: calculator.py, cases.py, priority scoring, recurrence, and review actions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.calculator import calculate_discrepancy, compute_allowed_per_unit
from app.cases import evaluate_and_save_case, record_case_review
from app.config import BACKEND_DIR
from app.db import Base, build_engine
from app.models import CaseStatus, Listing, MatchStatus, ReferencePrice
from app.schemas import MatchEvaluation
from scripts.seed_references import seed_reference_prices


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    engine = build_engine(f"sqlite:///{tmp_path / 'step3_test.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()
    seed_reference_prices(session, csv_path=BACKEND_DIR / "data" / "reference_prices.csv")
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_allowed_per_unit_uses_reference_gst_not_hardcoded() -> None:
    # 5% GST vs 12% GST vs 18% GST from reference row (Rule 3)
    assert compute_allowed_per_unit(Decimal("10.0000"), Decimal("5.00")) == Decimal("10.5000")
    assert compute_allowed_per_unit(Decimal("5.7100"), Decimal("12.00")) == Decimal("6.3952")
    assert compute_allowed_per_unit(Decimal("10.0000"), Decimal("18.00")) == Decimal("11.8000")


def test_calculator_refuses_uncertain_or_no_match_status() -> None:
    ref = ReferencePrice(
        id=99,
        ingredient="Atorvastatin",
        strength="10 mg",
        dosage_form="tablet",
        unit="1 tablet",
        ceiling_price_per_unit=Decimal("5.7100"),
        gst_percent=Decimal("12.00"),
        source_order="SO-TEST",
        effective_from=date(2025, 4, 1),
        version="v1",
    )
    uncertain_eval = MatchEvaluation(
        status=MatchStatus.UNCERTAIN,
        reference_id=99,
        parsed_ingredient="Atorvastatin",
        parsed_strength="10 mg",
        parsed_form="tablet",
        units_in_pack=None,
        confidence=0.45,
        can_calculate_discrepancy=False,
    )
    with pytest.raises(ValueError, match="Core Rule 2"):
        calculate_discrepancy(uncertain_eval, ref, mrp=Decimal("80.00"))


def test_tolerance_boundary_and_selling_price_check(db_session: Session) -> None:
    # Atorvastatin 10 mg tablet allowed_per_unit = 5.71 * 1.12 = 6.3952
    # Strip of 10 allowed pack price = 63.952
    # MRP 64.40 -> 6.4400/unit -> +0.70% (<= 1.0% tolerance -> compliant, no case)
    within_tol = Listing(
        site="pharmeasy",
        url="https://pharmeasy.in/item/storvas-10",
        product_name="Storvas 10 Tablet",
        composition_raw="Atorvastatin (10mg)",
        pack_size_raw="strip of 10 tablets",
        mrp=Decimal("64.40"),
        selling_price=Decimal("59.00"),
        raw_json={},
    )
    db_session.add(within_tol)
    db_session.flush()
    match_ok, case_none = evaluate_and_save_case(db_session, within_tol, tolerance_percent=1.0)
    assert match_ok.status == "matched"
    assert case_none is None

    # MRP 78.50 -> 7.8500/unit -> +22.75% (> 1.0% tolerance -> potential_discrepancy)
    over_tol = Listing(
        site="1mg",
        url="https://www.1mg.com/drugs/atorva-10",
        product_name="Atorva 10 Tablet",
        composition_raw="Atorvastatin (10mg)",
        pack_size_raw="strip of 10 tablets",
        mrp=Decimal("78.50"),
        selling_price=Decimal("69.00"),  # 6.9000/unit -> also exceeds 6.3952 by +7.89%
        raw_json={},
        screenshot_path="/storage/evidence/sample_1mg.svg",
    )
    db_session.add(over_tol)
    db_session.flush()
    _, flagged_case = evaluate_and_save_case(db_session, over_tol, tolerance_percent=1.0)
    db_session.commit()

    assert flagged_case is not None
    assert flagged_case.status == CaseStatus.POTENTIAL_DISCREPANCY.value
    assert flagged_case.allowed_per_unit == Decimal("6.3952")
    assert flagged_case.observed_per_unit == Decimal("7.8500")
    assert flagged_case.selling_per_unit == Decimal("6.9000")
    assert flagged_case.discrepancy_percent == Decimal("22.75")
    assert flagged_case.reference_version == "SAMPLE-UNVERIFIED-v1"
    assert flagged_case.formula is not None and "allowed_per_unit =" in flagged_case.formula
    # Stored reasons must remain advisory and avoid legal-conclusion wording.
    joined_reasons = " ".join(flagged_case.calculation_reasons + flagged_case.priority_reasons).lower()
    forbidden_legal_term = "vio" + "lation"
    assert forbidden_legal_term not in joined_reasons
    assert "potential discrepancy" in joined_reasons


def test_uncertain_listing_creates_needs_verification_without_discrepancy_math(
    db_session: Session,
) -> None:
    unclear = Listing(
        site="netmeds",
        url="https://www.netmeds.com/prescriptions/lipitor-20",
        product_name="Lipitor 20 Tablet",
        composition_raw="Atorvastatin (20mg)",
        pack_size_raw="1 strip",  # Unclear pack count -> Rule 2 STOP
        mrp=Decimal("210.00"),
        selling_price=Decimal("185.00"),
        raw_json={},
    )
    db_session.add(unclear)
    db_session.flush()
    match_row, verif_case = evaluate_and_save_case(db_session, unclear)
    db_session.commit()

    assert match_row.status == "uncertain"
    assert verif_case is not None
    assert verif_case.status == CaseStatus.NEEDS_VERIFICATION.value
    assert verif_case.observed_per_unit is None
    assert verif_case.allowed_per_unit is None
    assert verif_case.discrepancy_percent is None
    assert verif_case.formula is None


def test_recurrence_boosts_priority_and_respects_dismissed_reviews(
    db_session: Session,
) -> None:
    first = Listing(
        site="1mg",
        url="https://www.1mg.com/drugs/tonact-20",
        product_name="Tonact 20 Tablet",
        composition_raw="Atorvastatin (20mg)",
        pack_size_raw="strip of 10 tablets",
        mrp=Decimal("195.00"),  # 19.50/unit vs allowed 15.5232 -> +25.62%
        selling_price=Decimal("172.00"),
        raw_json={},
        screenshot_path="/storage/evidence/tonact_scan1.svg",
    )
    db_session.add(first)
    db_session.flush()
    _, case_one = evaluate_and_save_case(db_session, first)
    db_session.commit()
    assert case_one is not None
    assert case_one.is_recurrent is False

    # Same site + product observed again -> repeat finding (+10 recurrence points)
    second = Listing(
        site="1mg",
        url="https://www.1mg.com/drugs/tonact-20?ref=rescan",
        product_name="Tonact 20 Tablet",
        composition_raw="Atorvastatin (20mg)",
        pack_size_raw="strip of 10 tablets",
        mrp=Decimal("195.00"),
        selling_price=Decimal("172.00"),
        raw_json={},
        screenshot_path="/storage/evidence/tonact_scan2.svg",
    )
    db_session.add(second)
    db_session.flush()
    _, case_two = evaluate_and_save_case(db_session, second)
    db_session.commit()
    assert case_two is not None
    assert case_two.is_recurrent is True
    assert case_two.priority_score == pytest.approx(case_one.priority_score + 10.0)

    # Human reviewer transitions statuses cleanly
    rev_confirm = record_case_review(
        db_session,
        case_two,
        action="confirm",
        reviewer="reviewer1@medisentinel.in",
        note="Confirmed strip of 10 MRP from screenshot.",
    )
    db_session.commit()
    assert rev_confirm.action == "confirm"
    assert case_two.status == CaseStatus.CONFIRMED_FOR_REVIEW.value

    record_case_review(
        db_session,
        case_one,
        action="needs_more_evidence",
        reviewer="reviewer1@medisentinel.in",
        note="Back-of-strip image slightly blurred; re-capture.",
    )
    db_session.commit()
    assert case_one.status == CaseStatus.NEEDS_MORE_EVIDENCE.value
