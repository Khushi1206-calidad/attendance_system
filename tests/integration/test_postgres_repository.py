from datetime import UTC, datetime
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig

from attendance_service.domain import DevicePunch, ValidAttendanceEvent
from attendance_service.repository import AttendanceRepository


TEST_URL = os.getenv("ATTENDANCE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_URL,
    reason="ATTENDANCE_TEST_DATABASE_URL is not configured",
)


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    old_url = os.environ.get("ATTENDANCE_DATABASE_URL")
    os.environ["ATTENDANCE_DATABASE_URL"] = TEST_URL or ""
    root = Path(__file__).resolve().parents[2]
    command.upgrade(AlembicConfig(str(root / "alembic.ini")), "head")
    yield
    if old_url is None:
        os.environ.pop("ATTENDANCE_DATABASE_URL", None)
    else:
        os.environ["ATTENDANCE_DATABASE_URL"] = old_url


def test_database_constraint_and_on_conflict_prevent_duplicates():
    repository = AttendanceRepository.connect(TEST_URL or "")
    source_key = f"integration-{uuid4()}"
    try:
        source_id = repository.ensure_source(
            source_key=source_key,
            display_name="Integration test",
            timezone_name="Asia/Kolkata",
        )
        run_id = repository.start_sync_run(source_id, "initial")
        event = ValidAttendanceEvent(
            punch=DevicePunch(
                employee_id="0007",
                original_device_timestamp=datetime(2026, 9, 12, 9, 15),
                status_raw="1",
                punch_raw="0",
                vendor_event_id=None,
                employee_name="Test",
                raw_payload={},
            ),
            occurred_at_utc=datetime(2026, 9, 12, 3, 45, tzinfo=UTC),
        )

        assert repository.insert_valid_events(source_id, run_id, [event]) == 1
        assert repository.insert_valid_events(source_id, run_id, [event]) == 0
        assert len(repository.fetch_report_events(source_key)) == 1
    finally:
        repository.close()


def test_advisory_lock_prevents_second_process_for_same_source():
    first = AttendanceRepository.connect(TEST_URL or "")
    second = AttendanceRepository.connect(TEST_URL or "")
    source_key = f"lock-{uuid4()}"
    try:
        assert first.try_source_lock(source_key) is True
        assert second.try_source_lock(source_key) is False
        first.release_source_lock()
        assert second.try_source_lock(source_key) is True
    finally:
        first.close()
        second.close()

