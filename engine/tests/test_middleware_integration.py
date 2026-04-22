"""
Test middleware stack integration: exception handler + API key enforcement.
=====================================================================
Tests the behavior of GlobalExceptionHandler and APIKeyMiddleware
working together in the middleware pipeline.

NOTE: This test file does NOT use conftest.py to avoid conftest's import
of the broken agents.news_analyst module. Instead, we set env vars directly.
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Set env BEFORE any imports to avoid config errors
test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from middleware.api_key_middleware import APIKeyMiddleware
from middleware.exception_handler import GlobalExceptionHandler

logger = logging.getLogger(__name__)


@pytest.fixture
def test_app():
    """FastAPI app with both middlewares and test routes."""
    app = FastAPI()

    # Middleware registration order matches engine/main.py
    app.add_middleware(GlobalExceptionHandler)
    app.add_middleware(APIKeyMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/test/unhandled")
    async def unhandled_exception():
        """Route that raises an unhandled exception."""
        raise ValueError("Test unhandled exception")

    @app.get("/test/http-exception")
    async def http_exception_route():
        """Route that raises HTTPException (caught by FastAPI)."""
        raise HTTPException(status_code=400, detail="Bad request")

    @app.get("/test/try-except")
    async def try_except_route():
        """Route with its own try/except."""
        try:
            raise ValueError("Caught internally")
        except ValueError:
            return {"error": "Custom error message"}

    return app


@pytest.fixture
def client(test_app):
    """TestClient for the test app."""
    return TestClient(test_app)


class TestExceptionHandler:
    """GlobalExceptionHandler tests."""

    def test_unhandled_exception_returns_json_500(self, client):
        """Unhandled exception should return clean JSON 500."""
        response = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"] == "Internal server error"

    def test_exception_includes_request_id(self, client):
        """Response should include request_id field."""
        response = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        data = response.json()
        assert "request_id" in data
        assert isinstance(data["request_id"], str)
        assert len(data["request_id"]) > 0

    def test_request_ids_are_unique(self, client):
        """Different requests should get different request_ids."""
        response1 = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        response2 = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        id1 = response1.json()["request_id"]
        id2 = response2.json()["request_id"]
        assert id1 != id2

    def test_response_content_type_is_json(self, client):
        """Response Content-Type should be application/json."""
        response = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.headers["content-type"] == "application/json"

    def test_no_traceback_in_response_body(self, client):
        """Response body should not contain traceback or file paths."""
        response = client.get(
            "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        body = response.text
        assert "Traceback" not in body
        assert ".py" not in body
        assert "File " not in body

    def test_health_route_no_error(self, client):
        """Successful route should pass through without error."""
        response = client.get(
            "/health", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAPIKeyMiddleware:
    """APIKeyMiddleware tests."""

    def test_missing_api_key_returns_401(self, client):
        """Missing X-API-Key should return 401."""
        response = client.get("/test/unhandled")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_invalid_api_key_returns_401(self, client):
        """Invalid X-API-Key should return 401."""
        response = client.get("/test/unhandled", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401

    def test_valid_api_key_passes_through(self, client):
        """Valid X-API-Key should allow request through."""
        response = client.get(
            "/health", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 200

    def test_api_key_case_insensitive(self, client):
        """X-API-Key header should be case-insensitive."""
        response = client.get(
            "/health", headers={"x-api-key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 200


class TestMiddlewareIntegration:
    """Integration tests for both middlewares together."""

    def test_api_key_rejects_before_exception_handler(self, client):
        """API key check should happen before exception handler."""
        # Unhandled exception route without API key
        response = client.get("/test/unhandled")
        # Should get 401 (API key rejection), not 500 (exception)
        assert response.status_code == 401

    def test_existing_route_try_except_takes_precedence(self, client):
        """Route with try/except should return its own error."""
        response = client.get(
            "/test/try-except", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["error"] == "Custom error message"
        assert "request_id" not in data

    def test_fastapi_http_exception_not_caught_by_handler(self, client):
        """FastAPI HTTPException should be handled by FastAPI, not our handler."""
        response = client.get(
            "/test/http-exception", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_exception_handler_logged_on_unhandled(self, client, caplog):
        """Unhandled exception should be logged."""
        with caplog.at_level(logging.ERROR):
            response = client.get(
                "/test/unhandled", headers={"X-API-Key": os.environ.get("API_KEY", "test-key")}
            )
        assert response.status_code == 500
        # Log should contain exception details
        assert any("Unhandled exception" in record.message for record in caplog.records)
