from __future__ import annotations

import copy
import hashlib
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
    assert ids == sorted(ids, key=lambda item_id: next(i["priority"] for i in actionable if i["id"] == item_id))


def test_blockcrisis_resolution_matches_the_verdict_artifact() -> None:
    """The recorded resolution must be the measured one, not an assertion.

    Both the falsification (the preregistered Crisis tier was not the champion) and the
    campaign-deflation failure must be checkable against the committed verdict artifact.
    """
    queue = load_queue(QUEUE)
    item = next(i for i in queue["items"] if i["id"] == "MES_sma_trend_vix_pctile_blockCrisis_v1")
    assert item["state"] == "rejected"
    assert item["promotion_gates"]["backtest"] is True
    resolution = item["resolution"]
    assert resolution["outcome"] == "rejected"

    # Runtime verdicts are gitignored on purpose (.gitignore: engine/data/gate_v2_verdicts/*.json --
    # tracking them let a checkout clobber live verdicts, 2026-06-06 incident). The committed
    # snapshot is the auditable copy; it must still hash to what the queue records.
    snapshot = ROOT.parent / resolution["verdict_snapshot"]
    raw = snapshot.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == resolution["verdict_snapshot_sha256"]
    verdict = json.loads(raw)
    metrics = verdict["gate_v2_metrics"]
    measured = resolution["measured"]

    # The champion blocked nothing -- the preregistered Crisis tier lost the grid.
    assert verdict["champion_blocked_tiers"] == []
    assert resolution["preregistered_blocked_tiers"] == ["Crisis"]
    combos = {tuple(c["blocked_tiers"]): c for c in metrics["combo_results"]}
    assert combos[()]["pf"] == measured["pf_no_block"]
    assert combos[("Crisis",)]["pf"] == measured["pf_preregistered_crisis"]
    assert combos[()]["pf"] > combos[("Crisis",)]["pf"], "recorded rejection claims the block lost"

    assert metrics["pf_ci_lower"] == measured["pf_ci_lower"]
    assert metrics["p_edge"] == measured["p_edge"]
    assert metrics["deflation"]["dsr_grid"] == measured["dsr_grid"]
    assert metrics["deflation"]["dsr_campaign"] == measured["dsr_campaign"]
    assert metrics["deflation"]["n_trials_campaign"] == measured["n_trials_campaign"]
    assert measured["dsr_campaign"] < 0.30, "campaign deflation must be below the ALT floor"
    assert metrics["window_quality"]["sample_adequate_at_gate_floor"] is False

    # Provenance: the run certifies only if it used the deep cache.
    assert verdict["cache_provenance"]["cache_sha256"] == resolution["cache_sha256"]
    assert verdict["cache_provenance"]["cache_span_years"] >= 5.0


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
