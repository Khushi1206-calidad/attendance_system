"""Daily present / not-in classification against the device roster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from attendance_service.backend.work_hours import local_day_bounds_utc
from attendance_service.database.read_models import (
    CalculationWarning,
    DailyPresenceRow,
)
from attendance_service.database.read_repository import ReadOnlyAttendanceRepository


class FutureDateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DailyAttendanceReport:
    source_key: str
    selected_date: date
    timezone_name: str
    absence_label: str
    roster_count: int
    present: tuple[DailyPresenceRow, ...]
    not_in: tuple[DailyPresenceRow, ...]
    data_as_of: datetime | None
    warnings: tuple[CalculationWarning, ...]


def classify_daily_presence(
    rows: list[DailyPresenceRow], *, selected_date: date, today_local: date
) -> tuple[
    tuple[DailyPresenceRow, ...],
    tuple[DailyPresenceRow, ...],
    str,
    tuple[CalculationWarning, ...],
]:
    present = tuple(
        sorted(
            (row for row in rows if row.punch_count > 0),
            key=lambda row: row.first_punch_utc,
        )
    )
    not_in = tuple(
        sorted(
            (row for row in rows if row.punch_count == 0 and row.in_roster),
            key=lambda row: ((row.name or "").casefold(), row.employee_id),
        )
    )
    warnings: list[CalculationWarning] = []
    if not any(row.in_roster for row in rows):
        warnings.append(
            CalculationWarning(
                "roster_empty",
                "No employee roster has been synchronized from the device yet.",
            )
        )
    elif any(not row.in_roster for row in present):
        warnings.append(
            CalculationWarning(
                "unregistered_employees",
                "Some punches belong to employees not in the device roster.",
            )
        )
    label = "not_in_yet" if selected_date == today_local else "absent"
    return present, not_in, label, tuple(warnings)


class DailyAttendanceService:
    def __init__(
        self,
        repository: ReadOnlyAttendanceRepository,
        *,
        source_key: str,
        device_timezone: ZoneInfo,
    ) -> None:
        self._repository = repository
        self._source_key = source_key
        self._timezone = device_timezone

    def today(self, now_utc: datetime | None = None) -> date:
        return (now_utc or datetime.now(UTC)).astimezone(self._timezone).date()

    def build(
        self, selected_date: date, *, now_utc: datetime | None = None
    ) -> DailyAttendanceReport:
        today_local = self.today(now_utc)
        if selected_date > today_local:
            raise FutureDateError(selected_date)
        start_utc, end_utc = local_day_bounds_utc(selected_date, self._timezone)
        rows = self._repository.get_daily_presence(
            source_key=self._source_key, start_utc=start_utc, end_utc=end_utc
        )
        present, not_in, label, warnings = classify_daily_presence(
            rows, selected_date=selected_date, today_local=today_local
        )
        return DailyAttendanceReport(
            source_key=self._source_key,
            selected_date=selected_date,
            timezone_name=self._timezone.key,
            absence_label=label,
            roster_count=sum(1 for row in rows if row.in_roster),
            present=present,
            not_in=not_in,
            data_as_of=self._repository.get_last_successful_sync(
                source_key=self._source_key
            ),
            warnings=warnings,
        )
