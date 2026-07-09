"""Integration-glue test for LiveAuctionDataProvider using synthetic bars.

This does NOT verify real-world numeric accuracy (needs live IB Gateway + real
market data — that is the host smoke test documented in
data/auction_bias_provider.py and the design doc). It DOES execute the actual
control flow against synthetic data + the real backtest.tpo_profile /
wilder_atr functions and the real CoreyAuctionReport dataclass, catching
integration bugs (wrong column names, bad NaN handling, wrong await usage,
misspelled dataclass attributes) that a pure read-through cannot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from agents.corey_auction_analyst import CoreyAuctionReport
from analysis.auction_bias import synthesize_auction_bias
from data.auction_bias_provider import LiveAuctionDataProvider


def _daily_bars(n=25, start=7500.0):
    rows = []
    price = start
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i in range(n):
        high = price + 15
        low = price - 10
        rows.append(
            {
                "timestamp": base + timedelta(days=i),
                "open": price,
                "high": high,
                "low": low,
                "close": price + 2,
                "volume": 1000,
            }
        )
        price += 3
    return pd.DataFrame(rows)


def _intraday_bars_two_sessions():
    """Two distinct calendar-day sessions of 5-min bars, so compute_tpo_profile's
    shift(1) has a defined prior-session row for the second day."""
    rows = []
    day1 = datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc)  # 9:30 CT
    prices_day1 = [7500, 7505, 7510, 7515, 7520, 7515, 7510, 7505, 7500, 7495]
    for i, p in enumerate(prices_day1):
        ts = day1 + timedelta(minutes=5 * i)
        rows.append({"timestamp": ts, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 500})

    day2 = datetime(2026, 7, 8, 14, 30, tzinfo=timezone.utc)
    prices_day2 = [7520, 7515, 7510, 7505, 7500, 7495, 7490, 7485, 7480, 7526.75]
    for i, p in enumerate(prices_day2):
        ts = day2 + timedelta(minutes=5 * i)
        rows.append({"timestamp": ts, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 500})

    return pd.DataFrame(rows)


class FakeIBKR:
    is_connected = True


class FakeDataManager:
    def __init__(self):
        self.ibkr = FakeIBKR()

    async def get_current_price(self, symbol, is_futures=False):
        return {"last_price": 7526.75, "prev_close": 7551.75, "source": "ibkr"}

    async def get_bars(self, symbol, lookback_days=30, timeframe="5m", is_futures=False):
        if timeframe == "1d":
            return _daily_bars()
        return _intraday_bars_two_sessions()


class CachedDailyBarsDataManager(FakeDataManager):
    """Price leg reports live "ibkr", but the daily bars fell back to the
    SQLite cache tier -- the scenario Codex flagged (PR #315)."""

    async def get_bars(self, symbol, lookback_days=30, timeframe="5m", is_futures=False):
        if timeframe == "1d":
            df = _daily_bars()
            df.attrs["source"] = "sqlite_cache"
            return df
        return _intraday_bars_two_sessions()


class CachedIntradayBarsDataManager(FakeDataManager):
    async def get_bars(self, symbol, lookback_days=30, timeframe="5m", is_futures=False):
        if timeframe == "1d":
            return _daily_bars()
        df = _intraday_bars_two_sessions()
        df.attrs["source"] = "csv_cache"
        return df


class FakeCoreyAgent:
    async def analyze(self, symbol, current_price=0.0, atr=0.0, hp_context=None, **kwargs):
        return CoreyAuctionReport(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            signal=-0.5,
            confidence=0.6,
            session_type="RTH",
            directional_bias="bearish",
            key_levels=[7546.25, 7530.75],
            active_bot_signal={},
            bot_win_rate=0.55,
            alignment_score=-0.3,
            ib_bias="below_ib",
            corey_quote="sellers in control",
            summary="bearish auction",
            reasoning="test fixture",
            data_quality="full",
            sentiment_stale=False,
            sentiment_age_days=1,
        )


@pytest.mark.asyncio
async def test_get_inputs_returns_well_formed_payload():
    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["price"] == 7526.75
    # Derived from daily bars (_prior_close_from_daily), NOT the ticker's
    # prev_close (7551.75) -- the daily bar series is the reliable prior-
    # session-close source; see the Codex review finding on this PR.
    assert raw["prior_close"] == 7574.0
    assert raw["source"] == "ibkr"
    assert raw["ibkr_connected"] is True
    assert isinstance(raw["atr"], float) and raw["atr"] > 0
    assert isinstance(raw["day_range"], float)


@pytest.mark.asyncio
async def test_day_range_uses_intraday_session_not_daily_bar():
    """Codex review finding (PR #315), second pass: day_range must reflect
    today's actual intraday range, not the daily bar's high-low, which can be
    a completed (and different) session's range. The default fixture's daily
    bar would give 25.0; the correct intraday-derived value is 48.75."""
    daily = _daily_bars()
    last = daily.iloc[-1]
    stale_daily_derived_range = float(last["high"] - last["low"])

    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw["day_range"] != stale_daily_derived_range
    assert raw["day_range"] == 48.75


@pytest.mark.asyncio
async def test_prior_close_ignores_unreliable_ticker_prev_close():
    """Codex review finding on this PR: get_current_price()'s prev_close can be
    a stale/wrong artifact (IBKR snapshot fallback's previous-hour close, or
    None on TradingView/Schwab) -- NOT the true prior daily-session close that
    saty_atr_levels() needs. Confirms the daily-bar-derived value wins even
    when the ticker's prev_close is wildly different or absent."""

    class BadTickerPrevCloseDataManager(FakeDataManager):
        async def get_current_price(self, symbol, is_futures=False):
            # A plausible real-world failure: an hourly close far from the
            # true prior daily session close, or None entirely.
            return {"last_price": 7526.75, "prev_close": 1.0, "source": "ibkr"}

    provider = LiveAuctionDataProvider(BadTickerPrevCloseDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["prior_close"] == 7574.0  # from daily bars, NOT the bogus 1.0


@pytest.mark.asyncio
async def test_prior_close_falls_back_to_ticker_when_daily_bars_unavailable():
    class NoDailyBarsDataManager(FakeDataManager):
        async def get_bars(self, symbol, lookback_days=30, timeframe="5m", is_futures=False):
            if timeframe == "1d":
                return pd.DataFrame()  # empty -- feed unavailable
            return _intraday_bars_two_sessions()

    provider = LiveAuctionDataProvider(NoDailyBarsDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["prior_close"] == 7551.75  # ticker prev_close, the documented fallback
    assert raw["atr"] is None  # no daily bars -> no ATR either


@pytest.mark.asyncio
async def test_provenance_downgraded_when_daily_bars_are_cached():
    """Codex review finding (PR #315): a live price snapshot must not badge the
    whole payload LIVE when the Saty/TPO numbers actually came from cached
    daily bars."""
    provider = LiveAuctionDataProvider(CachedDailyBarsDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["source"] == "sqlite_cache"  # NOT "ibkr", despite the live price tick


@pytest.mark.asyncio
async def test_provenance_downgraded_when_intraday_bars_are_cached():
    provider = LiveAuctionDataProvider(CachedIntradayBarsDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["source"] == "csv_cache"


@pytest.mark.asyncio
async def test_provenance_stays_live_when_both_bar_legs_are_fresh():
    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["source"] == "ibkr"  # unchanged: neither bar leg is a cache tier


@pytest.mark.asyncio
async def test_tpo_failed_survives_intraday_bounce_back_across_fail_target():
    """Codex review finding (PR #315): passing only the last price into
    derive_tpo_failed means a session that breached fail_target and then
    pulled back reports failed=False, losing the breach. This fixture is a
    genuine regression check -- the exact prices below were verified (see PR
    history) to produce imbalance=BEAR_IMBAL, fail_target=7504.0, where the
    session HIGH (7513, bar 5) breaches fail_target but the LAST bar's close
    (7485) does not: a last-price-only check would wrongly report
    failed=False, while the session-extreme check correctly reports True."""

    class BreachedThenPulledBackDataManager(FakeDataManager):
        async def get_bars(self, symbol, lookback_days=30, timeframe="5m", is_futures=False):
            if timeframe == "1d":
                return _daily_bars()
            rows = []
            day2 = datetime(2026, 7, 8, 14, 30, tzinfo=timezone.utc)
            prices = [7490, 7495, 7500, 7510, 7512, 7505, 7498, 7492, 7488, 7485]
            for i, p in enumerate(prices):
                ts = day2 + timedelta(minutes=5 * i)
                rows.append(
                    {"timestamp": ts, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 500}
                )
            base = _intraday_bars_two_sessions()
            day1 = base[base["timestamp"] < day2]
            return pd.concat([day1, pd.DataFrame(rows)], ignore_index=True)

    provider = LiveAuctionDataProvider(BreachedThenPulledBackDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw is not None
    assert raw["tpo"] is not None
    assert raw["tpo"]["fail_target"] == 7504.0
    assert raw["tpo"]["failed"] is True  # the breach at bar 5 (high=7513) must not be forgotten


def test_prior_close_from_daily_excludes_todays_still_forming_bar_when_market_open(monkeypatch):
    """If the feed includes an in-progress "today" bar as the last row AND the
    futures market is currently open, the prior close must come from the last
    COMPLETED session, not that partial bar."""
    monkeypatch.setattr("scanner.signal_scanner._is_futures_market_hours", lambda: True)
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame(
        [
            {"timestamp": now - pd.Timedelta(days=2), "close": 100.0},
            {"timestamp": now - pd.Timedelta(days=1), "close": 200.0},  # true prior close
            {"timestamp": now, "close": 999.0},  # today's partial bar -- must be excluded
        ]
    )
    assert LiveAuctionDataProvider._prior_close_from_daily(df) == 200.0


def test_prior_close_from_daily_includes_todays_bar_when_market_closed(monkeypatch):
    """Codex review finding (PR #315), second pass: in the after-close window
    (CME Globex session already settled but still "today" in UTC), a bar dated
    today IS the true prior close, not the day before it."""
    monkeypatch.setattr("scanner.signal_scanner._is_futures_market_hours", lambda: False)
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame(
        [
            {"timestamp": now - pd.Timedelta(days=2), "close": 100.0},
            {"timestamp": now - pd.Timedelta(days=1), "close": 200.0},
            {"timestamp": now, "close": 300.0},  # settled today's session -- market is closed
        ]
    )
    assert LiveAuctionDataProvider._prior_close_from_daily(df) == 300.0


def test_prior_close_from_daily_falls_back_to_last_bar_when_feed_excludes_today(monkeypatch):
    """If the feed already excludes today (all bars strictly in the past),
    the last bar IS the prior completed session -- use it directly,
    regardless of market-hours state."""
    monkeypatch.setattr("scanner.signal_scanner._is_futures_market_hours", lambda: True)
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame(
        [
            {"timestamp": now - pd.Timedelta(days=3), "close": 100.0},
            {"timestamp": now - pd.Timedelta(days=2), "close": 200.0},
        ]
    )
    assert LiveAuctionDataProvider._prior_close_from_daily(df) == 200.0


@pytest.mark.asyncio
async def test_corey_shelves_are_deliberately_unset():
    # key_levels is populated on the fixture report, but the provider must NOT
    # guess a sellers_in_control_below / buyers_offside_below mapping from it.
    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    assert raw["corey"]["bias"] == "bearish"
    assert raw["corey"]["sellers_in_control_below"] is None
    assert raw["corey"]["buyers_offside_below"] is None


@pytest.mark.asyncio
async def test_tpo_dict_is_none_or_well_formed():
    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    # With only 2 synthetic sessions, compute_tpo_profile's prior-session shift
    # is defined for day 2 -> tpo should be populated (not silently dropped).
    assert raw["tpo"] is not None
    assert set(raw["tpo"].keys()) == {"value_area", "profile_target", "fail_target", "failed"}
    assert isinstance(raw["tpo"]["failed"], bool)


@pytest.mark.asyncio
async def test_payload_flows_cleanly_into_synthesize_auction_bias():
    """The real end-to-end glue: provider output -> synthesis, no exceptions,
    no NaN/None leaking into the numeric fields synthesize_auction_bias expects."""
    provider = LiveAuctionDataProvider(FakeDataManager(), FakeCoreyAgent())
    raw = await provider.get_inputs("MES")

    payload = synthesize_auction_bias(
        symbol="MES",
        price=raw["price"],
        prior_close=raw["prior_close"],
        atr=raw["atr"],
        day_range=raw["day_range"],
        tpo=raw["tpo"],
        corey=raw["corey"],
    )
    assert payload["saty"]["bias"] in ("long", "short", "neutral")
    assert payload["synthesis"]["line_in_sand"] is not None
    assert payload["engine_derived"] is True


@pytest.mark.asyncio
async def test_missing_price_returns_none():
    class NoPriceDataManager(FakeDataManager):
        async def get_current_price(self, symbol, is_futures=False):
            return {"last_price": None, "prev_close": None, "source": "unavailable"}

    provider = LiveAuctionDataProvider(NoPriceDataManager(), FakeCoreyAgent())
    assert await provider.get_inputs("MES") is None


@pytest.mark.asyncio
async def test_corey_failure_degrades_gracefully():
    class BrokenCoreyAgent(FakeCoreyAgent):
        async def analyze(self, *args, **kwargs):
            raise RuntimeError("db locked")

    provider = LiveAuctionDataProvider(FakeDataManager(), BrokenCoreyAgent())
    raw = await provider.get_inputs("MES")
    assert raw is not None  # price/ATR/TPO still usable even if Corey errors
    assert raw["corey"] is None
