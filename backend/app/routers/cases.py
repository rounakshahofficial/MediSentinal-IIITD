"""Routes for /stats, /cases (filtering, sorting, recurrence grouping), dossiers & /review."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case as sql_case
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.cases import (
    ACTIVE_DISCREPANCY_STATUSES,
    build_recurrence_group_key,
    find_prior_discrepancy_cases,
    group_cases_by_recurrence,
    record_case_review,
)
from app.db import get_db
from app.models import (
    Case,
    CaseStatus,
    Listing,
    Match,
    MatchStatus,
    ReferencePrice,
)
from app.parser import parse_listing_fields
from app.pdf import render_dossier_pdf
from app.scanner import PERMITTED_PHARMACY_SITES
from app.schemas import (
    CaseDossierRead,
    CaseListItem,
    ListingRead,
    MatchRead,
    PriorCaseSummary,
    RecurrenceGroupSummary,
    ReferencePriceRead,
    ReviewCreateRequest,
    ReviewRead,
    SiteComplianceBreakdown,
    StatsResponse,
    StatusCountItem,
    TopDiscrepancyChartItem,
)

router = APIRouter(tags=["cases"])

CaseSortField = Literal[
    "priority_score",
    "discrepancy_percent",
    "created_at",
    "observed_per_unit",
]
SortOrder = Literal["asc", "desc"]

_STATUS_LABELS: list[tuple[str, str]] = [
    (CaseStatus.POTENTIAL_DISCREPANCY.value, "Potential Discrepancy"),
    (CaseStatus.NEEDS_VERIFICATION.value, "Needs Verification"),
    (CaseStatus.CONFIRMED_FOR_REVIEW.value, "Confirmed for Review"),
    (CaseStatus.NEEDS_MORE_EVIDENCE.value, "Needs More Evidence"),
    (CaseStatus.DISMISSED.value, "Dismissed"),
]


def _compute_group_counts(db: Session) -> dict[str, int]:
    """Count active discrepancy observations per (site, normalized product) group."""
    active_cases = list(
        db.scalars(
            select(Case)
            .options(joinedload(Case.listing))
            .where(Case.status.in_(list(ACTIVE_DISCREPANCY_STATUSES)))
        )
        .unique()
        .all()
    )
    grouped = group_cases_by_recurrence(active_cases)
    return {key: len(members) for key, members in grouped.items()}


def _build_case_dossier(db: Session, case: Case) -> CaseDossierRead:
    """Assemble full evidence dossier with raw-field provenance and recurrence history."""
    parsed = parse_listing_fields(
        product_name=case.listing.product_name,
        composition_raw=case.listing.composition_raw,
        pack_size_raw=case.listing.pack_size_raw,
    )
    group_key = build_recurrence_group_key(case.listing.site, case.listing.product_name)
    group_counts = _compute_group_counts(db)
    rec_count = group_counts.get(group_key, 1) if case.status in ACTIVE_DISCREPANCY_STATUSES else 1

    priors = find_prior_discrepancy_cases(db, case.listing)
    prior_summaries = [
        PriorCaseSummary(
            case_id=p.id,
            observed_at=p.listing.observed_at,
            observed_per_unit=p.observed_per_unit,
            discrepancy_percent=p.discrepancy_percent,
            status=p.status,
        )
        for p in priors
    ]
    return CaseDossierRead(
        id=case.id,
        listing_id=case.listing_id,
        reference_id=case.reference_id,
        observed_per_unit=case.observed_per_unit,
        selling_per_unit=case.selling_per_unit,
        allowed_per_unit=case.allowed_per_unit,
        discrepancy_percent=case.discrepancy_percent,
        formula=case.formula,
        reference_version=case.reference_version,
        calculation_reasons=case.calculation_reasons,
        is_recurrent=case.is_recurrent,
        priority_score=case.priority_score,
        priority_reasons=case.priority_reasons,
        status=CaseStatus(case.status),
        created_at=case.created_at,
        listing=ListingRead.model_validate(case.listing),
        match=MatchRead.model_validate(case.listing.match) if case.listing.match else None,
        reference=ReferencePriceRead.model_validate(case.reference) if case.reference else None,
        raw_audit=parsed.raw_audit,
        recurrence_group_key=group_key,
        recurrence_count=rec_count,
        prior_cases=prior_summaries,
        reviews=[ReviewRead.model_validate(r) for r in case.reviews],
    )


@router.get("/stats", response_model=StatsResponse)
@router.get("/api/stats", response_model=StatsResponse, include_in_schema=False)
@router.get("/api/dashboard/summary", response_model=StatsResponse, include_in_schema=False)
def get_compliance_stats(db: Session = Depends(get_db)) -> StatsResponse:
    """Compute compliance intelligence KPIs, recurrence groups, and chart series."""
    listings = list(
        db.scalars(
            select(Listing).options(joinedload(Listing.match), joinedload(Listing.case))
        )
        .unique()
        .all()
    )
    cases = list(
        db.scalars(
            select(Case).options(joinedload(Case.listing), joinedload(Case.reference))
        )
        .unique()
        .all()
    )
    refs = list(db.scalars(select(ReferencePrice)).all())

    has_unverified = any(
        any(
            tok in f"{r.source_order} {r.version}".upper()
            for tok in ("SAMPLE", "REPLACE", "UNVERIFIED")
        )
        for r in refs
    )

    matched_listings = sum(
        1 for l in listings if l.match and l.match.status == MatchStatus.MATCHED.value
    )
    uncertain_listings = sum(
        1 for l in listings if l.match and l.match.status == MatchStatus.UNCERTAIN.value
    )
    no_match_listings = sum(
        1 for l in listings if l.match and l.match.status == MatchStatus.NO_MATCH.value
    )
    compliant_matched = sum(
        1
        for l in listings
        if l.match
        and l.match.status == MatchStatus.MATCHED.value
        and l.case is None
    )

    status_counts = {key: 0 for key, _ in _STATUS_LABELS}
    for c in cases:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    by_site: list[SiteComplianceBreakdown] = []
    for site_slug in PERMITTED_PHARMACY_SITES:
        site_listings = [l for l in listings if l.site.lower() == site_slug]
        site_disc = sum(
            1
            for l in site_listings
            if l.case and l.case.status in ACTIVE_DISCREPANCY_STATUSES
        )
        site_verif = sum(
            1
            for l in site_listings
            if l.case
            and l.case.status
            in {
                CaseStatus.NEEDS_VERIFICATION.value,
                CaseStatus.NEEDS_MORE_EVIDENCE.value,
            }
        )
        site_compliant = sum(
            1
            for l in site_listings
            if l.match
            and l.match.status == MatchStatus.MATCHED.value
            and l.case is None
        )
        by_site.append(
            SiteComplianceBreakdown(
                site=site_slug,
                total_listings=len(site_listings),
                potential_discrepancies=site_disc,
                needs_verification=site_verif,
                compliant=site_compliant,
            )
        )

    comparable_cases = [
        c
        for c in cases
        if c.observed_per_unit is not None
        and c.allowed_per_unit is not None
        and c.discrepancy_percent is not None
        and c.status != CaseStatus.DISMISSED.value
    ]
    comparable_cases.sort(
        key=lambda c: float(c.discrepancy_percent or 0),
        reverse=True,
    )

    disc_values = [float(c.discrepancy_percent) for c in comparable_cases if c.discrepancy_percent is not None]
    avg_disc = round(sum(disc_values) / len(disc_values), 2) if disc_values else None
    max_disc = round(max(disc_values), 2) if disc_values else None

    top_discrepancies = [
        TopDiscrepancyChartItem(
            case_id=c.id,
            site=c.listing.site,
            product_name=c.listing.product_name,
            strength=c.reference.strength if c.reference else "",
            observed_per_unit=round(float(c.observed_per_unit), 4),  # type: ignore[arg-type]
            allowed_per_unit=round(float(c.allowed_per_unit), 4),  # type: ignore[arg-type]
            discrepancy_percent=round(float(c.discrepancy_percent), 2),  # type: ignore[arg-type]
        )
        for c in comparable_cases[:8]
    ]

    # Build recurrence groups (repeat findings with >= 2 active discrepancy cases)
    grouped_map = group_cases_by_recurrence(cases)
    recurrence_groups: list[RecurrenceGroupSummary] = []
    for key, members in grouped_map.items():
        if len(members) < 2:
            continue
        ordered = sorted(
            members,
            key=lambda m: (m.listing.observed_at, m.id),
            reverse=True,
        )
        latest = ordered[0]
        member_discs = [
            float(m.discrepancy_percent)
            for m in members
            if m.discrepancy_percent is not None
        ]
        recurrence_groups.append(
            RecurrenceGroupSummary(
                recurrence_group_key=key,
                site=latest.listing.site,
                product_name=latest.listing.product_name,
                occurrence_count=len(members),
                latest_case_id=latest.id,
                max_discrepancy_percent=round(max(member_discs), 2) if member_discs else None,
                case_ids=[m.id for m in ordered],
            )
        )
    recurrence_groups.sort(key=lambda g: g.occurrence_count, reverse=True)

    return StatsResponse(
        total_listings=len(listings),
        matched_listings=matched_listings,
        uncertain_listings=uncertain_listings,
        no_match_listings=no_match_listings,
        compliant_matched_listings=compliant_matched,
        total_cases=len(cases),
        open_potential_discrepancies=status_counts[CaseStatus.POTENTIAL_DISCREPANCY.value],
        needs_verification_count=status_counts[CaseStatus.NEEDS_VERIFICATION.value],
        confirmed_for_review_count=status_counts[CaseStatus.CONFIRMED_FOR_REVIEW.value],
        dismissed_count=status_counts[CaseStatus.DISMISSED.value],
        needs_more_evidence_count=status_counts[CaseStatus.NEEDS_MORE_EVIDENCE.value],
        recurrent_cases_count=sum(1 for c in cases if c.is_recurrent),
        average_discrepancy_percent=avg_disc,
        max_discrepancy_percent=max_disc,
        has_unverified_references=has_unverified,
        recurrence_groups=recurrence_groups,
        by_site=by_site,
        by_status=[
            StatusCountItem(status=key, label=label, count=status_counts.get(key, 0))
            for key, label in _STATUS_LABELS
        ],
        top_discrepancies=top_discrepancies,
        compliance_notice=(
            "MediSentinel surfaces potential discrepancies for human verification only; "
            "outputs are advisory triage dossiers, not legal determinations."
        ),
    )


@router.get("/cases", response_model=list[CaseListItem])
@router.get("/api/cases", response_model=list[CaseListItem], include_in_schema=False)
def list_cases(
    status: str | None = Query(default=None),
    site: str | None = Query(default=None),
    min_priority: float | None = Query(default=None, ge=0.0, le=100.0),
    min_discrepancy: float | None = Query(default=None),
    recurrent_only: bool = Query(default=False),
    group_recurrent: bool = Query(default=False),
    search: str | None = Query(default=None),
    sort_by: CaseSortField = Query(default="priority_score"),
    sort_order: SortOrder = Query(default="desc"),
    db: Session = Depends(get_db),
) -> list[CaseListItem]:
    """List compliance triage cases with filtering, sorting, and optional recurrence grouping."""
    sort_column_map = {
        "priority_score": Case.priority_score,
        "discrepancy_percent": Case.discrepancy_percent,
        "created_at": Case.created_at,
        "observed_per_unit": Case.observed_per_unit,
    }
    target_col = sort_column_map[sort_by]
    null_guard = sql_case((target_col.is_(None), 1), else_=0)
    primary_order = target_col.asc() if sort_order == "asc" else target_col.desc()

    stmt = (
        select(Case)
        .join(Listing, Case.listing_id == Listing.id)
        .outerjoin(Match, Listing.id == Match.listing_id)
        .outerjoin(ReferencePrice, Case.reference_id == ReferencePrice.id)
        .options(
            joinedload(Case.listing).joinedload(Listing.match),
            joinedload(Case.reference),
            selectinload(Case.reviews),
        )
        .order_by(null_guard.asc(), primary_order, Case.priority_score.desc(), Case.id.desc())
    )

    if status:
        stmt = stmt.where(Case.status == status.strip().lower())
    if site:
        stmt = stmt.where(Listing.site == site.strip().lower())
    if min_priority is not None:
        stmt = stmt.where(Case.priority_score >= min_priority)
    if min_discrepancy is not None:
        stmt = stmt.where(Case.discrepancy_percent >= Decimal(str(min_discrepancy)))
    if recurrent_only:
        stmt = stmt.where(Case.is_recurrent.is_(True))
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Listing.product_name.ilike(pattern),
                Listing.composition_raw.ilike(pattern),
                ReferencePrice.source_order.ilike(pattern),
            )
        )

    rows = list(db.scalars(stmt).unique().all())
    group_counts = _compute_group_counts(db)

    seen_groups: set[str] = set()
    output: list[CaseListItem] = []

    for row in rows:
        g_key = build_recurrence_group_key(row.listing.site, row.listing.product_name)
        is_active_disc = row.status in ACTIVE_DISCREPANCY_STATUSES
        rec_count = group_counts.get(g_key, 1) if is_active_disc else 1

        if group_recurrent and is_active_disc:
            if g_key in seen_groups:
                continue
            seen_groups.add(g_key)

        output.append(
            CaseListItem(
                id=row.id,
                listing_id=row.listing_id,
                reference_id=row.reference_id,
                observed_per_unit=row.observed_per_unit,
                selling_per_unit=row.selling_per_unit,
                allowed_per_unit=row.allowed_per_unit,
                discrepancy_percent=row.discrepancy_percent,
                formula=row.formula,
                reference_version=row.reference_version,
                calculation_reasons=row.calculation_reasons,
                is_recurrent=row.is_recurrent,
                priority_score=row.priority_score,
                priority_reasons=row.priority_reasons,
                status=CaseStatus(row.status),
                created_at=row.created_at,
                listing=ListingRead.model_validate(row.listing),
                match=(
                    MatchRead.model_validate(row.listing.match)
                    if row.listing.match
                    else None
                ),
                reference=(
                    ReferencePriceRead.model_validate(row.reference)
                    if row.reference
                    else None
                ),
                review_count=len(row.reviews),
                recurrence_group_key=g_key,
                recurrence_count=rec_count,
            )
        )
    return output


@router.get("/cases/{case_id}", response_model=CaseDossierRead)
@router.get("/api/cases/{case_id}", response_model=CaseDossierRead, include_in_schema=False)
def get_case_dossier(case_id: int, db: Session = Depends(get_db)) -> CaseDossierRead:
    """Return full evidence dossier for a single case."""
    stmt = (
        select(Case)
        .where(Case.id == case_id)
        .options(
            joinedload(Case.listing).joinedload(Listing.match),
            joinedload(Case.reference),
            selectinload(Case.reviews),
        )
    )
    case = db.scalar(stmt)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case #{case_id} not found.")
    return _build_case_dossier(db, case)


@router.get(
    "/cases/{case_id}/dossier.pdf",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Downloadable human-review evidence dossier.",
        },
        404: {"description": "Case not found."},
    },
)
@router.get(
    "/api/cases/{case_id}/dossier.pdf",
    response_class=Response,
    include_in_schema=False,
)
def download_case_dossier_pdf(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Generate an A4 evidence dossier PDF with listing, reference, math, and audit history."""
    stmt = (
        select(Case)
        .where(Case.id == case_id)
        .options(
            joinedload(Case.listing).joinedload(Listing.match),
            joinedload(Case.reference),
            selectinload(Case.reviews),
        )
    )
    case = db.scalar(stmt)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case #{case_id} not found.")

    dossier = _build_case_dossier(db, case)
    try:
        pdf_bytes = render_dossier_pdf(
            dossier,
            evidence_dir=request.app.state.settings.evidence_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not render the evidence dossier PDF.",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="medisentinel-case-{case_id}-dossier.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/cases/{case_id}/review", response_model=CaseDossierRead)
@router.post("/cases/{case_id}/reviews", response_model=CaseDossierRead, include_in_schema=False)
@router.post("/api/cases/{case_id}/review", response_model=CaseDossierRead, include_in_schema=False)
@router.post("/api/cases/{case_id}/reviews", response_model=CaseDossierRead, include_in_schema=False)
def submit_case_review(
    case_id: int,
    payload: ReviewCreateRequest,
    db: Session = Depends(get_db),
) -> CaseDossierRead:
    """Record a human reviewer decision (confirm, dismiss, or needs_more_evidence)."""
    stmt = (
        select(Case)
        .where(Case.id == case_id)
        .options(
            joinedload(Case.listing).joinedload(Listing.match),
            joinedload(Case.reference),
            selectinload(Case.reviews),
        )
    )
    case = db.scalar(stmt)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case #{case_id} not found.")

    try:
        record_case_review(
            db,
            case=case,
            action=payload.action,
            reviewer=payload.reviewer,
            note=payload.note,
        )
        db.commit()
        db.refresh(case)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    refreshed = db.scalar(stmt)
    assert refreshed is not None
    return _build_case_dossier(db, refreshed)
