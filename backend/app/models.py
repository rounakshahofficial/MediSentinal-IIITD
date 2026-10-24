"""SQLAlchemy 2.x ORM models for MediSentinel's five core compliance tables."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MatchStatus(StrEnum):
    """Allowed outcomes for matching a pharmacy listing to an NPPA reference."""

    MATCHED = "matched"
    UNCERTAIN = "uncertain"
    NO_MATCH = "no_match"


class CaseStatus(StrEnum):
    """Workflow states for advisory compliance triage requiring human review."""

    POTENTIAL_DISCREPANCY = "potential_discrepancy"
    NEEDS_VERIFICATION = "needs_verification"
    CONFIRMED_FOR_REVIEW = "confirmed_for_review"
    DISMISSED = "dismissed"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class ReferencePrice(Base):
    """NPPA ceiling-price reference row for a scheduled formulation."""

    __tablename__ = "reference_prices"
    __table_args__ = (
        UniqueConstraint(
            "ingredient",
            "strength",
            "dosage_form",
            "version",
            name="uq_reference_prices_formulation_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ingredient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    strength: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    dosage_form: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    ceiling_price_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    source_order: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)

    matches: Mapped[list[Match]] = relationship(back_populates="reference")
    cases: Mapped[list[Case]] = relationship(back_populates="reference")


class Listing(Base):
    """Observed online pharmacy product listing with raw text preserved for audit."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    composition_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    pack_size_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )

    match: Mapped[Match | None] = relationship(
        back_populates="listing", uselist=False, cascade="all, delete-orphan"
    )
    case: Mapped[Case | None] = relationship(
        back_populates="listing", uselist=False, cascade="all, delete-orphan"
    )


class Match(Base):
    """Parsed formulation fields and deterministic match result for a listing."""

    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('matched', 'uncertain', 'no_match')",
            name="ck_matches_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_prices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parsed_ingredient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parsed_strength: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parsed_form: Mapped[str | None] = mapped_column(String(100), nullable=True)
    units_in_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    listing: Mapped[Listing] = relationship(back_populates="match")
    reference: Mapped[ReferencePrice | None] = relationship(back_populates="matches")


class Case(Base):
    """Compliance triage dossier linking a listing, reference math, and priority."""

    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('potential_discrepancy', 'needs_verification', "
            "'confirmed_for_review', 'dismissed', 'needs_more_evidence')",
            name="ck_cases_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_prices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    observed_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    selling_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    allowed_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    discrepancy_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    calculation_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_recurrent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    priority_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )

    listing: Mapped[Listing] = relationship(back_populates="case")
    reference: Mapped[ReferencePrice | None] = relationship(back_populates="cases")
    reviews: Mapped[list[Review]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Review.created_at.desc()",
    )


class Review(Base):
    """Human-in-the-loop review log entry recorded against a Case."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    case: Mapped[Case] = relationship(back_populates="reviews")


class ScanLogStatus(StrEnum):
    """Execution outcome states recorded in scan_logs."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ScanLog(Base):
    """Audit and failure telemetry log for each per-site scanner execution."""

    __tablename__ = "scan_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'partial', 'failed')",
            name="ck_scan_logs_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scanner_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    medicine_family: Mapped[str] = mapped_column(String(150), nullable=False)
    site: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    listings_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )

