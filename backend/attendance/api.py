"""Read-only attendance REST API (Django Ninja).

The paths, JSON bodies, and error format are the public contract used by the
Next.js frontend; change them only together with frontend/lib/types.ts.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pydantic_core
from django.db import Error as DjangoDatabaseError
from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI, Path, Query, Status
from ninja.errors import ValidationError
from ninja.renderers import BaseRenderer

from attendance.schemas import (
    DailyAttendanceResponse,
    DailyTotals,
    EmployeeResponse,
    EmployeeSearchResponse,
    ErrorDetail,
    ErrorResponse,
    PresentEmployeeResponse,
    PunchResponse,
    WarningResponse,
    WorkHoursResponse,
)
from attendance.services.daily_report import (
    DailyAttendanceService,
    FutureDateError,
)
from attendance.services.work_hours import (
    CALCULATION_METHOD,
    DISPLAY_LABEL,
    EmployeeNotFoundError,
    WorkHoursService,
)
from attendance import dependencies

LOGGER = logging.getLogger(__name__)


class PydanticJSONRenderer(BaseRenderer):
    """Serialize with pydantic's JSON rules (full ISO-8601 datetimes, ``Z`` for UTC)."""

    media_type = "application/json"

    def render(self, request: HttpRequest, data: Any, *, response_status: int) -> bytes:
        return pydantic_core.to_json(data)


api = NinjaAPI(
    title="Attendance API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    renderer=PydanticJSONRenderer(),
)


def _error(code: str, message: str) -> ErrorResponse:
    return ErrorResponse(error=ErrorDetail(code=code, message=message))


def _error_response(
    request: HttpRequest, status: int, code: str, message: str
) -> HttpResponse:
    return api.create_response(
        request, _error(code, message).model_dump(), status=status
    )


@api.exception_handler(ValidationError)
def validation_error_handler(request: HttpRequest, _exc: ValidationError) -> HttpResponse:
    return _error_response(
        request, 422, "invalid_request", "The request parameters are invalid."
    )


@api.exception_handler(psycopg.Error)
@api.exception_handler(DjangoDatabaseError)
def database_error_handler(request: HttpRequest, exc: Exception) -> HttpResponse:
    LOGGER.error("attendance_read_database_error", exc_info=exc)
    return _error_response(
        request, 503, "database_unavailable", "Attendance data is unavailable."
    )


@api.exception_handler(Exception)
def unexpected_error_handler(request: HttpRequest, exc: Exception) -> HttpResponse:
    LOGGER.error("attendance_api_unexpected_error", exc_info=exc)
    return _error_response(
        request, 500, "internal_error", "The request could not be completed."
    )


def _duration_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def _work_hours_service(repository: Any) -> WorkHoursService:
    config = dependencies.api_config()
    return WorkHoursService(
        repository,
        source_key=config.source_key,
        device_timezone=config.device_timezone,
        unreasonable_span_seconds=config.unreasonable_span_seconds,
        working_day_cutoff=config.working_day_cutoff,
    )


@api.get(
    "/api/v1/employees",
    response={200: EmployeeSearchResponse, 422: ErrorResponse},
)
def search_employees(
    request: HttpRequest,
    query: str = Query(..., min_length=1, max_length=100),
) -> Status[EmployeeSearchResponse | ErrorResponse]:
    normalized = query.strip()
    if not normalized:
        return Status(422, _error("invalid_query", "Search text cannot be blank."))
    with dependencies.repository() as repository:
        employees = _work_hours_service(repository).search_employees(normalized)
    warnings: list[WarningResponse] = []
    if len(employees) > 1:
        warnings.append(
            WarningResponse(
                code="multiple_matches",
                message="Multiple employees matched. Select using employee ID.",
            )
        )
    response = EmployeeSearchResponse(
        source_key=dependencies.api_config().source_key,
        query=normalized,
        count=len(employees),
        employees=[
            EmployeeResponse(employee_id=item.employee_id, name=item.name)
            for item in employees
        ],
        warnings=warnings,
    )
    return Status(200, response)


