"""
Multi-factor consensus voting for entry confirmation.

Requires N of M independent factors to agree before confirming an entry signal.
Reduces false positives in choppy/ranging markets where the primary STC signal
may fire but broader market context doesn't support the trade.

Pattern adapted from: Polymarket-Trading-Bot AI Forecast strategy
(github.com/dylanpersonguy/Polymarket-Trading-Bot)

Usage:
    from backtest.consensus import compute_consensus
    result = compute_consensus(ema_fast=..., ema_slow=..., ...)
    if result.threshold_met and result.direction == "LONG":
        # Entry confirmed by consensus
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ConsensusResult:
    direction: Literal["LONG", "SHORT", "HOLD"]
    factors_agree: int
    factors_total: int
    factors_detail: dict = field(default_factory=dict)  # factor_name → +1/0/-1
    threshold_met: bool = False
    required_factors: int = 3

    def __str__(self) -> str:
        status = "MET" if self.threshold_met else "NOT MET"
        return (f"{self.direction} ({self.factors_agree}/{self.factors_total} factors agree, "
                f"need {self.required_factors}) threshold={status}")

    def summary(self) -> str:
        """Human-readable factor breakdown for LLM context."""
        lines = [f"Consensus: {self}"]
        for name, vote in self.factors_detail.items():
            symbol = "\u25b2" if vote > 0 else ("\u25bc" if vote < 0 else "\u2500")
            lines.append(f"  {symbol} {name}: {'+1' if vote > 0 else ('-1' if vote < 0 else '0')}")
        return "\n".join(lines)


def compute_consensus(
    ema_fast: float,
    ema_slow: float,
    ema_slow_prev: float,
    rsi: float,
    atr: float,
    atr_sma: float,
    vwap: float,
    close: float,
    adx_norm: float,
    stc_value: float,
    stc_os: float = 15.0,
    stc_ob: float = 83.0,
    min_factors: int = 3,
    min_factors_volatile: int = 4,
    adx_volatile_threshold: float = 0.35,
    roc: float = 0.0,              # Rate of Change — positive = upward momentum
    vwap_zscore: float = 0.0,      # VWAP deviation z-score
    roc_threshold: float = 0.3,    # |RoC| > 0.3% = directional momentum signal
    vwap_z_threshold: float = 1.2, # |z| > 1.2 = extended, mean-reversion territory
) -> ConsensusResult:
    """
    Eight independent factors vote on directional bias.

    Requires min_factors (3) to agree for normal markets.
    Requires min_factors_volatile (4) in strongly trending markets (ADX > 0.35)
    because false breakouts are more costly in volatile regimes.

    Factor definitions:
    1. ema_trend:        EMA8 vs EMA21 slope alignment
    2. rsi_direction:    RSI deviation from neutral 50
    3. atr_regime:       ATR expansion (trending) vs compression (ranging)
    4. adx_strength:     Directional index confirms a trend exists
    5. vwap_position:    Price relative to daily VWAP anchor
    6. stc_state:        STC oscillator at extreme (oversold/overbought zone)
    7. roc_momentum:     Rate of Change — directional momentum over 10 bars
    8. vwap_convergence: VWAP z-score — contrarian mean-reversion signal

    Args:
        ema_fast:        EMA8 current value
        ema_slow:        EMA21 current value
        ema_slow_prev:   EMA21 value 3 bars ago (for slope check)
        rsi:             RSI(14) current value (0-100)
        atr:             ATR(14) current value
        atr_sma:         20-bar SMA of ATR (for regime comparison)
        vwap:            Current session VWAP
        close:           Current bar close price
        adx_norm:        ADX normalized 0-1 (divide raw ADX by 100)
        stc_value:       STC oscillator current value (0-100)
        stc_os:          STC oversold threshold (default 15)
        stc_ob:          STC overbought threshold (default 83)
        min_factors:     Minimum factors required in normal markets (default 3)
        min_factors_volatile: Minimum factors in trending markets (default 4)
        adx_volatile_threshold: ADX norm above which to use stricter threshold (default 0.35)
        roc:             Rate of Change (10-bar) value in percent
        vwap_zscore:     VWAP deviation in ATR units
        roc_threshold:   |RoC| above which a momentum signal is asserted (default 0.3%)
        vwap_z_threshold: |z| above which mean-reversion signal fires (default 1.2)

    Returns:
        ConsensusResult with direction, factor counts, and threshold_met flag
    """
    factors: dict[str, int] = {}

    # Factor 1: EMA trend alignment (both fast>slow AND slow is rising)
    if ema_fast > ema_slow and ema_slow > ema_slow_prev:
        factors['ema_trend'] = 1
    elif ema_fast < ema_slow and ema_slow < ema_slow_prev:
        factors['ema_trend'] = -1
    else:
        factors['ema_trend'] = 0

    # Factor 2: RSI directional bias (simple deviation from neutral)
    if rsi > 52:
        factors['rsi_direction'] = 1
    elif rsi < 48:
        factors['rsi_direction'] = -1
    else:
        factors['rsi_direction'] = 0

    # Factor 3: ATR regime (expanding = trending = confirms momentum direction)
    if atr_sma > 0:
        if atr > atr_sma * 1.05:
            factors['atr_regime'] = 1  # Expanding: trending context, trust signals
        elif atr < atr_sma * 0.75:
            factors['atr_regime'] = -1  # Compressing: ranging, be cautious
        else:
            factors['atr_regime'] = 0
    else:
        factors['atr_regime'] = 0

    # Factor 4: ADX directional strength (confirms a trend exists)
    # Note: ADX doesn't tell direction — we use it as a weight amplifier
    # When ADX is strong, we treat EMA trend as more reliable
    if adx_norm > 0.25:
        factors['adx_strength'] = factors['ema_trend']  # Echo EMA when trend confirmed
    else:
        factors['adx_strength'] = 0  # No confirmed trend

    # Factor 5: VWAP position (intraday fair value anchor)
    if vwap > 0:
        if close > vwap * 1.001:
            factors['vwap_position'] = 1
        elif close < vwap * 0.999:
            factors['vwap_position'] = -1
        else:
            factors['vwap_position'] = 0
    else:
        factors['vwap_position'] = 0

    # Factor 6: STC oscillator state (primary signal confirmation)
    if stc_value <= stc_os:
        factors['stc_state'] = 1   # Oversold -> LONG bias
    elif stc_value >= stc_ob:
        factors['stc_state'] = -1  # Overbought -> SHORT bias
    else:
        factors['stc_state'] = 0   # Midrange -> neutral

    # Factor 7: Momentum (Rate of Change — adapted from Polymarket momentum strategy)
    if roc > roc_threshold:
        factors['roc_momentum'] = 1   # Upward momentum
    elif roc < -roc_threshold:
        factors['roc_momentum'] = -1  # Downward momentum
    else:
        factors['roc_momentum'] = 0   # Insufficient momentum

    # Factor 8: VWAP convergence/mean-reversion (adapted from Polymarket convergence strategy)
    # CONTRARIAN: price far ABOVE VWAP → SHORT signal (expect mean reversion back down)
    # Only fires when z-score is extreme enough to matter
    if abs(vwap_zscore) > vwap_z_threshold:
        factors['vwap_convergence'] = -1 if vwap_zscore > vwap_z_threshold else 1
    else:
        factors['vwap_convergence'] = 0  # Near VWAP — no convergence signal

    # Count votes (8 total factors)
    bull_count = sum(1 for v in factors.values() if v > 0)
    bear_count = sum(1 for v in factors.values() if v < 0)

    # Stricter threshold in volatile/strongly-trending markets
    required = min_factors_volatile if adx_norm > adx_volatile_threshold else min_factors

    if bull_count >= required:
        return ConsensusResult(
            direction="LONG",
            factors_agree=bull_count,
            factors_total=8,
            factors_detail=factors,
            threshold_met=True,
            required_factors=required,
        )
    elif bear_count >= required:
        return ConsensusResult(
            direction="SHORT",
            factors_agree=bear_count,
            factors_total=8,
            factors_detail=factors,
            threshold_met=True,
            required_factors=required,
        )
    else:
        max_agree = max(bull_count, bear_count)
        return ConsensusResult(
            direction="HOLD",
            factors_agree=max_agree,
            factors_total=8,
            factors_detail=factors,
            threshold_met=False,
            required_factors=required,
        )
