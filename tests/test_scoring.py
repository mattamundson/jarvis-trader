"""
Unit tests for engine.backtest.scoring.SignalScorer

Test categories:
  1. Deterministic scoring — same row always produces same result
  2. Monotonicity — higher-quality rows score strictly higher
  3. Blocking — specific conditions always produce BLOCKED tier
  4. Boundary / clamp — no score component exceeds its declared maximum
  5. MES/MNQ 1H pipeline smoke tests — pipelines return correct types
"""
from __future__ import annotations

from collections import namedtuple
from typing import Optional

import pytest

from engine.backtest.scoring import SignalScorer, ScoreResult
from engine.backtest.mes_1h_pipeline import MES1HPipeline
from engine.backtest.mnq_1h_pipeline import MNQ1HPipeline
from engine.backtest.alert_schema import AlertTier, ExecutionMode, JarvisAlertV1


# ---------------------------------------------------------------------------
# Test row factory
# ---------------------------------------------------------------------------

Row = namedtuple(
    "Row",
    [
        "side", "structure_position", "broke_ib_high", "broke_ib_low",
        "c_period_confirmed", "above_vwap", "below_vwap", "vwap_zscore",
        "adx", "ema_8_gt_21", "ema_21_gt_34", "stc_value", "roc_10",
        "atr_consumed_pct", "regime", "entry_signal",
        "news_blackout", "low_volume", "mtf_blocked",
        # pipeline extras
        "atr", "close", "bias", "session_date",
        "ib_high", "ib_low", "ib_mid", "ib_range", "ib_range_pct", "ib_tier",
        "extension_prob_50", "extension_prob_100",
        "vwap", "vwap_distance_pct",
        "ema_8", "ema_21", "ema_34", "kama_value", "trend_state", "momentum_state",
    ],
    defaults=[
        # side, structure_position
        "LONG", "BUYER_CONTROL",
        # ib flags
        True, False, True,
        # vwap
        True, False, 0.5,
        # adx, emas
        32.0, True, True,
        # stc, roc, atr_consumed
        15.0, 0.3, 0.25,
        # regime, signal, blocks
        "TRENDING_BULL", "IB_BREAKOUT_LONG",
        False, False, False,
        # pipeline extras
        5.0, 5000.0, "STRONG_BULL", "2026-06-30",
        5010.0, 4990.0, 5000.0, 20.0, 0.004, "NORMAL",
        0.72, 0.45,
        5001.0, 0.02,
        5002.0, 5001.0, 4999.0, 5000.5, "TRENDING", "MOMENTUM_UP",
    ],
)


def make_a_plus_row(**kwargs) -> Row:
    return Row(**kwargs)


def make_a_row(**kwargs) -> Row:
    return Row(
        structure_position="NEUTRAL_STRUCTURE",
        broke_ib_high=False,
        c_period_confirmed=False,
        adx=25.0,
        stc_value=35.0,
        **kwargs,
    )


