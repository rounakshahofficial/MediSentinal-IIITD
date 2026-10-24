"""Pydantic v2 schemas for MediSentinel domain logic and API payloads."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import CaseStatus, MatchStatus, ScanLogStatus

PermittedSite = Literal["1mg", "pharmeasy", "netmeds"]


class RawFieldAudit(BaseModel):
    """Preserves raw source text alongside extracted value for auditability (Rule 8)."""

    raw_text: str | None = None
    normalized_value: str | int | None = None
    source_field: str | None = None
    rule_applied: str | None = None


class ParsedListingFields(BaseModel):
    """Structured output of deterministic listing parsing (Rules 1 & 8)."""

    parsed_ingredient: str | None = None
    parsed_strength: str | None = None
    parsed_form: str | None = None
    units_in_pack: int | None = None
    is_combination: bool = False
    has_conflict: bool = False
    raw_audit: dict[str, RawFieldAudit] = Field(default_factory=dict)
    parse_notes: list[str] = Field(default_factory=list)


class MatchEvaluation(BaseModel):
    """Outcome of matching parsed listing fields against NPPA reference_prices (Rule 2)."""

    status: MatchStatus
    reference_id: int | None = None
    parsed_ingredient: str | None = None
    parsed_strength: str | None = None
    parsed_form: str | None = None
    units_in_pack: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    raw_audit: dict[str, RawFieldAudit] = Field(default_factory=dict)
    can_calculate_discrepancy: bool = False


class DiscrepancyCalculation(BaseModel):
    """Deterministic per-unit ceiling vs. observed MRP/selling price math (Rules 3, 4, 5)."""

    allowed_per_unit: Decimal
    observed_per_unit: Decimal
    selling_per_unit: Decimal | None = None
    discrepancy_percent: Decimal
    selling_discrepancy_percent: Decimal | None = None
    tolerance_percent: Decimal
    exceeds_tolerance: bool
    selling_exceeds_tolerance: bool = False
    selling_above_mrp_anomaly: bool = False
    status_recommendation: Literal[
        "potential_discrepancy", "needs_verification", "within_limit"
    ] = "within_limit"
    formula: str
    reference_version: str
    source_order: str
    reasons: list[str] = Field(default_factory=list)


class PriorityBreakdown(BaseModel):
    """Four-factor priority score breakdown with human-readable reasons (Rules 6 & 7)."""

    total_score: float = Field(ge=0.0, le=100.0)
    discrepancy_points: float = Field(ge=0.0, le=45.0)
    confidence_points: float = Field(ge=0.0, le=25.0)
    evidence_points: float = Field(ge=0.0, le=15.0)
    recurrence_points: float = Field(ge=0.0, le=15.0)
    is_recurrent: bool = False
    prior_discrepancy_count: int = 0
    reasons: list[str] = Field(default_factory=list)


class ReferencePriceRead(BaseModel):
    """Serialized NPPA ceiling-price reference row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ingredient: str
    strength: str
    dosage_form: str
    unit: str
    ceiling_price_per_unit: Decimal
    gst_percent: Decimal
    source_order: str
    effective_from: date
    version: str


class ListingRead(BaseModel):
    """Serialized online pharmacy listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    site: str
    url: str
    product_name: str
    composition_raw: str | None
    pack_size_raw: str | None
    mrp: Decimal | None
    selling_price: Decimal | None
    raw_json: dict[str, Any]
    screenshot_path: str | None
    observed_at: datetime


class MatchRead(BaseModel):
    """Serialized match record attached to a listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    listing_id: int
    reference_id: int | None
    parsed_ingredient: str | None
    parsed_strength: str | None
    parsed_form: str | None
    units_in_pack: int | None
    confidence: float
    status: str
    reasons: list[str]


class ReviewRead(BaseModel):
    """Serialized human review log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    action: str
    note: str | None
    reviewer: str
    created_at: datetime


class ScannedListingItem(BaseModel):
    """Strict output schema validated for every listing returned by ScannerClient or MockScanner."""

    model_config = ConfigDict(extra="forbid")

    site: PermittedSite
    url: str = Field(min_length=8, max_length=1024)
    product_name: str = Field(min_length=2, max_length=500)
    composition_raw: str | None = None
    pack_size_raw: str | None = None
    mrp: Decimal | None = None
    selling_price: Decimal | None = None
    screenshot_path: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("site", mode="before")
    @classmethod
    def _normalize_site(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("site must be a string")
        return value.strip().lower()

    @field_validator("url")
    @classmethod
    def _validate_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError(f"url must start with http:// or https://, got {value!r}")
        return cleaned

    @field_validator("product_name")
    @classmethod
    def _validate_product_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("product_name cannot be blank")
        return cleaned

    @field_validator("mrp", "selling_price", mode="before")
    @classmethod
    def _parse_positive_currency(cls, value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        cleaned = (
            str(value)
            .replace("₹", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .replace("INR", "")
            .replace(",", "")
            .strip()
        )
        if not cleaned:
            return None
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid currency amount: {value!r}") from exc
        if dec <= Decimal("0"):
            raise ValueError(f"Price must be strictly positive (> 0), got {dec}")
        return dec

    @field_validator("observed_at", mode="before")
    @classmethod
    def _parse_utc_timestamp(cls, value: Any) -> datetime:
        if value is None or value == "":
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            iso = value.strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        raise ValueError(f"Invalid timestamp: {value!r}")


class ScanLogRead(BaseModel):
    """Serialized scan_logs record exposing attempts, latency, and errors."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scanner_mode: str
    medicine_family: str
    site: str
    target_url: str | None
    status: ScanLogStatus
    attempt_count: int
    listings_extracted: int
    duration_ms: int | None
    error_type: str | None
    error_message: str | None
    details_json: dict[str, Any]
    created_at: datetime


