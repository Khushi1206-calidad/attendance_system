"""Business calculation for total first-to-last attendance span."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from attendance_service.read_models import (
    AttendancePunch,
    AttendanceSpan,
    CalculationWarning,
    Employee,
)
from attendance_service.read_repository import ReadOnlyAttendanceRepository

CALCULATION_METHOD = "first_last_span"
DISPLAY_LABEL = "Total attendance span (breaks included)"


class EmployeeNotFoundError(LookupError):
    pass


class WorkHoursService:
    def __init__(
        self,
        repository: ReadOnlyAttendanceRepository,
        *,
        source_key: str,
        device_timezone: ZoneInfo,
        unreasonable_span_seconds: int,
    ) -> None:
        self._repository = repository
        self._source_key = source_key
        self._timezone = device_timezone
        self._unreasonable_span_seconds = unreasonable_span_seconds

    def search_employees(self, query: str, *, limit: int = 20) -> list[Employee]:
        return self._repository.search_employees(
            source_key=self._source_key, query=query, limit=limit
        )

    def calculate(self, employee_id: str, selected_date: date) -> AttendanceSpan:
        employee = self._repository.get_employee(
            source_key=self._source_key, employee_id=employee_id
        )
        if employee is None:
            raise EmployeeNotFoundError(employee_id)

        start_local = datetime.combine(
            selected_date, time.min, tzinfo=self._timezone
        )
        end_local = datetime.combine(
            selected_date + timedelta(days=1), time.min, tzinfo=self._timezone
        )
        punches = tuple(
            self._repository.get_punches(
                source_key=self._source_key,
                employee_id=employee_id,
                start_utc=start_local.astimezone(UTC),
                end_utc=end_local.astimezone(UTC),
            )
        )
        return calculate_first_last_span(
            employee=employee,
            source_key=self._source_key,
            selected_date=selected_date,
            timezone_name=self._timezone.key,
            punches=punches,
            unreasonable_span_seconds=self._unreasonable_span_seconds,
        )


def calculate_first_last_span(
    *,
    employee: Employee,
    source_key: str,
    selected_date: date,
    timezone_name: str,
    punches: tuple[AttendancePunch, ...],
    unreasonable_span_seconds: int,
) -> AttendanceSpan:
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
    )

