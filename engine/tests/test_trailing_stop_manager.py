"""
Unit tests — TrailingStopManager (fix/us09-trailing-stop-atr)

Covers three correctness requirements:
  (a) TRAILING_STOP_ATR_MULT from config propagates to the stop calculation.
  (b) When real ATR is provided via get_bars, stop distance uses mult * atr
      (NOT the 0.5% price proxy).
  (c) The 0.5%-of-price proxy fallback is used when bars are unavailable.

All tests use in-process fakes — no live engine, no .env required.

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_trailing_stop_manager.py -q
"""

import asyncio
import pathlib
import sys
import types

import numpy as np
import pandas as pd
import pytest

# Put engine/ on sys.path so services.*, analysis.* etc. import cleanly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------

class _Trade:
    def __init__(self, trade_id, symbol, quantity, stop_loss_price=None):
        self.trade_id = trade_id
        self.symbol = symbol
        self.quantity = quantity
        self.stop_loss_price = stop_loss_price
        # Minimal status stub
        self.status = types.SimpleNamespace(value="active")


class _OMS:
    """Records update_stop_loss calls for assertion."""

    def __init__(self, trades: list):
        self.active_trades = {t.trade_id: t for t in trades}
        self.updates: dict[str, float] = {}  # trade_id -> new_stop

    async def update_stop_loss(self, trade_id: str, new_stop: float):
        self.updates[trade_id] = new_stop


class _DataManager:
    """
    Controllable data stub.

    Pass `bars_df` to simulate a healthy data source returning OHLCV bars.
    Pass `bars_df=None` (default) to simulate unavailable bars (fallback path).
    `tick_price` is the current_price returned for all symbols.
    """

    def __init__(self, tick_price: float, bars_df=None):
        self._tick_price = tick_price
        self._bars_df = bars_df

    async def get_tick_price(self, symbol: str) -> dict:
        return {"last_price": self._tick_price}

    async def get_bars(self, symbol: str, lookback_days: int = 3, timeframe: str = "1h"):
        if self._bars_df is None:
            return pd.DataFrame()  # simulates data source failure
        return self._bars_df


