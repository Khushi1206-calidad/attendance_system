"""Shared exit-code handling for the attendance management commands.

Schedulers rely on these exit codes: 0 success, 1 operational failure,
2 missing or invalid configuration, 3 another sync owns the source lock.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from django.core.management.base import BaseCommand
from django.db import Error as DjangoDatabaseError

from attendance.services.config import ConfigurationError
from attendance.services.device import DeviceReadError
from attendance.services.ingestion import SyncAlreadyRunning

EXIT_FAILURE = 1
EXIT_CONFIGURATION = 2
EXIT_ALREADY_RUNNING = 3

LOGGER = logging.getLogger("attendance.commands")


class AttendanceCommand(BaseCommand):
    def run(self, **options: Any) -> None:
        raise NotImplementedError

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            self.run(**options)
        except ConfigurationError as exc:
            LOGGER.error("configuration_error: %s", exc)
            raise SystemExit(EXIT_CONFIGURATION) from exc
        except SyncAlreadyRunning as exc:
            LOGGER.warning("sync_already_running: %s", exc)
            raise SystemExit(EXIT_ALREADY_RUNNING) from exc
        except (
            DeviceReadError,
            DjangoDatabaseError,
            psycopg.Error,
            OSError,
            ValueError,
        ) as exc:
            LOGGER.error("command_failed: %s", exc, exc_info=True)
            raise SystemExit(EXIT_FAILURE) from exc
        except Exception as exc:
            LOGGER.critical("unexpected_command_failure: %s", exc, exc_info=True)
            raise SystemExit(EXIT_FAILURE) from exc
