"""PostgreSQL persistence, advisory locking, and synchronization auditing.

Uses Django's read-write ``default`` connection. Inserts that must report how
many rows were new (``ON CONFLICT DO NOTHING`` counts) use SQL on that
connection; everything else uses the ORM.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from django.db import connection as default_connection
from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Max
from django.db.models.functions import Now
from psycopg.types.json import Jsonb

from attendance.services.domain import (
    DeviceUser,
    EmployeeSyncCounts,
    InvalidAttendanceEvent,
    ValidAttendanceEvent,
)
from attendance.models import (
    AttendanceEvent,
    AttendanceSource,
    AttendanceSyncRun,
    InvalidAttendanceEvent as InvalidAttendanceEventRow,
)


class AttendanceRepository:
    def __init__(self, connection: BaseDatabaseWrapper | None = None) -> None:
        self.connection = connection or default_connection
        self._using = self.connection.alias
        self._locked_source_key: str | None = None

    def close(self) -> None:
        self.connection.close()

    def ensure_source(
        self, *, source_key: str, display_name: str | None, timezone_name: str
    ) -> UUID:
        source, _ = AttendanceSource.objects.using(self._using).get_or_create(
            source_key=source_key,
            defaults={
                "id": uuid4(),
                "display_name": display_name,
                "device_timezone": timezone_name,
            },
        )
        if source.device_timezone != timezone_name:
            raise ValueError(
                "Configured device timezone does not match the existing "
                f"source timezone ({source.device_timezone})"
            )
        return source.id

    def set_device_serial_if_missing(self, source_id: UUID, serial: str | None) -> None:
        if not serial:
            return
        sources = AttendanceSource.objects.using(self._using)
        with transaction.atomic(using=self._using):
            stored = sources.filter(id=source_id).values_list("device_serial", flat=True)
            if not stored:
                raise RuntimeError("Attendance source disappeared during sync")
            if stored[0] is not None and stored[0] != serial:
                raise ValueError(
                    "Connected device serial does not match the serial already "
                    "registered for this source"
                )
            sources.filter(id=source_id, device_serial__isnull=True).update(
                device_serial=serial, updated_at=Now()
            )

    def try_source_lock(self, source_key: str) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (f"attendance-service:{source_key}",),
            )
            acquired = bool(cursor.fetchone()[0])
        if acquired:
            self._locked_source_key = source_key
        return acquired

    def release_source_lock(self) -> None:
        if self._locked_source_key is None or self.connection.connection is None:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (f"attendance-service:{self._locked_source_key}",),
            )
        self._locked_source_key = None

    def atomic(self) -> AbstractContextManager[Any]:
        """One transaction; nested repository writes become savepoints."""
        return transaction.atomic(using=self._using)

    def latest_valid_device_timestamp(self, source_id: UUID) -> datetime | None:
        """Newest stored valid punch (device-local, naive), or None if empty."""
        return (
            AttendanceEvent.objects.using(self._using)
            .filter(source_id=source_id)
            .aggregate(latest=Max("original_device_timestamp"))["latest"]
        )

    def source_has_records(self, source_id: UUID) -> bool:
        return (
            AttendanceEvent.objects.using(self._using).filter(source_id=source_id).exists()
            or InvalidAttendanceEventRow.objects.using(self._using)
            .filter(source_id=source_id)
            .exists()
        )

    def start_sync_run(self, source_id: UUID, mode: str) -> UUID:
        run = AttendanceSyncRun.objects.using(self._using).create(
            id=uuid4(), source_id=source_id, mode=mode, status="running"
        )
        return run.id

    def finish_sync_run(
        self,
        run_id: UUID,
        *,
        status: str,
        received_count: int = 0,
        valid_count: int = 0,
        invalid_count: int = 0,
        inserted_count: int = 0,
        invalid_inserted_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        duplicate_count = received_count - inserted_count - invalid_inserted_count
        AttendanceSyncRun.objects.using(self._using).filter(id=run_id).update(
            status=status,
            finished_at=Now(),
            received_count=received_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            inserted_count=inserted_count,
            invalid_inserted_count=invalid_inserted_count,
            duplicate_count=max(duplicate_count, 0),
            error_message=error_message,
        )

    def sync_employees(
        self,
        source_id: UUID,
        run_id: UUID,
        users: Iterable[DeviceUser],
    ) -> EmployeeSyncCounts:
        unique = {user.employee_id: user for user in users}
        if not unique:
            # An empty device read must never wipe the roster.
            return EmployeeSyncCounts(upserted=0, deactivated=0)
        rows = [
            (source_id, user.employee_id, user.name, run_id)
            for user in unique.values()
        ]
        with transaction.atomic(using=self._using), self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO employees (
                    source_id, employee_id, name, last_sync_run_id
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_id, employee_id) DO UPDATE
                SET name = EXCLUDED.name,
                    is_active = true,
                    last_seen_at = now(),
                    last_sync_run_id = EXCLUDED.last_sync_run_id
                """,
                rows,
            )
            cursor.execute(
                """
                UPDATE employees
                SET is_active = false
                WHERE source_id = %s
                  AND is_active
                  AND NOT (employee_id = ANY(%s))
                """,
                (source_id, list(unique)),
            )
            deactivated = cursor.rowcount
        return EmployeeSyncCounts(upserted=len(rows), deactivated=deactivated)

    def insert_valid_events(
        self,
        source_id: UUID,
        run_id: UUID,
        events: Iterable[ValidAttendanceEvent],
    ) -> int:
        rows = [
            (
                source_id,
                event.punch.vendor_event_id,
                event.punch.employee_id,
                event.punch.employee_name,
                event.punch.original_device_timestamp,
                event.occurred_at_utc,
                event.punch.status_raw,
                event.punch.punch_raw,
                Jsonb(event.punch.raw_payload),
                run_id,
            )
            for event in events
        ]
        if not rows:
            return 0
        with transaction.atomic(using=self._using), self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO attendance_events (
                    source_id,
                    vendor_event_id,
                    employee_id,
                    employee_name,
                    original_device_timestamp,
                    occurred_at_utc,
                    status_raw,
                    punch_raw,
                    raw_payload,
                    sync_run_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
            return cursor.rowcount

    def insert_invalid_events(
        self,
        source_id: UUID,
        run_id: UUID,
        events: Iterable[InvalidAttendanceEvent],
    ) -> int:
        rows = [
            (
                source_id,
                event.punch.vendor_event_id,
                event.punch.employee_id,
                event.punch.employee_name,
                event.punch.original_device_timestamp,
                event.punch.status_raw,
                event.punch.punch_raw,
                event.validation_error,
                Jsonb(event.punch.raw_payload),
                run_id,
            )
            for event in events
        ]
        if not rows:
            return 0
        with transaction.atomic(using=self._using), self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO invalid_attendance_events (
                    source_id,
                    vendor_event_id,
                    employee_id,
                    employee_name,
                    original_device_timestamp,
                    status_raw,
                    punch_raw,
                    validation_error,
                    raw_payload,
                    sync_run_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
            return cursor.rowcount

    def fetch_report_events(self, source_key: str) -> list[tuple[Any, ...]]:
        return list(
            AttendanceEvent.objects.using(self._using)
            .filter(source__source_key=source_key)
            .order_by("original_device_timestamp", "id")
            .values_list(
                "employee_id",
                "employee_name",
                "original_device_timestamp",
                "status_raw",
                "punch_raw",
            )
        )

    def fetch_invalid_report_events(self, source_key: str) -> list[tuple[Any, ...]]:
        return list(
            InvalidAttendanceEventRow.objects.using(self._using)
            .filter(source__source_key=source_key)
            .order_by("original_device_timestamp", "id")
            .values_list(
                "employee_id",
                "employee_name",
                "original_device_timestamp",
                "status_raw",
                "punch_raw",
                "validation_error",
            )
        )

    def latest_successful_sync(self, source_id: UUID) -> datetime | None:
        finished = (
            AttendanceSyncRun.objects.using(self._using)
            .filter(source_id=source_id, status="succeeded")
            .aggregate(latest=Max("finished_at"))["latest"]
        )
        return finished.astimezone(UTC) if finished else None
