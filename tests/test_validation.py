from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from attendance_service.domain import (
    DevicePunch,
    InvalidAttendanceEvent,
    ValidAttendanceEvent,
)
from attendance_service.validation import AttendanceValidator


def punch(timestamp: datetime, employee_id: str = "0007") -> DevicePunch:
    return DevicePunch(
        employee_id=employee_id,
        original_device_timestamp=timestamp,
        status_raw="1",
        punch_raw="0",
        vendor_event_id=None,
        employee_name="Test Employee",
        raw_payload={"employee_id": employee_id},
    )


def validator() -> AttendanceValidator:
    return AttendanceValidator(
        minimum_valid_timestamp=datetime(2015, 1, 1),
        max_future_seconds=86400,
        device_timezone=ZoneInfo("Asia/Kolkata"),
    )


def test_valid_timestamp_is_converted_to_utc_without_changing_original() -> None:
    original = datetime(2026, 9, 12, 10, 30)
    result = validator().validate(
        punch(original), now_utc=datetime(2026, 9, 12, 12, tzinfo=UTC)
    )

    assert isinstance(result, ValidAttendanceEvent)
    assert result.punch.employee_id == "0007"
    assert result.punch.original_device_timestamp == original
    assert result.occurred_at_utc == datetime(2026, 9, 12, 5, tzinfo=UTC)


def test_year_2119_is_rejected_as_future_timestamp() -> None:
    result = validator().validate(
        punch(datetime(2119, 3, 17, 21, 31, 14)),
        now_utc=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert isinstance(result, InvalidAttendanceEvent)
    assert result.validation_error == "future_timestamp"
    assert result.punch.original_device_timestamp.year == 2119


def test_old_timestamp_is_rejected() -> None:
    result = validator().validate(
        punch(datetime(2014, 12, 31, 23, 59)),
        now_utc=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert isinstance(result, InvalidAttendanceEvent)
    assert result.validation_error == "before_minimum_timestamp"

