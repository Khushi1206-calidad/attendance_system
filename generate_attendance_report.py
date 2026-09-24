"""Compatibility wrapper for a PostgreSQL-sourced Excel report."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from attendance_service.backend.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(
        main(["report", "--output", str(Path("attendance_report.xlsx"))])
    )

