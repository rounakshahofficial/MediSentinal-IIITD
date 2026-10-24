"""Routes for inspecting and seeding NPPA ceiling-price reference data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculator import compute_allowed_per_unit
from app.config import Settings, get_settings
from app.db import get_db
from app.models import ReferencePrice
from app.schemas import ReferenceListResponse, ReferencePriceWithAllowedRead
from scripts.seed_references import seed_reference_prices

router = APIRouter(tags=["references"])


def _get_app_settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


@router.get("/references", response_model=ReferenceListResponse)
@router.get("/api/references", response_model=ReferenceListResponse, include_in_schema=False)
def list_reference_prices(db: Session = Depends(get_db)) -> ReferenceListResponse:
    """List configured NPPA reference rows with computed allowed_per_unit (incl. GST)."""
    rows = list(
        db.scalars(
            select(ReferencePrice).order_by(
                ReferencePrice.ingredient.asc(),
                ReferencePrice.dosage_form.asc(),
                ReferencePrice.ceiling_price_per_unit.asc(),
            )
        ).all()
    )
    items: list[ReferencePriceWithAllowedRead] = []
    has_unverified = False

    for row in rows:
        markers = f"{row.source_order} {row.version}".upper()
        if "SAMPLE" in markers or "REPLACE" in markers or "UNVERIFIED" in markers:
            has_unverified = True
        allowed = compute_allowed_per_unit(row.ceiling_price_per_unit, row.gst_percent)
        items.append(
            ReferencePriceWithAllowedRead(
                id=row.id,
                ingredient=row.ingredient,
                strength=row.strength,
                dosage_form=row.dosage_form,
                unit=row.unit,
                ceiling_price_per_unit=row.ceiling_price_per_unit,
                gst_percent=row.gst_percent,
                allowed_per_unit=allowed,
                source_order=row.source_order,
                effective_from=row.effective_from,
                version=row.version,
            )
        )

    return ReferenceListResponse(items=items, has_unverified_sample=has_unverified)


@router.post("/references/seed")
@router.post("/api/references/seed", include_in_schema=False)
def trigger_reference_seed(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, int | bool]:
    """Idempotently upsert backend/data/reference_prices.csv into reference_prices."""
    settings = _get_app_settings(request)
    csv_path = settings.data_dir / "reference_prices.csv"
    if not csv_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Reference CSV not found at {csv_path}",
        )
    return seed_reference_prices(db, csv_path=csv_path)
