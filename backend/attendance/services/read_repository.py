"""Parameterized, read-only PostgreSQL attendance queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection

from attendance.services.read_models import (
    AttendancePunch,
    DailyPresenceRow,
    Employee,
)


def _literal_ilike_pattern(value: str) -> str:
    """Escape LIKE metacharacters so the user input is a literal substring."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace(
        "_", "\\_"
    ) + "%"


class ReadOnlyAttendanceRepository:
    """Queries attendance without exposing any mutation operation."""

    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def search_employees(
        self, *, source_key: str, query: str, limit: int = 20
    ) -> list[Employee]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT latest.employee_id, latest.employee_name
                FROM (
                    SELECT DISTINCT ON (e.employee_id)
                           e.employee_id,
                           e.employee_name
                    FROM attendance_events e
                    JOIN attendance_sources s ON s.id = e.source_id
                    WHERE s.source_key = %s
                    ORDER BY e.employee_id, e.occurred_at_utc DESC, e.id DESC
                ) AS latest
                WHERE latest.employee_name ILIKE %s ESCAPE '\\'
                ORDER BY lower(latest.employee_name), latest.employee_id
                LIMIT %s
                """,
                (source_key, _literal_ilike_pattern(query), limit),
            )
            return [Employee(str(row[0]), row[1]) for row in cursor.fetchall()]

    def get_employee(self, *, source_key: str, employee_id: str) -> Employee | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.employee_id, e.employee_name
                FROM attendance_events e
                JOIN attendance_sources s ON s.id = e.source_id
                WHERE s.source_key = %s AND e.employee_id = %s
                ORDER BY e.occurred_at_utc DESC, e.id DESC
                LIMIT 1
                """,
                (source_key, employee_id),
            )
            row = cursor.fetchone()
            return Employee(str(row[0]), row[1]) if row else None

    def get_daily_presence(
        self, *, source_key: str, start_utc: datetime, end_utc: datetime
    ) -> list[DailyPresenceRow]:
        """Active roster members plus anyone who punched in the window."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH source AS (
                    SELECT id FROM attendance_sources WHERE source_key = %s
                ),
                day_punches AS (
                    SELECT e.employee_id,
                           min(e.occurred_at_utc) AS first_punch,
                           max(e.occurred_at_utc) AS last_punch,
                           count(*) AS punch_count,
                           (array_agg(e.employee_name ORDER BY e.occurred_at_utc DESC))[1]
                               AS punch_name
                    FROM attendance_events e
                    JOIN source s ON s.id = e.source_id
                    WHERE e.occurred_at_utc >= %s AND e.occurred_at_utc < %s
                    GROUP BY e.employee_id
                ),
                roster AS (
                    SELECT emp.employee_id, emp.name
                    FROM employees emp
                    JOIN source s ON s.id = emp.source_id
                    WHERE emp.is_active
                )
                SELECT coalesce(r.employee_id, p.employee_id),
                       coalesce(r.name, p.punch_name),
                       r.employee_id IS NOT NULL,
                       p.first_punch,
                       p.last_punch,
                       coalesce(p.punch_count, 0)
                FROM roster r
                FULL OUTER JOIN day_punches p ON p.employee_id = r.employee_id
                """,
                (source_key, start_utc, end_utc),
            )
            return [
                DailyPresenceRow(
                    employee_id=str(row[0]),
                    name=row[1],
                    in_roster=bool(row[2]),
                    first_punch_utc=row[3],
                    last_punch_utc=row[4],
                    punch_count=int(row[5]),
                )
                for row in cursor.fetchall()
            ]

    def get_last_successful_sync(self, *, source_key: str) -> datetime | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT max(r.finished_at)
                FROM attendance_sync_runs r
                JOIN attendance_sources s ON s.id = r.source_id
                WHERE s.source_key = %s AND r.status = 'succeeded'
                """,
                (source_key,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_punches(
        self,
        *,
        source_key: str,
        employee_id: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[AttendancePunch]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.original_device_timestamp,
                       e.occurred_at_utc,
                       e.status_raw,
                       e.punch_raw
                FROM attendance_events e
                JOIN attendance_sources s ON s.id = e.source_id
                WHERE s.source_key = %s
                  AND e.employee_id = %s
                  AND e.occurred_at_utc >= %s
                  AND e.occurred_at_utc < %s
                ORDER BY e.occurred_at_utc, e.id
                """,
                (source_key, employee_id, start_utc, end_utc),
            )
            return [
                AttendancePunch(
                    original_device_timestamp=row[0],
                    occurred_at_utc=row[1],
                    status_raw=row[2],
                    punch_raw=row[3],
                )
                for row in cursor.fetchall()
            ]

