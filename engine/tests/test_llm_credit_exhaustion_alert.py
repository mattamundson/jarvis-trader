"""Regression: credit-exhaustion → WhatsApp alert + /health flag (Phase 7 Task I3).

This locks the two halves of the credit-outage blind-spot fix:
1. Module-level LLM health state flips to unhealthy on credit_balance errors
2. A successful call auto-restores the state to healthy
3. Non-credit errors do NOT flip the state
4. The notifier is fire-and-forget (failure to send does not crash the client)
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tenacity import RetryError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import JarvisLLMClient  # noqa: E402
from llm.client import (  # noqa: E402
    _LLM_PATH_STATE,
    _is_credit_exhaustion,
    get_llm_path_state,
)


class _FakeBadRequest(Exception):
    def __init__(self, message: str, body):
        super().__init__(message)
        self.body = body


def _wrap(underlying: Exception) -> RetryError:
    class _Attempt:
        def exception(_self):
            return underlying

    err = RetryError(_Attempt())
    err.last_attempt = _Attempt()
    return err


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Each test starts with a clean healthy state."""
    _LLM_PATH_STATE["healthy"] = True
    _LLM_PATH_STATE["last_failure_ts"] = None
    _LLM_PATH_STATE["last_failure_reason"] = None
    _LLM_PATH_STATE["last_failure_agent"] = None
    # monkeypatch (not raw os.environ) so this reverts to the conftest.py
    # default after every test -- a raw assignment here previously leaked
    # TESTING="true" into every test file collected after this one for the
    # rest of the session (surfaced by test_openclaw_fire_and_forget.py,
    # which depends on TESTING being unset to exercise its real send path).
    monkeypatch.setenv("TESTING", "true")  # suppress actual WhatsApp send
    yield


# ── _is_credit_exhaustion helper ─────────────────────────────────────────────


def test_is_credit_exhaustion_detects_anthropic_phrasing():
    assert _is_credit_exhaustion("Your credit balance is too low")
    assert _is_credit_exhaustion("CREDIT BALANCE IS TOO LOW")
    assert _is_credit_exhaustion({"error": {"type": "credit_balance_too_low"}})
    assert _is_credit_exhaustion("credit balance too low to run")


def test_is_credit_exhaustion_rejects_unrelated_errors():
    assert not _is_credit_exhaustion("rate_limit_error")
    assert not _is_credit_exhaustion("HTTP 500 Internal Server Error")
    assert not _is_credit_exhaustion(None)
    assert not _is_credit_exhaustion("")
    assert not _is_credit_exhaustion("overloaded_error")


# ── Full client.call() integration — state flips, notifier fires ─────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Hermetic: config.py's load_dotenv(override=True) pulls the LIVE
    # engine/.env into os.environ, and PRB-10 broadened the cross-provider
    # cascade to fire on ANY Anthropic-side failure (not just credit
    # exhaustion). Without clearing these, a live GOOGLE_API_KEY/
    # OPENAI_API_KEY/MOONSHOT_API_KEY would make the cascade attempt REAL
    # network calls instead of the deterministic mocked/unconfigured paths
    # these tests assert on.
    for _k in (
        "JARVIS_DECISION_PRIMARY",
        "MOONSHOT_API_KEY",
        "JARVIS_LLM_KIMI_FALLBACK",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "JARVIS_LLM_GOOGLE_FALLBACK",
        "OPENAI_API_KEY",
        "JARVIS_LLM_OPENAI_FALLBACK",
        "JARVIS_CLAUDE_USE_VERTEX",
        "JARVIS_LLM_VERTEX_FAILOVER",
    ):
        monkeypatch.delenv(_k, raising=False)
    return JarvisLLMClient(api_key="test-key", db_path=str(tmp_path / "c.db"))


@pytest.mark.asyncio
async def test_credit_exhausted_flips_health_state(client):
    """Body containing 'credit balance' flips _LLM_PATH_STATE.healthy = False."""
    body = {"error": {"message": "Your credit balance is too low"}}
    err = _FakeBadRequest("400", body=body)
    wrapped = _wrap(err)

    client._call_with_retry = AsyncMock(side_effect=wrapped)
    client._try_fallback = AsyncMock(return_value=None)
    # Also disable the internal Gemini credit-exhaustion fallback so it can't
    # succeed and auto-clear the health state before the assertions run.
    client._call_google = AsyncMock(side_effect=RuntimeError("Gemini also down"))

    with patch(
        "notifications.openclaw_notifier.notify_credits_exhausted",
        new=AsyncMock(return_value=True),
    ) as mock_notify:
        await client.call(
            model="claude-opus-4-7",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            agent_name="bull_researcher",
            allow_fallback=False,
        )

    state = get_llm_path_state()
    assert state["healthy"] is False
    assert state["last_failure_agent"] == "bull_researcher"
    assert "credit balance" in (state["last_failure_reason"] or "").lower()
    mock_notify.assert_called_once()
    # notifier received the agent name + body
    call_kwargs = mock_notify.call_args.kwargs
    assert call_kwargs.get("agent") == "bull_researcher"
    assert "credit balance" in call_kwargs.get("reason", "").lower()


