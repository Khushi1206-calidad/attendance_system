from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from attendance_service.read_models import AttendancePunch, Employee
from attendance_service.work_hours import WorkHoursService, calculate_first_last_span


EMPLOYEE = Employee("0137", "Khushi")
DAY = date(2026, 9, 22)


def punch(hour: int, minute: int, status: str = "1", code: str = "0"):
    utc = datetime(2026, 9, 22, hour, minute, tzinfo=UTC)
    return AttendancePunch(
        original_device_timestamp=utc.replace(tzinfo=None),
        occurred_at_utc=utc,
        status_raw=status,
        punch_raw=code,
    )


def calculate(punches, threshold=64800):
    return calculate_first_last_span(
        employee=EMPLOYEE,
        source_key="main-office-device",
        selected_date=DAY,
        timezone_name="Asia/Kolkata",
        punches=tuple(punches),
        unreasonable_span_seconds=threshold,
    )


def test_zero_punches_returns_no_attendance_and_null_duration() -> None:
    result = calculate([])

    assert result.duration_seconds is None
    assert result.first_punch is None
    assert [warning.code for warning in result.warnings] == ["no_attendance"]


def test_one_punch_returns_insufficient_punches_and_null_duration() -> None:
    result = calculate([punch(3, 34)])

    assert result.duration_seconds is None
    assert result.first_punch == result.last_punch
    assert [warning.code for warning in result.warnings] == [
        "insufficient_punches"
    ]


def test_odd_punch_count_still_calculates_first_to_last_span() -> None:
    values = [punch(12, 41, code="5"), punch(3, 34), punch(8, 0, code="4")]

    result = calculate(values)

    assert result.duration_seconds == 9 * 3600 + 7 * 60
    assert [item.occurred_at_utc for item in result.punches] == sorted(
        item.occurred_at_utc for item in values
    )
    assert [warning.code for warning in result.warnings] == ["odd_punch_count"]
    assert result.punches[-1].punch_raw == "5"


def test_unreasonable_span_warns_without_changing_result() -> None:
    result = calculate([punch(1, 0), punch(13, 0)], threshold=8 * 3600)

    assert result.duration_seconds == 12 * 3600
    assert [warning.code for warning in result.warnings] == [
        "unreasonable_span"
    ]


class CapturingRepository:
    def __init__(self):
        self.boundaries = None

    def get_employee(self, **_):
        return EMPLOYEE

    def get_punches(self, **values):
        self.boundaries = (values["start_utc"], values["end_utc"])
        return []


def test_selected_date_boundaries_are_converted_from_device_timezone_to_utc():
    repository = CapturingRepository()
    service = WorkHoursService(
        repository,
        source_key="main-office-device",
        device_timezone=ZoneInfo("Asia/Kolkata"),
        unreasonable_span_seconds=64800,
    )

    service.calculate("0137", DAY)

    assert repository.boundaries == (
        datetime(2026, 9, 21, 18, 30, tzinfo=UTC),
        datetime(2026, 9, 22, 18, 30, tzinfo=UTC),
    )

