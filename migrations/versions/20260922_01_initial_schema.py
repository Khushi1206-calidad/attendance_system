"""Create immutable attendance ingestion schema.

Revision ID: 20260922_01
Revises: None
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attendance_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("device_serial", sa.Text()),
        sa.Column("device_timezone", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source_key", name="uq_attendance_sources_source_key"),
    )

    op.create_table(
        "attendance_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sources.id"),
            nullable=False,
        ),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "invalid_inserted_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_attendance_sync_runs_status",
        ),
        sa.CheckConstraint(
            "mode IN ('initial', 'scheduled', 'manual')",
            name="ck_attendance_sync_runs_mode",
        ),
    )

    op.create_table(
        "attendance_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sources.id"),
            nullable=False,
        ),
        sa.Column("vendor_event_id", sa.Text()),
        sa.Column("employee_id", sa.Text(), nullable=False),
        sa.Column("employee_name", sa.Text()),
        sa.Column("original_device_timestamp", sa.DateTime(), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_raw", sa.Text()),
        sa.Column("punch_raw", sa.Text()),
        sa.Column("raw_payload", postgresql.JSONB()),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "sync_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sync_runs.id"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_attendance_events_vendor_event",
        "attendance_events",
        ["source_id", "vendor_event_id"],
        unique=True,
        postgresql_where=sa.text("vendor_event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_attendance_events_fallback",
        "attendance_events",
        ["source_id", "employee_id", "original_device_timestamp"],
        unique=True,
        postgresql_where=sa.text("vendor_event_id IS NULL"),
    )
    op.create_index(
        "ix_attendance_events_occurred_at_utc",
        "attendance_events",
        ["occurred_at_utc"],
    )

    op.create_table(
        "invalid_attendance_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sources.id"),
            nullable=False,
        ),
        sa.Column("vendor_event_id", sa.Text()),
        sa.Column("employee_id", sa.Text(), nullable=False),
        sa.Column("employee_name", sa.Text()),
        sa.Column("original_device_timestamp", sa.DateTime(), nullable=False),
        sa.Column("status_raw", sa.Text()),
        sa.Column("punch_raw", sa.Text()),
        sa.Column("validation_error", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB()),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "sync_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sync_runs.id"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_invalid_attendance_vendor_event",
        "invalid_attendance_events",
        ["source_id", "vendor_event_id"],
        unique=True,
        postgresql_where=sa.text("vendor_event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_invalid_attendance_fallback",
        "invalid_attendance_events",
        ["source_id", "employee_id", "original_device_timestamp"],
        unique=True,
        postgresql_where=sa.text("vendor_event_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("invalid_attendance_events")
    op.drop_table("attendance_events")
    op.drop_table("attendance_sync_runs")
    op.drop_table("attendance_sources")

