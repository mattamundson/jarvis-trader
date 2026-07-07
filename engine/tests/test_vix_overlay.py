"""Pure-function + property tests for analytics.vix_overlay.

classify_vix() and VIXState are pure (no I/O); fetch_vix()/fetch_vix_async(None)
return the documented stub (18.0 / NORMAL). The module-level _vix_cache is
cleared around every test so cache state never leaks between cases.

No network, no LLM, no data_manager — these are deterministic unit tests.
"""

import time
from datetime import datetime, timezone

import pytest

from analytics import vix_overlay
from analytics.vix_overlay import (
    VIXOverlay,
    VIXState,
    classify_vix,
    fetch_vix,
    fetch_vix_async,
)


@pytest.fixture(autouse=True)
def _clear_vix_cache():
    """Isolate every test from cache state written by fetch_vix_async/seeding."""
    vix_overlay._vix_cache.clear()
    yield
    vix_overlay._vix_cache.clear()


def _seed_cache(regime, vix_value, position_size_pct, trading_allowed):
    """Warm the module cache so get_current_state()/fetch_vix() return it."""
    vix_overlay._vix_cache["data"] = VIXState(
        vix_value=vix_value,
        regime=regime,
        classification=regime,
        position_size_pct=position_size_pct,
        trading_allowed=trading_allowed,
        timestamp=time.time(),
    )
    vix_overlay._vix_cache["fetched_at"] = time.time()


# ---------------------------------------------------------------------------
# classify_vix — every regime boundary (the < cutoffs are exclusive)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vix,regime,pct,allowed",
    [
        (0.0, "CALM", 1.0, True),
        (11.99, "CALM", 1.0, True),
        (12.0, "NORMAL", 1.0, True),  # boundary: 12 is NORMAL, not CALM
        (18.0, "NORMAL", 1.0, True),
        (19.99, "NORMAL", 1.0, True),
        (20.0, "CAUTION", 0.75, True),  # boundary: 20 is CAUTION
        (29.99, "CAUTION", 0.75, True),
        (30.0, "ELEVATED", 0.50, True),  # boundary: 30 is ELEVATED
        (39.99, "ELEVATED", 0.50, True),
        (40.0, "EXTREME", 0.0, False),  # boundary: 40 pauses trading
        (75.0, "EXTREME", 0.0, False),
    ],
)
def test_classify_vix_boundaries(vix, regime, pct, allowed):
    assert classify_vix(vix) == (regime, pct, allowed)


def test_classify_vix_extreme_halts_trading():
    """The only regime that flips trading_allowed to False is EXTREME (>=40)."""
    for v in (10.0, 15.0, 25.0, 35.0):
        assert classify_vix(v)[2] is True
    assert classify_vix(40.0)[2] is False
    assert classify_vix(40.0)[1] == 0.0


# ---------------------------------------------------------------------------
# VIXState properties
# ---------------------------------------------------------------------------
def test_vixstate_as_datetime_is_utc():
    st = VIXState(
        vix_value=18.0,
        regime="NORMAL",
        classification="NORMAL",
        position_size_pct=1.0,
        trading_allowed=True,
        timestamp=0.0,
    )
    dt = st.as_datetime
    assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert dt.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "regime", ["CALM", "NORMAL", "CAUTION", "ELEVATED", "EXTREME"]
)
def test_vixstate_description_known_regimes(regime):
    st = VIXState(
        vix_value=18.0,
        regime=regime,
        classification=regime,
        position_size_pct=1.0,
        trading_allowed=True,
        timestamp=time.time(),
    )
    assert st.description != "Unknown"
    assert st.description  # non-empty human-readable string


def test_vixstate_description_unknown_fallback():
    """An unrecognised regime must not KeyError — it falls back to 'Unknown'."""
    st = VIXState(
        vix_value=18.0,
        regime="BOGUS",
        classification="BOGUS",
        position_size_pct=1.0,
        trading_allowed=True,
        timestamp=time.time(),
    )
    assert st.description == "Unknown"


# ---------------------------------------------------------------------------
# fetch_vix (sync) — stub when cold, cache when warm
# ---------------------------------------------------------------------------
def test_fetch_vix_returns_stub_when_cache_cold():
    st = fetch_vix()
    assert st.source == "stub"
    assert st.regime == "NORMAL"
    assert st.vix_value == 18.0
    assert st.trading_allowed is True


def test_fetch_vix_returns_cache_when_warm():
    _seed_cache("CAUTION", 25.0, 0.75, True)
    st = fetch_vix()
    assert st.source == "cache"
    assert st.vix_value == 25.0
    assert st.regime == "CAUTION"
    assert st.classification == "CAUTION"


# ---------------------------------------------------------------------------
# fetch_vix_async — None data_manager yields the stub (asyncio_mode=auto)
# ---------------------------------------------------------------------------
async def test_fetch_vix_async_none_manager_returns_stub():
    st = await fetch_vix_async(None)
    assert st.source == "stub"
    assert st.regime == "NORMAL"
    assert st.vix_value == 18.0


async def test_fetch_vix_async_serves_warm_cache():
    _seed_cache("ELEVATED", 33.0, 0.50, True)
    st = await fetch_vix_async(None)  # cache hit short-circuits before manager check
    assert st.source == "cache"
    assert st.regime == "ELEVATED"
    assert st.vix_value == 33.0


# ---------------------------------------------------------------------------
# VIXOverlay trade-filtering helpers (driven off the seeded cache)
# ---------------------------------------------------------------------------
def test_overlay_adjust_position_size_extreme_returns_zero():
    _seed_cache("EXTREME", 45.0, 0.0, False)
    assert VIXOverlay().adjust_position_size(10) == 0


def test_overlay_adjust_position_size_caution_floors():
    _seed_cache("CAUTION", 25.0, 0.75, True)
    # int(10 * 0.75) == 7
    assert VIXOverlay().adjust_position_size(10) == 7


def test_overlay_adjust_position_size_floor_is_one_when_allowed():
    _seed_cache("CAUTION", 25.0, 0.75, True)
    # int(1 * 0.75) == 0, but trading is allowed so it floors at 1
    assert VIXOverlay().adjust_position_size(1) == 1


def test_overlay_should_allow_trade_blocks_extreme():
    _seed_cache("EXTREME", 45.0, 0.0, False)
    allowed, reason = VIXOverlay().should_allow_trade("LONG")
    assert allowed is False
    assert "EXTREME" in reason


def test_overlay_should_allow_trade_permits_normal():
    _seed_cache("NORMAL", 15.0, 1.0, True)
    allowed, reason = VIXOverlay().should_allow_trade("LONG")
    assert allowed is True
    assert "trading allowed" in reason


@pytest.mark.parametrize(
    "regime,vix,pct,allowed,expected",
    [
        ("CALM", 10.0, 1.0, True, "pass"),
        ("NORMAL", 15.0, 1.0, True, "pass"),
        ("CAUTION", 25.0, 0.75, True, "reduce"),
        ("ELEVATED", 33.0, 0.50, True, "block"),
        ("EXTREME", 45.0, 0.0, False, "block"),
    ],
)
def test_overlay_trade_filter(regime, vix, pct, allowed, expected):
    _seed_cache(regime, vix, pct, allowed)
    assert VIXOverlay().get_trade_filter() == expected
