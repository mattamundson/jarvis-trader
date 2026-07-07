"""P4: decision-lineage forward-test track.

The LLM path stamps a per-symbol ``decision_identity`` on every live paper entry
(P2). This track groups closed trades by that lineage, windows them, runs a
family-wide BH-FDR, and graduates against the decision_registry -- but only
pre-registered lineages may graduate (default-material ``unregistered:*``
singletons can clear the stats yet never graduate, by design).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from backtest import forward_test as ft  # noqa: E402


def _trade(lineage, exit_iso, pnl):
    """A closed trade carrying a stamped decision_identity lineage."""
    return {
        "symbol": str(lineage).split("::")[-1],
        "pnl": pnl,
        "exit_time": exit_iso,
        "strategy_params": {"decision_identity": {"lineage": lineage}},
    }


# ── attribution ─────────────────────────────────────────────────────────────────

def test_trade_lineage_reads_stamped_identity():
    t = _trade("llm_core_v2::MES", "2026-01-02T00:00:00Z", 50.0)
    assert ft.trade_lineage(t) == "llm_core_v2::MES"


def test_trade_lineage_none_when_untagged():
    assert ft.trade_lineage({"strategy_params": {}}) is None
    assert ft.trade_lineage({"strategy_params": None}) is None


def test_trade_lineage_parses_json_string_params():
    t = {"strategy_params": '{"decision_identity": {"lineage": "x::MGC"}}'}
    assert ft.trade_lineage(t) == "x::MGC"


def test_lineage_buckets_groups_by_lineage():
    trades = [
        _trade("a::MES", "2026-01-02T00:00:00Z", 1.0),
        _trade("a::MES", "2026-01-03T00:00:00Z", 1.0),
        _trade("b::MGC", "2026-01-02T00:00:00Z", 1.0),
        {"strategy_params": {}},  # untagged -> dropped
    ]
    b = ft.lineage_buckets(trades)
    assert set(b) == {"a::MES", "b::MGC"}
    assert len(b["a::MES"]) == 2


# ── the track ────────────────────────────────────────────────────────────────────

def test_empty_when_no_tagged_trades():
    assert ft.run_lineage_track([{"strategy_params": {}}], decision_registry={"lineages": []}) == []


def test_unregistered_lineage_never_graduates_even_when_stats_clear():
    # A flood of profitable windows for a default-material singleton.
    lineage = "unregistered:deadbeef::MES"
    trades = []
    for i in range(10):
        trades.append(_trade(lineage, f"2026-{1 + i:02d}-15T15:00:00Z", 250.0))
    reg = {
        "graduation_rule": {
            "min_forward_oos_windows": 6, "min_forward_pf_ci_lower": 1.10,
            "min_forward_p_edge": 0.95, "must_survive_family_fdr": False,
        },
        "lineages": [],
    }
    out = ft.run_lineage_track(trades, decision_registry=reg)
    row = next(r for r in out if r["lineage"] == lineage)
    assert row["pre_registered"] is False
    assert row["graduated"] is False
    assert row["forward"]["n_oos_windows"] >= 6  # stats DID clear the window floor


def test_pre_registered_lineage_can_graduate_when_record_is_strong():
    lineage = "llm_core_v2::MGC"
    trades = []
    for i in range(8):
        trades.append(_trade(lineage, f"2026-{1 + i:02d}-15T15:00:00Z", 300.0))
    reg = {
        "graduation_rule": {
            "min_forward_oos_windows": 6, "min_forward_pf_ci_lower": 1.10,
            "min_forward_p_edge": 0.95, "must_survive_family_fdr": False,
        },
        "lineages": [{"id": "llm_core_v2", "status": "forward_testing",
                      "member_config_hashes": ["h1"]}],
    }
    out = ft.run_lineage_track(trades, decision_registry=reg)
    row = next(r for r in out if r["lineage"] == lineage)
    assert row["pre_registered"] is True
    assert row["forward"]["n_oos_windows"] >= 6
    assert row["forward"]["p_edge"] == 1.0
    assert row["graduated"] is True


def test_weak_pre_registered_lineage_does_not_graduate():
    lineage = "llm_core_v2::MES"
    # Only 2 windows -> below the 6-window floor.
    trades = [
        _trade(lineage, "2026-01-15T15:00:00Z", 100.0),
        _trade(lineage, "2026-03-15T15:00:00Z", 100.0),
    ]
    reg = {
        "graduation_rule": {
            "min_forward_oos_windows": 6, "min_forward_pf_ci_lower": 1.10,
            "min_forward_p_edge": 0.95, "must_survive_family_fdr": False,
        },
        "lineages": [{"id": "llm_core_v2", "status": "forward_testing"}],
    }
    out = ft.run_lineage_track(trades, decision_registry=reg)
    row = next(r for r in out if r["lineage"] == lineage)
    assert row["graduated"] is False
    assert "not yet graduated" in row["reason"]


def test_fdr_gate_blocks_graduation_when_required():
    lineage = "llm_core_v2::MNQ"
    trades = []
    for i in range(7):
        trades.append(_trade(lineage, f"2026-{1 + i:02d}-15T15:00:00Z", 300.0))
    reg = {
        "graduation_rule": {
            "min_forward_oos_windows": 6, "min_forward_pf_ci_lower": 1.10,
            "min_forward_p_edge": 0.95, "must_survive_family_fdr": True, "q": 0.10,
        },
        "lineages": [{"id": "llm_core_v2", "status": "forward_testing"}],
    }
    out = ft.run_lineage_track(trades, decision_registry=reg)
    row = next(r for r in out if r["lineage"] == lineage)
    # Graduation requires surviving FDR; assert the gate is actually consulted.
    assert row["graduated"] == (row["survives_family_fdr"] and row["pre_registered"])


def test_run_forward_test_report_carries_lineage_block():
    lineage = "llm_core_v2::MGC"
    closed = [_trade(lineage, f"2026-{1 + i:02d}-15T15:00:00Z", 120.0) for i in range(6)]

    class _DB:
        def get_closed_trades(self, limit=0):
            return closed

    report = ft.run_forward_test(
        registry={"graduation_rule": {}, "candidates": []},
        db=_DB(),
    )
    assert "lineages" in report
    assert report["n_lineages"] >= 1
    assert any(lin["lineage"] == lineage for lin in report["lineages"])
