"""
Bollinger-Band + RSI mean-reversion signal generator for JARVIS TRADER.

Designed for MCL (crude oil 1h) — per-symbol decision memo (commit `c4a1ef1`)
flagged MCL as a mean-reversion candidate rather than trend-following. MCL is
currently blocklisted via `DO_NOT_TRADE_SYMBOLS` pending a validated edge; this
module is the first step in that re-derivation (roadmap P1.1).

Thesis
------
Crude oil tends to mean-revert after short-horizon dislocations:
    * Price closing OUTSIDE a Bollinger band (20-SMA ± 2σ) is an extreme event.
    * RSI(14) at <30 (oversold) or >70 (overbought) confirms momentum exhaustion.
    * Target: reversion to the 20-SMA midband.
    * Stop:   ATR-based buffer below/above the entry bar extreme.

Symmetric (LONG + SHORT) — unlike the trend-following SMA module which is
LONG-only by design.

Entry (LONG)
------------
    * close < lower_band   AND   rsi < rsi_long_threshold  (default 30)

Entry (SHORT)
-------------
    * close > upper_band   AND   rsi > rsi_short_threshold (default 70)

Exit
----
    * Price crosses midband (primary — "reversion complete")   → exit_signal=EXIT_NOW
    * Stop hit                                                 → handled by backtester
    * RSI returns to 50 (optional momentum-reset exit; not enforced here)

Output format
-------------
Matches the column contract consumed by the backtester:
    entry_signal  : "ENTRY_NOW" | "NO_TRADE"
    exit_signal   : "EXIT_NOW"  | "NO_EXIT"
    bias          : "STRONG_BULL" (long setup) | "STRONG_BEAR" (short setup) | "NEUTRAL"
    regime        : "MEAN_REVERTING" | "TRENDING" | "NEUTRAL"
    stop_level    : float — entry ± stop_atr_mult × ATR(14)
    target_1      : float — midband (primary reversion target)
    target_2      : float — midband ± 0.5 × band_width (extended)
    target_3      : float — opposite band (max reversion)
    bb_upper / bb_mid / bb_lower : raw Bollinger levels
    rsi_14 / atr_14              : momentum + volatility context
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Default MCL-targeted params — refined via backtest in P1.1
# MGC: rank1 baseline (2026-05-07) — pending gate v2 verdict
#      Same defaults as MCL; rank1 sweeps BB_period × BB_std × stop_atr_mult.
#      Production champion params will replace this block after rank1 PASS.
MEANREV_PARAMS: dict[str, dict] = {
    "MCL": {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_long": 30.0,
        "rsi_short": 70.0,
        "stop_atr_mult": 1.5,
    },
    "MGC": {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_long": 30.0,
        "rsi_short": 70.0,
        "stop_atr_mult": 1.5,
    },
}

_ATR_PERIOD = 14


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _build_regime_gate(
    mode: str,
    df: pd.DataFrame,
    bb_upper: pd.Series,
    bb_lower: pd.Series,
    adx_threshold: float,
    bbwidth_pct: float,
    bbwidth_lookback: int,
    keltner_atr_mult: float,
    rv_min: float = 0.0,
    rv_max: float = 999.0,
    rv_lookback: int = 20,
    sentiment_db_path: str = "",
    sentiment_block_bearish: bool = True,
) -> pd.Series:
    """Return a boolean Series — True = entry allowed, False = suppressed.

    The gate ANDs into the per-direction entry conditions in the caller.
    Each mode targets a specific trend-regime signature that kills naive
    mean-reversion setups:
        adx      : suppress when ADX >= adx_threshold (trending)
        bbwidth  : suppress when bb_width rolling percentile > bbwidth_pct
                    (volatility-expansion phase = trend burst)
        keltner  : suppress when price is outside BOTH Bollinger AND Keltner
                    (extreme dislocation confirmed by ATR, not just SD)
        rv_band  : allow entry only when realized volatility (close-to-close,
                    annualized %) is within [rv_min, rv_max].  Hypothesis C
                    for MCL re-validation — filters out both ultra-low vol
                    (thin, directionless) and ultra-high vol (trending shock)
                    environments where mean-reversion has no edge.
    Unknown modes fall back to all-True (effectively no gate).
    """
    from backtest.indicators import compute_adx, keltner_channels

    close = df["close"]
    high = df["high"]
    low = df["low"]
    all_true = pd.Series(True, index=df.index)

    if mode == "adx":
        adx_df = compute_adx(df, period=14)
        adx = adx_df["adx"]
        # Allow entry when adx < threshold (non-trending / ranging regime).
        return (adx < adx_threshold).fillna(False)

    if mode == "bbwidth":
        bb_width = (bb_upper - bb_lower).abs()
        # Rolling percentile rank of current bb_width vs the prior `lookback`
        # bars. rank normalized to [0, 100]. Allow entry when rank <= pct
        # (current vol is in the calm-to-normal range, not top-pct%).
        rank = bb_width.rolling(bbwidth_lookback, min_periods=max(5, bbwidth_lookback // 4)).apply(
            lambda w: 100.0 * (w.iloc[-1] <= w).sum() / len(w) if len(w) > 0 else 50.0,
            raw=False,
        )
        # Above definition gives the "rank of current value among window"
        # (higher = current is LOW compared to window). Flip to standard
        # "percentile rank" where 100 = current is highest.
        percentile = 100.0 - rank
        return (percentile <= bbwidth_pct).fillna(False)

    if mode == "keltner":
        kc_upper, _kc_basis, kc_lower = keltner_channels(
            close,
            high,
            low,
            sma_len=20,
            atr_factor=keltner_atr_mult,
        )
        outside_bb_up = close > bb_upper
        outside_bb_dn = close < bb_lower
        outside_kc_up = close > kc_upper
        outside_kc_dn = close < kc_lower
        # Suppress when price breaches BOTH channel systems in the same
        # direction — that's a confirmed trend extension, not a reversion
        # setup. Allow entry when price breaches Bollinger but NOT Keltner.
        trend_ext = (outside_bb_up & outside_kc_up) | (outside_bb_dn & outside_kc_dn)
        return (~trend_ext).fillna(False)

    if mode == "rv_band":
        close = df["close"]
        # Resample to daily to compute conventional daily annualized RV.
        # Intraday (1h) close-to-close std × sqrt(252) understates because bars
        # are not daily — resample first so the RV values match the 20-50%
        # annualized convention used in the gate v2 parameter grid.
        try:
            daily_close = close.resample("1D").last().dropna()
        except TypeError:
            # Non-DatetimeIndex fallback: use raw 1h returns (rare case)
            daily_close = None

        if daily_close is not None and len(daily_close) >= max(5, rv_lookback // 2):
            daily_log_ret = np.log(daily_close / daily_close.shift(1))
            daily_rv = (
                daily_log_ret.rolling(rv_lookback, min_periods=max(5, rv_lookback // 2)).std()
                * np.sqrt(252)
                * 100.0
            )
            # Forward-fill daily RV back to the original (intraday) index.
            rv = daily_rv.reindex(close.index, method="ffill")
        else:
            daily_log_ret = np.log(close / close.shift(1))
            rv = (
                daily_log_ret.rolling(
                    rv_lookback * 23, min_periods=max(10, rv_lookback * 23 // 2)
                ).std()
                * np.sqrt(252 * 23)
                * 100.0
            )

        return ((rv >= rv_min) & (rv <= rv_max)).fillna(False)

    if mode == "sentiment_overlay":
        if not sentiment_db_path:
            return all_true
        try:
            import sqlite3

            conn = sqlite3.connect(sentiment_db_path)
            bias_df = pd.read_sql_query(
                "SELECT date, directional_bias FROM corey_session_bias ORDER BY date",
                conn,
                parse_dates=["date"],
            )
            conn.close()
        except Exception as exc:
            import warnings

            warnings.warn(
                f"sentiment_overlay DB read failed (path={sentiment_db_path!r}): {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return all_true
        if bias_df.empty:
            return all_true
        bias_df = bias_df.set_index("date")
        if not isinstance(close.index, pd.DatetimeIndex):
            return all_true
        daily_bias = bias_df["directional_bias"].resample("1D").last()
        if sentiment_block_bearish:
            daily_allowed = daily_bias != "bearish"
        else:
            daily_allowed = pd.Series(True, index=daily_bias.index)
        allowed = daily_allowed.reindex(close.index, method="ffill").fillna(True)
        return allowed.astype(bool)

    # Unknown mode — fail safe to all-True (no gating).
    return all_true


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI with exponential smoothing (alpha = 1/period)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # Wilder smoothing via EWMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # "No losses in window" → RSI = 100 (definitional).
    # Warmup bars (avg_loss NaN) must stay NaN so downstream warm-guards skip them.
    no_losses = avg_loss == 0.0
    rsi = rsi.mask(no_losses, 100.0)
    return rsi


def generate_bollinger_rsi_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_long: float = 30.0,
    rsi_short: float = 70.0,
    stop_atr_mult: float = 1.5,
    signal_direction: str = "both",
    regime_filter_mode: str = "none",
    regime_filter_adx_threshold: float = 20.0,
    regime_filter_bbwidth_pct: float = 40.0,
    regime_filter_bbwidth_lookback: int = 100,
    regime_filter_keltner_atr_mult: float = 1.5,
    regime_filter_min_rv: float = 20.0,
    regime_filter_max_rv: float = 50.0,
    regime_filter_rv_lookback: int = 20,
    sentiment_db_path: str = "",
    sentiment_block_bearish: bool = True,
    htf_rsi_period: int = 0,
    htf_rsi_upper: float = 60.0,
    htf_rsi_lower: float = 40.0,
) -> pd.DataFrame:
    """Generate Bollinger + RSI mean-reversion signals.

    Args:
        df: OHLCV DataFrame with columns open, high, low, close, volume.
        bb_period: Bollinger lookback window (default 20).
        bb_std: Standard-deviation multiplier for bands (default 2.0).
        rsi_period: Wilder RSI period (default 14).
        rsi_long: Oversold threshold for LONG entries (default 30.0).
        rsi_short: Overbought threshold for SHORT entries (default 70.0).
        stop_atr_mult: Stop distance in ATR(14) multiples (default 1.5).
        regime_filter_mode: "none" | "adx" | "bbwidth" | "keltner".
            - "none": default, no additional filter.
            - "adx":  suppress entries when ADX >= adx_threshold (trend day).
            - "bbwidth": suppress entries when bb_width rolling percentile
                rank > regime_filter_bbwidth_pct (top-pct% vol = trend burst).
            - "keltner": suppress entries when price is outside BOTH the
                Bollinger AND the Keltner channel (trend extension confirmed
                by ATR, not just standard deviation — filters out one-way
                momentum moves that look like reversion setups).
        regime_filter_adx_threshold: ADX value above which entries are
            suppressed in "adx" mode (default 20.0).
        regime_filter_bbwidth_pct: percentile threshold in "bbwidth" mode
            (default 40 = suppress top 60% vol bars).
        regime_filter_bbwidth_lookback: rolling window for bb_width percentile
            rank (default 100 bars).
        regime_filter_keltner_atr_mult: ATR multiplier for Keltner channel
            used in "keltner" mode (default 1.5, matching indicator default).
        regime_filter_min_rv: lower annualized RV bound (%) for "rv_band" mode
            (default 20.0 — below this, market is too thin for mean-reversion).
        regime_filter_max_rv: upper annualized RV bound (%) for "rv_band" mode
            (default 50.0 — above this, market is trending/shocked, not ranging).
        regime_filter_rv_lookback: rolling window (bars) for RV computation in
            "rv_band" mode (default 20 = ~1 month of 1h bars on CME futures).
        htf_rsi_period: Wilder RSI period computed on daily bars for HTF
            conditioning. 0 = disabled (default, backward-compatible). When
            > 0, the 1h close is resampled to daily, RSI is computed on daily
            bars, then forward-filled back to the 1h index. This gates entries
            by daily RSI to avoid buying intraday dips against a daily
            overbought reading (LONG) or shorting bounces into a daily oversold
            reading (SHORT). Hypothesis F for MCL — the six prior hypotheses
            (A-E) show mean-rev edge exists intraday but is destroyed by
            multi-day trending regimes; HTF RSI filtering targets exactly that.
        htf_rsi_upper: LONG entries are suppressed when the forward-filled
            daily RSI >= this threshold (default 60.0 — avoids buying 1h dips
            when the daily chart is already overbought). Only active when
            htf_rsi_period > 0.
        htf_rsi_lower: SHORT entries are suppressed when the forward-filled
            daily RSI <= this threshold (default 40.0 — avoids shorting 1h
            bounces when the daily chart is already oversold). Only active when
            htf_rsi_period > 0.

    Returns:
        Copy of df with added columns documented in the module docstring.
    """
    df = df.copy()

    # ── Core indicators ──────────────────────────────────────────────────
    sma = df["close"].rolling(bb_period).mean()
    sd = df["close"].rolling(bb_period).std(ddof=0)
    bb_upper = sma + bb_std * sd
    bb_lower = sma - bb_std * sd

    rsi = _wilder_rsi(df["close"], period=rsi_period)
    atr = _wilder_atr(df["high"], df["low"], df["close"], period=_ATR_PERIOD)

    # ── Entry logic ──────────────────────────────────────────────────────
    close = df["close"]

    long_cond = (close < bb_lower) & (rsi < rsi_long)
    short_cond = (close > bb_upper) & (rsi > rsi_short)
    # Require indicators to be warmed up (no NaN in any input)
    warm = sma.notna() & rsi.notna() & atr.notna()
    long_cond = long_cond & warm
    short_cond = short_cond & warm

    # Direction precedence: if somehow both fire (edge case, extreme vol), skip.
    conflict = long_cond & short_cond
    long_cond = long_cond & ~conflict
    short_cond = short_cond & ~conflict

    # ── Direction filter ─────────────────────────────────────────────────
    # "both" (default) keeps symmetric LONG+SHORT behavior.
    # "short_only" zeroes longs — isolates fade-highs edge when the underlying
    #   has a persistent uptrend (e.g. MES bull regime from rank11 PASS).
    # "long_only" zeroes shorts — for persistent-downtrend underlyings.
    if signal_direction == "short_only":
        long_cond = long_cond & False
    elif signal_direction == "long_only":
        short_cond = short_cond & False

    # ── Regime filter (optional) ─────────────────────────────────────────
    # Default "none" preserves original behavior. Non-default modes AND an
    # additional gate into the entry condition to suppress trend-day chop
    # that killed the first-pass MCL result (PF 0.855, 55% stop-hit rate).
    if regime_filter_mode != "none":
        regime_gate = _build_regime_gate(
            mode=regime_filter_mode,
            df=df,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
            adx_threshold=regime_filter_adx_threshold,
            bbwidth_pct=regime_filter_bbwidth_pct,
            bbwidth_lookback=regime_filter_bbwidth_lookback,
            keltner_atr_mult=regime_filter_keltner_atr_mult,
            rv_min=regime_filter_min_rv,
            rv_max=regime_filter_max_rv,
            rv_lookback=regime_filter_rv_lookback,
            sentiment_db_path=sentiment_db_path,
            sentiment_block_bearish=sentiment_block_bearish,
        )
        long_cond = long_cond & regime_gate
        short_cond = short_cond & regime_gate

    # ── HTF RSI filter (optional) ────────────────────────────────────────
    # Daily RSI conditioning: resample 1h close → daily, compute Wilder RSI,
    # forward-fill to 1h index, then AND into directional entry conditions.
    # htf_rsi_period=0 skips entirely (default, backward-compatible).
    if htf_rsi_period > 0:
        try:
            daily_close = df["close"].resample("1D").last().dropna()
            htf_rsi_daily = _wilder_rsi(daily_close, period=htf_rsi_period)
            # Forward-fill daily values to every 1h bar (each 1h bar inherits
            # the most recent daily close's RSI value).
            htf_rsi_1h = htf_rsi_daily.reindex(df.index, method="ffill")
        except (TypeError, AttributeError):
            # Non-DatetimeIndex or other resampling failure — fail safe to
            # neutral (50.0) which passes all threshold comparisons.
            htf_rsi_1h = pd.Series(50.0, index=df.index)

        htf_warm = htf_rsi_1h.notna()
        # LONG: only when daily is not overbought (RSI < htf_rsi_upper).
        long_cond = long_cond & (htf_rsi_1h < htf_rsi_upper).fillna(False) & htf_warm
        # SHORT: only when daily is not oversold (RSI > htf_rsi_lower).
        short_cond = short_cond & (htf_rsi_1h > htf_rsi_lower).fillna(False) & htf_warm

    # ── Exit logic: midband cross ─────────────────────────────────────────
    # Midband cross in either direction — simple reversion-complete signal.
    # The backtester handles per-trade direction-aware exit mechanics; this
    # column flags "a reversion back to fair value has occurred this bar."
    prev_close = close.shift(1)
    prev_sma = sma.shift(1)
    crossed_up_through_mid = (prev_close < prev_sma) & (close >= sma)
    crossed_down_through_mid = (prev_close > prev_sma) & (close <= sma)
    exit_cond = (crossed_up_through_mid | crossed_down_through_mid) & warm

    # ── Target ladder ────────────────────────────────────────────────────
    # LONG target_1 = midband (primary reversion); target_2/3 extend toward
    # and through the upper band. SHORT is mirrored.
    band_width = (bb_upper - bb_lower) / 2.0  # half-width = 1σ
    # Avoid invalid targets on warmup bars
    target_mid = sma

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    long_idx = np.flatnonzero(long_cond.values)
    for i in long_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BULL"
        stop_level[i] = price - stop_atr_mult * atr_i
        target_1[i] = float(target_mid.iloc[i])
        target_2[i] = float(target_mid.iloc[i]) + 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_upper.iloc[i])

    short_idx = np.flatnonzero(short_cond.values)
    for i in short_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BEAR"
        stop_level[i] = price + stop_atr_mult * atr_i
        target_1[i] = float(target_mid.iloc[i])
        target_2[i] = float(target_mid.iloc[i]) - 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_lower.iloc[i])

    exit_idx = np.flatnonzero(exit_cond.values)
    for i in exit_idx:
        exit_signal[i] = "EXIT_NOW"

    # ── Regime label ─────────────────────────────────────────────────────
    # A crude regime hint for downstream consumers. The full regime router
    # lives in regime_classifier.py (P1.3) and should replace this once built.
    regime = np.where(warm, "MEAN_REVERTING", "NEUTRAL")

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["bias"] = bias
    df["regime"] = regime
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["bb_upper"] = bb_upper
    df["bb_mid"] = sma
    df["bb_lower"] = bb_lower
    df["rsi_14"] = rsi
    df["atr_14"] = atr

    return df


def get_meanrev_params(symbol: str) -> dict | None:
    """Return validated mean-reversion params for symbol, or None."""
    return MEANREV_PARAMS.get(symbol.upper())
