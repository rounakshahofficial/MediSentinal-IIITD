"""Initial five-table MediSentinel schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-23 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ingredient", sa.String(length=255), nullable=False),
        sa.Column("strength", sa.String(length=100), nullable=False),
        sa.Column("dosage_form", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("ceiling_price_per_unit", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("gst_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("source_order", sa.String(length=255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingredient",
            "strength",
            "dosage_form",
            "version",
            name="uq_reference_prices_formulation_version",
        ),
    )
    op.create_index("ix_reference_prices_ingredient", "reference_prices", ["ingredient"])
    op.create_index("ix_reference_prices_strength", "reference_prices", ["strength"])
    op.create_index("ix_reference_prices_dosage_form", "reference_prices", ["dosage_form"])

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("product_name", sa.String(length=500), nullable=False),
        sa.Column("composition_raw", sa.Text(), nullable=True),
        sa.Column("pack_size_raw", sa.String(length=255), nullable=True),
        sa.Column("mrp", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_listings_site", "listings", ["site"])
    op.create_index("ix_listings_product_name", "listings", ["product_name"])
    op.create_index("ix_listings_observed_at", "listings", ["observed_at"])

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("parsed_ingredient", sa.String(length=255), nullable=True),
        sa.Column("parsed_strength", sa.String(length=100), nullable=True),
        sa.Column("parsed_form", sa.String(length=100), nullable=True),
        sa.Column("units_in_pack", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('matched', 'uncertain', 'no_match')",
            name="ck_matches_status",
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_id"], ["reference_prices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_listing_id", "matches", ["listing_id"], unique=True)
    op.create_index("ix_matches_reference_id", "matches", ["reference_id"])
    op.create_index("ix_matches_status", "matches", ["status"])

    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("observed_per_unit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("selling_per_unit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("allowed_per_unit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("discrepancy_percent", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("reference_version", sa.String(length=100), nullable=True),
        sa.Column("calculation_reasons", sa.JSON(), nullable=False),
        sa.Column("is_recurrent", sa.Boolean(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("priority_reasons", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('potential_discrepancy', 'needs_verification', "
            "'confirmed_for_review', 'dismissed', 'needs_more_evidence')",
            name="ck_cases_status",
        ),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_id"], ["reference_prices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_listing_id", "cases", ["listing_id"], unique=True)
    op.create_index("ix_cases_reference_id", "cases", ["reference_id"])
    op.create_index("ix_cases_priority_score", "cases", ["priority_score"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_created_at", "cases", ["created_at"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_case_id", "reviews", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_reviews_case_id", table_name="reviews")
    op.drop_table("reviews")

    op.drop_index("ix_cases_created_at", table_name="cases")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_priority_score", table_name="cases")
    op.drop_index("ix_cases_reference_id", table_name="cases")
    op.drop_index("ix_cases_listing_id", table_name="cases")
    op.drop_table("cases")

    op.drop_index("ix_matches_status", table_name="matches")
    op.drop_index("ix_matches_reference_id", table_name="matches")
    op.drop_index("ix_matches_listing_id", table_name="matches")
    op.drop_table("matches")

    op.drop_index("ix_listings_observed_at", table_name="listings")
    op.drop_index("ix_listings_product_name", table_name="listings")
    op.drop_index("ix_listings_site", table_name="listings")
    op.drop_table("listings")

    op.drop_index("ix_reference_prices_dosage_form", table_name="reference_prices")
    op.drop_index("ix_reference_prices_strength", table_name="reference_prices")
    op.drop_index("ix_reference_prices_ingredient", table_name="reference_prices")
    op.drop_table("reference_prices")
