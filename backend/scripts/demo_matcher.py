"""Runnable CLI demo for parser.py & matcher.py across single-line and tricky listings."""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.matcher import evaluate_listing_match  # noqa: E402
from app.models import ReferencePrice  # noqa: E402

DEMO_REFERENCES = [
    ReferencePrice(
        id=1,
        ingredient="Paracetamol",
        strength="650 mg",
        dosage_form="tablet",
        unit="1 tablet",
        ceiling_price_per_unit=Decimal("2.0400"),
        gst_percent=Decimal("12.00"),
        source_order="SAMPLE-SO-DEMO",
        effective_from=date(2025, 4, 1),
        version="SAMPLE-v1",
    ),
    ReferencePrice(
        id=2,
        ingredient="Atorvastatin",
        strength="10 mg",
        dosage_form="tablet",
        unit="1 tablet",
        ceiling_price_per_unit=Decimal("5.7100"),
        gst_percent=Decimal("12.00"),
        source_order="SAMPLE-SO-DEMO",
        effective_from=date(2025, 4, 1),
        version="SAMPLE-v1",
    ),
]

DEMO_CASES = [
    ("Paracetamol 650mg Tablet, strip of 15", None, None),
    ("Atorva 10 Tablet", "Atorvastatin (10mg)", "Strip of 10 tablets"),
    ("Zerodol P Tablet", "Aceclofenac (100mg) + Paracetamol (325mg)", "Strip of 10 tablets"),
    ("Paracetamol 650mcg Research Tablet", "Paracetamol 650 mcg", "Strip of 10 tablets"),
    ("Paracetamol 650mg Syrup", "Paracetamol 650 mg", "bottle of 60 ml"),
    ("Storvas 10 Tablet", "Atorvastatin 10 mg", "1 strip"),
]


def main() -> None:
    for title, comp, pack in DEMO_CASES:
        res = evaluate_listing_match(
            product_name=title,
            composition_raw=comp,
            pack_size_raw=pack,
            references=DEMO_REFERENCES,
        )
        print(
            f"[{res.status.value.upper():9}] conf={res.confidence:0.2f} | "
            f"title={title!r} | ing={res.parsed_ingredient} | "
            f"str={res.parsed_strength} | form={res.parsed_form} | "
            f"units={res.units_in_pack} | can_calc={res.can_calculate_discrepancy}"
        )
        print(f"            reason: {res.reasons[-1]}")


if __name__ == "__main__":
    main()
