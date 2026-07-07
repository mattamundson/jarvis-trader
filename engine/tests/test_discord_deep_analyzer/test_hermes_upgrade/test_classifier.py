"""Unit tests for engine/discord/hermes_upgrade/classifier.py.

We mock the JarvisLLMClient so these tests are fast, deterministic, and
do not touch the live Anthropic / Gemini API.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest

from discord.hermes_upgrade.classifier import (
    _coerce_payload,
    _strip_code_fences,
    classify_batch,
    classify_one,
)
from discord.hermes_upgrade.models import Candidate, ClassifiedUpgrade

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(**overrides: Any) -> Candidate:
    defaults: dict[str, Any] = {
        "bookmark_id": "m-test",
        "analysis_id": 1,
        "url": "https://github.com/x/y",
        "summary": "A great Hermes MCP server.",
        "structured_json": "{}",
        "topics": ["agent", "mcp-server"],
        "has_action_item": True,
        "source_kind": "github",
        "artifact_type": "url",
        "posted_at": "2026-05-20T00:00:00Z",
        "score": 0.85,
    }
    defaults.update(overrides)
    return Candidate(**defaults)


def _llm_result(text: str, success: bool = True) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like LLMCallResult."""
    return SimpleNamespace(
        success=success,
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0001,
        latency_ms=200,
        retries=0,
        content=text,
        error=None if success else "boom",
    )


