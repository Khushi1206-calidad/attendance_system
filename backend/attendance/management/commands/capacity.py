"""Read device attendance and biometric capacity."""

from __future__ import annotations

import logging
from typing import Any

from attendance.services.config import DeviceConfig, RetryConfig
from attendance.services.device import PyzkDeviceReader
from attendance.services.logging_config import log_fields
from attendance.management.base import AttendanceCommand

LOGGER = logging.getLogger(__name__)


class Command(AttendanceCommand):
    help = "Read device attendance and biometric capacity"

    def run(self, **options: Any) -> None:
        snapshot = PyzkDeviceReader(
            DeviceConfig.from_environment(), RetryConfig.from_environment()
        ).read_capacity()
        utilization = None
        if snapshot.attendance_capacity:
            utilization = round(
                100 * snapshot.attendance_count / snapshot.attendance_capacity, 1
            )
        log_fields(
            LOGGER,
            logging.INFO,
            "device_capacity_read",
            attendance_count=snapshot.attendance_count,
            attendance_capacity=snapshot.attendance_capacity,
            attendance_utilization_percent=utilization,
            users=snapshot.user_count,
            user_capacity=snapshot.user_capacity,
            fingerprints=snapshot.fingerprint_count,
            fingerprint_capacity=snapshot.fingerprint_capacity,
        )
