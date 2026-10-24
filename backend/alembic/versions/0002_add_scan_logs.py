"""Add scan_logs table for scanner retries, timeouts, and failure logging.

Revision ID: 0002_add_scan_logs
Revises: 0001_initial_schema
Create Date: 2026-10-23 01:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_scan_logs"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scanner_mode", sa.String(length=40), nullable=False),
        sa.Column("medicine_family", sa.String(length=150), nullable=False),
        sa.Column("site", sa.String(length=100), nullable=False),
        sa.Column("target_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("listings_extracted", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'partial', 'failed')",
            name="ck_scan_logs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_logs_site", "scan_logs", ["site"])
    op.create_index("ix_scan_logs_status", "scan_logs", ["status"])
    op.create_index("ix_scan_logs_created_at", "scan_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_scan_logs_created_at", table_name="scan_logs")
    op.drop_index("ix_scan_logs_status", table_name="scan_logs")
    op.drop_index("ix_scan_logs_site", table_name="scan_logs")
    op.drop_table("scan_logs")
