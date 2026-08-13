"""
GT-22 follow-up: pin down OOSEvaluator._fetch_data's data-source contract.

Context
-------
An adversarial verifier on PR #498 flagged that the GT-22 fix to
MarketDataManager's IBKR duration_map (engine/data/market_data.py) is a
"shared helper" with a second caller: OOSEvaluator._fetch_data
(engine/strategies/rl_evaluator.py:257-283). Pre-fix, long-lookback IBKR
requests silently truncated to ~21 bars, so the `len(df) >= 60` check in
_fetch_data always failed and RL evaluation always fell through to
BacktestDataLoader -- accidentally, not by design. Post-fix, a real
data_manager passed to OOSEvaluator.evaluate()/_fetch_data() can now return
>=60 bars from IBKR on the first try, so the (pre-existing, documented)
"prefer data_manager, fall back to BacktestDataLoader" contract in
_fetch_data's own docstring will actually engage for the first time.

Investigation (2026-07-27) confirmed:
  1. `data_manager`-preferred / BacktestDataLoader-fallback is the
     established, intentional pattern across the RL subsystem -- the exact
     same shape appears in RLTrainer._fetch_symbol_data (rl_trainer.py).
     It is not something introduced or implied by the GT-22 fix.
  2. The ONLY production caller of OOSEvaluator.evaluate() is
     routers/strategies_router.py's POST /strategies/rl/evaluate handler,
     and it does NOT pass data_manager (calls
     `evaluator.evaluate(req.symbol, req.start_date, req.end_date)` with no
     data_manager kwarg, so it defaults to None). Today, with or without the
     GT-22 fix, that endpoint's evaluations are 100% BacktestDataLoader --
     unaffected by the market_data.py change.
  3. EvaluateRequest (the endpoint's Pydantic body) has no field to opt into
     a data_manager either, so this isn't reachable from the public API.

These tests pin both halves of the contract explicitly so the behavior is
documented and intentional rather than a silent surprise if/when a future
caller does wire data_manager through (mirroring rl_trainer.py's existing
pattern at strategies_router.py:620, which already does this for a
different RL endpoint).
"""

from __future__ import annotations

import sys
import unittest.mock as mock
from typing import Optional

import pandas as pd
import pytest

from strategies.rl_evaluator import OOSEvaluator


def _bars_df(n: int, tag: str) -> pd.DataFrame:
    """Minimal OHLCV frame, tagged via `close` values so tests can prove
    which source's data actually made it back out of _fetch_data."""
    idx = pd.date_range("2024-01-02", periods=n, freq="D")
    base = 1.0 if tag == "data_manager" else 2.0
    return pd.DataFrame(
        {
            "open": [base] * n,
            "high": [base] * n,
            "low": [base] * n,
            "close": [base] * n,
            "volume": [1000] * n,
        },
        index=idx,
    )


class _FakeDataManager:
    """Stands in for MarketDataManager -- async get_bars, configurable bar count."""

    def __init__(self, n_bars: int):
        self._n_bars = n_bars
        self.calls: list[dict] = []

    async def get_bars(self, symbol, lookback_days, timeframe, is_futures):
        self.calls.append(
            {
                "symbol": symbol,
                "lookback_days": lookback_days,
                "timeframe": timeframe,
                "is_futures": is_futures,
            }
        )
        return _bars_df(self._n_bars, tag="data_manager")


class TestFetchDataSourceContract:
    """Pins OOSEvaluator._fetch_data's data-source selection, both halves."""

    def test_production_call_path_never_passes_data_manager(self):
        """The only real caller (POST /strategies/rl/evaluate) must keep
        calling evaluate() without a data_manager kwarg. If this ever
        changes, it's an intentional decision to start using live IBKR
        data for RL validation gating and should be reviewed as such --
        not something that should slip in as an incidental diff."""
        import inspect

        from routers import strategies_router

        src = inspect.getsource(strategies_router.run_rl_evaluation)
        assert "data_manager" not in src, (
            "routers/strategies_router.py's /rl/evaluate handler now passes "
            "data_manager to OOSEvaluator.evaluate() -- this activates the "
            "data_manager-preferred path (see GT-22 PR #498 follow-up) and "
            "switches RL OOS evaluation from BacktestDataLoader to live "
            "IBKR-sourced data. That's a validation-data-provenance change; "
            "confirm it's intentional before removing this guard test."
        )

    def test_fetch_data_uses_loader_when_data_manager_is_none(self):
        """Default / current-production behavior: data_manager=None must
        route through BacktestDataLoader, unaffected by the GT-22 fix."""
        evaluator = OOSEvaluator()

        fake_loader_df = _bars_df(100, tag="loader")
        with mock.patch("backtest.data_loader.BacktestDataLoader") as MockLoader:
            MockLoader.return_value.load.return_value = fake_loader_df
            result = evaluator._fetch_data(symbol="MES", interval="1h", data_manager=None)

        assert result is not None
        assert (result["close"] == 2.0).all(), "expected loader-tagged data (close=2.0)"

    def test_fetch_data_prefers_data_manager_when_it_returns_enough_bars(self):
        """Documented, pre-existing contract (matches rl_trainer.py's
        RLTrainer pattern): when a caller supplies a data_manager that
        returns >=60 bars, that data is used and BacktestDataLoader is
        never touched. This is the behavior GT-22 unblocks for IBKR --
        intentional, not a side effect to guard against."""
        evaluator = OOSEvaluator()
        fake_dm = _FakeDataManager(n_bars=100)

        with mock.patch("backtest.data_loader.BacktestDataLoader") as MockLoader:
            result = evaluator._fetch_data(symbol="MES", interval="1h", data_manager=fake_dm)
            MockLoader.assert_not_called()

        assert result is not None
        assert (result["close"] == 1.0).all(), "expected data_manager-tagged data (close=1.0)"
        assert fake_dm.calls, "data_manager.get_bars was never called"
        assert fake_dm.calls[0]["lookback_days"] == 730

    def test_fetch_data_falls_back_to_loader_when_data_manager_returns_too_few_bars(self):
        """Even with a data_manager supplied, an insufficient (<60-bar)
        response must still fall back to BacktestDataLoader -- the len()
        gate in _fetch_data is unchanged by GT-22."""
        evaluator = OOSEvaluator()
        fake_dm = _FakeDataManager(n_bars=10)  # below the 60-bar floor

        fake_loader_df = _bars_df(100, tag="loader")
        with mock.patch("backtest.data_loader.BacktestDataLoader") as MockLoader:
            MockLoader.return_value.load.return_value = fake_loader_df
            result = evaluator._fetch_data(symbol="MES", interval="1h", data_manager=fake_dm)

        assert result is not None
        assert (result["close"] == 2.0).all(), "expected loader-tagged fallback data (close=2.0)"
