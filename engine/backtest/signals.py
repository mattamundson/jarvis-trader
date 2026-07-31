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

import logging
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from discord.ib_levels import IBLevelProvider as _IBLevelProvider

    _ib_provider = _IBLevelProvider()
    _IB_AVAILABLE = True
except Exception:
    _ib_provider = None  # type: ignore[assignment]
    _IB_AVAILABLE = False

from .indicators import (  # noqa: E402
    cci,
    classify_trin,
    compute_adx,
    compute_vwap,
    ema_ribbon,
    kama,
    keltner_channels,
    phase_oscillator,
    range_consumed_pct,
    stc,
    volume_stack,
    wilder_atr,
)

# Per-instrument optimized parameters (research-validated)
# Format: (STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)
# 7th element (REGIME_FILTER): True = block EXHAUSTED/COMPRESSION entries, False = allow them
INSTRUMENT_PARAMS: Dict[str, tuple] = {
    "MNQ": (
        15,
        92,
        0.70,
        1.00,
        1.80,
        2.618,
        True,
    ),  # STC_OB=92 filters Nasdaq noise; 86 trades, PF 1.51
    "MCL": (
        23,
        83,
        0.50,
        1.00,
        2.618,
        4.00,
        True,
    ),  # Sprint 16: WF consensus params (WFE=0.82, OOS PF=1.21); OS raised 15→23, stop 0.90→0.50, T1 1.50→1.00
    "MGC": (
        17,
        88,
        0.30,
        1.50,
        2.618,
        4.00,
        True,
    ),  # Gold: tight stop + wide T1 matches trend length
    "SPY": (
        15,
        88,
        0.30,
        1.00,
        1.618,
        2.618,
        True,
    ),  # SPY 1h optimizer consensus (2024-06→2026-03): PF 3.79, 23 trades
    # MES → routed via TREND_INSTRUMENTS to trend_signals.generate_sma_trend_signals()
    # Defaults used for all other symbols: STC_OS=15, STC_OB=83, Stop=0.70, T1=1.00, regime ON
}

# Instruments that use composite signal generation (STC+ORB+VWAP regime-adaptive).
# Sprint 16: MCL and MNQ moved back to standard generate_signals() — the WF validation
# used the standard path (WFE=0.82/0.57), and the composite path produced broken
# exit_date=None artifacts. MES moved to SMA trend-following (2026-04-20 pivot).
COMPOSITE_INSTRUMENTS: set[str] = set()  # no active composite instruments

# Instruments that use SMA trend-following signal generation.
# MES pivot (2026-04-20): WFO winner SMA(50,200)+2.0×ATR, train PF 2.06 / test PF 1.69.
TREND_INSTRUMENTS = {"MES", "MGC"}

# Instruments with no validated edge on cached OHLC 2024-06→2026-03. The pipeline
# emits forced NO_TRADE signals for these symbols until a per-symbol edge is
# re-derived. Rationale: multi_symbol_trend_wfo.py (2026-04-20) showed 0 WFO
# winners for MCL/MNQ on the MES SMA(50,200) config; composite path scored
# PF 0.13 — net-negative. Paper-trading a negative-expectancy strategy
# contaminates the learning/feedback feedback loop.
# Decision frame: memory/project_per_symbol_strategy_decision.md (Option B).
#
# Per-symbol exhaustion as of 2026-05-06:
#   MCL — Mean-Rev hyp A/B/C + SMA Trend hyp D/E all FAIL (5 hypotheses exhausted)
#   MNQ — SMA Trend ranks 1-2 + Breakout ranks 1-7 + ORB rank 1 all FAIL
#   M2K — SMA Trend ranks 1-2 + ORB rank 1 all FAIL
DO_NOT_TRADE_SYMBOLS = frozenset({"MCL", "MNQ", "M2K"})

# Default symbols for dashboard/Discord briefing widgets (T3-23, 2026-07-09).
# Canonical active paper-trading pair per the 2026-05-24 instrument switch —
# see jarvis-trader/CLAUDE.md "Active Instruments". A single shared source so
# default-symbol call sites (e.g. discord_router.py's /intelligence
# aggregation) can't independently drift the way they did when MCL/MNQ were
# halted and three separate hardcodes were left pointing at them.
DEFAULT_BRIEFING_SYMBOLS = ("MES", "MGC")

# Env-var feature flag for Phase 3 FULL (gate v2 routing enforcement).
# Default OFF — ships dormant, user activates after verifying verdict
# files exist and the policy module reads them correctly.
# See: memory/project_gate_v2_proposal.md, engine/backtest/gate_v2_policy.py
_GATE_V2_ROUTING_TRUTHY = frozenset({"1", "true", "yes", "on"})

# PRB-02 (2026-07-29): TREND_INSTRUMENTS route exclusively through
# generate_sma_trend_signals() (the SMA-crossover path below). Only gate v2
# verdicts for that SAME code path — family "trend" or a "trend_*" variant
# (trend_rv_filter, trend_baseline, trend_adx_filter, ...) — are valid
# evidence this specific routing is authorized. A PASS for an unrelated
# family (e.g. "stark_gapfill_long", a completely different signal generator
# that TREND_INSTRUMENTS never invoke) must never authorize this path — that
# was the live bug: MES stayed "ungated" solely because
# MES_stark_gapfill_long_rank1.json PASSed, while every trend-family verdict
# for MES was FAIL or INSUFFICIENT_SAMPLE. See gate_v2_policy.is_ungate_eligible's
# `family_prefixes` param and PRB-02 in ~/.claude/loops/jarvis-prod-readiness/backlog.json.
TREND_GATE_V2_FAMILY_PREFIXES = frozenset({"trend"})


