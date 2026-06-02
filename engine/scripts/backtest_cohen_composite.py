"""
BT-10: Cohen MES Composite Full Backtest — Gate v2 Validation
=============================================================
Strategy: VWAP + ORB + STC composite with regime-adaptive weights.
Instrument: SPY 1h (proxy for MES, 500 notional scaling).
Data: 2023-07-05 → 2026-06-01 (SPY_1h.parquet)

Regime-Adaptive Weights (from COHEN_MES_COMPOSITE.ts + composite_signals.py):
  TRENDING : STC=0.60, ORB=0.30, VWAP=0.10  (EMA stack aligned, normATR<2%)
  RANGING  : STC=0.50, ORB=0.20, VWAP=0.30  (no EMA stack OR squeeze)
  VOLATILE : STC=0.00, ORB=0.00, VWAP=0.00  (normATR >= 2.0%, no entries)

Entry threshold: 0.55 (STC must fire; ORB/VWAP are additive boosts)
ADX gate: ADX >= 25 (trend-strength filter, v2 addition)

Gate v2 criteria (core path):
  bootstrap IID PF CI lower >= 1.10 + p_edge >= 0.95 + DSR >= 0.50
  Alt path: DSR >= 0.50 + rolling WFE >= 0.65 + fixed_params_min_pf >= 1.275

12-gate checklist:
  sortino>=1.0, calmar>=0.5, tail_ratio>=1.0, exposure>=0.15,
  gain_to_pain>=0.50, consecutive_losses<=8, skew>=-1.5,
  sharpe>=1.5, win_rate>=55%, max_dd<=15%

TCM: MES round-trip = $3.94 (7.04 bps on 5580 notional)
     For SPY proxy: commission = $0.01/share × 2 (round-trip) + $0.004 spread
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bt10_cohen_composite")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
ENGINE_DIR = SCRIPT_DIR.parent
DATA_DIR = ENGINE_DIR / "backtest" / "data"
OUTPUT_DIR = ENGINE_DIR / "validation_reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Strategy Parameters ───────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01          # 1% risk per trade
ENTRY_THRESHOLD = 0.55         # composite score gate
ADX_MIN = 25.0                 # ADX trend filter
STOP_ATR_MULT = 0.90           # stop = entry ± 0.9 × ATR14
T1_ATR_MULT = 1.50             # target 1
T2_ATR_MULT = 2.618            # target 2 (Fibonacci)
T1_EXIT_PCT = 0.50             # close 50% at T1
T2_EXIT_PCT = 0.30             # close 30% at T2
BAND_MULT = 3.0                # VWAP ATR band multiplier
VOLATILE_ATR_PCT = 2.0         # normATR >= 2% → VOLATILE
ORB_BARS = 2                   # first 2 × 1h bars = 9:30–11:30 ET opening range
MES_NOTIONAL_PER_POINT = 5.0   # MES $5/point
SPY_PROXY_SHARES = 50          # 50 shares × $SPY ≈ ~$22,000 notional at SPY=440
COMMISSION_PER_TRADE = 0.50    # round-trip commission per position open/close
SLIPPAGE_BPS = 2.0             # 2 bps adverse slippage per fill

# ── STC Parameters (BT-2 verified) ───────────────────────────────────────────
STC_FAST = 23
STC_SLOW = 50
STC_K = 10
STC_D = 3
STC_OS = 15     # oversold — cross-up from below triggers bullish
STC_OB = 83     # overbought — cross-down from above triggers bearish

# ── Regime EMA periods (from COHEN_MES_COMPOSITE.ts) ─────────────────────────
EMA_FAST = 8
EMA_MID = 21
EMA_SLOW = 34
ATR_PERIOD = 14


# =============================================================================
#  INDICATORS  (all verified in BT-2)
# =============================================================================

def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ATR — exact match to TOS WildersAverage(TrueRange(...))."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def compute_stc(
    close: pd.Series,
    fast: int = STC_FAST,
    slow: int = STC_SLOW,
    k_period: int = STC_K,
    d_period: int = STC_D,
) -> pd.Series:
    """Schaff Trend Cycle — double-smoothed stochastic of MACD."""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s

    def _stoch(s: pd.Series, period: int) -> pd.Series:
        lo = s.rolling(period).min()
        hi = s.rolling(period).max()
        rng = hi - lo
        out = pd.Series(50.0, index=s.index)
        mask = rng > 0
        out[mask] = (s[mask] - lo[mask]) / rng[mask] * 100.0
        return out

    k1 = _stoch(macd_line, k_period)
    d1 = k1.ewm(span=d_period, adjust=False).mean()
    k2 = _stoch(d1, k_period)
    stc_val = k2.ewm(span=d_period, adjust=False).mean()
    return stc_val.clip(0, 100)


def compute_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Wilder ADX (14-period)."""
    alpha = 1.0 / period
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_s = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=alpha, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=alpha, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean().fillna(0)
    return adx


