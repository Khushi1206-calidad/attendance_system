"""One finite, idempotent device-to-PostgreSQL synchronization."""

from __future__ import annotations

import logging
from typing import Any

from django.db import InterfaceError, OperationalError, connection

from attendance.services.config import SyncConfig
from attendance.services.device import PyzkDeviceReader
from attendance.services.ingestion import OneShotSynchronizer
from attendance.services.retry import retry_call
from attendance.services.repository import AttendanceRepository
from attendance.management.base import AttendanceCommand

LOGGER = logging.getLogger(__name__)


class Command(AttendanceCommand):
    help = "Run one finite, idempotent device-to-PostgreSQL synchronization"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--mode",
            choices=("scheduled", "manual"),
            default="scheduled",
            help="Audit label; the first synchronization is always recorded as initial",
        )

    def run(self, **options: Any) -> None:
        config = SyncConfig.from_environment()

        def attempt() -> None:
            repository = AttendanceRepository()
            try:
                OneShotSynchronizer(
                    config,
                    repository,
                    PyzkDeviceReader(config.device, config.retry),
                ).run(options["mode"])
            finally:
                # A fresh connection per attempt; this also releases the advisory lock.
                repository.close()

        retry_call(
            attempt,
            retry_on=(OperationalError, InterfaceError),
            config=config.retry,
            logger=LOGGER,
            operation_name="database_sync",
        )
        connection.close()
