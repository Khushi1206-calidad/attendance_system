#!/usr/bin/env python
"""Django's command-line utility for the attendance backend.

    python manage.py migrate
    python manage.py sync [--mode manual]
    python manage.py web [--host HOST] [--port PORT]
    python manage.py report --output attendance_report.xlsx
    python manage.py device-test
    python manage.py capacity

Settings are ATTENDANCE_* environment variables, loaded from the .env file next
to this script, or from ``--env-file PATH`` given before the command. Variables
already set in the process environment take precedence.
"""

import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
EXIT_CONFIGURATION = 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env_file: str | None = str(BASE_DIR / ".env") if (BASE_DIR / ".env").is_file() else None
    if args[:1] == ["--env-file"] and len(args) >= 2:
        env_file, args = args[1], args[2:]
    elif args[:1] and args[0].startswith("--env-file="):
        env_file, args = args[0].split("=", 1)[1], args[1:]

    from attendance.services.config import ConfigurationError, load_environment
    from attendance.services.logging_config import configure_logging

    try:
        if env_file:
            load_environment(env_file)
        configure_logging()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django

        django.setup()
    except ConfigurationError as exc:
        configure_logging()
        logging.getLogger(__name__).error("configuration_error: %s", exc)
        return EXIT_CONFIGURATION

    from django.core.management import execute_from_command_line

    try:
        execute_from_command_line([sys.argv[0], *args])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