def make_b_row(**kwargs) -> Row:
    return Row(
        structure_position="NEUTRAL_STRUCTURE",
        broke_ib_high=False,
        c_period_confirmed=False,
        adx=15.0,
        stc_value=50.0,
        roc_10=0.0,
        above_vwap=False,
        ema_8_gt_21=False,
        atr_consumed_pct=0.60,
        regime="RANGE_BOUND",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Scorer instantiation fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def scorer() -> SignalScorer:
    return SignalScorer()


# ---------------------------------------------------------------------------
# 1. Deterministic
# ---------------------------------------------------------------------------

class TestDeterministic:
    def test_same_row_same_score(self, scorer):
        row = make_a_plus_row()
        r1 = scorer.score_row(row)
        r2 = scorer.score_row(row)
        assert r1.total == r2.total
        assert r1.tier == r2.tier

    def test_a_plus_tier(self, scorer):
        row = make_a_plus_row()
        result = scorer.score_row(row)
        assert result.tier == "A_PLUS"
        assert result.total >= 75.0


# ---------------------------------------------------------------------------
# 2. Monotonicity
# ---------------------------------------------------------------------------

class TestMonotonicity:
    def test_a_plus_beats_a(self, scorer):
        r_aplus = scorer.score_row(make_a_plus_row())
        r_a = scorer.score_row(make_a_row())
        assert r_aplus.total > r_a.total

    def test_a_beats_b(self, scorer):
        r_a = scorer.score_row(make_a_row())
        r_b = scorer.score_row(make_b_row())
        assert r_a.total > r_b.total

    def test_structure_drives_score(self, scorer):
        buyer = scorer.score_row(make_a_plus_row(structure_position="BUYER_CONTROL"))
        neutral = scorer.score_row(make_a_plus_row(structure_position="NEUTRAL_STRUCTURE"))
        assert buyer.structure > neutral.structure


# ---------------------------------------------------------------------------
# 3. Blocking
# ---------------------------------------------------------------------------

class TestBlocking:
    def test_news_blackout_blocks(self, scorer):
        row = make_a_plus_row(news_blackout=True)
        result = scorer.score_row(row)
        assert result.tier == "BLOCKED"

    def test_low_volume_blocks(self, scorer):
        row = make_a_plus_row(low_volume=True)
        result = scorer.score_row(row)
        assert result.tier == "BLOCKED"

    def test_mtf_blocked_blocks(self, scorer):
        row = make_a_plus_row(mtf_blocked=True)
        result = scorer.score_row(row)
        assert result.tier == "BLOCKED"

    def test_block_signal_name_blocks(self, scorer):
        for sig in [
            "NEWS_BLACKOUT", "LOW_VOLUME_BLOCK", "MTF_BLOCKED",
            "KILL_SWITCH_ACTIVE", "CONSECUTIVE_LOSS_BLOCK",
        ]:
            row = make_a_plus_row(entry_signal=sig)
            result = scorer.score_row(row)
            assert result.tier == "BLOCKED", f"Expected BLOCKED for signal {sig}"

    def test_exhausted_regime_penalised(self, scorer):
        normal = scorer.score_row(make_a_plus_row(regime="TRENDING_BULL"))
        exhausted = scorer.score_row(make_a_plus_row(regime="EXHAUSTED"))
        assert exhausted.risk_penalty > normal.risk_penalty


# ---------------------------------------------------------------------------
# 4. Boundary / clamp
# ---------------------------------------------------------------------------

class TestBoundary:
    def test_structure_max_40(self, scorer):
        row = make_a_plus_row()
        result = scorer.score_row(row)
        assert result.structure <= 40.0

    def test_trend_max_30(self, scorer):
        row = make_a_plus_row()
        result = scorer.score_row(row)
        assert result.trend <= 30.0

    def test_momentum_max_20(self, scorer):
        row = make_a_plus_row()
        result = scorer.score_row(row)
        assert result.momentum <= 20.0

    def test_volatility_max_10(self, scorer):
        row = make_a_plus_row()
        result = scorer.score_row(row)
        assert result.volatility <= 10.0

    def test_total_non_negative(self, scorer):
        row = make_b_row(news_blackout=False, low_volume=False, mtf_blocked=False)
        result = scorer.score_row(row)
        assert result.total >= 0.0


# ---------------------------------------------------------------------------
# 5. Pipeline smoke tests
# ---------------------------------------------------------------------------

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


@pytest.mark.skipif(not HAS_PANDAS, reason="pandas not installed")
class TestPipelineSmoke:
    def _make_df(self, symbol: str) -> "pd.DataFrame":  # type: ignore[name-defined]
        import pandas as pd
        close = 5000.0 if symbol == "MES" else 20000.0
        atr = 5.0 if symbol == "MES" else 30.0
        return pd.DataFrame([{
            "side": "LONG",
            "structure_position": "BUYER_CONTROL",
            "broke_ib_high": True, "broke_ib_low": False,
            "c_period_confirmed": True,
            "above_vwap": True, "below_vwap": False, "vwap_zscore": 0.5,
            "adx": 32.0, "ema_8_gt_21": True, "ema_21_gt_34": True,
            "stc_value": 15.0, "roc_10": 0.3, "atr_consumed_pct": 0.25,
            "regime": "TRENDING_BULL", "bias": "STRONG_BULL",
            "entry_signal": "IB_BREAKOUT_LONG",
            "news_blackout": False, "low_volume": False, "mtf_blocked": False,
            "atr": atr, "close": close, "session_date": "2026-06-30",
            "ib_high": close + atr, "ib_low": close - atr,
            "ib_mid": close, "ib_range": 2 * atr, "ib_range_pct": 0.004,
            "ib_tier": "NORMAL",
            "extension_prob_50": 0.72, "extension_prob_100": 0.45,
            "vwap": close + 1, "vwap_distance_pct": 0.02,
            "ema_8": close + 2, "ema_21": close + 1, "ema_34": close - 1,
            "kama_value": close, "trend_state": "TRENDING",
            "momentum_state": "MOMENTUM_UP",
        }])

    def test_mes_pipeline_returns_alert(self):
        pipe = MES1HPipeline(execution_mode=ExecutionMode.PAPER)
        df = self._make_df("MES")
        alerts = pipe.run(df)
        assert len(alerts) == 1
        assert isinstance(alerts[0], JarvisAlertV1)
        assert alerts[0].symbol == "MES"
        assert alerts[0].timeframe == "1H"
        assert alerts[0].tier != AlertTier.BLOCKED

    def test_mnq_pipeline_returns_alert(self):
        pipe = MNQ1HPipeline(execution_mode=ExecutionMode.PAPER)
        df = self._make_df("MNQ")
        alerts = pipe.run(df)
        assert len(alerts) == 1
        assert isinstance(alerts[0], JarvisAlertV1)
        assert alerts[0].symbol == "MNQ"
        assert alerts[0].timeframe == "1H"

    def test_mes_targets_correct_direction(self):
        pipe = MES1HPipeline(execution_mode=ExecutionMode.PAPER)
        df = self._make_df("MES")
        alert = pipe.run(df)[0]
        assert alert.targets.target_1 > alert.targets.entry_price  # LONG
        assert alert.targets.stop_price < alert.targets.entry_price  # stop below

    def test_mnq_wider_targets_than_mes(self):
        mes_pipe = MES1HPipeline(execution_mode=ExecutionMode.PAPER)
        mnq_pipe = MNQ1HPipeline(execution_mode=ExecutionMode.PAPER)
        mes_df = self._make_df("MES")
        mnq_df = self._make_df("MNQ")
        mes_alert = mes_pipe.run(mes_df)[0]
        mnq_alert = mnq_pipe.run(mnq_df)[0]
        # MNQ T1 mult (1.5) > MES T1 mult (1.0), so T1 distance larger relative to ATR
        mes_t1_atr = (mes_alert.targets.target_1 - mes_alert.targets.entry_price) / mes_alert.targets.stop_distance
        mnq_t1_atr = (mnq_alert.targets.target_1 - mnq_alert.targets.entry_price) / mnq_alert.targets.stop_distance
        assert mnq_t1_atr > mes_t1_atr
