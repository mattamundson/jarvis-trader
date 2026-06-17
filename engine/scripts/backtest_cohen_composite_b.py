"""
BT-10b: Cohen MES Composite — Long-Only + Overnight Hold Variant
================================================================
Changes vs BT-10:
  1. LONG-ONLY: short entries disabled entirely (SPY 2023–2026 structural bull)
  2. OVERNIGHT HOLD: EOD close removed; position can hold up to MAX_HOLD_BARS (3 days)
  3. T1 = 1.0×ATR (was 1.50×ATR) — achievable within 1–2 intraday sessions
  4. T2 = 2.0×ATR (was 2.618) — kept for partial exit upside
  5. TRAILING STOP: after T1 hit, trail stop to breakeven; after T2 hit, trail to T1
  6. MAX_HOLD_BARS = 21 (3 trading days × 7 h/day) — hard exit if neither T1/T2 nor stop
  7. ADX_MIN lowered to 20 (from 25) — long side at SPY ADX 20 still has momentum

Hypothesis: removing 47.8% WR shorts (PnL -$296) and holding overnight for
            T1 completion will lift WR to ≥59%, PF ≥1.30, Sharpe ≥0.80.

Gate v2 criteria (core path):
  bootstrap IID PF CI lower ≥1.10 + p_edge ≥0.95 + DSR ≥0.50
  Alt path: DSR ≥0.50 + PF ≥1.275

10-gate checklist:
  sortino≥1.0, calmar≥0.5, tail_ratio≥1.0, exposure≥0.15,
  gain_to_pain≥0.50, consecutive_losses≤8, skew≥-1.5,
  sharpe≥1.5, win_rate≥55%, max_dd≤15%
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
logger = logging.getLogger("bt10b_cohen_longonly")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
ENGINE_DIR = SCRIPT_DIR.parent
DATA_DIR = ENGINE_DIR / "backtest" / "data"
OUTPUT_DIR = ENGINE_DIR / "validation_reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Strategy Parameters (BT-10b modifications in caps comments) ───────────────
INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01          # 1% risk per trade
ENTRY_THRESHOLD = 0.55         # composite score gate
ADX_MIN = 20.0                 # LOWERED from 25 → 20 (long-only, less restrictive)
STOP_ATR_MULT = 0.90           # stop = entry - 0.9×ATR14 (unchanged)
T1_ATR_MULT = 1.00             # REDUCED from 1.50 → 1.00×ATR (more achievable intraday)
T2_ATR_MULT = 2.00             # REDUCED from 2.618 → 2.00×ATR
T1_EXIT_PCT = 0.50             # close 50% at T1
T2_EXIT_PCT = 0.30             # close 30% at T2
MAX_HOLD_BARS = 21             # NEW: max 3 trading days (7 h/day) before forced exit
BAND_MULT = 3.0                # VWAP ATR band multiplier
VOLATILE_ATR_PCT = 2.0         # normATR >= 2% → VOLATILE
ORB_BARS = 2                   # first 2 × 1h bars = 9:30–11:30 ET opening range
COMMISSION_PER_TRADE = 0.50    # round-trip commission per full position
SLIPPAGE_BPS = 2.0             # 2 bps adverse slippage per fill

# ── STC Parameters (BT-2 verified, unchanged) ─────────────────────────────────
STC_FAST = 23
STC_SLOW = 50
STC_K = 10
STC_D = 3
STC_OS = 15
STC_OB = 83

# ── Regime EMA periods ────────────────────────────────────────────────────────
EMA_FAST = 8
EMA_MID = 21
EMA_SLOW = 34
ATR_PERIOD = 14


# =============================================================================
#  INDICATORS  (identical to BT-10, all BT-2 verified)
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
    d2 = k2.ewm(span=d_period, adjust=False).mean()
    return d2


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ADX."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=close.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=close.index)
    atr = wilder_atr(high, low, close, period)
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False).mean().fillna(0)


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Daily-resetting VWAP."""
    df = df.copy()
    df["date"] = df.index.normalize() if hasattr(df.index, "normalize") else pd.to_datetime(df.index).normalize()
    df["tp"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["cum_tp_vol"] = df.groupby("date").apply(
        lambda g: (g["tp"] * g["volume"]).cumsum()
    ).reset_index(level=0, drop=True)
    return df["cum_tp_vol"] / df["cum_vol"].replace(0, np.nan)


# =============================================================================
#  SIGNAL GENERATION  (long-only version)
# =============================================================================

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate composite signals — LONG ONLY.
    Short entries are suppressed: entry = max(0, long_signal).
    """
    out = df.copy()

    # ── Core indicators ───────────────────────────────────────────────────
    out["atr14"] = wilder_atr(out["high"], out["low"], out["close"])
    out["adx"] = compute_adx(out["high"], out["low"], out["close"])
    out["stc"] = compute_stc(out["close"])

    out["ema_fast"] = out["close"].ewm(span=EMA_FAST, adjust=False).mean()
    out["ema_mid"] = out["close"].ewm(span=EMA_MID, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=EMA_SLOW, adjust=False).mean()

    # VWAP — use mid-price if volume not available
    if "volume" in out.columns and out["volume"].sum() > 0:
        try:
            out["vwap"] = compute_vwap(out)
        except Exception:
            out["vwap"] = (out["high"] + out["low"] + out["close"]) / 3.0
    else:
        out["vwap"] = (out["high"] + out["low"] + out["close"]) / 3.0

    # ── Regime classification ─────────────────────────────────────────────
    norm_atr = out["atr14"] / out["close"] * 100.0
    ema_stack_bull = (out["ema_fast"] > out["ema_mid"]) & (out["ema_mid"] > out["ema_slow"])
    squeeze = norm_atr < 0.40  # tight squeeze = RANGING hint

    out["regime"] = "RANGING"
    out.loc[ema_stack_bull & (norm_atr < VOLATILE_ATR_PCT), "regime"] = "TRENDING"
    out.loc[norm_atr >= VOLATILE_ATR_PCT, "regime"] = "VOLATILE"

    # ── Regime-adaptive weights ───────────────────────────────────────────
    w_stc = pd.Series(0.50, index=out.index)
    w_orb = pd.Series(0.20, index=out.index)
    w_vwap = pd.Series(0.30, index=out.index)
    is_trending = out["regime"] == "TRENDING"
    w_stc[is_trending] = 0.60
    w_orb[is_trending] = 0.30
    w_vwap[is_trending] = 0.10

    # ── STC signals ───────────────────────────────────────────────────────
    stc_cross_up = (out["stc"] > STC_OS) & (out["stc"].shift(1) <= STC_OS)
    out["stc_long"] = stc_cross_up

    # ── ORB signals — long only ───────────────────────────────────────────
    # Opening range = first ORB_BARS bars of each day
    out["bar_of_day"] = out.groupby(
        out.index.normalize() if hasattr(out.index, "normalize") else pd.to_datetime(out.index).normalize()
    ).cumcount()
    orb_high = out.groupby(
        out.index.normalize() if hasattr(out.index, "normalize") else pd.to_datetime(out.index).normalize()
    )["high"].transform(lambda x: x.iloc[:ORB_BARS].max() if len(x) >= ORB_BARS else x.max())

    out["orb_long"] = (out["bar_of_day"] >= ORB_BARS) & (out["close"] > orb_high)

    # ── VWAP signals — long only ──────────────────────────────────────────
    vwap_band_up = out["vwap"] + BAND_MULT * out["atr14"]
    out["vwap_long"] = (out["close"] > out["vwap"]) & (out["close"] < vwap_band_up)

    # ── ADX gate (long only) ──────────────────────────────────────────────
    adx_pass = out["adx"] >= ADX_MIN

    # ── Composite scores (long only) ──────────────────────────────────────
    long_score = (
        w_stc * out["stc_long"].astype(float)
        + w_orb * out["orb_long"].astype(float)
        + w_vwap * out["vwap_long"].astype(float)
    )

    out["long_score"] = long_score.round(3)

    # ── Entry generation: LONG ONLY ───────────────────────────────────────
    is_not_volatile = out["regime"] != "VOLATILE"
    is_long = (
        (long_score >= ENTRY_THRESHOLD)
        & out["stc_long"]      # STC must be the trigger
        & is_not_volatile
        & adx_pass
    )

    out["entry"] = 0
    out.loc[is_long, "entry"] = 1   # NO shorts

    # ── Stop and target levels ────────────────────────────────────────────
    slippage = out["close"] * (SLIPPAGE_BPS / 10000.0)
    long_entry_px = out["close"] + slippage

    out["stop_level"] = np.where(
        out["entry"] == 1,
        long_entry_px - STOP_ATR_MULT * out["atr14"],
        np.nan,
    )
    out["target_1"] = np.where(
        out["entry"] == 1,
        long_entry_px + T1_ATR_MULT * out["atr14"],
        np.nan,
    )
    out["target_2"] = np.where(
        out["entry"] == 1,
        long_entry_px + T2_ATR_MULT * out["atr14"],
        np.nan,
    )

    return out


# =============================================================================
#  EVENT-DRIVEN BACKTESTER  (overnight hold enabled)
# =============================================================================

def run_backtest(df: pd.DataFrame) -> dict:
    """
    Long-only event-driven backtest with overnight hold.
    Key changes vs BT-10:
      - No EOD force-close
      - MAX_HOLD_BARS hard stop (21 bars = 3 trading days)
      - T1=1.0×ATR, T2=2.0×ATR
      - After T1 hit: trail stop to breakeven
      - After T2 hit: trail stop to T1 price
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
    t1_price_level = 0.0   # T1 exact level (for trailing after T2)
    contracts = 0
    t1_hit = False
    t2_hit = False
    t1_contracts = 0
    t2_contracts = 0
    remainder_contracts = 0
    entry_idx = None
    bars_in_trade = 0     # NEW: track hold duration

    # Daily loss tracker
    daily_pnl: dict[str, float] = {}
    max_daily_loss_abs = INITIAL_CAPITAL * 0.02  # 2% daily stop

    consecutive_losses = 0
    max_consec_losses = 0

    total_bars_in_trade = 0  # for exposure calculation

    for i, (idx, row) in enumerate(df.iterrows()):
        cur_date = str(idx)[:10]
        price = row["close"]
        high_bar = row["high"]
        low_bar = row["low"]
        slippage = price * (SLIPPAGE_BPS / 10000.0)
        pnl_bar = 0.0

        if in_trade:
            bars_in_trade += 1
            total_bars_in_trade += 1
            remaining = t1_contracts + t2_contracts + remainder_contracts

            # ── Check stop ────────────────────────────────────────────────
            stop_hit = (entry_direction == 1 and low_bar <= stop)
            if stop_hit and remaining > 0:
                exit_px = stop + slippage * entry_direction  # adverse fill at stop
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
                    "bars_held": bars_in_trade,
                })
                if pnl < 0:
                    consecutive_losses += 1
                    max_consec_losses = max(max_consec_losses, consecutive_losses)
                else:
                    consecutive_losses = 0
                in_trade = False
                t1_hit = False
                t2_hit = False
                bars_in_trade = 0
                equity_curve.append(capital)
                daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0) + pnl_bar
                continue

            # ── Check T1 hit ──────────────────────────────────────────────
            if not t1_hit:
                t1_achieved = (entry_direction == 1 and high_bar >= t1)
                if t1_achieved and t1_contracts > 0:
                    exit_px = t1 - slippage  # slightly adverse at target
                    pnl = (exit_px - entry_price) * t1_contracts - COMMISSION_PER_TRADE * T1_EXIT_PCT
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
                        "bars_held": bars_in_trade,
                    })
                    # Trail stop to breakeven after T1
                    stop = entry_price
                    t1_price_level = exit_px
                    t1_hit = True
                    t1_contracts = 0

            # ── Check T2 hit ──────────────────────────────────────────────
            if t1_hit and not t2_hit:
                t2_achieved = (entry_direction == 1 and high_bar >= t2)
                if t2_achieved and t2_contracts > 0:
                    exit_px = t2 - slippage
                    pnl = (exit_px - entry_price) * t2_contracts - COMMISSION_PER_TRADE * T2_EXIT_PCT
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
                        "bars_held": bars_in_trade,
                    })
                    # Trail stop to T1 level after T2
                    stop = t1_price_level
                    t2_hit = True
                    t2_contracts = 0

            # ── Recalculate remaining after T1/T2 exits ───────────────────
            remaining = t1_contracts + t2_contracts + remainder_contracts

            # ── MAX_HOLD_BARS forced exit (new for BT-10b) ─────────────────
            if bars_in_trade >= MAX_HOLD_BARS and remaining > 0:
                exit_px = price - slippage
                pnl = (exit_px - entry_price) * entry_direction * remaining - COMMISSION_PER_TRADE
                capital += pnl
                pnl_bar += pnl
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": idx,
                    "direction": entry_direction,
                    "entry_price": entry_price,
                    "exit_price": exit_px,
                    "exit_reason": "MAX_HOLD",
                    "pnl": pnl,
                    "contracts": remaining,
                    "capital": capital,
                    "bars_held": bars_in_trade,
                })
                if pnl < 0:
                    consecutive_losses += 1
                    max_consec_losses = max(max_consec_losses, consecutive_losses)
                else:
                    consecutive_losses = 0
                in_trade = False
                t1_hit = False
                t2_hit = False
                bars_in_trade = 0
                daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0) + pnl_bar
                equity_curve.append(capital)
                continue

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
        if signal != 1:   # LONG ONLY — only enter on signal=1
            equity_curve.append(capital)
            continue

        entry_direction = signal
        slippage_entry = price * (SLIPPAGE_BPS / 10000.0)
        entry_price = price + slippage_entry  # adverse fill
        stop = float(row["stop_level"])
        t1 = float(row["target_1"])
        t2 = float(row["target_2"])

        if np.isnan(stop) or np.isnan(t1) or np.isnan(t2):
            equity_curve.append(capital)
            continue

        stop_dist = abs(entry_price - stop)
        if stop_dist < 0.01:
            equity_curve.append(capital)
            continue

        risk_dollars = capital * RISK_PER_TRADE
        raw_contracts = risk_dollars / stop_dist
        contracts = max(1, int(raw_contracts))

        # Split contracts
        t1_contracts = max(1, int(contracts * T1_EXIT_PCT))
        t2_contracts = max(0, int(contracts * T2_EXIT_PCT))
        remainder_contracts = contracts - t1_contracts - t2_contracts

        in_trade = True
        t1_hit = False
        t2_hit = False
        t1_price_level = t1
        entry_idx = idx
        bars_in_trade = 0

        equity_curve.append(capital)
        daily_pnl[cur_date] = daily_pnl.get(cur_date, 0.0)  # init

    # ── Force-close any open trade at end of data ─────────────────────────
    if in_trade:
        remaining = t1_contracts + t2_contracts + remainder_contracts
        if remaining > 0:
            last_price = df["close"].iloc[-1]
            last_idx = df.index[-1]
            slippage = last_price * (SLIPPAGE_BPS / 10000.0)
            exit_px = last_price - slippage
            pnl = (exit_px - entry_price) * entry_direction * remaining - COMMISSION_PER_TRADE
            capital += pnl
            trades.append({
                "entry_idx": entry_idx,
                "exit_idx": last_idx,
                "direction": entry_direction,
                "entry_price": entry_price,
                "exit_price": exit_px,
                "exit_reason": "EOD_FINAL",
                "pnl": pnl,
                "contracts": remaining,
                "capital": capital,
                "bars_held": bars_in_trade,
            })

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "final_capital": capital,
        "total_bars_in_trade": total_bars_in_trade,
    }


