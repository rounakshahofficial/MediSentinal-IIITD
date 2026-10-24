"""Runnable CLI script for Step 4: executes MockScanner pipeline across all 3 sites."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Case  # noqa: E402
from app.scanner import MockScanner, run_scan_pipeline  # noqa: E402


def main() -> None:
    with SessionLocal() as session:
        summary = run_scan_pipeline(
            session,
            family="atorvastatin",
            scanner=MockScanner(),
        )
        print(f"Scan complete ({summary.scanner_mode}): {summary.model_dump_json(indent=2)}")
        print("\nPrioritized Triage Queue:")
        cases = list(
            session.scalars(
                select(Case).order_by(Case.priority_score.desc(), Case.id.asc())
            ).all()
        )
        for c in cases:
            print(
                f"  Case #{c.id:02d} | priority={c.priority_score:5.1f} | "
                f"status={c.status:21} | site={c.listing.site:9} | "
                f"discrepancy={str(c.discrepancy_percent) + '%' if c.discrepancy_percent is not None else 'N/A (STOP)':>10} | "
                f"recurrent={c.is_recurrent} | {c.listing.product_name}"
            )


if __name__ == "__main__":
    main()
