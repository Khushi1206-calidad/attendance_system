"""Read-only attendance query values shared by repository and calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Employee:
    employee_id: str
    name: str | None


@dataclass(frozen=True, slots=True)
class AttendancePunch:
    original_device_timestamp: datetime
    occurred_at_utc: datetime
    status_raw: str | None
    punch_raw: str | None


@dataclass(frozen=True, slots=True)
class DailyPresenceRow:
    employee_id: str
    name: str | None
    in_roster: bool
    first_punch_utc: datetime | None
    last_punch_utc: datetime | None
    punch_count: int


@dataclass(frozen=True, slots=True)
class CalculationWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class AttendanceSpan:
    employee: Employee
    source_key: str
    selected_date: date
    timezone_name: str
    punches: tuple[AttendancePunch, ...]
    first_punch: datetime | None
    last_punch: datetime | None
    duration_seconds: int | None
    warnings: tuple[CalculationWarning, ...]

