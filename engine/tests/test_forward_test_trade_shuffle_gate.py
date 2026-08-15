"""Tests for the ALWAYS-ON trade-sign shuffle graduation gate (this PR).

Proves the core [safety-review] claim directly, isolated from every other gate in
forward_test.py: a no-edge realized-P&L sequence is BLOCKED from graduating, and a
real-edge sequence of the SAME size still graduates. Both tracks forward_test.py
exposes are covered -- ``run_lineage_track`` (the LLM decision-lineage path that
actually trades live; the wiring point this PR chose per ml-pitfalls-defense.md #9)
and ``run_forward_test``'s mechanical candidate loop (kept symmetric with the lineage
track since both share the same gate wiring).

n=16 mirrors MES's live forward-test trade count (per ml-pitfalls-defense.md #9 /
CLAUDE.md) -- the realistic small-sample case the gate must actually engage at, not
an idealized large-n case where any threshold would trivially work.

Every other input the graduation decision depends on (``meets_graduation``,
``is_pre_registered``, the dormant DSR stat_gate) is stubbed/left-off so the only
variable under test is the trade-shuffle verdict -- these are NOT integration tests
of the full graduation rule (see test_forward_test_lineage.py / test_forward_test.py
for that).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import backtest.decision_registry as dr
import backtest.forward_test as ft

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

# 16 trades, exactly balanced (8 x +1, 8 x -1) -> real mean = 0.0, no directional edge.
# A valid permutation test's false-positive rate is exact at any n, so this sequence is
# rejected (p >= 0.05) at close to the nominal (1 - alpha) rate regardless of the small
# sample -- see the module docstring's small-sample-power caveat in forward_test.py.
NO_EDGE_PNLS = [1.0 if i % 2 == 0 else -1.0 for i in range(16)]

# 16 trades, 12 wins of +2.0 / 4 losses of -1.0 -> real mean = 1.25, a clear one-sided
# edge. Same n as NO_EDGE_PNLS -- the only difference is the presence of real edge.
REAL_EDGE_PNLS = [2.0] * 12 + [-1.0] * 4


def _lineage_trade(pnl: float, day: int, lineage: str) -> dict:
    return {
        "symbol": "MES",
        "pnl": pnl,
        "exit_time": (BASE + timedelta(days=day)).isoformat(),
        "strategy_params": {"decision_identity": {"lineage": lineage}},
    }


def _candidate_trade(pnl: float, day: int, candidate_id: str) -> dict:
    return {
        "symbol": "TEST",
        "pnl": pnl,
        "exit_time": (BASE + timedelta(days=day)).isoformat(),
        "strategy_params": {"candidate_id": candidate_id},
    }


class _FakeDB:
    def __init__(self, trades: list[dict]):
        self._trades = trades

    def get_closed_trades(self, limit: int = 100_000) -> list[dict]:
        return list(self._trades)[:limit]


# ── lineage track (the wiring point this PR chose) ──────────────────────────────


def _stub_lineage_registry(monkeypatch) -> None:
    """Isolate the trade-shuffle gate: base graduation always clears on its own."""
    monkeypatch.setattr(dr, "load_registry", lambda: {})
    monkeypatch.setattr(dr, "is_pre_registered", lambda lineage, reg: True)
    monkeypatch.setattr(dr, "meets_graduation", lambda stats, reg: True)
    monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)  # dormant DSR gate off


def test_no_edge_lineage_blocked_by_trade_shuffle_gate(monkeypatch):
    _stub_lineage_registry(monkeypatch)
    closed = [_lineage_trade(pnl, i, "lin-noedge") for i, pnl in enumerate(NO_EDGE_PNLS)]

    rows = ft.run_lineage_track(closed, window_days=30)
    row = next(r for r in rows if r["lineage"] == "lin-noedge")

    assert row["trade_shuffle"]["n_trades"] == 16
    assert row["trade_shuffle"]["p_value"] >= 0.05
    assert row["trade_shuffle"]["passes"] is False
    assert row["graduated"] is False  # BLOCKED despite meets_graduation stubbed True
    assert row["reason"].startswith("trade-shuffle gate block")


def test_real_edge_lineage_still_passes_trade_shuffle_gate(monkeypatch):
    _stub_lineage_registry(monkeypatch)
    closed = [_lineage_trade(pnl, i, "lin-edge") for i, pnl in enumerate(REAL_EDGE_PNLS)]

    rows = ft.run_lineage_track(closed, window_days=30)
    row = next(r for r in rows if r["lineage"] == "lin-edge")

    assert row["trade_shuffle"]["n_trades"] == 16
    assert row["trade_shuffle"]["p_value"] < 0.05
    assert row["trade_shuffle"]["passes"] is True
    assert row["graduated"] is True  # NOT blocked -- same n as the no-edge case above
    assert row["reason"].startswith("graduated")


# ── candidate track (kept symmetric; wired the same way) ────────────────────────

_LENIENT_REGISTRY = {
    "candidates": [
        {
            "id": "cand-test",
            "symbol": "TEST",
            "status": "forward_testing",
            "params": {"note": "trade-shuffle-gate test fixture"},
        }
    ],
    "graduation_rule": {
        "min_forward_oos_windows": 1,
        "min_forward_pf_ci_lower": 0.0,
        "min_forward_p_edge": 0.0,
        "must_survive_family_fdr": False,
    },
}


def _stub_candidate_registry(monkeypatch) -> None:
    """Isolate the trade-shuffle gate: base graduation always clears on its own."""
    monkeypatch.setattr(ft, "meets_graduation", lambda stats, reg: True)
    monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)  # dormant DSR gate off


def test_no_edge_candidate_blocked_by_trade_shuffle_gate(monkeypatch):
    _stub_candidate_registry(monkeypatch)
    closed = [_candidate_trade(pnl, i, "cand-test") for i, pnl in enumerate(NO_EDGE_PNLS)]

    report = ft.run_forward_test(registry=_LENIENT_REGISTRY, db=_FakeDB(closed))
    cand = next(c for c in report["candidates"] if c["id"] == "cand-test")

    assert cand["precise_attribution"] is True  # candidate_id-tagged, not symbol fallback
    assert cand["trade_shuffle"]["passes"] is False
    assert cand["graduated"] is False  # BLOCKED despite meets_graduation stubbed True
    assert cand["reason"].startswith("trade-shuffle gate block")
    assert report["n_graduated"] == 0


def test_real_edge_candidate_still_passes_trade_shuffle_gate(monkeypatch):
    _stub_candidate_registry(monkeypatch)
    closed = [_candidate_trade(pnl, i, "cand-test") for i, pnl in enumerate(REAL_EDGE_PNLS)]

    report = ft.run_forward_test(registry=_LENIENT_REGISTRY, db=_FakeDB(closed))
    cand = next(c for c in report["candidates"] if c["id"] == "cand-test")

    assert cand["precise_attribution"] is True
    assert cand["trade_shuffle"]["passes"] is True
    assert cand["graduated"] is True  # NOT blocked -- same n as the no-edge case above
    assert report["n_graduated"] == 1
