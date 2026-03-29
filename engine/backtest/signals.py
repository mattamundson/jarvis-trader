"""
JARVIS TRADER — Signal Generation
Composites all indicators into the 5-layer Tony Stark trading framework.

Layers wired:
  1 — Regime Map    (layer1_regime)
  2 — Structure Map (layer2_structure)   ← added
  3 — Bias          (layer3_bias)
  4 — Entry Timing  (layer4_entry)
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Optional

from .indicators import (
    wilder_atr,
    kama,
    stc,
    phase_oscillator,
    volume_stack,
    keltner_channels,
    cci,
    ema_ribbon,
    range_consumed_pct,
)


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all TOS-derived indicators on a OHLCV DataFrame.
    df must have columns: open, high, low, close, volume
    Returns df with all indicator columns added.
    """
    df = df.copy()

    # ── ATR (Wilder's, period=14) ─────────────────────────────────────────
    df['atr'] = wilder_atr(df['high'], df['low'], df['close'], period=14)

    # ── KAMA (period=10) ──────────────────────────────────────────────────
    df['kama_val'] = kama(df['close'], period=10)
    df['kama_signal'] = np.where(
        df['close'] > df['kama_val'], 'long',
        np.where(df['close'] < df['kama_val'], 'short', 'neutral')
    )

    # ── STC (fast=23, slow=50, K=10, D=3) ────────────────────────────────
    # Parameter sets (grid search, 162 combos, SPY 2024-06-01 to 2026-03-27):
    #
    #   DAILY (1d):  STC_OS=23, STC_OB=83, stop=0.70 ATR, T1=2.00 ATR  [Score 493]
    #   INTRADAY (1h): STC_OS=15, STC_OB=83, stop=0.70 ATR, T1=1.50 ATR [Score 496]
    #
    # Key difference: 1h uses a lower oversold threshold (15 vs 23) for earlier
    # entries, and a tighter T1 (1.5 vs 2.0 ATR) appropriate for intraday moves.
    # OB threshold (83) and stop (0.70 ATR) are consistent across timeframes.
    STC_OS = 15   # 1h optimal (daily: 23)
    STC_OB = 83   # consistent across timeframes

    df['stc_val'] = stc(df['close'], fast=23, slow=50, k_period=10, d_period=3)

    def _stc_signal(row):
        val = row['stc_val']
        prev_val = row.get('stc_prev', 50)
        if val < STC_OS:
            return 'oversold'
        elif val > STC_OB:
            return 'overbought'
        elif val > prev_val:
            return 'rising'
        elif val < prev_val:
            return 'falling'
        return 'neutral'

    df['stc_prev'] = df['stc_val'].shift(1).fillna(50)
    df['stc_signal'] = df.apply(_stc_signal, axis=1)
    df['stc_cross_up'] = (df['stc_val'] > STC_OS) & (df['stc_prev'] <= STC_OS)
    df['stc_cross_down'] = (df['stc_val'] < STC_OB) & (df['stc_prev'] >= STC_OB)

    # ── Phase Oscillator ──────────────────────────────────────────────────
    phase, compression = phase_oscillator(
        df['close'], df['high'], df['low'],
        ema_len=21, atr_len=14, bb_len=21, bb_std=2.0
    )
    df['phase_val'] = phase
    df['phase_compression'] = compression

    def _phase_signal(row):
        p = row['phase_val']
        if row['phase_compression']:
            return 'compression'
        elif p >= 61.8:
            return 'extended_up'
        elif p <= -61.8:
            return 'extended_down'
        elif p > 23.6:
            return 'bullish'
        elif p < -23.6:
            return 'bearish'
        return 'neutral'

    df['phase_signal'] = df.apply(_phase_signal, axis=1)

    # ── Volume Stack ──────────────────────────────────────────────────────
    buy_vol, sell_vol, buy_pct = volume_stack(
        df['open'], df['high'], df['low'], df['close'], df['volume']
    )
    df['buy_vol'] = buy_vol
    df['sell_vol'] = sell_vol
    df['buy_pct'] = buy_pct

    df['volume_signal'] = np.where(
        df['buy_pct'] > 60, 'buyer_dominant',
        np.where(df['buy_pct'] < 40, 'seller_dominant', 'balanced')
    )

    # ── Keltner Channels (1.5x, 2.0x, 3.0x) ─────────────────────────────
    kelt_u15, kelt_b, kelt_l15 = keltner_channels(
        df['close'], df['high'], df['low'], sma_len=20, atr_factor=1.5
    )
    kelt_u20, _, kelt_l20 = keltner_channels(
        df['close'], df['high'], df['low'], sma_len=20, atr_factor=2.0
    )
    kelt_u30, _, kelt_l30 = keltner_channels(
        df['close'], df['high'], df['low'], sma_len=20, atr_factor=3.0
    )
    df['kelt_basis'] = kelt_b
    df['kelt_inner_upper'] = kelt_u15
    df['kelt_inner_lower'] = kelt_l15
    df['kelt_outer_upper'] = kelt_u20
    df['kelt_outer_lower'] = kelt_l20
    df['kelt_extreme_upper'] = kelt_u30
    df['kelt_extreme_lower'] = kelt_l30

    # ── EMA Ribbon (8/21/34) ──────────────────────────────────────────────
    ema8, ema21, ema34 = ema_ribbon(df['close'])
    df['ema_8'] = ema8
    df['ema_21'] = ema21
    df['ema_34'] = ema34

    def _ema_trend(row):
        if row['ema_8'] > row['ema_21'] > row['ema_34']:
            return 'bullish'
        elif row['ema_8'] < row['ema_21'] < row['ema_34']:
            return 'bearish'
        return 'neutral'

    df['ema_trend'] = df.apply(_ema_trend, axis=1)

    # ── ATR Range Consumed ────────────────────────────────────────────────
    prior_close = df['close'].shift(1)
    df['atr_consumed_pct'] = df.apply(
        lambda r: range_consumed_pct(r['close'], prior_close.loc[r.name], r['atr'])
        if pd.notna(prior_close.loc[r.name]) and pd.notna(r['atr']) else 0.0,
        axis=1
    )

    # ── CCI (period=50) ───────────────────────────────────────────────────
    df['cci_50'] = cci(df['high'], df['low'], df['close'], period=50)

    # ── Layer 2 — Structure Map ───────────────────────────────────────────
    # VPOC approximation: rolling 20-bar volume-weighted average price.
    # True VPOC requires tick-level data; VWAP over the lookback window is
    # the best proxy available from OHLCV bars.
    df['vpoc'] = (
        (df['close'] * df['volume']).rolling(20).sum()
        / df['volume'].rolling(20).sum()
    )

    # Value Area approximation via rolling quantiles of bar highs/lows.
    # VAH ≈ 85th-percentile of recent highs (top ~15% of price action).
    # VAL ≈ 15th-percentile of recent lows  (bottom ~15% of price action).
    # This captures the 70% value area centred on VPOC without tick data.
    df['va_high'] = df['high'].rolling(20).quantile(0.85)
    df['va_low'] = df['low'].rolling(20).quantile(0.15)

    # IB proxy for daily bars: prior bar's high/low acts as the
    # "Initial Balance" range that price must accept or reject today.
    df['ib_high'] = df['high'].shift(1)
    df['ib_low'] = df['low'].shift(1)

    # Prior-bar IB flags (needed for breakout-detection in layer4_entry)
    df['prev_above_ib_high'] = df['close'].shift(1) > df['ib_high'].shift(1)

    # Price position relative to structure
    df['above_vah'] = df['close'] > df['va_high']
    df['below_val'] = df['close'] < df['va_low']
    df['above_ib_high'] = df['close'] > df['ib_high']
    df['below_ib_low'] = df['close'] < df['ib_low']

    return df


