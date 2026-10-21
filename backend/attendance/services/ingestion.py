"""One-shot, idempotent synchronization orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from datetime import timedelta
from typing import TypeVar

from attendance.services.config import SyncConfig
from attendance.services.device import PyzkDeviceReader
from attendance.services.domain import (
    IngestionCounts,
    InvalidAttendanceEvent,
    SyncOutcome,
    ValidAttendanceEvent,
)
from attendance.services.logging_config import log_fields
from attendance.services.validation import AttendanceValidator
from attendance.services.repository import AttendanceRepository

T = TypeVar("T")


class SyncAlreadyRunning(RuntimeError):
    """Another process owns the source-specific synchronization lock."""


def _batches(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


class OneShotSynchronizer:
    def __init__(
        self,
        config: SyncConfig,
        repository: AttendanceRepository,
        device: PyzkDeviceReader,
    ) -> None:
        self._config = config
        self._repository = repository
        self._device = device
        self._logger = logging.getLogger(__name__)

    def run(self, requested_mode: str = "scheduled") -> SyncOutcome:
        """Read the device once and store new punches in a single transaction."""
        source_id = self._repository.ensure_source(
            source_key=self._config.source_key,
            display_name=self._config.source_name,
            timezone_name=self._config.device.timezone_name,
        )
        if not self._repository.try_source_lock(self._config.source_key):
            raise SyncAlreadyRunning(
                f"A synchronization is already running for {self._config.source_key}"
            )

        started = time.monotonic()
        run_id = None
        mode = requested_mode
        received_count = 0
        valid_count = 0
        invalid_count = 0
        skipped_older = 0
        inserted = 0
        invalid_inserted = 0
        try:
            mode = (
                requested_mode
                if self._repository.source_has_records(source_id)
                else "initial"
            )
            watermark = self._repository.latest_valid_device_timestamp(source_id)
            # Re-check a lookback window so late-stored punches are not missed;
            # the unique constraint still discards anything already stored.
            threshold = (
                watermark - timedelta(seconds=self._config.lookback_seconds)
                if watermark is not None
                else None
            )
            run_id = self._repository.start_sync_run(source_id, mode)
            log_fields(
                self._logger,
                logging.INFO,
                "sync_started",
                run_id=run_id,
                source_key=self._config.source_key,
                mode=mode,
                watermark=watermark.isoformat() if watermark else None,
                threshold=threshold.isoformat() if threshold else None,
            )

            snapshot = self._device.read_snapshot()
            received_count = len(snapshot.punches)
            validator = AttendanceValidator(
                minimum_valid_timestamp=self._config.minimum_valid_timestamp,
                max_future_seconds=self._config.max_future_seconds,
                device_timezone=self._config.device.timezone,
            )
            valid: list[ValidAttendanceEvent] = []
            invalid: list[InvalidAttendanceEvent] = []
            for punch in snapshot.punches:
                result = validator.validate(punch)
                if isinstance(result, ValidAttendanceEvent):
                    if (
                        threshold is not None
                        and punch.original_device_timestamp < threshold
                    ):
                        skipped_older += 1
                        continue
                    valid.append(result)
                else:
                    invalid.append(result)
            valid_count = len(valid) + skipped_older
            invalid_count = len(invalid)

            # All-or-nothing: any failure below rolls back every row of this run.
            with self._repository.atomic():
                self._repository.set_device_serial_if_missing(
                    source_id, snapshot.device_serial
                )
                employee_counts = self._repository.sync_employees(
                    source_id, run_id, snapshot.users
                )
                for batch in _batches(valid, self._config.batch_size):
                    inserted += self._repository.insert_valid_events(
                        source_id, run_id, batch
                    )
                for batch in _batches(invalid, self._config.batch_size):
                    invalid_inserted += self._repository.insert_invalid_events(
                        source_id, run_id, batch
                    )

            if not snapshot.users:
                log_fields(
                    self._logger,
                    logging.WARNING,
                    "employee_roster_empty_snapshot",
                    run_id=run_id,
                    source_key=self._config.source_key,
                )
            counts = IngestionCounts(
                received=received_count,
                valid=valid_count,
                invalid=invalid_count,
                inserted=inserted,
                invalid_inserted=invalid_inserted,
                skipped_older=skipped_older,
            )
            self._repository.finish_sync_run(
                run_id,
                status="succeeded",
                received_count=counts.received,
                valid_count=counts.valid,
                invalid_count=counts.invalid,
                inserted_count=counts.inserted,
                invalid_inserted_count=counts.invalid_inserted,
            )
            log_fields(
                self._logger,
                logging.INFO,
                "sync_succeeded",
                run_id=run_id,
                source_key=self._config.source_key,
                mode=mode,
                fetched=counts.received,
                valid=counts.valid,
                invalid=counts.invalid,
                skipped_older=counts.skipped_older,
                inserted=counts.inserted,
                invalid_inserted=counts.invalid_inserted,
                duplicates=(
                    counts.received
                    - counts.skipped_older
                    - counts.inserted
                    - counts.invalid_inserted
                ),
                employees_upserted=employee_counts.upserted,
                employees_deactivated=employee_counts.deactivated,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return SyncOutcome(run_id=run_id, mode=mode, counts=counts)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:2000]
            log_fields(
                self._logger,
                logging.ERROR,
                "sync_failed",
                run_id=run_id,
                source_key=self._config.source_key,
                mode=mode,
                fetched=received_count,
                skipped_older=skipped_older,
                error=error,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            if run_id is not None:
                try:
                    # The event transaction was rolled back: nothing was inserted.
                    self._repository.finish_sync_run(
                        run_id,
                        status="failed",
                        received_count=received_count,
                        valid_count=valid_count,
                        invalid_count=invalid_count,
                        error_message=error,
                    )
                except Exception:
                    self._logger.error("sync_failure_audit_failed", exc_info=True)
            raise
        finally:
            try:
                self._repository.release_source_lock()
            except Exception:
                self._logger.error("sync_lock_release_failed", exc_info=True)
