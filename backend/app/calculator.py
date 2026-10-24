"""Deterministic ceiling-price & potential discrepancy calculator (Core Rules 2, 3, 4, 5)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.config import get_settings
from app.models import MatchStatus, ReferencePrice
from app.schemas import DiscrepancyCalculation, MatchEvaluation

_FOUR_DP = Decimal("0.0001")
_TWO_DP = Decimal("0.01")
_HUNDRED = Decimal("100")


def compute_allowed_per_unit(
    ceiling_price_per_unit: Decimal,
    gst_percent: Decimal,
) -> Decimal:
    """Core Rule 3: allowed_per_unit = ceiling_price_per_unit * (1 + gst_percent/100).

    GST comes strictly from the reference row (supports 0%, 5%, 12%, 18%, etc.).
    """
    ceiling_dec = Decimal(str(ceiling_price_per_unit))
    gst_dec = Decimal(str(gst_percent))

    if ceiling_dec <= Decimal("0"):
        raise ValueError("ceiling_price_per_unit must be strictly positive.")
    if gst_dec < Decimal("0") or gst_dec > _HUNDRED:
        raise ValueError(f"gst_percent ({gst_dec}) must be between 0 and 100.")

    multiplier = Decimal("1") + (gst_dec / _HUNDRED)
    return (ceiling_dec * multiplier).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)


def calculate_discrepancy(
    match_eval: MatchEvaluation,
    reference: ReferencePrice,
    mrp: Decimal | None,
    selling_price: Decimal | None = None,
    tolerance_percent: float | Decimal | None = None,
) -> DiscrepancyCalculation:
    """Compute per-unit MRP & selling price comparison against NPPA reference (Rules 2-5).

    Raises ValueError if called when match status is not 'matched', units_in_pack is
    unclear, or mrp is missing/non-positive (enforcing Core Rule 2 stop gate).
    """
    if match_eval.status != MatchStatus.MATCHED or not match_eval.can_calculate_discrepancy:
        raise ValueError(
            f"Cannot calculate discrepancy when match status is '{match_eval.status.value}' "
            "(Core Rule 2: stop when match is not deterministic)."
        )
    if match_eval.units_in_pack is None or match_eval.units_in_pack <= 0:
        raise ValueError("Cannot calculate discrepancy without a positive units_in_pack.")
    if mrp is None or Decimal(str(mrp)) <= Decimal("0"):
        raise ValueError("Cannot calculate MRP discrepancy when listed MRP is missing or <= 0.")

    tol_dec = (
        Decimal(str(tolerance_percent))
        if tolerance_percent is not None
        else Decimal(str(get_settings().discrepancy_tolerance_percent))
    ).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    if tol_dec < Decimal("0"):
        raise ValueError(f"tolerance_percent ({tol_dec}) cannot be negative.")

    ceiling_dec = Decimal(str(reference.ceiling_price_per_unit)).quantize(
        _FOUR_DP, rounding=ROUND_HALF_UP
    )
    gst_dec = Decimal(str(reference.gst_percent)).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    mrp_dec = Decimal(str(mrp)).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    units_dec = Decimal(match_eval.units_in_pack)

    allowed_per_unit = compute_allowed_per_unit(ceiling_dec, gst_dec)
    observed_per_unit = (mrp_dec / units_dec).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)

    # Core Rule 4: strictly "more than" configured tolerance (e.g. > 1.00%, so +1.00% is not flagged)
    discrepancy_pct = (
        ((observed_per_unit - allowed_per_unit) / allowed_per_unit) * _HUNDRED
    ).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    exceeds_tolerance = discrepancy_pct > tol_dec

    reasons: list[str] = [
        f"Reference applied: {reference.ingredient} {reference.strength} "
        f"{reference.dosage_form} | order={reference.source_order} | "
        f"effective_from={reference.effective_from.isoformat()} | version={reference.version}.",
        f"Allowed ceiling with GST: {ceiling_dec} * (1 + {gst_dec}/100) = "
        f"INR {allowed_per_unit} per {reference.unit}.",
        f"Observed MRP per unit: INR {mrp_dec} / {match_eval.units_in_pack} units = "
        f"INR {observed_per_unit} per unit ({discrepancy_pct:+.2f}% vs. allowed).",
    ]

    selling_per_unit: Decimal | None = None
    selling_discrepancy_pct: Decimal | None = None
    selling_exceeds_tolerance = False
    selling_above_mrp_anomaly = False
    selling_formula_part = "selling_price=N/A"

    if selling_price is not None and Decimal(str(selling_price)) > Decimal("0"):
        sell_dec = Decimal(str(selling_price)).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
        selling_per_unit = (sell_dec / units_dec).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)
        selling_discrepancy_pct = (
            ((selling_per_unit - allowed_per_unit) / allowed_per_unit) * _HUNDRED
        ).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
        selling_exceeds_tolerance = selling_discrepancy_pct > tol_dec
        selling_above_mrp_anomaly = sell_dec > mrp_dec

        selling_formula_part = (
            f"selling_per_unit = {sell_dec} / {match_eval.units_in_pack} = "
            f"{selling_per_unit} ({selling_discrepancy_pct:+.2f}%)"
        )
        reasons.append(
            f"Observed selling price per unit: INR {sell_dec} / {match_eval.units_in_pack} units = "
            f"INR {selling_per_unit} per unit ({selling_discrepancy_pct:+.2f}% vs. allowed)."
        )
        if selling_above_mrp_anomaly:
            reasons.append(
                f"Pricing anomaly: listed selling_price (INR {sell_dec}) exceeds "
                f"listed MRP (INR {mrp_dec}); requires human verification."
            )
        elif selling_exceeds_tolerance:
            reasons.append(
                "Active consumer selling price per unit also exceeds allowed per-unit "
                f"reference above {tol_dec}% tolerance."
            )
        elif exceeds_tolerance:
            reasons.append(
                "Discounted selling price per unit is within allowed reference, "
                "though listed MRP per unit exceeds tolerance."
            )

    status_rec: Literal["potential_discrepancy", "needs_verification", "within_limit"]
    if exceeds_tolerance:
        status_rec = "potential_discrepancy"
        reasons.append(
            f"Flagged as potential discrepancy: MRP excess ({discrepancy_pct:+.2f}%) "
            f"exceeds configured tolerance ({tol_dec}%). Human review required."
        )
    elif selling_above_mrp_anomaly:
        status_rec = "needs_verification"
        reasons.append(
            "Listed MRP is within tolerance, but selling_price exceeds MRP; "
            "routed to needs_verification."
        )
    else:
        status_rec = "within_limit"
        reasons.append(
            f"Within compliance tolerance: MRP difference ({discrepancy_pct:+.2f}%) "
            f"is at or below configured tolerance ({tol_dec}%)."
        )

    formula = (
        f"allowed_per_unit = {ceiling_dec} * (1 + {gst_dec}/100) = {allowed_per_unit}; "
        f"observed_per_unit = {mrp_dec} / {match_eval.units_in_pack} = {observed_per_unit}; "
        f"{selling_formula_part}; "
        f"discrepancy_percent = (({observed_per_unit} - {allowed_per_unit}) / "
        f"{allowed_per_unit}) * 100 = {discrepancy_pct:+.2f}% (tolerance: {tol_dec}%)"
    )

    return DiscrepancyCalculation(
        allowed_per_unit=allowed_per_unit,
        observed_per_unit=observed_per_unit,
        selling_per_unit=selling_per_unit,
        discrepancy_percent=discrepancy_pct,
        selling_discrepancy_percent=selling_discrepancy_pct,
        tolerance_percent=tol_dec,
        exceeds_tolerance=exceeds_tolerance,
        selling_exceeds_tolerance=selling_exceeds_tolerance,
        selling_above_mrp_anomaly=selling_above_mrp_anomaly,
        status_recommendation=status_rec,
        formula=formula,
        reference_version=reference.version,
        source_order=reference.source_order,
        reasons=reasons,
    )
