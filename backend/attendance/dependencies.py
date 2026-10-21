"""Configuration and repository access for API views; tests replace these."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from django.db import connections

from attendance.services.config import ApiConfig
from attendance.services.read_repository import ReadOnlyAttendanceRepository


@lru_cache(maxsize=1)
def api_config() -> ApiConfig:
    return ApiConfig.from_environment()


@contextmanager
def repository() -> Iterator[ReadOnlyAttendanceRepository]:
    # Pooled, UTC, and read-only (see settings.DATABASES["readonly"]).
    yield ReadOnlyAttendanceRepository(connections["readonly"])
