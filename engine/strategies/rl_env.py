"""
JARVIS TRADER — TradingEnvMES (RL Discovery Alias)
====================================================

Thin alias / factory layer over TradingEnvironment for the RL strategy
discovery pipeline.  The canonical environment lives in rl_environment.py
(TradingEnvironment); this module exposes the name TradingEnvMES that the
spec and runbook reference, so external tooling and scripts can import a
stable name without knowing the internal class hierarchy.

Observation space : Box(shape=(23,), dtype=float32)
    18 base features (OHLCV-derived indicators from rl_config.STATE_FEATURES)
    5 Discord signal context features (indices 18-22; zeros when no live context)

Action space : Discrete(4)
    0 = HOLD, 1 = BUY, 2 = SELL, 3 = CLOSE

Reward : P&L normalized by ATR, minus commissions on closing trades,
         minus hold cost while position is losing, minus entry cost per new
         entry, plus T1 bonus when target is reached.

Episode : Random 500-bar window from the loaded DataFrame (RTH bars only if
          the caller pre-filters the DataFrame before passing it in).

Data source : Caller provides a processed DataFrame (OHLCV + all indicators
              from backtest/signals.py compute_all_indicators).  The
              rl_train.py module handles data fetching via BacktestDataLoader.

Relationship to rl_environment.py :
    TradingEnvMES = TradingEnvironment (alias).
    make_trading_env() = build_env() with MES-specific defaults.

Usage:
    from strategies.rl_env import TradingEnvMES, make_trading_env

    env = make_trading_env(df)              # MES, default capital
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(1)  # BUY
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from strategies.rl_config import MAX_EPISODE_BARS

# Canonical environment — all logic lives there.
from strategies.rl_environment import TradingEnvironment, build_env

# ── Public alias ──────────────────────────────────────────────────────────────

#: Stable public name for the gymnasium-compatible trading environment.
#: Equivalent to TradingEnvironment.  Import TradingEnvMES for new code that
#: targets the RL discovery pipeline; use TradingEnvironment directly if you
#: need the full constructor signature (discord_context, reward_config, etc.).
TradingEnvMES = TradingEnvironment


# ── Factory ───────────────────────────────────────────────────────────────────


def make_trading_env(
    df: pd.DataFrame,
    symbol: str = "MES",
    initial_capital: float = 10_000.0,
    max_position: int = 1,
    max_episode_bars: int = MAX_EPISODE_BARS,
    reward_config: Optional[dict] = None,
) -> TradingEnvMES:
    """
    Create a TradingEnvMES from a pre-processed OHLCV + indicators DataFrame.

    This is the preferred factory for the RL strategy discovery loop.  It
    delegates to build_env() from rl_environment.py and applies MES-style
    defaults.  No Discord context is injected at training time (features
    18-22 are zero-padded neutral defaults), keeping the training loop
    free of live-data dependencies.

    Parameters
    ----------
    df              : DataFrame with columns from compute_all_indicators():
                      open, high, low, close, volume, atr, stc_val, ema_21,
                      ema_trend, phase_val, volume_signal, cci_50, buy_pct,
                      macd_hist, rsi, bb_upper, bb_lower, adx — at minimum.
    symbol          : Futures symbol for instrument-specific params (default: MES).
    initial_capital : Starting capital for P&L tracking (default: $10,000).
    max_position    : Maximum open contracts (default: 1).
    max_episode_bars: Bars per episode window (default: MAX_EPISODE_BARS=500).
    reward_config   : Optional reward config override dict (merges with
                      REWARD_CONFIG from rl_config.py).

    Returns
    -------
    TradingEnvMES instance ready for gymnasium interaction.
    """
    return build_env(
        symbol=symbol,
        df=df,
        initial_capital=initial_capital,
        max_position=max_position,
        max_episode_bars=max_episode_bars,
        reward_config=reward_config,
        discord_context=None,  # training-time: no live context
    )
