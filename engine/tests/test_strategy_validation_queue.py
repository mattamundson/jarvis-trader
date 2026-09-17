from __future__ import annotations

import copy
import json
from pathlib import Path

from research.strategy_validation_queue import (
    REQUIRED_PROMOTION_GATES,
    load_queue,
    next_actionable_items,
    promotion_ready,
    validate_queue,
)

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "research" / "strategy_validation_queue.json"
DOC = ROOT.parent / "docs" / "research" / "strategy-validation-queue.md"


def test_committed_queue_loads_and_has_canonical_promotion_gates() -> None:
    queue = load_queue(QUEUE)
    assert queue["promotion_required_gates"] == list(REQUIRED_PROMOTION_GATES)
    assert queue["global_rules"]["promotion_requires_human_approval"] is True
    assert queue["global_rules"]["agentic_loop_minimum_hours"] == 6


def test_no_queue_item_can_route_orders() -> None:
    queue = load_queue(QUEUE)
    assert queue["items"]
    assert all(item["may_route_orders"] is False for item in queue["items"])


def test_promotion_candidate_must_have_every_gate_true() -> None:
    queue = load_queue(QUEUE)
    bad = copy.deepcopy(queue)
    candidate = bad["items"][0]
    candidate["state"] = "promotion_candidate"
    candidate["promotion_gates"]["human_approval"] = False
    problems = validate_queue(bad)
    assert any("promotion_candidate without all gates true" in p for p in problems)


def test_next_actionable_items_skip_terminal_failures_and_blocked_references() -> None:
    queue = load_queue(QUEUE)
    actionable = next_actionable_items(queue)
    ids = [item["id"] for item in actionable]
    assert "MGC_trend_rv_filter_rank1" not in ids
    assert "MES_sma_trend_vix_pctile_blockCrisis_v1" not in ids
    assert "SPY_stc_trend_meta_rank1" not in ids
    assert "repo_reference_patterns" not in ids
    assert ids == []


def test_promotion_ready_is_false_for_committed_queue() -> None:
    queue = load_queue(QUEUE)
    assert all(not promotion_ready(item) for item in queue["items"])


def test_doc_describes_read_only_boundary_and_loop_cadence() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert "not a routing change" in doc
    assert "no more frequently than every 6 hours" in doc
    assert "human approval" in doc


def test_json_is_exactly_parseable_without_comments() -> None:
    assert json.loads(QUEUE.read_text(encoding="utf-8"))["schema_version"] == 1
