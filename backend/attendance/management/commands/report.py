"""Optional Excel report generated from PostgreSQL."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from attendance.services.config import ConfigurationError
from attendance.services.reporting import generate_excel_report
from attendance.services.repository import AttendanceRepository
from attendance.management.base import AttendanceCommand


class Command(AttendanceCommand):
    help = "Generate an optional Excel report from PostgreSQL"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument("--source-key")

    def run(self, **options: Any) -> None:
        source_key = options["source_key"] or os.getenv("ATTENDANCE_SOURCE_KEY")
        if not source_key:
            raise ConfigurationError("ATTENDANCE_SOURCE_KEY or --source-key is required")
        repository = AttendanceRepository()
        try:
            generate_excel_report(repository, source_key, options["output"].resolve())
        finally:
            repository.close()
