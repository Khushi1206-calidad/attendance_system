"""Add device employee roster and daily presence index.

Revision ID: 20260924_01
Revises: 20260922_01
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260924_01"
down_revision: str | None = "20260922_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sources.id"),
            nullable=False,
        ),
        sa.Column("employee_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_sync_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attendance_sync_runs.id"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_id", "employee_id", name="pk_employees"),
    )
    op.create_index(
        "ix_attendance_events_source_occurred",
        "attendance_events",
        ["source_id", "occurred_at_utc"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_attendance_events_source_occurred", table_name="attendance_events"
    )
    op.drop_table("employees")
