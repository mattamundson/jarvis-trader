"""
SMA trend-following signal generator for JARVIS TRADER.

Validated on MES 1h via walk-forward optimization — rank11 champion (2026-05-06):
    SMA(60, 200) + 2.0×ATR trailing stop
    fixed_params PF: fast=60→2.156, fast=55→1.722, fast=50→1.351
    gate v2 ALT PASS: dsr=1.0, wfo=STRONG, mc_dd=0.81%, fixed_params_min_pf=1.351

Entry : fast SMA crosses above slow SMA (Golden Cross) — LONG only.
Exit  : fast SMA crosses below slow SMA  OR  ATR trailing stop hit.
Stop  : initial stop = entry - trail_mult × ATR(14) at entry bar.
        (Static at entry; full trailing stop requires Backtester enhancement.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Walk-forward champion parameters
# MES: trend_rv_filter_rank2 (2026-06-04) -- verdict INSUFFICIENT_SAMPLE (16 OOS < 30 floor)
#      Gate blocks trades at runtime; re-authorize by collecting 30+ OOS trades OR flip
#      GATE_V2_ENFORCE_SAMPLE_ADEQUACY=False in engine/.env (Amo-gated decision).
#      RV filter: MES_MIN_RV_ANNUALIZED=9.0 env var (see engine/.env and signals.py)
# MNQ: rank1 baseline (2026-05-06) -- inherited from MES champion; pending rank1 verdict
SMA_TREND_PARAMS: dict[str, dict] = {
    "MES": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
    # MNQ baseline: MES champion params as starting point.
    # point_value=$2 (vs MES $5), tick_size=0.25, commission=$0.62/contract.
    # ATR in dollar terms differs from MES — trail_mult grid [1.8, 2.0, 2.2]
    # in run_mnq_trend_rank1.py determines production value after rank1 verdict.
    "MNQ": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
    # MGC: rank4 champion (2026-05-06) — gate v2 ALT PASS
    # 8-combo grid fast=[40,50]×slow=[80,120]×atr=[1.5,2.0]; all combos PF>1.35
    # dsr=1.0, wfo=STRONG, mc_dd=1.24%, cost=catastrophic. ALT ($50K+).
    "MGC": {"fast": 50, "slow": 120, "atr_trail_mult": 2.0},
}

_ATR_PERIOD = 14
_T1_MULT = 3.0  # static first target: 3× ATR from entry
_T2_MULT = 5.0
_T3_MULT = 7.0

# Realized-vol filter (Phase B+ addition, 2026-04-21):
# Analysis of 36 live champion trades shows SMA trend edge concentrates in
# high-vol regimes. Below RV-20 annualized ≈ 9%, trades net-lose. See
# commit cf76eb3 Tier A validation + ~/.claude/plans/ for threshold sweep.
# Default: 0.0 (no filter, backward-compatible). Recommended: 9.0 (safer,
# keeps 22/36 trades at PF 2.54) or 13.0 (max net, 13 trades at PF 5.51).
# Production gate to enable only after 60+ trades confirm the improvement.
_RV_WINDOW = 20
_RV_ANNUAL_FACTOR = 252 * 24  # 24 1h bars per trading day, 252 trading days/yr


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


<<<<<<< HEAD
=======
def _daily_date_index(index) -> pd.DatetimeIndex:
    """Return a tz-naive, midnight-normalized ``DatetimeIndex``.

    The daily VIX series (naive exchange dates) and the intraday bar index must
    share one tz convention before any comparison or ffill ``reindex``.

    pandas >= 3.0 raises ``TypeError: Cannot compare dtypes datetime64[us, UTC]
    and datetime64[s]`` on a mixed-tz comparison instead of silently comparing
    unequal. Caches whose timestamps carry a UTC offset — e.g.
    ``MES_2019-05-05_2026-08-26_1h.csv`` — therefore aborted *every* VIX-gated
    walk-forward window, so the whole VIX-gated research family produced no
    OOS results and no verdict.

    Tz-aware indexes are converted to UTC before the tz is dropped, so the
    calendar date stays the UTC date. That is identical to the historical
    behaviour on caches whose timestamps were stored without an offset, and it
    introduces no look-ahead: the caller still ffills a daily close forward onto
    later bars only.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
