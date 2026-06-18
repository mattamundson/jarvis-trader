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
    build_verdict,
    format_report,
    rank_arms,
)


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


class TestFormatReport:
    def test_renders_verdict_and_handles_missing_ic(self):
        arms = [_arm("trend", 1.6, 40), _arm("tpo", 1.0, 40, status="error")]
        v = build_verdict(arms, {"available": False, "error": "engine down"})
        report = format_report(v)
        assert "SIGNAL CONFLUENCE AUDIT" in report
        assert "corey-IC: unavailable" in report
        assert "Skipped arms:" in report
