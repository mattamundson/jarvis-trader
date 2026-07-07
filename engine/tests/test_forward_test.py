"""Tests for the forward-test loop (ROI #2).

Covers attribution (candidate_id / params / symbol / none), window bucketing,
forward statistics, the family-FDR + graduation gating, and the key honesty
invariant: symbol-level attribution never graduates a candidate, while a tagged
candidate with a clean forward record does.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backtest import candidate_registry as cr
from backtest import forward_test as ft

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
RV1 = "MGC_trend_rv_filter_rank1"
RV1_PARAMS = {"fast": 50, "slow": 120, "atr_trail_mult": 2.0, "min_rv_annualized": 9.0}


def _trade(symbol, pnl, day, strategy_params=None):
    return {
        "symbol": symbol,
        "pnl": pnl,
        "exit_time": (BASE + timedelta(days=day)).isoformat(),
        "strategy_params": (
            json.dumps(strategy_params) if strategy_params is not None else None
        ),
    }


class _FakeDB:
    def __init__(self, trades):
        self._trades = trades

    def get_closed_trades(self, limit=500):
        return list(self._trades)[:limit]


# ── attribution ────────────────────────────────────────────────────────────────

def test_attribution_candidate_id_is_most_precise():
    cand = cr.get_candidate(RV1)
    t = _trade("MGC", 100.0, 0, {"candidate_id": RV1, "source": "scanner"})
    assert ft.attribution_level(t, cand) == "candidate_id"


def test_attribution_params_match():
    cand = cr.get_candidate(RV1)
    t = _trade("MGC", 100.0, 0, dict(RV1_PARAMS))  # no candidate_id, but params equal
    assert ft.attribution_level(t, cand) == "params"


def test_attribution_symbol_fallback_for_scanner_trade():
    cand = cr.get_candidate(RV1)
    t = _trade("MGC", 100.0, 0, {"source": "scanner", "approval_id": "x"})
    assert ft.attribution_level(t, cand) == "symbol"


def test_attribution_none_for_other_symbol():
    cand = cr.get_candidate(RV1)
    t = _trade("MNQ", 100.0, 0, {"source": "scanner"})
    assert ft.attribution_level(t, cand) is None


def test_attributable_trades_prefers_precise_level():
    cand = cr.get_candidate(RV1)
    trades = [
        _trade("MGC", 100.0, 0, {"candidate_id": RV1}),
        _trade("MGC", 50.0, 1, {"source": "scanner"}),  # symbol-only
    ]
    level, trs = ft.attributable_trades(trades, cand)
    assert level == "candidate_id"
    assert len(trs) == 1  # only the precisely-tagged one


# ── windows + stats ──────────────────────────────────────────────────────────

def test_build_windows_buckets_by_30d():
    trades = [_trade("MGC", 10.0, d) for d in (0, 31, 62)]
    wins = ft.build_windows(trades, window_days=30)
    assert len(wins) == 3
    assert all(w["n_trades"] == 1 for w in wins)


def test_build_windows_drops_open_and_unparseable():
    trades = [
        {"symbol": "MGC", "pnl": None, "exit_time": BASE.isoformat()},  # open
        {"symbol": "MGC", "pnl": 5.0, "exit_time": "not-a-date"},        # bad ts
        _trade("MGC", 7.0, 0),
    ]
    wins = ft.build_windows(trades, 30)
    assert len(wins) == 1
    assert wins[0]["n_trades"] == 1


def test_forward_stats_all_profitable_windows():
    # 6 windows, each a single +100 win -> p_edge 1.0, pf inf-capped, binom small
    trades = [_trade("MGC", 100.0, d * 31) for d in range(6)]
    stats = ft.forward_stats(ft.build_windows(trades, 30))
    assert stats["n_oos_windows"] == 6
    assert stats["p_edge"] == 1.0
    assert stats["pf_ci_lower"] >= 1.10
    # P(X>=6 | Bin(6,0.5)) = 1/64
    assert stats["binom_p"] < 0.02


def test_forward_stats_empty():
    s = ft.forward_stats([])
    assert s["n_oos_windows"] == 0
    assert s["binom_p"] == 1.0


# ── tagging contract ─────────────────────────────────────────────────────────

def test_tag_strategy_params_stamps_candidate_id():
    out = ft.tag_strategy_params({"source": "scanner"}, RV1)
    assert out["candidate_id"] == RV1
    assert out["source"] == "scanner"  # preserved


def test_tag_strategy_params_accepts_json_string_and_none():
    assert ft.tag_strategy_params(json.dumps({"a": 1}), RV1)["candidate_id"] == RV1
    assert ft.tag_strategy_params(None, RV1) == {"candidate_id": RV1}


# ── the loop ───────────────────────────────────────────────────────────────────

def test_run_forward_test_symbol_level_never_graduates():
    # Untagged scanner MGC trades -> symbol attribution -> no graduation even with
    # a perfect record.
    trades = [_trade("MGC", 100.0, d * 31, {"source": "scanner"}) for d in range(8)]
    report = ft.run_forward_test(db=_FakeDB(trades))
    assert report["n_graduated"] == 0
    mgc = [c for c in report["candidates"] if c["symbol"] == "MGC"]
    assert mgc and all(c["attribution_level"] == "symbol" for c in mgc)
    assert all(not c["graduated"] for c in mgc)
    assert all(not c["precise_attribution"] for c in mgc)


def test_run_forward_test_tagged_candidate_graduates():
    # 6 tagged, all-profitable forward windows for RV1 -> graduates.
    trades = [
        _trade("MGC", 100.0, d * 31, {"candidate_id": RV1}) for d in range(6)
    ]
    report = ft.run_forward_test(db=_FakeDB(trades))
    rv1 = next(c for c in report["candidates"] if c["id"] == RV1)
    assert rv1["attribution_level"] == "candidate_id"
    assert rv1["precise_attribution"] is True
    assert rv1["forward"]["n_oos_windows"] == 6
    assert rv1["survives_family_fdr"] is True
    assert rv1["graduated"] is True
    assert report["n_graduated"] == 1


def test_run_forward_test_reports_symbol_context():
    trades = [_trade("MGC", 100.0, d * 31, {"source": "scanner"}) for d in range(3)]
    report = ft.run_forward_test(db=_FakeDB(trades))
    assert "MGC" in report["symbol_context"]
    assert report["symbol_context"]["MGC"]["total_trades"] == 3