class _FakeClient:
    """Mock JarvisLLMClient — records calls, returns a scripted reply."""

    def __init__(self, reply_text: str, *, success: bool = True, delay_s: float = 0.0):
        self.reply_text = reply_text
        self.success = success
        self.delay_s = delay_s
        self.calls: list[dict[str, Any]] = []

    async def call(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return _llm_result(self.reply_text, success=self.success)


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------


def test_strip_code_fences_plain_passthrough():
    s = '{"applicable": true}'
    assert _strip_code_fences(s) == s


def test_strip_code_fences_json_wrapper():
    raw = '```json\n{"applicable": true}\n```'
    assert _strip_code_fences(raw) == '{"applicable": true}'


def test_strip_code_fences_bare_triple_backticks():
    raw = '```\n{"applicable": true}\n```'
    assert _strip_code_fences(raw) == '{"applicable": true}'


def test_strip_code_fences_empty_input():
    assert _strip_code_fences("") == ""


# ---------------------------------------------------------------------------
# _coerce_payload
# ---------------------------------------------------------------------------


def test_coerce_payload_drops_unknown_keys():
    candidate = _make_candidate()
    data = {
        "applicable": True,
        "upgrade_type": "skill",
        "title": "Install hermes-mcp-server",
        "rationale": "Adds agent orchestration.",
        "leverage_rank": 4,
        "risk": "low",
        "estimated_cost_usd": 0,
        "unknown_field": "ignored",
        "bookmark_id": "spoofed",  # must be overridden with candidate.bookmark_id
    }
    upgrade = _coerce_payload(data, candidate)
    assert upgrade.bookmark_id == "m-test"
    assert upgrade.applicable is True
    assert upgrade.upgrade_type == "skill"
    assert upgrade.leverage_rank == 4
    assert upgrade.risk == "low"


def test_coerce_payload_non_dict_raises():
    with pytest.raises(ValueError):
        _coerce_payload(["not", "a", "dict"], _make_candidate())


# ---------------------------------------------------------------------------
# classify_one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_one_plain_json_reply():
    payload = {
        "applicable": True,
        "upgrade_type": "mcp_server",
        "title": "browser-use MCP server",
        "rationale": "Lets Hermes drive a real browser.",
        "implementation_steps": ["pip install browser-use", "wire into ~/.hermes/config.yaml"],
        "leverage_rank": 5,
        "risk": "med",
        "dependencies": ["chromium"],
        "estimated_cost_usd": 0,
        "extracted_content": "browser-use turns any LLM into a browser agent",
        "notes": "needs amo to add API key",
    }
    client = _FakeClient(json.dumps(payload))
    upgrade = await classify_one(client, _make_candidate(bookmark_id="m-1"))
    assert isinstance(upgrade, ClassifiedUpgrade)
    assert upgrade.bookmark_id == "m-1"
    assert upgrade.applicable is True
    assert upgrade.upgrade_type == "mcp_server"
    assert upgrade.leverage_rank == 5
    assert upgrade.risk == "med"
    assert upgrade.dependencies == ["chromium"]
    # Confirm the LLM was called with the expected kwargs shape
    assert len(client.calls) == 1
    kwargs = client.calls[0]
    assert kwargs["agent_name"] == "hermes-upgrade-classifier"
    assert kwargs["model"].startswith("claude-haiku")
    assert isinstance(kwargs["messages"], list)
    assert kwargs["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_classify_one_strips_json_fence():
    payload = {
        "applicable": True,
        "upgrade_type": "skill",
        "title": "fence-wrapped",
        "rationale": "ok",
        "leverage_rank": 1,
        "risk": "low",
        "estimated_cost_usd": 0,
    }
    text = "```json\n" + json.dumps(payload) + "\n```"
    client = _FakeClient(text)
    upgrade = await classify_one(client, _make_candidate())
    assert upgrade.applicable is True
    assert upgrade.upgrade_type == "skill"
    assert upgrade.title == "fence-wrapped"


@pytest.mark.asyncio
async def test_classify_one_malformed_json_returns_error_marker():
    client = _FakeClient("this is not json at all")
    upgrade = await classify_one(client, _make_candidate(bookmark_id="m-bad"))
    assert upgrade.applicable is False
    assert upgrade.upgrade_type == "none"
    assert upgrade.title == "<classifier error>"
    assert upgrade.bookmark_id == "m-bad"
    assert "classifier failed" in upgrade.rationale


@pytest.mark.asyncio
async def test_classify_one_llm_call_failure_returns_error_marker():
    client = _FakeClient("ignored", success=False)
    upgrade = await classify_one(client, _make_candidate(bookmark_id="m-fail"))
    assert upgrade.applicable is False
    assert upgrade.title == "<classifier error>"


@pytest.mark.asyncio
async def test_classify_one_empty_reply_returns_error_marker():
    client = _FakeClient("")
    upgrade = await classify_one(client, _make_candidate())
    assert upgrade.applicable is False
    assert upgrade.upgrade_type == "none"


@pytest.mark.asyncio
async def test_classify_one_non_dict_json_returns_error_marker():
    client = _FakeClient(json.dumps(["not", "a", "dict"]))
    upgrade = await classify_one(client, _make_candidate())
    assert upgrade.applicable is False
    assert upgrade.upgrade_type == "none"


# ---------------------------------------------------------------------------
# classify_batch — concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_batch_empty_returns_empty():
    out = await classify_batch([])
    assert out == []


@pytest.mark.asyncio
async def test_classify_batch_runs_all_with_order_preserved():
    payload = {
        "applicable": True,
        "upgrade_type": "skill",
        "title": "x",
        "rationale": "y",
        "leverage_rank": 2,
        "risk": "low",
        "estimated_cost_usd": 0,
    }
    client = _FakeClient(json.dumps(payload))
    candidates = [_make_candidate(bookmark_id=f"m-{i}") for i in range(5)]
    out = await classify_batch(candidates, concurrency=3, client=client)
    assert [u.bookmark_id for u in out] == [c.bookmark_id for c in candidates]
    assert all(u.applicable for u in out)
    assert len(client.calls) == 5


@pytest.mark.asyncio
async def test_classify_batch_respects_concurrency_limit():
    """With delay=0.05s per call, 10 tasks under concurrency=2 take >= ~0.25s.

    Specifically: 10 tasks in batches of 2 -> 5 sequential batches * 0.05 = 0.25s.
    We only assert a lower bound because real wall-clock varies.
    """
    payload = {
        "applicable": True,
        "upgrade_type": "skill",
        "title": "ok",
        "rationale": "ok",
        "leverage_rank": 1,
        "risk": "low",
        "estimated_cost_usd": 0,
    }
    client = _FakeClient(json.dumps(payload), delay_s=0.05)
    candidates = [_make_candidate(bookmark_id=f"m-{i}") for i in range(10)]
    t0 = time.monotonic()
    out = await classify_batch(candidates, concurrency=2, client=client)
    elapsed = time.monotonic() - t0
    assert len(out) == 10
    # If concurrency really is 2, total wall-clock >= ceil(10/2) * 0.05 = 0.25s.
    # Allow 20% slack for scheduling overhead on Windows.
    assert elapsed >= 0.20, f"concurrency limit not honored — elapsed={elapsed:.3f}s"
