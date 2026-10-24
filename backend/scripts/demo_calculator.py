"""Runnable CLI check for Step 3: calculator.py across limit & GST edge cases."""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.calculator import calculate_discrepancy  # noqa: E402
from app.models import MatchStatus, ReferencePrice  # noqa: E402
from app.schemas import MatchEvaluation  # noqa: E402


def _matched(units: int = 10) -> MatchEvaluation:
    return MatchEvaluation(
        status=MatchStatus.MATCHED,
        reference_id=1,
        parsed_ingredient="Atorvastatin",
        parsed_strength="10 mg",
        parsed_form="tablet",
        units_in_pack=units,
        confidence=0.98,
        can_calculate_discrepancy=True,
    )


def _ref(ceiling: str, gst: str, version: str = "SAMPLE-2026-v1") -> ReferencePrice:
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


def main() -> None:
    examples = [
        ("Over limit (+22.75%)", _ref("5.7100", "12.00"), Decimal("78.50"), Decimal("69.00")),
        ("Exact ceiling+GST limit (0.00%)", _ref("10.0000", "12.00"), Decimal("112.00"), Decimal("105.00")),
        ("Exact +1.00% tolerance boundary", _ref("10.0000", "0.00"), Decimal("101.00"), Decimal("99.00")),
        ("Zero-GST 0% tax-exempt schedule", _ref("10.0000", "0.00"), Decimal("105.00"), Decimal("102.00")),
    ]

    for label, ref, mrp, sell in examples:
        res = calculate_discrepancy(_matched(10), ref, mrp=mrp, selling_price=sell, tolerance_percent=1.0)
        print(
            f"[{res.status_recommendation.upper():21}] {label}\n"
            f"  allowed={res.allowed_per_unit} | observed={res.observed_per_unit} | "
            f"discrepancy={res.discrepancy_percent:+.2f}% | ref_ver={res.reference_version}\n"
            f"  formula: {res.formula}\n"
        )


if __name__ == "__main__":
    main()
