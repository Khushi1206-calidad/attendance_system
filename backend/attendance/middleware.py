"""Request logging and correlation IDs for the Django API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from uuid import uuid4

from django.http import HttpRequest, HttpResponse

from attendance.services.logging_config import log_fields

LOGGER = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        started = time.monotonic()
        response = self.get_response(request)
        match = getattr(request, "resolver_match", None)
        log_fields(
            LOGGER,
            logging.INFO,
            "http_request_completed",
            request_id=request_id,
            method=request.method,
            route="/" + match.route if match else "unmatched",
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        response["x-request-id"] = request_id
        return response
