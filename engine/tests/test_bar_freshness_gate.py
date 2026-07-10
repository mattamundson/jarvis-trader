"""Tests for the read-time freshness gate in engine.data.bar_quality_gate.

SOTA plan P1.4 — extends the write-time bar-quality screen (screen_bars,
covered by test_bar_quality_gate.py) to a READ-time, interval-scaled
staleness check consulted at decision time. A write-time-clean feed can
still be quietly frozen (well-formed historical rows, no new prints); this
gate is the orthogonal check that catches that case and forces NO_TRADE.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bar_quality_gate import (
    DEFAULT_MIN_FLOOR_SECONDS,
    DEFAULT_STALE_MULTIPLIER,
    FreshnessVerdict,
    check_freshness,
    freshness_gate_enabled,
    interval_to_seconds,
    stale_threshold_seconds,
)

# ---------------------------------------------------------------------------
# interval_to_seconds — pure token parser
# ---------------------------------------------------------------------------


class TestIntervalToSeconds:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("1m", 60),
            ("5m", 300),
            ("15m", 900),
            ("30m", 1_800),
            ("1h", 3_600),
            ("4h", 14_400),
            ("1d", 86_400),
            ("1D", 86_400),  # case-insensitive
            ("daily", 86_400),
            ("1w", 604_800),
            (" 1h ", 3_600),  # whitespace-tolerant
        ],
    )
    def test_known_tokens(self, token, expected):
        assert interval_to_seconds(token) == expected

    @pytest.mark.parametrize(
        "token,expected",
        [
            ("2h", 7_200),
            ("10m", 600),
            ("3d", 259_200),
        ],
    )
    def test_numeric_unit_tokens_not_in_table(self, token, expected):
        """Tokens not in the explicit table still parse via the regex fallback."""
        assert interval_to_seconds(token) == expected

    @pytest.mark.parametrize("token", ["", None, "garbage", "5x", "h5", "-1h"])
    def test_unparseable_returns_none(self, token):
        assert interval_to_seconds(token) is None


# ---------------------------------------------------------------------------
# stale_threshold_seconds — interval-scaled ceiling
# ---------------------------------------------------------------------------


class TestStaleThresholdSeconds:
    def test_scales_with_interval(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        # 1h * 3x = 10800s, well above the 300s floor.
        assert stale_threshold_seconds("1h") == pytest.approx(3_600 * DEFAULT_STALE_MULTIPLIER)
        # 4h interval gets a proportionally larger ceiling than 1h.
        assert stale_threshold_seconds("4h") > stale_threshold_seconds("1h")

    def test_fast_interval_floored(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        # 1m * 3x = 180s < 300s floor -> floor wins.
        assert stale_threshold_seconds("1m") == DEFAULT_MIN_FLOOR_SECONDS

    def test_unparseable_interval_returns_none(self):
        assert stale_threshold_seconds("not-an-interval") is None

    def test_env_overrides_honored(self, monkeypatch):
        monkeypatch.setenv("BAR_FRESHNESS_STALE_MULTIPLIER", "2")
        monkeypatch.setenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", "60")
        assert stale_threshold_seconds("1m") == pytest.approx(120.0)

    def test_garbage_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BAR_FRESHNESS_STALE_MULTIPLIER", "not-a-number")
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        assert stale_threshold_seconds("1h") == pytest.approx(3_600 * DEFAULT_STALE_MULTIPLIER)


# ---------------------------------------------------------------------------
# freshness_gate_enabled — opt-out flag
# ---------------------------------------------------------------------------


class TestFreshnessGateEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_GATE_ENABLED", raising=False)
        assert freshness_gate_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "OFF"])
    def test_disabled_via_env(self, monkeypatch, val):
        monkeypatch.setenv("BAR_FRESHNESS_GATE_ENABLED", val)
        assert freshness_gate_enabled() is False


# ---------------------------------------------------------------------------
# check_freshness — pure predicate, no I/O
# ---------------------------------------------------------------------------


class TestCheckFreshness:
    def test_fresh_bar_passes(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        verdict = check_freshness(age_seconds=300.0, interval="1h")
        assert verdict.is_stale is False
        assert verdict.age_seconds == 300.0
        assert verdict.threshold_seconds == pytest.approx(10_800.0)

    def test_stale_bar_fails_closed(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        # 1h interval -> 10,800s ceiling; 5h-old bar is well past it.
        verdict = check_freshness(age_seconds=5 * 3_600.0, interval="1h")
        assert verdict.is_stale is True
        assert "interval='1h'" in verdict.reason
        assert "NO_TRADE" in verdict.reason

    def test_exactly_at_threshold_is_not_stale(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        threshold = stale_threshold_seconds("1h")
        verdict = check_freshness(age_seconds=threshold, interval="1h")
        assert verdict.is_stale is False  # strictly greater-than trips it

    def test_just_over_threshold_is_stale(self, monkeypatch):
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        threshold = stale_threshold_seconds("1h")
        verdict = check_freshness(age_seconds=threshold + 1.0, interval="1h")
        assert verdict.is_stale is True

    def test_indeterminate_age_fails_open(self):
        """No usable bar timestamp -> skip the anchor, never fabricate a reject."""
        verdict = check_freshness(age_seconds=None, interval="1h")
        assert verdict.is_stale is False
        assert verdict.age_seconds is None

    def test_unparseable_interval_fails_open(self):
        """An unknown interval token cannot be scaled -> skip, don't guess."""
        verdict = check_freshness(age_seconds=99_999.0, interval="not-an-interval")
        assert verdict.is_stale is False
        assert verdict.threshold_seconds is None

    def test_fast_vs_slow_interval_same_age_different_verdict(self, monkeypatch):
        """The whole point of 'interval-scaled': the same absolute staleness
        (30 min) is disqualifying for a 5m strategy but fine for a 4h one."""
        monkeypatch.delenv("BAR_FRESHNESS_STALE_MULTIPLIER", raising=False)
        monkeypatch.delenv("BAR_FRESHNESS_MIN_FLOOR_SECONDS", raising=False)
        age = 30 * 60.0  # 30 minutes
        fast = check_freshness(age_seconds=age, interval="5m")
        slow = check_freshness(age_seconds=age, interval="4h")
        assert fast.is_stale is True
        assert slow.is_stale is False

    def test_returns_named_tuple(self):
        assert isinstance(check_freshness(None, "1h"), FreshnessVerdict)
