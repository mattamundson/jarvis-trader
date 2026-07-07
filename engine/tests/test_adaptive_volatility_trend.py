"""Tests for the Adaptive Volatility Trend (AVT) indicator.

Covers the Efficiency Ratio, efficiency-scaled ATR bands, the 0-100 signal
score, the RSI / volume gates, the presets, signal generation, and the
no-look-ahead property.
"""
import numpy as np
import pandas as pd
import pytest

from analytics.adaptive_volatility_trend import (
    PRESETS,
    AVTParams,
    adaptive_atr_bands,
    adaptive_trend,
    efficiency_ratio,
    generate_avt_signals,
    get_preset,
    signal_score,
)


def _frame(close: pd.Series, volume: float | pd.Series = 1000.0) -> pd.DataFrame:
    vol = volume if isinstance(volume, pd.Series) else pd.Series([volume] * len(close))
    return pd.DataFrame(
        {
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close.reset_index(drop=True),
            "volume": vol.reset_index(drop=True),
        }
    )


# ─── Efficiency ratio ────────────────────────────────────────────────────────


class TestEfficiencyRatio:
    def test_clean_trend_is_near_one(self):
        close = pd.Series(np.linspace(100, 140, 100))
        assert efficiency_ratio(close, 20).iloc[-1] == pytest.approx(1.0, abs=1e-9)

    def test_flat_series_is_zero(self):
        close = pd.Series([100.0] * 60)
        assert efficiency_ratio(close, 20).iloc[-1] == 0.0

    def test_noise_is_low(self):
        rng = np.random.default_rng(0)
        close = pd.Series(100 + np.cumsum(rng.normal(0, 1.0, 200)))
        # A random walk wanders; ER over the tail should be well below 0.5.
        assert efficiency_ratio(close, 20).iloc[-1] < 0.5

    def test_bounded_unit_interval(self):
        rng = np.random.default_rng(2)
        close = pd.Series(100 + np.cumsum(rng.normal(0, 1.0, 300)))
        er = efficiency_ratio(close, 20).dropna()
        assert (er >= 0).all() and (er <= 1).all()

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            efficiency_ratio(pd.Series([1.0, 2.0]), 0)


# ─── Adaptive bands ──────────────────────────────────────────────────────────


class TestAdaptiveBands:
    def test_high_er_narrows_band(self):
        n = 60
        close = pd.Series(np.linspace(100, 120, n))
        basis = adaptive_trend(close, 20)
        high, low = close * 1.01, close * 0.99
        er_high = pd.Series([1.0] * n)
        er_low = pd.Series([0.0] * n)
        up_h, lo_h = adaptive_atr_bands(high, low, close, basis, er_high, atr_period=14)
        up_l, lo_l = adaptive_atr_bands(high, low, close, basis, er_low, atr_period=14)
        width_high = (up_h - lo_h).iloc[-1]
        width_low = (up_l - lo_l).iloc[-1]
        assert width_high < width_low
        # Default band_er_scale=0.5 -> ER=1 leaves half the band of ER=0.
        assert width_high == pytest.approx(0.5 * width_low, rel=1e-6)


# ─── Signal score ────────────────────────────────────────────────────────────


class TestSignalScore:
    def test_full_long_score_is_100(self):
        assert signal_score(1.0, 100.0, 2.0, 1) == pytest.approx(100.0)

    def test_no_direction_is_zero(self):
        assert signal_score(1.0, 100.0, 2.0, 0) == 0.0

    def test_components_split_40_30_30(self):
        # ER 1 -> 40 trend; RSI 100 long -> 30 momentum; vol 2x -> 30 volume.
        assert signal_score(1.0, 50.0, 0.0, 1) == pytest.approx(40.0)  # trend only
        assert signal_score(0.0, 100.0, 0.0, 1) == pytest.approx(30.0)  # momentum only
        assert signal_score(0.0, 50.0, 2.0, 1) == pytest.approx(30.0)  # volume only

    def test_momentum_zero_when_rsi_against_direction(self):
        # RSI 80 with a SHORT signal -> no momentum credit.
        assert signal_score(0.0, 80.0, 0.0, -1) == 0.0

    def test_volume_caps_at_30(self):
        assert signal_score(0.0, 50.0, 10.0, 1) == pytest.approx(30.0)

    def test_nan_inputs_dont_crash(self):
        assert signal_score(float("nan"), float("nan"), float("nan"), 1) == 0.0


# ─── Presets ─────────────────────────────────────────────────────────────────


