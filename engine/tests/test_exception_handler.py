"""
JARVIS TRADER — Global Exception Handler Middleware Tests
===========================================================
Test suite for the GlobalExceptionHandler middleware.

Verifies that unhandled exceptions are caught and return clean JSON 500s
with request_id, never leaking Python traceback details.

Run with: pytest tests/test_exception_handler.py -v
"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Add parent directory to path so we can import middleware
sys.path.insert(0, str(Path(__file__).parent.parent))

from middleware.exception_handler import GlobalExceptionHandler


class TestGlobalExceptionHandler:
    """Test suite for GlobalExceptionHandler middleware."""

    def test_unhandled_exception_returns_clean_json_500(self):
        """
        Test that an unhandled exception returns a clean JSON 500 response.

        The response should contain:
        - status_code: 500
        - content: {error: "Internal server error", request_id: "xxxxxxxx"}
        """
        # Create a minimal app with just the exception handler to test it directly
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/error")
        async def error_endpoint():
            raise ValueError("This is a test error")

        test_client = TestClient(test_app)
        response = test_client.get("/error")

        # Verify status code is 500
        assert response.status_code == 500

        # Verify response is JSON
        assert response.headers["content-type"].startswith("application/json")

        # Verify response body has expected structure
        data = response.json()
        assert "error" in data
        assert data["error"] == "Internal server error"
        assert "request_id" in data

        # Verify request_id is 8 characters (short UUID)
        assert isinstance(data["request_id"], str)
        assert len(data["request_id"]) == 8

    def test_exception_response_does_not_contain_traceback(self):
        """
        Test that the response body never contains Python traceback text.

        This is a critical security requirement — responses should never
        leak implementation details.
        """
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/error")
        async def error_endpoint():
            raise RuntimeError("Sensitive implementation error message")

        test_client = TestClient(test_app)
        response = test_client.get("/error")

        # Get response body as text
        response_text = response.text

        # Verify common traceback patterns are NOT present
        assert "Traceback" not in response_text
        assert 'File "' not in response_text
        assert "line " not in response_text
        assert "RuntimeError" not in response_text
        assert "Sensitive implementation error message" not in response_text

    def test_successful_request_passes_through(self):
        """
        Test that successful requests pass through the middleware unchanged.

        The exception handler should not modify successful responses.
        """
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/success")
        async def success_endpoint():
            return {"status": "ok"}

        test_client = TestClient(test_app)
        response = test_client.get("/success")

        # Verify successful request is unmodified
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_different_exception_types(self):
        """
        Test that different exception types are all handled consistently.

        All unhandled exceptions should return the same clean JSON format.
        """
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/type_error")
        async def type_error_endpoint():
            raise TypeError("Invalid type")

        @test_app.get("/key_error")
        async def key_error_endpoint():
            raise KeyError("Missing key")

        @test_app.get("/custom_error")
        async def custom_error_endpoint():
            class CustomException(Exception):
                pass

            raise CustomException("Custom error")

        test_client = TestClient(test_app)

        # Test TypeError
        response = test_client.get("/type_error")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Internal server error"
        assert "request_id" in data

        # Test KeyError
        response = test_client.get("/key_error")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Internal server error"
        assert "request_id" in data

        # Test custom exception
        response = test_client.get("/custom_error")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Internal server error"
        assert "request_id" in data

    def test_each_error_has_unique_request_id(self):
        """
        Test that each error gets a unique request_id.

        This helps correlate client errors with server logs.
        """
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/error")
        async def error_endpoint():
            raise RuntimeError("Test error")

        test_client = TestClient(test_app)

        # Make multiple requests and collect request_ids
        request_ids = set()
        for _ in range(5):
            response = test_client.get("/error")
            data = response.json()
            request_ids.add(data["request_id"])

        # Verify all request_ids are unique
        assert len(request_ids) == 5

    def test_existing_try_except_in_routes_still_work(self):
        """
        Test that the exception handler is a last resort — existing try/except
        blocks in routes still work and return their custom responses.

        The exception handler should only catch truly unhandled exceptions.
        """
        test_app = FastAPI()
        test_app.add_middleware(GlobalExceptionHandler)

        @test_app.get("/custom_error_handler")
        async def custom_error_handler():
            try:
                raise ValueError("Some error")
            except ValueError:
                return {"status": "handled_by_route", "error": "ValueError caught"}

        test_client = TestClient(test_app)
        response = test_client.get("/custom_error_handler")

        # Verify the route's custom error handling works
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "handled_by_route"
        assert data["error"] == "ValueError caught"