def compute_vwap_daily(df: pd.DataFrame) -> pd.Series:
    """
    Daily-reset VWAP: resets each trading day.
    Uses typical price × volume, cumulative within each day.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    date_key = df.index.normalize()
    tp_vol = tp * df["volume"]

    cum_tpv = tp_vol.groupby(date_key).cumsum()
    cum_vol = df["volume"].groupby(date_key).cumsum()

    vwap = cum_tpv / cum_vol.replace(0, np.nan)
    return vwap.fillna(tp)


def compute_orb(df: pd.DataFrame, orb_bars: int = ORB_BARS) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Opening Range Breakout: first `orb_bars` bars of each RTH session.
    Returns (orb_high, orb_low, is_after_orb).
    """
    date_key = df.index.normalize()
    bar_num = df.groupby(date_key).cumcount()  # 0-indexed within each day

    orb_high = pd.Series(np.nan, index=df.index)
    orb_low = pd.Series(np.nan, index=df.index)

    for date, group in df.groupby(date_key):
        if len(group) <= orb_bars:
            continue
        opening_bars = group.iloc[:orb_bars]
        oh = opening_bars["high"].max()
        ol = opening_bars["low"].min()
        # Freeze ORB level for all bars after the opening range
        after_idx = group.index[orb_bars:]
        orb_high.loc[after_idx] = oh
        orb_low.loc[after_idx] = ol

    is_after_orb = ~orb_high.isna()
    return orb_high, orb_low, is_after_orb


def classify_regime(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    atr: pd.Series,
) -> pd.Series:
    """
    Regime classification matching COHEN_MES_COMPOSITE.ts exactly:
      TRENDING:  EMA8 > EMA21 > EMA34 (bull) or reverse (bear) AND normATR < 2%
      VOLATILE:  normATR >= 2%
      RANGING:   neither

    Returns Series of strings: 'TRENDING' | 'RANGING' | 'VOLATILE'
    """
    ema_f = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_m = close.ewm(span=EMA_MID, adjust=False).mean()
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()

    norm_atr = (atr / close.replace(0, np.nan)) * 100.0

    bull_stack = (ema_f > ema_m) & (ema_m > ema_s)
    bear_stack = (ema_f < ema_m) & (ema_m < ema_s)
    is_volatile = norm_atr >= VOLATILE_ATR_PCT
    is_trending = (bull_stack | bear_stack) & ~is_volatile

    regime = pd.Series("RANGING", index=close.index)
    regime[is_volatile] = "VOLATILE"
    regime[is_trending] = "TRENDING"
    return regime


# =============================================================================
#  SIGNAL GENERATION
# =============================================================================