def layer1_regime(row: pd.Series) -> str:
    """Determine market regime from Layer 1 indicators."""
    consumed = row.get('atr_consumed_pct', 0)
    phase = row.get('phase_val', 0)
    compression = row.get('phase_compression', False)
    ema_trend = row.get('ema_trend', 'neutral')

    if consumed > 90:
        return 'EXHAUSTED'
    if compression and consumed < 50:
        return 'COMPRESSION'
    if ema_trend == 'bullish' and consumed < 70 and phase > 0:
        return 'TRENDING_BULL'
    if ema_trend == 'bearish' and consumed < 70 and phase < 0:
        return 'TRENDING_BEAR'
    return 'RANGE_BOUND'


def layer2_structure(row: pd.Series) -> dict:
    """
    Layer 2 — Structure Map.
    Determines WHERE price is relative to key auction-theory levels:
      - VPOC  : rolling 20-bar volume-weighted average price (VWAP proxy)
      - VAH/VAL: approximate 70% value area high/low
      - IB High/Low: prior bar's high/low as daily Initial Balance proxy

    Output position labels:
      BUYER_CONTROL   — price above VAH AND above IB High (accepted above value)
      SELLER_CONTROL  — price below VAL AND below IB Low  (accepted below value)
      NEUTRAL_STRUCTURE — inside value area or mixed signals
    """
    above_vah = bool(row.get('above_vah', False))
    below_val = bool(row.get('below_val', False))
    above_ib_high = bool(row.get('above_ib_high', False))
    below_ib_low = bool(row.get('below_ib_low', False))

    result = {
        'position': 'NEUTRAL_STRUCTURE',
        'above_vah': above_vah,
        'below_val': below_val,
        'above_ib_high': above_ib_high,
        'below_ib_low': below_ib_low,
        'vpoc': float(row.get('vpoc', 0) or 0),
        'va_high': float(row.get('va_high', 0) or 0),
        'va_low': float(row.get('va_low', 0) or 0),
    }

    if above_vah and above_ib_high:
        result['position'] = 'BUYER_CONTROL'
    elif below_val and below_ib_low:
        result['position'] = 'SELLER_CONTROL'

    return result


