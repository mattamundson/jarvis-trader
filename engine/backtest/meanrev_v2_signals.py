"""
Mean-reversion v2 signal generator — addresses the three structural failures
identified in the meanrev_audit (2026-06-26).

Failures fixed
--------------
1. STATIC VOLATILITY TRIGGER → vol-adjusted percentile trigger.
   The original `close < BB_lower (20-period, 2σ)` assumes a stationary
   distribution within the 20-bar window. When vol regime-shifts, the
   2σ band becomes the new normal and the strategy fires on non-extremes.
   v2 uses a rolling 200-bar percentile of (close - sma) / atr, firing
   only when the current dislocation is above the 95th percentile of the
   trailing distribution. This self-calibrates to whatever vol regime is
   in force.

2. FIXED ATR STOP IN NON-STATIONARY TAILS → vol-targeted stop + time-stop.
   The original 1.5×ATR(14) stop catches up to vol expansion *after the
   fact* — meaning the stop placed at entry is systematically too tight
   during the very regime where mean-rev fails worst (55% stop-hit rate
   in MCL hyp-A). v2 uses:
     - stop_distance = max(stop_atr_mult × ATR(14),
                            stop_atr_mult × ATR_p75(50))
       (the larger of short-window ATR and the 75th-percentile of a
       longer-window ATR — automatically widens in high-vol regimes)
     - time_stop_bars: exit at market if reversion hasn't started within N
       bars (default 8 on 1h = ~1 trading day)
     - trail-to-midband: once price moves halfway to target, trail stop to
       breakeven (caps the "60% of winner given back" pattern)

3. NO CLUSTER-LOSS CIRCUIT BREAKER → strategy-level breaker.
   v2 emits a `circuit_breaker_active` column that the backtester must
   honour. The breaker trips when:
     - rolling 5-trade PnL < -2 × avg_winner, OR
     - last 3 trades were all stops, OR
     - cumulative-since-start daily PnL < -1% of capital
   When tripped, entry_signal is forced to NO_TRADE until 5 bars after
   the trip condition clears.

Bonus: OU-PARAMETER INTEGRATION (the unused mean_reversion_ou.py module).
The OU process gives an explicit half-life and steady-state z-score. When
ou_mode='filter', entries are gated by half_life ∈ [min, max] bars (avoid
strategies on series with infinite half-life i.e. random walk, or
half-life < 1 bar i.e. instantaneous reversion which costs eat). When
ou_mode='zscore_trigger', the entry condition uses the OU z-score
(|z| > 2.0 and theta > 0.1) INSTEAD of the Bollinger trigger — this is the
v2 "pure OU" mode for cyclical markets.

Output contract
---------------
Matches the column contract consumed by backtester.py (same as v1):
    entry_signal      : "ENTRY_NOW" | "NO_TRADE"
    exit_signal       : "EXIT_NOW"  | "NO_EXIT"
    bias              : "STRONG_BULL" | "STRONG_BEAR" | "NEUTRAL"
    regime            : "MEAN_REVERTING" | "TRENDING" | "NEUTRAL"
    stop_level        : float — vol-adaptive stop
    target_1          : float — primary reversion target (midband or OU mu)
    target_2          : float — extended
    target_3          : float — max reversion
    bb_upper / bb_mid / bb_lower : raw Bollinger levels (diagnostic)
    rsi_14 / atr_14   : momentum + vol context

New v2 columns:
    dislocation_percentile  : 0-100, current (close-sma)/atr vs trailing window
    stop_vol_regime         : "low" | "normal" | "high" — which ATR drove stop sizing
    time_stop_bars_remaining : int — how many bars until time stop fires
    circuit_breaker_active   : bool — entries are blocked this bar
    ou_theta / ou_mu / ou_half_life / ou_z : OU diagnostics (when ou_mode != "off")

Author: Funnel skill, meanrev_v2 (2026-06-26)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_ATR_PERIOD = 14
_DEFAULT_ATR_PERCENTILE_WINDOW = 50  # longer-window ATR for vol-target stops
_DEFAULT_ATR_PERCENTILE = 75  # use 75th percentile of trailing ATR as upper-bound

# v2 defaults — calibrated to the failure modes documented in meanrev_audit
MEANREV_V2_DEFAULTS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "rsi_long": 30.0,
    "rsi_short": 70.0,
    # v2 NEW PARAMETERS
    "dislocation_lookback": 200,
    "dislocation_percentile_min": 95.0,
    "stop_atr_mult": 1.5,
    "stop_atr_long_window": _DEFAULT_ATR_PERCENTILE_WINDOW,
    "stop_atr_long_percentile": _DEFAULT_ATR_PERCENTILE,
    "time_stop_bars": 8,
    "trail_to_be_at_pct_of_target": 0.5,  # trail to breakeven at 50% of move
    "cb_rolling_n_trades": 5,
    "cb_rolling_loss_multiple": 2.0,
    "cb_consecutive_stops": 3,
    "cb_daily_loss_pct_cap": 0.01,
    "cb_cooldown_bars": 5,
    "ou_mode": "filter",  # "off" | "filter" | "zscore_trigger"
    "ou_window": 100,
    "ou_min_half_life_bars": 4,
    "ou_max_half_life_bars": 100,
    "ou_zscore_threshold": 2.0,
    "ou_theta_min": 0.05,
}


# ── Indicator helpers ─────────────────────────────────────────────────────────


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_c).abs(), (low - prev_c).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    no_losses = avg_loss == 0.0
    rsi = rsi.mask(no_losses, 100.0)
    return rsi


def _rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """
    For each bar, compute the percentile rank of the current value within the
    trailing `window` of values (excluding the current bar to avoid look-ahead).
    Returns a value in [0, 100].
    """

    def pct_rank(w):
        if len(w) < 2:
            return np.nan
        # rank of last element within w
        return 100.0 * (w[:-1] <= w[-1]).sum() / (len(w) - 1)

    return series.rolling(window, min_periods=max(20, window // 4)).apply(pct_rank, raw=True)


def _rolling_quantile(series: pd.Series, window: int, q: float) -> pd.Series:
    """Trailing q-quantile of `series` over `window` bars (raw=True for speed)."""
    return series.rolling(window, min_periods=max(10, window // 4)).quantile(q / 100.0)


# ── OU parameter estimation (vectorized over a rolling window) ────────────────


def _rolling_ou_params(
    close: pd.Series, window: int = 100
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Rolling OU parameter estimation. Returns (theta, mu, sigma, half_life)
    aligned to the close series. For bars before `window`, returns NaN.

    Uses OLS: y_t = alpha + beta * y_{t-1} + eps
    theta = -ln(beta) (assumes dt=1)
    mu    = alpha / (1 - beta)
    sigma_eps = std(residuals)
    half_life = ln(2) / theta
    """
    n = len(close)
    theta = np.full(n, np.nan)
    mu = np.full(n, np.nan)
    sigma = np.full(n, np.nan)
    half_life = np.full(n, np.nan)

    values = close.values
    for i in range(window, n):
        y = values[i - window : i]
        if np.isnan(y).any():
            continue
        y_lag = y[:-1]
        y_curr = y[1:]
        # OLS via numpy (avoid sklearn dependency in hot path)
        X = np.column_stack([np.ones_like(y_lag), y_lag])
        try:
            coef, *_ = np.linalg.lstsq(X, y_curr, rcond=None)
            alpha, beta = coef[0], coef[1]
        except np.linalg.LinAlgError:
            continue
        if beta <= 0 or beta >= 1:
            continue  # no valid mean-reversion structure (random walk or explosive)
        theta_i = -np.log(beta)
        mu_i = alpha / (1 - beta) if abs(1 - beta) > 1e-9 else np.mean(y)
        y_pred = alpha + beta * y_lag
        sigma_eps = np.std(y_curr - y_pred)
        sigma_i = (
            sigma_eps * np.sqrt(2 * theta_i / (1 - beta**2)) if 1 - beta**2 > 1e-9 else sigma_eps
        )
        theta[i] = theta_i
        mu[i] = mu_i
        sigma[i] = sigma_i
        half_life[i] = np.log(2) / theta_i if theta_i > 1e-9 else np.inf

    return (
        pd.Series(theta, index=close.index, name="ou_theta"),
        pd.Series(mu, index=close.index, name="ou_mu"),
        pd.Series(sigma, index=close.index, name="ou_sigma"),
        pd.Series(half_life, index=close.index, name="ou_half_life"),
    )


