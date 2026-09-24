"""Attendance validation and device-local to UTC conversion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from attendance_service.backend.domain import (
    DevicePunch,
    InvalidAttendanceEvent,
    ValidAttendanceEvent,
)


class AttendanceValidator:
    def __init__(
        self,
        *,
        minimum_valid_timestamp: datetime,
        max_future_seconds: int,
        device_timezone: ZoneInfo,
    ) -> None:
        self._minimum = minimum_valid_timestamp
        self._future_delta = timedelta(seconds=max_future_seconds)
        self._timezone = device_timezone

    def validate(
        self, punch: DevicePunch, *, now_utc: datetime | None = None
    ) -> ValidAttendanceEvent | InvalidAttendanceEvent:
        if now_utc is None:
            now_utc = datetime.now(UTC)
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")

        timestamp = punch.original_device_timestamp
        if timestamp < self._minimum:
            return InvalidAttendanceEvent(punch, "before_minimum_timestamp")

        local_now = now_utc.astimezone(self._timezone).replace(tzinfo=None)
        if timestamp > local_now + self._future_delta:
            return InvalidAttendanceEvent(punch, "future_timestamp")

        occurred_at_utc = timestamp.replace(tzinfo=self._timezone).astimezone(UTC)
        return ValidAttendanceEvent(punch, occurred_at_utc)

