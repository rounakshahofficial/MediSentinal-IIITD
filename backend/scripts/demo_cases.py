"""Runnable CLI demo for Step 3: calculator.py + cases.py (rolls back demo rows cleanly)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.cases import evaluate_and_save_case  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Listing  # noqa: E402


def main() -> None:
    scenarios = [
        Listing(
            site="1mg",
            url="https://www.1mg.com/drugs/atorva-10-tablet-demo",
            product_name="Atorva 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw="strip of 10 tablets",
            mrp=Decimal("78.50"),
            selling_price=Decimal("69.00"),
            raw_json={},
            screenshot_path="/storage/evidence/demo_1mg_1.svg",
        ),
        Listing(
            site="1mg",
            url="https://www.1mg.com/drugs/atorva-10-tablet-demo?scan=2",
            product_name="Atorva 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw="strip of 10 tablets",
            mrp=Decimal("79.00"),
            selling_price=Decimal("70.00"),
            raw_json={},
            screenshot_path="/storage/evidence/demo_1mg_2.svg",
        ),
        Listing(
            site="pharmeasy",
            url="https://pharmeasy.in/online-medicine-order/storvas-10",
            product_name="Storvas 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw="strip of 10 tablets",
            mrp=Decimal("64.20"),  # +0.39% over 6.3952 -> within 1.0% tolerance
            selling_price=Decimal("58.00"),
            raw_json={},
        ),
        Listing(
            site="netmeds",
            url="https://www.netmeds.com/prescriptions/lipitor-20-tablet",
            product_name="Lipitor 20 Tablet",
            composition_raw="Atorvastatin (20mg)",
            pack_size_raw="1 strip",  # Unclear pack -> uncertain -> needs_verification (STOP)
            mrp=Decimal("180.00"),
            selling_price=Decimal("165.00"),
            raw_json={},
        ),
    ]

    with SessionLocal() as session:
        try:
            for idx, item in enumerate(scenarios, start=1):
                session.add(item)
                session.flush()
                match_row, case_row = evaluate_and_save_case(session, item)
                if case_row is None:
                    print(
                        f"#{idx} [{item.site}] {item.product_name}: "
                        f"match={match_row.status} -> COMPLIANT / NO CASE OPENED"
                    )
                else:
                    print(
                        f"#{idx} [{item.site}] {item.product_name}: "
                        f"case_status={case_row.status} | "
                        f"discrepancy={case_row.discrepancy_percent}% | "
                        f"recurrent={case_row.is_recurrent} | "
                        f"priority={case_row.priority_score}"
                    )
                    if case_row.formula:
                        print(f"    formula: {case_row.formula}")
        finally:
            session.rollback()


if __name__ == "__main__":
    main()