def generate_sma_trend_signals(
    df: pd.DataFrame,
    fast: int = 60,
    slow: int = 200,
    atr_trail_mult: float = 2.0,
    min_rv_annualized: float = 0.0,
    rv_annual_factor: int | None = None,
    vix_df: pd.DataFrame | None = None,
    vix_min: float = 0.0,
    vix_max: float = 999.0,
    vix_regime_block: tuple[str, ...] | None = None,
    vix_regime_lookback: int = 252,
) -> pd.DataFrame:
    """
    Generate SMA trend-following signals compatible with the JARVIS Backtester.

    Args:
        min_rv_annualized: If > 0, suppress ENTRY_NOW when 20-bar realized
            vol (annualized %) at entry bar < threshold. Empirically the
            SMA trend edge concentrates at RV ≥ 9% (36-trade sample).
            0.0 (default) = filter disabled.
        rv_annual_factor: Bars-per-year for RV annualization. Default None uses
            _RV_ANNUAL_FACTOR (252*24 for 1h bars). Pass 252 for daily bars.
        vix_df: Optional DataFrame with a "close" column indexed by date
            (daily VIX data). When provided, ENTRY_NOW is suppressed unless
            the current day's VIX is in [vix_min, vix_max].
            No-op when None (default, backward-compatible).
        vix_min: Lower bound for VIX filter (inclusive). 0.0 = no lower bound.
        vix_max: Upper bound for VIX filter (inclusive). 999.0 = no upper bound.
        vix_regime_block: Optional tuple of VIX percentile-tier names
            ("Crisis"|"HighVol"|"MidVol"|"LowVol") in which to suppress
            ENTRY_NOW. Adaptive alternative to the absolute vix_min/vix_max
            range — tiers are computed from the trailing VIX percentile
            (see backtest.vix_percentile_regime). Requires vix_df. No-op when
            None (default, backward-compatible).
        vix_regime_lookback: Trailing window (in daily VIX bars) for the
            percentile rank. Default 252 (~1 year).

    Returns df with columns:
        entry_signal  : "ENTRY_NOW" | "NO_TRADE"
        stop_level    : entry − trail_mult × ATR  (set at signal bar)
        target_1/2/3  : entry + N × ATR
        bias          : "STRONG_BULL" | "STRONG_BEAR" | "NEUTRAL"
        regime        : "TRENDING_BULL" | "RANGE_BOUND"
        atr           : ATR(14) series
        rv_20_ann_pct : 20-bar annualized realized volatility (percent)
        vix_level     : VIX at each bar (NaN when vix_df not provided)
    """
    df = df.copy()
    _rv_factor = rv_annual_factor if rv_annual_factor is not None else _RV_ANNUAL_FACTOR

    # Precompute per-bar VIX levels (daily, forward-filled to 1h bars)
    _vix_series: pd.Series | None = None
    _vix_tier_series: pd.Series | None = None
    if vix_df is not None and not vix_df.empty:
        vix_daily = vix_df["close"].copy()
<<<<<<< HEAD
        vix_daily.index = pd.to_datetime(vix_daily.index).normalize()
        bar_dates = df.index.normalize()
