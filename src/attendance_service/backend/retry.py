"""Small bounded retry helper used for temporary I/O failures."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from attendance_service.backend.config import RetryConfig
from attendance_service.backend.logging_config import log_fields

T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    retry_on: tuple[type[BaseException], ...],
    config: RetryConfig,
    logger: logging.Logger,
    operation_name: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    delay = config.initial_seconds
    for attempt in range(1, config.max_attempts + 1):
        try:
            return operation()
        except retry_on:
            if attempt >= config.max_attempts:
                raise
            log_fields(
                logger,
                logging.WARNING,
                "temporary_failure_retrying",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
                retry_in_seconds=delay,
            )
            sleep(delay)
            delay = min(config.max_seconds, max(delay * 2, config.initial_seconds))
    raise RuntimeError("retry loop ended unexpectedly")