class TestPresets:
    def test_all_four_present_with_documented_values(self):
        assert set(PRESETS) == {"conservative", "default", "aggressive", "scalping"}
        assert (PRESETS["default"].trend_length, PRESETS["default"].atr_length,
                PRESETS["default"].multiplier) == (20, 14, 2.0)
        assert (PRESETS["scalping"].trend_length, PRESETS["scalping"].atr_length,
                PRESETS["scalping"].multiplier) == (8, 7, 1.2)

    def test_get_preset_case_insensitive(self):
        assert get_preset("AGGRESSIVE") is PRESETS["aggressive"]

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError):
            get_preset("turbo")

    def test_params_from_preset_with_override(self):
        p = AVTParams.from_preset("conservative", min_score=60.0)
        assert p.trend_length == 30 and p.atr_length == 20 and p.multiplier == 2.5
        assert p.min_score == 60.0


# ─── Signal generation ───────────────────────────────────────────────────────


def _uptrend_then_chop(n_trend: int = 120, n_chop: int = 120) -> pd.Series:
    trend = np.linspace(100, 150, n_trend)
    rng = np.random.default_rng(7)
    chop = 150 + np.cumsum(rng.normal(0, 0.6, n_chop))
    return pd.Series(np.concatenate([trend, chop]))


class TestGenerateSignals:
    def test_missing_columns_raises(self):
        with pytest.raises(ValueError):
            generate_avt_signals(pd.DataFrame({"close": [1.0, 2.0]}))

    def test_adds_expected_columns(self):
        out = generate_avt_signals(_frame(_uptrend_then_chop()))
        for col in ("avt_trend", "avt_er", "avt_upper", "avt_lower", "avt_rsi",
                    "avt_vol_ratio", "avt_raw_signal", "avt_score", "avt_signal"):
            assert col in out.columns

    def test_signals_imply_raw_cross_same_sign(self):
        out = generate_avt_signals(
            _frame(_uptrend_then_chop()),
            AVTParams(use_rsi_gate=False, use_volume_gate=False),
        )
        fired = out[out["avt_signal"] != 0]
        assert (fired["avt_signal"] == fired["avt_raw_signal"]).all()

    def test_rsi_gate_blocks_overbought_longs(self):
        out = generate_avt_signals(
            _frame(_uptrend_then_chop()),
            AVTParams(use_rsi_gate=True, use_volume_gate=False, min_score=0.0),
        )
        longs = out[out["avt_signal"] == 1]
        assert (longs["avt_rsi"] <= 70.0).all()
        shorts = out[out["avt_signal"] == -1]
        assert (shorts["avt_rsi"] >= 30.0).all()

    def test_rsi_gate_reduces_signal_count(self):
        df = _frame(_uptrend_then_chop())
        ungated = generate_avt_signals(
            df, AVTParams(use_rsi_gate=False, use_volume_gate=False)
        )
        gated = generate_avt_signals(
            df, AVTParams(use_rsi_gate=True, use_volume_gate=False)
        )
        assert (gated["avt_signal"] != 0).sum() <= (ungated["avt_signal"] != 0).sum()

    def test_volume_gate_requires_above_average_volume(self):
        # Low volume everywhere -> volume gate suppresses all signals.
        df = _frame(_uptrend_then_chop(), volume=pd.Series([100.0] * 240))
        out = generate_avt_signals(
            df, AVTParams(use_rsi_gate=False, use_volume_gate=True)
        )
        # vol_ratio == 1.0 < 1.2 gate -> nothing fires.
        assert (out["avt_signal"] != 0).sum() == 0

    def test_min_score_filter(self):
        df = _frame(_uptrend_then_chop())
        out = generate_avt_signals(
            df, AVTParams(use_rsi_gate=False, use_volume_gate=False, min_score=200.0)
        )
        # No score can exceed 100, so a 200 floor blocks everything.
        assert (out["avt_signal"] != 0).sum() == 0


class TestNoLookAhead:
    def test_row_k_unaffected_by_future_bars(self):
        close = _uptrend_then_chop(n_trend=150, n_chop=150)
        df = _frame(close, volume=pd.Series([1000.0] * 200 + [2500.0] * 100))
        params = AVTParams(use_rsi_gate=True, use_volume_gate=True)
        k = 180
        full = generate_avt_signals(df, params)
        truncated = generate_avt_signals(df.iloc[: k + 1].copy(), params)
        for col in ("avt_trend", "avt_er", "avt_score", "avt_signal"):
            a = full[col].iloc[k]
            b = truncated[col].iloc[k]
            if isinstance(a, float) and np.isnan(a):
                assert np.isnan(b)
            else:
                assert a == pytest.approx(b)