def layer3_bias(row: pd.Series) -> str:
    """Determine directional bias from Layer 3 indicators."""
    bull_count = 0
    bear_count = 0

    # KAMA signal
    if row.get('kama_signal') == 'long':
        bull_count += 1
    elif row.get('kama_signal') == 'short':
        bear_count += 1

    # STC direction
    stc_sig = row.get('stc_signal', 'neutral')
    if stc_sig in ('oversold', 'rising'):
        bull_count += 1
    elif stc_sig in ('overbought', 'falling'):
        bear_count += 1

    # Volume
    vol_sig = row.get('volume_signal', 'balanced')
    if vol_sig == 'buyer_dominant':
        bull_count += 1
    elif vol_sig == 'seller_dominant':
        bear_count += 1

    # EMA trend
    ema = row.get('ema_trend', 'neutral')
    if ema == 'bullish':
        bull_count += 1
    elif ema == 'bearish':
        bear_count += 1

    if bull_count >= 4:
        return 'STRONG_BULL'
    elif bull_count >= 3 or (bull_count == 2 and ema == 'bullish'):
        return 'LEAN_BULL'
    elif bear_count >= 4:
        return 'STRONG_BEAR'
    elif bear_count >= 3 or (bear_count == 2 and ema == 'bearish'):
        return 'LEAN_BEAR'
    return 'NEUTRAL'


