"""
JARVIS TRADER Middleware Setup
===============================
FastAPI middleware registration: CORS, rate limiting, exception handling, API keys.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from middleware.api_key_middleware import APIKeyMiddleware
from middleware.exception_handler import GlobalExceptionHandler
from middleware.rate_limit import get_limiter, rate_limit_exception_handler


def setup_middleware(app: FastAPI) -> None:
    """Register all middleware in correct order (reverse registration order)."""

    # Exception handler (outermost)
    app.add_middleware(GlobalExceptionHandler)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3010",
            "http://localhost:3000",
            "http://localhost:3004",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API Key authentication
    app.add_middleware(APIKeyMiddleware)

    # Rate limiting
    app.state.limiter = get_limiter()
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