class ScanRunSummary(BaseModel):
    """Summary metrics returned after executing a scan + compliance pipeline run."""

    scanner_mode: str
    medicine_family: str
    sites_scanned: list[str]
    failed_sites: list[str] = Field(default_factory=list)
    listings_ingested: int
    matched_count: int
    uncertain_count: int
    no_match_count: int
    potential_discrepancies_flagged: int
    needs_verification_flagged: int
    created_case_ids: list[int] = Field(default_factory=list)
    scan_log_ids: list[int] = Field(default_factory=list)
    requested_scanner_mode: str | None = None
    fallback_used: bool = False
    fallback_sites: list[str] = Field(default_factory=list)


class CaseRead(BaseModel):
    """Serialized compliance triage case."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    listing_id: int
    reference_id: int | None
    observed_per_unit: Decimal | None
    selling_per_unit: Decimal | None
    allowed_per_unit: Decimal | None
    discrepancy_percent: Decimal | None
    formula: str | None
    reference_version: str | None
    calculation_reasons: list[str]
    is_recurrent: bool
    priority_score: float
    priority_reasons: list[str]
    status: CaseStatus
    created_at: datetime


class ReferencePriceWithAllowedRead(ReferencePriceRead):
    """ReferencePrice row enriched with pre-computed allowed_per_unit (incl. GST)."""

    allowed_per_unit: Decimal


class ReferenceListResponse(BaseModel):
    """Response envelope for NPPA reference table listing."""

    items: list[ReferencePriceWithAllowedRead]
    has_unverified_sample: bool = False


class ScanTriggerRequest(BaseModel):
    """Request body for triggering an online pharmacy scan."""

    medicine_family: str = Field(default="atorvastatin", min_length=1, max_length=120)
    sites: list[str] | None = None
    scanner_mode: Literal["mock", "tinyfish_rest", "tinyfish_sdk"] | None = None
    use_cached_fallback: bool | None = None


class ListingWithMatchRead(ListingRead):
    """Listing row bundled with its parsed/matched status and raw field audit."""

    match: MatchRead | None = None
    raw_audit: dict[str, RawFieldAudit] = Field(default_factory=dict)
    case_id: int | None = None
    case_status: str | None = None


class CaseListItem(CaseRead):
    """Prioritized triage queue item with nested listing, match, and recurrence group context."""

    listing: ListingRead
    match: MatchRead | None = None
    reference: ReferencePriceRead | None = None
    review_count: int = 0
    recurrence_group_key: str = ""
    recurrence_count: int = 1


class PriorCaseSummary(BaseModel):
    """Summary of an earlier discrepancy case on the same site + product (Rule 7)."""

    case_id: int
    observed_at: datetime
    observed_per_unit: Decimal | None
    discrepancy_percent: Decimal | None
    status: str


class CaseDossierRead(CaseRead):
    """Complete human-reviewer evidence dossier for a single Case."""

    listing: ListingRead
    match: MatchRead | None = None
    reference: ReferencePriceRead | None = None
    raw_audit: dict[str, RawFieldAudit] = Field(default_factory=dict)
    recurrence_group_key: str = ""
    recurrence_count: int = 1
    prior_cases: list[PriorCaseSummary] = Field(default_factory=list)
    reviews: list[ReviewRead] = Field(default_factory=list)


class ReviewCreateRequest(BaseModel):
    """Human reviewer decision payload (confirm, dismiss, or needs_more_evidence)."""

    action: Literal["confirm", "dismiss", "needs_more_evidence"]
    reviewer: str = Field(min_length=1, max_length=150)
    note: str | None = Field(default=None, max_length=2000)


class RecurrenceGroupSummary(BaseModel):
    """Grouped repeat-discrepancy findings for the same site + product."""

    recurrence_group_key: str
    site: str
    product_name: str
    occurrence_count: int
    latest_case_id: int
    max_discrepancy_percent: float | None = None
    case_ids: list[int] = Field(default_factory=list)


class SiteComplianceBreakdown(BaseModel):
    """Per-pharmacy compliance counts for Recharts grouped bar chart."""

    site: str
    total_listings: int
    potential_discrepancies: int
    needs_verification: int
    compliant: int


class StatusCountItem(BaseModel):
    """Workflow status distribution item."""

    status: str
    label: str
    count: int


class TopDiscrepancyChartItem(BaseModel):
    """Per-unit observed vs. allowed ceiling comparison point for Recharts."""

    case_id: int
    site: str
    product_name: str
    strength: str
    observed_per_unit: float
    allowed_per_unit: float
    discrepancy_percent: float


class StatsResponse(BaseModel):
    """Aggregated compliance intelligence KPIs, recurrence groups, and chart series."""

    total_listings: int
    matched_listings: int
    uncertain_listings: int
    no_match_listings: int
    compliant_matched_listings: int
    total_cases: int
    open_potential_discrepancies: int
    needs_verification_count: int
    confirmed_for_review_count: int
    dismissed_count: int
    needs_more_evidence_count: int
    recurrent_cases_count: int
    average_discrepancy_percent: float | None = None
    max_discrepancy_percent: float | None = None
    has_unverified_references: bool
    recurrence_groups: list[RecurrenceGroupSummary] = Field(default_factory=list)
    by_site: list[SiteComplianceBreakdown]
    by_status: list[StatusCountItem]
    top_discrepancies: list[TopDiscrepancyChartItem]
    compliance_notice: str


DashboardSummaryResponse = StatsResponse