def layer4_entry(row: pd.Series, regime: str, bias: str, structure: dict) -> str:
    """
    Determine entry timing from Layer 4 indicators.

    Structure-aware upgrades:
      - BUYER_CONTROL + bullish bias + trending regime → unconditional ENTRY_NOW
        (price has accepted above value AND above prior IB High — highest-
        conviction long setup in the Tony Stark framework)
      - IB High breakout: close crossed above IB High this bar (was below
        on the prior bar) → ENTRY_NOW regardless of STC crossover
    """
    if regime == 'EXHAUSTED':
        phase = row.get('phase_val', 0)
        consumed = row.get('atr_consumed_pct', 0)
        if consumed > 90 and (phase > 61.8 or phase < -61.8):
            return 'FADE_EXTREME'
        return 'NO_TRADE'

    if bias == 'NEUTRAL':
        return 'NO_TRADE'

    structure_position = structure.get('position', 'NEUTRAL_STRUCTURE')
    above_ib_high = structure.get('above_ib_high', False)
    below_ib_low = structure.get('below_ib_low', False)

    # ── Structure-boosted ENTRY_NOW ───────────────────────────────────────
    # 1. Full alignment: structure confirms bias AND regime is trending
    if (structure_position == 'BUYER_CONTROL'
            and bias in ('STRONG_BULL', 'LEAN_BULL')
            and regime in ('TRENDING_BULL',)):
        return 'ENTRY_NOW'

    if (structure_position == 'SELLER_CONTROL'
            and bias in ('STRONG_BEAR', 'LEAN_BEAR')
            and regime in ('TRENDING_BEAR',)):
        return 'ENTRY_NOW'

    # 2. IB High breakout: price just crossed above prior bar's high this bar
    #    (prev_above_ib_high=False means it was below IB High last bar)
    prev_above = bool(row.get('prev_above_ib_high', False))
    if above_ib_high and not prev_above and bias in ('STRONG_BULL', 'LEAN_BULL'):
        return 'ENTRY_NOW'

    # 3. IB Low breakdown: price just crossed below prior bar's low this bar
    prev_ib_high_prev = bool(row.get('prev_above_ib_high', False))
    # For the downside breakout we re-use the same prev flag directionally:
    # below_ib_low=True this bar means price broke below — no prior-cross flag
    # stored for lows, so accept the signal if we're below IB Low fresh (i.e.
    # IB Low breakout: below_ib_low True and structure is SELLER_CONTROL).
    if below_ib_low and structure_position == 'SELLER_CONTROL' and bias in ('STRONG_BEAR', 'LEAN_BEAR'):
        return 'ENTRY_NOW'

    # ── Standard STC crossover entry ─────────────────────────────────────
    stc_cross_up = row.get('stc_cross_up', False)
    stc_cross_down = row.get('stc_cross_down', False)

    if bias in ('STRONG_BULL', 'LEAN_BULL') and stc_cross_up:
        return 'ENTRY_NOW'
    if bias in ('STRONG_BEAR', 'LEAN_BEAR') and stc_cross_down:
        return 'ENTRY_NOW'

    stc_val = row.get('stc_val', 50)
    if 20 <= stc_val <= 80:
        return 'WAIT_FOR_PULLBACK'

    return 'NO_TRADE'


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run all 5 layers on each row.
    Adds: regime, structure_position, bias, entry_signal,
          stop_level, target_1, target_2, target_3
    """
    df = compute_all_indicators(df)

    regimes = []
    structures = []
    structure_positions = []
    biases = []
    entries = []

    for idx, row in df.iterrows():
        regime = layer1_regime(row)
        structure = layer2_structure(row)
        bias = layer3_bias(row)
        entry = layer4_entry(row, regime, bias, structure)

        regimes.append(regime)
        structures.append(structure)
        structure_positions.append(structure['position'])
        biases.append(bias)
        entries.append(entry)

    df['regime'] = regimes
    df['structure_position'] = structure_positions
    df['bias'] = biases
    df['entry_signal'] = entries

    # Optionally expose individual structure booleans as columns for downstream
    # analysis / filtering without unpacking the dict manually.
    df['s_above_vah'] = [s['above_vah'] for s in structures]
    df['s_below_val'] = [s['below_val'] for s in structures]
    df['s_above_ib_high'] = [s['above_ib_high'] for s in structures]
    df['s_below_ib_low'] = [s['below_ib_low'] for s in structures]
    df['s_vpoc'] = [s['vpoc'] for s in structures]
    df['s_va_high'] = [s['va_high'] for s in structures]
    df['s_va_low'] = [s['va_low'] for s in structures]

    # Stop and target levels using ATR Fibonacci
    atr = df['atr'].fillna(0)
    close = df['close']

    # For long entries: stop below, targets above
    # For short entries: stop above, targets below
    is_long = df['bias'].isin(['STRONG_BULL', 'LEAN_BULL'])

    # Bug 6 fix: Original T1=1.50 ATR was unreachable for intraday trades.
    # Analysis of 549 signals (SPY 1h, 2024-06-01 to 2026-03-27):
    #   T1=1.50 ATR → only 12% of signals reach T1 within the trading day
    #   T1=1.00 ATR → 26% reach T1 (23% before stop)
    #   T1=0.75 ATR → 37% reach T1 (32% before stop)
    #
    # With EOD forced exits, max favorable excursion is typically 0.5-1.2 ATR.
    # Setting T1=1.00 ATR balances reachability with R:R (1.0/0.70 = 1.43 R:R).
    # T2=1.80 ATR provides a realistic stretch target for strong intraday moves.
    #
    # Prior grid search found T1=1.50 "optimal" but that was before the Bug 3
    # pending-entry fix shifted entries to next-bar open, and before confirming
    # that zero targets were ever being hit (rendering the "optimum" meaningless).
    STOP_ATR = 0.70   # both timeframes
    T1_ATR   = 1.00   # 1h intraday-realistic (was 1.50 — never hit)
    T2_ATR   = 1.80   # intraday stretch target (was 2.618 — never hit)
    T3_ATR   = 2.618  # runner target (was 4.0 — reduced for intraday)

    df['stop_level'] = np.where(
        is_long,
        close - STOP_ATR * atr,
        close + STOP_ATR * atr
    )
    df['target_1'] = np.where(
        is_long,
        close + T1_ATR * atr,
        close - T1_ATR * atr
    )
    df['target_2'] = np.where(
        is_long,
        close + T2_ATR * atr,
        close - T2_ATR * atr
    )
    df['target_3'] = np.where(
        is_long,
        close + T3_ATR * atr,
        close - T3_ATR * atr
    )

    return df
