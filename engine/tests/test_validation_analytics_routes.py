"""
Tests for validation_analytics_router — the live replacements for the three
formerly-static /validation tables (significance, sensitivity, monte-carlo).

Seeds temp gate-v2 verdict JSONs and asserts the endpoints derive the right
live numbers (t-stat from OOS windows, per-param PF spread from the combo grid,
gate MC drawdown), and that the known edge cases are handled: a zero-loss window
(PF == inf) must not poison the mean/t-stat, and a degenerate MC artifact must
be flagged rather than rendered as fake spread.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("API_KEY", "test-dummy-key-not-a-secret-0000")

from routers import validation_analytics_router as v  # noqa: E402


def _write_verdict(d: Path, name: str, **over) -> None:
    body = {
        "symbol": over.get("symbol", "MES"),
        "family": over.get("family", "trend"),
        "rank": over.get("rank", 1),
        "verdict": over.get("verdict", "PASS"),
        "created_at": over.get("created_at", "2026-05-01T00:00:00+00:00"),
        "gate_v2_metrics": {
            "pf_ci_lower": over.get("pf_ci_lower", 1.5),
            "p_edge": over.get("p_edge", 0.97),
            "mc_95th_dd_pct": over.get("mc_95th_dd_pct", 3.2),
            "dsr": over.get("dsr", 0.4),
            "fixed_params_min_pf": over.get("min_pf", 1.1),
            "fixed_params_mean_pf": over.get("mean_pf", 1.4),
            "fixed_params_max_pf": over.get("max_pf", 1.9),
            "n_combos_with_trades": over.get("n_combos", None),
            "combo_results": over.get("combos", []),
        },
        "windows": over.get("windows", []),
    }
    (d / name).write_text(json.dumps(body), encoding="utf-8")


def test_significance_derives_t_stat_and_significance(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    _write_verdict(
        tmp_path,
        "MGC_trend_rank1.json",
        symbol="MGC",
        p_edge=0.98,
        windows=[
            {"oos_pf": 1.5, "oos_trades": 10},
            {"oos_pf": 1.2, "oos_trades": 8},
            {"oos_pf": 1.8, "oos_trades": 12},
        ],
    )
    _write_verdict(
        tmp_path, "MCL_meanrev_rank1.json", symbol="MCL", p_edge=0.5, verdict="FAIL"
    )

    resp = v.get_significance(symbol=None, significant_only=False)
    assert resp.total == 2
    assert resp.n_significant == 1  # only the p_edge>=0.95 row
    mgc = next(e for e in resp.entries if e.symbol == "MGC")
    assert mgc.significant is True
    assert mgc.n_oos_trades == 30  # summed from windows
    assert mgc.n_windows == 3
    assert mgc.mean_oos_pf is not None and math.isclose(mgc.mean_oos_pf, 1.5, abs_tol=1e-6)
    assert mgc.t_stat is not None and mgc.t_stat > 0  # mean PF 1.5 > break-even 1.0


def test_significance_ignores_infinite_pf_window(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    _write_verdict(
        tmp_path,
        "MES_trend_rank1.json",
        windows=[
            {"oos_pf": 1.4, "oos_trades": 9},
            {"oos_pf": float("inf"), "oos_trades": 5},  # zero-loss window
            {"oos_pf": 1.6, "oos_trades": 7},
        ],
    )
    resp = v.get_significance(symbol="MES", significant_only=False)
    e = resp.entries[0]
    # inf dropped → mean is the average of the two finite PFs, t-stat finite
    assert e.mean_oos_pf is not None and math.isfinite(e.mean_oos_pf)
    assert math.isclose(e.mean_oos_pf, 1.5, abs_tol=1e-6)
    assert e.t_stat is not None and math.isfinite(e.t_stat)


def test_sensitivity_computes_per_param_spread_and_level(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    # 'fast' moves PF a lot (high sensitivity); 'slow' barely moves it (low)
    combos = [
        {"fast": 10, "slow": 80, "pf": 1.0, "trades": 30},
        {"fast": 10, "slow": 100, "pf": 1.05, "trades": 28},
        {"fast": 40, "slow": 80, "pf": 2.0, "trades": 25},
        {"fast": 40, "slow": 100, "pf": 2.1, "trades": 24},
    ]
    _write_verdict(tmp_path, "MGC_trend_rank1.json", symbol="MGC", combos=combos)

    resp = v.get_sensitivity(symbol="MGC")
    assert resp.total == 1
    params = {p.parameter: p for p in resp.entries[0].params}
    assert set(params) == {"fast", "slow"}
    # fast: mean PF at 10 ≈ 1.025, at 40 ≈ 2.05 → spread ≈ 1.025 → HIGH
    assert params["fast"].level == "HIGH"
    assert params["fast"].best_value == 40
    # slow: mean PF at 80 ≈ 1.5, at 100 ≈ 1.575 → spread ≈ 0.075 → half ≈ 0.0375 → LOW
    assert params["slow"].level == "LOW"
    # most-sensitive param listed first
    assert resp.entries[0].params[0].parameter == "fast"


def test_monte_carlo_surfaces_gate_drawdown_for_all(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    # point results dir at an empty tmp so no artifacts are layered in
    monkeypatch.setattr(v, "_results_dir", lambda: tmp_path / "noresults")
    _write_verdict(tmp_path, "MGC_trend_rank1.json", symbol="MGC", mc_95th_dd_pct=2.1)
    _write_verdict(tmp_path, "MES_trend_rank1.json", symbol="MES", mc_95th_dd_pct=5.3)

    resp = v.get_monte_carlo(symbol=None)
    assert resp.total == 2
    assert resp.n_with_artifact == 0  # no artifacts present
    dd = {e.symbol: e.mc_95th_dd_pct for e in resp.entries}
    assert dd["MGC"] == 2.1 and dd["MES"] == 5.3
    assert all(e.source == "gate_v2" for e in resp.entries)


def test_monte_carlo_flags_degenerate_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(v, "_results_dir", lambda: results)
    _write_verdict(tmp_path, "MGC_trend_rank1.json", symbol="MGC", mc_95th_dd_pct=2.1)
    # degenerate artifact: collapsed percentiles (p5 == p95)
    (results / "MGC_1d_monte_carlo.json").write_text(
        json.dumps(
            {
                "n_simulations": 10000,
                "n_trades": 50,
                "original": {"final_capital": 128531.05, "total_return_pct": 28.53},
                "distribution": {
                    "final_capital": {"p5": 128531.05, "median": 128531.05, "p95": 128531.05}
                },
                "confidence": {"value_at_risk_5pct": 0.0},
                "verdict": "MARGINAL",
            }
        ),
        encoding="utf-8",
    )
    resp = v.get_monte_carlo(symbol="MGC")
    e = resp.entries[0]
    assert e.degenerate is True
    assert e.return_p5 is None and e.return_median is None and e.return_p95 is None
    assert e.mc_95th_dd_pct == 2.1  # real gate DD still surfaced
    assert e.source == "gate_v2+artifact" and e.timeframe == "1d"


def test_monte_carlo_computes_returns_from_healthy_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_verdicts_dir", lambda: tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(v, "_results_dir", lambda: results)
    _write_verdict(tmp_path, "MNQ_trend_rank1.json", symbol="MNQ", mc_95th_dd_pct=4.0)
    # healthy artifact: initial capital 100k, spread percentiles
    (results / "MNQ_1h_monte_carlo.json").write_text(
        json.dumps(
            {
                "n_simulations": 10000,
                "n_trades": 128,
                "original": {"final_capital": 110000.0, "total_return_pct": 10.0},
                "distribution": {
                    "final_capital": {"p5": 92000.0, "median": 113600.0, "p95": 131400.0}
                },
                "confidence": {"value_at_risk_5pct": 8000.0},
                "verdict": "GOOD",
            }
        ),
        encoding="utf-8",
    )
    resp = v.get_monte_carlo(symbol="MNQ")
    e = resp.entries[0]
    assert e.degenerate is False
    # initial = 110000 / 1.10 = 100000 → p5 return = -8.0%, p95 = +31.4%
    assert e.return_p5 is not None and math.isclose(e.return_p5, -8.0, abs_tol=0.1)
    assert e.return_median is not None and math.isclose(e.return_median, 13.6, abs_tol=0.1)
    assert e.return_p95 is not None and math.isclose(e.return_p95, 31.4, abs_tol=0.1)
