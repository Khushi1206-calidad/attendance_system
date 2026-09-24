"""Command-line entry points. Scheduling intentionally lives outside Python."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig

from attendance_service.backend.config import (
    ApiConfig,
    ConfigurationError,
    DatabaseConfig,
    SyncConfig,
    load_environment,
)
from attendance_service.backend.device import DeviceReadError, PyzkDeviceReader
from attendance_service.backend.ingestion import OneShotSynchronizer, SyncAlreadyRunning
from attendance_service.backend.logging_config import configure_logging, log_fields
from attendance_service.backend.reporting import generate_excel_report
from attendance_service.backend.retry import retry_call
from attendance_service.database.repository import AttendanceRepository

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIGURATION = 2
EXIT_ALREADY_RUNNING = 3

LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="attendance-service")
    parser.add_argument(
        "--env-file",
        help="Optional dotenv file; existing process environment takes precedence",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    sync = subcommands.add_parser(
        "sync", help="Run one finite, idempotent device-to-PostgreSQL synchronization"
    )
    sync.add_argument(
        "--mode",
        choices=("scheduled", "manual"),
        default="scheduled",
        help="Audit label; the first synchronization is always recorded as initial",
    )

    subcommands.add_parser("migrate", help="Apply pending PostgreSQL migrations")

    report = subcommands.add_parser(
        "report", help="Generate an optional Excel report from PostgreSQL"
    )
    report.add_argument("--output", required=True, type=Path)
    report.add_argument("--source-key")

    subcommands.add_parser(
        "device-test", help="Read a device snapshot without writing it anywhere"
    )
    subcommands.add_parser(
        "capacity", help="Read device attendance and biometric capacity"
    )
    web = subcommands.add_parser(
        "web", help="Run the read-only attendance API and web interface"
    )
    web.add_argument(
        "--host", help="Bind address; defaults to ATTENDANCE_API_HOST/127.0.0.1"
    )
    web.add_argument("--port", type=int, help="Bind port; defaults to 8000")
    return parser


def _run_sync(config: SyncConfig, mode: str) -> None:
    def attempt() -> None:
        repository = AttendanceRepository.connect(config.database.url)
        try:
            synchronizer = OneShotSynchronizer(
                config,
                repository,
                PyzkDeviceReader(config.device, config.retry),
            )
            synchronizer.run(mode)
        finally:
            repository.close()

    retry_call(
        attempt,
        retry_on=(psycopg.OperationalError, psycopg.InterfaceError),
        config=config.retry,
        logger=LOGGER,
        operation_name="database_sync",
    )


def _run_migrations(database_url: str) -> None:
    project_root = Path(__file__).resolve().parents[3]
    alembic_config = AlembicConfig(str(project_root / "alembic.ini"))
    command.upgrade(alembic_config, "head")


def _run_report(database_url: str, source_key: str, output: Path) -> None:
    repository = AttendanceRepository.connect(database_url)
    try:
        generate_excel_report(repository, source_key, output.resolve())
    finally:
        repository.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        load_environment(args.env_file)
        configure_logging()

        if args.command == "migrate":
            _run_migrations(DatabaseConfig.from_environment().url)
        elif args.command == "sync":
            _run_sync(SyncConfig.from_environment(), args.mode)
        elif args.command == "report":
            database = DatabaseConfig.from_environment()
            source_key = args.source_key or os.getenv("ATTENDANCE_SOURCE_KEY")
            if not source_key:
                raise ConfigurationError(
                    "ATTENDANCE_SOURCE_KEY or --source-key is required"
                )
            _run_report(
                database.url,
                source_key,
                args.output,
            )
        elif args.command == "device-test":
            from attendance_service.backend.config import DeviceConfig, RetryConfig

            device = DeviceConfig.from_environment()
            retry = RetryConfig.from_environment()
            snapshot = PyzkDeviceReader(device, retry).read_snapshot()
            log_fields(
                LOGGER,
                logging.INFO,
                "device_test_succeeded",
                records=len(snapshot.punches),
                users=snapshot.user_count,
                serial=snapshot.device_serial,
            )
        elif args.command == "capacity":
            from attendance_service.backend.config import DeviceConfig, RetryConfig

            device = DeviceConfig.from_environment()
            retry = RetryConfig.from_environment()
            snapshot = PyzkDeviceReader(device, retry).read_capacity()
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
        elif args.command == "web":
            import uvicorn

            from attendance_service.backend.api import create_app

            config = ApiConfig.from_environment()
            port = config.port if args.port is None else args.port
            if not 1 <= port <= 65535:
                raise ConfigurationError("Web port must be between 1 and 65535")
            uvicorn.run(
                create_app(config),
                host=args.host or config.host,
                port=port,
                access_log=False,
            )
        return EXIT_SUCCESS
    except ConfigurationError as exc:
        logging.getLogger(__name__).error("configuration_error: %s", exc)
        return EXIT_CONFIGURATION
    except SyncAlreadyRunning as exc:
        logging.getLogger(__name__).warning("sync_already_running: %s", exc)
        return EXIT_ALREADY_RUNNING
    except (DeviceReadError, psycopg.Error, OSError, ValueError) as exc:
        logging.getLogger(__name__).error(
            "command_failed: %s", exc, exc_info=True
        )
        return EXIT_FAILURE
    except Exception as exc:
        logging.getLogger(__name__).critical(
            "unexpected_command_failure: %s", exc, exc_info=True
        )
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
