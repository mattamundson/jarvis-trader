"""
Global X-API-Key enforcement for all non-exempt paths.
"""

from __future__ import annotations

import hmac
import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from config import settings
from middleware.auth import EXEMPT_PATHS

logger = logging.getLogger("jarvis_trader.auth_mw")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key except for health, docs, and OpenAPI."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith("/openapi"):
            return await call_next(request)

        x_api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
        if not x_api_key:
            logger.warning("Missing X-API-Key for path: %s", path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(x_api_key, settings.API_KEY):
            logger.warning("Invalid X-API-Key attempt for path: %s", path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
