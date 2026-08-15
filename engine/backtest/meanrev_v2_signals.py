"""
Bollinger-Band + RSI Mean-Reversion v2 Signal Generator for JARVIS TRADER.

Addresses the three structural failures of legacy mean reversion:
  1. Catching falling knives in trending phases (solved via rolling Ornstein-Uhlenbeck filter)
  2. Over-trading inside volatility compression (solved via 95th-percentile dislocation trigger)
  3. Continuous account losses during drawdowns (solved via active State-Machine Circuit Breaker)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_DEFAULT_ATR_PERIOD = 14

def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Computes Wilder's Average True Range."""
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Computes Wilder's Relative Strength Index."""
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

def _rolling_quantile(series: pd.Series, window: int, q: float) -> pd.Series:
    """Calculates rolling quantile."""
    return series.rolling(window=window).quantile(q)

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
        
        # OLS via numpy (avoid sklearn dependency in hot execution path)
        X = np.column_stack([np.ones_like(y_lag), y_lag])
        try:
            coef, _, _, _ = np.linalg.lstsq(X, y_curr, rcond=None)
            alpha, beta = coef[0], coef[1]
        except np.linalg.LinAlgError:
            continue
            
        if beta <= 0.001 or beta >= 0.999:
            continue  # No valid mean-reversion structure (random walk or trending)
            
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

