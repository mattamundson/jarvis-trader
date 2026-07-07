"""Tests for engine/analysis/hidden_pivots.py

All tests use synthetic OHLCV data — no network calls, no DB.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.hidden_pivots import (
    HPScanResult,
    bars_since_last_cross,
    full_hidden_pivots_scan,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_df(n: int = 150, trend: str = "up", seed: int = 42) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame. trend: 'up' | 'down' | 'flat'."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    drift = {"up": +0.25, "down": -0.25, "flat": 0.0}[trend]
    close = 100.0 + np.cumsum(rng.normal(drift, 0.8, n))
    close = np.clip(close, 1.0, None)
    spread = np.abs(rng.normal(0.4, 0.1, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.2, n),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.integers(500, 5000, n).astype(float),
        },
        index=dates,
    )


@pytest.fixture()
def up_df():
    return _make_df(150, "up")


@pytest.fixture()
def down_df():
    return _make_df(150, "down")


@pytest.fixture()
def flat_df():
    return _make_df(150, "flat")


@pytest.fixture()
def benchmark_df():
    return _make_df(150, "up", seed=99)


# ─── full_hidden_pivots_scan return shape ────────────────────────────────────


class TestScanReturnShape:
    def test_returns_hp_scan_result(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert isinstance(result, HPScanResult)

    def test_bias_is_valid_enum(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert result.bias in ("LONG", "SHORT", "WATCH", "SOH")

    def test_confidence_in_unit_range(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert 0.0 <= result.confidence <= 1.0

    def test_targets_is_list(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert isinstance(result.targets, list)

    def test_ema_alignment_is_valid(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert result.ema_alignment in ("BULLISH_FAN", "BEARISH_FAN", "COMPRESSED", "MIXED")

    def test_oscillator_state_is_valid(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert result.oscillator_state in (
            "BULLISH_CROSS",
            "BEARISH_CROSS",
            "RISING",
            "FALLING",
            "FLAT",
        )

    def test_rs_rw_score_in_normalized_range(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert -1.0 <= result.rs_rw_score <= 1.0

    def test_soh_is_bool(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert result.soh in (True, False)  # accepts np.bool_ too


# ─── Edge cases ──────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_too_short_df_does_not_raise(self, benchmark_df):
        """Less than 20 bars — insufficient_data path."""
        short_df = _make_df(15, "up")
        result = full_hidden_pivots_scan("SHORT", short_df, benchmark_df)
        assert result.bias in ("WATCH", "SOH", "LONG", "SHORT")

    def test_empty_df_returns_watch_or_raises_gracefully(self, benchmark_df):
        """Empty DataFrame should not crash the engine."""
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        try:
            result = full_hidden_pivots_scan("EMPTY", empty_df, benchmark_df)
            assert result.bias in ("WATCH", "SOH")
        except (ValueError, KeyError, IndexError):
            pass  # Well-typed exception is acceptable

    def test_no_benchmark_runs(self, up_df):
        """benchmark_df is optional — should not raise when omitted."""
        result = full_hidden_pivots_scan("TEST", up_df)
        assert isinstance(result, HPScanResult)
        assert result.bias in ("LONG", "SHORT", "WATCH", "SOH")

    def test_same_symbol_as_benchmark_runs(self):
        """Symbol == benchmark is valid (rs_rw_score near 0)."""
        df = _make_df(150, "up", seed=7)
        result = full_hidden_pivots_scan("SPY", df, df.copy())
        assert abs(result.rs_rw_score) < 0.3


# ─── SOH detection ───────────────────────────────────────────────────────────


class TestSOHDetection:
    def test_compressed_flat_does_not_crash(self):
        """Extremely compressed bars must not raise."""
        df = _make_df(150, "flat", seed=1)
        df.iloc[-5:, df.columns.get_loc("high")] = df.iloc[-5:]["close"] + 0.01
        df.iloc[-5:, df.columns.get_loc("low")] = df.iloc[-5:]["close"] - 0.01
        df.iloc[-5:, df.columns.get_loc("volume")] = 1.0
        result = full_hidden_pivots_scan("FLAT", df, _make_df(150, "up", seed=99))
        assert result.bias in ("WATCH", "SOH", "LONG", "SHORT")

    def test_soh_field_is_bool(self, up_df, benchmark_df):
        result = full_hidden_pivots_scan("TREND", up_df, benchmark_df)
        assert result.soh in (True, False)  # accepts np.bool_ too


# ─── RS/RW directional logic ─────────────────────────────────────────────────


class TestRSRW:
    def test_outperformer_has_positive_score(self):
        """Symbol rising 4x faster than benchmark → positive RS score."""
        rng = np.random.default_rng(0)
        n = 150
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        bench_close = 100.0 + np.cumsum(rng.normal(0.1, 0.5, n))
        sym_close = 100.0 + np.cumsum(rng.normal(0.4, 0.5, n))

        def _make(close):
            close = np.clip(close, 1.0, None)
            spread = np.abs(rng.normal(0.3, 0.05, n))
            return pd.DataFrame(
                {
                    "open": close,
                    "high": close + spread,
                    "low": close - spread,
                    "close": close,
                    "volume": rng.integers(500, 5000, n).astype(float),
                },
                index=dates,
            )

        result = full_hidden_pivots_scan("STRONG", _make(sym_close), _make(bench_close))
        assert result.rs_rw_score > 0.0

    def test_underperformer_has_negative_score(self):
        """Symbol falling while benchmark rises → negative RW score."""
        rng = np.random.default_rng(5)
        n = 150
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        bench_close = 100.0 + np.cumsum(rng.normal(0.2, 0.5, n))
        sym_close = 100.0 + np.cumsum(rng.normal(-0.3, 0.5, n))

        def _make(close):
            close = np.clip(close, 1.0, None)
            spread = np.abs(rng.normal(0.3, 0.05, n))
            return pd.DataFrame(
                {
                    "open": close,
                    "high": close + spread,
                    "low": close - spread,
                    "close": close,
                    "volume": rng.integers(500, 5000, n).astype(float),
                },
                index=dates,
            )

        result = full_hidden_pivots_scan("WEAK", _make(sym_close), _make(bench_close))
        assert result.rs_rw_score < 0.0


# ─── WATCH setups stay usable (level ladder populated even when gated) ─────────


class TestWatchSetupsRemainUsable:
    def test_directional_pattern_always_has_ladder(self):
        """A directional pattern must ship stops + 3 targets even when the
        oscillator gate downgrades the entry bias to WATCH/SOH (option B).
        Previously these came back null/[] on every non-crossover bar."""
        saw_gated_watch = False
        for seed in range(30):
            for trend in ("up", "down", "flat"):
                r = full_hidden_pivots_scan("T", _make_df(150, trend, seed=seed))
                if r.pattern is None or r.trigger_price is None:
                    continue
                # invariant: a directional pattern => usable ladder, any bias
                assert r.tight_stop is not None, (seed, trend, r.bias, r.pattern)
                assert r.riskier_stop is not None, (seed, trend, r.bias, r.pattern)
                assert len(r.targets) == 3, (seed, trend, r.bias, r.pattern)
                if r.bias in ("WATCH", "SOH"):
                    saw_gated_watch = True
        # the whole point of the fix is the gated case — make sure we hit it
        assert saw_gated_watch, "no gated WATCH/SOH setup in synthetic corpus"

    def test_recency_fields_present_and_sane(self, up_df, benchmark_df):
        r = full_hidden_pivots_scan("TEST", up_df, benchmark_df)
        assert isinstance(r.bars_since_cross, int)
        assert r.bars_since_cross >= -1
        assert r.last_cross_dir in ("bull", "bear", "none")
        # consistency: -1 bars <=> no direction
        assert (r.bars_since_cross == -1) == (r.last_cross_dir == "none")

    def test_bars_since_last_cross_short_series(self):
        """Under 60 bars -> no cross computable."""
        bars, direction = bars_since_last_cross(_make_df(40, "up"))
        assert bars == -1
        assert direction == "none"

    def test_bars_since_last_cross_nonnegative_when_found(self):
        bars, direction = bars_since_last_cross(_make_df(150, "up", seed=3))
        if direction != "none":
            assert bars >= 0