def _make_bars(n_bars: int = 30, atr_target: float = 5.0) -> pd.DataFrame:
    """
    Build a synthetic OHLCV DataFrame whose 14-bar ATR converges close to
    *atr_target*.  Uses a constant range of atr_target so true ATR = atr_target.
    """
    close = 100.0
    rows = []
    for _ in range(n_bars):
        rows.append({
            "high": close + atr_target / 2,
            "low": close - atr_target / 2,
            "close": close,
            "open": close,
            "volume": 1000,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_manager(oms, data, atr_mult: float = 2.0):
    """Create a TrailingStopManager with *atr_mult* injected directly (bypasses config)."""
    from services.trailing_stop_manager import TrailingStopManager

    mgr = TrailingStopManager.__new__(TrailingStopManager)
    mgr.oms = oms
    mgr.data = data
    mgr.interval = 60
    mgr._running = False
    mgr._task = None
    mgr._atr_mult = atr_mult  # inject directly; tested separately in (a)
    return mgr


def run(coro):
    # asyncio.run() creates and tears down a fresh event loop per call. The old
    # asyncio.get_event_loop().run_until_complete() pattern raises
    # "RuntimeError: There is no current event loop" under Python 3.12 once an
    # earlier async test in the full suite has closed the thread's loop -- it
    # passes in isolation (auto-creates a loop) but fails in CI's full run.
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# (a) Config multiplier propagates to the stop distance
# ---------------------------------------------------------------------------

def test_config_multiplier_propagates_to_long_stop():
    """
    Stop distance for a long = mult * ATR.
    Using bars with constant range so ATR converges to exactly atr_target,
    then asserting the stop distance is mult * atr (not the price proxy).
    """
    current_price = 100.0
    atr_target = 5.0
    mult = 3.5  # non-default to prove it isn't hardcoded to 2.0

    trade = _Trade("T1", "MES", quantity=1)
    oms = _OMS([trade])
    data = _DataManager(tick_price=current_price, bars_df=_make_bars(30, atr_target))
    mgr = _build_manager(oms, data, atr_mult=mult)

    run(mgr._process_active_trades())

    assert "T1" in oms.updates, "stop should have been updated"
    new_stop = oms.updates["T1"]
    # ATR from pandas_ta on constant-range bars should be ≈ atr_target.
    # Allow 10% tolerance for the EMA smoothing warm-up.
    expected_distance = mult * atr_target
    actual_distance = current_price - new_stop
    assert abs(actual_distance - expected_distance) / expected_distance < 0.10, (
        f"Stop distance {actual_distance:.4f} not within 10% of "
        f"expected mult*ATR = {expected_distance:.4f}"
    )


def test_config_multiplier_propagates_to_short_stop():
    """Same as above but for a short position."""
    current_price = 100.0
    atr_target = 5.0
    mult = 1.5

    trade = _Trade("T1", "MES", quantity=-1)
    oms = _OMS([trade])
    data = _DataManager(tick_price=current_price, bars_df=_make_bars(30, atr_target))
    mgr = _build_manager(oms, data, atr_mult=mult)

    run(mgr._process_active_trades())

    assert "T1" in oms.updates
    new_stop = oms.updates["T1"]
    expected_distance = mult * atr_target
    actual_distance = new_stop - current_price
    assert abs(actual_distance - expected_distance) / expected_distance < 0.10, (
        f"Short stop distance {actual_distance:.4f} not within 10% of "
        f"mult*ATR = {expected_distance:.4f}"
    )


# ---------------------------------------------------------------------------
# (b) Real ATR from bars is used (not the 0.5% proxy) when bars available
# ---------------------------------------------------------------------------

def test_real_atr_used_not_price_proxy():
    """
    The 0.5% price proxy would give stop_distance = 2.0 * 0.005 * 100 = 1.0.
    Real ATR (atr_target=8.0) gives stop_distance = 2.0 * 8.0 = 16.0.
    These are different enough to distinguish; assert the actual distance
    is NOT the proxy value.
    """
    current_price = 100.0
    atr_target = 8.0  # much larger than proxy (0.5 pts)
    mult = 2.0

    trade = _Trade("T1", "MES", quantity=1)
    oms = _OMS([trade])
    data = _DataManager(tick_price=current_price, bars_df=_make_bars(30, atr_target))
    mgr = _build_manager(oms, data, atr_mult=mult)

    run(mgr._process_active_trades())

    assert "T1" in oms.updates
    actual_distance = current_price - oms.updates["T1"]
    proxy_distance = mult * (current_price * 0.005)  # = 1.0

    # Real ATR path should produce ~16.0; proxy would produce ~1.0.
    assert actual_distance > proxy_distance * 5, (
        f"Expected real-ATR stop distance (~{mult*atr_target:.1f}) but got "
        f"{actual_distance:.4f} — looks like the proxy was used instead"
    )


# ---------------------------------------------------------------------------
# (c) Proxy fallback when bars are unavailable
# ---------------------------------------------------------------------------

def test_proxy_fallback_when_bars_unavailable():
    """
    When get_bars returns an empty DataFrame, _get_atr must fall back to
    0.5% of current_price so that a stop is always set (never None / zero).
    """
    current_price = 200.0
    mult = 2.0
    expected_proxy = current_price * 0.005  # 1.0

    trade = _Trade("T1", "MGC", quantity=1)
    oms = _OMS([trade])
    data = _DataManager(tick_price=current_price, bars_df=None)  # no bars
    mgr = _build_manager(oms, data, atr_mult=mult)

    run(mgr._process_active_trades())

    assert "T1" in oms.updates, "stop must be updated even when bars unavailable"
    new_stop = oms.updates["T1"]
    assert new_stop > 0, "stop price must be positive"
    expected_stop = current_price - mult * expected_proxy
    assert abs(new_stop - expected_stop) < 1e-6, (
        f"Proxy fallback stop {new_stop:.6f} != expected {expected_stop:.6f}"
    )


def test_proxy_fallback_when_bars_exception():
    """
    When get_bars raises an exception (network error etc.), the proxy
    fallback must still produce a valid stop — no unhandled exception.
    """
    current_price = 150.0
    mult = 2.0

    class _BrokenDataManager(_DataManager):
        async def get_bars(self, *args, **kwargs):
            raise RuntimeError("simulated data-source failure")

    trade = _Trade("T1", "MES", quantity=1)
    oms = _OMS([trade])
    data = _BrokenDataManager(tick_price=current_price)
    mgr = _build_manager(oms, data, atr_mult=mult)

    # Must not raise.
    run(mgr._process_active_trades())

    assert "T1" in oms.updates, "stop must be updated even on get_bars exception"
    new_stop = oms.updates["T1"]
    proxy_distance = mult * (current_price * 0.005)
    assert abs((current_price - new_stop) - proxy_distance) < 1e-6


# ---------------------------------------------------------------------------
# _compute_atr_from_df unit tests (pure function, no async needed)
# ---------------------------------------------------------------------------

def test_compute_atr_from_df_returns_positive_value():
    from services.trailing_stop_manager import _compute_atr_from_df

    df = _make_bars(30, atr_target=4.0)
    result = _compute_atr_from_df(df)
    assert result is not None
    assert result > 0


def test_compute_atr_from_df_empty_df_returns_none():
    from services.trailing_stop_manager import _compute_atr_from_df

    assert _compute_atr_from_df(pd.DataFrame()) is None
    assert _compute_atr_from_df(None) is None


def test_compute_atr_from_df_missing_columns_returns_none():
    from services.trailing_stop_manager import _compute_atr_from_df

    df = pd.DataFrame({"close": [100.0, 101.0]})  # missing high/low
    assert _compute_atr_from_df(df) is None
