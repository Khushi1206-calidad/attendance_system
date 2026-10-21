"""Read a device snapshot without writing it anywhere."""

from __future__ import annotations

import logging
from typing import Any

from attendance.services.config import DeviceConfig, RetryConfig
from attendance.services.device import PyzkDeviceReader
from attendance.services.logging_config import log_fields
from attendance.management.base import AttendanceCommand

LOGGER = logging.getLogger(__name__)


class Command(AttendanceCommand):
    help = "Read a device snapshot without writing it anywhere"

    def run(self, **options: Any) -> None:
        snapshot = PyzkDeviceReader(
            DeviceConfig.from_environment(), RetryConfig.from_environment()
        ).read_snapshot()
        log_fields(
            LOGGER,
            logging.INFO,
            "device_test_succeeded",
            records=len(snapshot.punches),
            users=snapshot.user_count,
            serial=snapshot.device_serial,
        )
