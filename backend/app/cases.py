"""Pipeline case builder, recurrence grouping, priority scoring & review workflow (Rules 2-7)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.calculator import calculate_discrepancy, compute_allowed_per_unit
from app.config import get_settings
from app.matcher import match_and_save_listing
from app.models import (
    Case,
    CaseStatus,
    Listing,
    Match,
    MatchStatus,
    ReferencePrice,
    Review,
)
from app.schemas import DiscrepancyCalculation, PriorityBreakdown

_REVIEW_ACTION_TO_STATUS: dict[str, CaseStatus] = {
    "confirm": CaseStatus.CONFIRMED_FOR_REVIEW,
    "confirmed_for_review": CaseStatus.CONFIRMED_FOR_REVIEW,
    "dismiss": CaseStatus.DISMISSED,
    "dismissed": CaseStatus.DISMISSED,
    "needs_more_evidence": CaseStatus.NEEDS_MORE_EVIDENCE,
    "request_more_evidence": CaseStatus.NEEDS_MORE_EVIDENCE,
}

ACTIVE_DISCREPANCY_STATUSES = {
    CaseStatus.POTENTIAL_DISCREPANCY.value,
    CaseStatus.CONFIRMED_FOR_REVIEW.value,
}


def _normalize_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_url(url: str) -> str:
    base = url.strip().lower().split("?", 1)[0].split("#", 1)[0]
    return base.rstrip("/")


def build_recurrence_group_key(site: str, product_name: str) -> str:
    """Deterministic key grouping repeat observations of the same site + product."""
    return f"{_normalize_key(site)}::{_normalize_key(product_name)}"


def group_cases_by_recurrence(cases: Sequence[Case]) -> dict[str, list[Case]]:
    """Group active discrepancy cases by (site, normalized product_name)."""
    grouped: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        if case.status not in ACTIVE_DISCREPANCY_STATUSES:
            continue
        key = build_recurrence_group_key(case.listing.site, case.listing.product_name)
        grouped[key].append(case)
    return dict(grouped)


def find_prior_discrepancy_cases(db: Session, listing: Listing) -> list[Case]:
    """Core Rule 7: find chronologically earlier discrepancy cases on same site + product/URL."""
    site_norm = _normalize_key(listing.site)
    prod_norm = _normalize_key(listing.product_name)
    url_norm = _normalize_url(listing.url)

    earlier_filter = or_(
        Listing.observed_at < listing.observed_at,
        and_(
            Listing.observed_at == listing.observed_at,
            Listing.id < listing.id,
        ),
    )

    stmt = (
        select(Case)
        .join(Listing, Case.listing_id == Listing.id)
        .where(
            Listing.id != listing.id,
            func.lower(Listing.site) == site_norm,
            Case.status.in_(list(ACTIVE_DISCREPANCY_STATUSES)),
            earlier_filter,
        )
        .order_by(Listing.observed_at.asc(), Case.id.asc())
    )
    candidates = list(db.scalars(stmt).all())
    return [
        prior
        for prior in candidates
        if _normalize_key(prior.listing.product_name) == prod_norm
        or (url_norm and _normalize_url(prior.listing.url) == url_norm)
    ]


def compute_priority_breakdown(
    listing: Listing,
    match_confidence: float,
    calc: DiscrepancyCalculation | None,
    prior_cases: Sequence[Case],
    is_discrepancy_finding: bool,
) -> PriorityBreakdown:
    """Core Rule 6: Priority = discrepancy size + match confidence + evidence + recurrence."""
    reasons: list[str] = []

    # 1. Discrepancy size (0 - 45 points)
    discrepancy_pts = 0.0
    if calc is None:
        reasons.append(
            "Discrepancy size (+0.0/45): pending human verification before price math."
        )
    elif calc.exceeds_tolerance:
        pct = float(calc.discrepancy_percent)
        if pct > 30.0:
            base = 40.0
        elif pct > 20.0:
            base = 32.0
        elif pct > 10.0:
            base = 24.0
        elif pct > 5.0:
            base = 16.0
        else:
            base = 10.0
        selling_bonus = 5.0 if calc.selling_exceeds_tolerance else 0.0
        discrepancy_pts = min(45.0, base + selling_bonus)
        bonus_note = (
            " (includes +5.0 active selling-price excess)" if selling_bonus > 0 else ""
        )
        reasons.append(
            f"Discrepancy size (+{discrepancy_pts:.1f}/45): observed MRP exceeds allowed "
            f"reference by {calc.discrepancy_percent:+.2f}%{bonus_note}."
        )
    elif calc.selling_above_mrp_anomaly:
        discrepancy_pts = 8.0
        reasons.append(
            "Discrepancy size (+8.0/45): listed selling price exceeds listed MRP anomaly."
        )
    else:
        reasons.append("Discrepancy size (+0.0/45): within configured tolerance.")

    # 2. Match confidence (0 - 25 points)
    clamped_conf = min(1.0, max(0.0, match_confidence))
    confidence_pts = round(clamped_conf * 25.0, 1)
    reasons.append(
        f"Match confidence (+{confidence_pts:.1f}/25): deterministic match confidence "
        f"{clamped_conf * 100:.0f}%."
    )

    # 3. Evidence completeness (0 - 15 points)
    evidence_pts = 0.0
    present: list[str] = []
    missing: list[str] = []
    for label, ok, pts in (
        ("screenshot", bool(listing.screenshot_path), 6.0),
        (
            "composition_raw",
            bool(listing.composition_raw and listing.composition_raw.strip()),
            3.0,
        ),
        (
            "pack_size_raw",
            bool(listing.pack_size_raw and listing.pack_size_raw.strip()),
            3.0,
        ),
        ("mrp+url", listing.mrp is not None and bool(listing.url), 3.0),
    ):
        if ok:
            evidence_pts += pts
            present.append(label)
        else:
            missing.append(label)

    missing_note = f"; missing: {', '.join(missing)}" if missing else " (complete)"
    reasons.append(
        f"Evidence completeness (+{evidence_pts:.1f}/15): captured "
        f"{', '.join(present) if present else 'none'}{missing_note}."
    )

    # 4. Recurrence (0 - 15 points)
    prior_count = len(prior_cases) if is_discrepancy_finding else 0
    is_recurrent = prior_count > 0
    if prior_count >= 2:
        recurrence_pts = 15.0
    elif prior_count == 1:
        recurrence_pts = 10.0
    else:
        recurrence_pts = 0.0

    if is_recurrent:
        prior_ids = ", ".join(f"#{c.id}" for c in prior_cases[:3])
        reasons.append(
            f"Recurrence (+{recurrence_pts:.1f}/15): repeat finding on '{listing.site}' "
            f"with {prior_count} prior potential discrepancy case(s) ({prior_ids})."
        )
    else:
        reasons.append(
            "Recurrence (+0.0/15): no prior confirmed/open discrepancy recorded for "
            "this site + product."
        )

    total = round(
        min(100.0, discrepancy_pts + confidence_pts + evidence_pts + recurrence_pts), 1
    )
    return PriorityBreakdown(
        total_score=total,
        discrepancy_points=discrepancy_pts,
        confidence_points=confidence_pts,
        evidence_points=evidence_pts,
        recurrence_points=recurrence_pts,
        is_recurrent=is_recurrent,
        prior_discrepancy_count=prior_count,
        reasons=reasons,
    )


def _upsert_case_row(
    db: Session,
    listing: Listing,
    *,
    reference_id: int | None,
    observed_per_unit: Decimal | None,
    selling_per_unit: Decimal | None,
    allowed_per_unit: Decimal | None,
    discrepancy_percent: Decimal | None,
    formula: str | None,
    reference_version: str | None,
    calculation_reasons: list[str],
    priority: PriorityBreakdown,
    default_status: CaseStatus,
) -> Case:
    existing = db.scalar(select(Case).where(Case.listing_id == listing.id))
    if existing is None:
        case_row = Case(
            listing_id=listing.id,
            reference_id=reference_id,
            observed_per_unit=observed_per_unit,
            selling_per_unit=selling_per_unit,
            allowed_per_unit=allowed_per_unit,
            discrepancy_percent=discrepancy_percent,
            formula=formula,
            reference_version=reference_version,
            calculation_reasons=calculation_reasons,
            is_recurrent=priority.is_recurrent,
            priority_score=priority.total_score,
            priority_reasons=priority.reasons,
            status=default_status.value,
        )
        db.add(case_row)
    else:
        existing.reference_id = reference_id
        existing.observed_per_unit = observed_per_unit
        existing.selling_per_unit = selling_per_unit
        existing.allowed_per_unit = allowed_per_unit
        existing.discrepancy_percent = discrepancy_percent
        existing.formula = formula
        existing.reference_version = reference_version
        existing.calculation_reasons = calculation_reasons
        existing.is_recurrent = priority.is_recurrent
        existing.priority_score = priority.total_score
        existing.priority_reasons = priority.reasons
        if not existing.reviews:
            existing.status = default_status.value
        case_row = existing

    db.flush()
    return case_row


def evaluate_and_save_case(
    db: Session,
    listing: Listing,
    references: Sequence[ReferencePrice] | None = None,
    tolerance_percent: float | Decimal | None = None,
) -> tuple[Match, Case | None]:
    """Run parse -> match -> conditional calculate -> create case or needs_verification."""
    match_row, match_eval = match_and_save_listing(db, listing, references=references)
    tol = (
        tolerance_percent
        if tolerance_percent is not None
        else get_settings().discrepancy_tolerance_percent
    )

    if match_eval.status == MatchStatus.NO_MATCH:
        return match_row, None

    ref = (
        db.get(ReferencePrice, match_eval.reference_id)
        if match_eval.reference_id is not None
        else None
    )

    # Core Rule 2: 'uncertain' -> STOP before discrepancy math; create needs_verification case
    if match_eval.status == MatchStatus.UNCERTAIN:
        priority = compute_priority_breakdown(
            listing=listing,
            match_confidence=match_eval.confidence,
            calc=None,
            prior_cases=[],
            is_discrepancy_finding=False,
        )
        case_row = _upsert_case_row(
            db,
            listing,
            reference_id=match_eval.reference_id,
            observed_per_unit=None,
            selling_per_unit=None,
            allowed_per_unit=None,
            discrepancy_percent=None,
            formula=None,
            reference_version=ref.version if ref else None,
            calculation_reasons=[
                "Discrepancy calculation skipped: match status is 'uncertain' (Core Rule 2).",
                *match_eval.reasons,
            ],
            priority=priority,
            default_status=CaseStatus.NEEDS_VERIFICATION,
        )
        return match_row, case_row

    assert ref is not None
    if listing.mrp is None or Decimal(str(listing.mrp)) <= Decimal("0"):
        allowed = compute_allowed_per_unit(ref.ceiling_price_per_unit, ref.gst_percent)
        sell_unit: Decimal | None = None
        if (
            listing.selling_price is not None
            and Decimal(str(listing.selling_price)) > Decimal("0")
            and match_eval.units_in_pack
        ):
            sell_unit = (
                Decimal(str(listing.selling_price)) / Decimal(match_eval.units_in_pack)
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        priority = compute_priority_breakdown(
            listing=listing,
            match_confidence=match_eval.confidence,
            calc=None,
            prior_cases=[],
            is_discrepancy_finding=False,
        )
        case_row = _upsert_case_row(
            db,
            listing,
            reference_id=ref.id,
            observed_per_unit=None,
            selling_per_unit=sell_unit,
            allowed_per_unit=allowed,
            discrepancy_percent=None,
            formula=(
                f"allowed_per_unit = {ref.ceiling_price_per_unit} * "
                f"(1 + {ref.gst_percent}/100) = {allowed}; observed_per_unit = N/A (MRP missing)"
            ),
            reference_version=ref.version,
            calculation_reasons=[
                "Listed MRP is missing or non-positive; human verification of evidence "
                "screenshot required before MRP discrepancy calculation.",
            ],
            priority=priority,
            default_status=CaseStatus.NEEDS_VERIFICATION,
        )
        return match_row, case_row

    calc = calculate_discrepancy(
        match_eval=match_eval,
        reference=ref,
        mrp=listing.mrp,
        selling_price=listing.selling_price,
        tolerance_percent=tol,
    )

    if not calc.exceeds_tolerance and not calc.selling_above_mrp_anomaly:
        return match_row, None

    target_status = (
        CaseStatus.POTENTIAL_DISCREPANCY
        if calc.exceeds_tolerance
        else CaseStatus.NEEDS_VERIFICATION
    )
    prior_cases = (
        find_prior_discrepancy_cases(db, listing) if calc.exceeds_tolerance else []
    )
    priority = compute_priority_breakdown(
        listing=listing,
        match_confidence=match_eval.confidence,
        calc=calc,
        prior_cases=prior_cases,
        is_discrepancy_finding=calc.exceeds_tolerance,
    )
    case_row = _upsert_case_row(
        db,
        listing,
        reference_id=ref.id,
        observed_per_unit=calc.observed_per_unit,
        selling_per_unit=calc.selling_per_unit,
        allowed_per_unit=calc.allowed_per_unit,
        discrepancy_percent=calc.discrepancy_percent,
        formula=calc.formula,
        reference_version=calc.reference_version,
        calculation_reasons=calc.reasons,
        priority=priority,
        default_status=target_status,
    )
    return match_row, case_row


def record_case_review(
    db: Session,
    case: Case,
    action: str,
    reviewer: str,
    note: str | None = None,
) -> Review:
    """Record a human reviewer decision and transition the Case status."""
    normalized_action = action.strip().lower()
    if normalized_action not in _REVIEW_ACTION_TO_STATUS:
        valid = ", ".join(sorted(_REVIEW_ACTION_TO_STATUS.keys()))
        raise ValueError(f"Unsupported review action '{action}'. Expected one of: {valid}")
    if not reviewer or not reviewer.strip():
        raise ValueError("Reviewer identifier cannot be empty.")

    new_status = _REVIEW_ACTION_TO_STATUS[normalized_action]
    review = Review(
        case_id=case.id,
        action=normalized_action,
        note=note.strip() if note and note.strip() else None,
        reviewer=reviewer.strip(),
    )
    case.status = new_status.value
    db.add(review)
    db.flush()
    return review
