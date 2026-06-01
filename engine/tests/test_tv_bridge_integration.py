"""
Integration tests for the TradingView indicator bridge chain:
  TVIndicatorBridge → TradingViewFeed → TechnicalAnalystAgent / CoreyAuctionAnalyst

All subprocess calls are mocked — no real TV CLI is ever invoked.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data.tv_indicator_bridge import (
    TVIndicatorBridge,
    TVIndicatorSnapshot,
    get_tv_bridge,
)

# ──────────────────────────────────────────────────────────────────────────
# Helpers — build a mocked bridge whose _run_tv / _read_* return canned data
# ──────────────────────────────────────────────────────────────────────────


def _canned_manifest_labels():
    """Return a list of manifest-style label dicts the parser understands."""
    return [
        {"text": "STC_VALUE: 73.5"},
        {"text": "STC_STATE: BULLISH"},
        {"text": "COMP_SCORE: 0.42"},
        {"text": "COMP_REGIME: TRENDING_BULL"},
        {"text": "ATR_VALUE: 24.80"},
        {"text": "IB_HIGH: 5818.00"},
        {"text": "IB_LOW: 5808.25"},
        {"text": "IB_RANGE: 9.75"},
        {"text": "PHASE_VALUE: 23.5"},
        {"text": "PHASE_COMPRESSED: false"},
        {"text": "COREY_SCORE: 0.31"},
        {"text": "COREY_BIAS: BULL"},
        {"text": "VWAP: 5815.25"},
    ]


def _make_bridge_with_manifest(labels=None, tables=None) -> TVIndicatorBridge:
    """Build a bridge whose availability and readers return canned data."""
    bridge = TVIndicatorBridge()
    # Force "available" state
    bridge._available = True
    bridge._manifest_available = True
    # Clear any lingering cache
    bridge._cache.clear()

    # Patch the internal readers to return canned manifest content
    bridge._read_labels = MagicMock(return_value=labels or _canned_manifest_labels())  # type: ignore[assignment]
    bridge._read_tables = MagicMock(return_value=tables or [])  # type: ignore[assignment]
    return bridge


# ──────────────────────────────────────────────────────────────────────────
# 1. Unavailable path — graceful no-crash
# ──────────────────────────────────────────────────────────────────────────


def test_bridge_unavailable_graceful():
    """When TradingView is offline, get_snapshot returns unavailable stub."""
    bridge = TVIndicatorBridge()
    bridge._available = False  # force unavailable
    bridge._cache.clear()

    snap = bridge.get_snapshot("MES")
    assert snap is not None
    assert snap.data_quality == "unavailable"
    assert snap.stc_value is None
    assert snap.composite_score is None
    assert snap.ib_high is None


# ──────────────────────────────────────────────────────────────────────────
# 2. Parse label helpers — pure unit tests
# ──────────────────────────────────────────────────────────────────────────


def test_parse_label_float_happy_path():
    bridge = TVIndicatorBridge()
    labels = [{"text": "STC_VALUE: 73.5"}, {"text": "ATR_VALUE: 24.80"}]
    assert bridge._parse_label_float(labels, "STC_VALUE") == pytest.approx(73.5)
    assert bridge._parse_label_float(labels, "ATR_VALUE") == pytest.approx(24.80)


def test_parse_label_float_missing_key_returns_none():
    bridge = TVIndicatorBridge()
    labels = [{"text": "STC_VALUE: 73.5"}]
    assert bridge._parse_label_float(labels, "COMP_SCORE") is None


def test_parse_label_str_happy_path():
    bridge = TVIndicatorBridge()
    labels = [{"text": "COMP_REGIME: TRENDING_BULL"}]
    assert bridge._parse_label_str(labels, "COMP_REGIME") == "TRENDING_BULL"


def test_parse_label_bool_true_false():
    bridge = TVIndicatorBridge()
    labels = [
        {"text": "PHASE_COMPRESSED: true"},
        {"text": "IB_COMPLETE: false"},
    ]
    assert bridge._parse_label_bool(labels, "PHASE_COMPRESSED") is True
    assert bridge._parse_label_bool(labels, "IB_COMPLETE") is False


# ──────────────────────────────────────────────────────────────────────────
# 3. Parse from manifest — full snapshot build
# ──────────────────────────────────────────────────────────────────────────


def test_parse_manifest_labels_populates_snapshot():
    bridge = TVIndicatorBridge()
    snap = bridge._parse_from_manifest(_canned_manifest_labels(), tables=[])
    assert isinstance(snap, TVIndicatorSnapshot)
    assert snap.stc_value == pytest.approx(73.5)
    assert snap.stc_state == "BULLISH"
    assert snap.composite_score == pytest.approx(0.42)
    assert snap.regime == "TRENDING_BULL"
    assert snap.atr_value == pytest.approx(24.80)
    assert snap.ib_high == pytest.approx(5818.00)
    assert snap.ib_low == pytest.approx(5808.25)
    assert snap.corey_score == pytest.approx(0.31)
    assert snap.corey_bias == "BULL"


def test_parse_manifest_empty_labels_returns_empty_snapshot():
    bridge = TVIndicatorBridge()
    snap = bridge._parse_from_manifest([], tables=[])
    assert isinstance(snap, TVIndicatorSnapshot)
    assert snap.stc_value is None
    assert snap.composite_score is None


# ──────────────────────────────────────────────────────────────────────────
# 4. End-to-end get_snapshot with mocked readers
# ──────────────────────────────────────────────────────────────────────────


def test_get_snapshot_live_data_quality():
    bridge = _make_bridge_with_manifest()
    snap = bridge.get_snapshot("MES")
    assert snap.data_quality == "live"
    assert snap.stc_value == pytest.approx(73.5)
    assert snap.regime == "TRENDING_BULL"
    assert snap.symbol == "MES"


# ──────────────────────────────────────────────────────────────────────────
# 5. 60-second cache
# ──────────────────────────────────────────────────────────────────────────


def test_cache_60s_returns_same_instance():
    bridge = _make_bridge_with_manifest()
    first = bridge.get_snapshot("MES")
    # Second call within TTL should return the SAME object (cache hit)
    second = bridge.get_snapshot("MES")
    assert first is second
    # Cache invariant: miss → fetch, hit → no fetch. Each miss does one
    # manifest read + one gamma-overlay read, so call_count is 2 per miss.
    first_miss_count = bridge._read_labels.call_count
    assert first_miss_count == 2  # exactly one miss happened
    # Second call was a cache hit and must not have fetched again
    assert first_miss_count == 2  # unchanged after the hit


def test_cache_expires_after_ttl():
    bridge = _make_bridge_with_manifest()
    _ = bridge.get_snapshot("MES")
    # Expire the cache by back-dating the stored timestamp
    snap, _ts = bridge._cache["MES"]
    bridge._cache["MES"] = (snap, time.time() - 3600)  # 1h ago
    _ = bridge.get_snapshot("MES")
    # Two misses × (manifest + gamma) = 4 reader calls total
    assert bridge._read_labels.call_count == 4


# ──────────────────────────────────────────────────────────────────────────
# 6. TradingView feed facade
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.skip(
    reason="tradingview_feed.py retired (commit 484b4d6) — TradingViewFeed class removed"
)
def test_tradingview_feed_get_all_indicators_flat_dict():
    """The flat get_all_indicators() contract used by TechnicalAnalystAgent."""
    from data import tradingview_feed

    # tradingview_feed imports get_tv_bridge lazily inside methods,
    # so we patch the canonical source module instead. Also stub
    # is_available() since it normally checks the `tv` CLI is on PATH.
    with (
        patch("data.tv_indicator_bridge.get_tv_bridge") as mock_get,
        patch.object(tradingview_feed.TradingViewFeed, "is_available", return_value=True),
    ):
        bridge = _make_bridge_with_manifest()
        mock_get.return_value = bridge

        feed = tradingview_feed.TradingViewFeed()
        indicators = feed.get_all_indicators("MES")

    assert isinstance(indicators, dict)
    # Must contain the tv_* prefixed keys that technical_analyst.py injects
    assert "tv_data_quality" in indicators
    assert indicators["tv_data_quality"] == "live"


# ──────────────────────────────────────────────────────────────────────────
# 7. Technical analyst never crashes on unavailable TV
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.skip(
    reason="tradingview_feed.py retired (commit 484b4d6) — TradingViewFeed class removed"
)
def test_tradingview_feed_unavailable_returns_empty_dict():
    """When TV is offline, get_all_indicators should not raise."""
    from data import tradingview_feed

    # tradingview_feed imports get_tv_bridge lazily inside methods,
    # so we patch the canonical source module instead.
    with patch("data.tv_indicator_bridge.get_tv_bridge") as mock_get:
        bridge = TVIndicatorBridge()
        bridge._available = False
        bridge._cache.clear()
        mock_get.return_value = bridge

        feed = tradingview_feed.TradingViewFeed()
        indicators = feed.get_all_indicators("MES")

    assert isinstance(indicators, dict)
    # tv_data_quality must explicitly say "unavailable"
    assert indicators.get("tv_data_quality") == "unavailable"


# ──────────────────────────────────────────────────────────────────────────
# 8. Singleton get_tv_bridge()
# ──────────────────────────────────────────────────────────────────────────


def test_get_tv_bridge_is_singleton():
    a = get_tv_bridge()
    b = get_tv_bridge()
    assert a is b