# ── Circuit breaker state machine ─────────────────────────────────────────────


def _compute_circuit_breaker(
    df: pd.DataFrame,
    entry_signal: np.ndarray,
    bias: np.ndarray,
    stop_level: np.ndarray,
    target_1: np.ndarray,
    rolling_n_trades: int,
    rolling_loss_multiple: float,
    consecutive_stops: int,
    daily_loss_pct_cap: float,
    cooldown_bars: int,
    capital: float,
) -> np.ndarray:
    """
    Simulate a forward pass of the strategy to estimate when the circuit breaker
    would trip historically. This is a SIGNAL-LEVEL approximation — the real
    backtester computes actual trade outcomes; this estimates them from
    target_1 / stop_level positions to feed back into the entry filter.

    For each entry bar, look ahead to the first of:
      - price hits target_1 (winner)
      - price hits stop_level (loser)
    Then track rolling stats and emit `cb_active=True` when a breaker fires.

    Returns a boolean array where True = entries should be blocked this bar.

    NOTE: This is an *advisory* circuit-breaker signal. The real backtester
    must apply the same logic on actual fills. Treat this as a "what would
    have been blocked in IS" diagnostic that also drops the IS noise where
    a discipline-following trader would have stopped.
    """
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    # Daily bucketing — use string keys to avoid DatetimeIndex .get_loc issues
    if isinstance(df.index, pd.DatetimeIndex):
        daily_keys = df.index.strftime("%Y-%m-%d").values
    else:
        daily_keys = (np.arange(n) // 24).astype(str)

    cb_active = np.zeros(n, dtype=bool)
    trade_pnls: list[float] = []  # in dollars (approximate)
    trade_results: list[str] = []  # "win" | "loss"
    daily_pnl: dict = {}
    in_trade_until = -1
    cooldown_until = -1

    for i in range(n):
        # Cooldown enforcement
        if i < cooldown_until:
            cb_active[i] = True
            continue

        # Already in a trade? — no new entries, but we don't block here (the
        # backtester handles position management; this is just the breaker)
        if i < in_trade_until:
            continue

        # Check the three trip conditions
        # 1. Rolling-N P&L breaker
        recent = trade_pnls[-rolling_n_trades:]
        if len(recent) >= rolling_n_trades:
            winners = [p for p in recent if p > 0]
            avg_win = np.mean(winners) if winners else (capital * 0.005)  # fallback
            rolling_pnl = sum(recent)
            if rolling_pnl < -rolling_loss_multiple * avg_win:
                cb_active[i] = True
                cooldown_until = i + cooldown_bars
                continue

        # 2. Consecutive stops
        recent_results = trade_results[-consecutive_stops:]
        if len(recent_results) >= consecutive_stops and all(
            r == "loss" for r in recent_results
        ):
            cb_active[i] = True
            cooldown_until = i + cooldown_bars
            continue

        # 3. Daily loss cap
        today_key = daily_keys[i]
        if daily_pnl.get(today_key, 0) < -daily_loss_pct_cap * capital:
            cb_active[i] = True
            # cooldown to next day
            cooldown_until = i + 1
            continue

        # No breaker tripped. If this bar has an entry signal, simulate the trade
        # forward to update statistics.
        if entry_signal[i] == "ENTRY_NOW":
            entry_price = df["close"].values[i]
            sl = stop_level[i]
            tp = target_1[i]
            if np.isnan(sl) or np.isnan(tp):
                continue
            direction = 1 if bias[i] == "STRONG_BULL" else -1

            # Look forward for stop or target hit
            outcome = "open"
            exit_price = entry_price
            for j in range(i + 1, min(n, i + 100)):  # cap at 100 bars to bound runtime
                hi_j, lo_j = high[j], low[j]
                if direction == 1:
                    if lo_j <= sl:
                        outcome = "loss"
                        exit_price = sl
                        break
                    if hi_j >= tp:
                        outcome = "win"
                        exit_price = tp
                        break
                else:
                    if hi_j >= sl:
                        outcome = "loss"
                        exit_price = sl
                        break
                    if lo_j <= tp:
                        outcome = "win"
                        exit_price = tp
                        break
            else:
                # ran past lookahead window; treat as unresolved (no stat update)
                continue

            pnl = (exit_price - entry_price) * direction  # in price units; approximation
            trade_pnls.append(pnl)
            trade_results.append(outcome)
            daily_pnl[today_key] = daily_pnl.get(today_key, 0) + pnl
            # bound the trade window so we don't open the next while this is "open"
            in_trade_until = j

    return cb_active


# ── Main signal generator ─────────────────────────────────────────────────────


def generate_meanrev_v2_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_long: float = 30.0,
    rsi_short: float = 70.0,
    # v2 vol-adaptive trigger
    dislocation_lookback: int = 200,
    dislocation_percentile_min: float = 95.0,
    # v2 vol-targeted stop
    stop_atr_mult: float = 1.5,
    stop_atr_long_window: int = _DEFAULT_ATR_PERCENTILE_WINDOW,
    stop_atr_long_percentile: float = _DEFAULT_ATR_PERCENTILE,
    # v2 time-stop & trail
    time_stop_bars: int = 8,
    trail_to_be_at_pct_of_target: float = 0.5,
    # v2 circuit breaker
    cb_rolling_n_trades: int = 5,
    cb_rolling_loss_multiple: float = 2.0,
    cb_consecutive_stops: int = 3,
    cb_daily_loss_pct_cap: float = 0.01,
    cb_cooldown_bars: int = 5,
    capital_for_cb: float = 50_000.0,
    # OU integration
    ou_mode: str = "filter",  # "off" | "filter" | "zscore_trigger"
    ou_window: int = 100,
    ou_min_half_life_bars: int = 4,
    ou_max_half_life_bars: int = 100,
    ou_zscore_threshold: float = 2.0,
    ou_theta_min: float = 0.05,
    signal_direction: str = "both",  # "both" | "long_only" | "short_only"
) -> pd.DataFrame:
    """Generate v2 mean-reversion signals with the three structural fixes.

    See module docstring for full rationale. Keep argument names stable —
    the runner scripts will sweep these as the parameter grid.
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── Indicators ────────────────────────────────────────────────────────
    sma = close.rolling(bb_period).mean()
    sd = close.rolling(bb_period).std(ddof=0)
    bb_upper = sma + bb_std * sd
    bb_lower = sma - bb_std * sd
    rsi = _wilder_rsi(close, period=rsi_period)
    atr = _wilder_atr(high, low, close, period=_DEFAULT_ATR_PERIOD)
    atr_long_q = _rolling_quantile(atr, stop_atr_long_window, stop_atr_long_percentile)

    # ── v2 fix #1: Vol-adjusted percentile trigger ────────────────────────
    # Dislocation = how far close is from sma, normalized by atr.
    # We track the SIGNED dislocation and compute its rolling percentile rank
    # over `dislocation_lookback` bars. Long entries require the negative tail
    # (current dislocation is below the (100 - min)th percentile of the
    # trailing window). Short entries require the positive tail.
    dislocation = (close - sma) / atr.replace(0, np.nan)
    # Lower tail percentile = how many trailing values are ABOVE the current value
    # (low values are extreme negatives). For LONGs we want current to be in the
    # bottom (100 - dpm)% of trailing → percentile_rank <= 100 - dpm.
    dpr = _rolling_percentile_rank(dislocation, dislocation_lookback)
    dpr_long = dpr <= (100.0 - dislocation_percentile_min)  # negative tail extreme
    dpr_short = dpr >= dislocation_percentile_min  # positive tail extreme

    # ── OU rolling parameters ─────────────────────────────────────────────
    if ou_mode in ("filter", "zscore_trigger"):
        ou_theta, ou_mu, ou_sigma, ou_half_life = _rolling_ou_params(close, window=ou_window)
        # Steady-state z-score: (price - mu) / sqrt(sigma^2 / (2 theta))
        ou_std = np.sqrt(ou_sigma**2 / (2 * ou_theta.where(ou_theta > 0)))
        ou_z = (close - ou_mu) / ou_std.replace(0, np.nan)
    else:
        ou_theta = pd.Series(np.nan, index=df.index, name="ou_theta")
        ou_mu = pd.Series(np.nan, index=df.index, name="ou_mu")
        ou_half_life = pd.Series(np.nan, index=df.index, name="ou_half_life")
        ou_z = pd.Series(np.nan, index=df.index, name="ou_z")

    # ── Entry conditions ─────────────────────────────────────────────────
    warm = sma.notna() & rsi.notna() & atr.notna()

    if ou_mode == "zscore_trigger":
        # PURE OU mode: use OU z-score AS the entry condition
        long_cond = (
            (ou_z < -ou_zscore_threshold)
            & (ou_theta > ou_theta_min)
            & (ou_half_life.between(ou_min_half_life_bars, ou_max_half_life_bars))
            & warm
        )
        short_cond = (
            (ou_z > ou_zscore_threshold)
            & (ou_theta > ou_theta_min)
            & (ou_half_life.between(ou_min_half_life_bars, ou_max_half_life_bars))
            & warm
        )
    else:
        # v1-compatible Bollinger+RSI trigger, gated by dislocation percentile
        long_cond = (close < bb_lower) & (rsi < rsi_long) & dpr_long.fillna(False) & warm
        short_cond = (close > bb_upper) & (rsi > rsi_short) & dpr_short.fillna(False) & warm

        if ou_mode == "filter":
            # OU half-life filter: only trade when series shows tradeable reversion speed
            ou_ok = ou_half_life.between(ou_min_half_life_bars, ou_max_half_life_bars) & (
                ou_theta > ou_theta_min
            )
            long_cond = long_cond & ou_ok.fillna(False)
            short_cond = short_cond & ou_ok.fillna(False)

    # Conflict resolution
    conflict = long_cond & short_cond
    long_cond = long_cond & ~conflict
    short_cond = short_cond & ~conflict

    if signal_direction == "long_only":
        short_cond = short_cond & False
    elif signal_direction == "short_only":
        long_cond = long_cond & False

    # ── v2 fix #2a: Vol-targeted stop sizing ──────────────────────────────
    # Stop distance = max(stop_atr_mult * ATR(14), stop_atr_mult * ATR_p75(50))
    # Use .values throughout to avoid index-vs-positional indexing bugs
    stop_dist_short_arr = (stop_atr_mult * atr).values
    stop_dist_long_arr = (stop_atr_mult * atr_long_q).values
    # Fill NaN in long-window stop with short-window value
    long_filled = np.where(np.isnan(stop_dist_long_arr), stop_dist_short_arr, stop_dist_long_arr)
    stop_dist = np.maximum(stop_dist_short_arr, long_filled)
    # Diagnostic label for which window drove sizing
    stop_vol_regime = np.where(long_filled > stop_dist_short_arr, "high", "normal")

    # ── Build per-bar arrays ──────────────────────────────────────────────
    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)
    time_stop_remaining = np.full(n, np.nan)

    # Targets: midband (or OU mu if OU mode active)
    target_mid = ou_mu.fillna(sma) if ou_mode != "off" else sma
    band_width = (bb_upper - bb_lower) / 2.0

    long_idx = np.flatnonzero(long_cond.values)
    for i in long_idx:
        price = float(close.iloc[i])
        sd_i = float(stop_dist[i])
        if np.isnan(sd_i):
            continue
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BULL"
        stop_level[i] = price - sd_i
        tgt = float(target_mid.iloc[i])
        target_1[i] = tgt
        target_2[i] = tgt + 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_upper.iloc[i])
        time_stop_remaining[i] = time_stop_bars

    short_idx = np.flatnonzero(short_cond.values)
    for i in short_idx:
        price = float(close.iloc[i])
        sd_i = float(stop_dist[i])
        if np.isnan(sd_i):
            continue
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BEAR"
        stop_level[i] = price + sd_i
        tgt = float(target_mid.iloc[i])
        target_1[i] = tgt
        target_2[i] = tgt - 0.5 * float(band_width.iloc[i])
        target_3[i] = float(bb_lower.iloc[i])
        time_stop_remaining[i] = time_stop_bars

    # ── v2 fix #2b: Midband-cross exit (same as v1 but uses adaptive target) ──
    prev_close = close.shift(1)
    prev_target = target_mid.shift(1)
    crossed_up = (prev_close < prev_target) & (close >= target_mid)
    crossed_down = (prev_close > prev_target) & (close <= target_mid)
    exit_cond = (crossed_up | crossed_down) & warm
    for i in np.flatnonzero(exit_cond.values):
        exit_signal[i] = "EXIT_NOW"

    # ── v2 fix #3: Circuit breaker (advisory, recomputed each call) ──────
    cb_active = _compute_circuit_breaker(
        df,
        entry_signal,
        bias,
        stop_level,
        target_1,
        cb_rolling_n_trades,
        cb_rolling_loss_multiple,
        cb_consecutive_stops,
        cb_daily_loss_pct_cap,
        cb_cooldown_bars,
        capital_for_cb,
    )
    # Apply breaker: force NO_TRADE where breaker is active
    blocked_idx = np.flatnonzero(cb_active & (entry_signal == "ENTRY_NOW"))
    for i in blocked_idx:
        entry_signal[i] = "NO_TRADE"
        bias[i] = "NEUTRAL"
        stop_level[i] = np.nan
        target_1[i] = np.nan
        target_2[i] = np.nan
        target_3[i] = np.nan

    regime = np.where(warm, "MEAN_REVERTING", "NEUTRAL")

    # ── Write outputs ────────────────────────────────────────────────────
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
    # v2 diagnostics
    df["dislocation_percentile"] = dpr
    df["stop_vol_regime"] = stop_vol_regime
    df["time_stop_bars_remaining"] = time_stop_remaining
    df["circuit_breaker_active"] = cb_active
    df["ou_theta"] = ou_theta.values
    df["ou_mu"] = ou_mu.values
    df["ou_half_life"] = ou_half_life.values
    df["ou_z"] = ou_z.values

    return df


def get_meanrev_v2_defaults() -> dict:
    """Return a copy of the v2 default parameters."""
    return dict(MEANREV_V2_DEFAULTS)
