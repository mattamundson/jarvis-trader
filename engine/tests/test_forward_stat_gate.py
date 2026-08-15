"""Tests for the DORMANT DSR fortification gate in forward_test.

NOTE: as of the [safety-review] trade-shuffle wiring, the trade-sign shuffle null is
ALWAYS ON and blocking (see test_forward_test_trade_shuffle_gate.py) -- this file now
covers only the SEPARATE, still-dormant DSR fortification gate layered on top of it.
That gate must be OFF by default, must ABSTAIN on thin samples even when enforced, and
-- only when enforced AND the sample is thick enough -- may make graduation MORE
restrictive (never rescues a non-graduating unit). ``TestGraduationIntegration`` uses
fixtures crafted so the always-on trade-shuffle gate does not confound what's being
isolated in each test (see per-test comments).
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
    # so the DORMANT stat_gate FAILS when enforced. 36 >= STAT_GATE_MIN_TRADES (30) ->
    # no abstain. This fixture also fails the ALWAYS-ON trade-shuffle gate (added
    # after #247 shipped this dormant gate) -- see test_off_leaves_graduation_unchanged
    # below for what that means for these tests.
    def _closed(self) -> list[dict]:
        return [_trade(1.0 if d % 2 else -1.0, d) for d in range(1, 37)]

    # A clearly one-sided-positive fixture that clears the always-on trade-shuffle
    # gate on its own (p << 0.05), used to isolate the DORMANT stat_gate's own
    # off/abstain behavior from the new always-on gate added by this PR.
    def _closed_edged(self) -> list[dict]:
        return [_trade(2.0 if d % 6 else -1.0, d) for d in range(1, 37)]

    def _stub_registry(self, monkeypatch):
        monkeypatch.setattr(dr, "load_registry", lambda: {})
        monkeypatch.setattr(dr, "is_pre_registered", lambda lineage, reg: True)
        monkeypatch.setattr(dr, "meets_graduation", lambda stats, reg: True)

    def test_off_leaves_graduation_unchanged(self, monkeypatch):
        # Isolate the DORMANT stat_gate: use an edged fixture so the always-on
        # trade-shuffle gate (this PR) passes, then confirm the dormant DSR gate,
        # while off, adds no further restriction -- graduation is exactly
        # base_graduated AND the (always-on) trade-shuffle verdict.
        self._stub_registry(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)
        rows = ft.run_lineage_track(self._closed_edged(), window_days=30)
        assert rows[0]["trade_shuffle"]["passes"] is True  # edged fixture clears it
        assert rows[0]["graduated"] is True  # base graduation preserved (DSR gate dormant)
        assert rows[0]["stat_gate"]["abstained"] is True

    def test_no_edge_sequence_blocked_even_with_dormant_gate_off(self, monkeypatch):
        # The always-on trade-shuffle gate (this PR) blocks a no-edge sequence on its
        # own, independent of the dormant DSR gate's on/off state.
        self._stub_registry(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: False)
        rows = ft.run_lineage_track(self._closed(), window_days=30)
        assert rows[0]["stat_gate"]["abstained"] is True  # dormant gate truly is off
        assert rows[0]["trade_shuffle"]["passes"] is False  # but the new gate isn't
        assert rows[0]["graduated"] is False
        assert rows[0]["reason"].startswith("trade-shuffle gate block")

    def test_on_blocks_when_stats_fail(self, monkeypatch):
        self._stub_registry(monkeypatch)
        monkeypatch.setattr(ft, "forward_stat_gate_enforced", lambda: True)
        rows = ft.run_lineage_track(self._closed(), window_days=30)
        assert rows[0]["stat_gate"]["enforced"] is True
        assert rows[0]["stat_gate"]["passes"] is False  # dormant DSR gate's own verdict
        assert rows[0]["graduated"] is False  # blocked (both gates fail on this fixture)
        # The always-on trade-shuffle gate is checked first in the reason chain, so it
        # -- not the dormant stat_gate -- names itself as the block reason here.
        assert rows[0]["reason"].startswith("trade-shuffle gate block")
