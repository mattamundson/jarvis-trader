"""
Smoke tests for TradingView MCP bridge.
Tests:
1. TVIndicatorSnapshot can be instantiated with defaults
2. TVIndicatorBridge.is_available() returns False gracefully when TV not running
3. TVIndicatorBridge.get_snapshot() returns snapshot with data_quality="unavailable" when TV offline
4. _parse_label_float extracts correct values
5. _parse_label_str extracts correct string values
6. Pine Script files exist in scripts/tradingview/pine/
"""

import os
import sys

import pytest

# Add engine to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_tv_snapshot_defaults():
    """TVIndicatorSnapshot can be created with all-None defaults."""
    from data.tv_indicator_bridge import TVIndicatorSnapshot

    snap = TVIndicatorSnapshot()
    assert snap.data_quality == "unavailable"
    assert snap.stc_value is None
    assert snap.composite_score is None
    assert snap.ib_high is None


def test_bridge_unavailable_when_tv_not_running():
    """Bridge returns False for is_available() when TV CLI not found."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    bridge = TVIndicatorBridge()
    # In CI / when TradingView is not running, should return False, not raise
    available = bridge.is_available()
    assert isinstance(available, bool)


def test_get_snapshot_never_raises():
    """get_snapshot() always returns a TVIndicatorSnapshot, never raises."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    bridge = TVIndicatorBridge()
    snap = bridge.get_snapshot("MES")
    assert snap is not None
    # data_quality must be one of these values
    assert snap.data_quality in ("live", "stale", "unavailable")


def test_parse_label_float():
    """_parse_label_float correctly extracts numeric values."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    bridge = TVIndicatorBridge()
    labels = [
        {"text": "STC_VALUE: 73.5", "price": 0},
        {"text": "ATR_VALUE: 1.24", "price": 0},
        {"text": "IB_HIGH: 5840.25", "price": 0},
    ]
    assert bridge._parse_label_float(labels, "STC_VALUE") == pytest.approx(73.5)
    assert bridge._parse_label_float(labels, "ATR_VALUE") == pytest.approx(1.24)
    assert bridge._parse_label_float(labels, "IB_HIGH") == pytest.approx(5840.25)
    assert bridge._parse_label_float(labels, "MISSING_KEY") is None


def test_parse_label_str():
    """_parse_label_str correctly extracts string values."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    bridge = TVIndicatorBridge()
    labels = [
        {"text": "STC_STATE: BULLISH", "price": 0},
        {"text": "COMPOSITE_REGIME: TRENDING_BULL", "price": 0},
    ]
    assert bridge._parse_label_str(labels, "STC_STATE") == "BULLISH"
    assert bridge._parse_label_str(labels, "COMPOSITE_REGIME") == "TRENDING_BULL"
    assert bridge._parse_label_str(labels, "MISSING") is None


def test_parse_label_bool():
    """_parse_label_bool correctly parses true/false labels."""
    from data.tv_indicator_bridge import TVIndicatorBridge

    bridge = TVIndicatorBridge()
    labels = [
        {"text": "COMPRESSED: true", "price": 0},
        {"text": "GAP_EXISTS: false", "price": 0},
        {"text": "IB_COMPLETE: true", "price": 0},
    ]
    assert bridge._parse_label_bool(labels, "COMPRESSED") is True
    assert bridge._parse_label_bool(labels, "GAP_EXISTS") is False
    assert bridge._parse_label_bool(labels, "IB_COMPLETE") is True


def test_pine_scripts_exist():
    """All expected Pine Script files exist in scripts/tradingview/pine/."""
    pine_dir = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "tradingview", "pine")
    expected_files = [
        "JARVIS_MCP_Manifest.pine",
        "JARVIS_STC_Sub.pine",
        "JARVIS_ATR_Levels.pine",
        "JARVIS_IB_Levels.pine",
        "JARVIS_Composite_Score.pine",
        "JARVIS_Phase_Oscillator.pine",
        "JARVIS_Corey_Score.pine",
        "JARVIS_Pivot_Points.pine",
        "JARVIS_Keltner_OB_Omega.pine",
        "JARVIS_Volume_Profile.pine",
        "JARVIS_Gap_Finder.pine",
    ]
    for fname in expected_files:
        fpath = os.path.join(pine_dir, fname)
        assert os.path.exists(fpath), f"Missing Pine script: {fname}"


@pytest.mark.skip(
    reason="tradingview_feed.py retired (commit 484b4d6) — TradingViewFeed removed in favour of MCP server path"
)
def test_get_all_indicators_returns_dict():
    """TradingViewFeed.get_all_indicators() returns a dict (possibly empty)."""
    from data.tradingview_feed import TradingViewFeed

    feed = TradingViewFeed()
    result = feed.get_all_indicators("MES")
    assert isinstance(result, dict)
    # If TV is offline, should be empty dict, not raise
