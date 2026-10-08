from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from attendance_service.backend.api import create_app
from attendance_service.backend.config import ApiConfig, DatabaseConfig
from attendance_service.database.read_models import (
    AttendancePunch,
    DailyPresenceRow,
    Employee,
)


class FakeRepository:
    def __init__(self):
        self.employees = {
            "0137": Employee("0137", "Khushi"),
            "0999": Employee("0999", "Khushi"),
        }
        self.punches = {
            "0137": [
                AttendancePunch(
                    datetime(2026, 9, 22, 9, 4),
                    datetime(2026, 9, 22, 3, 34, tzinfo=UTC),
                    "1",
                    "0",
                ),
                AttendancePunch(
                    datetime(2026, 9, 22, 12, 0),
                    datetime(2026, 9, 22, 6, 30, tzinfo=UTC),
                    "4",
                    "4",
                ),
                AttendancePunch(
                    datetime(2026, 9, 22, 18, 11),
                    datetime(2026, 9, 22, 12, 41, tzinfo=UTC),
                    "1",
                    "5",
                ),
            ]
        }

    def search_employees(self, *, source_key, query, limit):
        assert source_key == "main-office-device"
        return [
            employee
            for employee in self.employees.values()
            if query.casefold() in (employee.name or "").casefold()
        ][:limit]

    def get_employee(self, *, source_key, employee_id):
        assert source_key == "main-office-device"
        return self.employees.get(employee_id)

    def get_daily_presence(self, *, source_key, start_utc, end_utc):
        assert start_utc == datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
        return [
            DailyPresenceRow(
                "0137", "Khushi", True,
                datetime(2026, 9, 22, 3, 34, tzinfo=UTC),
                datetime(2026, 9, 22, 12, 41, tzinfo=UTC), 3,
            ),
            DailyPresenceRow("0999", "Khushi", True, None, None, 0),
        ]

    def get_last_successful_sync(self, *, source_key):
        return datetime(2026, 9, 22, 12, 45, tzinfo=UTC)

    def get_punches(self, *, source_key, employee_id, start_utc, end_utc):
        assert source_key == "main-office-device"
        assert start_utc == datetime(2026, 9, 21, 18, 30, tzinfo=UTC)
        assert end_utc == datetime(2026, 9, 22, 18, 30, tzinfo=UTC)
        return self.punches.get(employee_id, [])


def client() -> TestClient:
    repository = FakeRepository()

    @contextmanager
    def provider():
        yield repository

    config = ApiConfig(
        database=DatabaseConfig("postgresql://unused"),
        source_key="main-office-device",
        device_timezone_name="Asia/Kolkata",
        unreasonable_span_seconds=64800,
        host="127.0.0.1",
        port=8000,
        pool_min_size=1,
        pool_max_size=5,
    )
    return TestClient(create_app(config, repository_provider=provider))


def test_employee_search_is_case_insensitive_and_source_aware() -> None:
    with client() as api:
        response = api.get("/api/v1/employees", params={"query": "kHuShI"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_key"] == "main-office-device"
    assert [item["employee_id"] for item in payload["employees"]] == [
        "0137",
        "0999",
    ]
    assert payload["warnings"][0]["code"] == "multiple_matches"


def test_work_hours_response_uses_confirmed_first_last_policy() -> None:
    with client() as api:
        response = api.get(
            "/api/v1/employees/0137/work-hours", params={"date": "2026-09-22"}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_key"] == "main-office-device"
    assert payload["calculation_method"] == "first_last_span"
    assert payload["calculation_label"] == "Total attendance span (breaks included)"
    assert payload["calculated_duration_seconds"] == 9 * 3600 + 7 * 60
    assert payload["calculated_duration"] == "9h 7m"
    assert payload["breaks_excluded"] is False
    assert payload["punch_count"] == 3
    assert [item["punch_raw"] for item in payload["punches"]] == ["0", "4", "5"]
    assert payload["warnings"][0]["code"] == "odd_punch_count"


def test_unknown_employee_and_invalid_date_return_safe_errors() -> None:
    with client() as api:
        unknown = api.get(
            "/api/v1/employees/missing/work-hours",
            params={"date": "2026-09-22"},
        )
        invalid = api.get(
            "/api/v1/employees/0137/work-hours", params={"date": "not-a-date"}
        )

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "employee_not_found"
    assert invalid.status_code == 422
    assert invalid.json() == {
        "error": {
            "code": "invalid_request",
            "message": "The request parameters are invalid.",
        }
    }


def test_known_employee_with_no_attendance_returns_warning() -> None:
    with client() as api:
        response = api.get(
            "/api/v1/employees/0999/work-hours", params={"date": "2026-09-22"}
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["punches"] == []
    assert payload["calculated_duration"] is None
    assert payload["warnings"][0]["code"] == "no_attendance"


def test_daily_attendance_splits_present_and_absent() -> None:
    with client() as api:
        response = api.get("/api/v1/attendance/daily", params={"date": "2026-09-22"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"] == {"roster": 2, "present": 1, "not_in": 1}
    assert payload["present"][0]["employee_id"] == "0137"
    assert payload["present"][0]["first_punch"] == "2026-09-22T09:04:00+05:30"
    assert payload["not_in"] == [{"employee_id": "0999", "name": "Khushi"}]
    assert payload["absence_label"] == "absent"
    assert payload["data_as_of"] is not None


def test_daily_attendance_rejects_future_date() -> None:
    with client() as api:
        response = api.get("/api/v1/attendance/daily", params={"date": "2999-01-01"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "future_date"


def test_html_interface_is_available() -> None:
    with client() as api:
        response = api.get("/")

    assert response.status_code == 200
    assert "Total attendance span (breaks included)" in response.text
    assert "main-office-device" in response.text