@pytest.mark.asyncio
async def test_non_credit_error_does_not_send_credit_exhaustion_alert(client):
    """PRB-10: a generic 500 error (no cheaper fallback configured, all
    cross-provider legs unconfigured/exhausted) DOES flip the path unhealthy --
    previously it skipped the cascade entirely and left `healthy` untouched,
    which is the exact bug PRB-10 fixes. What must stay true is the specific
    credit-exhaustion ops alert (notify_credits_exhausted) does NOT fire for a
    non-credit failure, so ops are never told "buy more credits" for a plain
    5xx blip -- that's the "distinct alerting message" requirement."""
    err = _FakeBadRequest("500", body={"error": {"message": "overloaded_error"}})
    wrapped = _wrap(err)

    client._call_with_retry = AsyncMock(side_effect=wrapped)
    client._try_fallback = AsyncMock(return_value=None)

    with patch(
        "notifications.openclaw_notifier.notify_credits_exhausted",
        new=AsyncMock(return_value=True),
    ) as mock_notify:
        await client.call(
            model="claude-opus-4-7",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            agent_name="bear_researcher",
            allow_fallback=False,
        )

    state = get_llm_path_state()
    assert state["healthy"] is False
    assert "non-credit" in (state["last_failure_reason"] or "")
    mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_successful_call_clears_unhealthy_state(client):
    """A success after a failure must flip healthy back to True."""
    _LLM_PATH_STATE["healthy"] = False
    _LLM_PATH_STATE["last_failure_reason"] = "prior failure"

    # Mock a successful API result
    success_result = MagicMock()
    success_result.usage.input_tokens = 10
    success_result.usage.output_tokens = 20
    success_result.content = [MagicMock(text="ok", type="text")]
    success_result.stop_reason = "end_turn"

    client._call_with_retry = AsyncMock(return_value=success_result)

    await client.call(
        model="claude-opus-4-7",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        agent_name="trader",
        allow_fallback=False,
    )

    assert get_llm_path_state()["healthy"] is True


@pytest.mark.asyncio
async def test_notifier_failure_does_not_break_client(client):
    """If the notifier itself raises, the client's failure path must still return."""
    body = "credit balance is too low"
    err = _FakeBadRequest("400", body=body)
    wrapped = _wrap(err)

    client._call_with_retry = AsyncMock(side_effect=wrapped)
    client._try_fallback = AsyncMock(return_value=None)
    # Disable the internal Gemini credit-exhaustion fallback so the unhealthy
    # path is exercised and the state flip happens before the notifier fires.
    client._call_google = AsyncMock(side_effect=RuntimeError("Gemini also down"))

    with patch(
        "notifications.openclaw_notifier.notify_credits_exhausted",
        side_effect=RuntimeError("WhatsApp gateway down"),
    ):
        # Must not raise
        result = await client.call(
            model="claude-opus-4-7",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            agent_name="test",
            allow_fallback=False,
        )
    # Result is the failure fallback object; just assert we got one and
    # the health state still flipped (since log+state happen before notify)
    assert result is not None
    assert get_llm_path_state()["healthy"] is False


# ── notifier dedupe logic ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notifier_dedupes_same_day():
    """Back-to-back credit alerts on the same calendar day send once, then suppress."""
    # Use the real notifier but intercept _send so no subprocess runs
    from notifications import openclaw_notifier as on

    # Reset the module-level dedupe marker
    on._credits_exhausted_last_alert_date = ""
    os.environ.pop("TESTING", None)  # we WANT the real path here (no suppress)

    sent_messages = []

    async def fake_send(msg: str) -> bool:
        sent_messages.append(msg)
        return True

    with patch.object(on, "_send", side_effect=fake_send):
        r1 = await on.notify_credits_exhausted(reason="first", agent="a1")
        r2 = await on.notify_credits_exhausted(reason="second", agent="a2")

    # First send goes through; second suppressed by dedupe
    assert r1 is True
    assert r2 is False
    assert len(sent_messages) == 1
    assert "JARVIS LLM PATH DOWN" in sent_messages[0]
    os.environ["TESTING"] = "true"  # restore for subsequent tests


@pytest.mark.asyncio
async def test_notifier_suppressed_in_testing_mode():
    from notifications import openclaw_notifier as on

    on._credits_exhausted_last_alert_date = ""
    os.environ["TESTING"] = "true"
    result = await on.notify_credits_exhausted(reason="x", agent="y")
    assert result is False
