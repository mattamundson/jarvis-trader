"""
Global Exception Handler Middleware — JARVIS TRADER
=====================================================
Catches unhandled exceptions across all routes and returns clean JSON 500s
with request_id, while logging full tracebacks server-side.

This middleware is registered FIRST in the middleware stack to ensure
all exceptions (including those from route handlers) are caught and
logged consistently.
"""

import logging
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

logger = logging.getLogger("jarvis_trader.exception_handler")


class GlobalExceptionHandler(BaseHTTPMiddleware):
    """
    Catch all unhandled exceptions and return clean JSON 500s with request_id.

    Full traceback is logged server-side. Response body never contains
    Python traceback or implementation details.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        """
        Dispatch the request and catch any unhandled exceptions.

        Args:
            request: The incoming HTTP request
            call_next: Callable to invoke the next middleware/route handler

        Returns:
            Either the response from call_next, or a clean 500 JSON response
            if an exception was raised
        """
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            request_id = str(uuid.uuid4())[:8]
            logger.exception(
                "Unhandled exception [request_id=%s] %s %s: %s",
                request_id,
                request.method,
                request.url.path,
                str(exc),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "request_id": request_id,
                },
            )
