"""Pure-logic tests for the orchestrator (no data / no backtests)."""

from __future__ import annotations

from backtest.factory.orchestrator import (
    Universe,
    enumerate_candidates,
    pilot_cards,
    render_report,
)


def test_pilot_cards_all_pass_the_gate():
    """Every shipped pilot card must clear the rationale/family gate."""
    for card in pilot_cards():
        assert card.is_valid(), f"{card.name} failed gate: {card.problems()}"


def test_enumerate_intersects_universe():
    cards = pilot_cards()
    # Universe excludes 1d, so sma_trend (1d-only) yields zero candidates.
    uni = Universe(instruments=["MES", "SPY"], timeframes=["1h"])
    cands = enumerate_candidates(cards, uni)
    names = {c.name for c, _, _ in cands}
    assert "sma_trend" not in names  # 1d-only, filtered out
    assert "donchian_breakout" in names
    # donchian is MES+SPY on 1h -> exactly 2 candidates
    don = [(c, s, t) for c, s, t in cands if c.name == "donchian_breakout"]
    assert {s for _, s, _ in don} == {"MES", "SPY"}
    assert all(t == "1h" for _, _, t in don)


def test_enumerate_unknown_symbol_dropped():
    cards = pilot_cards()
    uni = Universe(instruments=["ZZZ"], timeframes=["1h"])  # no card lists ZZZ
    assert enumerate_candidates(cards, uni) == []


def test_render_report_contains_sections():
    summary = {
        "run_id": 1,
        "created_at": "2026-06-26T00:00:00Z",
        "global_trials": 24,
        "n_candidates": 3,
        "n_smoke_pass": 1,
        "n_robustness_pass": 0,
        "rows": [
            {
                "card": "donchian_breakout",
                "sym": "MES",
                "tf": "1h",
                "smoke_pass": True,
                "stage": "robustness",
                "verdict": "FAIL",
                "gate": {
                    "pf_ci_lower": 0.95,
                    "mc_95th_dd_pct": 7.2,
                    "dsr": 0.04,
                    "p_edge": 0.6,
                    "dsr_global": 0.01,
                    "pbo": 0.7,
                },
            },
            {
                "card": "bollinger_rsi_meanrev",
                "sym": "SPY",
                "tf": "1h",
                "smoke_pass": False,
                "stage": "killed_smoke",
                "smoke": {"kill_reason": "does not survive realistic cost"},
            },
            {"card": "sma_trend", "sym": "MES", "tf": "1d", "stage": "skip", "reason": "no data"},
        ],
    }
    report = render_report(summary)
    assert "# Strategy-Factory Pilot Report" in report
    assert "global DSR n_trials = **24**" in report
    assert "## Kill / fail reasons" in report
    # overfit PBO must surface in the fail reason
    assert "PBO 0.70>0.5" in report
    assert "does not survive realistic cost" in report
