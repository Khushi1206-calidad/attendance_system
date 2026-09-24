"""Environment-based configuration with strict validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required configuration is absent or invalid."""


def load_environment(env_file: str | None = None) -> None:
    """Load an optional dotenv file without overriding process environment."""
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            raise ConfigurationError(f"Environment file does not exist: {path}")
        load_dotenv(path, override=False)
    else:
        load_dotenv(override=False)


def _required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"Required environment variable is missing: {name}")
    return value.strip()


def _integer(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        return cls(url=_required("ATTENDANCE_DATABASE_URL"))


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    ip: str
    port: int
    password: int
    timeout_seconds: int
    timezone_name: str

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(
                f"Unknown ATTENDANCE_DEVICE_TIMEZONE: {self.timezone_name}"
            ) from exc

    @classmethod
    def from_environment(cls) -> "DeviceConfig":
        config = cls(
            ip=_required("ATTENDANCE_DEVICE_IP"),
            port=_integer("ATTENDANCE_DEVICE_PORT", 4370, minimum=1),
            password=_integer("ATTENDANCE_DEVICE_PASSWORD", 0),
            timeout_seconds=_integer(
                "ATTENDANCE_DEVICE_TIMEOUT_SECONDS", 10, minimum=1
            ),
            timezone_name=_required("ATTENDANCE_DEVICE_TIMEZONE"),
        )
        config.timezone
        return config


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int
    initial_seconds: float
    max_seconds: float

    @classmethod
    def from_environment(cls) -> "RetryConfig":
        config = cls(
            max_attempts=_integer("ATTENDANCE_MAX_ATTEMPTS", 3, minimum=1),
            initial_seconds=_float(
                "ATTENDANCE_RETRY_INITIAL_SECONDS", 1.0, minimum=0.0
            ),
            max_seconds=_float(
                "ATTENDANCE_RETRY_MAX_SECONDS", 10.0, minimum=0.0
            ),
        )
        if config.max_seconds < config.initial_seconds:
            raise ConfigurationError(
                "ATTENDANCE_RETRY_MAX_SECONDS must be greater than or equal to "
                "ATTENDANCE_RETRY_INITIAL_SECONDS"
            )
        return config


@dataclass(frozen=True, slots=True)
class SyncConfig:
    database: DatabaseConfig
    device: DeviceConfig
    retry: RetryConfig
    source_key: str
    source_name: str | None
    minimum_valid_timestamp: datetime
    max_future_seconds: int
    batch_size: int

    @classmethod
    def from_environment(cls) -> "SyncConfig":
        raw_minimum = _required("ATTENDANCE_MIN_VALID_TIMESTAMP")
        try:
            minimum = datetime.fromisoformat(raw_minimum)
        except ValueError as exc:
            raise ConfigurationError(
                "ATTENDANCE_MIN_VALID_TIMESTAMP must be an ISO-8601 local datetime"
            ) from exc
        if minimum.tzinfo is not None:
            raise ConfigurationError(
                "ATTENDANCE_MIN_VALID_TIMESTAMP must not include a timezone"
            )
        return cls(
            database=DatabaseConfig.from_environment(),
            device=DeviceConfig.from_environment(),
            retry=RetryConfig.from_environment(),
            source_key=_required("ATTENDANCE_SOURCE_KEY"),
            source_name=os.getenv("ATTENDANCE_SOURCE_NAME") or None,
            minimum_valid_timestamp=minimum,
            max_future_seconds=_integer(
                "ATTENDANCE_MAX_FUTURE_SECONDS", 86400, minimum=0
            ),
            batch_size=_integer("ATTENDANCE_BATCH_SIZE", 1000, minimum=1),
        )


@dataclass(frozen=True, slots=True)
class ApiConfig:
    database: DatabaseConfig
    source_key: str
    device_timezone_name: str
    unreasonable_span_seconds: int
    host: str
    port: int
    pool_min_size: int
    pool_max_size: int

    @property
    def device_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.device_timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(
                f"Unknown ATTENDANCE_DEVICE_TIMEZONE: {self.device_timezone_name}"
            ) from exc

    @classmethod
    def from_environment(cls) -> "ApiConfig":
        config = cls(
            database=DatabaseConfig.from_environment(),
            source_key=_required("ATTENDANCE_SOURCE_KEY"),
            device_timezone_name=_required("ATTENDANCE_DEVICE_TIMEZONE"),
            unreasonable_span_seconds=_integer(
                "ATTENDANCE_UNREASONABLE_SPAN_SECONDS", 64800, minimum=1
            ),
            host=os.getenv("ATTENDANCE_API_HOST", "127.0.0.1"),
            port=_integer("ATTENDANCE_API_PORT", 8000, minimum=1),
            pool_min_size=_integer(
                "ATTENDANCE_API_DB_POOL_MIN_SIZE", 1, minimum=1
            ),
            pool_max_size=_integer(
                "ATTENDANCE_API_DB_POOL_MAX_SIZE", 5, minimum=1
            ),
        )
        if config.port > 65535:
            raise ConfigurationError("ATTENDANCE_API_PORT must be at most 65535")
        if config.pool_max_size < config.pool_min_size:
            raise ConfigurationError(
                "ATTENDANCE_API_DB_POOL_MAX_SIZE must be greater than or equal "
                "to ATTENDANCE_API_DB_POOL_MIN_SIZE"
            )
        config.device_timezone
        return config