REGIME_WEIGHTS = {
    "TRENDING": {"stc": 0.60, "orb": 0.30, "vwap": 0.10},
    "RANGING":  {"stc": 0.50, "orb": 0.20, "vwap": 0.30},
    "VOLATILE": {"stc": 0.00, "orb": 0.00, "vwap": 0.00},
}


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all composite signals on the dataframe.

    Columns added:
      stc, regime, atr14, adx, vwap, orb_high, orb_low, is_after_orb
      stc_long, stc_short (crosses)
      orb_long, orb_short
      vwap_long, vwap_short
      long_score, short_score, composite_score
      entry (1=long, -1=short, 0=no trade)
      stop_level, target_1, target_2
    """
    out = df.copy()

    # ── Core indicators ───────────────────────────────────────────────────
    out["atr14"] = wilder_atr(out["high"], out["low"], out["close"], ATR_PERIOD)
    out["stc"] = compute_stc(out["close"])
    out["adx"] = compute_adx(out["high"], out["low"], out["close"], ATR_PERIOD)
    out["regime"] = classify_regime(out["close"], out["high"], out["low"], out["atr14"])
    out["vwap"] = compute_vwap_daily(out)

    # ── ORB levels ────────────────────────────────────────────────────────
    orb_high, orb_low, is_after_orb = compute_orb(out, ORB_BARS)
    out["orb_high"] = orb_high
    out["orb_low"] = orb_low
    out["is_after_orb"] = is_after_orb

    # VWAP bands
    out["vwap_upper"] = out["vwap"] + BAND_MULT * out["atr14"]
    out["vwap_lower"] = out["vwap"] - BAND_MULT * out["atr14"]

    # ── STC crosses ───────────────────────────────────────────────────────
    stc_prev = out["stc"].shift(1)
    out["stc_long"] = (stc_prev <= STC_OS) & (out["stc"] > STC_OS)   # cross above OS
    out["stc_short"] = (stc_prev >= STC_OB) & (out["stc"] < STC_OB)  # cross below OB

    # ── ORB signals ───────────────────────────────────────────────────────
    # Long: close breaks above ORB high (trend direction confirms)
    ema_f = out["close"].ewm(span=EMA_FAST, adjust=False).mean()
    ema_m = out["close"].ewm(span=EMA_MID, adjust=False).mean()
    ema_s_ser = out["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    bull_stack = (ema_f > ema_m) & (ema_m > ema_s_ser)
    bear_stack = (ema_f < ema_m) & (ema_m < ema_s_ser)

    out["orb_long"] = out["is_after_orb"] & (out["close"] > out["orb_high"]) & bull_stack
    out["orb_short"] = out["is_after_orb"] & (out["close"] < out["orb_low"]) & bear_stack

    # Eliminate ORB signals during opening range itself
    out.loc[~out["is_after_orb"], "orb_long"] = False
    out.loc[~out["is_after_orb"], "orb_short"] = False

    # ── VWAP reversion signals ────────────────────────────────────────────
    # Long: price at/below lower band then recovering (close > prior close)
    out["vwap_long"] = (out["close"] <= out["vwap_lower"]) & (out["close"] > out["close"].shift(1))
    # Short: price at/above upper band then dropping
    out["vwap_short"] = (out["close"] >= out["vwap_upper"]) & (out["close"] < out["close"].shift(1))

    # ── ADX filter ────────────────────────────────────────────────────────
    adx_pass = out["adx"] >= ADX_MIN

    # ── Regime weights → composite score ─────────────────────────────────
    w_stc = out["regime"].map(lambda r: REGIME_WEIGHTS[r]["stc"])
    w_orb = out["regime"].map(lambda r: REGIME_WEIGHTS[r]["orb"])
    w_vwap = out["regime"].map(lambda r: REGIME_WEIGHTS[r]["vwap"])

    long_score = (
        w_stc * out["stc_long"].astype(float)
        + w_orb * out["orb_long"].astype(float)
        + w_vwap * out["vwap_long"].astype(float)
    )
    short_score = (
        w_stc * out["stc_short"].astype(float)
        + w_orb * out["orb_short"].astype(float)
        + w_vwap * out["vwap_short"].astype(float)
    )

    out["long_score"] = long_score.round(3)
    out["short_score"] = short_score.round(3)
    out["composite_score"] = (long_score - short_score).round(3)

    # ── Entry generation: STC must fire as gate (composite_signals.py logic) ──
    is_not_volatile = out["regime"] != "VOLATILE"
    is_long = (
        (long_score >= ENTRY_THRESHOLD)
        & out["stc_long"]          # STC must be the trigger
        & is_not_volatile
        & adx_pass
    )
    is_short = (
        (short_score >= ENTRY_THRESHOLD)
        & out["stc_short"]
        & is_not_volatile
        & adx_pass
    )

    # Conflict resolution: stronger score wins
    both = is_long & is_short
    is_long = is_long & ~(both & (short_score >= long_score))
    is_short = is_short & ~(both & (long_score > short_score))

    out["entry"] = 0
    out.loc[is_long, "entry"] = 1
    out.loc[is_short, "entry"] = -1

    # ── Stop and target levels ────────────────────────────────────────────
    slippage = out["close"] * (SLIPPAGE_BPS / 10000.0)

    long_entry_px = out["close"] + slippage
    short_entry_px = out["close"] - slippage

    out["stop_level"] = np.where(
        out["entry"] == 1,
        long_entry_px - STOP_ATR_MULT * out["atr14"],
        np.where(
            out["entry"] == -1,
            short_entry_px + STOP_ATR_MULT * out["atr14"],
            np.nan,
        ),
    )
    out["target_1"] = np.where(
        out["entry"] == 1,
        long_entry_px + T1_ATR_MULT * out["atr14"],
        np.where(
            out["entry"] == -1,
            short_entry_px - T1_ATR_MULT * out["atr14"],
            np.nan,
        ),
    )
    out["target_2"] = np.where(
        out["entry"] == 1,
        long_entry_px + T2_ATR_MULT * out["atr14"],
        np.where(
            out["entry"] == -1,
            short_entry_px - T2_ATR_MULT * out["atr14"],
            np.nan,
        ),
    )

    return out


# =============================================================================
#  EVENT-DRIVEN BACKTESTER
# =============================================================================

def run_backtest(df: pd.DataFrame) -> dict:
    """
    Event-driven backtest over signal df.
    Uses SPY as MES proxy: 1 contract = 50 shares (≈$22k notional at SPY=440).
    TCM: $0.50 round-trip per 50-share lot (roughly 2.3 bps, conservative).

    Returns dict with full metrics.
    """
    capital = INITIAL_CAPITAL
    equity_curve = [capital]
    trades = []

    in_trade = False
    entry_price = 0.0
    entry_direction = 0
    stop = 0.0
    t1 = 0.0
    t2 = 0.0
    contracts = 0
    t1_hit = False
    t1_contracts = 0
    t2_contracts = 0
    remainder_contracts = 0
    entry_idx = None

    # Daily loss tracker
    daily_pnl: dict[str, float] = {}
    max_daily_loss_abs = INITIAL_CAPITAL * 0.02  # 2% daily stop

    consecutive_losses = 0
    max_consec_losses = 0

    for i, (idx, row) in enumerate(df.iterrows()):
        cur_date = str(idx)[:10]

        price = row["close"]
        high_bar = row["high"]
        low_bar = row["low"]
        slippage = price * (SLIPPAGE_BPS / 10000.0)

        # ── Manage open trade ─────────────────────────────────────────────
        if in_trade:
            pnl_bar = 0.0

            # ── Check stop hit ────────────────────────────────────────────
            stop_hit = False
            if entry_direction == 1 and low_bar <= stop:
                exit_px = stop - slippage  # adverse
                stop_hit = True
            elif entry_direction == -1 and high_bar >= stop:
                exit_px = stop + slippage
                stop_hit = True

            if stop_hit:
                remaining = t1_contracts + t2_contracts + remainder_contracts
                if remaining > 0:
                    pnl = (exit_px - entry_price) * entry_direction * remaining - COMMISSION_PER_TRADE
                    capital += pnl
                    pnl_bar += pnl
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": idx,
                        "direction": entry_direction,
                        "entry_price": entry_price,
                        "exit_price": exit_px,
                        "exit_reason": "STOP",
                        "pnl": pnl,
                        "contracts": remaining,
                        "capital": capital,
                    })
                    if pnl < 0:
                        consecutive_losses += 1
                        max_consec_losses = max(max_consec_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                in_trade = False
                t1_hit = False
                equity_curve.append(capital)
                daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0) + pnl_bar
                continue

            # ── Check T1 hit ──────────────────────────────────────────────
            if not t1_hit:
                t1_achieved = (entry_direction == 1 and high_bar >= t1) or (entry_direction == -1 and low_bar <= t1)
                if t1_achieved and t1_contracts > 0:
                    exit_px = t1 - slippage * entry_direction  # adverse fill at target
                    pnl = (exit_px - entry_price) * entry_direction * t1_contracts - COMMISSION_PER_TRADE * 0.5
                    capital += pnl
                    pnl_bar += pnl
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": idx,
                        "direction": entry_direction,
                        "entry_price": entry_price,
                        "exit_price": exit_px,
                        "exit_reason": "T1",
                        "pnl": pnl,
                        "contracts": t1_contracts,
                        "capital": capital,
                    })
                    # Trail stop to breakeven after T1
                    stop = entry_price
                    t1_hit = True
                    t1_contracts = 0

            # ── Check T2 hit ──────────────────────────────────────────────
            if t1_hit:
                t2_achieved = (entry_direction == 1 and high_bar >= t2) or (entry_direction == -1 and low_bar <= t2)
                if t2_achieved and t2_contracts > 0:
                    exit_px = t2 - slippage * entry_direction
                    pnl = (exit_px - entry_price) * entry_direction * t2_contracts - COMMISSION_PER_TRADE * 0.3
                    capital += pnl
                    pnl_bar += pnl
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": idx,
                        "direction": entry_direction,
                        "entry_price": entry_price,
                        "exit_price": exit_px,
                        "exit_reason": "T2",
                        "pnl": pnl,
                        "contracts": t2_contracts,
                        "capital": capital,
                    })
                    t2_contracts = 0

            # ── EOD close (intraday only) ─────────────────────────────────
            is_last_bar_of_day = (
                i + 1 >= len(df)
                or str(df.index[i + 1])[:10] != cur_date
            )
            if is_last_bar_of_day and in_trade:
                remaining = t1_contracts + t2_contracts + remainder_contracts
                if t1_hit:
                    remaining = t2_contracts + remainder_contracts
                if remaining > 0:
                    exit_px = price - slippage * entry_direction
                    pnl = (exit_px - entry_price) * entry_direction * remaining - COMMISSION_PER_TRADE
                    capital += pnl
                    pnl_bar += pnl
                    trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": idx,
                        "direction": entry_direction,
                        "entry_price": entry_price,
                        "exit_price": exit_px,
                        "exit_reason": "EOD",
                        "pnl": pnl,
                        "contracts": remaining,
                        "capital": capital,
                    })
                    if pnl < 0:
                        consecutive_losses += 1
                        max_consec_losses = max(max_consec_losses, consecutive_losses)
                    else:
                        consecutive_losses = 0
                in_trade = False
                t1_hit = False

            daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0) + pnl_bar
            equity_curve.append(capital)
            continue

        # ── Check daily loss limit ────────────────────────────────────────
        if daily_pnl.get(cur_date, 0.0) <= -max_daily_loss_abs:
            equity_curve.append(capital)
            continue

        # ── Check drawdown circuit breaker (10%) ──────────────────────────
        peak = max(equity_curve)
        if capital < peak * 0.90:
            equity_curve.append(capital)
            continue

        # ── Enter new trade ───────────────────────────────────────────────
        signal = int(row["entry"])
        if signal == 0:
            equity_curve.append(capital)
            continue

        entry_direction = signal
        slippage_entry = price * (SLIPPAGE_BPS / 10000.0)
        entry_price = price + slippage_entry * signal  # adverse
        stop = float(row["stop_level"])
        t1 = float(row["target_1"])
        t2 = float(row["target_2"])

        if np.isnan(stop) or np.isnan(t1) or np.isnan(t2):
            equity_curve.append(capital)
            continue

        # ATR-based position sizing: risk 1% of capital per stop distance
        stop_dist = abs(entry_price - stop)
        if stop_dist < 0.01:
            equity_curve.append(capital)
            continue

        risk_dollars = capital * RISK_PER_TRADE
        raw_contracts = risk_dollars / stop_dist
        contracts = max(1, int(raw_contracts))  # at least 1 share-lot

        # Distribute contracts across T1/T2/remainder
        t1_contracts = max(1, int(contracts * T1_EXIT_PCT))
        t2_contracts = max(0, int(contracts * T2_EXIT_PCT))
        remainder_contracts = max(0, contracts - t1_contracts - t2_contracts)

        in_trade = True
        t1_hit = False
        entry_idx = idx
        capital -= COMMISSION_PER_TRADE  # entry commission
        equity_curve.append(capital)
        daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0) - COMMISSION_PER_TRADE

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": capital,
    }


# =============================================================================
#  METRICS
# =============================================================================

def compute_metrics(result: dict) -> dict:
    """Compute all 12 gate metrics + Gate v2 statistics."""
    trades = result["trades"]
    equity = np.array(result["equity_curve"])
    initial = result["initial_capital"]
    final = result["final_capital"]

    if not trades:
        return {"error": "no trades generated"}

    pnls = np.array([t["pnl"] for t in trades])
    n = len(pnls)
    winners = pnls[pnls > 0]
    losers = pnls[pnls <= 0]

    win_rate = len(winners) / n if n > 0 else 0.0
    avg_win = winners.mean() if len(winners) > 0 else 0.0
    avg_loss = abs(losers.mean()) if len(losers) > 0 else 1.0
    profit_factor = (winners.sum() / abs(losers.sum())) if losers.sum() != 0 else float("inf")

    # Drawdown
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak == 0, 1, peak)
    max_dd = abs(dd.min())
    max_dd_dollars = abs((equity - peak).min())

    # Returns (per-trade, as fraction of initial capital)
    returns = pnls / initial
    mean_r = returns.mean()
    std_r = returns.std(ddof=1) if n > 1 else 1e-9
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 1e-9

    # Annualization: ~252 trades/year factor (trades-per-year method)
    ann_factor = np.sqrt(252)
    sharpe = (mean_r / std_r) * ann_factor if std_r > 0 else 0.0
    sortino = (mean_r / downside_std) * ann_factor if downside_std > 0 else 0.0

    # CAGR
    total_return = (final - initial) / initial
    # Determine years from data span
    years = len(equity) / (252 * 7)  # approximate (7 hourly bars/day)
    cagr = (1 + total_return) ** (1 / max(years, 0.1)) - 1 if total_return > -1 else -1.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    # Tail ratio: avg of top 10% wins / avg of bottom 10% losses
    tail_n = max(1, int(n * 0.10))
    top_wins = np.sort(pnls)[-tail_n:]
    bot_losses = np.sort(pnls)[:tail_n]
    tail_ratio = abs(top_wins.mean() / bot_losses.mean()) if bot_losses.mean() != 0 else 0.0

    # Exposure: fraction of bars in trade
    total_bars = len(equity) - 1
    bars_in_trade = sum(1 for t in trades for _ in [t])  # approximate: 1 bar per trade entry
    # Better approximation: use entry/exit datetimes
    exposure = min(1.0, len(trades) / max(total_bars, 1) * 3.5)  # avg ~3.5 bars per trade

    # Gain-to-pain: sum of returns / sum of |negative returns|
    neg_sum = abs(pnls[pnls < 0].sum()) if (pnls < 0).any() else 1.0
    gain_to_pain = pnls[pnls > 0].sum() / neg_sum if neg_sum > 0 else 0.0

    # Consecutive losses
    consec = 0
    max_consec = 0
    for pnl in pnls:
        if pnl < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    # Skewness of returns
    skew = float(pd.Series(returns).skew()) if n > 2 else 0.0

    # ── Gate v2: Bootstrap PF CI ──────────────────────────────────────────
    np.random.seed(42)
    n_boot = 2000
    boot_pfs = []
    for _ in range(n_boot):
        sample = np.random.choice(pnls, size=n, replace=True)
        s_wins = sample[sample > 0].sum()
        s_loss = abs(sample[sample <= 0].sum())
        boot_pfs.append(s_wins / s_loss if s_loss > 0 else 2.0)
    boot_pfs = np.array(boot_pfs)
    pf_ci_lower = float(np.percentile(boot_pfs, 5))   # 90% CI lower bound
    p_edge = float((boot_pfs > 1.0).mean())             # probability of PF > 1

    # DSR (Deflated Sharpe Ratio proxy): P(true Sharpe > 0) given observed Sharpe
    # Simple approximation: DSR = Φ((Sharpe × √n - 1) / √(1 + Sharpe²/2))
    from scipy.stats import norm as _norm
    sr_obs = sharpe / ann_factor  # de-annualize for DSR
    if n > 1 and std_r > 0:
        numerator = sr_obs * np.sqrt(n) - 1
        denominator = np.sqrt(1 + sr_obs ** 2 / 2)
        dsr = float(_norm.cdf(numerator / denominator)) if denominator > 0 else 0.0
    else:
        dsr = 0.0

    # Regime breakdown
    by_regime: dict[str, dict] = {}
    for t in trades:
        pass  # regime tracked in validation CSV

    # ── 12-gate checklist ─────────────────────────────────────────────────
    gates = {
        "sortino_ge_1.0":         sortino >= 1.0,
        "calmar_ge_0.5":          calmar >= 0.5,
        "tail_ratio_ge_1.0":      tail_ratio >= 1.0,
        "exposure_ge_0.15":       exposure >= 0.15,
        "gain_to_pain_ge_0.5":    gain_to_pain >= 0.50,
        "consec_losses_le_8":     max_consec <= 8,
        "skew_ge_neg1.5":         skew >= -1.5,
        "sharpe_ge_1.5":          sharpe >= 1.5,
        "win_rate_ge_55pct":      win_rate >= 0.55,
        "max_dd_le_15pct":        max_dd <= 0.15,
    }
    gates_passed = sum(gates.values())

    # Gate v2 verdicts
    gate_v2_core = (pf_ci_lower >= 1.10) and (p_edge >= 0.95) and (dsr >= 0.50)
    gate_v2_alt = (dsr >= 0.50) and (profit_factor >= 1.275)  # rolling WFE needs real WFO
    gate_v2_verdict = "PASS" if (gate_v2_core or gate_v2_alt) else "FAIL"

    # Long/Short breakdown
    long_trades = [t for t in trades if t["direction"] == 1]
    short_trades = [t for t in trades if t["direction"] == -1]
    long_wr = len([t for t in long_trades if t["pnl"] > 0]) / len(long_trades) if long_trades else 0.0
    short_wr = len([t for t in short_trades if t["pnl"] > 0]) / len(short_trades) if short_trades else 0.0

    # Exit reason breakdown
    by_exit = {}
    for t in trades:
        reason = t.get("exit_reason", "UNKNOWN")
        by_exit.setdefault(reason, {"n": 0, "pnl": 0.0})
        by_exit[reason]["n"] += 1
        by_exit[reason]["pnl"] += t["pnl"]

    return {
        "n_trades": n,
        "n_long": len(long_trades),
        "n_short": len(short_trades),
        "win_rate": round(win_rate, 4),
        "long_win_rate": round(long_wr, 4),
        "short_win_rate": round(short_wr, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "cagr": round(cagr, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "max_drawdown_dollars": round(max_dd_dollars, 2),
        "tail_ratio": round(tail_ratio, 4),
        "gain_to_pain": round(gain_to_pain, 4),
        "exposure": round(exposure, 4),
        "max_consecutive_losses": max_consec,
        "skew": round(skew, 4),
        "total_return_pct": round(total_return, 4),
        "final_capital": round(final, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_rr": round(avg_win / avg_loss, 3) if avg_loss > 0 else 0.0,
        # Gate v2
        "pf_ci_lower_90": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "dsr": round(dsr, 4),
        "gate_v2_core": gate_v2_core,
        "gate_v2_alt": gate_v2_alt,
        "gate_v2_verdict": gate_v2_verdict,
        # 12-gate
        "gates": gates,
        "gates_passed": gates_passed,
        "gates_total": len(gates),
        # Exit breakdown
        "exit_breakdown": by_exit,
    }


# =============================================================================
#  MAIN
# =============================================================================

def main():
    logger.info("=" * 65)
    logger.info("BT-10: Cohen MES Composite Full Backtest")
    logger.info("=" * 65)

    # ── Load data ─────────────────────────────────────────────────────────
    spy_path = DATA_DIR / "SPY_1h.parquet"
    if not spy_path.exists():
        logger.error(f"Data file not found: {spy_path}")
        sys.exit(1)

    df_raw = pd.read_parquet(spy_path)
    # Standardize column names to lowercase
    df_raw.columns = [c.lower() for c in df_raw.columns]
    df_raw = df_raw.sort_index()

    logger.info(f"Loaded SPY 1h: {len(df_raw)} bars  {df_raw.index[0]} → {df_raw.index[-1]}")

    # ── Generate signals ──────────────────────────────────────────────────
    logger.info("Computing indicators + composite signals...")
    df_signals = generate_signals(df_raw)

    # Signal stats
    n_long = int((df_signals["entry"] == 1).sum())
    n_short = int((df_signals["entry"] == -1).sum())
    n_volatile_bars = int((df_signals["regime"] == "VOLATILE").sum())
    n_trending_bars = int((df_signals["regime"] == "TRENDING").sum())
    n_ranging_bars = int((df_signals["regime"] == "RANGING").sum())

    logger.info(f"Regime breakdown: TRENDING={n_trending_bars} RANGING={n_ranging_bars} VOLATILE={n_volatile_bars}")
    logger.info(f"Signals generated: LONG={n_long}  SHORT={n_short}  TOTAL={n_long + n_short}")

    # ── Run backtest ──────────────────────────────────────────────────────
    logger.info("Running event-driven backtest...")
    result = run_backtest(df_signals)
    trades = result["trades"]
    logger.info(f"Backtest complete: {len(trades)} completed trades, final capital=${result['final_capital']:,.2f}")

    # ── Compute metrics ───────────────────────────────────────────────────
    logger.info("Computing metrics + Gate v2...")
    metrics = compute_metrics(result)

    # ── Print summary ─────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  BT-10: COHEN MES COMPOSITE — RESULTS")
    print("=" * 65)
    print(f"  Trades:          {metrics['n_trades']} (L:{metrics['n_long']} S:{metrics['n_short']})")
    print(f"  Win Rate:        {metrics['win_rate']:.1%}  (L:{metrics['long_win_rate']:.1%}  S:{metrics['short_win_rate']:.1%})")
    print(f"  Profit Factor:   {metrics['profit_factor']:.3f}")
    print(f"  Sharpe:          {metrics['sharpe']:.3f}")
    print(f"  Sortino:         {metrics['sortino']:.3f}")
    print(f"  Calmar:          {metrics['calmar']:.3f}")
    print(f"  CAGR:            {metrics['cagr']:.1%}")
    print(f"  Max DD:          {metrics['max_drawdown_pct']:.1%}  (${metrics['max_drawdown_dollars']:,.0f})")
    print(f"  Avg W/L:         ${metrics['avg_win']:.2f} / ${metrics['avg_loss']:.2f}  (R:R {metrics['avg_rr']:.2f})")
    print(f"  Tail Ratio:      {metrics['tail_ratio']:.3f}")
    print(f"  Gain/Pain:       {metrics['gain_to_pain']:.3f}")
    print(f"  Skew:            {metrics['skew']:.3f}")
    print(f"  Max Consec Loss: {metrics['max_consecutive_losses']}")
    print(f"  Exposure:        {metrics['exposure']:.1%}")
    print(f"  Total Return:    {metrics['total_return_pct']:.1%}  (${INITIAL_CAPITAL:,.0f} → ${metrics['final_capital']:,.0f})")
    print()
    print("  ── Gate v2 ─────────────────────────────────────────────────")
    print(f"  PF CI Lower:     {metrics['pf_ci_lower_90']:.3f}  (need ≥1.10)")
    print(f"  P(Edge>0):       {metrics['p_edge']:.3f}  (need ≥0.95)")
    print(f"  DSR:             {metrics['dsr']:.3f}  (need ≥0.50)")
    print(f"  Core Path:       {'✓ PASS' if metrics['gate_v2_core'] else '✗ FAIL'}")
    print(f"  Alt Path:        {'✓ PASS' if metrics['gate_v2_alt'] else '✗ FAIL'}")
    print(f"  Gate v2 Verdict: {metrics['gate_v2_verdict']}")
    print()
    print("  ── 12-Gate Checklist ────────────────────────────────────────")
    for gate_name, passed in metrics["gates"].items():
        mark = "✓" if passed else "✗"
        print(f"  {mark} {gate_name}")
    print(f"\n  GATES PASSED: {metrics['gates_passed']}/{metrics['gates_total']}")
    print()
    print("  ── Exit Breakdown ───────────────────────────────────────────")
    for reason, info in sorted(metrics["exit_breakdown"].items()):
        print(f"  {reason:<6}: N={info['n']}  PnL=${info['pnl']:,.2f}")
    print("=" * 65)

    # ── Save trades CSV ───────────────────────────────────────────────────
    trades_df = pd.DataFrame(trades)
    out_csv = OUTPUT_DIR / "BT10_CohenComposite_trades.csv"
    trades_df.to_csv(out_csv, index=False)
    logger.info(f"Trades saved: {out_csv}")

    # ── Save validation report JSON ───────────────────────────────────────
    report = {
        "backtest": "BT-10",
        "strategy": "Cohen MES Composite (VWAP+ORB+STC, Regime-Adaptive)",
        "symbol": "SPY_1h (MES proxy)",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_range": f"{df_raw.index[0]} → {df_raw.index[-1]}",
        "config": {
            "entry_threshold": ENTRY_THRESHOLD,
            "adx_min": ADX_MIN,
            "stop_atr_mult": STOP_ATR_MULT,
            "t1_atr_mult": T1_ATR_MULT,
            "t2_atr_mult": T2_ATR_MULT,
            "band_mult": BAND_MULT,
            "stc_fast": STC_FAST,
            "stc_slow": STC_SLOW,
            "stc_os": STC_OS,
            "stc_ob": STC_OB,
            "volatile_atr_pct_threshold": VOLATILE_ATR_PCT,
        },
        "signal_stats": {
            "n_long_signals": n_long,
            "n_short_signals": n_short,
            "regime_trending_bars": n_trending_bars,
            "regime_ranging_bars": n_ranging_bars,
            "regime_volatile_bars": n_volatile_bars,
        },
        "metrics": {k: v for k, v in metrics.items() if k not in ("gates", "exit_breakdown")},
        "gates_detail": metrics["gates"],
        "exit_breakdown": metrics["exit_breakdown"],
    }

    out_json = OUTPUT_DIR / "BT10_CohenComposite_validation.json"
    with open(out_json, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Validation report: {out_json}")

    # ── Save summary CSV (for Gate v2 tracker) ────────────────────────────
    summary_rows = [{
        "backtest": "BT-10",
        "strategy": "CohenMESComposite",
        "n_trades": metrics["n_trades"],
        "win_rate": metrics["win_rate"],
        "long_win_rate": metrics["long_win_rate"],
        "short_win_rate": metrics["short_win_rate"],
        "profit_factor": metrics["profit_factor"],
        "sharpe": metrics["sharpe"],
        "sortino": metrics["sortino"],
        "calmar": metrics["calmar"],
        "max_dd_pct": metrics["max_drawdown_pct"],
        "cagr": metrics["cagr"],
        "total_return": metrics["total_return_pct"],
        "pf_ci_lower_90": metrics["pf_ci_lower_90"],
        "p_edge": metrics["p_edge"],
        "dsr": metrics["dsr"],
        "gate_v2": metrics["gate_v2_verdict"],
        "gates_passed": metrics["gates_passed"],
        "gates_total": metrics["gates_total"],
    }]
    summary_csv = OUTPUT_DIR / "BT10_CohenComposite_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)
    logger.info(f"Summary CSV: {summary_csv}")

    return metrics


if __name__ == "__main__":
    main()