# =============================================================================
#  METRICS  (identical computation to BT-10, adapted for long-only)
# =============================================================================

def compute_metrics(result: dict) -> dict:
    trades = result["trades"]
    equity = np.array(result["equity_curve"])
    initial = INITIAL_CAPITAL
    final = result["final_capital"]
    n = len(trades)

    if n == 0:
        return {"n_trades": 0, "gate_v2_verdict": "FAIL", "gates_passed": 0, "gates_total": 10}

    pnls = np.array([t["pnl"] for t in trades])
    winners = pnls[pnls > 0]
    losers = pnls[pnls < 0]

    win_rate = len(winners) / n
    avg_win = winners.mean() if len(winners) > 0 else 0.0
    avg_loss = abs(losers.mean()) if len(losers) > 0 else 1.0
    profit_factor = (winners.sum() / abs(losers.sum())) if losers.sum() != 0 else float("inf")

    # Drawdown
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak == 0, 1, peak)
    max_dd = abs(dd.min())
    max_dd_dollars = abs((equity - peak).min())

    # Returns
    returns = pnls / initial
    mean_r = returns.mean()
    std_r = returns.std(ddof=1) if n > 1 else 1e-9
    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 1e-9

    ann_factor = np.sqrt(252)
    sharpe = (mean_r / std_r) * ann_factor if std_r > 0 else 0.0
    sortino = (mean_r / downside_std) * ann_factor if downside_std > 0 else 0.0

    # CAGR (SPY 1h: ~7 bars/day, ~252 days/year)
    total_bars = len(equity) - 1
    years = total_bars / (252 * 7)
    total_return = (final - initial) / initial
    cagr = (1 + total_return) ** (1 / max(years, 0.1)) - 1 if total_return > -1 else -1.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    # Tail ratio
    tail_n = max(1, int(n * 0.10))
    top_wins = np.sort(pnls)[-tail_n:]
    bot_losses = np.sort(pnls)[:tail_n]
    tail_ratio = abs(top_wins.mean() / bot_losses.mean()) if bot_losses.mean() != 0 else 0.0

    # Exposure: fraction of total bars in trade
    exposure = min(1.0, result["total_bars_in_trade"] / max(total_bars, 1))

    # Gain-to-pain
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

    # Skew
    skew = float(pd.Series(returns).skew()) if n > 2 else 0.0

    # Hold time stats
    hold_bars = [t.get("bars_held", 0) for t in trades]
    avg_hold_bars = np.mean(hold_bars) if hold_bars else 0.0
    max_hold_bars_actual = max(hold_bars) if hold_bars else 0

    # ── Gate v2: Bootstrap PF CI ──────────────────────────────────────────
    np.random.seed(42)
    n_boot = 2000
    boot_pfs = []
    for _ in range(n_boot):
        sample = np.random.choice(pnls, size=n, replace=True)
        s_wins = sample[sample > 0].sum()
        s_loss = abs(sample[sample <= 0].sum())
        boot_pfs.append(s_wins / s_loss if s_loss > 0 else 2.0)
    boot_pfs_arr = np.array(boot_pfs)
    pf_ci_lower = float(np.percentile(boot_pfs_arr, 5))
    p_edge = float((boot_pfs_arr > 1.0).mean())

    # DSR
    from scipy.stats import norm as _norm
    sr_obs = sharpe / ann_factor
    if n > 1 and std_r > 0:
        numerator = sr_obs * np.sqrt(n) - 1
        denominator = np.sqrt(1 + sr_obs ** 2 / 2)
        dsr = float(_norm.cdf(numerator / denominator)) if denominator > 0 else 0.0
    else:
        dsr = 0.0

    # ── 10-gate checklist ─────────────────────────────────────────────────
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

    gate_v2_core = (pf_ci_lower >= 1.10) and (p_edge >= 0.95) and (dsr >= 0.50)
    gate_v2_alt = (dsr >= 0.50) and (profit_factor >= 1.275)
    gate_v2_verdict = "PASS" if (gate_v2_core or gate_v2_alt) else "FAIL"

    # Exit reason breakdown
    by_exit: dict[str, dict] = {}
    for t in trades:
        reason = t.get("exit_reason", "UNKNOWN")
        by_exit.setdefault(reason, {"n": 0, "pnl": 0.0, "avg_hold": []})
        by_exit[reason]["n"] += 1
        by_exit[reason]["pnl"] += t["pnl"]
        by_exit[reason]["avg_hold"].append(t.get("bars_held", 0))
    for r in by_exit:
        holds = by_exit[r]["avg_hold"]
        by_exit[r]["avg_hold_bars"] = round(np.mean(holds), 1) if holds else 0.0
        del by_exit[r]["avg_hold"]

    return {
        "n_trades": n,
        "n_long": n,   # all long
        "n_short": 0,
        "win_rate": round(win_rate, 4),
        "long_win_rate": round(win_rate, 4),
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
        "avg_hold_bars": round(avg_hold_bars, 1),
        "max_hold_bars_actual": max_hold_bars_actual,
        # Gate v2
        "pf_ci_lower_90": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "dsr": round(dsr, 4),
        "gate_v2_core": gate_v2_core,
        "gate_v2_alt": gate_v2_alt,
        "gate_v2_verdict": gate_v2_verdict,
        # 10-gate
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
    logger.info("BT-10b: Cohen MES Composite — Long-Only + Overnight Hold")
    logger.info("=" * 65)

    spy_path = DATA_DIR / "SPY_1h.parquet"
    if not spy_path.exists():
        logger.error(f"Data file not found: {spy_path}")
        sys.exit(1)

    df_raw = pd.read_parquet(spy_path)
    df_raw.columns = [c.lower() for c in df_raw.columns]
    df_raw = df_raw.sort_index()
    logger.info(f"Loaded SPY 1h: {len(df_raw)} bars  {df_raw.index[0]} → {df_raw.index[-1]}")

    logger.info("Computing indicators + long-only signals...")
    df_signals = generate_signals(df_raw)

    n_long = int((df_signals["entry"] == 1).sum())
    n_trending_bars = int((df_signals["regime"] == "TRENDING").sum())
    n_ranging_bars = int((df_signals["regime"] == "RANGING").sum())
    n_volatile_bars = int((df_signals["regime"] == "VOLATILE").sum())
    logger.info(f"Regime breakdown: TRENDING={n_trending_bars} RANGING={n_ranging_bars} VOLATILE={n_volatile_bars}")
    logger.info(f"Long signals: {n_long}  (shorts suppressed)")

    logger.info("Running event-driven backtest (overnight hold enabled)...")
    result = run_backtest(df_signals)
    trades = result["trades"]
    logger.info(f"Backtest complete: {len(trades)} trades, final capital=${result['final_capital']:,.2f}")

    logger.info("Computing metrics + Gate v2...")
    metrics = compute_metrics(result)

    # ── Print summary ─────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  BT-10b: COHEN COMPOSITE — LONG-ONLY + OVERNIGHT HOLD")
    print("=" * 65)
    print(f"  Trades:          {metrics['n_trades']} (all long)")
    print(f"  Win Rate:        {metrics['win_rate']:.1%}")
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
    print(f"  Avg Hold:        {metrics['avg_hold_bars']:.1f} bars  (max={metrics['max_hold_bars_actual']})")
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
    print("  ── 10-Gate Checklist ────────────────────────────────────────")
    for gate_name, passed in metrics["gates"].items():
        mark = "✓" if passed else "✗"
        print(f"  {mark} {gate_name}")
    print(f"\n  GATES PASSED: {metrics['gates_passed']}/{metrics['gates_total']}")
    print()
    print("  ── Exit Breakdown ───────────────────────────────────────────")
    for reason, info in sorted(metrics["exit_breakdown"].items()):
        print(f"  {reason:<10}: N={info['n']}  PnL=${info['pnl']:,.2f}  AvgHold={info['avg_hold_bars']:.1f}bars")
    print()
    print("  ── vs BT-10 Comparison ──────────────────────────────────────")
    print("  Metric       BT-10       BT-10b      Delta")
    print(f"  WinRate      53.3%       {metrics['win_rate']:.1%}     {'▲' if metrics['win_rate'] > 0.533 else '▼'}")
    print(f"  PF           0.949       {metrics['profit_factor']:.3f}     {'▲' if metrics['profit_factor'] > 0.949 else '▼'}")
    print(f"  Sharpe      -0.381       {metrics['sharpe']:.3f}     {'▲' if metrics['sharpe'] > -0.381 else '▼'}")
    print(f"  Trades       135         {metrics['n_trades']}         {'▲' if metrics['n_trades'] > 135 else '▼'} (long-only reduction expected)")
    print(f"  Gates        4/10        {metrics['gates_passed']}/10")
    print("=" * 65)

    # ── Save outputs ──────────────────────────────────────────────────────
    trades_df = pd.DataFrame(trades)
    out_csv = OUTPUT_DIR / "BT10b_LongOnly_trades.csv"
    trades_df.to_csv(out_csv, index=False)
    logger.info(f"Trades CSV: {out_csv}")

    report = {
        "backtest": "BT-10b",
        "strategy": "Cohen MES Composite — Long-Only + Overnight Hold",
        "symbol": "SPY_1h (MES proxy)",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_range": f"{df_raw.index[0]} → {df_raw.index[-1]}",
        "config": {
            "long_only": True,
            "eod_close": False,
            "max_hold_bars": MAX_HOLD_BARS,
            "entry_threshold": ENTRY_THRESHOLD,
            "adx_min": ADX_MIN,
            "stop_atr_mult": STOP_ATR_MULT,
            "t1_atr_mult": T1_ATR_MULT,
            "t2_atr_mult": T2_ATR_MULT,
            "trailing_stop_after_t1": True,
            "trailing_stop_after_t2": True,
        },
        "signal_stats": {
            "n_long_signals": n_long,
            "n_short_signals": 0,
            "regime_trending_bars": n_trending_bars,
            "regime_ranging_bars": n_ranging_bars,
            "regime_volatile_bars": n_volatile_bars,
        },
        "metrics": {k: v for k, v in metrics.items() if k not in ("gates", "exit_breakdown")},
        "gates_detail": metrics["gates"],
        "exit_breakdown": metrics["exit_breakdown"],
    }

    out_json = OUTPUT_DIR / "BT10b_LongOnly_validation.json"
    with open(out_json, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Validation JSON: {out_json}")

    summary_rows = [{
        "backtest": "BT-10b",
        "strategy": "CohenMESComposite_LongOnly",
        "n_trades": metrics["n_trades"],
        "win_rate": metrics["win_rate"],
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
    summary_csv = OUTPUT_DIR / "BT10b_LongOnly_summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_csv, index=False)
    logger.info(f"Summary CSV: {summary_csv}")

    return metrics


if __name__ == "__main__":
    main()
