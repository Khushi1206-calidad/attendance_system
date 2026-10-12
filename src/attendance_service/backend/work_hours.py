"""Business calculation for total first-to-last attendance span."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from attendance_service.database.read_models import (
    AttendancePunch,
    AttendanceSpan,
    CalculationWarning,
    Employee,
)
from attendance_service.database.read_repository import ReadOnlyAttendanceRepository

CALCULATION_METHOD = "first_last_span"
DISPLAY_LABEL = "Total attendance span (breaks included)"


class EmployeeNotFoundError(LookupError):
    pass


def local_day_bounds_utc(
    selected_date: date, timezone: ZoneInfo, cutoff: time = time.min
) -> tuple[datetime, datetime]:
    """Return the UTC bounds of working day D: [D at cutoff, D+1 at cutoff).

    Both ends are built from local wall-clock time, so daylight-saving days
    yield 23- or 25-hour windows. A ``00:00`` cutoff is the calendar day.
    """
    start_local = datetime.combine(selected_date, cutoff, tzinfo=timezone)
    end_local = datetime.combine(
        selected_date + timedelta(days=1), cutoff, tzinfo=timezone
    )
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def working_day_for(
    instant: datetime, timezone: ZoneInfo, cutoff: time = time.min
) -> date:
    """Return the working day containing an aware instant."""
    local = instant.astimezone(timezone)
    if local.time() < cutoff:
        return local.date() - timedelta(days=1)
    return local.date()


class WorkHoursService:
    def __init__(
        self,
        repository: ReadOnlyAttendanceRepository,
        *,
        source_key: str,
        device_timezone: ZoneInfo,
        unreasonable_span_seconds: int,
        working_day_cutoff: time = time.min,
    ) -> None:
        self._repository = repository
        self._source_key = source_key
        self._timezone = device_timezone
        self._unreasonable_span_seconds = unreasonable_span_seconds
        self._cutoff = working_day_cutoff

    def search_employees(self, query: str, *, limit: int = 20) -> list[Employee]:
        return self._repository.search_employees(
            source_key=self._source_key, query=query, limit=limit
        )

    def calculate(self, employee_id: str, selected_date: date) -> AttendanceSpan:
        """Calculate the first-to-last span within one working-day window."""
        employee = self._repository.get_employee(
            source_key=self._source_key, employee_id=employee_id
        )
        if employee is None:
            raise EmployeeNotFoundError(employee_id)

        start_utc, end_utc = local_day_bounds_utc(
            selected_date, self._timezone, self._cutoff
        )
        punches = tuple(
            self._repository.get_punches(
                source_key=self._source_key,
                employee_id=employee_id,
                start_utc=start_utc,
                end_utc=end_utc,
            )
        )
        return calculate_first_last_span(
            employee=employee,
            source_key=self._source_key,
            selected_date=selected_date,
            timezone_name=self._timezone.key,
            punches=punches,
            unreasonable_span_seconds=self._unreasonable_span_seconds,
            window_start=start_utc,
            window_end=end_utc,
        )


def calculate_first_last_span(
    *,
    employee: Employee,
    source_key: str,
    selected_date: date,
    timezone_name: str,
    punches: tuple[AttendancePunch, ...],
    unreasonable_span_seconds: int,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> AttendanceSpan:
    """Last punch minus first punch; the window only labels the result."""
    ordered = tuple(sorted(punches, key=lambda punch: punch.occurred_at_utc))
    warnings: list[CalculationWarning] = []
    first: datetime | None = None
    last: datetime | None = None
    duration: int | None = None

    if not ordered:
        warnings.append(
            CalculationWarning("no_attendance", "No attendance was recorded.")
        )
    elif len(ordered) == 1:
        first = last = ordered[0].occurred_at_utc
        warnings.append(
            CalculationWarning(
                "insufficient_punches",
                "At least two punches are required to calculate attendance span.",
            )
        )
    else:
        first = ordered[0].occurred_at_utc
        last = ordered[-1].occurred_at_utc
        duration = int((last - first).total_seconds())
        if len(ordered) % 2 == 1:
            warnings.append(
                CalculationWarning(
                    "odd_punch_count",
                    "An odd number of punches was recorded; the first-to-last span "
                    "is still shown.",
                )
            )
        if duration > unreasonable_span_seconds:
            warnings.append(
                CalculationWarning(
                    "unreasonable_span",
                    "The attendance span exceeds the configured warning threshold.",
                )
            )

    return AttendanceSpan(
        employee=employee,
        source_key=source_key,
        selected_date=selected_date,
        timezone_name=timezone_name,
        punches=ordered,
        first_punch=first,
        last_punch=last,
        duration_seconds=duration,
        warnings=tuple(warnings),
        window_start=window_start,
        window_end=window_end,
    )