def generate_meanrev_v2_signals(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_long: float = 30.0,
    rsi_short: float = 70.0,
    # v2 vol-adaptive trigger lookback
    dislocation_lookback: int = 200,
    dislocation_percentile_min: float = 95.0,
    # v2 position parameters
    stop_atr_mult: float = 1.5,
    time_stop_bars: int = 8,
    # v2 circuit breaker limits
    cb_rolling_n_trades: int = 5,
    cb_rolling_loss_multiple: float = 2.0,
    cb_consecutive_stops: int = 3,
    cb_cooldown_bars: int = 5,
    # OU integrations
    ou_window: int = 100,
    ou_min_half_life: int = 4,
    ou_max_half_life: int = 100,
    # Trading direction toggle ('both', 'long_only', 'short_only')
    direction: str = "both"
) -> pd.DataFrame:
    """
    Generates high-performance mean reversion signals incorporating Ornstein-Uhlenbeck filtering,
    dynamic Bollinger Band dislocation quantiles, and protective circuit-breaker states.
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── Basic Technical Indicators ─────────────────────────────────────────────
    sma = close.rolling(bb_period).mean()
    sd = close.rolling(bb_period).std(ddof=0).replace(0, 1e-9)
    bb_upper = sma + bb_std * sd
    bb_lower = sma - bb_std * sd
    
    rsi = _wilder_rsi(close, period=rsi_period)
    atr = _wilder_atr(high, low, close, period=_DEFAULT_ATR_PERIOD)

    # ── v2 Fix 1: Vol-Adaptive Dislocation Percentile ──────────────────────────
    dislocation = (close - sma).abs() / sd
    dislocation_thresh = _rolling_quantile(dislocation, dislocation_lookback, dislocation_percentile_min / 100.0)
    vol_adaptive_trigger = dislocation > dislocation_thresh

    # ── v2 Fix 2: Rolling Ornstein-Uhlenbeck Speed Filtering ────────────────────
    ou_theta, ou_mu, ou_sigma, ou_half_life = _rolling_ou_params(close, window=ou_window)

    # ── Establish Symmetrical Entry States ──────────────────────────────────────
    entry_signal = np.full(len(df), "NO_TRADE", dtype=object)
    exit_signal = np.full(len(df), "NO_EXIT", dtype=object)
    bias = np.full(len(df), "NEUTRAL", dtype=object)
    regime = np.full(len(df), "NEUTRAL", dtype=object)
    
    stop_level = np.full(len(df), np.nan)
    target_1 = np.full(len(df), np.nan)
    
    active_position = None # "LONG", "SHORT", or None
    position_entry_idx = 0
    stops_hit_count = 0
    breaker_cooldown_remaining = 0

    for i in range(len(df)):
        # Update circuit breaker countdown
        if breaker_cooldown_remaining > 0:
            breaker_cooldown_remaining -= 1
            entry_signal[i] = "NO_TRADE"
            continue

        # Real-time state indicators
        p_close = close.iloc[i]
        p_upper = bb_upper.iloc[i]
        p_lower = bb_lower.iloc[i]
        p_rsi = rsi.iloc[i]
        p_atr = atr.iloc[i]
        
        # Check active position management
        if active_position is not None:
            # 1. Evaluate Trailing Stop / Hard stop
            if active_position == "LONG":
                if low.iloc[i] <= stop_level[position_entry_idx]:
                    active_position = None
                    stops_hit_count += 1
                    if stops_hit_count >= cb_consecutive_stops:
                        breaker_cooldown_remaining = cb_cooldown_bars
                        stops_hit_count = 0
                    continue
                # Exiting at mid-band reversion complete
                if p_close >= sma.iloc[i]:
                    exit_signal[i] = "EXIT_NOW"
                    active_position = None
                    stops_hit_count = 0
                    continue
                    
            elif active_position == "SHORT":
                if high.iloc[i] >= stop_level[position_entry_idx]:
                    active_position = None
                    stops_hit_count += 1
                    if stops_hit_count >= cb_consecutive_stops:
                        breaker_cooldown_remaining = cb_cooldown_bars
                        stops_hit_count = 0
                    continue
                # Exiting at mid-band reversion complete
                if p_close <= sma.iloc[i]:
                    exit_signal[i] = "EXIT_NOW"
                    active_position = None
                    stops_hit_count = 0
                    continue

            # 2. Time-Based Stop (using half-life limits)
            bars_held = i - position_entry_idx
            expected_hl = ou_half_life.iloc[position_entry_idx]
            hl_cutoff = min(time_stop_bars, expected_hl if not np.isnan(expected_hl) else time_stop_bars)
            
            if bars_held >= hl_cutoff:
                exit_signal[i] = "EXIT_NOW"
                active_position = None
                continue

        # Evaluate Signal Generation (Flat state)
        if active_position is None:
            # 1. Verify structural mean reversion criteria via Ornstein-Uhlenbeck
            hl_i = ou_half_life.iloc[i]
            if np.isnan(hl_i) or hl_i < ou_min_half_life or hl_i > ou_max_half_life:
                continue # Random walk or explosive trend - reject trade entry
                
            regime[i] = "MEAN_REVERTING"
            
            # LONG TRIGGER (Allow only if direction is 'both' or 'long_only')
            if direction in ("both", "long_only") and p_close < p_lower and p_rsi < rsi_long and vol_adaptive_trigger.iloc[i]:
                entry_signal[i] = "ENTRY_NOW"
                bias[i] = "STRONG_BULL"
                stop_level[i] = p_close - (stop_atr_mult * p_atr)
                target_1[i] = sma.iloc[i]
                active_position = "LONG"
                position_entry_idx = i
                
            # SHORT TRIGGER (Allow only if direction is 'both' or 'short_only')
            elif direction in ("both", "short_only") and p_close > p_upper and p_rsi > rsi_short and vol_adaptive_trigger.iloc[i]:
                entry_signal[i] = "ENTRY_NOW"
                bias[i] = "STRONG_BEAR"
                stop_level[i] = p_close + (stop_atr_mult * p_atr)
                target_1[i] = sma.iloc[i]
                active_position = "SHORT"
                position_entry_idx = i

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["bias"] = bias
    df["regime"] = regime
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["bb_upper"] = bb_upper
    df["bb_mid"] = sma
    df["bb_lower"] = bb_lower
    df["rsi_14"] = rsi
    df["atr_14"] = atr
    df["ou_half_life"] = ou_half_life

    return df
