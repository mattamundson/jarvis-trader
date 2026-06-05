"""Regression: RLExecutor must call IBKRDataConnector.is_connected() (snake_case).

Bug (2026-06-05, live log): `_fetch_latest_bars` called `ibkr.isConnected()`
(ib_insync's raw IB camelCase API), but `data_manager.ibkr` is our
`IBKRDataConnector` wrapper whose method is `is_connected()`. Every
`RLExecutor.run_once` raised `'IBKRDataConnector' object has no attribute
'isConnected'`, was swallowed, and fell through to Polygon — so the IBKR bar
path was dead even when IBKR was connected.

These tests use a fake connector that exposes ONLY `is_connected` (exactly
like the real wrapper) so the camelCase call would raise AttributeError and the
IBKR path would be skipped.
"""

import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.rl_executor import RLExecutor  # noqa: E402


def _bars(n: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [100.5 + i * 0.1 for i in range(n)],
            "low": [99.5 + i * 0.1 for i in range(n)],
            "close": [100.2 + i * 0.1 for i in range(n)],
            "volume": [1000 + i for i in range(n)],
        }
    )


class _FakeConnector:
    """Mirrors IBKRDataConnector: exposes is_connected(), NOT isConnected()."""

    def __init__(self, connected: bool):
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


class _FakeDataManager:
    def __init__(self, connected: bool, bars: pd.DataFrame):
        self.ibkr = _FakeConnector(connected)
        self._bars = bars
        self.get_historical_bars_called = False

    async def get_historical_bars(self, symbol, bar_size, n_bars):
        self.get_historical_bars_called = True
        return self._bars


@pytest.fixture
def executor_factory(tmp_path):
    def _make(dm):
        # model_path points nowhere → stays in simulation mode; _fetch_latest_bars
        # does not load the model, so construction is cheap and offline.
        return RLExecutor(symbol="MES", model_path=str(tmp_path / "no_model"), data_manager=dm)

    return _make


def test_connector_wrapper_has_no_camelcase_attr():
    """Guards the assumption the bug depended on: the wrapper has no isConnected."""
    c = _FakeConnector(True)
    assert hasattr(c, "is_connected")
    assert not hasattr(c, "isConnected")


def test_ibkr_path_taken_when_connected(executor_factory):
    dm = _FakeDataManager(connected=True, bars=_bars(80))
    ex = executor_factory(dm)

    df = ex._fetch_latest_bars(n=150)

    # IBKR path must have been used (no AttributeError on is_connected()).
    assert dm.get_historical_bars_called is True
    assert df is not None and len(df) >= 60
    assert list(df.columns) == [c.lower() for c in df.columns]


def test_ibkr_path_skipped_when_disconnected(executor_factory):
    # is_connected() returns False → IBKR fetch must be skipped, not error.
    dm = _FakeDataManager(connected=False, bars=_bars(80))
    ex = executor_factory(dm)

    # Should not raise and should not call the IBKR historical fetch.
    ex._fetch_latest_bars(n=150)
    assert dm.get_historical_bars_called is False
