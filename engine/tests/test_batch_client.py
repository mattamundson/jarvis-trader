"""
Tests for engine/llm/batch_client.py (JarvisBatchClient)

Covers:
  - build_request: custom_id uniqueness across a batch, cache_control wrapping
  - collect_results: out-of-order streamed results bucket correctly by custom_id
  - sweep_pending: stale (>25h) batch is marked stale without a live API call
  - cost: calculate_batch_cost halves the synchronous rate; log_batch_cost logs
    with provider="batch"
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.batch_client import JarvisBatchClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def batch_client():
    with tempfile.TemporaryDirectory() as tmp:
        with patch("anthropic.AsyncAnthropic"):
            client = JarvisBatchClient(api_key="sk-test-dummy", db_path=f"{tmp}/batches.db")
            yield client


class _FakeMessage:
    def __init__(self, text: str, in_tok: int, out_tok: int):
        block = MagicMock()
        block.type = "text"
        block.text = text
        self.content = [block]
        self.usage = MagicMock(input_tokens=in_tok, output_tokens=out_tok)


class _FakeSucceeded:
    type = "succeeded"

    def __init__(self, message):
        self.message = message


class _FakeErrored:
    type = "errored"

    def __init__(self, error):
        self.error = error


class _FakeEntry:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


async def _fake_results_aiter(entries):
    for e in entries:
        yield e


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_build_request_custom_ids_unique_across_batch(batch_client):
    requests = [
        batch_client.build_request(
            custom_id=f"MES-{n}",
            model="claude-haiku-4-5-20251001",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=800,
        )
        for n in range(1, 6)
    ]
    custom_ids = [r["custom_id"] for r in requests]
    assert len(custom_ids) == len(set(custom_ids)), "custom_ids must be unique within a batch"


def test_build_request_no_cache_control_by_default(batch_client):
    req = batch_client.build_request(
        custom_id="c1",
        model="claude-haiku-4-5-20251001",
        system="plain system prompt",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=800,
    )
    assert req["params"]["system"] == "plain system prompt"


def test_build_request_shared_system_cache_wraps_with_ephemeral(batch_client):
    req = batch_client.build_request(
        custom_id="c1",
        model="claude-haiku-4-5-20251001",
        system="shared system prompt",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=800,
        shared_system_cache=True,
    )
    system = req["params"]["system"]
    assert isinstance(system, list)
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "shared system prompt"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# collect_results — out-of-order bucketing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_results_buckets_out_of_order_by_custom_id(batch_client):
    # Results arrive in an order that does NOT match submission order (3, 1, 2).
    entries = [
        _FakeEntry("c3", _FakeSucceeded(_FakeMessage("third", 100, 50))),
        _FakeEntry("c1", _FakeSucceeded(_FakeMessage("first", 200, 75))),
        _FakeEntry("c2", _FakeErrored({"type": "invalid_request"})),
    ]

    async def fake_results(message_batch_id):
        return _fake_results_aiter(entries)

    batch_client.client.messages.batches.results = fake_results

    bucketed = await batch_client.collect_results("batch_xyz")

    assert set(bucketed.keys()) == {"c1", "c2", "c3"}
    assert bucketed["c1"].content == "first"
    assert bucketed["c1"].input_tokens == 200
    assert bucketed["c1"].result_type == "succeeded"
    assert bucketed["c3"].content == "third"
    assert bucketed["c2"].result_type == "errored"
    assert bucketed["c2"].content == ""

    # Persisted to SQLite too, independent of streaming order.
    unconsumed = batch_client.get_unconsumed_results("batch_xyz")
    assert set(unconsumed.keys()) == {"c1", "c2", "c3"}


# ---------------------------------------------------------------------------
# sweep_pending — stale detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_pending_marks_batch_stale_past_grace_period(batch_client):
    old_time = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()

    import sqlite3

    conn = sqlite3.connect(batch_client.db_path)
    conn.execute(
        """
        INSERT INTO batch_jobs
        (batch_id, agent_name, submitted_at, request_count, status,
         processing_status, request_meta_json, consumer)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("stale_batch_1", "research_agent", old_time, 2, "submitted", "in_progress", "{}", "research_agent"),
    )
    conn.commit()
    conn.close()

    # retrieve() must NOT be called for a batch already past the grace period —
    # sweep_pending should short-circuit to stale before hitting the API.
    batch_client.client.messages.batches.retrieve = AsyncMock(
        side_effect=AssertionError("should not poll a batch already past the stale grace period")
    )

    summary = await batch_client.sweep_pending()

    assert summary["newly_stale"] == ["stale_batch_1"]
    assert summary["newly_ended"] == []

    jobs = batch_client.list_jobs(agent_name="research_agent")
    assert jobs[0]["status"] == "stale"


@pytest.mark.asyncio
async def test_sweep_pending_polls_and_collects_recent_batch(batch_client):
    recent_time = datetime.now(timezone.utc).isoformat()

    import sqlite3

    conn = sqlite3.connect(batch_client.db_path)
    conn.execute(
        """
        INSERT INTO batch_jobs
        (batch_id, agent_name, submitted_at, request_count, status,
         processing_status, request_meta_json, consumer)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("recent_batch_1", "research_agent", recent_time, 1, "submitted", "in_progress", "{}", "research_agent"),
    )
    conn.commit()
    conn.close()

    ended_batch = MagicMock(processing_status="ended", ended_at=None)
    batch_client.client.messages.batches.retrieve = AsyncMock(return_value=ended_batch)

    entries = [_FakeEntry("c1", _FakeSucceeded(_FakeMessage("ok", 10, 10)))]

    async def fake_results(message_batch_id):
        return _fake_results_aiter(entries)

    batch_client.client.messages.batches.results = fake_results

    summary = await batch_client.sweep_pending()

    assert summary["newly_ended"] == ["recent_batch_1"]
    assert summary["newly_stale"] == []


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_calculate_batch_cost_is_half_synchronous_rate(batch_client):
    from llm.client import JarvisLLMClient

    model = "claude-haiku-4-5-20251001"
    sync_cost = (
        (600 / 1_000_000) * JarvisLLMClient.COST_PER_MTOK[model]["input"]
        + (400 / 1_000_000) * JarvisLLMClient.COST_PER_MTOK[model]["output"]
    )
    batch_cost = batch_client.calculate_batch_cost(model, 600, 400)
    assert batch_cost == pytest.approx(sync_cost * 0.5)


def test_calculate_batch_cost_unknown_model_returns_zero(batch_client):
    assert batch_client.calculate_batch_cost("not-a-real-model", 100, 100) == 0.0


@pytest.mark.asyncio
async def test_log_batch_cost_logs_with_provider_batch(batch_client):
    fake_llm_client = MagicMock()
    fake_llm_client.cost_tracker.log_call = AsyncMock()

    await batch_client.log_batch_cost(
        fake_llm_client,
        model="claude-haiku-4-5-20251001",
        input_tokens=600,
        output_tokens=400,
        agent_name="research_agent",
    )

    fake_llm_client.cost_tracker.log_call.assert_awaited_once()
    _, kwargs = fake_llm_client.cost_tracker.log_call.call_args
    assert kwargs["provider"] == "batch"
    assert kwargs["success"] is True
    assert kwargs["agent_name"] == "research_agent"


# ---------------------------------------------------------------------------
# Health summary
# ---------------------------------------------------------------------------


def test_get_batch_health_summary_empty_db(batch_client):
    health = batch_client.get_batch_health_summary()
    assert health == {"jobs_by_status": {}, "unconsumed_results": 0}
