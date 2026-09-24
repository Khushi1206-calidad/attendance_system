"""PostgreSQL persistence, advisory locking, and synchronization auditing."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from attendance_service.backend.domain import InvalidAttendanceEvent, ValidAttendanceEvent


class AttendanceRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection
        self.connection.autocommit = True
        self._locked_source_key: str | None = None

    @classmethod
    def connect(cls, database_url: str) -> "AttendanceRepository":
        return cls(psycopg.connect(database_url))

    def close(self) -> None:
        self.connection.close()

    def ensure_source(
        self, *, source_key: str, display_name: str | None, timezone_name: str
    ) -> UUID:
        candidate_id = uuid4()
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_sources (
                    id, source_key, display_name, device_timezone
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_key) DO NOTHING
                """,
                (candidate_id, source_key, display_name, timezone_name),
            )
            cursor.execute(
                """
                SELECT id, device_timezone
                FROM attendance_sources
                WHERE source_key = %s
                """,
                (source_key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Could not create or retrieve attendance source")
            if row[1] != timezone_name:
                raise ValueError(
                    "Configured device timezone does not match the existing "
                    f"source timezone ({row[1]})"
                )
            return row[0]

    def set_device_serial_if_missing(self, source_id: UUID, serial: str | None) -> None:
        if not serial:
            return
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT device_serial FROM attendance_sources WHERE id = %s",
                (source_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Attendance source disappeared during sync")
            if row[0] is not None and row[0] != serial:
                raise ValueError(
                    "Connected device serial does not match the serial already "
                    "registered for this source"
                )
            cursor.execute(
                """
                UPDATE attendance_sources
                SET device_serial = %s, updated_at = now()
                WHERE id = %s AND device_serial IS NULL
                """,
                (serial, source_id),
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
        if self._locked_source_key is None or self.connection.closed:
            return
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (f"attendance-service:{self._locked_source_key}",),
            )
        self._locked_source_key = None

    def source_has_records(self, source_id: UUID) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM attendance_events WHERE source_id = %s
                    UNION ALL
                    SELECT 1 FROM invalid_attendance_events WHERE source_id = %s
                )
                """,
                (source_id, source_id),
            )
            return bool(cursor.fetchone()[0])

    def start_sync_run(self, source_id: UUID, mode: str) -> UUID:
        run_id = uuid4()
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_sync_runs (id, source_id, mode, status)
                VALUES (%s, %s, %s, 'running')
                """,
                (run_id, source_id, mode),
            )
        return run_id

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
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE attendance_sync_runs
                SET status = %s,
                    finished_at = now(),
                    received_count = %s,
                    valid_count = %s,
                    invalid_count = %s,
                    inserted_count = %s,
                    invalid_inserted_count = %s,
                    duplicate_count = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    status,
                    received_count,
                    valid_count,
                    invalid_count,
                    inserted_count,
                    invalid_inserted_count,
                    max(duplicate_count, 0),
                    error_message,
                    run_id,
                ),
            )

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
        with self.connection.transaction(), self.connection.cursor() as cursor:
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
        with self.connection.transaction(), self.connection.cursor() as cursor:
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
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.employee_id,
                       e.employee_name,
                       e.original_device_timestamp,
                       e.status_raw,
                       e.punch_raw
                FROM attendance_events e
                JOIN attendance_sources s ON s.id = e.source_id
                WHERE s.source_key = %s
                ORDER BY e.original_device_timestamp, e.id
                """,
                (source_key,),
            )
            return cursor.fetchall()

    def fetch_invalid_report_events(self, source_key: str) -> list[tuple[Any, ...]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.employee_id,
                       e.employee_name,
                       e.original_device_timestamp,
                       e.status_raw,
                       e.punch_raw,
                       e.validation_error
                FROM invalid_attendance_events e
                JOIN attendance_sources s ON s.id = e.source_id
                WHERE s.source_key = %s
                ORDER BY e.original_device_timestamp, e.id
                """,
                (source_key,),
            )
            return cursor.fetchall()

    def latest_successful_sync(self, source_id: UUID) -> datetime | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT finished_at
                FROM attendance_sync_runs
                WHERE source_id = %s AND status = 'succeeded'
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (source_id,),
            )
            row = cursor.fetchone()
            return row[0].astimezone(UTC) if row else None