def _is_gate_v2_routing_enforced() -> bool:
    """Check `GATE_V2_ENFORCE_ROUTING` env var (case-insensitive truthy set)."""
    return os.environ.get("GATE_V2_ENFORCE_ROUTING", "").strip().lower() in _GATE_V2_ROUTING_TRUTHY


def _force_no_trade(result):
    """Override entry/exit columns to NO_TRADE / NO_EXIT while preserving
    all other columns + the index. Shared by DO_NOT_TRADE and gate_v2
    enforcement paths."""
    result = result.copy()
    result["entry_signal"] = "NO_TRADE"
    if "exit_signal" in result.columns:
        result["exit_signal"] = "NO_EXIT"
    return result


def generate_instrument_signals(df, symbol: str, **kwargs):
    """Route to trend, composite, or standard signal generation based on instrument.

    Post-processing (applied universally regardless of routing path):
      1. DO_NOT_TRADE_SYMBOLS — static blocklist, always forces NO_TRADE.
      2. Gate v2 routing enforcement (optional, env-flagged) — force NO_TRADE
         when `GATE_V2_ENFORCE_ROUTING` is set and the symbol lacks a fresh
         PASS verdict per `gate_v2_policy.is_ungate_eligible`. For
         TREND_INSTRUMENTS this is scoped to `TREND_GATE_V2_FAMILY_PREFIXES`
         (PRB-02) — a PASS for an unrelated strategy family can no longer
         authorize the trend-crossover path these symbols actually trade.

    DO_NOT_TRADE takes precedence — MCL/MNQ stay blocked even if a
    gate_v2 PASS verdict exists. Gate v2 enforcement fails open: a missing
    or stale verdict forces NO_TRADE, never an implicit allow.
    """
    if symbol in TREND_INSTRUMENTS:
        from backtest.trend_signals import generate_sma_trend_signals, get_sma_trend_params

        params = get_sma_trend_params(symbol)
        if params:
            # Config-controlled RV filter (off by default; see commit 5816aae).
            # Env var MES_MIN_RV_ANNUALIZED enables the filter for live backtests
            # without redeploying code — set to "9.0" or "13.0" after forward
            # validation confirms improvement on 60+ trades.
            env_rv = os.environ.get(f"{symbol.upper()}_MIN_RV_ANNUALIZED", "0.0")
            try:
                default_rv = float(env_rv)
            except (TypeError, ValueError):
                default_rv = 0.0
            # Allow caller overrides (e.g. optimizer varying fast/slow/min_rv_annualized)
            merged = {
                **params,
                "min_rv_annualized": default_rv,
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k in ("fast", "slow", "atr_trail_mult", "min_rv_annualized")
                },
            }
            result = generate_sma_trend_signals(df, **merged)
        else:
            result = generate_signals(df, symbol=symbol, **kwargs)
    elif symbol in COMPOSITE_INSTRUMENTS:
        from backtest.composite_signals import generate_composite_signals

        result = generate_composite_signals(df, symbol=symbol, **kwargs)
    else:
        result = generate_signals(df, symbol=symbol, **kwargs)

    # Override layer 1: static blocklist wins first.
    if symbol in DO_NOT_TRADE_SYMBOLS:
        return _force_no_trade(result)

    # Override layer 2: optional gate_v2 dynamic enforcement.
    if _is_gate_v2_routing_enforced():
        # Lazy import so the policy module's dependencies aren't loaded
        # for callers that never enable enforcement.
        from backtest.gate_v2_policy import is_ungate_eligible

        # PRB-02: TREND_INSTRUMENTS may only be authorized by a verdict for
        # the SAME family they actually trade (trend / trend_*) — an
        # unrelated family's PASS (e.g. a gap-fill scanner) must not
        # authorize this path. Other routing paths keep the broader
        # symbol-wide check until they get the same per-path audit.
        family_prefixes = TREND_GATE_V2_FAMILY_PREFIXES if symbol in TREND_INSTRUMENTS else None
        if not is_ungate_eligible(symbol, family_prefixes=family_prefixes):
            return _force_no_trade(result)

    return result


