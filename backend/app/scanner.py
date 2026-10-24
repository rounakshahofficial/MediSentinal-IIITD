"""Online pharmacy scanner: TinyFish ScannerClient + MockScanner with retries & scan_logs."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cases import evaluate_and_save_case
from app.config import Settings, get_settings
from app.models import (
    CaseStatus,
    Listing,
    MatchStatus,
    ReferencePrice,
    ScanLog,
    ScanLogStatus,
)
from app.schemas import ScannedListingItem, ScanRunSummary

# Scope strictly limited to 3 permitted Indian online pharmacy portals (no offline/map data)
PERMITTED_PHARMACY_SITES: dict[str, str] = {
    "1mg": "https://www.1mg.com/search/all?name={query}",
    "pharmeasy": "https://pharmeasy.in/search/all?name={query}",
    "netmeds": "https://www.netmeds.com/catalogsearch/result/{query}/all",
}

_RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


class ScannerError(RuntimeError):
    """Raised when a scanner target fails after exhausting permitted retry attempts."""

    def __init__(
        self,
        message: str,
        *,
        site: str,
        attempt_count: int = 1,
        error_type: str = "ScannerError",
        scan_log_id: int | None = None,
    ) -> None:
        super().__init__(message)
        self.site = site
        self.attempt_count = attempt_count
        self.error_type = error_type
        self.scan_log_id = scan_log_id


class _NonRetryableScanError(Exception):
    """Internal wrapper signaling permanent auth/config/client errors that must not retry."""


class ScannerProtocol(Protocol):
    """Common interface implemented by both ScannerClient and MockScanner."""

    mode_name: str

    def scan_medicine_family(
        self,
        family: str,
        sites: Sequence[str] | None = None,
        db: Session | None = None,
        raise_on_error: bool = True,
    ) -> list[ScannedListingItem]: ...


def validate_requested_sites(sites: Sequence[str] | None) -> list[str]:
    """Validate requested site slugs against the 3 permitted online pharmacies."""
    if not sites:
        return list(PERMITTED_PHARMACY_SITES.keys())
    normalized: list[str] = []
    for raw in sites:
        slug = raw.strip().lower()
        if slug not in PERMITTED_PHARMACY_SITES:
            allowed = ", ".join(PERMITTED_PHARMACY_SITES.keys())
            raise ValueError(
                f"Unpermitted pharmacy site '{raw}'. Permitted sites: {allowed}"
            )
        if slug not in normalized:
            normalized.append(slug)
    return normalized


def build_tinyfish_goal_prompt(site: str, family: str) -> str:
    """Build deterministic TinyFish extraction & screenshot goal prompt."""
    return (
        f"You are auditing public medicine listings on {site} for the medicine family "
        f"'{family}'. Open up to 5 relevant product detail pages and capture a full "
        "product-card screenshot on each page.\n"
        "Extract the EXACT verbatim text displayed on the page without rewriting or guessing:\n"
        "1. product_name: exact product title string.\n"
        "2. composition_raw: exact active ingredient / salt composition text (null if absent).\n"
        "3. pack_size_raw: exact strip/bottle/pack unit text such as 'strip of 10 tablets' (null if absent).\n"
        "4. mrp: numeric Maximum Retail Price (inclusive of all taxes) in INR; null if MRP is not shown "
        "(NEVER substitute selling_price for mrp).\n"
        "5. selling_price: numeric current consumer selling price in INR; null if absent.\n"
        "6. url: full https:// canonical product URL.\n"
        "7. screenshot_url or screenshot_base64: captured visual evidence of the listing.\n"
        "Return strict JSON matching this exact structure:\n"
        '{"listings": [{"product_name": "...", "composition_raw": "...", '
        '"pack_size_raw": "...", "mrp": "78.50", "selling_price": "69.00", '
        '"url": "https://...", "screenshot_url": "https://..."}]}'
    )


def _record_scan_log(
    db: Session | None,
    *,
    scanner_mode: str,
    medicine_family: str,
    site: str,
    target_url: str | None,
    status: ScanLogStatus,
    attempt_count: int,
    listings_extracted: int,
    duration_ms: int,
    error_type: str | None = None,
    error_message: str | None = None,
    details_json: dict[str, Any] | None = None,
) -> ScanLog | None:
    """Persist execution/failure telemetry to scan_logs and commit immediately."""
    if db is None:
        return None
    log_row = ScanLog(
        scanner_mode=scanner_mode,
        medicine_family=medicine_family,
        site=site,
        target_url=target_url,
        status=status.value,
        attempt_count=attempt_count,
        listings_extracted=listings_extracted,
        duration_ms=duration_ms,
        error_type=error_type,
        error_message=error_message,
        details_json=details_json or {},
    )
    db.add(log_row)
    db.commit()
    db.refresh(log_row)
    return log_row


class ScannerClient:
    """Encapsulates ALL TinyFish Agent API calls (REST SSE & Python SDK).

    Check official TinyFish documentation at `# TODO(tinyfish-docs #1..#6)` below.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.mode_name = self.settings.scanner_mode
        self._sleep = sleep_fn
        if not self.settings.tinyfish_api_key:
            raise ValueError(
                "TINYFISH_API_KEY is empty. Set TINYFISH_API_KEY in backend/.env "
                "or use SCANNER_MODE=mock."
            )

    def scan_medicine_family(
        self,
        family: str,
        sites: Sequence[str] | None = None,
        db: Session | None = None,
        raise_on_error: bool = True,
    ) -> list[ScannedListingItem]:
        """Scan `family` across permitted sites with retries, timeouts, and scan_logs."""
        target_sites = validate_requested_sites(sites)
        clean_family = family.strip()
        if not clean_family:
            raise ValueError("medicine family query cannot be empty.")

        collected: list[ScannedListingItem] = []
        for site in target_sites:
            try:
                site_items = self._scan_single_site(
                    site=site,
                    family=clean_family,
                    db=db,
                )
                collected.extend(site_items)
            except ScannerError:
                if raise_on_error:
                    raise
        return collected

    def _scan_single_site(
        self,
        site: str,
        family: str,
        db: Session | None,
    ) -> list[ScannedListingItem]:
        search_url = PERMITTED_PHARMACY_SITES[site].format(query=quote_plus(family))
        goal_prompt = build_tinyfish_goal_prompt(site=site, family=family)
        max_attempts = max(1, self.settings.scanner_max_retries)
        started = time.monotonic()

        attempt_errors: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] | None = None
        attempts_used = 0

        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            try:
                if self.settings.scanner_mode == "tinyfish_sdk":
                    raw_records = self._run_via_python_sdk(search_url, goal_prompt)
                else:
                    raw_records = self._run_via_rest_sse(search_url, goal_prompt)
                break
            except _NonRetryableScanError as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                cause = exc.__cause__ or exc
                err_type = type(cause).__name__
                attempt_errors.append(
                    {"attempt": attempt, "error_type": err_type, "message": str(exc)}
                )
                log_row = _record_scan_log(
                    db,
                    scanner_mode=self.mode_name,
                    medicine_family=family,
                    site=site,
                    target_url=search_url,
                    status=ScanLogStatus.FAILED,
                    attempt_count=attempt,
                    listings_extracted=0,
                    duration_ms=duration_ms,
                    error_type=err_type,
                    error_message=str(exc),
                    details_json={"attempt_errors": attempt_errors, "retryable": False},
                )
                raise ScannerError(
                    str(exc),
                    site=site,
                    attempt_count=attempt,
                    error_type=err_type,
                    scan_log_id=log_row.id if log_row else None,
                ) from cause
            except Exception as exc:
                err_type = type(exc).__name__
                attempt_errors.append(
                    {"attempt": attempt, "error_type": err_type, "message": str(exc)}
                )
                if attempt < max_attempts:
                    backoff = self.settings.scanner_backoff_seconds * (2 ** (attempt - 1))
                    if backoff > 0:
                        self._sleep(backoff)
                else:
                    duration_ms = int((time.monotonic() - started) * 1000)
                    log_row = _record_scan_log(
                        db,
                        scanner_mode=self.mode_name,
                        medicine_family=family,
                        site=site,
                        target_url=search_url,
                        status=ScanLogStatus.FAILED,
                        attempt_count=attempts_used,
                        listings_extracted=0,
                        duration_ms=duration_ms,
                        error_type=err_type,
                        error_message=str(exc),
                        details_json={"attempt_errors": attempt_errors, "retryable": True},
                    )
                    raise ScannerError(
                        f"Scan failed for site '{site}' after {attempts_used} attempt(s): {exc}",
                        site=site,
                        attempt_count=attempts_used,
                        error_type=err_type,
                        scan_log_id=log_row.id if log_row else None,
                    ) from exc

        assert raw_records is not None
        validated_items: list[ScannedListingItem] = []
        validation_errors: list[dict[str, Any]] = []

        for idx, raw_item in enumerate(raw_records):
            try:
                validated_items.append(self._normalize_raw_record(site, raw_item))
            except ValidationError as val_exc:
                validation_errors.append(
                    {"index": idx, "errors": json.loads(val_exc.json(include_url=False))}
                )

        duration_ms = int((time.monotonic() - started) * 1000)
        log_status = (
            ScanLogStatus.PARTIAL
            if validation_errors and validated_items
            else (
                ScanLogStatus.FAILED
                if validation_errors and not validated_items
                else ScanLogStatus.SUCCEEDED
            )
        )
        _record_scan_log(
            db,
            scanner_mode=self.mode_name,
            medicine_family=family,
            site=site,
            target_url=search_url,
            status=log_status,
            attempt_count=attempts_used,
            listings_extracted=len(validated_items),
            duration_ms=duration_ms,
            error_type="ValidationError" if validation_errors else None,
            error_message=(
                f"{len(validation_errors)} item(s) failed strict schema validation."
                if validation_errors
                else None
            ),
            details_json={
                "attempt_errors": attempt_errors,
                "validation_errors": validation_errors,
            },
        )
        return validated_items

    def _run_via_rest_sse(self, target_url: str, goal: str) -> list[dict[str, Any]]:
        """Invoke TinyFish REST SSE endpoint: POST /v1/automation/run-sse."""
        # TODO(tinyfish-docs #1): Confirm exact auth header name (`X-API-Key`) and
        # endpoint URL (`https://agent.tinyfish.ai/v1/automation/run-sse`).
        headers = {
            "X-API-Key": self.settings.tinyfish_api_key,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
        # TODO(tinyfish-docs #2): Verify exact request JSON fields for POST /v1/automation/run-sse
        # (e.g., `"url"`, `"goal"`, `"browser_profile": "stealth"`, or screenshot options).
        payload = {
            "url": target_url,
            "goal": goal,
        }

        timeout = httpx.Timeout(
            timeout=self.settings.scanner_timeout_seconds,
            connect=min(10.0, self.settings.scanner_timeout_seconds),
        )
        final_payload: dict[str, Any] = {}

        with httpx.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                self.settings.tinyfish_api_url,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body_preview = response.read().decode("utf-8", errors="replace")[:300]
                    msg = f"TinyFish HTTP {response.status_code}: {body_preview}"
                    if response.status_code in _RETRYABLE_HTTP_STATUSES:
                        raise httpx.HTTPStatusError(
                            msg, request=response.request, response=response
                        )
                    raise _NonRetryableScanError(msg)

                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw_data = line[len("data:") :].strip()
                    if not raw_data or raw_data == "[DONE]":
                        continue
                    event_obj = json.loads(raw_data)
                    # TODO(tinyfish-docs #3): Verify SSE event `type`/`status` values for
                    # agent failure vs completion (e.g., `"ERROR"`/`"FAILED"` vs `"COMPLETE"`).
                    event_type = str(event_obj.get("type") or event_obj.get("status") or "").upper()
                    if event_type in {"ERROR", "FAILED"}:
                        raise RuntimeError(
                            f"TinyFish SSE error event: {event_obj.get('error') or event_obj}"
                        )
                    if event_type in {"COMPLETE", "COMPLETED", "RESULT"} or (
                        "resultJson" in event_obj or "listings" in event_obj
                    ):
                        final_payload = event_obj

        return self._extract_listings_array(final_payload)

    def _run_via_python_sdk(self, target_url: str, goal: str) -> list[dict[str, Any]]:
        """Invoke TinyFish via Python SDK (`from tinyfish import TinyFish`)."""
        try:
            from tinyfish import TinyFish  # type: ignore[import-not-found]
        except ImportError as exc:
            raise _NonRetryableScanError(
                "TinyFish Python SDK is not installed. Install `tinyfish` or use "
                "SCANNER_MODE=tinyfish_rest / SCANNER_MODE=mock."
            ) from exc

        # TODO(tinyfish-docs #5): Verify TinyFish Python SDK constructor (`api_key`, `timeout`)
        # and run method signature (`sdk_client.automation.run(...)` vs `sdk_client.agent.run(...)`).
        sdk_client = TinyFish(
            api_key=self.settings.tinyfish_api_key,
            timeout=self.settings.scanner_timeout_seconds,
        )
        result = sdk_client.automation.run(url=target_url, goal=goal)

        if isinstance(result, dict):
            return self._extract_listings_array(result)
        if hasattr(result, "model_dump"):
            return self._extract_listings_array(result.model_dump())
        return []

    @staticmethod
    def _extract_listings_array(container: dict[str, Any]) -> list[dict[str, Any]]:
        """Unwrap listings array from TinyFish result envelope."""
        # TODO(tinyfish-docs #4): Confirm exact output path (`resultJson.listings` vs `data.listings`).
        candidate = (
            container.get("resultJson")
            or container.get("result")
            or container.get("data")
            or container
        )
        if isinstance(candidate, str):
            candidate = json.loads(candidate)
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
        if isinstance(candidate, dict) and isinstance(candidate.get("listings"), list):
            return [row for row in candidate["listings"] if isinstance(row, dict)]
        return []

    def _persist_evidence_screenshot(
        self,
        site: str,
        raw_item: dict[str, Any],
    ) -> str | None:
        """Save screenshot artifact to /storage/evidence and return its FastAPI mount path."""
        self.settings.evidence_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(
            f"{site}:{raw_item.get('url', '')}:{raw_item.get('product_name', '')}".encode()
        ).hexdigest()[:12]

        # TODO(tinyfish-docs #6): Check whether TinyFish returns `screenshot_base64` or a
        # temporary signed `screenshot_url` (and whether downloading requires `X-API-Key`).
        b64_data = raw_item.get("screenshot_base64")
        if isinstance(b64_data, str) and b64_data.strip():
            payload = b64_data.split(",", 1)[-1]
            filename = f"tinyfish_{site}_{digest}.png"
            (self.settings.evidence_dir / filename).write_bytes(base64.b64decode(payload))
            return f"/storage/evidence/{filename}"

        remote_url = raw_item.get("screenshot_url")
        if isinstance(remote_url, str) and remote_url.startswith(("http://", "https://")):
            resp = httpx.get(
                remote_url,
                timeout=min(30.0, self.settings.scanner_timeout_seconds),
            )
            resp.raise_for_status()
            ext = ".svg" if "svg" in resp.headers.get("content-type", "") else ".png"
            filename = f"tinyfish_{site}_{digest}{ext}"
            (self.settings.evidence_dir / filename).write_bytes(resp.content)
            return f"/storage/evidence/{filename}"

        local_mount = raw_item.get("screenshot_path")
        return str(local_mount) if local_mount else None

    def _normalize_raw_record(
        self,
        site: str,
        raw_item: dict[str, Any],
    ) -> ScannedListingItem:
        screenshot_path = self._persist_evidence_screenshot(site, raw_item)
        return ScannedListingItem(
            site=site,  # type: ignore[arg-type]
            url=str(raw_item.get("url", "")),
            product_name=str(raw_item.get("product_name", "")),
            composition_raw=raw_item.get("composition_raw"),
            pack_size_raw=raw_item.get("pack_size_raw"),
            mrp=raw_item.get("mrp"),
            selling_price=raw_item.get("selling_price"),
            screenshot_path=screenshot_path,
            observed_at=raw_item.get("observed_at"),  # type: ignore[arg-type]
            raw_json=raw_item,
        )


class MockScanner:
    """Deterministic offline scanner reading cached JSON from backend/data/cached_scans/."""

    mode_name = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def scan_medicine_family(
        self,
        family: str,
        sites: Sequence[str] | None = None,
        db: Session | None = None,
        raise_on_error: bool = True,
    ) -> list[ScannedListingItem]:
        target_sites = validate_requested_sites(sites)
        family_slug = family.strip().lower()
        if not family_slug:
            raise ValueError("medicine family query cannot be empty.")

        items: list[ScannedListingItem] = []
        scans_dir: Path = self.settings.cached_scans_dir

        for site in target_sites:
            started = time.monotonic()
            candidate_file = scans_dir / f"{site}_{family_slug}.json"
            if not candidate_file.exists():
                duration_ms = int((time.monotonic() - started) * 1000)
                _record_scan_log(
                    db,
                    scanner_mode=self.mode_name,
                    medicine_family=family_slug,
                    site=site,
                    target_url=str(candidate_file),
                    status=ScanLogStatus.FAILED,
                    attempt_count=1,
                    listings_extracted=0,
                    duration_ms=duration_ms,
                    error_type="FileNotFoundError",
                    error_message=f"Cached scan file not found: {candidate_file.name}",
                )
                if raise_on_error and not scans_dir.exists():
                    raise ScannerError(
                        f"Cached scans directory missing: {scans_dir}",
                        site=site,
                        error_type="FileNotFoundError",
                    )
                continue

            try:
                payload = json.loads(candidate_file.read_text(encoding="utf-8"))
                raw_listings = (
                    payload.get("listings", []) if isinstance(payload, dict) else payload
                )
                site_items: list[ScannedListingItem] = []
                validation_errors: list[dict[str, Any]] = []

                for idx, entry in enumerate(raw_listings):
                    if not isinstance(entry, dict):
                        continue
                    try:
                        site_items.append(
                            ScannedListingItem(
                                site=str(entry.get("site") or site),  # type: ignore[arg-type]
                                url=str(entry.get("url", "")),
                                product_name=str(entry.get("product_name", "")),
                                composition_raw=entry.get("composition_raw"),
                                pack_size_raw=entry.get("pack_size_raw"),
                                mrp=entry.get("mrp"),
                                selling_price=entry.get("selling_price"),
                                screenshot_path=entry.get("screenshot_path"),
                                observed_at=entry.get("observed_at"),  # type: ignore[arg-type]
                                raw_json=entry,
                            )
                        )
                    except ValidationError as val_exc:
                        validation_errors.append(
                            {"index": idx, "errors": json.loads(val_exc.json(include_url=False))}
                        )

                duration_ms = int((time.monotonic() - started) * 1000)
                status = (
                    ScanLogStatus.PARTIAL
                    if validation_errors and site_items
                    else (
                        ScanLogStatus.FAILED
                        if validation_errors and not site_items
                        else ScanLogStatus.SUCCEEDED
                    )
                )
                _record_scan_log(
                    db,
                    scanner_mode=self.mode_name,
                    medicine_family=family_slug,
                    site=site,
                    target_url=f"file://{candidate_file.name}",
                    status=status,
                    attempt_count=1,
                    listings_extracted=len(site_items),
                    duration_ms=duration_ms,
                    error_type="ValidationError" if validation_errors else None,
                    error_message=(
                        f"{len(validation_errors)} cached item(s) failed validation."
                        if validation_errors
                        else None
                    ),
                    details_json={"validation_errors": validation_errors},
                )
                items.extend(site_items)
            except Exception as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                log_row = _record_scan_log(
                    db,
                    scanner_mode=self.mode_name,
                    medicine_family=family_slug,
                    site=site,
                    target_url=f"file://{candidate_file.name}",
                    status=ScanLogStatus.FAILED,
                    attempt_count=1,
                    listings_extracted=0,
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                if raise_on_error:
                    raise ScannerError(
                        str(exc),
                        site=site,
                        error_type=type(exc).__name__,
                        scan_log_id=log_row.id if log_row else None,
                    ) from exc

        return items


def get_scanner(settings: Settings | None = None) -> ScannerProtocol:
    """Return MockScanner or ScannerClient based on SCANNER_MODE in .env."""
    cfg = settings or get_settings()
    if cfg.scanner_mode == "mock":
        return MockScanner(cfg)
    return ScannerClient(cfg)


def run_scan_pipeline(
    db: Session,
    family: str = "atorvastatin",
    sites: Sequence[str] | None = None,
    scanner: ScannerProtocol | None = None,
    settings: Settings | None = None,
) -> ScanRunSummary:
    """Execute scan -> log to scan_logs -> save Listing -> parse/match -> calculate/case."""
    cfg = settings or get_settings()
    active_scanner = scanner or get_scanner(cfg)
    target_sites = validate_requested_sites(sites)

    prior_max_log_id = db.scalar(select(ScanLog.id).order_by(ScanLog.id.desc()).limit(1)) or 0

    scanned_items = active_scanner.scan_medicine_family(
        family=family,
        sites=target_sites,
        db=db,
        raise_on_error=False,
    )

    new_logs = list(
        db.scalars(
            select(ScanLog).where(ScanLog.id > prior_max_log_id).order_by(ScanLog.id.asc())
        ).all()
    )
    failed_sites = [
        log.site for log in new_logs if log.status == ScanLogStatus.FAILED.value
    ]
    scan_log_ids = [log.id for log in new_logs]

    references = list(db.scalars(select(ReferencePrice)).all())

    ingested = 0
    matched_count = 0
    uncertain_count = 0
    no_match_count = 0
    potential_discrepancies = 0
    needs_verification = 0
    created_case_ids: list[int] = []

    for item in scanned_items:
        obs_at = item.observed_at or datetime.now(timezone.utc)
        existing_listing = db.scalar(
            select(Listing).where(
                Listing.site == item.site,
                Listing.url == item.url,
                Listing.observed_at == obs_at,
            )
        )
        if existing_listing is None:
            listing_row = Listing(
                site=item.site,
                url=item.url,
                product_name=item.product_name,
                composition_raw=item.composition_raw,
                pack_size_raw=item.pack_size_raw,
                mrp=item.mrp,
                selling_price=item.selling_price,
                raw_json=item.raw_json,
                screenshot_path=item.screenshot_path,
                observed_at=obs_at,
            )
            db.add(listing_row)
            db.flush()
            ingested += 1
        else:
            listing_row = existing_listing

        match_row, case_row = evaluate_and_save_case(
            db,
            listing=listing_row,
            references=references,
            tolerance_percent=cfg.discrepancy_tolerance_percent,
        )

        if match_row.status == MatchStatus.MATCHED.value:
            matched_count += 1
        elif match_row.status == MatchStatus.UNCERTAIN.value:
            uncertain_count += 1
        else:
            no_match_count += 1

        if case_row is not None:
            created_case_ids.append(case_row.id)
            if case_row.status in {
                CaseStatus.POTENTIAL_DISCREPANCY.value,
                CaseStatus.CONFIRMED_FOR_REVIEW.value,
            }:
                potential_discrepancies += 1
            elif case_row.status in {
                CaseStatus.NEEDS_VERIFICATION.value,
                CaseStatus.NEEDS_MORE_EVIDENCE.value,
            }:
                needs_verification += 1

    db.commit()
    return ScanRunSummary(
        scanner_mode=active_scanner.mode_name,
        medicine_family=family.strip().lower(),
        sites_scanned=target_sites,
        failed_sites=failed_sites,
        listings_ingested=ingested,
        matched_count=matched_count,
        uncertain_count=uncertain_count,
        no_match_count=no_match_count,
        potential_discrepancies_flagged=potential_discrepancies,
        needs_verification_flagged=needs_verification,
        created_case_ids=created_case_ids,
        scan_log_ids=scan_log_ids,
        requested_scanner_mode=active_scanner.mode_name,
    )
