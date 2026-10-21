"""Django models for the attendance schema.

The tables are created by migrations/0001_initial.py with explicit SQL so that
existing databases (created before Django) are adopted unchanged. Event rows are
immutable: the sync only inserts them, never updates or deletes.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class LocalDateTimeField(models.DateTimeField):
    """``timestamp without time zone``: device-local wall-clock time, stored as read.

    Values stay naive; they are not converted with the project's UTC setting.
    """

    def db_type(self, connection):
        return "timestamp"

    def get_prep_value(self, value):
        return models.Field.get_prep_value(self, value)


class AttendanceSource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    source_key = models.TextField()
    display_name = models.TextField(null=True)
    device_serial = models.TextField(null=True)
    device_timezone = models.TextField()
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "attendance_sources"
        constraints = [
            models.UniqueConstraint(
                fields=["source_key"], name="uq_attendance_sources_source_key"
            ),
        ]

    def __str__(self) -> str:
        return self.source_key


class AttendanceSyncRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    source = models.ForeignKey(
        AttendanceSource, models.DO_NOTHING, db_index=False, related_name="sync_runs"
    )
    mode = models.TextField()
    status = models.TextField()
    started_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True)
    received_count = models.IntegerField(db_default=0)
    valid_count = models.IntegerField(db_default=0)
    invalid_count = models.IntegerField(db_default=0)
    inserted_count = models.IntegerField(db_default=0)
    invalid_inserted_count = models.IntegerField(db_default=0)
    duplicate_count = models.IntegerField(db_default=0)
    error_message = models.TextField(null=True)

    class Meta:
        db_table = "attendance_sync_runs"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["running", "succeeded", "failed"]),
                name="ck_attendance_sync_runs_status",
            ),
            models.CheckConstraint(
                condition=Q(mode__in=["initial", "scheduled", "manual"]),
                name="ck_attendance_sync_runs_mode",
            ),
        ]


# The occurred_at_utc indexes (ix_attendance_events_*) exist in the database but
# are not declared here: their names exceed Django's 30-character Index limit.
class AttendanceEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(
        AttendanceSource, models.DO_NOTHING, db_index=False, related_name="events"
    )
    vendor_event_id = models.TextField(null=True)
    employee_id = models.TextField()
    employee_name = models.TextField(null=True)
    original_device_timestamp = LocalDateTimeField()
    occurred_at_utc = models.DateTimeField()
    status_raw = models.TextField(null=True)
    punch_raw = models.TextField(null=True)
    raw_payload = models.JSONField(null=True)
    ingested_at = models.DateTimeField(db_default=Now())
    sync_run = models.ForeignKey(
        AttendanceSyncRun, models.DO_NOTHING, db_index=False, related_name="events"
    )

    class Meta:
        db_table = "attendance_events"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "vendor_event_id"],
                condition=Q(vendor_event_id__isnull=False),
                name="uq_attendance_events_vendor_event",
            ),
            models.UniqueConstraint(
                fields=["source", "employee_id", "original_device_timestamp"],
                condition=Q(vendor_event_id__isnull=True),
                name="uq_attendance_events_fallback",
            ),
        ]


class InvalidAttendanceEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    source = models.ForeignKey(
        AttendanceSource,
        models.DO_NOTHING,
        db_index=False,
        related_name="invalid_events",
    )
    vendor_event_id = models.TextField(null=True)
    employee_id = models.TextField()
    employee_name = models.TextField(null=True)
    original_device_timestamp = LocalDateTimeField()
    status_raw = models.TextField(null=True)
    punch_raw = models.TextField(null=True)
    validation_error = models.TextField()
    raw_payload = models.JSONField(null=True)
    detected_at = models.DateTimeField(db_default=Now())
    sync_run = models.ForeignKey(
        AttendanceSyncRun,
        models.DO_NOTHING,
        db_index=False,
        related_name="invalid_events",
    )

    class Meta:
        db_table = "invalid_attendance_events"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "vendor_event_id"],
                condition=Q(vendor_event_id__isnull=False),
                name="uq_invalid_attendance_vendor_event",
            ),
            models.UniqueConstraint(
                fields=["source", "employee_id", "original_device_timestamp"],
                condition=Q(vendor_event_id__isnull=True),
                name="uq_invalid_attendance_fallback",
            ),
        ]


class Employee(models.Model):
    """Device roster; users missing from a sync snapshot become inactive."""

    pk = models.CompositePrimaryKey("source", "employee_id")
    source = models.ForeignKey(
        AttendanceSource, models.DO_NOTHING, db_index=False, related_name="employees"
    )
    employee_id = models.TextField()
    name = models.TextField(null=True)
    is_active = models.BooleanField(db_default=True)
    first_seen_at = models.DateTimeField(db_default=Now())
    last_seen_at = models.DateTimeField(db_default=Now())
    last_sync_run = models.ForeignKey(
        AttendanceSyncRun, models.DO_NOTHING, db_index=False, related_name="+"
    )

    class Meta:
        db_table = "employees"
