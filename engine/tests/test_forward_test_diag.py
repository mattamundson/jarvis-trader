"""Tests for the report-only trade-sign permutation diagnostic in forward_test.

Verifies the diagnostic is computed and attached to the report, and crucially that it
does NOT leak into the graduation decision (graduation must stay a function of
forward_stats + family FDR only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import backtest.decision_registry as dr
import backtest.forward_test as ft


def _trade(pnl: float, day: int, lineage: str = "lin-A") -> dict:
    exit_time = (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()
    return {
        "pnl": pnl,
        "exit_time": exit_time,
        "symbol": "MES",
        "strategy_params": {"decision_identity": {"lineage": lineage}},
    }


def test_trade_shuffle_diag_shape():
    res = ft.trade_shuffle_diag([{"pnl": 1.0}, {"pnl": -1.0}, {"pnl": 1.0}], n_iters=50)
    assert set(res) == {"p_value", "n_trades", "passes", "metric"}
    assert res["n_trades"] == 3
    assert 0.0 < res["p_value"] <= 1.0


def test_trade_shuffle_diag_skips_none_pnl():
    res = ft.trade_shuffle_diag([{"pnl": 1.0}, {"pnl": None}, {"pnl": 2.0}], n_iters=20)
    assert res["n_trades"] == 2


def test_lineage_report_attaches_diag_without_changing_graduation(monkeypatch):
    # Stub the decision registry so the test is independent of registry files, and
    # force graduation to a known constant so we can prove the diagnostic does not move it.
    monkeypatch.setattr(dr, "load_registry", lambda: {})
    monkeypatch.setattr(dr, "is_pre_registered", lambda lineage, reg: True)
    monkeypatch.setattr(dr, "meets_graduation", lambda stats, reg: False)

    # A win-heavy lineage (the diagnostic would "pass") spread across multiple windows.
    closed = [_trade(5.0, d) for d in (1, 35, 70, 105, 140)] + [_trade(-1.0, 175)]
    rows = ft.run_lineage_track(closed, window_days=30)

    assert rows, "expected at least one lineage row"
    row = rows[0]
    assert "trade_shuffle" in row
    assert "p_value" in row["trade_shuffle"]
    # The diagnostic must not override the stubbed graduation verdict.
    assert row["graduated"] is False


def test_markdown_includes_ts_p_column(monkeypatch):
    monkeypatch.setattr(dr, "load_registry", lambda: {})
    monkeypatch.setattr(dr, "is_pre_registered", lambda lineage, reg: True)
    monkeypatch.setattr(dr, "meets_graduation", lambda stats, reg: False)
    closed = [_trade(5.0, d) for d in (1, 35, 70)]
    report = {
        "generated_at": "x",
        "window_days": 30,
        "graduation_rule": None,
        "n_active_candidates": 0,
        "n_graduated": 0,
        "candidates": [],
        "lineages": ft.run_lineage_track(closed, window_days=30),
        "n_lineages": 1,
        "n_lineages_graduated": 0,
        "symbol_context": {},
        "note": "n",
    }
    md = ft._markdown(report)
    assert "ts_p" in md
