"""Read-only adapter for one-shot attendance snapshots from a pyzk device."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from attendance_service.backend.config import DeviceConfig, RetryConfig
from attendance_service.backend.domain import (
    CapacitySnapshot,
    DevicePunch,
    DeviceSnapshot,
    DeviceUser,
)
from attendance_service.backend.logging_config import log_fields
from attendance_service.backend.retry import retry_call


class DeviceReadError(RuntimeError):
    """The device snapshot could not be read."""


class PyzkDeviceReader:
    def __init__(
        self,
        config: DeviceConfig,
        retry_config: RetryConfig,
        *,
        zk_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._retry_config = retry_config
        self._zk_factory = zk_factory
        self._logger = logging.getLogger(__name__)

    def read_snapshot(self) -> DeviceSnapshot:
        return retry_call(
            self._read_once,
            retry_on=(DeviceReadError,),
            config=self._retry_config,
            logger=self._logger,
            operation_name="device_snapshot",
        )

    def read_capacity(self) -> CapacitySnapshot:
        return retry_call(
            self._read_capacity_once,
            retry_on=(DeviceReadError,),
            config=self._retry_config,
            logger=self._logger,
            operation_name="device_capacity",
        )

    def _new_zk(self) -> Any:
        factory = self._zk_factory
        if factory is None:
            try:
                from zk import ZK
            except ImportError as exc:
                raise DeviceReadError("pyzk is not installed") from exc
            factory = ZK
        return factory(
            self._config.ip,
            port=self._config.port,
            timeout=self._config.timeout_seconds,
            password=self._config.password,
            force_udp=False,
            ommit_ping=False,
        )

    def _read_once(self) -> DeviceSnapshot:
        zk = self._new_zk()
        connection = None
        try:
            connection = zk.connect()
            users = connection.get_users()
            user_lookup = {str(user.user_id): user.name for user in users}
            attendance = connection.get_attendance()
            serial = self._read_serial(connection)
            punches = tuple(
                self._convert_punch(item, user_lookup) for item in attendance
            )
            log_fields(
                self._logger,
                logging.INFO,
                "device_snapshot_read",
                records=len(punches),
                users=len(users),
            )
            return DeviceSnapshot(
                punches=punches,
                user_count=len(users),
                device_serial=serial,
                users=tuple(
                    DeviceUser(str(user.user_id), user.name or None)
                    for user in users
                ),
            )
        except Exception as exc:
            raise DeviceReadError(f"Could not read device snapshot: {exc}") from exc
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    self._logger.warning("device_disconnect_failed", exc_info=True)

    def _read_capacity_once(self) -> CapacitySnapshot:
        connection = None
        try:
            connection = self._new_zk().connect()
            attendance = connection.get_attendance()
            users = connection.get_users()
            try:
                connection.read_sizes()
                return CapacitySnapshot(
                    attendance_count=len(attendance),
                    user_count=len(users),
                    attendance_capacity=getattr(connection, "rec_cap", None),
                    device_reported_attendance_count=getattr(
                        connection, "records", None
                    ),
                    user_capacity=getattr(connection, "users_cap", None),
                    fingerprint_count=getattr(connection, "fingers", None),
                    fingerprint_capacity=getattr(connection, "fingers_cap", None),
                )
            except Exception:
                return CapacitySnapshot(
                    attendance_count=len(attendance),
                    user_count=len(users),
                    attendance_capacity=None,
                    device_reported_attendance_count=None,
                    user_capacity=None,
                    fingerprint_count=None,
                    fingerprint_capacity=None,
                )
        except Exception as exc:
            raise DeviceReadError(f"Could not read device capacity: {exc}") from exc
        finally:
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    self._logger.warning("device_disconnect_failed", exc_info=True)

    @staticmethod
    def _read_serial(connection: Any) -> str | None:
        try:
            value = connection.get_serialnumber()
        except Exception:
            return None
        return str(value) if value is not None else None

    @staticmethod
    def _convert_punch(item: Any, users: dict[str, Any]) -> DevicePunch:
        timestamp = item.timestamp
        if not isinstance(timestamp, datetime):
            raise DeviceReadError(
                f"Device returned a non-datetime attendance timestamp: {timestamp!r}"
            )
        employee_id = str(item.user_id)
        status = getattr(item, "status", None)
        punch = getattr(item, "punch", None)
        # pyzk's Attendance.uid is documented in the installed library as a
        # legacy field, not a reliable per-event identifier. Do not use it.
        return DevicePunch(
            employee_id=employee_id,
            original_device_timestamp=timestamp.replace(tzinfo=None),
            status_raw=None if status is None else str(status),
            punch_raw=None if punch is None else str(punch),
            vendor_event_id=None,
            employee_name=users.get(employee_id),
            raw_payload={
                "employee_id": employee_id,
                "timestamp": timestamp.isoformat(),
                "status": status,
                "punch": punch,
            },
        )
