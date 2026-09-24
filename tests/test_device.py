from datetime import datetime

from attendance_service.backend.config import DeviceConfig, RetryConfig
from attendance_service.backend.device import PyzkDeviceReader


class User:
    user_id = "0007"
    name = "Employee"


class Attendance:
    user_id = "0007"
    timestamp = datetime(2026, 9, 12, 9, 15)
    status = 1
    punch = 0
    uid = 987654


class Connection:
    disconnected = False

    def get_users(self):
        return [User()]

    def get_attendance(self):
        return [Attendance()]

    def get_serialnumber(self):
        return "SERIAL-1"

    def disconnect(self):
        self.disconnected = True


class Factory:
    def __init__(self, connection):
        self.connection = connection
        self.kwargs = None

    def __call__(self, *args, **kwargs):
        self.kwargs = kwargs
        return self

    def connect(self):
        return self.connection


def test_snapshot_preserves_string_id_and_does_not_use_legacy_uid() -> None:
    connection = Connection()
    factory = Factory(connection)
    reader = PyzkDeviceReader(
        DeviceConfig("10.0.0.2", 4370, 0, 10, "Asia/Kolkata"),
        RetryConfig(1, 0, 0),
        zk_factory=factory,
    )

    snapshot = reader.read_snapshot()

    assert snapshot.punches[0].employee_id == "0007"
    assert snapshot.punches[0].vendor_event_id is None
    assert snapshot.punches[0].status_raw == "1"
    assert snapshot.punches[0].punch_raw == "0"
    assert connection.disconnected is True
    assert factory.kwargs["force_udp"] is False

