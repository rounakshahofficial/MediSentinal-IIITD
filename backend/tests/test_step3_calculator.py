"""Step 3 unit tests for calculator.py: exact limits, tolerance boundaries, and GST edge cases."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.calculator import calculate_discrepancy, compute_allowed_per_unit
from app.models import MatchStatus, ReferencePrice
from app.schemas import MatchEvaluation


def _make_match(
    units: int | None = 10,
    status: MatchStatus = MatchStatus.MATCHED,
    can_calc: bool = True,
) -> MatchEvaluation:
    return MatchEvaluation(
        status=status,
        reference_id=1,
        parsed_ingredient="Atorvastatin",
        parsed_strength="10 mg",
        parsed_form="tablet",
        units_in_pack=units,
        confidence=0.98 if status == MatchStatus.MATCHED else 0.40,
        can_calculate_discrepancy=can_calc,
    )


def _make_ref(
    ceiling: str = "5.7100",
    gst: str = "12.00",
    version: str = "NPPA-SAMPLE-2026-v2",
) -> ReferencePrice:
    return ReferencePrice(
        id=1,
        ingredient="Atorvastatin",
        strength="10 mg",
        dosage_form="tablet",
        unit="1 tablet",
        ceiling_price_per_unit=Decimal(ceiling),
        gst_percent=Decimal(gst),
        source_order="SAMPLE-SO-1547E",
        effective_from=date(2025, 4, 1),
        version=version,
    )


def test_standard_potential_discrepancy_returns_formula_and_reference_version() -> None:
    res = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=_make_ref(ceiling="5.7100", gst="12.00", version="NPPA-SAMPLE-2026-v2"),
        mrp=Decimal("78.50"),
        selling_price=Decimal("69.00"),
        tolerance_percent=1.0,
    )
    assert res.allowed_per_unit == Decimal("6.3952")
    assert res.observed_per_unit == Decimal("7.8500")
    assert res.selling_per_unit == Decimal("6.9000")
    assert res.discrepancy_percent == Decimal("22.75")
    assert res.exceeds_tolerance is True
    assert res.selling_exceeds_tolerance is True
    assert res.status_recommendation == "potential_discrepancy"
    assert res.reference_version == "NPPA-SAMPLE-2026-v2"
    assert "allowed_per_unit = 5.7100 * (1 + 12.00/100) = 6.3952" in res.formula
    assert "observed_per_unit = 78.50 / 10 = 7.8500" in res.formula
    forbidden_legal_term = "vio" + "lation"
    assert forbidden_legal_term not in " ".join(res.reasons).lower()


def test_listing_exactly_at_ceiling_limit_and_exact_tolerance_boundary() -> None:
    # 1. Exactly at statutory ceiling + GST (0.00% discrepancy)
    ref = _make_ref(ceiling="10.0000", gst="12.00")  # allowed = 11.2000/unit
    exact_ceiling = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=ref,
        mrp=Decimal("112.00"),  # 11.2000/unit -> 0.00%
        selling_price=Decimal("112.00"),
        tolerance_percent=1.0,
    )
    assert exact_ceiling.allowed_per_unit == Decimal("11.2000")
    assert exact_ceiling.observed_per_unit == Decimal("11.2000")
    assert exact_ceiling.discrepancy_percent == Decimal("0.00")
    assert exact_ceiling.exceeds_tolerance is False
    assert exact_ceiling.status_recommendation == "within_limit"

    # 2. Exactly AT +1.00% tolerance limit -> Rule 4 says "more than" tolerance, so NOT flagged
    ref_zero_gst = _make_ref(ceiling="10.0000", gst="0.00")  # allowed = 10.0000/unit
    exact_tol_limit = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=ref_zero_gst,
        mrp=Decimal("101.00"),  # 10.1000/unit -> exactly +1.00%
        tolerance_percent=1.0,
    )
    assert exact_tol_limit.discrepancy_percent == Decimal("1.00")
    assert exact_tol_limit.exceeds_tolerance is False
    assert exact_tol_limit.status_recommendation == "within_limit"

    # 3. One paisa per pack above +1.00% tolerance (+1.01%) -> FLAGGED
    just_over_tol = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=ref_zero_gst,
        mrp=Decimal("101.01"),  # 10.1010/unit -> +1.01%
        tolerance_percent=1.0,
    )
    assert just_over_tol.discrepancy_percent == Decimal("1.01")
    assert just_over_tol.exceeds_tolerance is True
    assert just_over_tol.status_recommendation == "potential_discrepancy"


def test_gst_edge_cases_zero_five_eighteen_rounding_and_invalid_bounds() -> None:
    # 0% GST (tax-exempt life-saving schedule): must NOT fall back to 12%
    zero_gst = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=_make_ref(ceiling="8.5000", gst="0.00"),
        mrp=Decimal("85.00"),
        tolerance_percent=0.0,  # Also tests 0.0% tolerance edge case
    )
    assert zero_gst.allowed_per_unit == Decimal("8.5000")
    assert zero_gst.discrepancy_percent == Decimal("0.00")
    assert zero_gst.exceeds_tolerance is False

    # Same 90.00 MRP evaluated under 5% GST vs 18% GST reference rows
    under_5_gst = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=_make_ref(ceiling="8.0000", gst="5.00"),  # allowed = 8.4000
        mrp=Decimal("90.00"),  # 9.0000 -> +7.14%
        tolerance_percent=1.0,
    )
    under_18_gst = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=_make_ref(ceiling="8.0000", gst="18.00"),  # allowed = 9.4400
        mrp=Decimal("90.00"),  # 9.0000 -> -4.66%
        tolerance_percent=1.0,
    )
    assert under_5_gst.exceeds_tolerance is True
    assert under_18_gst.exceeds_tolerance is False

    # Half-way 5th decimal GST rounding: 1.0050 * 1.05 = 1.05525 -> 1.0553 (ROUND_HALF_UP)
    assert compute_allowed_per_unit(Decimal("1.0050"), Decimal("5.00")) == Decimal("1.0553")

    # Reject corrupted negative or >100% GST values
    with pytest.raises(ValueError, match="gst_percent"):
        compute_allowed_per_unit(Decimal("5.0000"), Decimal("-5.00"))
    with pytest.raises(ValueError, match="gst_percent"):
        compute_allowed_per_unit(Decimal("5.0000"), Decimal("120.00"))


def test_selling_price_checks_and_anomaly_detection() -> None:
    ref = _make_ref(ceiling="10.0000", gst="12.00")  # allowed = 11.2000/unit

    # MRP exceeds limit (+11.61%), but discounted selling price is within limit (-1.79%)
    mrp_only = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=ref,
        mrp=Decimal("125.00"),
        selling_price=Decimal("110.00"),
        tolerance_percent=1.0,
    )
    assert mrp_only.exceeds_tolerance is True
    assert mrp_only.selling_exceeds_tolerance is False

    # MRP is compliant (0.00%), but selling_price > mrp anomaly -> needs_verification
    anomaly = calculate_discrepancy(
        match_eval=_make_match(units=10),
        reference=ref,
        mrp=Decimal("112.00"),
        selling_price=Decimal("119.00"),
        tolerance_percent=1.0,
    )
    assert anomaly.exceeds_tolerance is False
    assert anomaly.selling_above_mrp_anomaly is True
    assert anomaly.status_recommendation == "needs_verification"


def test_core_rule_2_stop_gate_rejects_uncertain_or_missing_mrp() -> None:
    ref = _make_ref()
    with pytest.raises(ValueError, match="Core Rule 2"):
        calculate_discrepancy(
            _make_match(units=None, status=MatchStatus.UNCERTAIN, can_calc=False),
            ref,
            mrp=Decimal("80.00"),
        )
    with pytest.raises(ValueError, match="MRP is missing"):
        calculate_discrepancy(_make_match(units=10), ref, mrp=None)
