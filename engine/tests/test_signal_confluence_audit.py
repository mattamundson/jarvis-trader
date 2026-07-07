"""Unit tests for the pure verdict logic in scripts/signal_confluence_audit.py.

Only the pure functions (rank_arms / build_verdict / format_report) are exercised
here — no MES data, no engine, no pandas. Backtest arms are passed as fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from scripts.signal_confluence_audit import (  # noqa: E402
    ARMS,
    DIAGNOSE_PARAMS,
    _composite_funnel,
    _entry_count,
    build_verdict,
    format_diagnose,
    format_report,
    rank_arms,
)


class TestArmWiring:
    def test_expected_arms_registered(self):
        assert set(ARMS) == {"trend", "composite", "tpo", "saty", "atrtrail"}
        for grid_fn, apply_fn in ARMS.values():
            assert callable(grid_fn) and callable(apply_fn)


def _arm(name, pf, trades, status="ok", sharpe=1.0, wfe=0.6):
    return {
        "arm": name,
        "status": status,
        "oos_pf": pf,
        "oos_sharpe": sharpe,
        "oos_trades": trades,
        "wfe": wfe,
    }


def _ic(score, n=40, ready=True):
    return {"available": True, "source": "test", "ic_score": score, "sample_count": n, "ready": ready}


class TestRankArms:
    def test_orders_by_oos_pf_desc(self):
        arms = [_arm("trend", 1.2, 30), _arm("tpo", 1.8, 30), _arm("composite", 1.5, 30)]
        ranked = rank_arms(arms)
        assert [a["arm"] for a in ranked] == ["tpo", "composite", "trend"]
        assert [a["rank"] for a in ranked] == [1, 2, 3]

    def test_filters_low_trade_count(self):
        arms = [_arm("trend", 1.2, 30), _arm("tpo", 9.9, 3)]  # tpo under-sampled
        ranked = rank_arms(arms, min_trades=10)
        assert [a["arm"] for a in ranked] == ["trend"]

    def test_filters_non_ok_status(self):
        arms = [_arm("trend", 1.2, 30), _arm("tpo", 2.0, 30, status="no_data")]
        assert [a["arm"] for a in rank_arms(arms)] == ["trend"]


class TestBuildVerdict:
    def test_trend_dominant_when_trend_wins(self):
        arms = [_arm("trend", 1.6, 40), _arm("tpo", 1.1, 40), _arm("composite", 1.0, 40)]
        v = build_verdict(arms, _ic(0.3))
        assert v["verdict"] == "TREND_DOMINANT"
        assert v["best_arm"] == "trend"

    def test_auction_candidate_requires_margin_and_positive_ic(self):
        arms = [_arm("trend", 1.2, 40), _arm("tpo", 1.6, 40)]  # 1.6 > 1.2 * 1.10
        v = build_verdict(arms, _ic(0.25))
        assert v["verdict"] == "AUCTION_EDGE_CANDIDATE"
        assert v["best_arm"] == "tpo"

    def test_auction_unconfirmed_when_ic_not_positive(self):
        arms = [_arm("trend", 1.2, 40), _arm("tpo", 1.6, 40)]
        v = build_verdict(arms, _ic(-0.1))
        assert v["verdict"] == "AUCTION_EDGE_UNCONFIRMED"

    def test_margin_not_cleared_stays_trend_dominant(self):
        arms = [_arm("trend", 1.5, 40), _arm("tpo", 1.55, 40)]  # < 1.5 * 1.10
        v = build_verdict(arms, _ic(0.4))
        assert v["verdict"] == "TREND_DOMINANT"

    def test_insufficient_sample_when_nothing_ranks(self):
        arms = [_arm("trend", 2.0, 3), _arm("tpo", 3.0, 4)]
        v = build_verdict(arms, _ic(0.5))
        assert v["verdict"] == "INSUFFICIENT_SAMPLE"

    def test_caveats_always_present(self):
        v = build_verdict([_arm("trend", 1.6, 40)], _ic(0.3))
        assert any("DIAGNOSTIC" in c for c in v["caveats"])
        assert any("Multiple testing" in c for c in v["caveats"])

    def test_screen_not_verdict_caveat_present(self):
        # Audit must never read as a refutation; the demotion caveat is mandatory.
        v = build_verdict([_arm("trend", 1.6, 40)], _ic(0.3))
        assert any("SCREEN, NOT A VERDICT" in c for c in v["caveats"])
        assert any("validate_strategy.py" in c for c in v["caveats"])
        assert any("--diagnose" in c for c in v["caveats"])


class TestDiagnose:
    def test_diagnose_params_cover_all_arms(self):
        # Every arm needs a representative param point for --diagnose.
        assert set(DIAGNOSE_PARAMS) == set(ARMS)

    def test_entry_count_handles_none_and_missing_column(self):
        assert _entry_count(None) == 0

        class _NoCol:
            columns: list = []

        assert _entry_count(_NoCol()) == 0

    def test_composite_funnel_handles_none(self):
        assert _composite_funnel(None) == {}

    def test_format_diagnose_renders_counts_and_funnel(self):
        rows = [
            {"arm": "composite", "train_bars": 100, "test_bars": 80,
             "train_entries": 21, "test_entries": 0,
             "test_funnel": {"regime": {"VOLATILE": 80}, "adx_ge_25_pct": 0.0}},
            {"arm": "trend", "train_bars": 100, "test_bars": 80,
             "train_entries": 9, "test_entries": 10},
        ]
        out = format_diagnose(rows)
        assert "ENTRY FUNNEL DIAGNOSTIC" in out
        assert "composite" in out and "VOLATILE" in out
        assert "not proof of no edge" in out


class TestFormatReport:
    def test_renders_verdict_and_handles_missing_ic(self):
        arms = [_arm("trend", 1.6, 40), _arm("tpo", 1.0, 40, status="error")]
        v = build_verdict(arms, {"available": False, "error": "engine down"})
        report = format_report(v)
        assert "SIGNAL CONFLUENCE AUDIT" in report
        assert "corey-IC: unavailable" in report
        assert "Skipped arms:" in report
