"""Idempotent seed script loading backend/data/reference_prices.csv into PostgreSQL/DB."""

from __future__ import annotations

import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Allow running directly as `python scripts/seed_references.py` from backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import BaseModel, Field, field_validator  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ReferencePrice  # noqa: E402


class ReferenceCsvRow(BaseModel):
    """Validated row parsed from reference_prices.csv."""

    ingredient: str = Field(min_length=1)
    strength: str = Field(min_length=1)
    dosage_form: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    ceiling_price_per_unit: Decimal = Field(gt=Decimal("0"))
    gst_percent: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))
    source_order: str = Field(min_length=1)
    effective_from: date
    version: str = Field(min_length=1)

    @field_validator("ingredient", "unit", "source_order", "version")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Field cannot be blank")
        return cleaned

    @field_validator("strength", "dosage_form")
    @classmethod
    def _normalize_lower(cls, value: str) -> str:
        cleaned = " ".join(value.lower().split())
        if not cleaned:
            raise ValueError("Field cannot be blank")
        return cleaned


def seed_reference_prices(
    db: Session,
    csv_path: Path | None = None,
) -> dict[str, int | bool]:
    """Upsert NPPA reference prices from CSV; return summary counts."""
    target_csv = csv_path or (get_settings().data_dir / "reference_prices.csv")
    if not target_csv.exists():
        raise FileNotFoundError(f"Reference CSV not found at: {target_csv}")

    inserted = 0
    updated = 0
    has_unverified_sample = False

    with target_csv.open("r", encoding="utf-8", newline="") as handle:
        data_lines = (
            line
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(data_lines)
        for line_num, raw_row in enumerate(reader, start=1):
            parsed = ReferenceCsvRow.model_validate(raw_row)
            markers = f"{parsed.source_order} {parsed.version}".upper()
            if "SAMPLE" in markers or "REPLACE" in markers or "UNVERIFIED" in markers:
                has_unverified_sample = True

            existing = db.scalar(
                select(ReferencePrice).where(
                    func.lower(ReferencePrice.ingredient) == parsed.ingredient.lower(),
                    ReferencePrice.strength == parsed.strength,
                    ReferencePrice.dosage_form == parsed.dosage_form,
                    ReferencePrice.version == parsed.version,
                )
            )
            if existing is None:
                db.add(
                    ReferencePrice(
                        ingredient=parsed.ingredient,
                        strength=parsed.strength,
                        dosage_form=parsed.dosage_form,
                        unit=parsed.unit,
                        ceiling_price_per_unit=parsed.ceiling_price_per_unit,
                        gst_percent=parsed.gst_percent,
                        source_order=parsed.source_order,
                        effective_from=parsed.effective_from,
                        version=parsed.version,
                    )
                )
                inserted += 1
            else:
                existing.ingredient = parsed.ingredient
                existing.unit = parsed.unit
                existing.ceiling_price_per_unit = parsed.ceiling_price_per_unit
                existing.gst_percent = parsed.gst_percent
                existing.source_order = parsed.source_order
                existing.effective_from = parsed.effective_from
                updated += 1

    db.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "total_processed": inserted + updated,
        "has_unverified_sample": has_unverified_sample,
    }


def main() -> None:
    csv_arg = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    with SessionLocal() as session:
        summary = seed_reference_prices(session, csv_path=csv_arg)

    print(
        f"Seeded reference_prices: inserted={summary['inserted']}, "
        f"updated={summary['updated']}, total={summary['total_processed']}"
    )
    if summary["has_unverified_sample"]:
        print(
            "WARNING: Loaded SAMPLE/UNVERIFIED reference rows. "
            "Replace backend/data/reference_prices.csv with verified values from "
            "official NPPA S.O. Gazette orders before compliance review use."
        )


if __name__ == "__main__":
    main()
