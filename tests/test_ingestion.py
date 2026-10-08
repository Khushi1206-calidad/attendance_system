from datetime import datetime
from uuid import UUID, uuid4

import pytest

from attendance_service.backend.config import (
    DatabaseConfig,
    DeviceConfig,
    RetryConfig,
    SyncConfig,
)
from attendance_service.backend.domain import (
    DevicePunch,
    DeviceSnapshot,
    EmployeeSyncCounts,
)
from attendance_service.backend.ingestion import OneShotSynchronizer, SyncAlreadyRunning


class FakeDevice:
    def __init__(self, snapshot: DeviceSnapshot):
        self.snapshot = snapshot
        self.calls = 0

    def read_snapshot(self) -> DeviceSnapshot:
        self.calls += 1
        return self.snapshot


class FakeRepository:
    source_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    def __init__(self, *, lock_available: bool = True):
        self.lock_available = lock_available
        self.valid_keys = set()
        self.invalid_keys = set()
        self.runs = []
        self.finished = []
        self.released = False

    def ensure_source(self, **_):
        return self.source_id

    def try_source_lock(self, _):
        return self.lock_available

    def release_source_lock(self):
        self.released = True

    def source_has_records(self, _):
        return bool(self.valid_keys or self.invalid_keys)

    def start_sync_run(self, _, mode):
        run_id = uuid4()
        self.runs.append((run_id, mode))
        return run_id

    def set_device_serial_if_missing(self, *_):
        pass

    def sync_employees(self, _, __, users):
        return EmployeeSyncCounts(upserted=len(users), deactivated=0)

    def insert_valid_events(self, _, __, events):
        inserted = 0
        for event in events:
            key = (
                event.punch.employee_id,
                event.punch.original_device_timestamp,
            )
            if key not in self.valid_keys:
                self.valid_keys.add(key)
                inserted += 1
        return inserted

    def insert_invalid_events(self, _, __, events):
        inserted = 0
        for event in events:
            key = (
                event.punch.employee_id,
                event.punch.original_device_timestamp,
            )
            if key not in self.invalid_keys:
                self.invalid_keys.add(key)
                inserted += 1
        return inserted

    def finish_sync_run(self, run_id, **values):
        self.finished.append((run_id, values))


def config() -> SyncConfig:
    return SyncConfig(
        database=DatabaseConfig("postgresql://unused"),
        device=DeviceConfig("10.0.0.2", 4370, 0, 10, "Asia/Kolkata"),
        retry=RetryConfig(1, 0, 0),
        source_key="test-device",
        source_name="Test",
        minimum_valid_timestamp=datetime(2015, 1, 1),
        max_future_seconds=86400,
        batch_size=1,
    )


def snapshot() -> DeviceSnapshot:
    return DeviceSnapshot(
        punches=(
            DevicePunch(
                employee_id="0007",
                original_device_timestamp=datetime(2025, 1, 2, 9),
                status_raw="1",
                punch_raw="0",
                vendor_event_id=None,
                employee_name="Employee",
                raw_payload={},
            ),
            DevicePunch(
                employee_id="0007",
                original_device_timestamp=datetime(2119, 3, 17, 21, 31),
                status_raw="1",
                punch_raw="0",
                vendor_event_id=None,
                employee_name="Employee",
                raw_payload={},
            ),
        ),
        user_count=1,
        device_serial="SERIAL-1",
    )


def test_first_run_backfills_then_later_run_is_idempotent() -> None:
    repository = FakeRepository()
    device = FakeDevice(snapshot())
    synchronizer = OneShotSynchronizer(config(), repository, device)

    first = synchronizer.run("scheduled")
    second = synchronizer.run("manual")

    assert first.mode == "initial"
    assert first.counts.inserted == 1
    assert first.counts.invalid_inserted == 1
    assert second.mode == "manual"
    assert second.counts.inserted == 0
    assert second.counts.invalid_inserted == 0
    assert repository.runs[0][1] == "initial"
    assert repository.runs[1][1] == "manual"
    assert repository.finished[-1][1]["status"] == "succeeded"
    assert repository.released is True


def test_overlap_exits_before_device_connection() -> None:
    repository = FakeRepository(lock_available=False)
    device = FakeDevice(snapshot())

    with pytest.raises(SyncAlreadyRunning):
        OneShotSynchronizer(config(), repository, device).run()

    assert device.calls == 0
    assert repository.runs == []
