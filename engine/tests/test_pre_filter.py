"""
Tests for US-2140: LLM pre-filter for STC mid-range skipping
"""

import pytest

from agents.pre_filter import pre_filter_decision, pre_filter_signal
from config import settings


class TestPreFilterSignal:
    """Test pre_filter_signal() with various STC values."""

    def test_disabled_filter_always_passes(self):
        """When STC_MIDRANGE_SKIP_ENABLED=False, always return True."""
        # Temporarily disable the filter
        original = settings.STC_MIDRANGE_SKIP_ENABLED
        try:
            settings.STC_MIDRANGE_SKIP_ENABLED = False
            assert pre_filter_signal(50.0, 15.0, 83.0) is True
            assert pre_filter_signal(10.0, 15.0, 83.0) is True
            assert pre_filter_signal(90.0, 15.0, 83.0) is True
        finally:
            settings.STC_MIDRANGE_SKIP_ENABLED = original

    def test_stc_below_os_boundary(self):
        """STC below (OS + 10) should return True (run pipeline)."""
        # OS=15, so boundary is 25
        assert pre_filter_signal(24.9, 15.0, 83.0) is True
        assert pre_filter_signal(10.0, 15.0, 83.0) is True
        assert pre_filter_signal(0.0, 15.0, 83.0) is True

    def test_stc_above_ob_boundary(self):
        """STC above (OB - 10) should return True (run pipeline)."""
        # OB=83, so boundary is 73
        assert pre_filter_signal(73.1, 15.0, 83.0) is True
        assert pre_filter_signal(90.0, 15.0, 83.0) is True
        assert pre_filter_signal(100.0, 15.0, 83.0) is True

    def test_stc_in_mid_range(self):
        """STC between (OS + 10) and (OB - 10) should return False (skip)."""
        # Range is [25, 73]
        assert pre_filter_signal(25.0, 15.0, 83.0) is False
        assert pre_filter_signal(50.0, 15.0, 83.0) is False
        assert pre_filter_signal(73.0, 15.0, 83.0) is False

    def test_default_thresholds_from_config(self):
        """When os_threshold and ob_threshold are None, use config defaults."""
        # Assuming STC_MIDRANGE_SKIP_LOW=15.0, STC_MIDRANGE_SKIP_HIGH=83.0
        os = float(settings.STC_MIDRANGE_SKIP_LOW)
        ob = float(settings.STC_MIDRANGE_SKIP_HIGH)
        mid_low = os + 10.0
        mid_high = ob - 10.0

        # Test that config values are used
        assert pre_filter_signal(mid_low - 1) is True  # Just below boundary
        assert pre_filter_signal(mid_low + 1) is False  # Just above boundary
        assert pre_filter_signal(mid_high - 1) is False  # Just below upper boundary
        assert pre_filter_signal(mid_high + 1) is True  # Just above upper boundary

    def test_edge_cases(self):
        """Test exact boundary values."""
        # With OS=15, OB=83: mid_low=25, mid_high=73
        assert pre_filter_signal(24.999999, 15.0, 83.0) is True
        assert pre_filter_signal(25.0, 15.0, 83.0) is False
        assert pre_filter_signal(73.0, 15.0, 83.0) is False
        assert pre_filter_signal(73.000001, 15.0, 83.0) is True


class TestPreFilterDecision:
    """Test pre_filter_decision() which wraps pre_filter_signal()."""

    def test_filtered_returns_hold_dict(self):
        """When STC is mid-range, should return HOLD dict."""
        result = pre_filter_decision(50.0, 15.0, 83.0)
        assert result is not None
        assert result["action"] == "hold"
        assert result["reason"] == "pre_filter_mid_range"
        assert result["confidence"] == 0.0
        assert result["stc_value"] == 50.0

    def test_passed_returns_none(self):
        """When STC passes filter, should return None."""
        result = pre_filter_decision(10.0, 15.0, 83.0)
        assert result is None

        result = pre_filter_decision(90.0, 15.0, 83.0)
        assert result is None

    def test_decision_dict_includes_thresholds(self):
        """HOLD dict should include original thresholds."""
        result = pre_filter_decision(50.0, 15.0, 83.0)
        assert result["os_threshold"] == 15.0
        assert result["ob_threshold"] == 83.0

    def test_decision_dict_uses_config_defaults(self):
        """HOLD dict should use config defaults when not provided."""
        result = pre_filter_decision(50.0)  # No os_threshold, ob_threshold
        assert result is not None
        assert result["os_threshold"] == float(settings.STC_MIDRANGE_SKIP_LOW)
        assert result["ob_threshold"] == float(settings.STC_MIDRANGE_SKIP_HIGH)
