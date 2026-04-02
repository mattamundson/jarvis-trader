"""
JARVIS TRADER — Rate Limiting
==============================
slowapi-based rate limiting with graduated limits per endpoint.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger("jarvis_trader.rate_limit")

# Initialize limiter with get_remote_address key function
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],  # Default: 60 requests per minute
    storage_uri="memory://",  # limits>=5 expects URI scheme (was "memory")
)


def get_limiter() -> Limiter:
    """Return the configured limiter instance."""
    return limiter


async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom exception handler for rate limit exceeded.
    Returns 429 with JSON detail instead of HTML.
    """
    logger.warning(f"Rate limit exceeded for {request.client.host} on {request.url.path}")
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "status": 429,
        },
    )