# Default STC thresholds
STC_OS = 15  # Oversold threshold
STC_OB = 83  # Overbought threshold


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all TOS-derived indicators on a OHLCV DataFrame.
    df must have columns: open, high, low, close, volume
    Returns df with all indicator columns added.
    """
    df = df.copy()

    # ── ATR (Wilder's, period=14) ─────────────────────────────────────────
    df["atr"] = wilder_atr(df["high"], df["low"], df["close"], period=14)

    # ── KAMA (period=10) ──────────────────────────────────────────────────
    df["kama_val"] = kama(df["close"], period=10)
    df["kama_signal"] = np.where(
        df["close"] > df["kama_val"],
        "long",
        np.where(df["close"] < df["kama_val"], "short", "neutral"),
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
    STC_OS = 15  # 1h optimal (daily: 23)
    STC_OB = 83  # consistent across timeframes

    df["stc_val"] = stc(df["close"], fast=23, slow=50, k_period=10, d_period=3)

    def _stc_signal(row):
        val = row["stc_val"]
        prev_val = row.get("stc_prev", 50)
        if val < STC_OS:
            return "oversold"
        elif val > STC_OB:
            return "overbought"
        elif val > prev_val:
            return "rising"
        elif val < prev_val:
            return "falling"
        return "neutral"

    df["stc_prev"] = df["stc_val"].shift(1).fillna(50)
    df["stc_signal"] = df.apply(_stc_signal, axis=1)
    df["stc_cross_up"] = (df["stc_val"] > STC_OS) & (df["stc_prev"] <= STC_OS)
    df["stc_cross_down"] = (df["stc_val"] < STC_OB) & (df["stc_prev"] >= STC_OB)

    # ── Phase Oscillator ──────────────────────────────────────────────────
    phase, compression = phase_oscillator(
        df["close"], df["high"], df["low"], ema_len=21, atr_len=14, bb_len=21, bb_std=2.0
    )
    df["phase_val"] = phase
    df["phase_compression"] = compression

    def _phase_signal(row):
        p = row["phase_val"]
        if row["phase_compression"]:
            return "compression"
        elif p >= 61.8:
            return "extended_up"
        elif p <= -61.8:
            return "extended_down"
        elif p > 23.6:
            return "bullish"
        elif p < -23.6:
            return "bearish"
        return "neutral"

    df["phase_signal"] = df.apply(_phase_signal, axis=1)

    # ── Volume Stack ──────────────────────────────────────────────────────
    buy_vol, sell_vol, buy_pct = volume_stack(
        df["open"], df["high"], df["low"], df["close"], df["volume"]
    )
    df["buy_vol"] = buy_vol
    df["sell_vol"] = sell_vol
    df["buy_pct"] = buy_pct

    df["volume_signal"] = np.where(
        df["buy_pct"] > 60,
        "buyer_dominant",
        np.where(df["buy_pct"] < 40, "seller_dominant", "balanced"),
    )

    # ── Keltner Channels (1.5x, 2.0x, 3.0x) ─────────────────────────────
    kelt_u15, kelt_b, kelt_l15 = keltner_channels(
        df["close"], df["high"], df["low"], sma_len=20, atr_factor=1.5
    )
    kelt_u20, _, kelt_l20 = keltner_channels(
        df["close"], df["high"], df["low"], sma_len=20, atr_factor=2.0
    )
    kelt_u30, _, kelt_l30 = keltner_channels(
        df["close"], df["high"], df["low"], sma_len=20, atr_factor=3.0
    )
    df["kelt_basis"] = kelt_b
    df["kelt_inner_upper"] = kelt_u15
    df["kelt_inner_lower"] = kelt_l15
    df["kelt_outer_upper"] = kelt_u20
    df["kelt_outer_lower"] = kelt_l20
    df["kelt_extreme_upper"] = kelt_u30
    df["kelt_extreme_lower"] = kelt_l30

    # ── EMA Ribbon (8/21/34) ──────────────────────────────────────────────
    ema8, ema21, ema34 = ema_ribbon(df["close"])
    df["ema_8"] = ema8
    df["ema_21"] = ema21
    df["ema_34"] = ema34

    def _ema_trend(row):
        if row["ema_8"] > row["ema_21"] > row["ema_34"]:
            return "bullish"
        elif row["ema_8"] < row["ema_21"] < row["ema_34"]:
            return "bearish"
        return "neutral"

    df["ema_trend"] = df.apply(_ema_trend, axis=1)

    # ── ATR Range Consumed ────────────────────────────────────────────────
    prior_close = df["close"].shift(1)
    df["atr_consumed_pct"] = df.apply(
        lambda r: (
            range_consumed_pct(r["close"], prior_close.loc[r.name], r["atr"])
            if pd.notna(prior_close.loc[r.name]) and pd.notna(r["atr"])
            else 0.0
        ),
        axis=1,
    )

    # ── CCI (period=50) ───────────────────────────────────────────────────
    df["cci_50"] = cci(df["high"], df["low"], df["close"], period=50)

    # ── Layer 2 — Structure Map ───────────────────────────────────────────
    # VPOC approximation: rolling 20-bar volume-weighted average price.
    # True VPOC requires tick-level data; VWAP over the lookback window is
    # the best proxy available from OHLCV bars.
    df["vpoc"] = (df["close"] * df["volume"]).rolling(20).sum() / df["volume"].rolling(20).sum()

    # Value Area approximation via rolling quantiles of bar highs/lows.
    # VAH ≈ 85th-percentile of recent highs (top ~15% of price action).
    # VAL ≈ 15th-percentile of recent lows  (bottom ~15% of price action).
    # This captures the 70% value area centred on VPOC without tick data.
    df["va_high"] = df["high"].rolling(20).quantile(0.85)
    df["va_low"] = df["low"].rolling(20).quantile(0.15)

    # IB proxy for daily bars: prior bar's high/low acts as the
    # "Initial Balance" range that price must accept or reject today.
    # TODO(Phase 2): replace this shift(1) proxy with compute_initial_balance()
    #   from engine/backtest/ib_signals.py.  That function requires intraday
    #   (1-min or 5-min) bars with a DatetimeIndex so it can isolate the
    #   first `open_minutes` of each RTH session.  generate_signals() currently
    #   operates on daily OHLC bars, so the wiring requires either (a) passing
    #   an intraday df alongside the daily df, or (b) pre-computing IB columns
    #   before calling generate_signals and merging on date.  Until the data
    #   pipeline supports intraday lookups here, the shift(1) proxy is the
    #   correct fallback.  See thinkorswim-scripts/docs/corey_ib_v1.md for
    #   the full IB spec and engine/backtest/ib_signals.py for the port.
    df["ib_high"] = df["high"].shift(1)
    df["ib_low"] = df["low"].shift(1)

    # Prior-bar IB flags (needed for breakout-detection in layer4_entry)
    df["prev_above_ib_high"] = df["close"].shift(1) > df["ib_high"].shift(1)

    # Price position relative to structure
    df["above_vah"] = df["close"] > df["va_high"]
    df["below_val"] = df["close"] < df["va_low"]
    df["above_ib_high"] = df["close"] > df["ib_high"]
    df["below_ib_low"] = df["close"] < df["ib_low"]

    # ── RSI (period=14) for consensus module ─────────────────────────────
    from .indicators import rsi as _rsi

    df["rsi_14"] = _rsi(df["close"], period=14)

    # ── VWAP (session-reset daily) ────────────────────────────────────────
    try:
        df["vwap"] = compute_vwap(df, session_reset=True)
    except Exception:
        df["vwap"] = float("nan")

    # ── ADX (period=14) ───────────────────────────────────────────────────
    try:
        adx_result = compute_adx(df, period=14)
        df["adx"] = adx_result["adx"]
        df["adx_norm"] = adx_result["adx_norm"]
        df["plus_di"] = adx_result["plus_di"]
        df["minus_di"] = adx_result["minus_di"]
    except Exception:
        df["adx"] = float("nan")
        df["adx_norm"] = float("nan")
        df["plus_di"] = float("nan")
        df["minus_di"] = float("nan")

    # ── ATR SMA (20-bar) for consensus module ─────────────────────────────
    df["atr_sma20"] = df["atr"].rolling(20).mean()

    # ── Rate of Change (momentum, period=10) ──────────────────────────────
    from .indicators import compute_roc as _roc

    df["roc_10"] = _roc(df["close"], period=10)

    # ── VWAP z-score (mean-reversion distance) ────────────────────────────
    if "vwap" in df.columns and "atr" in df.columns:
        from .indicators import compute_vwap_zscore as _vwap_z

        df["vwap_zscore"] = _vwap_z(df["close"], df["vwap"], df["atr"])
    else:
        df["vwap_zscore"] = float("nan")

    return df


def layer1_regime(row: pd.Series, trin_value: Optional[float] = None) -> str:
    """
    Determine market regime from Layer 1 indicators.

    Args:
        row: DataFrame row with indicator values.
        trin_value: Optional TRIN (Arms Index) value from IB Gateway RTH data.
                    Only available during regular trading hours — pass None otherwise.
    """
    consumed = row.get("atr_consumed_pct", 0)
    phase = row.get("phase_val", 0)
    compression = row.get("phase_compression", False)
    ema_trend = row.get("ema_trend", "neutral")

    if consumed > 90:
        return "EXHAUSTED"
    if compression and consumed < 50:
        return "COMPRESSION"
    if ema_trend == "bullish" and consumed < 70 and phase > 0:
        regime = "TRENDING_BULL"
    elif ema_trend == "bearish" and consumed < 70 and phase < 0:
        regime = "TRENDING_BEAR"
    else:
        regime = "RANGE_BOUND"

    # Apply TRIN modifier — only when TRIN data is available (RTH hours)
    if trin_value is not None:
        trin_class = classify_trin(trin_value)
        if trin_class == "BLOWOFF_TOP" and regime == "TRENDING_BULL":
            regime = "EXHAUSTED"  # Downgrade — extreme buying often precedes reversal
        elif trin_class == "CAPITULATION" and regime == "TRENDING_BEAR":
            regime = "EXHAUSTED"  # Downgrade — potential reversal zone

    return regime


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
    above_vah = bool(row.get("above_vah", False))
    below_val = bool(row.get("below_val", False))
    above_ib_high = bool(row.get("above_ib_high", False))
    below_ib_low = bool(row.get("below_ib_low", False))

    result = {
        "position": "NEUTRAL_STRUCTURE",
        "above_vah": above_vah,
        "below_val": below_val,
        "above_ib_high": above_ib_high,
        "below_ib_low": below_ib_low,
        "vpoc": float(row.get("vpoc", 0) or 0),
        "va_high": float(row.get("va_high", 0) or 0),
        "va_low": float(row.get("va_low", 0) or 0),
    }

    if above_vah and above_ib_high:
        result["position"] = "BUYER_CONTROL"
    elif below_val and below_ib_low:
        result["position"] = "SELLER_CONTROL"

    # Discord IB level fields (additive — None when not injected)
    result["discord_ibu50"] = (
        float(row["discord_ibu50"])
        if "discord_ibu50" in row and row["discord_ibu50"] is not None
        else None
    )
    result["discord_ibu100"] = (
        float(row["discord_ibu100"])
        if "discord_ibu100" in row and row["discord_ibu100"] is not None
        else None
    )
    result["discord_ibd50"] = (
        float(row["discord_ibd50"])
        if "discord_ibd50" in row and row["discord_ibd50"] is not None
        else None
    )
    result["discord_ibd100"] = (
        float(row["discord_ibd100"])
        if "discord_ibd100" in row and row["discord_ibd100"] is not None
        else None
    )

    return result


def layer3_bias(row: pd.Series) -> str:
    """Determine directional bias from Layer 3 indicators."""
    bull_count = 0
    bear_count = 0

    # KAMA signal
    if row.get("kama_signal") == "long":
        bull_count += 1
    elif row.get("kama_signal") == "short":
        bear_count += 1

    # STC direction
    stc_sig = row.get("stc_signal", "neutral")
    if stc_sig in ("oversold", "rising"):
        bull_count += 1
    elif stc_sig in ("overbought", "falling"):
        bear_count += 1

    # Volume
    vol_sig = row.get("volume_signal", "balanced")
    if vol_sig == "buyer_dominant":
        bull_count += 1
    elif vol_sig == "seller_dominant":
        bear_count += 1

    # EMA trend
    ema = row.get("ema_trend", "neutral")
    if ema == "bullish":
        bull_count += 1
    elif ema == "bearish":
        bear_count += 1

    # VWAP position adds to directional score
    try:
        vwap_val = row.get("vwap")
        if vwap_val is not None and not pd.isna(vwap_val):
            close_price = float(row.get("close", 0))
            vwap_f = float(vwap_val)
            if vwap_f > 0:
                if close_price > vwap_f * 1.001:
                    bull_count += 1  # price above VWAP = bullish
                elif close_price < vwap_f * 0.999:
                    bear_count += 1  # price below VWAP = bearish
    except Exception:
        pass  # VWAP is advisory

    if bull_count >= 4:
        bias = "STRONG_BULL"
    elif bull_count >= 3 or (bull_count == 2 and ema == "bullish"):
        bias = "LEAN_BULL"
    elif bear_count >= 4:
        bias = "STRONG_BEAR"
    elif bear_count >= 3 or (bear_count == 2 and ema == "bearish"):
        bias = "LEAN_BEAR"
    else:
        bias = "NEUTRAL"

    # ADX directional filter: downgrade STRONG signals in non-trending markets
    try:
        adx_value = row.get("adx")
        if adx_value is not None and not pd.isna(adx_value):
            ADX_STRONG_THRESHOLD = 20.0  # Must show directional movement for STRONG signals
            if float(adx_value) < ADX_STRONG_THRESHOLD:
                if bias == "STRONG_BULL":
                    bias = "LEAN_BULL"
                elif bias == "STRONG_BEAR":
                    bias = "LEAN_BEAR"
    except Exception:
        pass  # ADX filter is advisory — never block on failure

    return bias


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
    if regime == "EXHAUSTED":
        phase = row.get("phase_val", 0)
        consumed = row.get("atr_consumed_pct", 0)
        if consumed > 90 and (phase > 61.8 or phase < -61.8):
            return "FADE_EXTREME"
        return "NO_TRADE"

    if bias == "NEUTRAL":
        return "NO_TRADE"

    structure_position = structure.get("position", "NEUTRAL_STRUCTURE")
    above_ib_high = structure.get("above_ib_high", False)
    below_ib_low = structure.get("below_ib_low", False)

    # ── Structure-boosted ENTRY_NOW ───────────────────────────────────────
    # 1. Full alignment: structure confirms bias AND regime is trending
    if (
        structure_position == "BUYER_CONTROL"
        and bias in ("STRONG_BULL", "LEAN_BULL")
        and regime in ("TRENDING_BULL",)
    ):
        return "ENTRY_NOW"

    if (
        structure_position == "SELLER_CONTROL"
        and bias in ("STRONG_BEAR", "LEAN_BEAR")
        and regime in ("TRENDING_BEAR",)
    ):
        return "ENTRY_NOW"

    # 2. IB High breakout: price just crossed above prior bar's high this bar
    #    (prev_above_ib_high=False means it was below IB High last bar)
    prev_above = bool(row.get("prev_above_ib_high", False))
    if above_ib_high and not prev_above and bias in ("STRONG_BULL", "LEAN_BULL"):
        return "ENTRY_NOW"

    # 3. IB Low breakdown: price just crossed below prior bar's low this bar
    bool(row.get("prev_above_ib_high", False))
    # For the downside breakout we re-use the same prev flag directionally:
    # below_ib_low=True this bar means price broke below — no prior-cross flag
    # stored for lows, so accept the signal if we're below IB Low fresh (i.e.
    # IB Low breakout: below_ib_low True and structure is SELLER_CONTROL).
    if (
        below_ib_low
        and structure_position == "SELLER_CONTROL"
        and bias in ("STRONG_BEAR", "LEAN_BEAR")
    ):
        return "ENTRY_NOW"

    # ── Standard STC crossover entry ─────────────────────────────────────
    stc_cross_up = row.get("stc_cross_up", False)
    stc_cross_down = row.get("stc_cross_down", False)

    entry_signal = "NO_TRADE"
    if bias in ("STRONG_BULL", "LEAN_BULL") and stc_cross_up:
        entry_signal = "ENTRY_NOW"
    elif bias in ("STRONG_BEAR", "LEAN_BEAR") and stc_cross_down:
        entry_signal = "ENTRY_NOW"
    else:
        stc_val = row.get("stc_val", 50)
        if 20 <= stc_val <= 80:
            entry_signal = "WAIT_FOR_PULLBACK"

    # Consensus filter: downgrade ENTRY_NOW if 6-factor consensus disagrees
    if entry_signal == "ENTRY_NOW":
        try:
            from backtest.consensus import compute_consensus

            stc_current = float(row.get("stc_val", 50))
            ema_fast = float(row.get("ema_8", row.get("close", 0)))
            ema_slow = float(row.get("ema_21", row.get("close", 0)))
            # ema_slow_prev not available in row — approximate with ema_34 as proxy
            # (ema_34 lags ema_21, so ema_21 > ema_34 means ema_21 is still rising)
            ema_slow_prev = float(row.get("ema_34", ema_slow))
            rsi_raw = row.get("rsi_14", 50.0)
            rsi_val = float(rsi_raw) if rsi_raw is not None and not pd.isna(rsi_raw) else 50.0
            atr_val = (
                float(row.get("atr", 1.0)) if not pd.isna(row.get("atr", float("nan"))) else 1.0
            )
            atr_sma_val = (
                float(row.get("atr_sma20", atr_val))
                if not pd.isna(row.get("atr_sma20", float("nan")))
                else atr_val
            )
            vwap_val_raw = row.get("vwap", None)
            vwap_val = (
                float(vwap_val_raw)
                if vwap_val_raw is not None and not pd.isna(vwap_val_raw)
                else float(row.get("close", 0))
            )
            adx_norm_raw = row.get("adx_norm", None)
            adx_norm_val = (
                float(adx_norm_raw)
                if adx_norm_raw is not None and not pd.isna(adx_norm_raw)
                else 0.25
            )
            roc_val = (
                float(row.get("roc_10", 0.0))
                if not pd.isna(row.get("roc_10", float("nan")))
                else 0.0
            )
            vwap_z_val = (
                float(row.get("vwap_zscore", 0.0))
                if not pd.isna(row.get("vwap_zscore", float("nan")))
                else 0.0
            )

            consensus = compute_consensus(
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                ema_slow_prev=ema_slow_prev,
                rsi=rsi_val,
                atr=atr_val,
                atr_sma=atr_sma_val,
                vwap=vwap_val,
                close=float(row.get("close", 0)),
                adx_norm=adx_norm_val,
                stc_value=stc_current,
                roc=roc_val,
                vwap_zscore=vwap_z_val,
            )

            if not consensus.threshold_met or consensus.direction == "HOLD":
                entry_signal = "WAIT_FOR_PULLBACK"  # Downgrade: consensus not met
        except Exception:
            pass  # Consensus is advisory — never block on error

    return entry_signal


def generate_signals(
    df: pd.DataFrame,
    regime_filter: bool = True,
    stc_oversold: Optional[float] = None,
    stc_overbought: Optional[float] = None,
    symbol: Optional[str] = None,
    adaptive_regime: bool = False,
    volume_filter: bool = False,
    volume_period: int = 20,
    mtf_df: Optional[pd.DataFrame] = None,
    news_blackout: bool = False,
    news_blackout_window: int = 30,
) -> pd.DataFrame:
    """
    Run all 5 layers on each row.
    Adds: regime, structure_position, bias, entry_signal,
          stop_level, target_1, target_2, target_3

    Parameters
    ----------
    regime_filter : bool, default True
        When True (default), EXHAUSTED and COMPRESSION regimes block all
        entries — the conservative, research-validated behaviour that produces
        51 trades / PF 1.51 for MNQ 1h.
        When False, EXHAUSTED and COMPRESSION are downgraded to RANGE_BOUND so
        structure-based entries can still fire.  Pass False only when the
        optimizer's winning parameter set includes regime_filter=False.
    stc_oversold : float, optional
        Override STC oversold threshold.  Defaults to the module-level STC_OS.
    stc_overbought : float, optional
        Override STC overbought threshold.  Defaults to the module-level STC_OB.
    adaptive_regime : bool, default False
        When True, classify each bar's market regime (TRENDING/RANGING/VOLATILE)
        and dynamically apply regime-specific STC thresholds bar-by-bar.
        Walk-forward analysis identified regime dependency as the root cause of
        WFE failure — this flag enables the adaptive fix.
        WARNING: adds ~3s overhead per 10,000 bars. Disable for fast grid search.
    volume_filter : bool, default False
        When True, block ENTRY_NOW signals on bars where volume is below the
        N-period rolling average. Blocked entries are tagged 'LOW_VOLUME_BLOCK'.
    volume_period : int, default 20
        Lookback period for the volume moving average used by volume_filter.
    mtf_df : pd.DataFrame, optional
        Higher-timeframe DataFrame (e.g. 4h) with indicators pre-computed via
        compute_all_indicators(). When provided, the MTFFilter is applied as a
        final gate: 1h ENTRY_NOW signals are blocked unless the 4h STC trend
        aligns with the entry direction. Adds 'mtf_aligned' column to output.
    news_blackout : bool, default False
        When True, block ENTRY_NOW signals that fall within `news_blackout_window`
        minutes of major economic events (FOMC, CPI, NFP, GDP). Blocked entries
        are tagged 'NEWS_BLACKOUT'. Adds 'news_blocked' column to output.
    news_blackout_window : int, default 30
        Minutes before AND after each event to block entries. For daily bars,
        use 480 (8 hours) to block the entire trading day of the event.
    """
    df = compute_all_indicators(df)

    # ── Discord IB extension levels (additive enrichment) ────────────────
    # Populate discord_ibu50/ibu100/ibd50/ibd100 columns from historical
    # IB reports in discord_ib_reports. One DB lookup per unique date (cached).
    # layer2_structure() reads these columns; they are None when unavailable.
    if _IB_AVAILABLE and symbol is not None:
        try:
            discord_sym = {"MNQ": "NQ", "MCL": "CL", "MES": "ES", "MGC": "GC"}.get(
                symbol.upper(), symbol.upper()
            )
            for col in ("discord_ibu50", "discord_ibu100", "discord_ibd50", "discord_ibd100"):
                if col not in df.columns:
                    df[col] = None

            # Batch by date — one query per unique trading date
            if hasattr(df.index, "date"):
                unique_dates = df.index.date
            else:
                unique_dates = [None] * len(df)

            _date_cache: dict = {}
            for i, bar_date in enumerate(unique_dates):
                if bar_date is None:
                    continue
                if bar_date not in _date_cache:
                    _date_cache[bar_date] = _ib_provider.get_levels(discord_sym, bar_date)
                lvl = _date_cache[bar_date]
                if lvl:
                    df.iloc[i, df.columns.get_loc("discord_ibu50")] = lvl.get("ibu50")
                    df.iloc[i, df.columns.get_loc("discord_ibu100")] = lvl.get("ibu100")
                    df.iloc[i, df.columns.get_loc("discord_ibd50")] = lvl.get("ibd50")
                    df.iloc[i, df.columns.get_loc("discord_ibd100")] = lvl.get("ibd100")
        except Exception:
            pass  # IB level enrichment is additive — never block signal generation

    # ── Optional regime-adaptive STC classification ───────────────────────
    if adaptive_regime:
        from backtest.regime import RegimeClassifier

        clf = RegimeClassifier()
        df = clf.classify(df)
        # adaptive_stc_os / adaptive_stc_ob columns now exist; they will
        # override the static thresholds on a per-bar basis below.

    # ── Load per-instrument optimized parameters ──────────────────────────
    if symbol is not None:
        inst_params = INSTRUMENT_PARAMS.get(symbol.upper())
        if inst_params:
            if len(inst_params) >= 7:
                os_val, ob_val, stop_atr, t1_atr, t2_atr, t3_atr, inst_regime = inst_params
                # Apply per-instrument regime_filter unless caller explicitly set it
                regime_filter = inst_regime
            else:
                os_val, ob_val, stop_atr, t1_atr, t2_atr, t3_atr = inst_params
            # Override STC thresholds only if not explicitly passed
            if stc_oversold is None:
                stc_oversold = os_val
            if stc_overbought is None:
                stc_overbought = ob_val
        else:
            stop_atr = 0.70
            t1_atr = 1.00
            t2_atr = 1.80
            t3_atr = 2.618
    else:
        stop_atr = 0.70
        t1_atr = 1.00
        t2_atr = 1.80
        t3_atr = 2.618

    # ── Adaptive regime: recompute STC signals using per-bar thresholds ─────
    if adaptive_regime and "adaptive_stc_os" in df.columns:
        # Each bar uses the regime-specific OS/OB for its crossover detection.
        # This is a vectorized per-bar computation: broadcasting column vs column.
        stc_v = df["stc_val"]
        stc_prev_v = stc_v.shift(1).fillna(50)
        adapt_os = df["adaptive_stc_os"]
        adapt_ob = df["adaptive_stc_ob"]

        df["stc_cross_up"] = (stc_v > adapt_os) & (stc_prev_v <= adapt_os)
        df["stc_cross_down"] = (stc_v < adapt_ob) & (stc_prev_v >= adapt_ob)

        stc_signal = pd.Series("neutral", index=df.index)
        stc_signal[stc_v < adapt_os] = "oversold"
        stc_signal[stc_v > adapt_ob] = "overbought"
        rising = (stc_v > stc_prev_v) & (stc_signal == "neutral")
        falling = (stc_v < stc_prev_v) & (stc_signal == "neutral")
        stc_signal[rising] = "rising"
        stc_signal[falling] = "falling"
        df["stc_signal"] = stc_signal
        df["stc_prev"] = stc_prev_v

    # ── Optional static STC threshold overrides (mirrors optimizer._compute_signals) ──
    elif stc_oversold is not None or stc_overbought is not None:
        os_val = stc_oversold if stc_oversold is not None else STC_OS
        ob_val = stc_overbought if stc_overbought is not None else STC_OB

        stc_prev = df["stc_val"].shift(1).fillna(50)
        df["stc_cross_up"] = (df["stc_val"] > os_val) & (stc_prev <= os_val)
        df["stc_cross_down"] = (df["stc_val"] < ob_val) & (stc_prev >= ob_val)

        stc_signal = pd.Series("neutral", index=df.index)
        stc_signal[df["stc_val"] < os_val] = "oversold"
        stc_signal[df["stc_val"] > ob_val] = "overbought"
        rising = (df["stc_val"] > stc_prev) & (stc_signal == "neutral")
        falling = (df["stc_val"] < stc_prev) & (stc_signal == "neutral")
        stc_signal[rising] = "rising"
        stc_signal[falling] = "falling"
        df["stc_signal"] = stc_signal
        df["stc_prev"] = stc_prev

    regimes = []
    structures = []
    structure_positions = []
    biases = []
    entries = []

    for _idx, row in df.iterrows():
        regime = layer1_regime(row)
        # Regime filter bypass: match optimizer._compute_signals() behaviour.
        # When regime_filter=False, downgrade blocking regimes to RANGE_BOUND
        # so structure-based entries (IB breakout, buyer/seller control) fire.
        if not regime_filter and regime in ("EXHAUSTED", "COMPRESSION"):
            regime = "RANGE_BOUND"
        structure = layer2_structure(row)
        bias = layer3_bias(row)
        entry = layer4_entry(row, regime, bias, structure)

        regimes.append(regime)
        structures.append(structure)
        structure_positions.append(structure["position"])
        biases.append(bias)
        entries.append(entry)

    df["regime"] = regimes
    df["structure_position"] = structure_positions
    df["bias"] = biases
    df["entry_signal"] = entries

    # Optionally expose individual structure booleans as columns for downstream
    # analysis / filtering without unpacking the dict manually.
    df["s_above_vah"] = [s["above_vah"] for s in structures]
    df["s_below_val"] = [s["below_val"] for s in structures]
    df["s_above_ib_high"] = [s["above_ib_high"] for s in structures]
    df["s_below_ib_low"] = [s["below_ib_low"] for s in structures]
    df["s_vpoc"] = [s["vpoc"] for s in structures]
    df["s_va_high"] = [s["va_high"] for s in structures]
    df["s_va_low"] = [s["va_low"] for s in structures]

    # Stop and target levels using ATR Fibonacci
    atr = df["atr"].fillna(0)
    close = df["close"]

    # For long entries: stop below, targets above
    # For short entries: stop above, targets below
    is_long = df["bias"].isin(["STRONG_BULL", "LEAN_BULL"])

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
    #
    # stop_atr / t1_atr / t2_atr / t3_atr are set earlier from
    # INSTRUMENT_PARAMS[symbol] when a symbol is provided, otherwise
    # they fall back to the defaults set at lines 408-416 above.

    df["stop_level"] = np.where(is_long, close - stop_atr * atr, close + stop_atr * atr)
    df["target_1"] = np.where(is_long, close + t1_atr * atr, close - t1_atr * atr)
    df["target_2"] = np.where(is_long, close + t2_atr * atr, close - t2_atr * atr)
    df["target_3"] = np.where(is_long, close + t3_atr * atr, close - t3_atr * atr)

    # ── Volume confirmation filter (Improvement #3) ────────────────────
    if volume_filter and "volume" in df.columns:
        vol_ma = df["volume"].rolling(volume_period).mean()
        high_volume = df["volume"] > vol_ma
        # Block entries on low-volume bars
        df.loc[(df["entry_signal"] == "ENTRY_NOW") & ~high_volume, "entry_signal"] = (
            "LOW_VOLUME_BLOCK"
        )
        df["volume_ma"] = vol_ma
        df["high_volume"] = high_volume

    # ── Multi-Timeframe (MTF) confirmation filter ─────────────────────────
    if mtf_df is not None:
        from .mtf_filter import MTFFilter

        mtf = MTFFilter(cross_lookback=3)
        df["mtf_aligned"] = mtf.check_alignment(df, mtf_df)
        # Block entries where 4h trend does not align
        blocked = (df["entry_signal"] == "ENTRY_NOW") & (~df["mtf_aligned"])
        df.loc[blocked, "entry_signal"] = "MTF_BLOCKED"
    else:
        df["mtf_aligned"] = True

    # ── News/Event Blackout filter (Improvement #4) ─────────────────────
    if news_blackout:
        from .news_blackout import EconomicCalendar

        calendar = EconomicCalendar()
        # Vectorized: check each bar's timestamp against the calendar
        news_blocked_mask = pd.Series(False, index=df.index)
        for idx_ts in df.index:
            if calendar.is_blackout(idx_ts, window_minutes=news_blackout_window):
                news_blocked_mask.loc[idx_ts] = True
        df["news_blocked"] = news_blocked_mask
        # Only block ENTRY_NOW signals (leave other signal types unchanged)
        blocked = (df["entry_signal"] == "ENTRY_NOW") & df["news_blocked"]
        df.loc[blocked, "entry_signal"] = "NEWS_BLACKOUT"
    else:
        df["news_blocked"] = False

    return df


# ── Layer 5 — Conviction-Aware Position Sizing ────────────────────────────────
# Scales base risk percentage by the alignment strength across Layers 1-4.
# Safety layer hard limits (config.py) still apply — this is pre-safety sizing.
SIZING_FULL = 1.00  # STRONG bias + TRENDING + directional structure
SIZING_HIGH = 0.80  # STRONG bias + TRENDING (any structure)
SIZING_HALF = 0.50  # LEAN bias OR RANGING regime
SIZING_MIN = 0.25  # All other cases (minimum viable position)


def compute_position_size(
    bias: str,
    regime: str,
    structure_position: str,
    base_risk_pct: float,
) -> float:
    """
    Layer 5: compute risk-scaled position size from signal conviction.
    Returns the actual risk_pct to use (a fraction of base_risk_pct × multiplier).

    Parameters
    ----------
    bias : str
        Bias from layer 3 (STRONG_BULL, STRONG_BEAR, LEAN_BULL, LEAN_BEAR, NEUTRAL)
    regime : str
        Regime from layer 1 (TRENDING_BULL, TRENDING_BEAR, RANGING, VOLATILE, etc)
    structure_position : str
        Structure position from layer 2 (BUYER_CONTROL, SELLER_CONTROL, NEUTRAL, etc)
    base_risk_pct : float
        Base risk percentage (e.g., 0.02 for 2% risk per trade)

    Returns
    -------
    float
        Actual risk percentage to use, scaled by conviction multiplier
    """
    strong_bias = bias in ("STRONG_BULL", "STRONG_BEAR")
    lean_bias = bias in ("LEAN_BULL", "LEAN_BEAR")
    trending = regime in ("TRENDING_BULL", "TRENDING_BEAR")
    directional_structure = structure_position in ("BUYER_CONTROL", "SELLER_CONTROL")

    if strong_bias and trending and directional_structure:
        multiplier = SIZING_FULL
    elif strong_bias and trending:
        multiplier = SIZING_HIGH
    elif lean_bias or not trending:
        multiplier = SIZING_HALF
    else:
        multiplier = SIZING_MIN

    return round(base_risk_pct * multiplier, 6)


def inject_ib_levels(df: pd.DataFrame, symbol: str, db_path: str | None = None) -> pd.DataFrame:
    """Opt-in: inject Discord IB levels as additive discord_ columns. No-op on any error."""
    for c in ("discord_ibu50", "discord_ibu100", "discord_ibd50", "discord_ibd100"):
        if c not in df.columns:
            df[c] = None
    try:
        from discord.ib_levels import IBLevelProvider

        sym = IBLevelProvider.SYMBOL_MAP.get(symbol.upper(), symbol.upper())
        p = _ib_provider if _IB_AVAILABLE and db_path is None else IBLevelProvider(db_path=db_path)
        dates = df.index.date if hasattr(df.index, "date") else [None] * len(df)
        seen: dict = {}
        for i, dt in enumerate(dates):
            if dt and dt not in seen:
                try:
                    seen[dt] = p.get_levels(sym, dt)
                except Exception:
                    seen[dt] = None
            lv = seen.get(dt)
            if lv:
                for k, c in zip(
                    ("ibu50", "ibu100", "ibd50", "ibd100"),
                    ("discord_ibu50", "discord_ibu100", "discord_ibd50", "discord_ibd100"),
                    strict=False,
                ):
                    df.at[df.index[i], c] = lv.get(k)
    except Exception as exc:
        logger.warning(f"[IB_LEVELS] inject_ib_levels error: {exc}")
    return df
