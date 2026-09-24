"""Optional smoke test against populated PostgreSQL attendance data.

This test issues SELECT statements only. It is intentionally opt-in so the
ordinary suite never discovers or connects to a company database implicitly.
"""

from datetime import date
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from attendance_service.backend.api import create_app
from attendance_service.backend.config import ApiConfig, DatabaseConfig


READ_DATABASE_URL = os.getenv("ATTENDANCE_READ_DATABASE_URL")
SOURCE_KEY = os.getenv("ATTENDANCE_SOURCE_KEY")
DEVICE_TIMEZONE = os.getenv("ATTENDANCE_DEVICE_TIMEZONE")
pytestmark = pytest.mark.skipif(
    not all((READ_DATABASE_URL, SOURCE_KEY, DEVICE_TIMEZONE)),
    reason="Populated PostgreSQL read-test configuration is absent",
)


def test_api_reads_source_scoped_actual_postgresql_attendance() -> None:
    with psycopg.connect(READ_DATABASE_URL or "") as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            """
            SELECT e.employee_id,
                   max(e.employee_name) FILTER (WHERE e.employee_name IS NOT NULL),
                   (e.occurred_at_utc AT TIME ZONE %s)::date AS local_date
            FROM attendance_events e
            JOIN attendance_sources s ON s.id = e.source_id
            WHERE s.source_key = %s AND e.employee_name IS NOT NULL
            GROUP BY e.employee_id, local_date
            HAVING count(*) >= 2
            ORDER BY local_date DESC
            LIMIT 1
            """,
            (DEVICE_TIMEZONE, SOURCE_KEY),
        ).fetchone()
        connection.rollback()

    if row is None:
        pytest.skip("No populated employee-day with two punches exists")
    employee_id, employee_name, local_date = row
    assert isinstance(local_date, date)

    config = ApiConfig(
        database=DatabaseConfig(READ_DATABASE_URL or ""),
        source_key=SOURCE_KEY or "",
        device_timezone_name=DEVICE_TIMEZONE or "",
        unreasonable_span_seconds=64800,
        host="127.0.0.1",
        port=8000,
        pool_min_size=1,
        pool_max_size=2,
    )
    with TestClient(create_app(config)) as client:
        search = client.get(
            "/api/v1/employees", params={"query": employee_name.swapcase()}
        )
        work_hours = client.get(
            f"/api/v1/employees/{employee_id}/work-hours",
            params={"date": local_date.isoformat()},
        )

    assert search.status_code == 200
    assert any(
        item["employee_id"] == str(employee_id)
        for item in search.json()["employees"]
    )
    assert work_hours.status_code == 200
    payload = work_hours.json()
    assert payload["source_key"] == SOURCE_KEY
    assert payload["employee_id"] == str(employee_id)
    assert payload["calculation_method"] == "first_last_span"
    assert payload["breaks_excluded"] is False
    assert payload["punch_count"] >= 2
    assert payload["calculated_duration_seconds"] is not None
    utc_values = [item["timestamp_utc"] for item in payload["punches"]]
    assert utc_values == sorted(utc_values)
    assert all(value.endswith("Z") or value.endswith("+00:00") for value in utc_values)
