"""Serve the read-only Django Ninja REST API with uvicorn (ASGI)."""

from __future__ import annotations

from typing import Any

from attendance.services.config import ApiConfig, ConfigurationError
from attendance.management.base import AttendanceCommand


class Command(AttendanceCommand):
    help = "Run the read-only attendance REST API (Django Ninja)"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--host", help="Bind address; defaults to ATTENDANCE_API_HOST/127.0.0.1")
        parser.add_argument("--port", type=int, help="Bind port; defaults to ATTENDANCE_API_PORT/8000")

    def run(self, **options: Any) -> None:
        import uvicorn

        config = ApiConfig.from_environment()
        port = config.port if options["port"] is None else options["port"]
        if not 1 <= port <= 65535:
            raise ConfigurationError("Web port must be between 1 and 65535")
        uvicorn.run(
            "config.asgi:application",
            host=options["host"] or config.host,
            port=port,
            access_log=False,
            log_config=None,
        )
