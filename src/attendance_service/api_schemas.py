"""Public API response contracts."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class WarningResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    name: str | None


class EmployeeSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_key: str
    query: str
    count: int
    employees: list[EmployeeResponse]
    warnings: list[WarningResponse]


class PunchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    original_device_timestamp: datetime
    timestamp_local: datetime
    timestamp_utc: datetime
    status_raw: str | None
    punch_raw: str | None


class WorkHoursResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_key: str
    employee_id: str
    name: str | None
    date: date
    timezone: str
    punches: list[PunchResponse]
    punch_count: int
    first_punch: datetime | None
    last_punch: datetime | None
    calculation_method: str
    calculation_label: str
    calculated_duration_seconds: int | None
    calculated_duration: str | None
    breaks_excluded: bool
    warnings: list[WarningResponse]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail

