"""
JARVIS TRADER — RegimeGuard Tests (T4 — close zero-test gap on safety-tier file)
=============================================================================
Covers invariants for risk/regime_guard.py:

  - trending regime (ADX > threshold) classification
  - ranging / chop regime (ADX < threshold) classification — Market Making allowed
  - is_suitable_for_mm only True when last_regime == "ranging" (conservative refusal)
  - missing / insufficient market data → safe "unknown" fallback (no exception)
  - data fetch failure (exception inside get_bars) → "unknown" fallback, no propagation
  - state of last_regime / last_check after a successful classification

Why this file matters: RegimeGuard sits in the safety tier (engine/risk/) and gates
strategy admission — a silent exception or wrong classification cascades into the
pipeline routing layer. Per .claude/rules/safety.md and rules/testing.md, every
safety-tier file must have a test. This file existed at 72 lines with zero tests.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from risk.regime_guard import RegimeGuard


def _make_adx_df(adx_value: float) -> pd.DataFrame:
    """Build a minimal pandas_ta-shaped ADX DataFrame with a known final ADX_14."""
    return pd.DataFrame(
        {
            "ADX_14": [10.0, 15.0, 20.0, adx_value],
            "DMP_14": [5.0, 6.0, 7.0, 8.0],
            "DMN_14": [4.0, 5.0, 6.0, 7.0],
        }
    )


def _make_bars(count: int = 30) -> list:
    """Build `count` bar objects with .__dict__ exposing OHLCV — what regime_guard
    expects (it iterates `b.__dict__` to build a DataFrame).
    """
    return [
        SimpleNamespace(
            timestamp=f"2026-05-20T{i:02d}:00:00",
            open=100.0 + i * 0.1,
            high=101.0 + i * 0.1,
            low=99.0 + i * 0.1,
            close=100.5 + i * 0.1,
            volume=1000.0,
        )
        for i in range(count)
    ]


@pytest.fixture
def mock_data_manager():
    """data_manager.get_bars is async — use AsyncMock."""
    mgr = MagicMock()
    mgr.get_bars = AsyncMock(return_value=_make_bars(30))
    return mgr


class TestRegimeClassification:
    """ADX-based regime classification — invariants."""

    async def test_trending_regime_when_adx_above_threshold(self, mock_data_manager, monkeypatch):
        """ADX > 25 (default threshold) → regime = 'trending'.

        Invariant: trend-day classification — mean-reversion / Market-Making strategies
        should be BLOCKED. This is enforced via is_suitable_for_mm() returning False
        when last_regime != 'ranging'.
        """
        guard = RegimeGuard(data_manager=mock_data_manager, adx_threshold=25.0)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(35.0))

        regime = await guard.get_market_regime("SPY")

        assert regime == "trending"
        assert guard.last_regime == "trending"
        # Invariant: Market Making (mean-reversion) is NOT suitable in trend day
        assert guard.is_suitable_for_mm("SPY") is False

    async def test_ranging_regime_when_adx_below_threshold(self, mock_data_manager, monkeypatch):
        """ADX < 25 → regime = 'ranging'.

        Invariant: chop classification — mean-reversion strategy entry ALLOWED.
        is_suitable_for_mm() returns True iff last_regime == 'ranging'.
        """
        guard = RegimeGuard(data_manager=mock_data_manager, adx_threshold=25.0)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(15.0))

        regime = await guard.get_market_regime("SPY")

        assert regime == "ranging"
        assert guard.last_regime == "ranging"
        # Invariant: Market Making (mean-reversion) IS suitable in chop
        assert guard.is_suitable_for_mm("SPY") is True

    async def test_threshold_boundary_exact_value_treated_as_ranging(
        self, mock_data_manager, monkeypatch
    ):
        """ADX == threshold → NOT trending (strict greater-than). Conservative refusal:
        an exactly-at-threshold ADX is classified as 'ranging' because the source
        uses `if current_adx > self.adx_threshold` (strict). The implication for the
        consumer: ambiguity at the boundary errs toward 'ranging', so a downstream
        trend strategy gating on 'trending' will refuse the entry — conservative.
        """
        guard = RegimeGuard(data_manager=mock_data_manager, adx_threshold=25.0)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(25.0))

        regime = await guard.get_market_regime("SPY")

        assert regime == "ranging"

    async def test_custom_adx_threshold_respected(self, mock_data_manager, monkeypatch):
        """Caller-supplied adx_threshold overrides default 25.0."""
        guard = RegimeGuard(data_manager=mock_data_manager, adx_threshold=40.0)
        # ADX 35 → trending under default 25, BUT ranging under custom 40
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(35.0))

        regime = await guard.get_market_regime("SPY")

        assert regime == "ranging"


class TestMissingDataFallback:
    """Safe fallback when market data is missing or malformed — no exceptions
    must escape; regime must default to 'unknown' (conservative refusal)."""

    async def test_empty_bars_returns_unknown(self, monkeypatch):
        """get_bars returns [] → 'unknown' (not crash, not 'trending')."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=[])
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"
        # Invariant: 'unknown' is NOT 'ranging' → MM strategy refused
        assert guard.is_suitable_for_mm("SPY") is False

    async def test_insufficient_bars_returns_unknown(self):
        """Fewer than 20 bars → 'unknown' (insufficient data for stable indicator)."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=_make_bars(10))
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"
        assert guard.is_suitable_for_mm("SPY") is False

    async def test_none_bars_returns_unknown(self):
        """get_bars returns None → 'unknown' (defensive against connector returning None)."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=None)
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"

    async def test_data_manager_exception_returns_unknown(self):
        """Underlying data_manager.get_bars raising → caught → 'unknown'.

        Invariant: a transient broker / data-source failure must NOT propagate
        and crash the routing layer. Safe-fallback to 'unknown' ensures every
        consumer sees a 'no decision' signal, not an exception.
        """
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(side_effect=ConnectionError("simulated broker outage"))
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"
        # last_regime should remain at its initial "unknown" state
        assert guard.last_regime == "unknown"

    async def test_adx_returns_empty_dataframe_returns_unknown(
        self, mock_data_manager, monkeypatch
    ):
        """ADX calc returning empty DataFrame → 'unknown' (no false-positive
        classification on degenerate indicator output)."""
        guard = RegimeGuard(data_manager=mock_data_manager)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: pd.DataFrame())

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"

    async def test_adx_returns_none_returns_unknown(self, mock_data_manager, monkeypatch):
        """ADX calc returning None → 'unknown' (pandas_ta can return None on insufficient data)."""
        guard = RegimeGuard(data_manager=mock_data_manager)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: None)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"


class TestInitialState:
    """Pre-classification state — guard against use-before-classify bugs."""

    def test_initial_last_regime_is_unknown(self):
        """Newly-constructed guard has last_regime='unknown' (conservative default)."""
        guard = RegimeGuard(data_manager=MagicMock())
        assert guard.last_regime == "unknown"
        assert guard.last_check is None

    def test_is_suitable_for_mm_before_any_classification(self):
        """is_suitable_for_mm called before get_market_regime → False.

        Invariant: never green-light Market Making (mean-reversion) without
        a positive 'ranging' classification first.
        """
        guard = RegimeGuard(data_manager=MagicMock())
        assert guard.is_suitable_for_mm("SPY") is False


class TestLastCheckTracking:
    """last_check timestamp updated on successful classifications only."""

    async def test_last_check_updated_after_successful_classification(
        self, mock_data_manager, monkeypatch
    ):
        """Successful classification sets last_check to current datetime."""
        guard = RegimeGuard(data_manager=mock_data_manager)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(30.0))

        assert guard.last_check is None
        await guard.get_market_regime("SPY")

        assert guard.last_check is not None
        assert isinstance(guard.last_check, datetime)


class TestProductionDataFrameInterface:
    """Regression-lock for the 2026-05-20 production bug.

    The production `MarketDataManager.get_bars()` returns a `pd.DataFrame`
    (engine/data/market_data.py:773). Earlier revisions of RegimeGuard assumed
    a list-of-bar-objects interface and did `if not bars or len(bars) < 20`,
    which raises ValueError on a DataFrame ("truth value is ambiguous"). The
    bare except in get_market_regime swallowed that ValueError and returned
    "unknown" for every call — silently blocking mean-reversion strategy
    entry regardless of actual market regime. The existing tests above didn't
    catch it because they mocked get_bars to return a list of SimpleNamespace.

    These tests pass a REAL pd.DataFrame and verify regime classification
    actually completes. If any of these starts returning 'unknown' from a
    valid DataFrame, the production bug has been reintroduced.
    """

    @staticmethod
    def _ohlcv_dataframe(count: int = 30, trending: bool = False) -> pd.DataFrame:
        """Build a real OHLCV DataFrame in the shape get_bars() returns."""
        import numpy as np

        rng = np.random.default_rng(42)
        if trending:
            base_closes = 100.0 + np.linspace(0, 50, count)  # strong uptrend
        else:
            base_closes = 100.0 + rng.standard_normal(count) * 0.5  # chop
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-05-20", periods=count, freq="1h"),
                "open": base_closes - 0.1,
                "high": base_closes + 0.5,
                "low": base_closes - 0.5,
                "close": base_closes,
                "volume": rng.integers(1000, 10000, count).astype(float),
            }
        )

    async def test_dataframe_input_does_not_raise_truthiness_valueerror(self, monkeypatch):
        """Production path: get_bars returns pd.DataFrame.

        Pre-fix: `if not bars` on a DataFrame raised ValueError → silent unknown.
        Post-fix: must classify normally and return 'trending' or 'ranging'.
        """
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=self._ohlcv_dataframe(30))
        guard = RegimeGuard(data_manager=mgr)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(15.0))

        regime = await guard.get_market_regime("SPY")

        # Must classify, not silently fall back to 'unknown'
        assert regime in ("trending", "ranging"), (
            f"DataFrame interface broken — got '{regime}' (expected trending/ranging). "
            f"Likely a regression of the 2026-05-20 truthiness bug."
        )
        assert regime == "ranging"  # ADX 15 < threshold 25
        assert guard.last_check is not None

    async def test_dataframe_input_classifies_trending(self, monkeypatch):
        """Real DataFrame + ADX > threshold → 'trending'."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=self._ohlcv_dataframe(30, trending=True))
        guard = RegimeGuard(data_manager=mgr)
        monkeypatch.setattr(guard.indicators, "adx", lambda *a, **kw: _make_adx_df(35.0))

        regime = await guard.get_market_regime("SPY")

        assert regime == "trending"
        assert guard.is_suitable_for_mm("SPY") is False

    async def test_empty_dataframe_returns_unknown(self):
        """Real empty DataFrame → 'unknown' (no truthiness exception)."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=pd.DataFrame())
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"

    async def test_short_dataframe_returns_unknown(self):
        """DataFrame with <20 rows → 'unknown' (insufficient for stable ADX)."""
        mgr = MagicMock()
        mgr.get_bars = AsyncMock(return_value=self._ohlcv_dataframe(10))
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"

    async def test_dataframe_missing_ohlc_columns_returns_unknown(self, monkeypatch):
        """DataFrame without OHLC columns → 'unknown' (no KeyError crash).

        Guards against CSV-cache schema drift or non-OHLCV connector returns.
        """
        mgr = MagicMock()
        # DataFrame with 25 rows but missing 'high', 'low', 'close'
        mgr.get_bars = AsyncMock(
            return_value=pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-05-20", periods=25, freq="1h"),
                    "value": range(25),
                }
            )
        )
        guard = RegimeGuard(data_manager=mgr)

        regime = await guard.get_market_regime("SPY")

        assert regime == "unknown"
        # Must NOT have updated last_regime — the unknown is from the guard, not
        # a successful classification.
        assert guard.last_regime == "unknown"
