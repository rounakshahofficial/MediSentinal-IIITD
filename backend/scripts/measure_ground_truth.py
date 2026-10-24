"""Compare a manual listing ground-truth CSV with persisted MediSentinel output."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import build_engine  # noqa: E402
from app.models import CaseStatus, Listing  # noqa: E402

_REQUIRED_COLUMNS = {
    "site",
    "url",
    "expected_ingredient",
    "expected_strength",
    "expected_dosage_form",
    "expected_units_in_pack",
    "expected_match_status",
    "expected_flag",
}
_ALLOWED_MATCH_STATUSES = {"matched", "uncertain", "no_match"}


@dataclass(frozen=True)
class GroundTruthRow:
    row_number: int
    site: str
    url: str
    observed_at: str | None
    expected_ingredient: str
    expected_strength: str
    expected_dosage_form: str
    expected_units_in_pack: int | None
    expected_match_status: str
    expected_flag: bool


@dataclass
class RowResult:
    row_number: int
    site: str
    url: str
    observed_at: str | None
    extracted: bool
    listing_id: int | None
    expected_match_status: str
    actual_match_status: str | None
    match_correct: bool | None
    expected_flag: bool
    actual_flag: bool | None
    notes: list[str]


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.query,
            "",
        )
    )


def _normalized_timestamp(value: str | datetime | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 observed_at value: {value!r}") from exc
    # SQLite may drop timezone metadata; compare the wall-clock ISO value consistently.
    return parsed.replace(tzinfo=None).isoformat(timespec="seconds")


def _parse_bool(value: str, *, row_number: int, column: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(
        f"Row {row_number}: {column} must be true/false (or 1/0), got {value!r}."
    )


def load_ground_truth(csv_path: Path) -> list[GroundTruthRow]:
    """Load and validate the documented manual-label CSV contract."""
    if not csv_path.is_file():
        raise ValueError(f"Ground-truth CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(_REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(
                "Ground-truth CSV is missing required columns: " + ", ".join(missing)
            )

        rows: list[GroundTruthRow] = []
        seen_keys: set[tuple[str, str, str | None]] = set()
        for row_number, raw in enumerate(reader, start=2):
            site = _normalized_text(raw.get("site"))
            url = (raw.get("url") or "").strip()
            if not site or not url:
                raise ValueError(f"Row {row_number}: site and url are required.")
            observed_at = _normalized_timestamp(raw.get("observed_at"))
            status = _normalized_text(raw.get("expected_match_status"))
            if status not in _ALLOWED_MATCH_STATUSES:
                raise ValueError(
                    f"Row {row_number}: expected_match_status must be one of "
                    f"{sorted(_ALLOWED_MATCH_STATUSES)}, got {status!r}."
                )

            units_raw = (raw.get("expected_units_in_pack") or "").strip()
            units = int(units_raw) if units_raw else None
            if units is not None and units <= 0:
                raise ValueError(
                    f"Row {row_number}: expected_units_in_pack must be positive."
                )
            expected_flag = _parse_bool(
                raw.get("expected_flag") or "",
                row_number=row_number,
                column="expected_flag",
            )
            key = (site, _normalized_url(url), observed_at)
            if key in seen_keys:
                raise ValueError(
                    f"Row {row_number}: duplicate ground-truth key {key}."
                )
            seen_keys.add(key)

            rows.append(
                GroundTruthRow(
                    row_number=row_number,
                    site=site,
                    url=url,
                    observed_at=observed_at,
                    expected_ingredient=(raw.get("expected_ingredient") or "").strip(),
                    expected_strength=(raw.get("expected_strength") or "").strip(),
                    expected_dosage_form=(
                        raw.get("expected_dosage_form") or ""
                    ).strip(),
                    expected_units_in_pack=units,
                    expected_match_status=status,
                    expected_flag=expected_flag,
                )
            )

    if not rows:
        raise ValueError("Ground-truth CSV has no data rows.")
    return rows


def _is_system_flag(listing: Listing) -> bool:
    """A price flag has discrepancy math and has not been dismissed by a reviewer."""
    return bool(
        listing.case
        and listing.case.discrepancy_percent is not None
        and listing.case.status != CaseStatus.DISMISSED.value
    )


def _match_is_correct(gt: GroundTruthRow, listing: Listing) -> tuple[bool, list[str]]:
    actual = listing.match
    if actual is None:
        return False, ["System listing has no match row."]
    notes: list[str] = []
    if actual.status != gt.expected_match_status:
        notes.append(
            f"Match status expected {gt.expected_match_status!r}, got {actual.status!r}."
        )
        return False, notes

    # For uncertain/no_match, the reviewer label is the intended matching outcome.
    if gt.expected_match_status != "matched":
        return True, notes

    checks = {
        "ingredient": (
            _normalized_text(gt.expected_ingredient),
            _normalized_text(actual.parsed_ingredient),
        ),
        "strength": (
            _normalized_text(gt.expected_strength),
            _normalized_text(actual.parsed_strength),
        ),
        "dosage_form": (
            _normalized_text(gt.expected_dosage_form),
            _normalized_text(actual.parsed_form),
        ),
        "units_in_pack": (gt.expected_units_in_pack, actual.units_in_pack),
    }
    for field, (expected, observed) in checks.items():
        if expected != observed:
            notes.append(f"{field} expected {expected!r}, got {observed!r}.")
    return not notes, notes


def measure(rows: list[GroundTruthRow], db: Session) -> dict[str, Any]:
    """Calculate extraction rate, deterministic match accuracy, and flag precision."""
    listings = list(
        db.scalars(
            select(Listing)
            .options(joinedload(Listing.match), joinedload(Listing.case))
            .order_by(Listing.observed_at.desc(), Listing.id.desc())
        )
        .unique()
        .all()
    )
    by_site_url: dict[tuple[str, str], list[Listing]] = {}
    for listing in listings:
        key = (_normalized_text(listing.site), _normalized_url(listing.url))
        by_site_url.setdefault(key, []).append(listing)

    results: list[RowResult] = []
    consumed_listing_ids: set[int] = set()
    gt_by_listing_id: dict[int, GroundTruthRow] = {}

    for gt in rows:
        candidates = by_site_url.get((gt.site, _normalized_url(gt.url)), [])
        selected: Listing | None = None
        notes: list[str] = []
        if gt.observed_at:
            selected = next(
                (
                    listing
                    for listing in candidates
                    if _normalized_timestamp(listing.observed_at) == gt.observed_at
                ),
                None,
            )
        elif len(candidates) == 1:
            selected = candidates[0]
        elif len(candidates) > 1:
            notes.append(
                "Multiple system observations share site + URL; set observed_at in the CSV."
            )

        if selected is None:
            results.append(
                RowResult(
                    row_number=gt.row_number,
                    site=gt.site,
                    url=gt.url,
                    observed_at=gt.observed_at,
                    extracted=False,
                    listing_id=None,
                    expected_match_status=gt.expected_match_status,
                    actual_match_status=None,
                    match_correct=None,
                    expected_flag=gt.expected_flag,
                    actual_flag=None,
                    notes=notes or ["No system listing matched this ground-truth key."],
                )
            )
            continue

        consumed_listing_ids.add(selected.id)
        gt_by_listing_id[selected.id] = gt
        correct, match_notes = _match_is_correct(gt, selected)
        actual_flag = _is_system_flag(selected)
        if actual_flag != gt.expected_flag:
            match_notes.append(
                f"Flag expected {gt.expected_flag}, got {actual_flag}."
            )
        results.append(
            RowResult(
                row_number=gt.row_number,
                site=gt.site,
                url=gt.url,
                observed_at=gt.observed_at,
                extracted=True,
                listing_id=selected.id,
                expected_match_status=gt.expected_match_status,
                actual_match_status=selected.match.status if selected.match else None,
                match_correct=correct,
                expected_flag=gt.expected_flag,
                actual_flag=actual_flag,
                notes=match_notes,
            )
        )

    extracted_results = [result for result in results if result.extracted]
    correct_matches = sum(result.match_correct is True for result in extracted_results)
    extraction_rate = len(extracted_results) / len(rows)
    match_accuracy = (
        correct_matches / len(extracted_results) if extracted_results else 0.0
    )

    true_positives = 0
    false_positives = 0
    false_negatives = 0
    unexpected_positive_listing_ids: list[int] = []
    for listing in listings:
        system_flag = _is_system_flag(listing)
        gt = gt_by_listing_id.get(listing.id)
        if system_flag:
            if gt is not None and gt.expected_flag:
                true_positives += 1
            else:
                false_positives += 1
                if gt is None:
                    unexpected_positive_listing_ids.append(listing.id)
        elif gt is not None and gt.expected_flag:
            false_negatives += 1

    # Missing extracted rows expected to be flagged are also false negatives.
    false_negatives += sum(
        1 for result in results if not result.extracted and result.expected_flag
    )
    flag_precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )

    return {
        "definitions": {
            "extraction_rate": "ground-truth listing observations found by site + URL + optional observed_at / all ground-truth rows",
            "match_accuracy": "extracted rows with correct expected match status; matched rows must also agree on ingredient, strength, dosage form, and pack units / extracted rows",
            "flag_precision": "true positive price flags / all system positive price flags; unlabelled system positives count as false positives",
            "system_positive_flag": "case has discrepancy_percent and is not dismissed",
        },
        "counts": {
            "ground_truth_rows": len(rows),
            "system_listings": len(listings),
            "extracted_ground_truth_rows": len(extracted_results),
            "correct_matches": correct_matches,
            "true_positive_flags": true_positives,
            "false_positive_flags": false_positives,
            "false_negative_flags": false_negatives,
        },
        "metrics": {
            "extraction_rate": round(extraction_rate, 6),
            "match_accuracy": round(match_accuracy, 6),
            "flag_precision": round(flag_precision, 6),
        },
        "unexpected_positive_listing_ids": unexpected_positive_listing_ids,
        "rows": [asdict(result) for result in results],
    }


def _print_report(report: dict[str, Any]) -> None:
    counts = report["counts"]
    metrics = report["metrics"]
    print("MediSentinel Ground-Truth Measurement")
    print("=" * 39)
    print(
        f"Extraction rate : {metrics['extraction_rate'] * 100:6.2f}% "
        f"({counts['extracted_ground_truth_rows']}/{counts['ground_truth_rows']})"
    )
    print(
        f"Match accuracy  : {metrics['match_accuracy'] * 100:6.2f}% "
        f"({counts['correct_matches']}/{counts['extracted_ground_truth_rows']})"
    )
    predicted_flags = counts["true_positive_flags"] + counts["false_positive_flags"]
    print(
        f"Flag precision  : {metrics['flag_precision'] * 100:6.2f}% "
        f"({counts['true_positive_flags']}/{predicted_flags})"
    )
    print(
        "Flag confusion  : "
        f"TP={counts['true_positive_flags']} "
        f"FP={counts['false_positive_flags']} "
        f"FN={counts['false_negative_flags']}"
    )

    problem_rows = [row for row in report["rows"] if row["notes"]]
    if problem_rows:
        print("\nRows needing inspection:")
        for row in problem_rows:
            print(
                f"- CSV row {row['row_number']} ({row['site']} · {row['url']}): "
                + "; ".join(row["notes"])
            )
    if report["unexpected_positive_listing_ids"]:
        print(
            "\nSystem positive listing IDs absent from ground truth: "
            + ", ".join(map(str, report["unexpected_positive_listing_ids"]))
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare a manual ground-truth CSV with MediSentinel database output."
    )
    parser.add_argument("ground_truth_csv", type=Path)
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy database URL; defaults to DATABASE_URL from backend/.env.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path for the full machine-readable report.",
    )
    parser.add_argument("--min-extraction-rate", type=float, default=None)
    parser.add_argument("--min-match-accuracy", type=float, default=None)
    parser.add_argument("--min-flag-precision", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows = load_ground_truth(args.ground_truth_csv)
        database_url = args.database_url or get_settings().database_url
        engine = build_engine(database_url)
        try:
            with Session(engine) as db:
                report = measure(rows, db)
        finally:
            engine.dispose()
    except (OSError, ValueError, SQLAlchemyError) as exc:
        print(f"Measurement error: {exc}", file=sys.stderr)
        return 1

    _print_report(report)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nJSON report: {args.json_output}")

    thresholds = {
        "extraction_rate": args.min_extraction_rate,
        "match_accuracy": args.min_match_accuracy,
        "flag_precision": args.min_flag_precision,
    }
    failures = [
        f"{metric}={report['metrics'][metric]:.4f} < {threshold:.4f}"
        for metric, threshold in thresholds.items()
        if threshold is not None and report["metrics"][metric] < threshold
    ]
    if failures:
        print("\nThreshold failure: " + "; ".join(failures), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