@api.get(
    "/api/v1/employees/{employee_id}/work-hours",
    response={200: WorkHoursResponse, 404: ErrorResponse, 422: ErrorResponse},
)
def employee_work_hours(
    request: HttpRequest,
    employee_id: str = Path(..., min_length=1, max_length=100),
    selected_date: date = Query(..., alias="date"),
) -> Status[WorkHoursResponse | ErrorResponse]:
    config = dependencies.api_config()
    try:
        with dependencies.repository() as repository:
            result = _work_hours_service(repository).calculate(
                employee_id, selected_date
            )
    except EmployeeNotFoundError:
        return Status(
            404,
            _error(
                "employee_not_found",
                "No employee exists for this source and employee ID.",
            ),
        )

    timezone = config.device_timezone
    response = WorkHoursResponse(
        source_key=result.source_key,
        employee_id=result.employee.employee_id,
        name=result.employee.name,
        date=result.selected_date,
        timezone=result.timezone_name,
        punches=[
            PunchResponse(
                original_device_timestamp=punch.original_device_timestamp,
                timestamp_local=punch.occurred_at_utc.astimezone(timezone),
                timestamp_utc=punch.occurred_at_utc.astimezone(UTC),
                status_raw=punch.status_raw,
                punch_raw=punch.punch_raw,
            )
            for punch in result.punches
        ],
        punch_count=len(result.punches),
        first_punch=(
            result.first_punch.astimezone(timezone)
            if result.first_punch is not None
            else None
        ),
        last_punch=(
            result.last_punch.astimezone(timezone)
            if result.last_punch is not None
            else None
        ),
        calculation_method=CALCULATION_METHOD,
        calculation_label=DISPLAY_LABEL,
        calculated_duration_seconds=result.duration_seconds,
        calculated_duration=_duration_label(result.duration_seconds),
        breaks_excluded=False,
        working_day_cutoff=config.working_day_cutoff.strftime("%H:%M"),
        window_start=result.window_start.astimezone(timezone),
        window_end=result.window_end.astimezone(timezone),
        warnings=[
            WarningResponse(code=warning.code, message=warning.message)
            for warning in result.warnings
        ],
    )
    return Status(200, response)


@api.get(
    "/api/v1/attendance/daily",
    response={200: DailyAttendanceResponse, 422: ErrorResponse},
)
def daily_attendance(
    request: HttpRequest,
    selected_date: date | None = Query(None, alias="date"),
) -> Status[DailyAttendanceResponse | ErrorResponse]:
    config = dependencies.api_config()
    timezone = config.device_timezone
    with dependencies.repository() as repository:
        service = DailyAttendanceService(
            repository,
            source_key=config.source_key,
            device_timezone=timezone,
            working_day_cutoff=config.working_day_cutoff,
        )
        current_working_day = service.today()
        try:
            report = service.build(selected_date or current_working_day)
        except FutureDateError:
            return Status(
                422, _error("future_date", "The selected date is in the future.")
            )

    response = DailyAttendanceResponse(
        source_key=report.source_key,
        date=report.selected_date,
        timezone=report.timezone_name,
        generated_at=datetime.now(UTC),
        data_as_of=report.data_as_of,
        absence_label=report.absence_label,
        totals=DailyTotals(
            roster=report.roster_count,
            present=len(report.present),
            not_in=len(report.not_in),
        ),
        present=[
            PresentEmployeeResponse(
                employee_id=row.employee_id,
                name=row.name,
                first_punch=row.first_punch_utc.astimezone(timezone),
                last_punch=row.last_punch_utc.astimezone(timezone),
                punch_count=row.punch_count,
                registered=row.in_roster,
            )
            for row in report.present
        ],
        not_in=[
            EmployeeResponse(employee_id=row.employee_id, name=row.name)
            for row in report.not_in
        ],
        working_day_cutoff=config.working_day_cutoff.strftime("%H:%M"),
        current_working_day=current_working_day,
        window_start=report.window_start.astimezone(timezone),
        window_end=report.window_end.astimezone(timezone),
        warnings=[
            WarningResponse(code=warning.code, message=warning.message)
            for warning in report.warnings
        ],
    )
    return Status(200, response)
