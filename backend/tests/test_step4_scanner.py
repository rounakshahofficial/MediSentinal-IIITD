"""Step 4 tests: strict listing schema, TinyFish goal prompt, retries, timeouts & scan_logs."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import Base, build_engine
from app.models import Case, Listing, ScanLog, ScanLogStatus
from app.scanner import (
    MockScanner,
    ScannerClient,
    ScannerError,
    build_tinyfish_goal_prompt,
    run_scan_pipeline,
    validate_requested_sites,
)
from app.schemas import ScannedListingItem
from scripts.seed_references import seed_reference_prices


def test_strict_scanned_listing_schema_accepts_valid_and_rejects_malformed() -> None:
    valid = ScannedListingItem(
        site="1mg",
        url="https://www.1mg.com/drugs/atorva-10",
        product_name="Atorva 10 Tablet",
        composition_raw="Atorvastatin (10mg)",
        pack_size_raw="strip of 10 tablets",
        mrp="₹1,078.50",  # type: ignore[arg-type]
        selling_price="Rs. 950.00",  # type: ignore[arg-type]
        raw_json={"title": "Atorva 10 Tablet"},
    )
    assert str(valid.mrp) == "1078.50"
    assert str(valid.selling_price) == "950.00"

    # Reject unpermitted site
    with pytest.raises(ValidationError):
        ScannedListingItem(
            site="offline_chemist",  # type: ignore[arg-type]
            url="https://example.com/p",
            product_name="Atorva 10",
        )

    # Reject non-http URL
    with pytest.raises(ValidationError):
        ScannedListingItem(
            site="1mg",
            url="ftp://www.1mg.com/bad",
            product_name="Atorva 10",
        )

    # Reject non-positive MRP
    with pytest.raises(ValidationError):
        ScannedListingItem(
            site="1mg",
            url="https://www.1mg.com/drugs/atorva-10",
            product_name="Atorva 10",
            mrp="-5.00",  # type: ignore[arg-type]
        )

    # Reject unknown extra top-level keys (extra="forbid")
    with pytest.raises(ValidationError):
        ScannedListingItem(
            site="1mg",
            url="https://www.1mg.com/drugs/atorva-10",
            product_name="Atorva 10",
            unexpected_field="nope",  # type: ignore[call-arg]
        )


def test_tinyfish_goal_prompt_requests_all_seven_required_fields_and_screenshot() -> None:
    prompt = build_tinyfish_goal_prompt(site="1mg", family="atorvastatin")
    for token in (
        "product_name",
        "composition_raw",
        "pack_size_raw",
        "mrp",
        "selling_price",
        "url",
        "screenshot",
    ):
        assert token in prompt


def test_permitted_sites_validation_enforces_three_online_pharmacies() -> None:
    assert validate_requested_sites(None) == ["1mg", "pharmeasy", "netmeds"]
    with pytest.raises(ValueError, match="Unpermitted pharmacy site"):
        validate_requested_sites(["offline_local_chemist"])


def test_scanner_client_retries_timeout_and_503_then_succeeds_and_logs_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'retry_ok.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\nMOCKPNG").decode("ascii")
    sse_ok = "\n".join(
        [
            'data: {"type": "PROGRESS", "step": "Opening listing"}',
            "data: "
            + json.dumps(
                {
                    "type": "COMPLETE",
                    "resultJson": {
                        "listings": [
                            {
                                "url": "https://www.1mg.com/drugs/atorva-10-live",
                                "product_name": "Atorva 10 Tablet",
                                "composition_raw": "Atorvastatin (10mg)",
                                "pack_size_raw": "strip of 10 tablets",
                                "mrp": "₹78.50",
                                "selling_price": "₹69.00",
                                "screenshot_base64": f"data:image/png;base64,{tiny_png}",
                                "observed_at": "2026-10-23T12:00:00Z",
                            },
                            {
                                # Malformed URL item -> exercises partial validation logging
                                "url": "not-an-http-url",
                                "product_name": "Broken Row",
                            },
                        ]
                    },
                }
            ),
            "data: [DONE]",
        ]
    ).encode("utf-8")

    call_counter = {"n": 0}
    sleeps: list[float] = []
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        call_counter["n"] += 1
        captured_headers.update(dict(request.headers))
        if call_counter["n"] == 1:
            raise httpx.ReadTimeout("Simulated SSE stream timeout", request=request)
        if call_counter["n"] == 2:
            return httpx.Response(503, text="Upstream TinyFish busy")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_ok,
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        "app.scanner.httpx.Client",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handler)),
    )

    settings = Settings(
        scanner_mode="tinyfish_rest",
        tinyfish_api_key="tf_test_key_placeholder",
        scanner_timeout_seconds=15.0,
        scanner_max_retries=3,
        scanner_backoff_seconds=0.5,
        evidence_dir=tmp_path / "evidence",
        cached_scans_dir=tmp_path / "cached_scans",
    )
    client = ScannerClient(settings, sleep_fn=sleeps.append)

    with TestSession() as session:
        items = client.scan_medicine_family("atorvastatin", sites=["1mg"], db=session)
        assert len(items) == 1
        assert items[0].product_name == "Atorva 10 Tablet"
        assert captured_headers.get("x-api-key") == "tf_test_key_placeholder"
        assert sleeps == [0.5, 1.0]  # Exponential backoff across attempts 1 & 2

        logs = list(session.scalars(select(ScanLog)).all())
        assert len(logs) == 1
        assert logs[0].attempt_count == 3
        assert logs[0].status == ScanLogStatus.PARTIAL.value
        assert logs[0].listings_extracted == 1
        assert len(logs[0].details_json["attempt_errors"]) == 2
        assert len(logs[0].details_json["validation_errors"]) == 1

    engine.dispose()


def test_scanner_client_logs_failed_scan_log_on_exhausted_timeout_and_non_retryable_401(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'retry_fail.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    mode = {"kind": "timeout"}
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if mode["kind"] == "timeout":
            raise httpx.ConnectTimeout("Timed out connecting to TinyFish", request=request)
        return httpx.Response(401, text="Invalid X-API-Key")

    real_client = httpx.Client
    monkeypatch.setattr(
        "app.scanner.httpx.Client",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handler)),
    )

    settings = Settings(
        scanner_mode="tinyfish_rest",
        tinyfish_api_key="tf_bad_key",
        scanner_timeout_seconds=5.0,
        scanner_max_retries=3,
        scanner_backoff_seconds=0.0,
        evidence_dir=tmp_path / "evidence",
        cached_scans_dir=tmp_path / "cached_scans",
    )
    client = ScannerClient(settings, sleep_fn=lambda _: None)

    with TestSession() as session:
        # 1. Persistent timeout -> retries all 3 times, logs status='failed' to scan_logs
        with pytest.raises(ScannerError) as exc_info:
            client.scan_medicine_family("atorvastatin", sites=["pharmeasy"], db=session)
        assert exc_info.value.attempt_count == 3
        assert attempts["count"] == 3

        # 2. HTTP 401 -> fails fast on attempt 1 without wasting retries, logs to scan_logs
        mode["kind"] = "401"
        attempts["count"] = 0
        with pytest.raises(ScannerError) as auth_exc:
            client.scan_medicine_family("atorvastatin", sites=["netmeds"], db=session)
        assert auth_exc.value.attempt_count == 1
        assert attempts["count"] == 1

        logs = list(session.scalars(select(ScanLog).order_by(ScanLog.id.asc())).all())
        assert len(logs) == 2
        assert logs[0].site == "pharmeasy"
        assert logs[0].status == "failed"
        assert logs[0].attempt_count == 3
        assert logs[0].error_type == "ConnectTimeout"

        assert logs[1].site == "netmeds"
        assert logs[1].status == "failed"
        assert logs[1].attempt_count == 1
        assert logs[1].details_json["retryable"] is False

    engine.dispose()


def test_mock_scanner_pipeline_ingests_cached_scans_and_records_scan_logs(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'step4_pipeline.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    settings = Settings(
        app_env="test",
        scanner_mode="mock",
        discrepancy_tolerance_percent=1.0,
        data_dir=BACKEND_DIR / "data",
        cached_scans_dir=BACKEND_DIR / "data" / "cached_scans",
        evidence_dir=tmp_path / "evidence",
    )

    with TestSession() as session:
        seed_reference_prices(session, csv_path=BACKEND_DIR / "data" / "reference_prices.csv")

        summary_one = run_scan_pipeline(
            session,
            family="atorvastatin",
            scanner=MockScanner(settings),
            settings=settings,
        )
        assert summary_one.listings_ingested == 10
        assert summary_one.potential_discrepancies_flagged == 5
        assert summary_one.needs_verification_flagged == 2
        assert summary_one.failed_sites == []
        assert len(summary_one.scan_log_ids) == 3

        log_count = session.scalar(select(func.count()).select_from(ScanLog))
        assert log_count == 3

        # Re-running same cached snapshots stays idempotent on listings & cases
        summary_two = run_scan_pipeline(
            session,
            family="atorvastatin",
            scanner=MockScanner(settings),
            settings=settings,
        )
        assert summary_two.listings_ingested == 0
        assert session.scalar(select(func.count()).select_from(Listing)) == 10
        assert session.scalar(select(func.count()).select_from(Case)) == 7

    engine.dispose()
