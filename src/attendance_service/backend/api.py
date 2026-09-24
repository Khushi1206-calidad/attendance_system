"""Minimal read-only FastAPI application and HTML interface."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from datetime import UTC, date
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import psycopg
from fastapi import Depends, FastAPI, Path as ApiPath, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg_pool import ConnectionPool

from attendance_service.backend.api_schemas import (
    EmployeeResponse,
    EmployeeSearchResponse,
    ErrorDetail,
    ErrorResponse,
    PunchResponse,
    WarningResponse,
    WorkHoursResponse,
)
from attendance_service.backend.config import ApiConfig
from attendance_service.backend.logging_config import log_fields
from attendance_service.backend.work_hours import (
    CALCULATION_METHOD,
    DISPLAY_LABEL,
    EmployeeNotFoundError,
    WorkHoursService,
)
from attendance_service.database.read_repository import ReadOnlyAttendanceRepository

LOGGER = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
RepositoryProvider = Callable[
    [], AbstractContextManager[ReadOnlyAttendanceRepository]
]


def _configure_read_only_connection(connection: Any) -> None:
    connection.execute("SET TIME ZONE 'UTC'")
    connection.execute("SET default_transaction_read_only = on")


def _duration_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def get_repository(request: Request) -> Iterator[ReadOnlyAttendanceRepository]:
    provider: RepositoryProvider = request.app.state.repository_provider
    with provider() as repository:
        yield repository


def _service(
    request: Request, repository: ReadOnlyAttendanceRepository
) -> WorkHoursService:
    config: ApiConfig = request.app.state.api_config
    return WorkHoursService(
        repository,
        source_key=config.source_key,
        device_timezone=config.device_timezone,
        unreasonable_span_seconds=config.unreasonable_span_seconds,
    )


def create_app(
    config: ApiConfig | None = None,
    *,
    repository_provider: RepositoryProvider | None = None,
) -> FastAPI:
    api_config = config or ApiConfig.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool: ConnectionPool[Any] | None = None
        if repository_provider is None:
            pool = ConnectionPool(
                conninfo=api_config.database.url,
                min_size=api_config.pool_min_size,
                max_size=api_config.pool_max_size,
                open=False,
                kwargs={"autocommit": True},
                configure=_configure_read_only_connection,
                name="attendance-read-api",
            )
            pool.open(wait=True)

            @contextmanager
            def pooled_repository() -> Iterator[ReadOnlyAttendanceRepository]:
                assert pool is not None
                with pool.connection() as connection:
                    yield ReadOnlyAttendanceRepository(connection)

            app.state.repository_provider = pooled_repository
        else:
            app.state.repository_provider = repository_provider
        try:
            yield
        finally:
            if pool is not None:
                pool.close()

    app = FastAPI(
        title="Attendance API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.api_config = api_config
    templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR / "static")),
        name="static",
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next: Callable[..., Any]):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        log_fields(
            LOGGER,
            logging.INFO,
            "http_request_completed",
            request_id=request_id,
            method=request.method,
            route=route_path,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error(422, "invalid_request", "The request parameters are invalid.")

    @app.exception_handler(psycopg.Error)
    async def database_error_handler(
        _request: Request, exc: psycopg.Error
    ) -> JSONResponse:
        LOGGER.error("attendance_read_database_error", exc_info=exc)
        return _error(503, "database_unavailable", "Attendance data is unavailable.")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        LOGGER.error("attendance_api_unexpected_error", exc_info=exc)
        return _error(500, "internal_error", "The request could not be completed.")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"source_key": api_config.source_key},
        )

    @app.get(
        "/api/v1/employees",
        response_model=EmployeeSearchResponse,
        responses={422: {"model": ErrorResponse}},
    )
    def search_employees(
        request: Request,
        repository: Annotated[
            ReadOnlyAttendanceRepository, Depends(get_repository)
        ],
        query: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> EmployeeSearchResponse | JSONResponse:
        normalized = query.strip()
        if not normalized:
            return _error(422, "invalid_query", "Search text cannot be blank.")
        employees = _service(request, repository).search_employees(normalized)
        warnings: list[WarningResponse] = []
        if len(employees) > 1:
            warnings.append(
                WarningResponse(
                    code="multiple_matches",
                    message="Multiple employees matched. Select using employee ID.",
                )
            )
        return EmployeeSearchResponse(
            source_key=api_config.source_key,
            query=normalized,
            count=len(employees),
            employees=[
                EmployeeResponse(employee_id=item.employee_id, name=item.name)
                for item in employees
            ],
            warnings=warnings,
        )

    @app.get(
        "/api/v1/employees/{employee_id}/work-hours",
        response_model=WorkHoursResponse,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def employee_work_hours(
        request: Request,
        repository: Annotated[
            ReadOnlyAttendanceRepository, Depends(get_repository)
        ],
        employee_id: Annotated[str, ApiPath(min_length=1, max_length=100)],
        selected_date: Annotated[date, Query(alias="date")],
    ) -> WorkHoursResponse | JSONResponse:
        try:
            result = _service(request, repository).calculate(
                employee_id, selected_date
            )
        except EmployeeNotFoundError:
            return _error(
                404,
                "employee_not_found",
                "No employee exists for this source and employee ID.",
            )

        timezone = api_config.device_timezone
        return WorkHoursResponse(
            source_key=result.source_key,
            employee_id=result.employee.employee_id,
            name=result.employee.name,
            date=result.selected_date,
            timezone=result.timezone_name,
            punches=[
                PunchResponse(
                    original_device_timestamp=punch.original_device_timestamp,
                    timestamp_local=punch.occurred_at_utc.astimezone(timezone),
                    timestamp_utc=punch.occurred_at_utc.astimezone(UTC),
                    status_raw=punch.status_raw,
                    punch_raw=punch.punch_raw,
                )
                for punch in result.punches
            ],
            punch_count=len(result.punches),
            first_punch=(
                result.first_punch.astimezone(timezone)
                if result.first_punch is not None
                else None
            ),
            last_punch=(
                result.last_punch.astimezone(timezone)
                if result.last_punch is not None
                else None
            ),
            calculation_method=CALCULATION_METHOD,
            calculation_label=DISPLAY_LABEL,
            calculated_duration_seconds=result.duration_seconds,
            calculated_duration=_duration_label(result.duration_seconds),
            breaks_excluded=False,
            warnings=[
                WarningResponse(code=warning.code, message=warning.message)
                for warning in result.warnings
            ],
        )

    return app
