"""Regression: surface raw Anthropic error body when tenacity wraps it (Phase 7 Task I4).

Bug class: during the 2026-04-11 → 2026-04-19 credit outage, every LLM call
failed but the logs only said "Unexpected error: RetryError[...]" — the useful
body ("credit balance too low") was buried inside the wrapped exception and
never reached the log. This locked us into 8 days of failure-state before
we diagnosed it.

The fix at client.py:452 unwraps `e.last_attempt.exception()` and reads the
underlying `.body` attribute (Anthropic SDK) or `.response.text` fallback.
"""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from tenacity import RetryError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import JarvisLLMClient  # noqa: E402


class _FakeBadRequest(Exception):
    """Mimics anthropic.BadRequestError — exposes a `.body` attribute."""

    def __init__(self, message: str, body: dict):
        super().__init__(message)
        self.body = body


class _FakeStatusError(Exception):
    """Mimics an exception whose body lives in response.text (fallback path)."""

    def __init__(self, message: str, response_text: str):
        super().__init__(message)

        class _Resp:
            text = response_text

        self.response = _Resp()


def _build_retry_error(underlying: Exception) -> RetryError:
    """Construct a tenacity.RetryError the way tenacity builds it internally."""
    # tenacity.RetryError takes a "last_attempt" that has .exception() -> the underlying error
    class _FakeAttempt:
        def exception(self_inner):
            return underlying

    err = RetryError(_FakeAttempt())
    # Ensure e.last_attempt is reachable exactly as tenacity exposes it
    err.last_attempt = _FakeAttempt()
    return err


@pytest.fixture
def llm_client(tmp_path: Path):
    client = JarvisLLMClient(api_key="test-key", db_path=str(tmp_path / "costs.db"))
    yield client


@pytest.mark.asyncio
async def test_error_surfacing_unwraps_body_from_retry_error(llm_client, caplog):
    """When _call_with_retry raises a RetryError wrapping a BadRequestError with
    a `body`, the body dict must appear in the logs (not just "RetryError[...]")."""
    body = {"error": {"type": "invalid_request_error", "message": "credit balance too low"}}
    underlying = _FakeBadRequest("400 Bad Request", body=body)
    wrapped = _build_retry_error(underlying)

    # Patch _call_with_retry to raise the wrapped error (simulates tenacity bubbling up)
    llm_client._call_with_retry = AsyncMock(side_effect=wrapped)
    # Force no fallback — we want the exception to reach the terminal except block
    llm_client._try_fallback = AsyncMock(return_value=None)

    caplog.set_level(logging.ERROR, logger="llm.client")

    await llm_client.call(
        model="claude-opus-4-7",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        agent_name="test_agent",
        allow_fallback=False,
    )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "credit balance too low" in combined, (
        f"Expected body text in logs but got:\n{combined}"
    )
    assert "_FakeBadRequest" in combined, (
        f"Expected underlying type name in logs but got:\n{combined}"
    )
    assert "final failure" in combined, (
        f"Expected 'final failure' marker but got:\n{combined}"
    )


@pytest.mark.asyncio
async def test_error_surfacing_falls_back_to_response_text(llm_client, caplog):
    """If the underlying error has no `.body` but has `.response.text`, that
    text should be logged instead (Anthropic HTTPStatusError shape)."""
    underlying = _FakeStatusError(
        "500 Internal Server Error",
        response_text="upstream_error: connection reset",
    )
    wrapped = _build_retry_error(underlying)

    llm_client._call_with_retry = AsyncMock(side_effect=wrapped)
    llm_client._try_fallback = AsyncMock(return_value=None)

    caplog.set_level(logging.ERROR, logger="llm.client")

    await llm_client.call(
        model="claude-opus-4-7",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        agent_name="test_agent",
        allow_fallback=False,
    )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "upstream_error: connection reset" in combined, (
        f"Expected response.text in logs but got:\n{combined}"
    )


@pytest.mark.asyncio
async def test_error_surfacing_generic_exception_unchanged(llm_client, caplog):
    """Exceptions without `.last_attempt` should log via the original path —
    no regression of the generic handler."""
    bare = RuntimeError("bare error, no retry wrapping")

    llm_client._call_with_retry = AsyncMock(side_effect=bare)
    llm_client._try_fallback = AsyncMock(return_value=None)

    caplog.set_level(logging.ERROR, logger="llm.client")

    await llm_client.call(
        model="claude-opus-4-7",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        agent_name="test_agent",
        allow_fallback=False,
    )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "Unexpected error for test_agent" in combined, (
        f"Expected generic handler output but got:\n{combined}"
    )
    assert "bare error, no retry wrapping" in combined


@pytest.mark.asyncio
async def test_error_surfacing_unwrap_failure_is_swallowed(llm_client, caplog):
    """If unwrapping itself raises (malformed last_attempt), we must fall back
    to the generic log line, not crash."""

    class _BrokenAttempt:
        def exception(self_inner):
            raise ValueError("unwrap exploded")

    wrapped = RetryError(_BrokenAttempt())
    wrapped.last_attempt = _BrokenAttempt()

    llm_client._call_with_retry = AsyncMock(side_effect=wrapped)
    llm_client._try_fallback = AsyncMock(return_value=None)

    caplog.set_level(logging.ERROR, logger="llm.client")

    # Must not raise
    await llm_client.call(
        model="claude-opus-4-7",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        agent_name="test_agent",
        allow_fallback=False,
    )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "Unexpected error for test_agent" in combined, (
        f"Expected fallback log line but got:\n{combined}"
    )