=======
        # Align tz conventions before the ffill reindex (pandas >= 3.0 raises on
        # mixed-tz comparisons — see _daily_date_index).
        vix_daily.index = _daily_date_index(vix_daily.index)
        bar_dates = _daily_date_index(df.index)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
        _vix_series = vix_daily.reindex(bar_dates, method="ffill")
        _vix_series.index = df.index

        # Percentile-tier gate: classify on the DAILY series (point-in-time
        # trailing percentile) then forward-fill tiers onto the bar index.
        if vix_regime_block:
            from backtest.vix_percentile_regime import classify_vix_regime

            # pandas >= 3.0 coerces the str-Enum tier elements to plain str inside the
            # Series, so `t` may be 'MidVol' (str) rather than VixTier.MID_VOL. The
            # coerced str already equals the enum's .value, so fall back to the element
            # itself when .value is absent.
            tiers_daily = classify_vix_regime(vix_daily, lookback=vix_regime_lookback).map(
                lambda t: getattr(t, "value", t)
            )
            _vix_tier_series = tiers_daily.reindex(bar_dates, method="ffill")
            _vix_tier_series.index = df.index

    sma_f = df["close"].rolling(fast).mean()
    sma_s = df["close"].rolling(slow).mean()
    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)
    # Realized vol: stddev of log returns over _RV_WINDOW bars, annualized as percent
    log_ret = np.log(df["close"] / df["close"].shift(1))
    rv_ann = log_ret.rolling(_RV_WINDOW).std() * np.sqrt(_rv_factor) * 100.0

    # Force numpy bool dtype: NaN comparisons → False, shift with fill_value avoids
    # the object-dtype conversion that makes Python's ~bool give wrong results (Python 3.12+).
    above = (sma_f > sma_s).fillna(False).astype(bool)
    prev_above = above.shift(1, fill_value=False)
    # Guard: require previous bar to also have valid slow SMA.  Without this,
    # the first valid slow-SMA bar (bar=slow) always triggers a spurious cross
    # because prev bar had NaN→fillna(False).  With wide trail stops this
    # synthetic entry never exits, producing 0 completed trades.
    prev_sma_s_valid = sma_s.shift(1).notna()
    cross_up = above & ~prev_above & prev_sma_s_valid  # golden cross
    cross_dn = ~above & prev_above & prev_sma_s_valid  # death cross

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    trailing_stop = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    current_trail = np.nan
    in_trade = False

    for i in range(n):
        if pd.isna(sma_s.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        low_i = float(df["low"].iloc[i])
        atr_i = float(atr.iloc[i])

        if cross_up.iloc[i]:
            # Realized-vol gate: skip entry if vol is below threshold.
            if min_rv_annualized > 0.0:
                rv_i = rv_ann.iloc[i]
                if pd.isna(rv_i) or float(rv_i) < min_rv_annualized:
                    continue  # leave entry_signal as NO_TRADE

            # VIX range gate: skip entry when VIX is outside [vix_min, vix_max].
            if _vix_series is not None:
                vix_i = _vix_series.iloc[i]
                if pd.isna(vix_i) or not (vix_min <= float(vix_i) <= vix_max):
                    continue  # leave entry_signal as NO_TRADE

            # VIX percentile-tier gate: skip entry in a blocked volatility tier.
            if _vix_tier_series is not None:
                tier_i = _vix_tier_series.iloc[i]
                if pd.isna(tier_i) or tier_i in vix_regime_block:
                    continue  # leave entry_signal as NO_TRADE

            entry_signal[i] = "ENTRY_NOW"
            initial_stop = price - atr_trail_mult * atr_i
            stop_level[i] = initial_stop
            current_trail = initial_stop
            in_trade = True

            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + _T3_MULT * atr_i

        elif in_trade:
            # Update trail: only moves UP
            new_trail = price - atr_trail_mult * atr_i
            if new_trail > current_trail:
                current_trail = new_trail

            trailing_stop[i] = current_trail

            # Exit check
            if low_i <= current_trail or cross_dn.iloc[i]:
                exit_signal[i] = "EXIT_NOW"
                in_trade = False
                current_trail = np.nan

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["trailing_stop"] = trailing_stop
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["rv_20_ann_pct"] = rv_ann
    df["vix_level"] = _vix_series if _vix_series is not None else np.nan

    df["bias"] = "NEUTRAL"
    df.loc[above, "bias"] = "STRONG_BULL"
    df.loc[~above & sma_s.notna(), "bias"] = "STRONG_BEAR"

    df["regime"] = "RANGE_BOUND"
    df.loc[above, "regime"] = "TRENDING_BULL"

    return df


def get_sma_trend_params(symbol: str) -> dict:
    """Return validated SMA trend params for symbol, or None if not configured."""
    return SMA_TREND_PARAMS.get(symbol.upper())
