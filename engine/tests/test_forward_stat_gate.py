"""Tests for the DORMANT DSR + trade-shuffle graduation gate in forward_test.

The gate must be OFF by default (graduation identical to meets_graduation), must
ABSTAIN on thin samples even when enforced, and — only when enforced AND the
sample is thick enough — may make graduation MORE restrictive (never rescues a
non-graduating unit).
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


class TestFlag:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("FORWARD_STAT_GATE_ENFORCE", raising=False)
        assert ft.forward_stat_gate_enforced() is False

    def test_on_when_truthy(self, monkeypatch):
        monkeypatch.setenv("FORWARD_STAT_GATE_ENFORCE", "1")
        assert ft.forward_stat_gate_enforced() is True


class TestStatGateVerdict:
    def test_dormant_when_off(self, monkeypatch):
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)
        v = ft.stat_gate_verdict({"dsr": 0.0, "n_trades": 100}, {"p_value": 1.0})
        assert v["enforced"] is False and v["abstained"] is True and v["passes"] is True

    def test_abstain_thin_sample(self, monkeypatch):
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        v = ft.stat_gate_verdict({"dsr": 0.0, "n_trades": 10}, {"p_value": 1.0})
        assert v["abstained"] is True and v["passes"] is True  # < 30 trades -> abstain

    def test_blocks_low_dsr(self, monkeypatch):
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        v = ft.stat_gate_verdict({"dsr": 0.05, "n_trades": 50}, {"p_value": 0.01})
        assert v["passes"] is False and any("dsr" in r for r in v["reasons"])

    def test_blocks_high_ts_p(self, monkeypatch):
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        v = ft.stat_gate_verdict({"dsr": 0.5, "n_trades": 50}, {"p_value": 0.20})
        assert v["passes"] is False and any("ts_p" in r for r in v["reasons"])

    def test_passes_when_both_ok(self, monkeypatch):
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        v = ft.stat_gate_verdict({"dsr": 0.5, "n_trades": 50}, {"p_value": 0.01})
        assert v["passes"] is True and v["abstained"] is False


class TestGraduationIntegration:
    # 36 alternating-sign trades in one lineage: mean ~0 -> DSR ~0 and high ts_p,
    # so the gate FAILS when enforced. 36 >= STAT_GATE_MIN_TRADES (30) -> no abstain.
    def _closed(self) -> list[dict]:
        return [_trade(1.0 if d % 2 else -1.0, d) for d in range(1, 37)]

    def _stub_registry(self, monkeypatch):
        monkeypatch.setattr(dr, "load_registry", lambda: {})
        monkeypatch.setattr(dr, "is_pre_registered", lambda lineage, reg: True)
        monkeypatch.setattr(dr, "meets_graduation", lambda stats, reg: True)

    def test_off_leaves_graduation_unchanged(self, monkeypatch):
        self._stub_registry(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)
        rows = ft.run_lineage_track(self._closed(), window_days=30)
        assert rows[0]["graduated"] is True  # base graduation preserved (gate dormant)
        assert rows[0]["stat_gate"]["abstained"] is True

    def test_on_blocks_when_stats_fail(self, monkeypatch):
        self._stub_registry(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        rows = ft.run_lineage_track(self._closed(), window_days=30)
        assert rows[0]["stat_gate"]["enforced"] is True
        assert rows[0]["stat_gate"]["passes"] is False
        assert rows[0]["graduated"] is False  # gate blocked despite meets_graduation True
        assert rows[0]["reason"].startswith("stat-gate block")


class _FakeDB:
    def __init__(self, trades):
        self._trades = trades

    def get_closed_trades(self, limit=500):
        return list(self._trades)[:limit]


class TestCandidateLoopGraduationIntegration:
    """Same dormant gate, driven through run_forward_test's MECHANICAL candidate
    loop instead of the LLM decision-lineage loop above -- both loops AND the same
    stat_gate_verdict() onto their own base graduation check, so this closes the
    candidate-loop's missing integration coverage (only the lineage loop had one)."""

    _CAND = {"id": "fake-cand", "symbol": "MES"}

    def _stub(self, monkeypatch):
        monkeypatch.setattr(ft, "load_registry", lambda: {"graduation_rule": {}})
        monkeypatch.setattr(ft, "get_active_candidates", lambda reg: [dict(self._CAND)])
        monkeypatch.setattr(ft, "meets_graduation", lambda stats, reg: True)

    @staticmethod
    def _cand_trade(pnl: float, day: int) -> dict:
        exit_time = (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()
        return {
            "pnl": pnl,
            "exit_time": exit_time,
            "symbol": "MES",
            "strategy_params": {"candidate_id": "fake-cand"},
        }

    # 36 alternating-sign trades tagged to the candidate_id: mean ~0 -> DSR ~0.5 but
    # a high trade-shuffle p (real mean is indistinguishable from the sign-flip null),
    # so the gate FAILS when enforced. 36 >= STAT_GATE_MIN_TRADES (30) -> no abstain.
    def _degenerate_closed(self) -> list[dict]:
        return [self._cand_trade(1.0 if d % 2 else -1.0, d) for d in range(1, 37)]

    # 36 trades, all profitable with modest scatter -> strong raw Sharpe, DSR clears
    # dsr_min even after deflation, and the sign-shuffle null is rejected (every real
    # sign is positive, so shuffled means center far below the real one).
    def _strong_closed(self) -> list[dict]:
        return [self._cand_trade(2.0 + 0.6 * ((d % 5) - 2), d) for d in range(1, 37)]

    def test_off_leaves_graduation_unchanged(self, monkeypatch):
        self._stub(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)
        report = ft.run_forward_test(db=_FakeDB(self._degenerate_closed()), window_days=30)
        row = next(c for c in report["candidates"] if c["id"] == "fake-cand")
        assert row["graduated"] is True  # base graduation preserved (gate dormant)
        assert row["stat_gate"]["abstained"] is True

    def test_on_blocks_degenerate_dsr(self, monkeypatch):
        self._stub(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        report = ft.run_forward_test(db=_FakeDB(self._degenerate_closed()), window_days=30)
        row = next(c for c in report["candidates"] if c["id"] == "fake-cand")
        assert row["stat_gate"]["enforced"] is True
        assert row["stat_gate"]["passes"] is False
        assert row["graduated"] is False  # gate blocked despite meets_graduation True
        assert row["reason"].startswith("stat-gate block")

    def test_on_graduates_when_dsr_is_strong(self, monkeypatch):
        self._stub(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        report = ft.run_forward_test(db=_FakeDB(self._strong_closed()), window_days=30)
        row = next(c for c in report["candidates"] if c["id"] == "fake-cand")
        assert row["stat_gate"]["enforced"] is True
        assert row["stat_gate"]["abstained"] is False
        assert row["dsr"]["dsr"] >= ft.DSR_GATE_MIN
        assert row["stat_gate"]["passes"] is True
        assert row["graduated"] is True  # strong forward record clears the gate too
