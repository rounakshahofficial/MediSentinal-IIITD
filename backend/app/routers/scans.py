"""Routes for running pharmacy scans, inspecting scan_logs, and listing raw observations."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Listing, Match, ReferencePrice, ScanLog
from app.parser import parse_listing_fields
from app.scanner import (
    MockScanner,
    get_scanner,
    run_scan_pipeline,
    validate_requested_sites,
)
from app.schemas import (
    ListingWithMatchRead,
    MatchRead,
    ScanLogRead,
    ScanRunSummary,
    ScanTriggerRequest,
)
from scripts.seed_references import seed_reference_prices

router = APIRouter(tags=["scans"])


def _get_app_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


@router.post("/scans", response_model=ScanRunSummary)
@router.post("/api/scans", response_model=ScanRunSummary, include_in_schema=False)
@router.post("/api/scans/run", response_model=ScanRunSummary, include_in_schema=False)
def create_scan_run(
    request: Request,
    payload: ScanTriggerRequest = Body(default_factory=ScanTriggerRequest),
    db: Session = Depends(get_db),
) -> ScanRunSummary:
    """Execute pipeline: scan -> store listing -> parse -> match -> calculate -> case."""
    base_settings = _get_app_settings(request)
    effective_settings = (
        base_settings.model_copy(update={"scanner_mode": payload.scanner_mode})
        if payload.scanner_mode is not None
        else base_settings
    )

    ref_count = db.scalar(select(func.count()).select_from(ReferencePrice)) or 0
    default_csv = effective_settings.data_dir / "reference_prices.csv"
    if ref_count == 0 and default_csv.exists():
        seed_reference_prices(db, csv_path=default_csv)

    fallback_enabled = (
        payload.use_cached_fallback
        if payload.use_cached_fallback is not None
        else effective_settings.cached_run_fallback
    )
    requested_mode = effective_settings.scanner_mode

    try:
        target_sites = validate_requested_sites(payload.sites)
        try:
            scanner = get_scanner(effective_settings)
        except (ValueError, RuntimeError):
            if not fallback_enabled or requested_mode == "mock":
                raise
            cached = run_scan_pipeline(
                db,
                family=payload.medicine_family,
                sites=target_sites,
                scanner=MockScanner(effective_settings),
                settings=effective_settings,
            )
            return cached.model_copy(
                update={
                    "scanner_mode": f"{requested_mode}+mock_fallback",
                    "requested_scanner_mode": requested_mode,
                    "fallback_used": True,
                    "fallback_sites": target_sites,
                }
            )

        primary = run_scan_pipeline(
            db,
            family=payload.medicine_family,
            sites=target_sites,
            scanner=scanner,
            settings=effective_settings,
        )
        primary = primary.model_copy(
            update={"requested_scanner_mode": requested_mode}
        )

        failed_sites = list(dict.fromkeys(primary.failed_sites))
        if (
            not fallback_enabled
            or requested_mode == "mock"
            or not failed_sites
        ):
            return primary

        cached = run_scan_pipeline(
            db,
            family=payload.medicine_family,
            sites=failed_sites,
            scanner=MockScanner(effective_settings),
            settings=effective_settings,
        )
        still_failed = list(dict.fromkeys(cached.failed_sites))
        return ScanRunSummary(
            scanner_mode=f"{requested_mode}+mock_fallback",
            requested_scanner_mode=requested_mode,
            fallback_used=True,
            fallback_sites=failed_sites,
            medicine_family=primary.medicine_family,
            sites_scanned=primary.sites_scanned,
            failed_sites=still_failed,
            listings_ingested=primary.listings_ingested + cached.listings_ingested,
            matched_count=primary.matched_count + cached.matched_count,
            uncertain_count=primary.uncertain_count + cached.uncertain_count,
            no_match_count=primary.no_match_count + cached.no_match_count,
            potential_discrepancies_flagged=(
                primary.potential_discrepancies_flagged
                + cached.potential_discrepancies_flagged
            ),
            needs_verification_flagged=(
                primary.needs_verification_flagged
                + cached.needs_verification_flagged
            ),
            created_case_ids=primary.created_case_ids + cached.created_case_ids,
            scan_log_ids=primary.scan_log_ids + cached.scan_log_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/scans/logs", response_model=list[ScanLogRead])
@router.get("/api/scans/logs", response_model=list[ScanLogRead], include_in_schema=False)
def list_scan_logs(
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ScanLogRead]:
    """List recent scan_logs telemetry entries (attempts, timeouts, errors)."""
    rows = list(
        db.scalars(
            select(ScanLog)
            .order_by(ScanLog.created_at.desc(), ScanLog.id.desc())
            .limit(limit)
        ).all()
    )
    return [ScanLogRead.model_validate(r) for r in rows]


@router.get("/listings", response_model=list[ListingWithMatchRead])
@router.get("/api/listings", response_model=list[ListingWithMatchRead], include_in_schema=False)
def list_scanned_listings(
    site: str | None = Query(default=None),
    match_status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ListingWithMatchRead]:
    """List scanned pharmacy listings with their parsed match outcome and case link."""
    stmt = (
        select(Listing)
        .options(joinedload(Listing.match), joinedload(Listing.case))
        .order_by(Listing.observed_at.desc(), Listing.id.desc())
    )
    if site:
        stmt = stmt.where(func.lower(Listing.site) == site.strip().lower())
    if match_status:
        stmt = stmt.join(Match, Listing.id == Match.listing_id).where(
            Match.status == match_status.strip().lower()
        )

    rows = list(db.scalars(stmt).unique().all())
    output: list[ListingWithMatchRead] = []
    for row in rows:
        parsed = parse_listing_fields(
            product_name=row.product_name,
            composition_raw=row.composition_raw,
            pack_size_raw=row.pack_size_raw,
        )
        output.append(
            ListingWithMatchRead(
                id=row.id,
                site=row.site,
                url=row.url,
                product_name=row.product_name,
                composition_raw=row.composition_raw,
                pack_size_raw=row.pack_size_raw,
                mrp=row.mrp,
                selling_price=row.selling_price,
                raw_json=row.raw_json,
                screenshot_path=row.screenshot_path,
                observed_at=row.observed_at,
                match=MatchRead.model_validate(row.match) if row.match else None,
                raw_audit=parsed.raw_audit,
                case_id=row.case.id if row.case else None,
                case_status=row.case.status if row.case else None,
            )
        )
    return output
