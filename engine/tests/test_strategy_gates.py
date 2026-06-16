"""US-005 tests — GET /strategy/gates/{symbol} production-gate scorecard.

Builds the 6 gate-v2 gates (PF-CI, p_edge, MC DD, DSR, OOS sample, win-rate CI)
from a symbol's verdict via find_verdict + the canonical thresholds in
backtest._gate_v2_helpers. No recompute. Missing verdict => every gate
value=None / passed=None (unknown, not "fail").
"""
from __future__ import annotations

import pytest

from routers import strategy_ledger_router as slr
from routers.strategy_ledger_router import build_gate_scorecard


def _patch_verdict(monkeypatch, row):
    monkeypatch.setattr(slr, "find_verdict", lambda symbol, family=None: row)


def _gate(resp, key):
    return next(g for g in resp.gates if g.key == key)


def test_all_enforced_gates_pass(monkeypatch):
    _patch_verdict(monkeypatch, {
        "family": "trend", "verdict": "PASS", "created_at": "2026-06-10T00:00:00Z",
        "pf_ci_lower": 1.5, "p_edge": 0.97, "mc_95th_dd_pct": 2.0,
        "dsr": 0.5, "oos_trades": 40, "win_rate_ci_lower": 0.4,
    })
    resp = build_gate_scorecard("mes")
    assert resp.symbol == "MES"
    assert resp.verdict == "PASS"
    assert _gate(resp, "pf_ci_lower").passed is True
    assert _gate(resp, "p_edge").passed is True
    assert _gate(resp, "mc_95th_dd").passed is True
    assert _gate(resp, "dsr").passed is True
    assert _gate(resp, "sample").passed is True
    # win gate is shadow (threshold None) -> not evaluable
    assert _gate(resp, "win_rate_ci_lower").passed is None
    assert resp.n_pass == 5
    assert resp.n_evaluated == 5
    assert resp.n_total == 6


def test_failing_gates_marked_false(monkeypatch):
    _patch_verdict(monkeypatch, {
        "verdict": "FAIL",
        "pf_ci_lower": 0.9,        # < 1.10 -> fail
        "p_edge": 0.80,           # < 0.95 -> fail
        "mc_95th_dd_pct": 8.0,    # > 5%   -> fail
        "dsr": 0.05,              # < 0.10 -> fail
        "oos_trades": 12,         # < 30   -> fail
    })
    resp = build_gate_scorecard("MES")
    assert _gate(resp, "pf_ci_lower").passed is False
    assert _gate(resp, "p_edge").passed is False
    assert _gate(resp, "mc_95th_dd").passed is False
    assert _gate(resp, "dsr").passed is False
    assert _gate(resp, "sample").passed is False
    assert resp.n_pass == 0


def test_mc_dd_threshold_is_percent_and_le(monkeypatch):
    _patch_verdict(monkeypatch, {"mc_95th_dd_pct": 4.9})
    g = _gate(build_gate_scorecard("MES"), "mc_95th_dd")
    assert g.comparator == "<="
    assert g.threshold == 5.0  # GATE_MC_DD_CORE (0.05) rendered in percent units
    assert g.unit == "%"
    assert g.passed is True  # 4.9 <= 5.0


def test_win_gate_is_shadow(monkeypatch):
    _patch_verdict(monkeypatch, {"win_rate_ci_lower": 0.55})
    g = _gate(build_gate_scorecard("MES"), "win_rate_ci_lower")
    assert g.enforced is False
    assert g.passed is None
    assert g.note and "shadow" in g.note.lower()


def test_missing_verdict_is_unknown_not_fail(monkeypatch):
    _patch_verdict(monkeypatch, None)
    resp = build_gate_scorecard("MES")
    assert resp.verdict is None
    assert resp.n_pass == 0
    assert resp.n_evaluated == 0
    for g in resp.gates:
        assert g.value is None
        assert g.passed is None  # absence != failure


def test_non_numeric_value_is_tolerated(monkeypatch):
    _patch_verdict(monkeypatch, {"pf_ci_lower": "n/a", "dsr": None})
    resp = build_gate_scorecard("MES")
    assert _gate(resp, "pf_ci_lower").value is None
    assert _gate(resp, "pf_ci_lower").passed is None


def test_route_registered_on_app():
    from main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/strategy/gates/{symbol}" in paths
