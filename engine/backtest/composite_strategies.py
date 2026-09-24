"""
JARVIS Composite Strategy Signal Generators — TPV / ODF / MRB.

Three orthogonal alpha sources for MES (and generally any futures/equity cache
with the canonical OHLCV contract), built to the same output contract as
`trend_signals.generate_sma_trend_signals` so they drop into the existing
Backtester + iterate.py harness unchanged.

  TPV  Trend-Pullback with Volatility Targeting   (momentum)
       EMA(fast) vs EMA(slow) trend filter; enter on pullback to EMA(pull)
       with close-reversal confirmation; ATR trailing exit; VIX-gated.
  ODF  Overnight Drift + Intraday Fade            (session structure)
       DIRECT session-return model (NOT Backtester): close->next-open drift
       with daily momentum + VIX gate. Returns a metrics dict + PnL series
       for MC. The Backtester cannot express close->open gap capture, so this
       one is computed honestly at the daily level.
  MRB  Guarded Counter-Trend Mean Reversion       (overreaction)
       VIX <= pctile gate, dead-trend gate (EMA bands flat), Bollinger touch +
       RSI extreme + reversal confirmation + volume spike; +1xATR target,
       -1xATR stop, 6-bar time-stop. Reversion only in calm regimes.

Contract for TPV/MRB (Backtester path), identical to SMA trend:
    entry_signal  : "ENTRY_NOW" | "NO_TRADE"
    exit_signal   : "EXIT_NOW"  | "NO_EXIT"
    stop_level    : initial stop (intrabar stop-out)
    target_1/2/3  : profit targets (MRB: target_1 = +1xATR)
    bias          : "STRONG_BULL" | "STRONG_BEAR" (NEVER NEUTRAL at entry)
    regime        : informational
    atr           : ATR(14) series
    vix_level     : VIX at each bar (when vix_df given)

Rules inherited from jarvis-deep-validation skill:
  - Never hand-roll lookahead. All signals use data available at bar close.
  - VIX tiers are point-in-time rolling percentiles (backtest.vix_percentile_regime).
  - Cost discipline: realistic tier must survive; MC bootstrap on PnL list.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.trend_signals import _wilder_atr  # reuse the battle-tested ATR

_ATR_PERIOD = 14
_RV_WINDOW = 20
_RV_ANNUAL_FACTOR = 252 * 24  # 1h bars


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _vix_series_and_tiers(
    df: pd.DataFrame,
    vix_df: pd.DataFrame | None,
    vix_min: float,
    vix_max: float,
    vix_regime_block: tuple[str, ...] | None,
    vix_regime_lookback: int,
) -> tuple[pd.Series | None, pd.Series | None]:
    """Forward-fill daily VIX + optional percentile-tier series onto bar index."""
    if vix_df is None or vix_df.empty:
        return None, None
    vix_daily = vix_df["close"].copy()
    # Normalize both sides to a tz-naive midnight index before the ffill reindex:
    # pandas >= 3.0 raises on a mixed-tz comparison (tz-aware deep cache vs naive
    # yfinance VIX index). See trend_signals._daily_date_index.
    from backtest.trend_signals import _daily_date_index

    vix_daily.index = _daily_date_index(vix_daily.index)
    bar_dates = _daily_date_index(df.index)
    vix_series = vix_daily.reindex(bar_dates, method="ffill")
    vix_series.index = df.index
    tier_series = None
    if vix_regime_block:
        from backtest.vix_percentile_regime import classify_vix_regime

        tiers_daily = classify_vix_regime(vix_daily, lookback=vix_regime_lookback).map(
            lambda t: getattr(t, "value", t)
        )
        tier_series = tiers_daily.reindex(bar_dates, method="ffill")
        tier_series.index = df.index
    return vix_series, tier_series


def _vix_gate_ok(
    i: int,
    vix_series: pd.Series | None,
    vix_min: float,
    vix_max: float,
    tier_series: pd.Series | None,
    vix_regime_block: tuple[str, ...] | None,
) -> bool:
    """True when the VIX (absolute or percentile-tier) allows an entry at bar i."""
    if vix_series is not None:
        v = vix_series.iloc[i]
        if pd.isna(v) or not (vix_min <= float(v) <= vix_max):
            return False
    if tier_series is not None:
        t = tier_series.iloc[i]
        if pd.isna(t) or t in vix_regime_block:
            return False
    return True


# ---------------------------------------------------------------------------
# TPV — Trend-Pullback with Volatility Targeting
# ---------------------------------------------------------------------------

def generate_trend_pullback_signals(
    df: pd.DataFrame,
    fast_ema: int = 55,
    slow_ema: int = 200,
    pullback_ema: int = 20,
    atr_trail_mult: float = 2.0,
    initial_stop_mult: float = 1.5,
    min_rv_annualized: float = 0.0,
    vix_df: pd.DataFrame | None = None,
    vix_min: float = 0.0,
    vix_max: float = 999.0,
    vix_regime_block: tuple[str, ...] | None = None,
    vix_regime_lookback: int = 252,
) -> pd.DataFrame:
    """
    EMA trend filter + pullback entry + ATR trailing exit.

    Entry (long): EMA(fast) > EMA(slow) [trend up], price pulls back to
        EMA(pull) [low <= EMA(pull)] then the bar closes back above it.
        Same mirror for shorts.
    Exit: trailing stop = highest_close_since_entry - trail_mult*ATR
        (emitted as exit_signal at bar close) OR fast EMA crosses back
        through slow EMA.
    """
    df = df.copy()
    ema_f = df["close"].ewm(span=fast_ema, adjust=False).mean()
    ema_s = df["close"].ewm(span=slow_ema, adjust=False).mean()
    ema_p = df["close"].ewm(span=pullback_ema, adjust=False).mean()
    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)

    log_ret = np.log(df["close"] / df["close"].shift(1))
    rv_ann = log_ret.rolling(_RV_WINDOW).std() * np.sqrt(_RV_ANNUAL_FACTOR) * 100.0

    vix_series, tier_series = _vix_series_and_tiers(
        df, vix_df, vix_min, vix_max, vix_regime_block, vix_regime_lookback
    )

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    bias_arr = np.full(n, "NEUTRAL", dtype=object)
    regime_arr = np.full(n, "RANGE_BOUND", dtype=object)

    trend_up = ema_f > ema_s
    trend_dn = ema_f < ema_s

    in_trade = False
    direction = None
    current_trail = np.nan
    extreme = np.nan  # highest close (long) / lowest close (short) since entry

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(ema_s.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        low_i = float(df["low"].iloc[i])
        high_i = float(df["high"].iloc[i])
        atr_i = float(atr.iloc[i])

        if not in_trade:
            # --- Long setup: trend up, pullback to EMA(pull), close back above
            if trend_up.iloc[i] and low_i <= float(ema_p.iloc[i]) and price > float(ema_p.iloc[i]):
                if not _vix_gate_ok(i, vix_series, vix_min, vix_max, tier_series, vix_regime_block):
                    continue
                if min_rv_annualized > 0.0:
                    rv_i = rv_ann.iloc[i]
                    if pd.isna(rv_i) or float(rv_i) < min_rv_annualized:
                        continue
                entry_signal[i] = "ENTRY_NOW"
                bias_arr[i] = "STRONG_BULL"
                regime_arr[i] = "TRENDING_BULL"
                stop_level[i] = price - initial_stop_mult * atr_i
                target_1[i] = price + 4.0 * atr_i
                target_2[i] = price + 6.0 * atr_i
                target_3[i] = price + 8.0 * atr_i
                in_trade = True
                direction = "long"
                current_trail = stop_level[i]
                extreme = price
            # --- Short setup (mirror)
            elif trend_dn.iloc[i] and high_i >= float(ema_p.iloc[i]) and price < float(ema_p.iloc[i]):
                if not _vix_gate_ok(i, vix_series, vix_min, vix_max, tier_series, vix_regime_block):
                    continue
                if min_rv_annualized > 0.0:
                    rv_i = rv_ann.iloc[i]
                    if pd.isna(rv_i) or float(rv_i) < min_rv_annualized:
                        continue
                entry_signal[i] = "ENTRY_NOW"
                bias_arr[i] = "STRONG_BEAR"
                regime_arr[i] = "TRENDING_BEAR"
                stop_level[i] = price + initial_stop_mult * atr_i
                target_1[i] = price - 4.0 * atr_i
                target_2[i] = price - 6.0 * atr_i
                target_3[i] = price - 8.0 * atr_i
                in_trade = True
                direction = "short"
                current_trail = stop_level[i]
                extreme = price
        else:
            # Trail update + exit (evaluated at bar close)
            if direction == "long":
                extreme = max(extreme, price)
                new_trail = extreme - atr_trail_mult * atr_i
                if new_trail > current_trail:
                    current_trail = new_trail
                if low_i <= current_trail or trend_dn.iloc[i]:
                    exit_signal[i] = "EXIT_NOW"
                    in_trade = False
            else:
                extreme = min(extreme, price)
                new_trail = extreme + atr_trail_mult * atr_i
                if new_trail < current_trail:
                    current_trail = new_trail
                if high_i >= current_trail or trend_up.iloc[i]:
                    exit_signal[i] = "EXIT_NOW"
                    in_trade = False

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["rv_20_ann_pct"] = rv_ann
    df["vix_level"] = vix_series if vix_series is not None else np.nan
    df["bias"] = bias_arr
    df["regime"] = regime_arr
    return df


# ---------------------------------------------------------------------------
# MRB — Guarded Counter-Trend Mean Reversion
# ---------------------------------------------------------------------------

def generate_guarded_meanrev_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    atr_mult: float = 1.0,
    stop_atr_mult: float = 0.8,
    max_hold_bars: int = 6,
    volume_mult: float = 1.2,
    dead_trend_pct: float = 0.02,
    vix_df: pd.DataFrame | None = None,
    vix_min: float = 0.0,
    vix_max: float = 999.0,
    vix_regime_block: tuple[str, ...] | None = ("Crisis", "HighVol"),
    vix_regime_lookback: int = 252,
) -> pd.DataFrame:
    """
    Fade short-term extremes ONLY in calm regimes.

    Context gates (all required): VIX gate ok (default blocks Crisis+HighVol),
        dead trend: |EMA(55)-EMA(200)|/EMA(200) < dead_trend_pct.
    Long entry: close < BB_lower(bb_period, bb_std) AND RSI < 25 AND
        close > open (reversal confirmation) AND volume > volume_mult*avg.
    Short entry: mirror (close > BB_upper, RSI > 75, close < open, volume spike).
    Exit: +atr_mult xATR target (target_1), -stop_atr_mult xATR stop,
        6-bar time-stop (exit_signal).

    NOTE (2026-08-17): stop_atr_mult defaults to 0.8 so the R:R at entry is
    1.0/0.8 = 1.25, clearing the Backtester's hardcoded rr >= 1.2 entry gate
    (backtester.py Bug 6). A 1:1 reversion (stop=1.0) would be rejected
    silently with 0 trades — mean-reversion must meet the entry R:R gate.
    Tighter stop also matches the design: don't hold a failing reversion
    for a full ATR.
    """
    df = df.copy()
    mid = df["close"].rolling(bb_period).mean()
    sd = df["close"].rolling(bb_period).std()
    bb_lo = mid - bb_std * sd
    bb_hi = mid + bb_std * sd

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)

    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)
    vol_avg = df["volume"].rolling(bb_period).mean() if "volume" in df.columns else None

    ema_f = df["close"].ewm(span=55, adjust=False).mean()
    ema_s = df["close"].ewm(span=200, adjust=False).mean()
    trend_gap_pct = ((ema_f - ema_s).abs() / ema_s.replace(0, np.nan)).fillna(1.0)

    vix_series, tier_series = _vix_series_and_tiers(
        df, vix_df, vix_min, vix_max, vix_regime_block, vix_regime_lookback
    )

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    bias_arr = np.full(n, "NEUTRAL", dtype=object)
    regime_arr = np.full(n, "RANGE_BOUND", dtype=object)

    in_trade = False
    entry_bar = -999

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(bb_lo.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if in_trade:
            # Time-stop: hard exit at max_hold_bars
            if (i - entry_bar) >= max_hold_bars:
                exit_signal[i] = "EXIT_NOW"
                in_trade = False
            continue

        # Context gates
        if not _vix_gate_ok(i, vix_series, vix_min, vix_max, tier_series, vix_regime_block):
            continue
        if trend_gap_pct.iloc[i] > dead_trend_pct:
            continue
        if vol_avg is not None and pd.notna(vol_avg.iloc[i]) and vol_avg.iloc[i] > 0:
            vol_ok = float(df["volume"].iloc[i]) > volume_mult * float(vol_avg.iloc[i])
        else:
            vol_ok = True

        # Long fade: extreme dip + oversold + reversal confirmation + volume
        if (
            price < float(bb_lo.iloc[i])
            and rsi.iloc[i] < 25
            and price > float(df["open"].iloc[i])
            and vol_ok
        ):
            entry_signal[i] = "ENTRY_NOW"
            bias_arr[i] = "STRONG_BULL"
            regime_arr[i] = "RANGE_BOUND"
            stop_level[i] = price - stop_atr_mult * atr_i
            target_1[i] = price + atr_mult * atr_i
            target_2[i] = price + 1.5 * atr_i
            target_3[i] = price + 2.0 * atr_i
            in_trade = True
            entry_bar = i
        # Short fade (mirror)
        elif (
            price > float(bb_hi.iloc[i])
            and rsi.iloc[i] > 75
            and price < float(df["open"].iloc[i])
            and vol_ok
        ):
            entry_signal[i] = "ENTRY_NOW"
            bias_arr[i] = "STRONG_BEAR"
            regime_arr[i] = "RANGE_BOUND"
            stop_level[i] = price + stop_atr_mult * atr_i
            target_1[i] = price - atr_mult * atr_i
            target_2[i] = price - 1.5 * atr_i
            target_3[i] = price - 2.0 * atr_i
            in_trade = True
            entry_bar = i

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["rv_20_ann_pct"] = np.nan
    df["vix_level"] = vix_series if vix_series is not None else np.nan
    df["bias"] = bias_arr
    df["regime"] = regime_arr
    return df


# ---------------------------------------------------------------------------
# ODF — Overnight Drift + Intraday Fade (direct session-return model)
# ---------------------------------------------------------------------------

def overnight_drift_returns(
    df: pd.DataFrame,
    vix_df: pd.DataFrame | None = None,
    vix_max_pctile: float = 65.0,
    vix_regime_lookback: int = 252,
) -> pd.DataFrame:
    """
    Daily session-return model for the overnight-drift edge. NOT Backtester —
    the Backtester cannot express close->next-open gap capture, so this is the
    honest way to evaluate a session strategy.

    For each session day:
      overnight_ret = (next_open / close) - 1     [the drift edge]
      Long if: prior day close > prior day open (daily momentum)
               AND VIX percentile <= vix_max_pctile
               AND close > EMA(200)               [long regime]
      Short if: prior day close < prior day open
               AND VIX percentile <= vix_max_pctile
               AND close < EMA(200)

    Returns a DataFrame with one row per session:
      date, close, next_open, overnight_ret, side (1/-1/0), pnl_ret,
      vix_level, vix_pctile
    pnl_ret = side * overnight_ret * 100 (percent of notional)
    """
    d = df.copy()
    d["date"] = d.index.normalize()
    daily = d.groupby("date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    daily["next_open"] = daily["open"].shift(-1)
    daily["overnight_ret"] = daily["next_open"] / daily["close"] - 1.0
    daily["mom"] = (daily["close"] > daily["open"]).astype(int) * 2 - 1  # +1 up, -1 down
    daily["ema200"] = daily["close"].ewm(span=200, adjust=False).mean()

    vix_pctile = None
    vix_level_s = None
    if vix_df is not None and not vix_df.empty:
        from backtest.trend_signals import _daily_date_index

        vix_daily = vix_df["close"].copy()
        vix_daily.index = _daily_date_index(vix_daily.index)
        daily_dates = _daily_date_index(daily.index)
        vix_level_s = vix_daily.reindex(daily_dates, method="ffill")
        vix_level_s.index = daily.index
        pct = vix_daily.rolling(vix_regime_lookback).rank(pct=True) * 100.0
        vix_pctile = pct.reindex(daily_dates, method="ffill")
        vix_pctile.index = daily.index

    long_ok = (daily["mom"] == 1) & (daily["close"] > daily["ema200"])
    short_ok = (daily["mom"] == -1) & (daily["close"] < daily["ema200"])
    if vix_pctile is not None:
        long_ok &= vix_pctile <= vix_max_pctile
        short_ok &= vix_pctile <= vix_max_pctile

    daily["side"] = np.where(long_ok, 1, np.where(short_ok, -1, 0))
    daily["pnl_ret"] = daily["side"] * daily["overnight_ret"] * 100.0
    daily["vix_level"] = vix_level_s
    daily["vix_pctile"] = vix_pctile
    daily = daily.dropna(subset=["overnight_ret"])
    return daily


def overnight_drift_metrics(
    daily: pd.DataFrame,
    capital: float = 50_000.0,
    commission_daily: float = 2.0,  # ~1 round trip MES @ $1 + slippage buffer
) -> dict:
    """Summary metrics for the ODF session model (one row per day)."""
    traded = daily[daily["side"] != 0]
    n = len(traded)
    if n < 10:
        return {
            "total_trades": n,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "hit_rate": 0.0,
            "n_pnl_samples": n,
        }
    rets = traded["pnl_ret"].to_numpy() / 100.0  # fractional returns on notional
    # Convert to $ on $50k notional, subtract commission per trade
    pnls = (rets * capital) - commission_daily
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")
    equity = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    max_dd_pct = float(((equity - peak) / peak).min()) if len(equity) else 0.0
    sharpe = float(pnls.mean() / pnls.std(ddof=1) * np.sqrt(252)) if n > 1 and pnls.std(ddof=1) > 0 else 0.0
    return {
        "total_trades": n,
        "win_rate": round(float((wins.size / n)), 4),
        "profit_factor": round(pf, 4),
        "total_pnl": round(float(pnls.sum()), 2),
        "max_drawdown_pct": round(abs(max_dd_pct), 4),
        "sharpe_ratio": round(sharpe, 4),
        "hit_rate": round(float((traded["overnight_ret"] * traded["side"] > 0).mean()), 4),
        "n_pnl_samples": n,
    }
