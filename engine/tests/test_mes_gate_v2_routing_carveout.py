"""Regression tests for the MES gate-v2 routing enforcement carve-out.

`GATE_V2_ENFORCE_ROUTING=1` calls `is_ungate_eligible()` directly from the
signal layer. Without a carve-out that bypasses the MES exemption already in
`gate_v2_policy.is_strategy_authorized()` and silently forces 100% of MES trend
entries to NO_TRADE whenever MES has only FAIL/INSUFFICIENT_SAMPLE trend verdicts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _ohlcv_df(rows: int = 240) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="1h")
    close = np.linspace(7000.0, 7200.0, rows)
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.full(rows, 10_000),
        },
        index=dates,
    )


def _entry_frame(index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_signal": ["ENTRY_NOW"] * len(index),
            "exit_signal": ["NO_EXIT"] * len(index),
        },
        index=index,
    )


def _patch_trend(monkeypatch, eligible: bool):
    import backtest.gate_v2_policy as gate_v2_policy
    import backtest.trend_signals as trend_signals

    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    monkeypatch.setattr(gate_v2_policy, "is_ungate_eligible", lambda *a, **k: eligible)
    monkeypatch.setattr(trend_signals, "get_sma_trend_params", lambda symbol: {"fast": 50, "slow": 200})
    monkeypatch.setattr(
        trend_signals, "generate_sma_trend_signals", lambda frame, **kwargs: _entry_frame(frame.index)
    )


def test_mes_not_forced_no_trade_when_gate_v2_routing_enforced(monkeypatch):
    """MES keeps its entries even when the dynamic verdict layer would deny.

    Locks Amo's standing MES directive at the layer that diverged from
    gate_v2_policy.is_strategy_authorized(): only the verdict check is bypassed.
    """
    import backtest.signals as signals

    _patch_trend(monkeypatch, eligible=False)
    monkeypatch.setattr(signals, "DO_NOT_TRADE_SYMBOLS", frozenset())

    out = signals.generate_instrument_signals(_ohlcv_df(), "MES")

    assert (out["entry_signal"] == "ENTRY_NOW").all()


def test_mes_carveout_is_case_insensitive(monkeypatch):
    import backtest.signals as signals

    assert signals._is_mes_gate_v2_verdict_exempt("mes") is True
    assert signals._is_mes_gate_v2_verdict_exempt("MES") is True
    assert signals._is_mes_gate_v2_verdict_exempt("MGC") is False


def test_non_mes_symbol_still_denied_when_gate_v2_routing_enforced(monkeypatch):
    """The MES carve-out must not weaken fail-closed enforcement for anything else."""
    import backtest.signals as signals

    _patch_trend(monkeypatch, eligible=False)
    monkeypatch.setattr(signals, "TREND_INSTRUMENTS", frozenset({"FOO"}))
    monkeypatch.setattr(signals, "DO_NOT_TRADE_SYMBOLS", frozenset())

    out = signals.generate_instrument_signals(_ohlcv_df(), "FOO")

    assert (out["entry_signal"] == "NO_TRADE").all()
    assert (out["exit_signal"] == "NO_EXIT").all()


def test_do_not_trade_still_wins_before_mes_carveout(monkeypatch):
    """The static blocklist stays higher priority than any gate-v2 exemption."""
    import backtest.signals as signals

    _patch_trend(monkeypatch, eligible=True)
    monkeypatch.setattr(signals, "DO_NOT_TRADE_SYMBOLS", frozenset({"MES"}))

    out = signals.generate_instrument_signals(_ohlcv_df(), "MES")

    assert (out["entry_signal"] == "NO_TRADE").all()
    assert (out["exit_signal"] == "NO_EXIT").all()
