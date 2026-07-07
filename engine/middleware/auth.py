"""
JARVIS TRADER — API Key Authentication
========================================
FastAPI dependency for X-API-Key header validation.
Health, docs, and OpenAPI endpoints are exempt from authentication.
"""

import hmac
import logging
from typing import Annotated, Optional

from fastapi import Header, HTTPException, Request, status

from config import settings

logger = logging.getLogger("jarvis_trader.auth")

# List of exempt paths (no authentication required)
EXEMPT_PATHS = {
    "/health",
    "/health/full",
    "/health/llm",
    "/health/watchdog",
    "/health/pm2",
    "/health/apis",
    "/docs",
    "/openapi.json",
    "/redoc",
    # Prometheus exposition — read-only metrics, loopback-bound. Scraped keyless
    # so the Prometheus container needs no engine API key. The ASGI mount
    # 307-redirects /metrics -> /metrics/, so BOTH forms must be exempt or the
    # scrape lands on /metrics/ and gets 401. See monitoring.metrics.
    "/metrics",
    "/metrics/",
}


async def verify_api_key(
    request: Request,
    x_api_key: Annotated[Optional[str], Header()] = None,
) -> str:
    """
    FastAPI dependency to verify X-API-Key header.

    Returns the validated API key on success.
    Raises HTTPException(401) if invalid or missing.

    Args:
        request: FastAPI Request object (scope path extracted)
        x_api_key: Value of X-API-Key header (None if missing)

    Returns:
        The valid API key string

    Raises:
        HTTPException(401): If API key is invalid or missing
    """
    # Extract path from request scope
    path = request.url.path

    # Skip auth for exempt endpoints
    if path in EXEMPT_PATHS or path.startswith("/openapi"):
        return x_api_key or "exempt"

    # Require API key for all other endpoints
    if not x_api_key:
        logger.warning(f"Missing X-API-Key header for path: {path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate API key using constant-time comparison (prevent timing attacks)
    if not hmac.compare_digest(x_api_key, settings.API_KEY):
        logger.warning(f"Invalid X-API-Key attempt for path: {path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(f"Valid API key for path: {path}")
    return x_api_key
