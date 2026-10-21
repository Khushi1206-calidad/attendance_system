"""Typed values passed between the device, validation, and database layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DevicePunch:
    employee_id: str
    original_device_timestamp: datetime
    status_raw: str | None
    punch_raw: str | None
    vendor_event_id: str | None
    employee_name: str | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidAttendanceEvent:
    punch: DevicePunch
    occurred_at_utc: datetime


@dataclass(frozen=True, slots=True)
class InvalidAttendanceEvent:
    punch: DevicePunch
    validation_error: str


@dataclass(frozen=True, slots=True)
class DeviceUser:
    employee_id: str
    name: str | None


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    punches: tuple[DevicePunch, ...]
    user_count: int
    device_serial: str | None
    users: tuple[DeviceUser, ...] = ()


@dataclass(frozen=True, slots=True)
class EmployeeSyncCounts:
    upserted: int
    deactivated: int


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    attendance_count: int
    user_count: int
    attendance_capacity: int | None
    user_capacity: int | None
    fingerprint_count: int | None
    fingerprint_capacity: int | None


@dataclass(frozen=True, slots=True)
class IngestionCounts:
    received: int
    valid: int
    invalid: int
    inserted: int
    invalid_inserted: int
    skipped_older: int = 0


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    run_id: UUID
    mode: str
    counts: IngestionCounts
