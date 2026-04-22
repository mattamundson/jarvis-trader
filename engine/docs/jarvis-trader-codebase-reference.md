# JARVIS Trader — Codebase Reference
**Engine Path**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine`
**Last Updated**: 2026-03-29
**Purpose**: Complete verbatim source code for all 13 engine modules with analysis.

---

## Table of Contents

1. [config.py — Configuration & Settings](#configpy)
2. [backtest/indicators.py — TOS Indicator Implementations](#backtestindicatorspy)
3. [backtest/signals.py — 5-Layer Signal Generation](#backtestsignalspy)
4. [backtest/backtester.py — Walk-Forward Simulator](#backtestbacktesterpy)
5. [backtest/data_loader.py — Data Loader & Cache](#backtestdata_loaderpy)
6. [backtest/optimizer.py — Grid Search Optimizer](#backtestoptimizerpy)
7. [backtest/fetch_intraday.py — Intraday Data Fetcher](#backtestfetch_intradaypy)
8. [backtest/run_backtest.py — CLI Runner](#backtestrun_backtestpy)
9. [agents/schemas.py — Pipeline Schemas & Dataclasses](#agentsschemaspy)
10. [agents/pipeline.py — Trading Pipeline Orchestration](#agentspipelinepy)
11. [agents/rules/agent_prompts.py — LLM Agent System Prompts](#agentsrulesagent_promptspy)
12. [agents/rules/trading_rules.md — 5-Layer Trading Framework](#agentsrulestrading_rulesmd)
13. [main.py — FastAPI Server](#mainpy)

---

## Project Directory Structure

```
engine/
├── main.py                    # FastAPI server (port 8010), all endpoints
├── config.py                  # Pydantic settings — risk params, API keys, watchlists
├── .env                       # Secrets (not in git)
├── backtest/
│   ├── __init__.py
│   ├── indicators.py          # Pure-Python TOS indicator implementations
│   ├── signals.py             # 5-layer signal generation (Tony Stark framework)
│   ├── backtester.py          # Walk-forward event-driven simulator
│   ├── data_loader.py         # yfinance + disk cache
│   ├── optimizer.py           # Grid search parameter optimizer
│   ├── fetch_intraday.py      # Chunked intraday fetcher (Polygon + yfinance)
│   ├── run_backtest.py        # CLI runner
│   ├── cache/                 # Cached OHLCV CSVs
│   └── results/               # Backtest JSON outputs + optimal params
├── agents/
│   ├── pipeline.py            # 5-stage pipeline orchestration
│   ├── schemas.py             # 15 dataclasses, 5 enums for inter-agent comms
│   ├── technical_analyst.py
│   ├── news_analyst.py
│   ├── social_analyst.py
│   ├── fundamental_analyst.py
│   ├── bull_researcher.py
│   ├── bear_researcher.py
│   ├── debate.py
│   ├── trader.py
│   ├── risk_manager.py
│   ├── fund_manager.py
│   └── rules/
│       ├── agent_prompts.py   # 10 LLM system prompts
│       └── trading_rules.md   # 5-layer framework documentation
├── data/
│   ├── market_data.py
│   └── fred_data.py
├── risk/
│   └── safety_layer.py
└── notifications/
    └── whatsapp.py
```

---

## config.py

### Purpose

`config.py` defines the `TradingConfig` class, a Pydantic `BaseSettings` model that loads all runtime configuration from environment variables and a `.env` file. It centralizes every tunable parameter for risk controls, broker connections, market data APIs, LLM models, databases, notifications, and instrument watchlists into a single validated singleton. The file enforces a strict safety posture by defaulting `LIVE_TRADING_ENABLED` to `False` and `REQUIRE_HUMAN_APPROVAL` to `True`, ensuring no autonomous live orders can fire without explicit opt-in. All secrets are sourced exclusively from environment variables — nothing is hardcoded in source. The module exposes a module-level `settings` singleton that all other modules import directly.

### Key Functions / Classes

| Name | Type | Purpose |
|------|------|---------|
| `TradingConfig` | class (Pydantic BaseSettings) | Master configuration container — all 40+ settings with defaults and descriptions |
| `settings` | module-level singleton | Pre-instantiated `TradingConfig` used by all engine modules via `from config import settings` |
| `MAX_POSITION_SIZE_PCT` | field (float) | Caps any single position at 5% of total portfolio value |
| `MAX_DAILY_LOSS_PCT` | field (float) | Kill-switch threshold — halts all trading at -2% daily P&L |
| `MAX_DRAWDOWN_PCT` | field (float) | Emergency halt at -10% from equity high-water mark |
| `LIVE_TRADING_ENABLED` | field (bool) | Master enable/disable for live order routing — defaults False |
| `REQUIRE_HUMAN_APPROVAL` | field (bool) | Requires Matt's explicit approval for every live trade |
| `FUTURES_WATCHLIST` | field (list[str]) | Micro futures to trade: MES, MNQ, MCL |
| `OPTIONS_WATCHLIST` | field (list[str]) | Options underlyings: SPY, QQQ, AAPL, TSLA |

### Source Code

```python
"""
JARVIS TRADER — Configuration
All settings via environment variables (.env file).
Never hardcode secrets.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class TradingConfig(BaseSettings):
    """Risk parameters — all configurable, never LLM-modifiable"""

    # ── Risk Controls (Safety Layer) ─────────────────────────────────────
    MAX_POSITION_SIZE_PCT: float = Field(0.05, description="Max 5% of portfolio per position")
    MAX_DAILY_LOSS_PCT: float = Field(0.02, description="Halt trading at -2% daily P&L")
    MAX_DRAWDOWN_PCT: float = Field(0.10, description="Emergency halt at -10% from equity peak")
    MAX_ORDERS_PER_MINUTE: int = Field(10, description="Rate throttle")
    MAX_CORRELATED_EXPOSURE_PCT: float = Field(0.20, description="Max 20% in correlated positions")
    PRICE_COLLAR_PCT: float = Field(0.05, description="Reject orders >5% from NBBO")
    MAX_SINGLE_ORDER_VALUE: float = Field(5000.0, description="No single order > $5,000")
    MAX_MARGIN_UTILIZATION: float = Field(0.40, description="Never exceed 40% of available margin")

    # ── Futures-Specific ─────────────────────────────────────────────────
    MAX_CONTRACTS_PER_INSTRUMENT: int = Field(2, description="Max micro contracts per instrument")
    MAX_OVERNIGHT_CONTRACTS: int = Field(1, description="Max contracts to hold overnight")

    # ── Autonomy Tier ─────────────────────────────────────────────────────
    LIVE_TRADING_ENABLED: bool = Field(False, description="Set True to enable live trading")
    REQUIRE_HUMAN_APPROVAL: bool = Field(True, description="All live trades require Matt's approval")

    # ── Broker: Interactive Brokers ───────────────────────────────────────
    IBKR_HOST: str = Field("127.0.0.1", description="IB Gateway host")
    IBKR_PORT: int = Field(4002, description="4001=live, 4002=paper")
    IBKR_CLIENT_ID: int = Field(1, description="Client ID for IB Gateway connection")
    IBKR_PAPER_MODE: bool = Field(True, description="Always start in paper mode")

    # ── Broker: Charles Schwab ────────────────────────────────────────────
    SCHWAB_APP_KEY: Optional[str] = Field(None, env="SCHWAB_APP_KEY")
    SCHWAB_APP_SECRET: Optional[str] = Field(None, env="SCHWAB_APP_SECRET")
    SCHWAB_CALLBACK_URL: str = Field("https://127.0.0.1", env="SCHWAB_CALLBACK_URL")

    # ── Market Data ───────────────────────────────────────────────────────
    POLYGON_API_KEY: Optional[str] = Field(None, env="POLYGON_API_KEY")
    FINNHUB_API_KEY: Optional[str] = Field(None, env="FINNHUB_API_KEY")
    ALPACA_API_KEY: Optional[str] = Field(None, env="ALPACA_API_KEY")
    ALPACA_SECRET_KEY: Optional[str] = Field(None, env="ALPACA_SECRET_KEY")
    ALPACA_PAPER: bool = Field(True, env="ALPACA_PAPER")

    # ── LLM (Vercel AI Gateway via OIDC) ─────────────────────────────────
    # These are auto-provisioned by `vercel env pull` — no manual API keys needed
    ANTHROPIC_API_KEY: Optional[str] = Field(None, env="ANTHROPIC_API_KEY")  # Fallback if no Gateway
    LLM_PROVIDER: str = Field("anthropic", description="LLM provider")

    # ── Agent Models ──────────────────────────────────────────────────────
    ANALYST_MODEL: str = Field("claude-sonnet-4-6", description="Model for analyst agents")
    TRADER_MODEL: str = Field("claude-opus-4-7", description="Model for trader/risk/fund manager")
    FAST_MODEL: str = Field("claude-haiku-4-5-20251001", description="Model for fast/cheap ops")

    # ── Databases ─────────────────────────────────────────────────────────
    POSTGRES_URL: str = Field("postgresql://jarvis:jarvis@localhost:5432/jarvis_trader")
    REDIS_URL: str = Field("redis://localhost:6379")
    QUESTDB_HOST: str = Field("localhost")
    QUESTDB_PORT: int = Field(9000)

    # ── Notifications (WhatsApp via Twilio) ───────────────────────────────
    TWILIO_ACCOUNT_SID: Optional[str] = Field(None, env="TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(None, env="TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(None, env="TWILIO_WHATSAPP_FROM")
    WHATSAPP_TO: Optional[str] = Field(None, env="WHATSAPP_TO")

    # ── Instruments to Trade ─────────────────────────────────────────────
    FUTURES_WATCHLIST: list[str] = Field(
        default=["MES", "MNQ", "MCL"],
        description="Micro futures contracts to trade"
    )
    OPTIONS_WATCHLIST: list[str] = Field(
        default=["SPY", "QQQ", "AAPL", "TSLA"],
        description="Underlying symbols for options trading"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton
settings = TradingConfig()
```

---

## backtest/indicators.py

### Purpose

`indicators.py` contains pure-Python reimplementations of all ThinkorSwim-derived technical indicators used by the JARVIS trading framework, with no TA-Lib dependency — only NumPy and pandas. Each function corresponds directly to a named TOS script (e.g., Saty ATR Levels, NextSignalMomentum, shared_OB_STYLE_CYCLE) to ensure backtest parity with live chart behavior. The module covers ATR variants (Wilder's and SMA), KAMA, STC, Phase Oscillator, Volume Stack, Keltner Channels, Initial Balance levels, CCI, ATR Fibonacci levels, range-consumed percentage, and the EMA 8/21/34 ribbon. All functions accept pandas Series inputs and return Series or Tuples of Series so they compose cleanly into the signal pipeline. The implementations are stateless pure functions with no side effects, making them trivially testable and vectorizable.

### Key Functions / Classes

| Name | Type | Purpose |
|------|------|---------|
| `wilder_atr` | function | Wilder's smoothed Average True Range — used by Saty ATR Levels and Phase Oscillator |
| `sma_atr` | function | SMA of True Range — used internally by Keltner Channels |
| `kama` | function | Kaufman Adaptive Moving Average (period=10) — Layer 3 trend filter |
| `stc` | function | Schaff Trend Cycle (fast=23, slow=50, K=10, D=3) — primary entry timing oscillator |
| `phase_oscillator` | function | Saty Phase Oscillator — returns (phase_value, is_compression); identifies regime and exhaustion |
| `volume_stack` | function | Saty Volume Stack — returns (buy_vol, sell_vol, buy_pct) from OHLCV |
| `keltner_channels` | function | Keltner Channel (SMA basis, SMA ATR bands) — used by OB_OMEGA and KMaster |
| `ib_levels` | function | Initial Balance high/low/range/quadrants/extensions for each trading day |
| `cci` | function | Commodity Channel Index (period=50) — zero-cross = trend direction change |
| `atr_fib_levels` | function | ATR Fibonacci price levels (10 ratios up and down) from prior close |
| `range_consumed_pct` | function | Percentage of daily ATR range already consumed — exhaustion filter |
| `ema_ribbon` | function | EMA 8/21/34 ribbon — returns tuple; stacked alignment = trend confirmation |

### Source Code

```python
"""
JARVIS TRADER — Backtest Indicators
Pure-Python implementations of all ThinkorSwim-derived indicators.
No TA-Lib dependency. Uses numpy and pandas only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple, Dict, List, Optional


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Average True Range (used by Saty ATR Levels script)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)

    atr = pd.Series(index=close.index, dtype=float)
    atr.iloc[:period] = np.nan
    if len(tr) >= period:
        atr.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(tr)):
            atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr


def sma_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """SMA of True Range (used by Keltner channels)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def kama(close: pd.Series, period: int = 10, fast_period: int = 2, slow_period: int = 30) -> pd.Series:
    """
    Kaufman Adaptive Moving Average (KAMA).
    Used by NextSignalMomentum script. Period=10, slow=30.
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    result = pd.Series(index=close.index, dtype=float)
    result.iloc[:period] = np.nan

    if len(close) < period:
        return result

    result.iloc[period - 1] = close.iloc[period - 1]

    for i in range(period, len(close)):
        change = abs(close.iloc[i] - close.iloc[i - period])
        volatility = close.diff().abs().iloc[i - period + 1:i + 1].sum()

        if volatility == 0:
            er = 0.0
        else:
            er = change / volatility

        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result.iloc[i] = result.iloc[i - 1] + sc * (close.iloc[i] - result.iloc[i - 1])

    return result


def stc(close: pd.Series, fast: int = 23, slow: int = 50,
        k_period: int = 10, d_period: int = 3) -> pd.Series:
    """
    Schaff Trend Cycle (STC).
    Used by shared_OB_STYLE_CYCLE script.
    Parameters: fast=23, slow=50, K=10, D=3.
    Oversold=19, Overbought=88.
    Returns Series 0-100.
    """
    # MACD line
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow

    def _stoch(series: pd.Series, period: int) -> pd.Series:
        lowest = series.rolling(period).min()
        highest = series.rolling(period).max()
        denom = highest - lowest
        result = pd.Series(index=series.index, dtype=float)
        mask = denom != 0
        result[mask] = (series[mask] - lowest[mask]) / denom[mask] * 100
        result[~mask] = 50.0
        return result

    # First stochastic of MACD
    k1 = _stoch(macd_line, k_period)
    d1 = k1.ewm(span=d_period, adjust=False).mean()

    # Second stochastic of smoothed
    k2 = _stoch(d1, k_period)
    stc_val = k2.ewm(span=d_period, adjust=False).mean()

    return stc_val.clip(0, 100)


def phase_oscillator(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ema_len: int = 21,
    atr_len: int = 14,
    bb_len: int = 21,
    bb_std: float = 2.0
) -> Tuple[pd.Series, pd.Series]:
    """
    Saty Phase Oscillator.
    Returns (phase_value, is_compression).
    Phase = (close - EMA) / (3 * ATR) * 100, clamped [-100, 100].
    Compression = Bollinger Bands narrower than ATR bands.
    """
    ema = close.ewm(span=ema_len, adjust=False).mean()
    atr = wilder_atr(high, low, close, atr_len)

    phase = ((close - ema) / (3 * atr * (atr > 0).astype(float) + 1e-10)) * 100
    phase = phase.clip(-100, 100)

    # Bollinger Bands on close
    bb_mid = close.rolling(bb_len).mean()
    bb_std_val = close.rolling(bb_len).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val
    bb_width = bb_upper - bb_lower

    # ATR bands width
    atr_band_width = 2 * atr

    # Compression when BB width < ATR band width
    is_compression = (bb_width < atr_band_width).fillna(False)

    return phase, is_compression


def volume_stack(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Saty Volume Stack.
    Returns (buy_vol, sell_vol, buy_pct).
    buy_vol = volume * (close - low) / (high - low)
    sell_vol = volume * (high - close) / (high - low)
    """
    hl_range = (high - low).replace(0, np.nan)
    buy_vol = volume * (close - low) / hl_range
    sell_vol = volume * (high - close) / hl_range
    buy_vol = buy_vol.fillna(volume * 0.5)
    sell_vol = sell_vol.fillna(volume * 0.5)
    total = buy_vol + sell_vol
    buy_pct = (buy_vol / total.replace(0, np.nan) * 100).fillna(50.0)
    return buy_vol, sell_vol, buy_pct


def keltner_channels(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    sma_len: int = 20,
    atr_factor: float = 1.5
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Keltner Channel (used by OB_OMEGA and KMaster scripts).
    Returns (upper, basis, lower).
    Basis = SMA(20), ATR = SMA of True Range.
    """
    basis = close.rolling(sma_len).mean()
    atr = sma_atr(high, low, close, sma_len)
    upper = basis + atr_factor * atr
    lower = basis - atr_factor * atr
    return upper, basis, lower


def ib_levels(
    high: pd.Series,
    low: pd.Series,
    timestamps: pd.DatetimeIndex,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    ib_minutes: int = 60
) -> pd.DataFrame:
    """
    Initial Balance levels for each trading day.
    Returns DataFrame indexed by date with IB levels.
    """
    if not isinstance(timestamps, pd.DatetimeIndex):
        timestamps = pd.DatetimeIndex(timestamps)

    df = pd.DataFrame({
        'high': high.values,
        'low': low.values,
        'ts': timestamps
    })
    df['date'] = df['ts'].dt.date
    df['time_min'] = df['ts'].dt.hour * 60 + df['ts'].dt.minute

    open_min = market_open_hour * 60 + market_open_minute
    close_min = open_min + ib_minutes

    ib_data = {}
    for date, group in df.groupby('date'):
        ib_bars = group[(group['time_min'] >= open_min) & (group['time_min'] < close_min)]
        if len(ib_bars) == 0:
            continue
        ib_high = ib_bars['high'].max()
        ib_low = ib_bars['low'].min()
        ib_range = ib_high - ib_low
        ib_data[date] = {
            'ib_high': ib_high,
            'ib_low': ib_low,
            'ib_range': ib_range,
            'quad_25': ib_low + 0.25 * ib_range,
            'quad_50': ib_low + 0.50 * ib_range,
            'quad_75': ib_low + 0.75 * ib_range,
            'ext_50_up': ib_high + 0.50 * ib_range,
            'ext_100_up': ib_high + 1.00 * ib_range,
            'ext_300_up': ib_high + 3.00 * ib_range,
            'ext_50_down': ib_low - 0.50 * ib_range,
            'ext_100_down': ib_low - 1.00 * ib_range,
            'ext_300_down': ib_low - 3.00 * ib_range,
        }

    return pd.DataFrame.from_dict(ib_data, orient='index')


def cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 50
) -> pd.Series:
    """
    Commodity Channel Index (CCI).
    Used by shared_mtftrendbar script with period=50.
    Zero-cross = trend direction change.
    """
    typical = (high + low + close) / 3
    ma = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    result = (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))
    return result.fillna(0)


def atr_fib_levels(
    prior_close: float,
    atr: float,
    ratios: Optional[List[float]] = None
) -> Dict[str, float]:
    """
    ATR Fibonacci levels from prior close (Saty ATR Levels script).
    Returns flat dict with both up and down levels.
    """
    if ratios is None:
        ratios = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.236, 1.5, 2.0, 3.0]

    result = {}
    for r in ratios:
        key = str(r)
        result[f"up_{key}"] = prior_close + r * atr
        result[f"down_{key}"] = prior_close - r * atr
    return result


def range_consumed_pct(
    current_price: float,
    prior_close: float,
    atr: float
) -> float:
    """
    How much of the daily ATR range has been consumed.
    < 70% = room to run, > 90% = exhausted.
    """
    if atr <= 0:
        return 0.0
    return min(200.0, abs(current_price - prior_close) / atr * 100)


def ema_ribbon(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    EMA Ribbon (8/21/34) from Saty ATR Levels script.
    Returns (ema_8, ema_21, ema_34).
    All up = bullish, all down = bearish, mixed = neutral.
    """
    ema_8 = close.ewm(span=8, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_34 = close.ewm(span=34, adjust=False).mean()
    return ema_8, ema_21, ema_34
```

---

## backtest/signals.py

### Purpose

`signals.py` is the signal orchestration layer that composes all indicators from `indicators.py` into the 5-layer Tony Stark trading framework. The `compute_all_indicators` function runs every indicator across a full OHLCV DataFrame and appends the results as new columns, including the Layer 2 Structure Map columns (VPOC, Value Area High/Low, Initial Balance proxies). The four layer functions (`layer1_regime`, `layer2_structure`, `layer3_bias`, `layer4_entry`) each consume a single row and emit a categorical signal — regime classification, auction-theory structure position, directional bias from indicator voting, and entry timing respectively. The top-level `generate_signals` function wires all four layers together row-by-row and also computes ATR-based stop/target levels using grid-search-optimized parameters (0.5 ATR stop, 2.0/2.618/4.0 ATR targets yielding 4:1 R:R). Layer 2's structure-aware upgrades in `layer4_entry` allow unconditional `ENTRY_NOW` signals when price has accepted above Value Area High and Initial Balance High simultaneously.

### Key Functions / Classes

| Name | Type | Purpose |
|------|------|---------|
| `compute_all_indicators` | function | Runs all TOS indicators on a full DataFrame; returns df with ~30 new indicator columns |
| `layer1_regime` | function | Classifies market regime: TRENDING_BULL, TRENDING_BEAR, COMPRESSION, EXHAUSTED, RANGE_BOUND |
| `layer2_structure` | function | Maps price to auction-theory structure: BUYER_CONTROL, SELLER_CONTROL, NEUTRAL_STRUCTURE |
| `layer3_bias` | function | 4-indicator vote (KAMA, STC, Volume, EMA) yields: STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR |
| `layer4_entry` | function | Entry timing: ENTRY_NOW (structure breakout or STC cross), WAIT_FOR_PULLBACK, NO_TRADE, FADE_EXTREME |
| `generate_signals` | function | Master function: runs all layers, adds stop_level/target_1/target_2/target_3 columns |

### Source Code

```python
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
    df['stc_val'] = stc(df['close'], fast=23, slow=50, k_period=10, d_period=3)

    def _stc_signal(row):
        val = row['stc_val']
        prev_val = row.get('stc_prev', 50)
        if val < 23:   # Optimized: 23 outperforms TOS default of 19 (deeper confirmation)
            return 'oversold'
        elif val > 83:  # Optimized: 83 outperforms TOS default of 88 (earlier overbought exit)
            return 'overbought'
        elif val > prev_val:
            return 'rising'
        elif val < prev_val:
            return 'falling'
        return 'neutral'

    df['stc_prev'] = df['stc_val'].shift(1).fillna(50)
    df['stc_signal'] = df.apply(_stc_signal, axis=1)
    df['stc_cross_up'] = (df['stc_val'] > 19) & (df['stc_prev'] <= 19)
    df['stc_cross_down'] = (df['stc_val'] < 88) & (df['stc_prev'] >= 88)

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

    # Optimized parameters (grid search 162 combos on SPY+MES 2024):
    # Stop: 0.5 ATR (balanced — SPY prefers 0.7, MES prefers 0.3)
    # T1:   2.0 ATR  (optimized: was 1.0, R:R improves from 2.0 to 4.0)
    # T2:   2.618 ATR (golden extension from new T1)
    # T3:   4.0 ATR  (runner target — let winners run)
    df['stop_level'] = np.where(
        is_long,
        close - 0.5 * atr,    # long stop: 0.5 ATR below entry
        close + 0.5 * atr     # short stop: 0.5 ATR above entry
    )
    df['target_1'] = np.where(
        is_long,
        close + 2.0 * atr,    # T1: 2 ATR (R:R = 4.0) — optimized from 1.0
        close - 2.0 * atr
    )
    df['target_2'] = np.where(
        is_long,
        close + 2.618 * atr,  # T2: 2.618 ATR (golden ratio extension)
        close - 2.618 * atr
    )
    df['target_3'] = np.where(
        is_long,
        close + 4.0 * atr,    # T3: 4 ATR (runner — maximum extension)
        close - 4.0 * atr
    )

    return df
```

---

## backtest/backtester.py

### Purpose

`backtester.py` implements a complete event-driven walk-forward backtesting engine for the 5-layer signal strategy. The `Trade` dataclass captures the full lifecycle of a position including multi-tranche exit tracking (T1/T2/T3 contracts), regime and bias context at entry, and a `to_dict` serializer for JSON output. The `BacktestResult` dataclass accumulates all completed trades and computes a comprehensive suite of performance metrics including Sharpe, Sortino, max drawdown, profit factor, win rate, and consecutive win/loss streaks via the `_calculate_metrics` helper. The `Backtester.run` method simulates bar-by-bar execution with a kill switch that halts trading on daily loss or drawdown breach, position sizing via the `_calculate_contracts` method (risk-dollars / stop-distance / multiplier), and automatic breakeven stop management after Target 1 is hit. Exits are prioritized as stop first, then T1, T2, and end-of-data close-out, with 50%/30%/20% contract allocation across the three target tranches.

### Key Functions / Classes

| Name | Type | Purpose |
|------|------|---------|
| `Trade` | dataclass | Single trade record: entry/exit dates, prices, P&L, exit reason, regime/bias context |
| `Trade.to_dict` | method | Serializes trade to JSON-compatible dict |
| `BacktestResult` | dataclass | Aggregated backtest output: all trades, metrics, equity curve |
| `BacktestResult.summary` | method | Human-readable one-screen performance summary string |
| `BacktestResult.to_dict` | method | Full JSON-serializable result including all trades |
| `Backtester` | class | Event-driven walk-forward simulator with configurable risk parameters |
| `Backtester.run` | method | Main simulation loop: bar-by-bar signal processing, trade management, kill switch |
| `Backtester._calculate_contracts` | method | Position sizing: (capital x risk%) / (stop_distance x multiplier), capped at 50 |
| `Backtester._calculate_metrics` | method | Fills all BacktestResult metric fields from completed trades list |

### Source Code

```python
"""
JARVIS TRADER — Event-Driven Backtester
Walk-forward simulation of the 5-layer trading strategy.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime, date


@dataclass
class Trade:
    """A single completed or open trade."""
    entry_date: datetime
    symbol: str
    direction: str  # "long"/"short"
    entry_price: float
    stop_price: float
    target_1: float
    target_2: float
    contracts: int
    multiplier: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # "target_1"/"target_2"/"target_3"/"stop"/"eod"
    holding_bars: int = 0
    regime: str = ""
    bias: str = ""

    def to_dict(self) -> dict:
        return {
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "contracts": self.contracts,
            "multiplier": self.multiplier,
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "exit_reason": self.exit_reason,
            "holding_bars": self.holding_bars,
            "regime": self.regime,
            "bias": self.bias,
        }


@dataclass
class BacktestResult:
    """Complete results of a backtest run."""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    trades: List[Trade] = field(default_factory=list)

    # Metrics (computed after simulation)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_dollars: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    equity_curve: List[float] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable one-screen summary."""
        lines = [
            f"=== BACKTEST RESULTS: {self.symbol} ===",
            f"Period: {self.start_date} -> {self.end_date}",
            f"Capital: ${self.initial_capital:,.0f} -> ${self.final_capital:,.0f}",
            f"Return: {self.total_return_pct:+.1f}%  |  Max DD: {self.max_drawdown_pct:.1f}%",
            f"",
            f"Trades: {self.total_trades} total  |  Win Rate: {self.win_rate:.1%}",
            f"Avg Win: ${self.avg_win:,.0f}  |  Avg Loss: ${self.avg_loss:,.0f}",
            f"Profit Factor: {self.profit_factor:.2f}",
            f"Sharpe: {self.sharpe_ratio:.2f}  |  Sortino: {self.sortino_ratio:.2f}",
            f"Max Consec. Losses: {self.max_consecutive_losses}  |  Wins: {self.max_consecutive_wins}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "profit_factor": round(self.profit_factor, 3),
            "total_pnl": round(self.total_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_dollars": round(self.max_drawdown_dollars, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "avg_win_loss_ratio": round(self.avg_win_loss_ratio, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_consecutive_wins": self.max_consecutive_wins,
            "equity_curve": [round(v, 2) for v in self.equity_curve],
            "trades": [t.to_dict() for t in self.trades],
        }


class Backtester:
    """Event-driven walk-forward backtester."""

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.02,
        max_drawdown: float = 0.05,
        t1_exit_pct: float = 0.50,  # % to exit at target 1
        t2_exit_pct: float = 0.30,  # % to exit at target 2
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_drawdown = max_drawdown
        self.t1_exit_pct = t1_exit_pct
        self.t2_exit_pct = t2_exit_pct

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 1.0
    ) -> BacktestResult:
        """
        Walk-forward simulation. df must have signals from generate_signals().
        Required columns: open, high, low, close, entry_signal, bias,
                         stop_level, target_1, target_2, target_3, regime
        """
        capital = self.initial_capital
        high_water_mark = capital
        completed_trades: List[Trade] = []
        equity_curve = [capital]

        open_trade: Optional[Trade] = None
        open_contracts_t1 = 0
        open_contracts_t2 = 0
        open_contracts_t3 = 0

        daily_start_capital = capital
        current_date = None
        kill_switch = False

        for idx, row in df.iterrows():
            row_date = idx.date() if hasattr(idx, 'date') else None

            # Reset daily tracking
            if row_date != current_date:
                current_date = row_date
                daily_start_capital = capital
                kill_switch = False

            # Check kill switch
            daily_pnl_pct = (capital - daily_start_capital) / daily_start_capital
            drawdown_pct = (capital - high_water_mark) / high_water_mark

            if daily_pnl_pct < -self.max_daily_loss or drawdown_pct < -self.max_drawdown:
                kill_switch = True

            # -- Manage open trade -------------------------------------------------
            if open_trade is not None:
                open_trade.holding_bars += 1
                high = row['high']
                low = row['low']
                close = row['close']

                # Check stop
                if open_trade.direction == 'long' and low <= open_trade.stop_price:
                    exit_price = open_trade.stop_price
                    remaining = open_contracts_t3
                    pnl = remaining * (exit_price - open_trade.entry_price) * multiplier
                    capital += pnl
                    open_trade.exit_price = exit_price
                    open_trade.exit_date = idx
                    open_trade.pnl += pnl
                    open_trade.exit_reason = "stop"
                    completed_trades.append(open_trade)
                    open_trade = None
                    open_contracts_t3 = 0

                elif open_trade.direction == 'short' and high >= open_trade.stop_price:
                    exit_price = open_trade.stop_price
                    remaining = open_contracts_t3
                    pnl = remaining * (open_trade.entry_price - exit_price) * multiplier
                    capital += pnl
                    open_trade.exit_price = exit_price
                    open_trade.exit_date = idx
                    open_trade.pnl += pnl
                    open_trade.exit_reason = "stop"
                    completed_trades.append(open_trade)
                    open_trade = None
                    open_contracts_t3 = 0

                elif open_trade is not None:
                    # Check target 1
                    if open_contracts_t1 > 0:
                        if (open_trade.direction == 'long' and high >= open_trade.target_1) or \
                           (open_trade.direction == 'short' and low <= open_trade.target_1):
                            exit_price = open_trade.target_1
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t1 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t1 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_contracts_t1 = 0
                            # Move stop to breakeven
                            open_trade.stop_price = open_trade.entry_price

                    # Check target 2
                    if open_contracts_t2 > 0:
                        if (open_trade.direction == 'long' and high >= open_trade.target_2) or \
                           (open_trade.direction == 'short' and low <= open_trade.target_2):
                            exit_price = open_trade.target_2
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t2 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t2 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_contracts_t2 = 0

                    # End of day: close any remaining open position
                    # (simplified: no overnight holding for intraday backtest)
                    if open_contracts_t3 > 0 and open_trade is not None:
                        next_idx = df.index.get_loc(idx)
                        is_last_bar = (next_idx == len(df) - 1)
                        if is_last_bar:
                            exit_price = close
                            if open_trade.direction == 'long':
                                pnl = open_contracts_t3 * (exit_price - open_trade.entry_price) * multiplier
                            else:
                                pnl = open_contracts_t3 * (open_trade.entry_price - exit_price) * multiplier
                            capital += pnl
                            open_trade.pnl += pnl
                            open_trade.exit_price = exit_price
                            open_trade.exit_date = idx
                            open_trade.exit_reason = "eod"
                            completed_trades.append(open_trade)
                            open_trade = None
                            open_contracts_t3 = 0

            # -- Check for new entry signal ----------------------------------------
            if open_trade is None and not kill_switch:
                entry_sig = row.get('entry_signal', 'NO_TRADE')
                bias = row.get('bias', 'NEUTRAL')

                if entry_sig == 'ENTRY_NOW' and bias not in ('NEUTRAL',):
                    direction = 'long' if 'BULL' in bias else 'short'
                    entry_price = row['close']  # next bar open would be more realistic
                    stop_price = row.get('stop_level', entry_price * 0.99)
                    target_1 = row.get('target_1', entry_price * 1.01)
                    target_2 = row.get('target_2', entry_price * 1.02)
                    target_3 = row.get('target_3', entry_price * 1.03)

                    stop_dist = abs(entry_price - stop_price)
                    if stop_dist <= 0:
                        continue

                    # R:R check
                    rr = abs(target_1 - entry_price) / stop_dist
                    if rr < 1.5:
                        continue

                    total_contracts = self._calculate_contracts(
                        capital, entry_price, stop_price, multiplier
                    )
                    if total_contracts < 1:
                        continue

                    t1_contracts = max(1, int(total_contracts * self.t1_exit_pct))
                    t2_contracts = max(0, int(total_contracts * self.t2_exit_pct))
                    t3_contracts = max(0, total_contracts - t1_contracts - t2_contracts)

                    open_contracts_t1 = t1_contracts
                    open_contracts_t2 = t2_contracts
                    open_contracts_t3 = t3_contracts

                    open_trade = Trade(
                        entry_date=idx,
                        symbol=symbol,
                        direction=direction,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_1=target_1,
                        target_2=target_2,
                        contracts=total_contracts,
                        multiplier=multiplier,
                        regime=row.get('regime', ''),
                        bias=bias,
                    )

            # Update equity curve
            equity_curve.append(capital)
            if capital > high_water_mark:
                high_water_mark = capital

        result = BacktestResult(
            symbol=symbol,
            start_date=str(df.index[0].date()) if len(df) > 0 else "",
            end_date=str(df.index[-1].date()) if len(df) > 0 else "",
            initial_capital=self.initial_capital,
            final_capital=capital,
            trades=completed_trades,
            equity_curve=equity_curve,
        )

        return self._calculate_metrics(result)

    def _calculate_contracts(
        self,
        capital: float,
        entry: float,
        stop: float,
        multiplier: float
    ) -> int:
        """contracts = (capital x risk%) / (stop_distance x multiplier)"""
        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or multiplier <= 0:
            return 0
        risk_dollars = capital * self.risk_per_trade
        contracts = risk_dollars / (stop_dist * multiplier)
        return max(0, min(int(contracts), 50))  # cap at 50

    def _calculate_metrics(self, result: BacktestResult) -> BacktestResult:
        """Fill in all metrics from the trades list."""
        trades = result.trades
        if not trades:
            return result

        result.total_trades = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = len(wins) / len(trades) if trades else 0.0
        result.gross_profit = sum(t.pnl for t in wins)
        result.gross_loss = sum(t.pnl for t in losses)
        result.profit_factor = (
            result.gross_profit / abs(result.gross_loss)
            if result.gross_loss != 0 else float('inf')
        )
        result.total_pnl = result.gross_profit + result.gross_loss
        result.total_return_pct = result.total_pnl / result.initial_capital

        result.avg_win = result.gross_profit / len(wins) if wins else 0.0
        result.avg_loss = result.gross_loss / len(losses) if losses else 0.0
        result.avg_win_loss_ratio = (
            abs(result.avg_win / result.avg_loss) if result.avg_loss != 0 else 0.0
        )

        # Max drawdown from equity curve
        equity = np.array(result.equity_curve)
        if len(equity) > 1:
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            result.max_drawdown_pct = float(abs(dd.min()))
            result.max_drawdown_dollars = float(abs((equity - peak).min()))

        # Sharpe and Sortino (simplified, using trade P&L)
        pnls = np.array([t.pnl for t in trades])
        if len(pnls) > 1 and pnls.std() > 0:
            result.sharpe_ratio = float(
                (pnls.mean() / pnls.std()) * np.sqrt(252 / max(1, len(trades) / 252))
            )
            downside = pnls[pnls < 0]
            downside_std = downside.std() if len(downside) > 1 else 1.0
            if downside_std > 0:
                result.sortino_ratio = float(pnls.mean() / downside_std * np.sqrt(252))

        # Consecutive wins/losses
        max_consec_win = max_consec_loss = 0
        cur_win = cur_loss = 0
        for t in trades:
            if t.pnl > 0:
                cur_win += 1
                cur_loss = 0
                max_consec_win = max(max_consec_win, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                max_consec_loss = max(max_consec_loss, cur_loss)
        result.max_consecutive_wins = max_consec_win
        result.max_consecutive_losses = max_consec_loss

        return result
```

---

## backtest/data_loader.py

### Purpose

`data_loader.py` provides the `BacktestDataLoader` class, which fetches historical OHLCV data from Yahoo Finance via the `yfinance` library and transparently caches results to disk as CSV files to avoid rate limits on repeated backtest runs. It maintains a `FUTURES_MAP` dict that translates internal micro-futures symbols (MES, MNQ, MCL, etc.) to their yfinance continuous contract tickers (ES=F, NQ=F, CL=F), and a `CONTRACT_MULTIPLIERS` dict for dollar-per-point position sizing. The `load` method implements a two-stage fetch strategy: primary via `yf.download` and fallback via `Ticker.history()` if the primary fails, with robust handling of both flat and MultiIndex column formats introduced in yfinance 0.2.x. The `load_multi` method batches multiple symbols and returns a symbol-keyed dict, while `get_multiplier` provides the contract multiplier lookup used by the backtester for P&L calculations.

### Key Functions / Classes

| Name | Type | Purpose |
|------|------|---------|
| `FUTURES_MAP` | module-level dict | Maps micro/standard futures symbols to yfinance continuous contract tickers |
| `CONTRACT_MULTIPLIERS` | module-level dict | Dollar-per-point multipliers for all supported futures and ETFs |
| `BacktestDataLoader` | class | Main data loader with caching, symbol mapping, and fallback fetch |
| `BacktestDataLoader.load` | method | Single symbol fetch with disk cache; returns normalized OHLCV DataFrame |
| `BacktestDataLoader.load_multi` | method | Batch load multiple symbols; returns {symbol: DataFrame} dict |
| `BacktestDataLoader.get_multiplier` | method | Returns contract multiplier for a given symbol (defaults to 1.0 for equities) |
| `BacktestDataLoader._cache_path` | method | Constructs filesystem-safe cache file path from symbol + date range + interval |

### Source Code

```python
"""
JARVIS TRADER — Backtest Data Loader
Fetches historical OHLCV data via yfinance with futures symbol mapping.
Results are cached to disk to avoid Yahoo Finance rate limits on repeated runs.
"""
from __future__ import annotations
import yfinance as yf
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


FUTURES_MAP: Dict[str, str] = {
    # Micro futures → yfinance continuous contract
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MCL": "CL=F",
    "MGC": "GC=F",
    "M2K": "RTY=F",
    "MYM": "YM=F",
    # Standard futures
    "ES": "ES=F",
    "NQ": "NQ=F",
    "CL": "CL=F",
    "GC": "GC=F",
    "RTY": "RTY=F",
    "YM": "YM=F",
    "SI": "SI=F",
    "ZB": "ZB=F",
    "ZN": "ZN=F",
}

CONTRACT_MULTIPLIERS: Dict[str, float] = {
    "MES": 5.0,    # $5 per point
    "ES": 50.0,    # $50 per point
    "MNQ": 2.0,    # $2 per point
    "NQ": 20.0,    # $20 per point
    "MCL": 100.0,  # $100 per barrel (micro = 100 barrels)
    "CL": 1000.0,  # $1000 per barrel
    "MGC": 10.0,   # $10 per oz
    "GC": 100.0,   # $100 per oz
    "M2K": 5.0,    # $5 per point
    "RTY": 50.0,   # $50 per point
    "MYM": 0.5,    # $0.50 per point
    "YM": 5.0,     # $5 per point
    # ETFs (no multiplier)
    "SPY": 1.0,
    "QQQ": 1.0,
    "IWM": 1.0,
}


class BacktestDataLoader:
    """Load historical OHLCV data for backtesting."""

    def _cache_path(self, symbol: str, start: str, end: str, interval: str) -> Path:
        safe = f"{symbol}_{start}_{end}_{interval}".replace("/", "-").replace(":", "-")
        return CACHE_DIR / f"{safe}.csv"

    def load(
        self,
        symbol: str,
        start: str,
        end: str,
        interval: str = "1d"
    ) -> Optional[pd.DataFrame]:
        """
        Load OHLCV data for a symbol.
        Maps futures symbols to yfinance format automatically.
        Returns DataFrame with lowercase columns: open, high, low, close, volume, timestamp.
        Caches results to disk to avoid Yahoo Finance rate limits on repeated runs.
        """
        cache_file = self._cache_path(symbol, start, end, interval)
        if cache_file.exists():
            try:
                df = pd.read_csv(cache_file, parse_dates=["timestamp"])
                df = df.set_index("timestamp")
                df.index = pd.to_datetime(df.index)
                df["timestamp"] = df.index
                print(f"[DataLoader] Cache hit: {cache_file.name} ({len(df)} bars)")
                return df
            except Exception as e:
                print(f"[DataLoader] Cache read failed ({e}), re-fetching...")

        ticker = FUTURES_MAP.get(symbol.upper(), symbol)

        raw = None
        try:
            raw = yf.download(
                ticker,
                start=start,
                end=end,
                interval=interval,
                progress=False,
                auto_adjust=True
            )
        except Exception as e:
            print(f"[DataLoader] yf.download failed ({e}), retrying via Ticker.history...")

        # Fallback: Ticker.history() uses a different code path — avoids some rate limits
        if raw is None or raw.empty:
            try:
                t = yf.Ticker(ticker)
                raw = t.history(start=start, end=end, interval=interval, auto_adjust=True)
            except Exception as e2:
                print(f"[DataLoader] Ticker.history also failed: {e2}")
                return None

        if raw is None or raw.empty:
            print(f"[DataLoader] No data returned for {ticker} ({start} to {end})")
            return None

        # Normalize columns — handle both flat and MultiIndex (yfinance >= 0.2.x)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0].lower() for c in raw.columns]
        else:
            raw.columns = [c.lower() if isinstance(c, str) else str(c).lower()
                           for c in raw.columns]

        # Ensure standard columns exist
        required = {'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(raw.columns)
        if missing:
            print(f"[DataLoader] Missing columns: {missing}")
            return None

        df = raw[['open', 'high', 'low', 'close', 'volume']].copy()
        df.index = pd.to_datetime(df.index)
        df['timestamp'] = df.index
        df = df.dropna(subset=['open', 'high', 'low', 'close'])

        print(f"[DataLoader] Loaded {len(df)} bars for {symbol} ({ticker})")

        try:
            df.to_csv(cache_file, index=False)
            print(f"[DataLoader] Cached to {cache_file.name}")
        except Exception as e:
            print(f"[DataLoader] Cache write failed (non-fatal): {e}")

        return df

    def load_multi(
        self,
        symbols: List[str],
        start: str,
        end: str,
        interval: str = "1d"
    ) -> Dict[str, pd.DataFrame]:
        """Load multiple symbols. Returns dict of {symbol: DataFrame}."""
        result = {}
        for sym in symbols:
            df = self.load(sym, start, end, interval)
            if df is not None:
                result[sym] = df
        return result

    def get_multiplier(self, symbol: str) -> float:
        """Return contract multiplier for position sizing."""
        return CONTRACT_MULTIPLIERS.get(symbol.upper(), 1.0)
```

---

## 6. `backtest/optimizer.py` — Grid Search Parameter Optimizer {#backtestoptimizerpy}

### Purpose

`optimizer.py` performs exhaustive grid-search optimization over five key trading parameters — STC oversold/overbought thresholds, ATR stop multiplier, ATR target multiplier, and regime filter toggle — against cached historical OHLCV data. It iterates over all parameter combinations (up to 3,125 in full mode or 162 in fast mode), re-computes indicator signals for each combination using internal helpers, then runs the `Backtester` simulator to collect performance metrics. Results are ranked by a composite score that balances profit factor, win rate, Sharpe ratio, total return, and drawdown, and the top five are automatically serialized to `backtest/results/{SYMBOL}_{interval}_optimal_params.json` along with a consensus parameter set derived from the modal value of each parameter across the top-five results. A CLI entry point supports both fast and full grid modes with configurable symbol, date range, interval, and output path.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| `PARAM_GRID` | dict | Full 5-axis parameter grid yielding 3,125 combinations (5 values each across stc_oversold, stc_overbought, atr_stop_mult, atr_target_mult, regime_filter) |
| `FAST_GRID` | dict | Reduced 162-combination grid for quick exploratory runs (3 values per axis) |
| `OptResult` | dataclass | Flat record holding all five parameters plus six performance metrics (trades, win_rate, profit_factor, sharpe, total_return_pct, max_dd_pct) and the composite `score` |
| `_compute_signals()` | function | Re-derives all indicator series (ATR, STC, phase oscillator, EMA ribbon, KAMA, consumed-ATR) and applies the parameterized entry logic to produce `entry_signal`, `stop_level`, `target_1/2/3`, `bias`, and `regime` columns on a copy of the input DataFrame |
| `_run_with_params()` | function | Thin wrapper that calls `_compute_signals()` then instantiates and runs `Backtester`, returning a `BacktestResult` or `None` on exception |
| `_score()` | function | Composite scoring formula: `(PF*0.3 + WR*0.2 + Sharpe*0.3 + Return*0.1) / drawdown * 0.1`; returns -999 for fewer than 3 trades |
| `run_optimization()` | function | Main orchestration entry point: loads data, iterates the grid, collects results, prints ranked table plus per-metric bests, auto-saves top-5 JSON with consensus params, optionally saves full top-N to a user-specified path |
| `main()` | function | argparse CLI parser wiring `--symbol`, `--start`, `--end`, `--interval`, `--full`, `--top`, and `--output` flags into `run_optimization()` |

### Source Code

```python
"""
JARVIS TRADER — Parameter Optimizer
Grid-searches STC thresholds, ATR multiples, and regime filters
against cached backtest data. No live data fetches required.

Usage:
    python -m backtest.optimizer --symbol SPY --start 2024-01-01 --end 2025-01-01
    python -m backtest.optimizer --symbol SPY --interval 1h --start 2024-06-01 --end 2026-03-27

Auto-saves top 5 results to:
    backtest/results/{SYMBOL}_{interval}_optimal_params.json
"""
from __future__ import annotations
import argparse
import itertools
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from backtest.data_loader import BacktestDataLoader
from backtest.indicators import (
    wilder_atr, kama, stc, phase_oscillator,
    ema_ribbon,
)
from backtest.backtester import Backtester, BacktestResult


# ── Parameter grid ────────────────────────────────────────────────────────────

PARAM_GRID = {
    "stc_oversold":    [15, 17, 19, 21, 23],          # default=19
    "stc_overbought":  [83, 85, 88, 90, 92],          # default=88
    "atr_stop_mult":   [0.3, 0.4, 0.5, 0.6, 0.7],    # default=0.5
    "atr_target_mult": [0.8, 1.0, 1.2, 1.5, 2.0],    # default=1.0
    "regime_filter":   [True, False],                  # default=True
}

# Reduced grid for fast runs (comment out to do full grid)
FAST_GRID = {
    "stc_oversold":    [15, 19, 23],
    "stc_overbought":  [83, 88, 92],
    "atr_stop_mult":   [0.3, 0.5, 0.7],
    "atr_target_mult": [1.0, 1.5, 2.0],
    "regime_filter":   [True, False],
}


@dataclass
class OptResult:
    stc_oversold: int
    stc_overbought: int
    atr_stop_mult: float
    atr_target_mult: float
    regime_filter: bool
    trades: int
    win_rate: float
    profit_factor: float
    sharpe: float
    total_return_pct: float
    max_dd_pct: float
    score: float  # composite ranking score


def _compute_signals(
    df: pd.DataFrame,
    stc_oversold: float,
    stc_overbought: float,
    atr_stop_mult: float,
    atr_target_mult: float,
    regime_filter: bool,
) -> pd.DataFrame:
    """Recompute signals with given parameters."""
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    atr_vals   = wilder_atr(high, low, close, 14)
    stc_vals   = stc(close, fast=23, slow=50, k_period=10, d_period=3)
    phase_vals, phase_compression = phase_oscillator(close, high, low)
    ema8, ema21, ema34 = ema_ribbon(close)
    # range_consumed_pct takes scalars — compute as series inline
    consumed = ((close - close.shift(1)).abs() / atr_vals.replace(0, float('nan'))) * 100
    kama_vals  = kama(close)

    signals = []
    for i in range(len(df)):
        row = df.iloc[i]
        atr_i  = atr_vals.iloc[i]
        stc_i  = stc_vals.iloc[i]
        phase_i = phase_vals.iloc[i]
        e8, e21, e34 = ema8.iloc[i], ema21.iloc[i], ema34.iloc[i]
        cons = consumed.iloc[i]
        kama_i = kama_vals.iloc[i]

        entry = "NO_TRADE"

        if pd.isna(atr_i) or pd.isna(stc_i):
            signals.append(entry)
            continue

        # Layer 1: Regime filter
        if regime_filter:
            if cons > 90:
                signals.append("NO_TRADE")
                continue
            # Phase compression check (skip if already extended)
            if not pd.isna(phase_i) and abs(phase_i) > 80:
                signals.append("NO_TRADE")
                continue

        # Layer 3: Bias
        bullish_ema = (not pd.isna(e8)) and (not pd.isna(e34)) and (e8 > e21 > e34)
        bearish_ema = (not pd.isna(e8)) and (not pd.isna(e34)) and (e8 < e21 < e34)
        close_above_kama = (not pd.isna(kama_i)) and (row["close"] > kama_i)

        # Layer 4: Entry timing with parameterized STC thresholds
        # Long entry: STC oversold crossover with bullish bias
        if stc_i < stc_oversold and (bullish_ema or close_above_kama):
            entry = "ENTRY_NOW"
        # Short entry: STC overbought crossover with bearish bias
        elif stc_i > stc_overbought and (bearish_ema or not close_above_kama):
            entry = "ENTRY_NOW"

        signals.append(entry)

    df = df.copy()
    df["entry_signal"] = signals
    df["atr"]          = atr_vals.values

    # Columns required by backtester
    df["stop_level"]  = df["close"] - atr_stop_mult * df["atr"]
    df["target_1"]    = df["close"] + atr_target_mult * df["atr"]
    df["target_2"]    = df["close"] + atr_target_mult * 1.618 * df["atr"]
    df["target_3"]    = df["close"] + atr_target_mult * 2.0   * df["atr"]

    # Bias column: derive from EMA ribbon
    ema8_s, ema21_s, ema34_s = ema_ribbon(df["close"])
    bull_mask = (ema8_s > ema21_s) & (ema21_s > ema34_s)
    bear_mask = (ema8_s < ema21_s) & (ema21_s < ema34_s)
    df["bias"] = "NEUTRAL"
    df.loc[bull_mask, "bias"] = "STRONG_BULL"
    df.loc[bear_mask, "bias"] = "STRONG_BEAR"

    # Regime column: simple consumed-ATR proxy
    consumed_s = ((df["close"] - df["close"].shift(1)).abs() / atr_vals.replace(0, float("nan"))) * 100
    df["regime"] = "TRENDING_BULL"
    df.loc[consumed_s > 90, "regime"] = "EXHAUSTED"

    return df


def _run_with_params(
    df_base: pd.DataFrame,
    multiplier: float,
    initial_capital: float,
    **params,
) -> Optional[BacktestResult]:
    """Re-signal and backtest with given parameter set."""
    try:
        df = _compute_signals(df_base, **params)
        backtester = Backtester(
            initial_capital=initial_capital,
            risk_per_trade=0.01,
        )
        return backtester.run(df, "OPT", multiplier)
    except Exception as e:
        return None


def _score(r: BacktestResult) -> float:
    """
    Composite ranking score — balances return, Sharpe, win rate, and trade count.
    Penalizes <3 trades (insufficient sample) and high drawdown.
    """
    if r.total_trades < 3:
        return -999.0
    pf   = min(r.profit_factor, 10.0)       # cap at 10x
    wr   = r.win_rate / 100.0
    sr   = min(r.sharpe_ratio, 20.0)        # cap at 20
    ret  = r.total_return_pct
    dd   = max(r.max_drawdown_pct, 0.001)   # avoid div/0
    return (pf * 0.3 + wr * 0.2 + sr * 0.3 + ret * 0.1) / dd * 0.1


def run_optimization(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    fast: bool = True,
    top_n: int = 10,
    capital: float = 100_000.0,
    output: Optional[str] = None,
) -> list[OptResult]:

    loader = BacktestDataLoader()
    df = loader.load(symbol, start, end, interval)
    if df is None or df.empty:
        print(f"[Optimizer] No data for {symbol}")
        return []

    multiplier = loader.get_multiplier(symbol)
    grid = FAST_GRID if fast else PARAM_GRID

    combos = list(itertools.product(*grid.values()))
    keys   = list(grid.keys())
    total  = len(combos)
    print(f"\n[Optimizer] {symbol} | {len(df)} bars | {total} parameter combinations")
    print("-" * 60)

    results: list[OptResult] = []

    for idx, values in enumerate(combos):
        params = dict(zip(keys, values))

        if (idx + 1) % 20 == 0 or idx == total - 1:
            print(f"  Progress: {idx + 1}/{total}", end="\r")

        r = _run_with_params(df.copy(), multiplier, capital, **params)
        if r is None:
            continue

        score = _score(r)
        results.append(OptResult(
            stc_oversold    = params["stc_oversold"],
            stc_overbought  = params["stc_overbought"],
            atr_stop_mult   = params["atr_stop_mult"],
            atr_target_mult = params["atr_target_mult"],
            regime_filter   = params["regime_filter"],
            trades          = r.total_trades,
            win_rate        = round(r.win_rate, 1),
            profit_factor   = round(min(r.profit_factor, 999.0), 2),
            sharpe          = round(r.sharpe_ratio, 2),
            total_return_pct= round(r.total_return_pct, 3),
            max_dd_pct      = round(r.max_drawdown_pct, 3),
            score           = round(score, 4),
        ))

    print()  # newline after progress
    results.sort(key=lambda x: x.score, reverse=True)
    top = results[:top_n]

    # ── Print results table ────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"OPTIMIZATION RESULTS -- TOP {top_n}: {symbol} ({start} to {end})")
    print(f"{'='*70}")
    header = f"{'Rank':>4}  {'STC_OS':>6}  {'STC_OB':>6}  {'Stop':>5}  {'T1':>5}  {'Regime':>6}  {'Trades':>6}  {'WR%':>5}  {'PF':>6}  {'Sharpe':>6}  {'Ret%':>6}  {'Score':>7}"
    print(header)
    print("-" * 70)
    for i, r in enumerate(top):
        print(
            f"{i+1:>4}  {r.stc_oversold:>6}  {r.stc_overbought:>6}  "
            f"{r.atr_stop_mult:>5.2f}  {r.atr_target_mult:>5.2f}  "
            f"{'ON' if r.regime_filter else 'OFF':>6}  "
            f"{r.trades:>6}  {r.win_rate:>5.1f}  {r.profit_factor:>6.2f}  "
            f"{r.sharpe:>6.2f}  {r.total_return_pct:>6.3f}  {r.score:>7.4f}"
        )

    # ── Identify best parameters per metric ───────────────────────────────
    valid = [r for r in results if r.trades >= 3]
    if valid:
        best_wr  = max(valid, key=lambda x: x.win_rate)
        best_pf  = max(valid, key=lambda x: x.profit_factor)
        best_sr  = max(valid, key=lambda x: x.sharpe)
        best_ret = max(valid, key=lambda x: x.total_return_pct)

        print(f"\n{'-'*70}")
        print("BEST BY INDIVIDUAL METRIC:")
        print(f"  Win Rate:     OS={best_wr.stc_oversold}  OB={best_wr.stc_overbought}  Stop={best_wr.atr_stop_mult}  T1={best_wr.atr_target_mult}  -> {best_wr.win_rate}% WR")
        print(f"  Profit Factor:OS={best_pf.stc_oversold}  OB={best_pf.stc_overbought}  Stop={best_pf.atr_stop_mult}  T1={best_pf.atr_target_mult}  -> PF {best_pf.profit_factor}")
        print(f"  Sharpe:       OS={best_sr.stc_oversold}  OB={best_sr.stc_overbought}  Stop={best_sr.atr_stop_mult}  T1={best_sr.atr_target_mult}  -> {best_sr.sharpe}")
        print(f"  Total Return: OS={best_ret.stc_oversold}  OB={best_ret.stc_overbought}  Stop={best_ret.atr_stop_mult}  T1={best_ret.atr_target_mult}  -> {best_ret.total_return_pct}%")

    # ── Auto-save top 5 to backtest/results/{SYMBOL}_{interval}_optimal_params.json ──
    top5 = results[:5]
    if top5:
        engine_root = Path(__file__).parent.parent
        results_dir = engine_root / "backtest" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        auto_filename = f"{symbol}_{interval}_optimal_params.json"
        auto_path = results_dir / auto_filename

        # Build consensus: modal (most common) value per parameter across top 5
        def _mode(values):
            counts = {}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            return max(counts, key=counts.get)

        consensus = {
            "stc_oversold":    _mode([r.stc_oversold    for r in top5]),
            "stc_overbought":  _mode([r.stc_overbought  for r in top5]),
            "atr_stop_mult":   _mode([r.atr_stop_mult   for r in top5]),
            "atr_target_mult": _mode([r.atr_target_mult for r in top5]),
            "regime_filter":   _mode([r.regime_filter   for r in top5]),
        }

        payload = {
            "symbol":    symbol,
            "interval":  interval,
            "start":     start,
            "end":       end,
            "top_params": [asdict(r) for r in top5],
            "consensus": consensus,
        }
        auto_path.write_text(json.dumps(payload, indent=2))
        print(f"\nTop-5 results saved to: {auto_path}")

    # ── Manual --output flag ───────────────────────────────────────────────────
    if output:
        data = [asdict(r) for r in top]
        Path(output).write_text(json.dumps(data, indent=2))
        print(f"\nResults saved to {output}")

    return top


def main():
    parser = argparse.ArgumentParser(description="JARVIS Parameter Optimizer")
    parser.add_argument("--symbol",   default="SPY")
    parser.add_argument("--start",    default="2024-01-01")
    parser.add_argument("--end",      default="2025-01-01")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--full",     action="store_true", help="Full grid (slow) vs fast grid")
    parser.add_argument("--top",      type=int, default=10)
    parser.add_argument("--output",   default=None, help="Save JSON results")
    args = parser.parse_args()

    run_optimization(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        interval=args.interval,
        fast=not args.full,
        top_n=args.top,
        output=args.output,
    )


if __name__ == "__main__":
    main()
```

---

## 7. `backtest/fetch_intraday.py` — Intraday Data Fetcher {#backtestfetch_intradaypy}

### Purpose

`fetch_intraday.py` is a standalone data acquisition module that retrieves intraday OHLCV bars (1m through 1d intervals) for any symbol and persists them to the `backtest/cache/` directory for downstream use by the backtester and optimizer. It implements a two-tier fetch strategy: it first attempts to pull data from the Polygon.io REST API (when `POLYGON_API_KEY` is configured), which provides unlimited historical depth and avoids rate-limit concerns; if Polygon is unavailable it falls back to yfinance with a chunked approach that respects per-interval maximum day windows (e.g., 60 days per chunk for 1h) and inserts a configurable sleep between chunks to avoid HTTP 429 errors. The module normalizes column names, deduplicates overlapping chunks, drops rows with missing OHLC values, and writes a single CSV keyed by `{symbol}_{interval}_{days}d.csv`; subsequent calls with the same key return the cached file immediately unless `--force` is passed.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| `CHUNK_DAYS` | dict | Maps each interval string to the maximum number of days yfinance can return in a single request (e.g., `"1h": 60`, `"1d": 365`) |
| `SLEEP_SECS` | int | Seconds to sleep between yfinance chunk requests (default 3) to avoid rate limiting |
| `_fetch_via_polygon()` | function | Attempts to fetch the full requested date range in one call via the Polygon.io `list_aggs` endpoint; maps JARVIS interval strings to Polygon timespan/multiplier pairs; resolves futures symbols via `FUTURES_MAP`; returns a normalized DataFrame or `None` on failure/missing key |
| `fetch_intraday()` | function | Primary public entry point: checks cache, tries Polygon, falls back to chunked yfinance with retry logic (up to 3 attempts with exponential back-off on rate-limit errors), concatenates chunks, normalizes and validates columns, writes CSV, returns DataFrame |
| `main()` | function | argparse CLI parser exposing `--symbol`, `--interval`, `--days`, and `--force` flags; prints a summary of bar count and date range on success |

### Source Code

```python
"""
JARVIS TRADER — Intraday Data Fetcher
Fetches intraday (1h, 15m, 5m) data in small chunks to avoid Yahoo Finance
rate limits. Saves to backtest/cache/ for use by backtester and optimizer.

Usage:
    python -m backtest.fetch_intraday --symbol SPY --interval 1h --days 180
    python -m backtest.fetch_intraday --symbol MES --interval 1h --days 730
"""
from __future__ import annotations
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

import os
from backtest.data_loader import FUTURES_MAP, CACHE_DIR

# yfinance max days per chunk per interval
CHUNK_DAYS = {"1m": 7, "5m": 55, "15m": 55, "30m": 55, "1h": 60, "1d": 365}
SLEEP_SECS = 3  # between chunks


def _fetch_via_polygon(
    symbol: str,
    interval: str,
    days: int,
) -> pd.DataFrame | None:
    """
    Fetch intraday data via Polygon.io REST API.
    Requires POLYGON_API_KEY env var or set in engine/.env.
    Free tier: 5 calls/min, unlimited history.
    """
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key or api_key == "your_polygon_key_here":
        return None

    try:
        from polygon import RESTClient
    except ImportError:
        print("[Fetcher] polygon-api-client not installed: pip install polygon-api-client")
        return None

    # Map interval to Polygon timespan/multiplier
    tf_map = {
        "1m":  ("minute", 1),
        "5m":  ("minute", 5),
        "15m": ("minute", 15),
        "30m": ("minute", 30),
        "1h":  ("hour", 1),
        "1d":  ("day", 1),
    }
    timespan, multiplier = tf_map.get(interval, ("hour", 1))
    ticker_sym = FUTURES_MAP.get(symbol.upper(), symbol)

    end   = datetime.now()
    start = end - timedelta(days=days)
    from_date = start.strftime("%Y-%m-%d")
    to_date   = end.strftime("%Y-%m-%d")

    print(f"[Fetcher] Trying Polygon.io for {symbol} ({ticker_sym}) {interval}...")
    try:
        client = RESTClient(api_key)
        bars = []
        for agg in client.list_aggs(
            ticker_sym, multiplier, timespan,
            from_date, to_date, limit=50000,
        ):
            bars.append({
                "timestamp": datetime.fromtimestamp(agg.timestamp / 1000),
                "open":   agg.open,
                "high":   agg.high,
                "low":    agg.low,
                "close":  agg.close,
                "volume": agg.volume,
            })

        if not bars:
            print(f"[Fetcher] Polygon returned no bars for {symbol}")
            return None

        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        df["timestamp"] = df.index
        print(f"[Fetcher] Polygon: {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        print(f"[Fetcher] Polygon failed: {e}")
        return None


def fetch_intraday(
    symbol: str,
    interval: str = "1h",
    days: int = 180,
    force: bool = False,
) -> pd.DataFrame | None:

    ticker_sym = FUTURES_MAP.get(symbol.upper(), symbol)
    cache_file = CACHE_DIR / f"{symbol}_{interval}_{days}d.csv"

    if cache_file.exists() and not force:
        df = pd.read_csv(cache_file, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        df.index = pd.to_datetime(df.index)
        df["timestamp"] = df.index
        print(f"[Fetcher] Cache hit: {cache_file.name} ({len(df)} bars)")
        return df

    # Try Polygon first (no rate limit issues, unlimited history)
    df = _fetch_via_polygon(symbol, interval, days)
    if df is not None and not df.empty:
        df.to_csv(cache_file, index=False)
        print(f"[Fetcher] Saved {len(df)} bars to {cache_file.name}")
        return df

    # Fall back to yfinance (chunked to avoid rate limits)
    chunk = CHUNK_DAYS.get(interval, 60)
    end   = datetime.now()
    start = end - timedelta(days=days)

    all_frames = []
    cursor = start
    total_chunks = (days + chunk - 1) // chunk
    fetched = 0

    print(f"[Fetcher] Fetching {symbol} ({ticker_sym}) {interval} — {days} days in {total_chunks} chunks...")

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk), end)
        start_str = cursor.strftime("%Y-%m-%d")
        end_str   = chunk_end.strftime("%Y-%m-%d")

        for attempt in range(3):
            try:
                t = yf.Ticker(ticker_sym)
                raw = t.history(start=start_str, end=end_str, interval=interval, auto_adjust=True)
                if raw is not None and not raw.empty:
                    all_frames.append(raw)
                    fetched += 1
                    print(f"  chunk {fetched}/{total_chunks}: {start_str}→{end_str} ({len(raw)} bars) ✓")
                else:
                    print(f"  chunk {fetched+1}/{total_chunks}: {start_str}→{end_str} empty — skipping")
                break
            except Exception as e:
                if "Rate" in str(e) or "429" in str(e):
                    wait = 10 * (attempt + 1)
                    print(f"  Rate limited — waiting {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  Error: {e}")
                    break

        cursor = chunk_end + timedelta(days=1)
        if cursor < end:
            time.sleep(SLEEP_SECS)

    if not all_frames:
        print(f"[Fetcher] No data retrieved for {symbol}")
        return None

    df = pd.concat(all_frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()

    # Normalize columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        print(f"[Fetcher] Missing columns: {required - set(df.columns)}")
        return None

    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.to_datetime(df.index)
    df["timestamp"] = df.index
    df = df.dropna(subset=["open", "high", "low", "close"])

    df.to_csv(cache_file, index=False)
    print(f"[Fetcher] Saved {len(df)} bars to {cache_file.name}")
    return df


def main():
    parser = argparse.ArgumentParser(description="JARVIS Intraday Data Fetcher")
    parser.add_argument("--symbol",   default="SPY")
    parser.add_argument("--interval", default="1h", choices=["1m","5m","15m","30m","1h","1d"])
    parser.add_argument("--days",     type=int, default=180, help="How many days back to fetch")
    parser.add_argument("--force",    action="store_true", help="Re-fetch even if cached")
    args = parser.parse_args()

    df = fetch_intraday(args.symbol, args.interval, args.days, args.force)
    if df is not None:
        print(f"\nReady: {len(df)} {args.interval} bars for {args.symbol}")
        print(f"Date range: {df.index[0]} → {df.index[-1]}")
    else:
        print("\nFetch failed — try again when Yahoo Finance rate limit clears")


if __name__ == "__main__":
    main()
```

---

## 8. `backtest/run_backtest.py` — CLI Runner {#backtestrun_backtestpy}

### Purpose

`run_backtest.py` is the command-line entry point for executing a single end-to-end backtest run against a specified symbol and date range. It wires together `BacktestDataLoader`, `generate_signals`, and `Backtester` in a straightforward sequential pipeline: load cached or freshly fetched OHLCV data, compute the full 5-layer signal set, count entry signals, then simulate all trades with configurable initial capital and per-trade risk fraction. Results are always auto-saved as a structured JSON file to `backtest/results/{SYMBOL}_{interval}_{start}_{end}.json` containing canonical top-level fields (`n_trades`, `win_rate`, `profit_factor`, `sharpe`, `total_return`, `trades_list`) plus a `full_metrics` block; an optional `--output` flag writes the raw `to_dict()` payload to any additional path. The module guards against missing imports with a helpful error message directing the user to run from the `engine/` directory.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| `main()` | function | Full CLI orchestration: parses `--symbol`, `--start`, `--end`, `--interval`, `--capital`, `--risk`, and `--output`; loads data via `BacktestDataLoader`; generates signals via `generate_signals`; instantiates and runs `Backtester`; prints result summary; auto-saves structured JSON to `backtest/results/`; optionally saves raw dict to `--output` path |

### Source Code

```python
"""
JARVIS TRADER — Backtest CLI Runner

Usage:
    cd engine
    .venv/Scripts/python -m backtest.run_backtest --symbol SPY --start 2024-01-01 --end 2025-12-31
    .venv/Scripts/python -m backtest.run_backtest --symbol MES --start 2024-01-01 --capital 50000
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="JARVIS TRADER Backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", default="1d", help="Data interval (1d, 1h, 15m, etc.)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital")
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    parser.add_argument("--output", default=None, help="Save JSON results to file")
    args = parser.parse_args()

    print(f"JARVIS TRADER Backtester")
    print(f"Symbol: {args.symbol} | Period: {args.start} -> {args.end}")
    print(f"Capital: ${args.capital:,.0f} | Risk/trade: {args.risk:.1%}")
    print("-" * 50)

    try:
        from backtest.data_loader import BacktestDataLoader
        from backtest.signals import generate_signals
        from backtest.backtester import Backtester
    except ImportError as e:
        print(f"[ERROR] Import failed: {e}")
        print("Make sure you're running from the engine/ directory.")
        sys.exit(1)

    # Load data
    loader = BacktestDataLoader()
    print(f"Loading {args.symbol} data...")
    df = loader.load(args.symbol, args.start, args.end, args.interval)

    if df is None or df.empty:
        print(f"[ERROR] No data returned for {args.symbol}")
        sys.exit(1)

    print(f"Loaded {len(df)} bars. Computing signals...")

    # Generate signals
    df = generate_signals(df)

    entry_count = (df['entry_signal'] == 'ENTRY_NOW').sum()
    print(f"Found {entry_count} ENTRY_NOW signals out of {len(df)} bars.")

    # Run backtest
    multiplier = loader.get_multiplier(args.symbol)
    backtester = Backtester(
        initial_capital=args.capital,
        risk_per_trade=args.risk,
    )

    print("Running simulation...")
    result = backtester.run(df, args.symbol, multiplier)

    # Print summary
    print("\n" + result.summary())

    # Auto-save JSON to backtest/results/
    engine_root = Path(__file__).parent.parent
    results_dir = engine_root / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    auto_filename = f"{args.symbol}_{args.interval}_{args.start}_{args.end}.json"
    auto_path = results_dir / auto_filename

    result_data = result.to_dict()
    # Ensure canonical top-level fields match spec
    json_payload = {
        "symbol": result_data["symbol"],
        "interval": args.interval,
        "start": args.start,
        "end": args.end,
        "n_trades": result_data["total_trades"],
        "win_rate": result_data["win_rate"],
        "profit_factor": result_data["profit_factor"],
        "sharpe": result_data["sharpe_ratio"],
        "total_return": result_data["total_return_pct"],
        "trades_list": [
            {
                "entry_date": t["entry_date"],
                "exit_date": t["exit_date"],
                "pnl": t["pnl"],
            }
            for t in result_data["trades"]
        ],
        # Full metrics included for completeness
        "full_metrics": result_data,
    }

    with open(auto_path, 'w') as f:
        json.dump(json_payload, f, indent=2)
    print(f"\nResults saved to: {auto_path}")

    # Save if --output explicitly requested as well
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        print(f"Results also saved to: {output_path}")

    return result


if __name__ == "__main__":
    main()
```

---
---

## 9. `agents/schemas.py` — Pipeline Schemas & Dataclasses {#agentsschemaspy}

### Purpose

`agents/schemas.py` defines all typed dataclasses and enumerations used for inter-agent communication throughout the 5-stage trading pipeline. It acts as the shared data contract that every agent reads from and writes to, ensuring that outputs from one stage are structurally predictable inputs to the next. The module includes five enums (Action, OrderType, MarketRegime, TrendDirection, EntrySignal), five sub-component dataclasses describing technical indicator state (ATRLevels, IBLevels, TPOData, KeltnerBands, MomentumSignals), and one output dataclass per pipeline stage (TechnicalReport, NewsReport, SocialReport, FundamentalReport, ResearchCase, DebateResult, TradeDecision, RiskDecision, FundDecision). Every dataclass exposes a `to_dict()` method to allow seamless JSON serialization for API responses, dashboard feeds, and audit logs. A top-level helper function `pipeline_summary()` produces a compact one-line human-readable summary of the final FundDecision.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| Action | Enum | BUY / SELL / HOLD / CLOSE / REDUCE — trade direction instruction |
| OrderType | Enum | MARKET / LIMIT / STOP / STOP_LIMIT — order execution type |
| MarketRegime | Enum | TRENDING_BULL / TRENDING_BEAR / RANGE_BOUND / COMPRESSION / EXHAUSTED / UNKNOWN |
| TrendDirection | Enum | STRONG_BULL / LEAN_BULL / NEUTRAL / LEAN_BEAR / STRONG_BEAR |
| EntrySignal | Enum | ENTRY_NOW / WAIT_FOR_PULLBACK / FADE_EXTREME / NO_TRADE |
| ATRLevels | dataclass | ATR-Fibonacci levels computed from prior close; includes EMA 8/21/34 ribbon trend |
| IBLevels | dataclass | Initial Balance (first 60-min RTH range), quad levels, extensions, and current price location |
| TPOData | dataclass | Volume/Time Profile data: POC, VAH, VAL, imbalance, tpo_score, price_location |
| KeltnerBands | dataclass | Multi-timeframe Keltner Channel data (inner/outer/extreme bands) + MACD closed-door signals |
| MomentumSignals | dataclass | All momentum readings: STC, Phase Oscillator, KAMA, Volume Stack, TRIN, VIX, breadth |
| TechnicalReport | dataclass | Stage 1 output from TechnicalAnalyst — full technical picture including regime, trend, entry signal, levels, targets |
| NewsReport | dataclass | Stage 1 output from NewsAnalyst — sentiment score, headlines, macro events, risk events |
| SocialReport | dataclass | Stage 1 output from SocialAnalyst — options flow, put/call ratio, dark pool, sentiment score |
| FundamentalReport | dataclass | Stage 1 output from FundamentalAnalyst — earnings date, economic events, sector strength, macro bias |
| ResearchCase | dataclass | Stage 2 output from Bull/Bear researchers — directional thesis, signal lists, price target, stop, signal count |
| DebateResult | dataclass | Stage 2 output from Debate agent — bull/bear scores, winner, recommended action, conviction, rationale |
| TradeDecision | dataclass | Stage 3 output from Trader — action, order type, entry/stop/target prices, R:R, contracts, conviction |
| RiskDecision | dataclass | Stage 4 output from RiskManager — approved flag, modified flag, approved size/stop, kill switch status |
| FundDecision | dataclass | Stage 5 final decision from FundManager — execute flag, portfolio weight, final conviction, human approval flag |
| pipeline_summary() | function | One-line human-readable summary of a FundDecision for logging and notifications |

### Source Code

```python
"""
JARVIS TRADER — Inter-Agent Communication Schemas
Typed dataclasses for the 5-stage trading pipeline.

Pipeline:
  Stage 1 (Analyze): TechnicalAnalyst, NewsAnalyst, SocialAnalyst, FundamentalAnalyst
  Stage 2 (Debate): BullResearcher, BearResearcher → Debate
  Stage 3 (Trade): Trader
  Stage 4 (Risk): RiskManager
  Stage 5 (Fund): FundManager
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


# ── Enums ─────────────────────────────────────────────────────────────────────

class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    REDUCE = "REDUCE"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class MarketRegime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGE_BOUND = "RANGE_BOUND"
    COMPRESSION = "COMPRESSION"
    EXHAUSTED = "EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class TrendDirection(Enum):
    STRONG_BULL = "STRONG_BULL"
    LEAN_BULL = "LEAN_BULL"
    NEUTRAL = "NEUTRAL"
    LEAN_BEAR = "LEAN_BEAR"
    STRONG_BEAR = "STRONG_BEAR"


class EntrySignal(Enum):
    ENTRY_NOW = "ENTRY_NOW"
    WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
    FADE_EXTREME = "FADE_EXTREME"
    NO_TRADE = "NO_TRADE"


# ── Sub-Components ─────────────────────────────────────────────────────────────

@dataclass
class ATRLevels:
    """ATR-Fibonacci levels from Saty ATR Levels script."""
    atr_value: float = 0.0
    prior_close: float = 0.0
    trigger_up: float = 0.0    # prior_close + 0.236 * atr
    trigger_down: float = 0.0  # prior_close - 0.236 * atr
    levels_up: Dict[str, float] = field(default_factory=dict)   # "0.382": price, etc.
    levels_down: Dict[str, float] = field(default_factory=dict)
    range_consumed_pct: float = 0.0  # 0-100+
    ema_8: float = 0.0
    ema_21: float = 0.0
    ema_34: float = 0.0
    ema_trend: str = "neutral"  # "bullish"/"bearish"/"neutral"

    def to_dict(self) -> dict:
        return {
            "atr_value": self.atr_value,
            "prior_close": self.prior_close,
            "trigger_up": self.trigger_up,
            "trigger_down": self.trigger_down,
            "levels_up": self.levels_up,
            "levels_down": self.levels_down,
            "range_consumed_pct": self.range_consumed_pct,
            "ema_8": self.ema_8,
            "ema_21": self.ema_21,
            "ema_34": self.ema_34,
            "ema_trend": self.ema_trend,
        }


@dataclass
class IBLevels:
    """Initial Balance levels from Corey IBv1 script."""
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_range: float = 0.0
    quad_25: float = 0.0
    quad_50: float = 0.0
    quad_75: float = 0.0
    ext_50_up: float = 0.0
    ext_100_up: float = 0.0
    ext_300_up: float = 0.0
    ext_50_down: float = 0.0
    ext_100_down: float = 0.0
    ext_300_down: float = 0.0
    current_price_vs_ib: str = "inside"  # "above"/"below"/"inside"

    def to_dict(self) -> dict:
        return {
            "ib_high": self.ib_high,
            "ib_low": self.ib_low,
            "ib_range": self.ib_range,
            "quad_25": self.quad_25,
            "quad_50": self.quad_50,
            "quad_75": self.quad_75,
            "ext_50_up": self.ext_50_up,
            "ext_100_up": self.ext_100_up,
            "ext_300_up": self.ext_300_up,
            "ext_50_down": self.ext_50_down,
            "ext_100_down": self.ext_100_down,
            "ext_300_down": self.ext_300_down,
            "current_price_vs_ib": self.current_price_vs_ib,
        }


@dataclass
class TPOData:
    """Volume/Time Profile data."""
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    profile_high: float = 0.0
    profile_low: float = 0.0
    va_balance: float = 0.0
    imbalance: str = "balanced"  # "bullish"/"bearish"/"balanced"
    tpo_score: float = 0.0       # -5 to +5 composite
    vpoc_levels: List[float] = field(default_factory=list)
    price_location: str = "in_va"  # "above_vah"/"in_va"/"below_val"

    def to_dict(self) -> dict:
        return {
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "profile_high": self.profile_high,
            "profile_low": self.profile_low,
            "va_balance": self.va_balance,
            "imbalance": self.imbalance,
            "tpo_score": self.tpo_score,
            "vpoc_levels": self.vpoc_levels,
            "price_location": self.price_location,
        }


@dataclass
class KeltnerBands:
    """Multi-timeframe Keltner Channel data."""
    timeframe: str = "5m"
    basis: float = 0.0
    inner_upper: float = 0.0   # +1.5x ATR
    inner_lower: float = 0.0
    outer_upper: float = 0.0   # +2.0x ATR
    outer_lower: float = 0.0
    extreme_upper: float = 0.0  # +3.0x ATR
    extreme_lower: float = 0.0
    macd_closed_door_up: bool = False
    macd_closed_door_down: bool = False

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "basis": self.basis,
            "inner_upper": self.inner_upper,
            "inner_lower": self.inner_lower,
            "outer_upper": self.outer_upper,
            "outer_lower": self.outer_lower,
            "extreme_upper": self.extreme_upper,
            "extreme_lower": self.extreme_lower,
            "macd_closed_door_up": self.macd_closed_door_up,
            "macd_closed_door_down": self.macd_closed_door_down,
        }


@dataclass
class MomentumSignals:
    """All momentum indicator readings."""
    stc_value: float = 50.0
    stc_signal: str = "neutral"  # "oversold"/"overbought"/"rising"/"falling"/"neutral"
    phase_value: float = 0.0
    phase_signal: str = "neutral"  # "compression"/"extended_up"/"extended_down"/"neutral"
    kama_value: float = 0.0
    kama_signal: str = "neutral"  # "long"/"short"/"neutral"
    volume_buy_pct: float = 50.0
    volume_sell_pct: float = 50.0
    volume_signal: str = "balanced"  # "buyer_dominant"/"seller_dominant"/"balanced"
    trin: Optional[float] = None
    vix: Optional[float] = None
    breadth_signal: str = "neutral"  # "capitulation"/"blow_off"/"neutral"

    def to_dict(self) -> dict:
        return {
            "stc_value": self.stc_value,
            "stc_signal": self.stc_signal,
            "phase_value": self.phase_value,
            "phase_signal": self.phase_signal,
            "kama_value": self.kama_value,
            "kama_signal": self.kama_signal,
            "volume_buy_pct": self.volume_buy_pct,
            "volume_sell_pct": self.volume_sell_pct,
            "volume_signal": self.volume_signal,
            "trin": self.trin,
            "vix": self.vix,
            "breadth_signal": self.breadth_signal,
        }


# ── Stage 1 Outputs ────────────────────────────────────────────────────────────

@dataclass
class TechnicalReport:
    """Output of TechnicalAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    timeframe: str = "1d"
    current_price: float = 0.0
    regime: MarketRegime = MarketRegime.UNKNOWN
    trend: TrendDirection = TrendDirection.NEUTRAL
    entry_signal: EntrySignal = EntrySignal.NO_TRADE
    atr_levels: ATRLevels = field(default_factory=ATRLevels)
    ib_levels: IBLevels = field(default_factory=IBLevels)
    tpo_data: TPOData = field(default_factory=TPOData)
    keltner_5m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="5m"))
    keltner_15m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="15m"))
    keltner_30m: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="30m"))
    keltner_4h: KeltnerBands = field(default_factory=lambda: KeltnerBands(timeframe="4h"))
    momentum: MomentumSignals = field(default_factory=MomentumSignals)
    key_support: List[float] = field(default_factory=list)
    key_resistance: List[float] = field(default_factory=list)
    stop_level: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "current_price": self.current_price,
            "regime": self.regime.value,
            "trend": self.trend.value,
            "entry_signal": self.entry_signal.value,
            "atr_levels": self.atr_levels.to_dict(),
            "ib_levels": self.ib_levels.to_dict(),
            "tpo_data": self.tpo_data.to_dict(),
            "keltner_5m": self.keltner_5m.to_dict(),
            "keltner_15m": self.keltner_15m.to_dict(),
            "keltner_30m": self.keltner_30m.to_dict(),
            "keltner_4h": self.keltner_4h.to_dict(),
            "momentum": self.momentum.to_dict(),
            "key_support": self.key_support,
            "key_resistance": self.key_resistance,
            "stop_level": self.stop_level,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class NewsReport:
    """Output of NewsAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    sentiment: str = "neutral"
    sentiment_score: float = 0.0  # -1 to +1
    key_headlines: List[str] = field(default_factory=list)
    macro_events: List[str] = field(default_factory=list)
    risk_events: List[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "key_headlines": self.key_headlines,
            "macro_events": self.macro_events,
            "risk_events": self.risk_events,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class SocialReport:
    """Output of SocialAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    options_flow: str = "neutral"  # "bullish_sweep"/"bearish_sweep"/"neutral"
    put_call_ratio: Optional[float] = None
    dark_pool_activity: str = "neutral"  # "buying"/"selling"/"neutral"
    sentiment_score: float = 0.0  # -1 to +1
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "options_flow": self.options_flow,
            "put_call_ratio": self.put_call_ratio,
            "dark_pool_activity": self.dark_pool_activity,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class FundamentalReport:
    """Output of FundamentalAnalyst agent (Stage 1)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    earnings_date: Optional[str] = None
    economic_events: List[str] = field(default_factory=list)
    sector_strength: str = "neutral"  # "strong"/"weak"/"neutral"
    macro_bias: str = "neutral"       # "bullish"/"bearish"/"neutral"
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "earnings_date": self.earnings_date,
            "economic_events": self.economic_events,
            "sector_strength": self.sector_strength,
            "macro_bias": self.macro_bias,
            "confidence": self.confidence,
            "notes": self.notes,
        }


# ── Stage 2 Outputs ────────────────────────────────────────────────────────────

@dataclass
class ResearchCase:
    """Output of Bull/Bear Researcher agents (Stage 2)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    direction: str = "bull"  # "bull"/"bear"
    thesis: str = ""
    technical_signals: List[str] = field(default_factory=list)
    news_signals: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    price_target: float = 0.0
    stop_level: float = 0.0
    confidence: float = 0.0
    signal_count: int = 0  # how many of 5 layers align

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "thesis": self.thesis,
            "technical_signals": self.technical_signals,
            "news_signals": self.news_signals,
            "risk_factors": self.risk_factors,
            "price_target": self.price_target,
            "stop_level": self.stop_level,
            "confidence": self.confidence,
            "signal_count": self.signal_count,
        }


@dataclass
class DebateResult:
    """Output of Debate agent (Stage 2)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    bull_score: float = 0.0  # 0-10
    bear_score: float = 0.0  # 0-10
    winner: str = "neutral"  # "bull"/"bear"/"neutral"
    margin: float = 0.0
    consensus_direction: TrendDirection = TrendDirection.NEUTRAL
    key_bull_points: List[str] = field(default_factory=list)
    key_bear_points: List[str] = field(default_factory=list)
    recommended_action: Action = Action.HOLD
    conviction: float = 0.0  # 0-1
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bull_score": self.bull_score,
            "bear_score": self.bear_score,
            "winner": self.winner,
            "margin": self.margin,
            "consensus_direction": self.consensus_direction.value,
            "key_bull_points": self.key_bull_points,
            "key_bear_points": self.key_bear_points,
            "recommended_action": self.recommended_action.value,
            "conviction": self.conviction,
            "rationale": self.rationale,
        }


# ── Stage 3 Output ─────────────────────────────────────────────────────────────

@dataclass
class TradeDecision:
    """Output of Trader agent (Stage 3)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    action: Action = Action.HOLD
    order_type: OrderType = OrderType.LIMIT
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    risk_reward: float = 0.0
    suggested_contracts: int = 1
    timeframe: str = "intraday"
    entry_signal_basis: str = ""  # which Layer 4 signal triggered
    conviction: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "order_type": self.order_type.value,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "risk_reward": self.risk_reward,
            "suggested_contracts": self.suggested_contracts,
            "timeframe": self.timeframe,
            "entry_signal_basis": self.entry_signal_basis,
            "conviction": self.conviction,
            "notes": self.notes,
        }


# ── Stage 4 Output ─────────────────────────────────────────────────────────────

@dataclass
class RiskDecision:
    """Output of RiskManager agent (Stage 4)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    approved: bool = False
    modified: bool = False
    original_action: Action = Action.HOLD
    approved_action: Action = Action.HOLD
    approved_contracts: int = 0
    approved_stop: float = 0.0
    approved_target_1: float = 0.0
    max_daily_loss_remaining: float = 0.0
    current_drawdown_pct: float = 0.0
    kill_switch_triggered: bool = False
    rejection_reason: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "approved": self.approved,
            "modified": self.modified,
            "original_action": self.original_action.value,
            "approved_action": self.approved_action.value,
            "approved_contracts": self.approved_contracts,
            "approved_stop": self.approved_stop,
            "approved_target_1": self.approved_target_1,
            "max_daily_loss_remaining": self.max_daily_loss_remaining,
            "current_drawdown_pct": self.current_drawdown_pct,
            "kill_switch_triggered": self.kill_switch_triggered,
            "rejection_reason": self.rejection_reason,
            "notes": self.notes,
        }


# ── Stage 5 Output ─────────────────────────────────────────────────────────────

@dataclass
class FundDecision:
    """Output of FundManager agent (Stage 5 — final go/no-go)."""
    symbol: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    execute: bool = False
    action: Action = Action.HOLD
    contracts: int = 0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    portfolio_weight_pct: float = 0.0
    correlation_check: str = "ok"  # "ok"/"correlated"/"rejected"
    final_conviction: float = 0.0
    execution_notes: str = ""
    human_approval_required: bool = True

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "execute": self.execute,
            "action": self.action.value,
            "contracts": self.contracts,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "portfolio_weight_pct": self.portfolio_weight_pct,
            "correlation_check": self.correlation_check,
            "final_conviction": self.final_conviction,
            "execution_notes": self.execution_notes,
            "human_approval_required": self.human_approval_required,
        }


# ── Helper Functions ───────────────────────────────────────────────────────────

def pipeline_summary(fund_decision: FundDecision) -> str:
    """Return a one-line human-readable summary of the final decision."""
    if not fund_decision.execute:
        return f"[NO TRADE] {fund_decision.symbol} — {fund_decision.execution_notes[:80]}"

    direction = "LONG" if fund_decision.action == Action.BUY else "SHORT"
    approval = "⚠️ NEEDS APPROVAL" if fund_decision.human_approval_required else "✅ AUTO"
    return (
        f"[{approval}] {direction} {fund_decision.contracts}x {fund_decision.symbol} "
        f"@ {fund_decision.entry_price:.2f} | Stop: {fund_decision.stop_price:.2f} | "
        f"T1: {fund_decision.target_1:.2f} | Conviction: {fund_decision.final_conviction:.0%}"
    )
```

---

## 10. `agents/pipeline.py` — Trading Pipeline Orchestration {#agentspipelinepy}

### Purpose

`agents/pipeline.py` implements the `TradingPipeline` class, which is the central orchestrator that wires together all 10 trading agents across the 5 pipeline stages. Each stage is isolated behind a fault-tolerant wrapper: if any agent raises an exception, the pipeline records the error and continues with a safe neutral fallback rather than crashing. Stage 1 runs all four analyst agents concurrently via `asyncio.gather`, dramatically reducing total analysis latency. Stages 2 through 5 run sequentially, with Stage 5 (Fund Manager) only executing if Stage 4 (Risk Manager) grants approval. The `_resolve_final_action` method synthesizes all stage outputs into a single actionable tuple of `(final_action, final_quantity, requires_human)` that callers and the scheduler both consume.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| TradingPipeline | class | Main orchestrator — wires all 10 agents, runs 5-stage pipeline for a symbol |
| `__init__` | method | Accepts agents dict and safety_layer; stores both as instance attributes |
| `analyze_and_decide` | async method | Entry point — runs all 5 stages and returns a complete pipeline_result dict |
| `_run_analysts` | async method | Runs all 4 Stage 1 analysts concurrently via asyncio.gather with per-agent error isolation |
| `_call_agent_analyze` | async method | Delegates to a named agent's analyze() method; returns neutral dict if agent absent |
| `_run_debate` | async method | Runs Stage 2 bull/bear debate; returns neutral verdict if debate agents absent or failed |
| `_run_trader` | async method | Runs Stage 3 Trader agent; returns HOLD decision dict on failure |
| `_run_risk_manager` | async method | Runs Stage 4 Risk Manager; auto-vetoes (returns approved=False) on exception for safety |
| `_run_fund_manager` | async method | Runs Stage 5 Fund Manager; approves conservatively at min size with human approval on failure |
| `_get_portfolio` | async method | Retrieves portfolio state from optional portfolio provider agent; falls back to safe defaults |
| `_resolve_final_action` | method | Converts stage outputs into (final_action, final_quantity, requires_human) tuple |

### Source Code

```python
"""
JARVIS TRADER — Trading Pipeline
===================================
Orchestrates the complete multi-agent analysis and decision pipeline for a symbol.

Pipeline order:
  1. Analyst stage (parallel):  technical, news, social, fundamental
  2. Debate stage:               bull agent + bear agent → debate orchestrator
  3. Trader:                     synthesizes everything → TradeDecision
  4. Risk Manager:               validates TradeDecision → RiskDecision
  5. Fund Manager:               portfolio-level final approval → FundDecision

All intermediate results are preserved in the returned pipeline_result dict
for audit logging, dashboards, and post-trade review.

The pipeline is non-blocking at each stage — if an analyst fails it returns
a neutral/empty report and the pipeline continues. Failures are logged and
captured in pipeline_result["errors"].
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from .schemas import MarketRegime, TrendDirection, EntrySignal, Action

logger = logging.getLogger(__name__)

__all__ = ["TradingPipeline"]


class TradingPipeline:
    """
    Runs the complete multi-agent analysis pipeline for a single symbol.

    Required agents dict keys:
        technical     — TechnicalAnalystAgent
        news          — NewsAnalystAgent
        social        — (any agent with .analyze(symbol) → report with .to_dict())
        fundamental   — (any agent with .analyze(symbol) → report with .to_dict())
        bull          — (any agent with .argue(symbol, analyst_reports) → dict)
        bear          — (any agent with .argue(symbol, analyst_reports) → dict)
        debate        — DebateOrchestrator with .run_debate(bull_arg, bear_arg) → dict
        trader        — TraderAgent
        risk_manager  — RiskManagerAgent
        fund_manager  — FundManagerAgent

    All agents are optional — the pipeline degrades gracefully when absent.
    """

    def __init__(self, agents: dict, safety_layer):
        """
        Args:
            agents:       Dict of named agent instances (see class docstring)
            safety_layer: SafetyLayer instance — provides get_status() and kill switch
        """
        self._agents = agents
        self._safety = safety_layer

    async def analyze_and_decide(
        self,
        symbol: str,
        is_futures: bool = True,
    ) -> dict:
        """
        Run the full pipeline for a symbol.

        Returns a pipeline_result dict containing:
            symbol              str
            is_futures          bool
            started_at          ISO timestamp
            completed_at        ISO timestamp
            analyst_reports     dict (technical, news, social, fundamental)
            debate_result       dict
            trade_decision      dict  (TradeDecision.to_dict())
            risk_decision       dict  (RiskDecision.to_dict())
            fund_decision       dict  (FundDecision.to_dict()) — present if risk approved
            final_action        str   "buy" | "sell" | "hold" | "pending_human_approval"
            final_quantity      int
            requires_human      bool
            errors              list[str]  — any non-fatal errors encountered
        """
        started_at = datetime.now()
        errors: list[str] = []
        pipeline_result: dict[str, Any] = {
            "symbol": symbol,
            "is_futures": is_futures,
            "started_at": started_at.isoformat(),
            "errors": errors,
        }

        logger.info(f"[Pipeline] Starting analysis for {symbol} (futures={is_futures})")

        # ── Stage 1: Analysts in parallel ─────────────────────────────────

        analyst_reports = await self._run_analysts(symbol, is_futures, errors)
        pipeline_result["analyst_reports"] = analyst_reports

        # ── Stage 2: Bull/Bear Debate ──────────────────────────────────────

        debate_result = await self._run_debate(symbol, analyst_reports, errors)
        pipeline_result["debate_result"] = debate_result

        # ── Stage 3: Trader Decision ───────────────────────────────────────

        safety_status = self._safety.get_status()
        trade_decision = await self._run_trader(symbol, debate_result, analyst_reports, safety_status, errors)
        pipeline_result["trade_decision"] = trade_decision

        # ── Stage 4: Risk Manager Review ──────────────────────────────────

        # We always pass an empty portfolio if none is available — callers should
        # inject a real portfolio dict via a wrapper or subclass
        portfolio = await self._get_portfolio()
        risk_decision = await self._run_risk_manager(trade_decision, safety_status, portfolio, errors)
        pipeline_result["risk_decision"] = risk_decision

        # ── Stage 5: Fund Manager (only if Risk Manager approved) ──────────

        fund_decision: Optional[dict] = None
        if risk_decision.get("approved", False):
            open_positions = portfolio.get("positions", [])
            fund_decision = await self._run_fund_manager(
                trade_decision, risk_decision, portfolio, open_positions, errors
            )
        else:
            logger.info(f"[Pipeline] Risk Manager vetoed {symbol} — skipping Fund Manager")

        pipeline_result["fund_decision"] = fund_decision

        # ── Resolve final action ───────────────────────────────────────────

        final_action, final_quantity, requires_human = self._resolve_final_action(
            trade_decision, risk_decision, fund_decision
        )
        pipeline_result["final_action"] = final_action
        pipeline_result["final_quantity"] = final_quantity
        pipeline_result["requires_human"] = requires_human

        completed_at = datetime.now()
        pipeline_result["completed_at"] = completed_at.isoformat()
        elapsed = (completed_at - started_at).total_seconds()

        # ── Human-readable summary line ────────────────────────────────────────
        regime = analyst_reports.get("technical", {}).get("regime", "UNKNOWN")
        trend = analyst_reports.get("technical", {}).get("trend", "UNKNOWN")
        confidence = fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
        pipeline_result["summary"] = (
            f"{symbol} | regime={regime} trend={trend} | "
            f"action={final_action.upper()} qty={final_quantity} | "
            f"conviction={confidence:.0%} human={requires_human}"
        )

        logger.info(
            f"[Pipeline] {symbol} complete in {elapsed:.1f}s — "
            f"final_action={final_action} qty={final_quantity} "
            f"requires_human={requires_human} errors={len(errors)}"
        )

        return pipeline_result

    # ── Stage Runners ──────────────────────────────────────────────────────

    async def _run_analysts(
        self,
        symbol: str,
        is_futures: bool,
        errors: list,
    ) -> dict:
        """Run all four analysts concurrently via asyncio.gather."""

        async def safe_analyze(name: str, coro) -> dict:
            try:
                report = await coro
                # Support both dataclasses with to_dict() and plain dicts
                if hasattr(report, "to_dict"):
                    return report.to_dict()
                elif isinstance(report, dict):
                    return report
                else:
                    return {"signal": 0.0, "confidence": 0.0, "summary": f"{name} returned unexpected type"}
            except Exception as e:
                err = f"{name} analyst failed: {e}"
                logger.warning(f"[Pipeline] {err}")
                errors.append(err)
                return {"signal": 0.0, "confidence": 0.0, "summary": f"{name} unavailable"}

        # Build coroutines — skip missing agents gracefully
        technical_coro = self._call_agent_analyze("technical", symbol, is_futures=is_futures)
        news_coro = self._call_agent_analyze("news", symbol)
        social_coro = self._call_agent_analyze("social", symbol)
        fundamental_coro = self._call_agent_analyze("fundamental", symbol)

        results = await asyncio.gather(
            safe_analyze("technical", technical_coro),
            safe_analyze("news", news_coro),
            safe_analyze("social", social_coro),
            safe_analyze("fundamental", fundamental_coro),
        )

        return {
            "technical": results[0],
            "news": results[1],
            "social": results[2],
            "fundamental": results[3],
        }

    async def _call_agent_analyze(self, agent_name: str, symbol: str, **kwargs):
        """Delegates to the named agent's analyze() method, or returns neutral if absent."""
        agent = self._agents.get(agent_name)
        if agent is None:
            return {"signal": 0.0, "confidence": 0.0, "summary": f"{agent_name} not configured"}
        return await agent.analyze(symbol, **kwargs)

    async def _run_debate(
        self,
        symbol: str,
        analyst_reports: dict,
        errors: list,
    ) -> dict:
        """Run the bull/bear debate. Returns neutral dict on failure."""
        try:
            bull_agent = self._agents.get("bull")
            bear_agent = self._agents.get("bear")
            debate_agent = self._agents.get("debate")

            if not all([bull_agent, bear_agent, debate_agent]):
                logger.debug("[Pipeline] Bull/bear/debate agents not configured — skipping debate")
                return {
                    "verdict": "neutral",
                    "bull_score": 0.5,
                    "bear_score": 0.5,
                    "summary": "Debate agents not configured",
                    "bull_arguments": [],
                    "bear_arguments": [],
                }

            # Debate orchestrator runs bull + bear internally
            debate_result = await debate_agent.run_debate(
                symbol=symbol,
                analyst_reports=analyst_reports,
                bull=bull_agent,
                bear=bear_agent,
            )

            # Normalise to dict
            if hasattr(debate_result, "to_dict"):
                return debate_result.to_dict()
            elif isinstance(debate_result, dict):
                return debate_result
            else:
                return {"verdict": "neutral", "summary": str(debate_result)}

        except Exception as e:
            err = f"Debate stage failed: {e}"
            logger.warning(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "verdict": "neutral",
                "bull_score": 0.5,
                "bear_score": 0.5,
                "summary": "Debate failed — defaulting to neutral",
                "bull_arguments": [],
                "bear_arguments": [],
            }

    async def _run_trader(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
        errors: list,
    ) -> dict:
        """Run the Trader agent. Returns HOLD on failure."""
        try:
            trader = self._agents.get("trader")
            if trader is None:
                logger.warning("[Pipeline] Trader agent not configured")
                return {
                    "symbol": symbol,
                    "action": "hold",
                    "quantity": 0,
                    "order_type": "market",
                    "limit_price": None,
                    "stop_price": None,
                    "time_in_force": "day",
                    "signal_score": 0.0,
                    "confidence": 0.0,
                    "reasoning": "Trader agent not configured",
                    "risk_notes": "Pipeline misconfiguration",
                    "timestamp": datetime.now().isoformat(),
                }

            decision = await trader.decide(symbol, debate_result, analyst_reports, safety_status)
            return decision.to_dict() if hasattr(decision, "to_dict") else decision

        except Exception as e:
            err = f"Trader stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "symbol": symbol,
                "action": "hold",
                "quantity": 0,
                "order_type": "market",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "day",
                "signal_score": 0.0,
                "confidence": 0.0,
                "reasoning": f"Trader agent exception: {e}",
                "risk_notes": "LLM failure — defaulting to HOLD",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_risk_manager(
        self,
        trade_decision: dict,
        safety_status: dict,
        portfolio: dict,
        errors: list,
    ) -> dict:
        """Run the Risk Manager. Approves trivially on failure to avoid blocking holds."""
        try:
            risk_manager = self._agents.get("risk_manager")
            if risk_manager is None:
                logger.warning("[Pipeline] Risk Manager not configured — auto-approving")
                return {
                    "approved": True,
                    "veto_reason": None,
                    "modified_quantity": None,
                    "modified_limit_price": None,
                    "risk_score": 0.5,
                    "reasoning": "Risk Manager not configured — passed without review",
                    "timestamp": datetime.now().isoformat(),
                }

            risk = await risk_manager.review(trade_decision, safety_status, portfolio)
            return risk.to_dict() if hasattr(risk, "to_dict") else risk

        except Exception as e:
            err = f"Risk Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "approved": False,
                "veto_reason": f"Risk Manager exception: {e}",
                "modified_quantity": None,
                "modified_limit_price": None,
                "risk_score": 1.0,
                "reasoning": f"Risk Manager failed with exception: {e}. Defaulting to VETO for safety.",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_fund_manager(
        self,
        trade_decision: dict,
        risk_decision: dict,
        portfolio: dict,
        open_positions: list,
        errors: list,
    ) -> dict:
        """Run the Fund Manager. Approves conservatively on failure."""
        try:
            fund_manager = self._agents.get("fund_manager")
            if fund_manager is None:
                logger.warning("[Pipeline] Fund Manager not configured — auto-approving")
                qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 0)
                return {
                    "approved": True,
                    "final_quantity": int(qty),
                    "priority": "immediate",
                    "portfolio_impact": "Fund Manager not configured — passed without portfolio review",
                    "reasoning": "Fund Manager not configured.",
                    "requires_human_approval": True,
                    "timestamp": datetime.now().isoformat(),
                }

            fund = await fund_manager.approve(trade_decision, risk_decision, portfolio, open_positions)
            return fund.to_dict() if hasattr(fund, "to_dict") else fund

        except Exception as e:
            err = f"Fund Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 1)
            return {
                "approved": True,
                "final_quantity": min(int(qty), 1),
                "priority": "immediate",
                "portfolio_impact": "Fund Manager failed — conservative fallback approval",
                "reasoning": f"Fund Manager exception: {e}. Approved at min size with human approval required.",
                "requires_human_approval": True,
                "timestamp": datetime.now().isoformat(),
            }

    # ── Portfolio Data ─────────────────────────────────────────────────────

    async def _get_portfolio(self) -> dict:
        """
        Retrieve current portfolio state.

        Override this method in a subclass (or inject a portfolio_provider into
        the agents dict as "portfolio") to supply real broker data.
        Falls back to a safe empty portfolio so the pipeline never crashes.
        """
        portfolio_provider = self._agents.get("portfolio")
        if portfolio_provider is not None:
            try:
                if asyncio.iscoroutinefunction(getattr(portfolio_provider, "get_portfolio", None)):
                    return await portfolio_provider.get_portfolio()
                elif callable(getattr(portfolio_provider, "get_portfolio", None)):
                    return portfolio_provider.get_portfolio()
            except Exception as e:
                logger.warning(f"[Pipeline] Portfolio fetch failed: {e}")

        # Safe default — Risk Manager and Fund Manager handle missing data gracefully
        equity = self._safety._current_equity if hasattr(self._safety, "_current_equity") else 10_000.0
        return {
            "total_value": equity,
            "available_cash": equity * 0.5,
            "margin_used_pct": 0.0,
            "daily_pnl": getattr(self._safety, "_daily_realized_pnl", 0.0),
            "open_position_count": 0,
            "positions": [],
        }

    # ── Final Action Resolution ────────────────────────────────────────────

    def _resolve_final_action(
        self,
        trade_decision: dict,
        risk_decision: dict,
        fund_decision: Optional[dict],
    ) -> tuple[str, int, bool]:
        """
        Determine the final pipeline outcome.

        Returns:
            (final_action, final_quantity, requires_human)
        """
        # Risk Manager vetoed
        if not risk_decision.get("approved", False):
            return "hold", 0, False

        # No Fund Manager decision (shouldn't happen if risk approved, but guard it)
        if fund_decision is None:
            return "hold", 0, False

        # Fund Manager rejected
        if not fund_decision.get("approved", False):
            return "hold", 0, False

        # Fund Manager says skip
        if fund_decision.get("priority") == "skip":
            return "hold", 0, False

        final_quantity = int(fund_decision.get("final_quantity", 0))
        requires_human = bool(fund_decision.get("requires_human_approval", False))
        action = trade_decision.get("action", "hold")

        if final_quantity == 0:
            return "hold", 0, requires_human

        if requires_human:
            # Decision made but execution paused pending human confirmation
            return "pending_human_approval", final_quantity, True

        return action, final_quantity, False
```

---

## 11. `agents/rules/agent_prompts.py` — LLM Agent System Prompts {#agentsrulesagent_promptspy}

### Purpose

`agents/rules/agent_prompts.py` contains the complete system prompt strings for all seven LLM-backed agents in the trading pipeline. Each prompt is a multi-section markdown document that defines the agent's role, the exact ThinkorSwim-derived indicator parameters and thresholds they must reference, and the precise output format they are required to return. The prompts encode the 5-layer Tony Stark trading framework at the LLM instruction level, including specific numeric thresholds such as STC crossover levels (23/83, grid-optimized from defaults), Phase Oscillator Fibonacci levels, and Keltner Channel ATR multipliers. The Debate Prompt enforces the scoring and verdict logic so the LLM moderator applies the same rules as the Python synthesis logic. All prompts are imported directly by their respective agent classes.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| TECHNICAL_ANALYST_PROMPT | str | System prompt for TechnicalAnalystAgent — Layer 1-4 indicator toolkit, output format for TechnicalReport |
| FUNDAMENTAL_ANALYST_PROMPT | str | System prompt for FundamentalistAgent — macro calendar, regime indicators, FundamentalReport format |
| NEWS_ANALYST_PROMPT | str | System prompt for NewsAnalystAgent — market-moving news categories, NewsReport format |
| SOCIAL_ANALYST_PROMPT | str | System prompt for SocialAnalystAgent — options flow, dark pool, sentiment, SocialReport format |
| BULL_RESEARCHER_PROMPT | str | System prompt for BullResearcherAgent — instructs agent to build strongest possible bullish case |
| BEAR_RESEARCHER_PROMPT | str | System prompt for BearResearcherAgent — instructs agent to build strongest possible bearish case |
| DEBATE_PROMPT | str | System prompt for DebateOrchestrator — 0-10 scoring rules, EXHAUSTED regime rule, verdict thresholds |
| TRADER_PROMPT | str | System prompt for TraderAgent — entry/stop/target rules, R:R minimum 1.5:1, order type preferences |
| RISK_MANAGER_PROMPT | str | System prompt for RiskManagerAgent — hardcoded kill-switch rules, position sizing formula, veto criteria |
| FUND_MANAGER_PROMPT | str | System prompt for FundManagerAgent — portfolio balance rules, conviction thresholds, time-of-day rules |

### Source Code

```python
"""
JARVIS TRADER — LLM Agent System Prompts
Grounded in exact ThinkorSwim script parameters and the 5-layer trading framework.
"""

TECHNICAL_ANALYST_PROMPT = """You are the Technical Analyst for JARVIS TRADER, an AI-powered futures trading system.

Your role is to analyze price action and compute the 5-layer trading framework for any given symbol.

## Your Toolkit (ThinkorSwim-Derived Indicators)

**Layer 1 — Regime Detection:**
- ATR Range Consumed: <70% = room to run, 70-90% = caution, >90% = EXHAUSTED
- Phase Oscillator levels: +100/+61.8/+23.6/0/-23.6/-61.8/-100 (deviation from 21 EMA normalized to 3×ATR)
- EMA Ribbon (8/21/34): All stacked up = bullish, all down = bearish, mixed = neutral
- TRIN: <0.6 = blow-off top, >2.0 = capitulation (when available)

**Layer 2 — Structure:**
- Initial Balance (IB): First 60-min range, IB High/Low, quad levels (25/50/75%), extensions (50/100/300%)
- TPO Profile: POC (fair value), VAH/VAL (70% value area), price location vs value
- ATR Fibonacci levels from prior close: 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.236, 1.5, 2.0, 3.0 × ATR(14)
- Keltner Channels: ±1.5× ATR (inner), ±2.0× (outer), ±3.0× (extreme) on 5m/15m/30m/4H
- Floor Pivots: PP, R1-R4, S1-S4
- Virgin VPOCs: Unvisited high-volume levels (price magnets)

**Layer 3 — Directional Bias:**
- KAMA(10): Close > KAMA = long bias, Close < KAMA = short bias + LinReg(7,20) slope confirmation
- Volume Stack: Buy proxy = vol × (close-low)/(high-low). Buyers >60% = bullish, <40% = bearish

**Layer 4 — Entry Timing:**
- STC (Schaff Trend Cycle): fast=23, slow=50, K=10, D=3. Cross above 23 = buy trigger, cross below 83 = sell trigger
  (Optimized from TOS defaults 19/88 via 162-combo grid search — 23/83 reduces false entries, higher profit factor)
- Range expansion (outside bar): Arrow direction + excess analysis

## Your Output Format

Always return a structured TechnicalReport with:
1. Current regime (TRENDING_BULL/BEAR/RANGE_BOUND/COMPRESSION/EXHAUSTED)
2. Key levels (support/resistance arrays, POC, IB High/Low)
3. Directional bias (STRONG_BULL through STRONG_BEAR)
4. Entry signal (ENTRY_NOW/WAIT_FOR_PULLBACK/FADE_EXTREME/NO_TRADE)
5. Stop and target levels (using ATR Fibonacci)
6. Confidence score (0.0-1.0)

Be precise with numbers. State the exact levels in dollar terms. Do not hedge excessively — give a clear directional view."""

FUNDAMENTAL_ANALYST_PROMPT = """You are the Fundamental Analyst for JARVIS TRADER, an AI-powered futures trading system.

Your role is to assess macro and fundamental conditions that affect the traded instruments (primarily S&P 500 / Nasdaq futures: MES, MNQ).

## Your Focus Areas

**Macro Calendar:**
- Fed meeting dates, rate decisions, FOMC minutes
- CPI, PPI, PCE inflation data releases
- NFP (Non-Farm Payrolls), unemployment rate
- GDP releases, ISM Manufacturing/Services
- Treasury auctions and yield curve dynamics

**Market Regime Indicators:**
- VIX level and trend (>25 = fear, >35 = extreme fear)
- High Yield credit spreads (HYG) — widening = risk-off
- Dollar index (DXY) direction — strong dollar = headwind for risk assets
- Treasury yields (10yr, 2yr) — inversion status

**Sector Analysis:**
- Which sectors are leading vs lagging
- Rotation from growth to value or vice versa
- Technology sector strength (critical for NQ)

## Your Output Format

Return a FundamentalReport with:
1. Key upcoming events in next 48 hours
2. Macro bias (bullish/bearish/neutral for risk assets)
3. Sector strength assessment
4. Risk events that could invalidate the technical setup
5. Confidence score (0.0-1.0)

Be brief. Your role is context-setting, not overriding the technical signal."""

NEWS_ANALYST_PROMPT = """You are the News Analyst for JARVIS TRADER, an AI-powered futures trading system.

Your role is to assess the near-term impact of news and events on the traded instruments.

## Your Focus Areas

**Market-Moving News Categories:**
- Fed speeches and communications (immediate impact)
- Earnings from major S&P 500 components (AAPL, NVDA, MSFT, etc.)
- Geopolitical events affecting risk appetite
- Economic data beats/misses vs consensus
- M&A, regulatory actions on major companies

**Sentiment Scoring:**
- Positive: News that supports higher prices (earnings beats, rate cuts, stimulus)
- Negative: News that pressures prices (rate hikes, geopolitical risk, earnings misses)
- Neutral: No significant near-term impact

## Your Output Format

Return a NewsReport with:
1. Top 5 relevant headlines from last 24 hours
2. Overall sentiment score (-1.0 = very bearish to +1.0 = very bullish)
3. List of upcoming catalyst events
4. Any news that directly contradicts the technical setup
5. Confidence score (0.0-1.0)

Focus on what MOVES THE MARKET in the next 4-8 hours. Long-term analysis is not needed."""

SOCIAL_ANALYST_PROMPT = """You are the Social/Flow Analyst for JARVIS TRADER, an AI-powered futures trading system.

Your role is to assess market sentiment from options flow, dark pool activity, and social indicators.

## Your Focus Areas

**Options Flow:**
- Large block options purchases (sweeps) indicating institutional direction
- Put/call ratio: <0.7 = bullish, 0.7-1.0 = neutral, >1.0 = bearish
- Unusual options activity (large positions vs average)
- Gamma exposure levels (can pin or amplify price moves)

**Dark Pool Activity:**
- Large block trades off-exchange (institutional accumulation/distribution)
- Dark pool prints near key technical levels confirm those levels

**Sentiment Indicators:**
- AAII bull/bear survey (contrarian at extremes)
- Social media sentiment (r/wallstreetbets, Fintwit) — contrarian signal at extremes
- Fear & Greed Index

## Your Output Format

Return a SocialReport with:
1. Options flow assessment (bullish sweep/bearish sweep/neutral)
2. Put/call ratio if available
3. Dark pool activity assessment
4. Overall sentiment score (-1.0 to +1.0)
5. Confidence score (0.0-1.0)

Note: If options flow data is unavailable, state that clearly and assign low confidence."""

BULL_RESEARCHER_PROMPT = """You are the Bull Researcher for JARVIS TRADER. Your job is to BUILD THE STRONGEST POSSIBLE BULLISH CASE for a trade.

You receive the reports from Technical, News, Social, and Fundamental analysts. Your task is to identify and synthesize ALL bullish signals, even if you personally believe the setup is mixed.

## Your Process

1. **Extract all bullish technical signals:**
   - Regime: Is it TRENDING_BULL or COMPRESSION (potential breakout up)?
   - Structure: Is price above VAH (buyer control)? Above IB High? Above POC?
   - Bias: Is KAMA long? Volume buyers > 60%? STC rising from oversold?
   - Levels: Are there Virgin VPOCs above as targets? ATR Fibonacci targets overhead?

2. **Extract all bullish fundamental/news signals:**
   - Positive earnings, rate cut expectations, improving macro data

3. **Count signal alignment:**
   - How many of the 5 layers support a long trade?

4. **Construct the bull thesis:**
   - 2-3 sentences: What is the setup? Why would price go up? What are the targets?

## Your Output Format

Return a ResearchCase (direction="bull") with:
1. Clear 2-3 sentence thesis
2. List of supporting technical signals (with specific numbers)
3. List of supporting macro/news signals
4. Price target (next ATR Fibonacci level or VPOC)
5. Stop level (IB Low or nearest Keltner inner band)
6. Signal count (how many of 5 layers align bullishly, out of 5)
7. Confidence score (0.0-1.0)

Be RUTHLESSLY BULLISH. Present the bull case as strongly as the data allows. The Bear Researcher will counter you."""

BEAR_RESEARCHER_PROMPT = """You are the Bear Researcher for JARVIS TRADER. Your job is to BUILD THE STRONGEST POSSIBLE BEARISH CASE for a trade.

You receive the reports from Technical, News, Social, and Fundamental analysts. Your task is to identify and synthesize ALL bearish signals, even if you personally believe the setup is bullish.

## Your Process

1. **Extract all bearish technical signals:**
   - Regime: Is it TRENDING_BEAR or EXHAUSTED (fade opportunity)?
   - Structure: Is price below VAL (seller control)? Below IB Low? Below POC?
   - Bias: Is KAMA short? Volume sellers > 60%? STC falling from overbought (88)?
   - Levels: Are there Virgin VPOCs below as targets? ATR Fibonacci puts targets below?
   - TRIN: Is it elevated (>2.0 = potential bounce but confirmed downtrend)?

2. **Extract all bearish fundamental/news signals:**
   - Rate hike fears, earnings misses, geopolitical risk, credit spread widening

3. **Count signal alignment:**
   - How many of the 5 layers support a short trade?

4. **Construct the bear thesis:**
   - 2-3 sentences: What is the setup? Why would price go down? What are the targets?

## Your Output Format

Return a ResearchCase (direction="bear") with:
1. Clear 2-3 sentence thesis
2. List of supporting technical signals (with specific numbers)
3. List of supporting macro/news signals
4. Price target (next ATR Fibonacci level down or VPOC below)
5. Stop level (IB High or nearest Keltner inner band above)
6. Signal count (how many of 5 layers align bearishly, out of 5)
7. Confidence score (0.0-1.0)

Be RUTHLESSLY BEARISH. Present the bear case as strongly as the data allows."""

DEBATE_PROMPT = """You are the Debate Moderator for JARVIS TRADER. You receive the Bull Case and Bear Case from the researchers and must render a VERDICT.

## Your Process

1. **Score each case on a 0-10 scale:**
   - Technical alignment: How many of the 5 layers support this direction?
   - Signal quality: Are the signals high-quality (specific levels, strong indicators) or weak (vague)?
   - Risk/reward: Does the proposed trade have R:R ≥ 1.5:1?
   - Conviction: Does the researcher cite specific numbers (ATR levels, STC values, VPOC locations)?

2. **Apply the 5-layer filter:**
   - A direction with 5/5 layers aligned scores maximum
   - A direction with 3/5 layers aligned scores moderate
   - A direction with 2/5 or fewer layers aligned should NOT be recommended (score < 5)

3. **The EXHAUSTED rule:**
   - If current regime = EXHAUSTED, neither bull nor bear case should score above 6
   - In EXHAUSTED regime, only FADE trades (counter-trend, 0.5% risk) are allowed

4. **Render verdict:**
   - If bull_score - bear_score > 2: RECOMMEND LONG
   - If bear_score - bull_score > 2: RECOMMEND SHORT
   - If scores within 2 of each other: NEUTRAL (no trade)

## Your Output Format

Return a DebateResult with:
1. Bull score (0-10)
2. Bear score (0-10)
3. Winner (bull/bear/neutral)
4. Top 3 bull points that won the argument
5. Top 3 bear points (even if they lost, note the key risks)
6. Recommended action (BUY/SELL/HOLD)
7. Conviction level (0.0-1.0)
8. Clear rationale (2-3 sentences)"""

TRADER_PROMPT = """You are the Trader for JARVIS TRADER. You receive the Debate Result and Technical Report and must produce an executable trade decision.

## Your Mandate

1. **Only execute if Debate says ENTRY_NOW and conviction ≥ 0.7**
2. **Use exact levels from the Technical Report:**
   - Entry: Current ask (longs) or current bid (shorts), or limit at next ATR Fib level
   - Stop: As specified in Layer 5 rules (IB Low/High or Keltner inner band)
   - Target 1: +0.382 × ATR from entry (exit 50% of position)
   - Target 2: +0.618 × ATR (exit 30%)
   - Target 3: +1.0 × ATR (exit remaining 20%)
3. **Calculate risk/reward BEFORE committing:**
   - R:R must be ≥ 1.5:1 (Target 1 vs stop distance)
   - If R:R < 1.5:1, HOLD (wait for better entry or skip)

## Order Preferences
- Prefer LIMIT orders (better fills)
- Use MARKET only if signal is time-sensitive (e.g., STC about to leave oversold)
- Default: order type = LIMIT

## Your Output Format

Return a TradeDecision with:
1. Action (BUY/SELL/HOLD)
2. Order type (MARKET/LIMIT)
3. Entry price
4. Stop price
5. Target 1, 2, 3 prices
6. Risk/reward ratio
7. Suggested contracts (placeholder — RiskManager will approve final size)
8. Which Layer 4 signal triggered this entry
9. Conviction (0.0-1.0)

If R:R < 1.5:1 or conviction < 0.7, return HOLD."""

RISK_MANAGER_PROMPT = """You are the Risk Manager for JARVIS TRADER. You are the LAST LINE OF DEFENSE before any trade is approved. You have VETO POWER.

## Your Hardcoded Rules (CANNOT be overridden by any other agent)

### Daily Loss Limit
- Maximum daily loss: 2% of starting account value
- If current day P&L < -2%: REJECT ALL TRADES, return kill_switch_triggered=True
- No exceptions.

### Drawdown Limit
- Maximum drawdown from high-water mark: 5%
- If current drawdown > 5%: REJECT ALL TRADES
- No exceptions.

### Position Size Limits
- Maximum single position: 5% of account value
- Maximum contracts per trade: Calculated as (account × 0.01) / (stop_distance × multiplier)
- Round DOWN to nearest whole contract
- Minimum: 1 contract

### Risk/Reward Filter
- Minimum R:R ratio: 1.5:1 (Target 1 vs stop)
- If R:R < 1.5:1: REJECT or modify entry to improve R:R

### EXHAUSTED Regime Rule
- If current regime = EXHAUSTED: Only approve FADE trades at max 0.5% risk
- Standard trades in EXHAUSTED regime: REJECT

### Correlation Rule
- Cannot have 2 simultaneous positions in highly correlated instruments (e.g., MES + MNQ both long)
- Exception: If one is a hedge

## Your Process

1. Check kill switch (daily loss + drawdown)
2. Validate position size
3. Validate R:R
4. Check regime vs trade direction
5. Check correlation with open positions
6. Approve, modify, or reject

## Your Output Format

Return a RiskDecision with:
1. approved (True/False)
2. modified (True/False — if you changed the size)
3. approved_contracts (your calculation)
4. approved_stop (you may tighten it)
5. max_daily_loss_remaining
6. current_drawdown_pct
7. kill_switch_triggered
8. rejection_reason (if rejected)"""

FUND_MANAGER_PROMPT = """You are the Fund Manager for JARVIS TRADER. You make the FINAL decision on whether to execute a trade.

## Your Role

You receive the Risk-approved TradeDecision and make the final call considering the full portfolio context.

## Your Considerations

### Portfolio Balance
- Maximum exposure to a single sector: 50% of portfolio
- Maximum total portfolio heat (all open risk combined): 6% of account
- Prefer diversification across uncorrelated instruments

### Conviction Threshold
- Only execute if the pipeline conviction ≥ 0.7 (aggregate of all 5 stages)
- If conviction 0.5-0.7: reduce size by 50%
- If conviction < 0.5: NO_TRADE

### Human Approval
- If REQUIRE_HUMAN_APPROVAL=True: set human_approval_required=True on all trades
- If REQUIRE_HUMAN_APPROVAL=False: execute automatically

### Time of Day Rules
- Avoid new positions in first 5 minutes of RTH (9:30-9:35 AM CT) — too chaotic
- Avoid new positions in last 15 minutes of RTH (3:45-4:00 PM CT) — forced closes
- Prefer entries 9:35-11:30 AM and 1:00-3:30 PM CT (best liquidity)

### Final Conviction Calculation
- Average the conviction scores from: TechnicalReport, DebateResult, TradeDecision
- Apply regime multiplier: COMPRESSION × 0.8, TRENDING × 1.0, EXHAUSTED × 0.4

## Your Output Format

Return a FundDecision with:
1. execute (True/False)
2. Action, contracts, entry, stop, targets
3. Portfolio weight % this trade represents
4. Final conviction score
5. human_approval_required flag
6. Brief execution notes (2-3 sentences on why you approved/rejected)"""
```

---

## 12. `agents/rules/trading_rules.md` — 5-Layer Trading Framework {#agentsrulestrading_rulesmd}

### Purpose

`agents/rules/trading_rules.md` is the canonical human-readable specification of the 5-layer "Tony Stark" trading framework that drives all agent decision-making in JARVIS Trader. It defines precise, numeric rules for each layer: Layer 1 establishes regime classification thresholds using TRIN, ATR Range Consumed, and Phase Oscillator; Layer 2 maps out the complete structural level system including IB quad/extension levels, TPO profile components, ATR Fibonacci targets, floor pivots, and Keltner Channel configurations; Layer 3 specifies directional bias scoring via the TPO Score System and KAMA/Volume Stack; Layer 4 defines entry timing using STC (with grid-optimized 23/83 thresholds), Range Finder signals, Keltner entries, gap fills, and single prints. Layer 5 encodes position sizing, stop/target placement, contract multipliers, and hardcoded kill-switch rules that no LLM agent is permitted to override. This document is both the design specification for the backtest signal generation and the grounding reference for all LLM agent system prompts.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| LAYER 1: REGIME FILTER | section | Go/No-Go gate — classifies market into TRENDING/RANGE/COMPRESSION/EXHAUSTED using TRIN, Phase, ATR, EMA Ribbon |
| LAYER 2: STRUCTURE MAP | section | Complete price map: IB levels, TPO/Volume Profile, ATR Fibonacci, Floor Pivots, Keltner Channels, confluence rules |
| LAYER 3: DIRECTIONAL BIAS | section | TPO Score System (-5 to +5), KAMA direction, Volume Stack, bias classification table |
| LAYER 4: ENTRY TIMING | section | STC crossover triggers (23 buy / 83 sell), RFv2 arrows, Keltner entries, gap fills, single prints, entry signal table |
| LAYER 5: POSITION SIZING & RISK | section | Stop rules, ATR-based targets (0.382/0.618/1.0x), 1% risk per trade sizing formula, contract multipliers table, kill-switch rules |
| THE SYNTHESIS RULE | section | Boolean formula: all 5 layers must pass — any NO = NO TRADE |
| PRIORITY ORDER | section | Daily preparation checklist — 7-step workflow for each trading day |

### Source Code

```markdown
# JARVIS TRADER — Trading Rules
## The 5-Layer "Tony Stark" Framework
All 5 layers must align for a valid trade signal.

---

## LAYER 1: REGIME FILTER (Go/No-Go Gate)

Evaluate market conditions BEFORE looking at any setup.

### Regime Classifications

| Regime | Conditions | Action |
|--------|-----------|--------|
| TRENDING_BULL | TRIN < 1.0 + Phase > 0 + ATR consumed < 70% + EMA ribbon all up | Trade longs freely |
| TRENDING_BEAR | TRIN > 1.5 + Phase < 0 + ATR consumed < 70% + EMA ribbon all down | Trade shorts freely |
| RANGE_BOUND | TRIN 0.8-1.2 + Phase between -23.6 and +23.6 + price inside VA | Mean reversion only |
| COMPRESSION | Phase Bollinger inside ATR bands + ATR consumed < 50% | Wait for breakout direction |
| EXHAUSTED | ATR consumed > 90% OR price at 2x ATR extension | No new trades (fade only with 0.5% risk) |

### TRIN Thresholds (Chetan TRIN script)
- **Capitulation (BUY zone)**: TRIN close > 2.0 AND TRIN low > 1.0 AND VIX > 30 → cyan bars
- **Blow-off TOP (SELL zone)**: TRIN close < 0.6 AND TRIN high < 1.0 AND VVIX < 120 → magenta bars
- Normal range: TRIN 0.6-2.0 = no extreme signal

### ATR Range Consumed (Saty ATR Levels script)
- ATR period: 14 (Wilder's smoothing)
- Range consumed = abs(current_price - prior_close) / ATR × 100
- **< 70%** = green (room to run, trade with trend)
- **70-90%** = orange (caution, reduce size)
- **> 90%** = red (exhausted, wait or fade only)

### Phase Oscillator (Saty Phase script)
- Formula: (close - EMA(21)) / (3 × ATR(14)) × 100
- **Compression**: Bollinger Bands (21, 2SD) contracting INSIDE ATR bands → BREAKOUT IMMINENT
- **+100**: Extreme extension up (distribution zone, fade)
- **+61.8**: Distribution (start scaling out longs)
- **+23.6**: Neutral up
- **-23.6**: Neutral down
- **-61.8**: Accumulation (start scaling into longs)
- **-100**: Extreme extension down (fade shorts)

### EMA Ribbon (Saty ATR script)
- EMA 8, EMA 21, EMA 34 (standard EMA, not Wilder's)
- **Bullish**: EMA 8 > EMA 21 > EMA 34 (all stacked up)
- **Bearish**: EMA 8 < EMA 21 < EMA 34 (all stacked down)
- **Neutral**: Mixed order

---

## LAYER 2: STRUCTURE MAP (Establish Key Levels)

Build the price map BEFORE entering any trade.

### Initial Balance (Corey IB script)
- **Definition**: First 60 minutes of RTH (9:30-10:30 AM CT)
- **IB High / IB Low** = day's primary reference range
- **Quad levels** (support/resistance within range):
  - Q25 = IB Low + 0.25 × IB Range
  - Q50 = IB Low + 0.50 × IB Range (midpoint)
  - Q75 = IB Low + 0.75 × IB Range
- **Extensions** (targets if IB breaks):
  - Up: +50% of IB range above IB High (first target)
  - Up: +100% of IB range above IB High (second target)
  - Up: +300% of IB range above IB High (major extension)
  - Down: mirror of above
- **Day bias**: Price above IB High = bullish. Below IB Low = bearish.

### TPO/Volume Profile (Corey TPO + Virgin Profile scripts)
- **Value Area**: 70% of volume/time (standard)
- **POC (Point of Control)**: Price with most volume/TPO = FAIR VALUE
- **VAH (Value Area High)**: Upper boundary of 70% value area
- **VAL (Value Area Low)**: Lower boundary of 70% value area
- **Price location**:
  - Above VAH = buyer control (bullish)
  - Inside VA = balanced/rotating
  - Below VAL = seller control (bearish)
- **Virgin VPOC**: POC levels that have NEVER been revisited = HIGH-PRIORITY MAGNETS
  - Track up to 10 virgin VPOCs above and below current price
  - Price is attracted to nearest VPOC (gravity effect)

### ATR Fibonacci Levels (Saty ATR script)
- **Base**: Prior day's close
- **Trigger zones** (0.236 × ATR from close):
  - Call trigger: prior_close + 0.236 × ATR(14)
  - Put trigger: prior_close - 0.236 × ATR(14)
- **Full target levels** (both up and down from prior close):
  - 0.236 × ATR (trigger/entry)
  - 0.382 × ATR (Target 1)
  - 0.500 × ATR (Target 2 / midpoint)
  - 0.618 × ATR (Target 3 / golden ratio)
  - 0.786 × ATR (Target 4)
  - 1.000 × ATR (Full daily range)
  - 1.236 × ATR (Extension 1)
  - 1.500 × ATR (Extension 2)
  - 2.000 × ATR (Extension 3 / double range)
  - 3.000 × ATR (Extreme extension)

### Floor Pivot Points
- PP = (Prior High + Prior Low + Prior Close) / 3
- R1 = 2 × PP - Prior Low
- R2 = PP + (Prior High - Prior Low)
- R3 = 2 × PP + (Prior High - 2 × Prior Low)
- S1 = 2 × PP - Prior High
- S2 = PP - (Prior High - Prior Low)
- S3 = 2 × PP - (2 × Prior High - Prior Low)

### Multi-TF Keltner Channels (Omega 5m/15m/30m + KMaster 4H)
- **Basis**: SMA(20) of close
- **ATR**: SMA of True Range(20)
- **Inner bands** (±1.5 × ATR): Normal extension, pullback entry zone
- **Outer bands** (±2.0 × ATR): Extended price, caution zone
- **Extreme bands** (±3.0 × ATR): Extreme fade zone
- **MACD closed door** (12/26/9): When MACD aligns with a band, that side is "closed" (price unlikely to breach)
- **Timeframes**: 5-min, 15-min, 30-min, 4-hour — stacked for confluence

### Confluence Rules
- **STRONG S/R**: 2+ of the following at same price: VPOC, VAH/VAL, IB High/Low, ATR Fib, Pivot, Keltner band
- **WEAK S/R**: Only 1 of the above
- Always note nearest VPOC above and below as primary magnets

---

## LAYER 3: DIRECTIONAL BIAS

Determine the most likely direction BEFORE timing entry.

### TPO Score System (Corey TScore script)
5-component composite (-5 to +5):
1. VAH position vs POC: above=+1, below=-1
2. VAL position vs POC: below=-1, above=+1
3. POC position in profile: upper half=+1, lower half=-1
4. VA Balance direction: up=+1, down=-1
5. Imbalance: bull=+1, bear=-1

Score interpretation:
- **+3 to +5**: STRONG_BULL
- **+1 to +2**: LEAN_BULL
- **0**: NEUTRAL
- **-1 to -2**: LEAN_BEAR
- **-3 to -5**: STRONG_BEAR

### KAMA Direction (NextSignalMomentum script)
- KAMA period: 10
- **Long signal**: close > KAMA
- **Short signal**: close < KAMA
- **Confirmation**: LinReg(7) and LinReg(20) both positive slope (longs) or negative (shorts)

### Volume Stack (Saty Volume script)
- Buy volume proxy: volume × (close - low) / (high - low)
- Sell volume proxy: volume × (high - close) / (high - low)
- **Bullish confirmation**: buyers > 60% of total volume
- **Bearish confirmation**: sellers > 60% of total volume
- **Balanced**: 40-60% split → no edge

### Bias Classification
- **STRONG_BULL**: TPO score ≥ +3 AND KAMA long AND volume buyers > 60%
- **LEAN_BULL**: 2 of above conditions + EMA ribbon bullish
- **NEUTRAL**: Mixed signals, price inside VA, STC in 20-80 zone
- **LEAN_BEAR**: 2 bearish conditions + EMA ribbon bearish
- **STRONG_BEAR**: TPO score ≤ -3 AND KAMA short AND volume sellers > 60%

---

## LAYER 4: ENTRY TIMING

Identify precise entry after regime + structure + bias all confirmed.

### STC (Schaff Trend Cycle) — Primary Timing Tool
- Parameters: fast=23, slow=50, K_period=10, D_period=3
- Formula: MACD → Stochastic of MACD → EMA smooth → Stochastic again → EMA smooth
- **Buy trigger**: STC crosses UP through 23 (oversold → rising) — grid-optimized from TOS default 19
- **Sell trigger**: STC crosses DOWN through 83 (overbought → falling) — grid-optimized from TOS default 88
- **Bull momentum zone**: STC 20-80 (rising = trend continuation)
- **Bear momentum zone**: STC 80-20 (falling = trend continuation)

### Range Finder Signals (Corey RFv2 script)
- **Outside bar detection**: high > prior high AND low < prior low
- **Green up-arrow**: Outside bar with bullish 3-bar average + low excess → continuation up
- **Red down-arrow**: Outside bar with bearish 3-bar average + high excess → continuation down
- **Yellow arrow**: Caution — mixed signals
- **Bear/Bull Imbalance label**: Profile imbalance determines extension direction

### Keltner Channel Entries
- **Inner band (1.5x) touch**: Pullback entry on trend confirmation
- **Outer band (2.0x) touch**: More aggressive entry, wider stop
- **Extreme band (3.0x) touch**: COUNTER-TREND FADE only (small size, tight stop)
- **MACD closed door**: If MACD suggests band is "closed", fade that side

### Gap Fill Entries (Corey GapFinder script)
- Unfilled gap above = resistance, fade toward it from below
- Unfilled gap below = support, fade toward it from above
- Gap fill = high-probability target; enter on approach with confirmation

### Single Print Entries (Corey SingleFinder script)
- Unfilled bull single = support level (buy on test)
- Unfilled bear single = resistance level (sell on test)
- Filled single = confirms direction (enter in direction of fill)

### Entry Signal Classification
| Signal | Conditions |
|--------|-----------|
| ENTRY_NOW | STC crosses 19/88 + RFv2 arrow + Layer 1-3 all aligned |
| WAIT_FOR_PULLBACK | Bias confirmed, STC in middle zone (20-80), wait for retracement to POC/Keltner |
| FADE_EXTREME | Regime=EXHAUSTED, ATR>90%, Phase>+61.8 or <-61.8, counter-trend small size |
| NO_TRADE | Regime=EXHAUSTED without fade setup, or bias=NEUTRAL, or conflicting signals |

---

## LAYER 5: POSITION SIZING & RISK MANAGEMENT

### Stop Loss Rules
- **Long stop**: Below the LOWER of: IB Low OR nearest Keltner inner band
- **Short stop**: Above the HIGHER of: IB High OR nearest Keltner inner band
- **Maximum stop distance**: 1 × ATR from entry (hard cap)
- **Minimum stop distance**: 0.25 × ATR (avoid stops too tight)

### Profit Target Rules
- **Target 1** (50% exit): Entry + 0.382 × ATR (long) or Entry - 0.382 × ATR (short)
- **Target 2** (30% exit): Entry + 0.618 × ATR
- **Target 3** (20% exit): Entry + 1.0 × ATR
- Move stop to breakeven after Target 1 is hit

### Position Sizing
- **Risk per trade**: 1% of account equity
- **Contracts**: floor((account × 0.01) / (stop_distance × contract_multiplier))
- **Minimum**: 1 contract
- **Maximum**: Capped by available capital

### Contract Multipliers
| Symbol | Multiplier |
|--------|-----------|
| MES (Micro S&P) | $5 per point |
| MNQ (Micro Nasdaq) | $2 per point |
| MGC (Micro Gold) | $10 per oz |
| M2K (Micro Russell) | $5 per point |
| MYM (Micro Dow) | $0.50 per point |

### Kill Switch Rules (HARDCODED — LLM cannot override)
- **Daily loss limit**: Stop ALL trading if day's P&L < -2% of starting account value
- **Drawdown limit**: Stop ALL trading if drawdown from high-water mark > 5%
- **Intraday**: Kill switch resets at midnight CT (new trading day)
- **Regime shift**: If mid-trade regime becomes EXHAUSTED, exit at market or next Target 1

---

## THE SYNTHESIS RULE

```
VALID TRADE =
  Layer 1 (Regime) ≠ EXHAUSTED
  AND Layer 2 (Structure) shows clear S/R with ≥2 confluence factors
  AND Layer 3 (Bias) ≠ NEUTRAL
  AND Layer 4 (Timing) = ENTRY_NOW
  AND Layer 5 (Risk) R:R ≥ 1.5:1

ANY "no" from any layer = NO TRADE
```

---

## PRIORITY ORDER FOR DAILY PREPARATION

1. Check overnight ATR levels (prior close ± ATR Fibs) — these are the day's targets
2. Note IB range from 9:30-10:30 AM
3. Mark prior day's VPOC and any Virgin VPOCs near current price
4. Identify Keltner bands for the day on all 4 timeframes
5. Check breadth (TRIN, VIX) for regime classification
6. Watch Phase Oscillator for compression signals
7. Wait for STC entry trigger that aligns with all 5 layers
```

---

## 13. `main.py` — FastAPI Server {#mainpy}

### Purpose

`main.py` is the FastAPI application entry point for JARVIS Trader, running on port 8010. At startup it initializes all 10 trading agents, wires them into the `TradingPipeline`, connects the `MarketDataManager` and `SafetyLayer`, and starts an APScheduler job that automatically scans the top futures and equity watchlist symbols every 30 minutes during regular trading hours (9:30 AM to 4:00 PM CT, weekdays). The server exposes 23 HTTP endpoints organized into logical groups: safety and kill switch management, technical and sentiment analysis, portfolio state, the full 5-stage pipeline, scheduler status, WhatsApp notifications, ThinkScript code generation, FRED macro data, and backtesting. The lifespan context manager handles graceful startup and shutdown including IBKR broker disconnection and scheduler teardown.

### Key Components

| Name | Type | Purpose |
|------|------|---------|
| lifespan | async context manager | FastAPI startup/shutdown — initializes all agents, pipeline, scheduler; tears down on exit |
| app | FastAPI | Main application instance with CORS middleware for dashboard origins |
| run_watchlist_analysis | async function | Scheduled task — runs pipeline on top 2 futures + top 3 equity symbols every 30 min |
| AnalysisRequest | Pydantic model | Request body for /analyze/technical — symbol, timeframe, is_futures |
| PipelineRequest | Pydantic model | Request body for /pipeline/run — symbol, is_futures |
| ThinkScriptRequest | Pydantic model | Request body for /thinkscript/generate — symbol, timeframe, is_futures |
| BacktestRequest | Pydantic model | Request body for /backtest/run — symbol, date range, interval, capital, risk_per_trade |
| _decision_log | list | In-memory ring buffer (100 entries max) storing all pipeline and scheduler decisions |
| health | endpoint | GET /health — server status, kill switch state, broker connection, uptime |
| activate_kill_switch | endpoint | POST /safety/kill-switch/activate — manual trading halt with WhatsApp alert |
| deactivate_kill_switch | endpoint | POST /safety/kill-switch/deactivate — resume trading |
| run_technical_analysis | endpoint | POST /analyze/technical — runs TechnicalAnalystAgent |
| get_bars | endpoint | GET /analyze/bars/{symbol} — OHLCV bars from MarketDataManager |
| run_pipeline | endpoint | POST /pipeline/run — full 5-stage pipeline with decision logging and WhatsApp alert |
| run_backtest | endpoint | POST /backtest/run — runs Backtester in ThreadPoolExecutor (blocking-safe) |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Server health + kill switch status + broker connection + uptime |
| POST | /safety/kill-switch/activate | Activate trading halt with reason; fires WhatsApp alert |
| POST | /safety/kill-switch/deactivate | Deactivate trading halt |
| GET | /safety/status | Current safety layer state (kill switch, daily P&L, drawdown) |
| POST | /analyze/technical | Run technical analyst on symbol — returns regime, trend, levels, scores |
| GET | /analyze/bars/{symbol} | Get OHLCV bars (last 200 of requested window) |
| GET | /sentiment/reddit | Reddit trending tickers via filter (default: all-stocks) |
| GET | /sentiment/news/{symbol} | Finnhub news sentiment for a symbol |
| GET | /portfolio | Current portfolio state from safety layer (positions placeholder) |
| GET | /decisions/recent | Last N pipeline decisions from in-memory log |
| POST | /decisions/log | Internal: log a decision to the ring buffer |
| GET | /sentiment/recent | Latest sentiment scores from Reddit (top 3 tickers normalized to -1..1) |
| GET | /watchlist | Configured futures + equity watchlists with live yfinance prices |
| GET | /prices/snapshot | Live price snapshot for comma-separated symbols with micro-futures mapping |
| POST | /pipeline/run | Run full 5-stage pipeline; logs decision; sends WhatsApp alert on non-HOLD |
| GET | /pipeline/status | Pipeline availability and last run info |
| GET | /scheduler/status | APScheduler job list with next run times and decision count |
| POST | /notifications/whatsapp/test | Test Twilio WhatsApp configuration |
| POST | /thinkscript/generate | Generate TOS ThinkScript code from JARVIS technical analysis |
| GET | /macro/snapshot | FRED macro snapshot (Fed Funds, yields, VIX, unemployment) |
| GET | /macro/series/{series_id} | Historical FRED series data (e.g., FEDFUNDS, GS10, VIXCLS) |
| POST | /backtest/run | Run backtest via API in thread pool; returns full BacktestResult dict |

### Source Code

```python
"""
JARVIS TRADER — Main Server
============================
FastAPI backend for the trading engine.
Runs on port 8010 (separate from GMS JARVIS on 8009).

Start with: uvicorn main:app --reload --port 8010
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from data.market_data import MarketDataManager
from risk.safety_layer import SafetyLayer, OrderRequest
from agents.technical_analyst import TechnicalAnalystAgent
from agents.news_analyst import NewsAnalystAgent
from agents.social_analyst import SocialAnalystAgent
from agents.fundamental_analyst import FundamentalistAgent
from agents.bull_researcher import BullResearcherAgent
from agents.bear_researcher import BearResearcherAgent
from agents.debate import DebateOrchestrator
from agents.trader import TraderAgent
from agents.risk_manager import RiskManagerAgent
from agents.fund_manager import FundManagerAgent
from agents.pipeline import TradingPipeline

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("jarvis_trader")

# ── Global State ─────────────────────────────────────────────────────────
data_manager: MarketDataManager | None = None
safety_layer: SafetyLayer | None = None
technical_analyst: TechnicalAnalystAgent | None = None
trading_pipeline: TradingPipeline | None = None
scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and teardown on startup/shutdown"""
    global data_manager, safety_layer, technical_analyst, trading_pipeline, scheduler

    logger.info("🤖 JARVIS TRADER starting up...")
    logger.info(f"   Live trading: {'ENABLED ⚠️' if settings.LIVE_TRADING_ENABLED else 'DISABLED (paper mode)'}")
    logger.info(f"   IBKR port:   {settings.IBKR_PORT} ({'live' if settings.IBKR_PORT == 4001 else 'paper'})")

    # Safety layer — always first
    safety_layer = SafetyLayer(settings)

    # Market data connections
    data_manager = MarketDataManager(settings)
    await data_manager.initialize()

    # Agents (need LLM client)
    class SimpleLLMClient:
        api_key = settings.ANTHROPIC_API_KEY

    if settings.ANTHROPIC_API_KEY:
        llm_client = SimpleLLMClient()

        # Stage 1: Analysts
        technical_analyst = TechnicalAnalystAgent(llm_client, data_manager)
        news_agent = NewsAnalystAgent(llm_client, data_manager)
        social_agent = SocialAnalystAgent(llm_client)
        fundamental_agent = FundamentalistAgent(llm_client, data_manager)

        # Stage 2: Debate
        bull_agent = BullResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        bear_agent = BearResearcherAgent(api_key=settings.ANTHROPIC_API_KEY)
        debate_agent = DebateOrchestrator()

        # Stages 3-5: Trader → Risk → Fund
        trader_agent = TraderAgent(llm_client)
        risk_agent = RiskManagerAgent(llm_client)
        fund_agent = FundManagerAgent(llm_client)

        logger.info("✅ All 10 trading agents initialized")

        # Trading Pipeline — all agents wired
        trading_pipeline = TradingPipeline(
            agents={
                "technical":    technical_analyst,
                "news":         news_agent,
                "social":       social_agent,
                "fundamental":  fundamental_agent,
                "bull":         bull_agent,
                "bear":         bear_agent,
                "debate":       debate_agent,
                "trader":       trader_agent,
                "risk_manager": risk_agent,
                "fund_manager": fund_agent,
            },
            safety_layer=safety_layer,
        )
        logger.info("✅ Trading Pipeline initialized — all 5 stages wired")
    else:
        logger.warning("⚠️  No ANTHROPIC_API_KEY — LLM agents disabled. Add to .env to enable.")

    # Scheduled analysis (runs during market hours)
    scheduler = AsyncIOScheduler(timezone="America/Chicago")

    async def run_watchlist_analysis():
        """Run pipeline on all watchlist symbols — called by scheduler"""
        if not trading_pipeline or not safety_layer:
            return
        safety = safety_layer.get_status()
        if safety.get("kill_switch_active"):
            logger.info("⏭️  Scheduler: skipping — kill switch active")
            return

        symbols_to_scan = [
            (sym, True) for sym in settings.FUTURES_WATCHLIST[:2]  # Top 2 futures
        ] + [
            (sym, False) for sym in settings.OPTIONS_WATCHLIST[:3]  # Top 3 equities
        ]

        logger.info(f"⏰ Scheduled scan: {[s[0] for s in symbols_to_scan]}")
        for symbol, is_futures in symbols_to_scan:
            try:
                result = await trading_pipeline.analyze_and_decide(symbol, is_futures)
                action = result.get("final_action", "hold")
                if action not in ("hold",):
                    logger.info(f"📊 {symbol}: {action.upper()} ({result.get('confidence', 0):.0%} confidence)")
                    _decision_log.append({
                        "id": len(_decision_log) + 1,
                        "timestamp": datetime.now().isoformat(),
                        "symbol": symbol,
                        "action": action,
                        "confidence": result.get("confidence", 0),
                        "source": "scheduler",
                        "summary": result.get("summary", ""),
                    })
                    if len(_decision_log) > 100:
                        _decision_log.pop(0)
            except Exception as e:
                logger.error(f"Scheduler analysis failed for {symbol}: {e}")

    # Run every 30 minutes on weekdays, 9:30am-4:00pm Chicago time
    if settings.ANTHROPIC_API_KEY:
        scheduler.add_job(
            run_watchlist_analysis,
            CronTrigger(
                day_of_week="mon-fri",
                hour="9-15",
                minute="0,30",
                timezone="America/Chicago"
            ),
            id="watchlist_scan",
            name="Watchlist Auto-Scan",
            max_instances=1,
            misfire_grace_time=300,
        )
        scheduler.start()
        logger.info("⏰ Scheduler started — watchlist scan every 30min (9:30am-4pm CT weekdays)")

    logger.info("✅ JARVIS TRADER ready. Dashboard: http://localhost:3010")
    logger.info("   API docs: http://localhost:8010/docs")

    yield  # Server runs here

    # Teardown
    if data_manager and data_manager.ibkr:
        await data_manager.ibkr.disconnect()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("👋 JARVIS TRADER shutdown complete")


app = FastAPI(
    title="JARVIS TRADER",
    description="AI-powered autonomous trading system for futures and options",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010", "http://localhost:3000", "http://localhost:3004"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────

_start_time = datetime.now()

@app.get("/health")
async def health():
    safety = safety_layer.get_status() if safety_layer else {}
    return {
        "status": "online",
        "version": "0.1.0",
        "timestamp": datetime.now().isoformat(),
        "live_trading": settings.LIVE_TRADING_ENABLED,
        "kill_switch_active": safety.get("kill_switch_active", False),
        "paper_mode": not settings.LIVE_TRADING_ENABLED,
        "ibkr_connected": data_manager.ibkr.is_connected if data_manager and data_manager.ibkr else False,
        "schwab_connected": False,  # Schwab connector TODO
        "uptime_seconds": (datetime.now() - _start_time).total_seconds(),
    }


# ── Safety / Kill Switch ──────────────────────────────────────────────────

@app.post("/safety/kill-switch/activate")
async def activate_kill_switch(reason: str = "manual"):
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    from risk.safety_layer import KillSwitchReason
    safety_layer.activate_kill_switch(KillSwitchReason.MANUAL, f"Manual activation: {reason}")
    from notifications.whatsapp import get_notifier
    asyncio.create_task(get_notifier().alert_kill_switch(reason))
    return {"status": "kill_switch_activated", "reason": reason}


@app.post("/safety/kill-switch/deactivate")
async def deactivate_kill_switch():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    safety_layer.deactivate_kill_switch(authorized_by="matt_dashboard")
    return {"status": "kill_switch_deactivated"}


@app.get("/safety/status")
async def safety_status():
    if not safety_layer:
        raise HTTPException(500, "Safety layer not initialized")
    return safety_layer.get_status()


# ── Analysis ──────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@app.post("/analyze/technical")
async def run_technical_analysis(req: AnalysisRequest):
    """Run the Technical Analyst agent on a symbol"""
    if not technical_analyst:
        raise HTTPException(503, "Technical analyst not available (no API key)")

    report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)

    return {
        "symbol": report.symbol,
        "timestamp": report.timestamp.isoformat(),
        "timeframe": report.timeframe,
        "signal": report.signal,
        "confidence": report.confidence,
        "trend": report.trend,
        "regime": report.regime,
        "is_overbought": report.is_overbought,
        "is_oversold": report.is_oversold,
        "summary": report.summary,
        "reasoning": report.reasoning,
        "scores": {
            "trend": report.trend_score,
            "momentum": report.momentum_score,
            "volatility": report.volatility_score,
            "volume": report.volume_score,
        },
        "levels": {
            "current_price": report.current_price,
            "support": report.support_levels,
            "resistance": report.resistance_levels,
        },
        "raw_indicators": report.indicators,
    }


@app.get("/analyze/bars/{symbol}")
async def get_bars(symbol: str, timeframe: str = "5m", days: int = 7, futures: bool = False):
    """Get OHLCV bars for a symbol"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    df = await data_manager.get_bars(symbol, lookback_days=days, timeframe=timeframe, is_futures=futures)
    if df.empty:
        raise HTTPException(404, f"No data available for {symbol}")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": df.tail(200).to_dict(orient="records"),
        "count": len(df),
    }


@app.get("/sentiment/reddit")
async def get_reddit_sentiment(filter: str = "all-stocks"):
    """Get trending tickers from Reddit"""
    if not data_manager:
        raise HTTPException(503, "Data manager not initialized")

    tickers = await data_manager.reddit.get_trending_tickers(filter)
    return {"filter": filter, "tickers": tickers[:20]}


@app.get("/sentiment/news/{symbol}")
async def get_news_sentiment(symbol: str):
    """Get news sentiment for a symbol via Finnhub"""
    if not data_manager or not data_manager.finnhub:
        raise HTTPException(503, "Finnhub not connected (add FINNHUB_API_KEY to .env)")

    sentiment = data_manager.finnhub.get_news_sentiment(symbol)
    return {"symbol": symbol, "sentiment": sentiment}


# ── Portfolio ─────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def get_portfolio():
    """Current portfolio state — sourced from broker API, never from agent memory"""
    if not safety_layer:
        raise HTTPException(503, "Safety layer not initialized")
    status = safety_layer.get_status()
    return {
        "total_equity": status.get("portfolio_equity", 0.0),
        "cash_balance": status.get("portfolio_equity", 0.0),  # Approximation until broker sync
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "daily_pnl": status.get("daily_pnl", 0.0),
        "margin_used": 0.0,
        "margin_available": status.get("portfolio_equity", 0.0),
        "positions": [],  # Populated after IBKR connector is wired
    }


# ── Recent decisions (for dashboard feed) ─────────────────────────────────

_decision_log: list[dict] = []  # In-memory ring buffer, 100 entries

@app.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20):
    """Return most recent agent decisions"""
    return _decision_log[-limit:]


@app.post("/decisions/log")
async def log_decision(decision: dict):
    """Internal: agents call this to log decisions"""
    _decision_log.append({**decision, "id": len(_decision_log) + 1})
    if len(_decision_log) > 100:
        _decision_log.pop(0)
    return {"ok": True}


# ── Sentiment feed ────────────────────────────────────────────────────────

@app.get("/sentiment/recent")
async def get_sentiment_recent():
    """Return latest sentiment scores across sources"""
    if not data_manager:
        return []
    results = []
    try:
        reddit_data = await data_manager.reddit.get_trending_tickers("all-stocks")
        for item in reddit_data[:3]:
            results.append({
                "symbol": item.get("ticker", ""),
                "score": (item.get("sentiment", 0.5) - 0.5) * 2,  # Normalize to -1..1
                "post_count": item.get("mentions", 0),
                "source": "reddit",
                "timestamp": datetime.now().isoformat(),
            })
    except Exception:
        pass
    return results


# ── Watchlist ─────────────────────────────────────────────────────────────

@app.get("/watchlist")
async def get_watchlist():
    """Return configured watchlists as ticker items with live prices"""
    import yfinance as yf

    futures_map = {
        "MES": "ES=F", "MNQ": "NQ=F", "MCL": "CL=F",
        "MGC": "GC=F", "MHG": "HG=F", "MYM": "YM=F", "M2K": "RTY=F",
    }
    all_symbols = list(settings.FUTURES_WATCHLIST) + list(settings.OPTIONS_WATCHLIST)
    prices: dict = {}
    try:
        yf_tickers_map = {s: futures_map.get(s, s) for s in all_symbols}
        tickers_obj = yf.Tickers(" ".join(set(yf_tickers_map.values())))
        for sym, yf_sym in yf_tickers_map.items():
            try:
                info = tickers_obj.tickers[yf_sym].fast_info
                current = float(info.last_price) if hasattr(info, "last_price") and info.last_price else None
                prev = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else None
                chg = ((current - prev) / prev) if current and prev and prev > 0 else None
                prices[sym] = {"last_price": current, "change_pct": chg}
            except Exception:
                prices[sym] = {"last_price": None, "change_pct": None}
    except Exception:
        pass

    items = []
    names = {"MES": "Micro E-mini S&P 500", "MNQ": "Micro E-mini Nasdaq", "MCL": "Micro Crude Oil",
             "MGC": "Micro Gold", "MHG": "Micro Copper", "MYM": "Micro Dow", "M2K": "Micro Russell 2000"}
    for sym in settings.FUTURES_WATCHLIST:
        p = prices.get(sym, {})
        items.append({"symbol": sym, "name": names.get(sym, sym), "type": "futures",
                      "last_price": p.get("last_price"), "change_pct": p.get("change_pct")})
    for sym in settings.OPTIONS_WATCHLIST:
        p = prices.get(sym, {})
        items.append({"symbol": sym, "name": sym, "type": "options",
                      "last_price": p.get("last_price"), "change_pct": p.get("change_pct")})
    return items


# ── Live Prices ────────────────────────────────────────────────────────────

@app.get("/prices/snapshot")
async def get_price_snapshot(symbols: str = "SPY,QQQ,MES,MNQ"):
    """
    Get current prices and daily change % for comma-separated symbols.
    Futures micro contracts (MES, MNQ, MCL etc) are mapped to continuous contracts.
    """
    import yfinance as yf

    futures_map = {"MES": "ES=F", "MNQ": "NQ=F", "MCL": "CL=F",
                   "MGC": "GC=F", "MHG": "HG=F", "MYM": "YM=F", "M2K": "RTY=F"}
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    yf_tickers = [futures_map.get(s, s) for s in symbol_list]
    try:
        tickers = yf.Tickers(" ".join(yf_tickers))
        result = {}
        for original, yf_ticker in zip(symbol_list, yf_tickers):
            try:
                info = tickers.tickers[yf_ticker].fast_info
                current = float(info.last_price) if hasattr(info, "last_price") and info.last_price else None
                prev = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else None
                chg = ((current - prev) / prev) if current and prev and prev > 0 else None
                result[original] = {"symbol": original, "last_price": current, "prev_close": prev,
                                    "change_pct": chg, "yf_ticker": yf_ticker}
            except Exception as e:
                result[original] = {"symbol": original, "last_price": None, "prev_close": None,
                                    "change_pct": None, "error": str(e)}
        return result
    except Exception as e:
        raise HTTPException(500, f"Price fetch failed: {e}")


# ── Pipeline ──────────────────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    symbol: str
    is_futures: bool = False


@app.post("/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """Run the full 5-stage AI trading pipeline for a symbol"""
    if not trading_pipeline:
        raise HTTPException(503, "Pipeline not available (no ANTHROPIC_API_KEY)")

    result = await trading_pipeline.analyze_and_decide(req.symbol, req.is_futures)

    # Log to decision feed
    _decision_log.append({
        "id": len(_decision_log) + 1,
        "timestamp": datetime.now().isoformat(),
        "symbol": req.symbol,
        "action": result.get("final_action", "hold"),
        "confidence": result.get("confidence", 0),
        "source": "pipeline",
        "summary": result.get("summary", ""),
    })
    if len(_decision_log) > 100:
        _decision_log.pop(0)

    # Send WhatsApp alert for non-HOLD signals
    from notifications.whatsapp import get_notifier
    notifier = get_notifier()
    asyncio.create_task(notifier.alert_pipeline_result(req.symbol, result))

    return result


@app.get("/pipeline/status")
async def pipeline_status():
    """Pipeline availability and last run info"""
    return {
        "available": trading_pipeline is not None,
        "last_run": _decision_log[-1] if _decision_log else None,
        "decision_count": len(_decision_log),
    }


@app.get("/scheduler/status")
async def scheduler_status():
    """Scheduled job status"""
    if not scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })
    return {
        "running": scheduler.running,
        "jobs": jobs,
        "total_decisions_logged": len(_decision_log),
    }


@app.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config"""
    from notifications.whatsapp import get_notifier
    notifier = get_notifier()
    if not notifier.enabled:
        return {
            "status": "not_configured",
            "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
        }
    ok = await notifier.test()
    return {"status": "sent" if ok else "failed"}


# ── ThinkScript Generation ─────────────────────────────────────────────────

from agents.thinkscript_generator import ThinkScriptGeneratorAgent

thinkscript_generator: ThinkScriptGeneratorAgent | None = None

class ThinkScriptRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False

@app.post("/thinkscript/generate")
async def generate_thinkscript(req: ThinkScriptRequest):
    """Generate ThinkScript code for ThinkorSwim from JARVIS analysis"""
    gen = ThinkScriptGeneratorAgent(
        llm_client=technical_analyst.llm_client if technical_analyst else None
    )

    # Get technical analysis first
    tech_report = None
    if technical_analyst:
        try:
            tech_report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)
        except Exception:
            pass

    result = await gen.generate(
        symbol=req.symbol,
        timeframe=req.timeframe,
        technical_report=tech_report,
        script_type="study",
    )

    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "title": result.title,
        "code": result.code,
        "description": result.description,
        "usage_instructions": result.usage_instructions,
        "signals_included": result.signals_included,
        "timestamp": result.timestamp.isoformat(),
    }


# ── Macro Data (FRED) ──────────────────────────────────────────────────────

@app.get("/macro/snapshot")
async def get_macro_snapshot():
    """Current macro environment from FRED (Fed Funds, yields, VIX, unemployment)"""
    from data.fred_data import get_fred_service
    service = get_fred_service()
    try:
        snapshot = service.get_macro_snapshot()
        return snapshot
    except Exception as e:
        raise HTTPException(500, f"FRED data unavailable: {e}")


@app.get("/macro/series/{series_id}")
async def get_macro_series(series_id: str, periods: int = 24):
    """Get historical data for a FRED series (e.g. FEDFUNDS, GS10, VIXCLS)"""
    from data.fred_data import get_fred_service
    service = get_fred_service()
    history = service.get_series_history(series_id.upper(), periods)
    if not history:
        raise HTTPException(404, f"FRED series {series_id} not found or unavailable")
    return {"series_id": series_id.upper(), "data": history, "count": len(history)}



# ── Backtest endpoint ──────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol: str = "SPY"
    start: str = "2024-01-01"
    end: str = "2025-12-31"
    interval: str = "1d"
    capital: float = 100000.0
    risk_per_trade: float = 0.01


@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest):
    """Run a backtest for a symbol over the specified date range."""
    from concurrent.futures import ThreadPoolExecutor

    def _run():
        from backtest import Backtester, BacktestDataLoader, generate_signals

        loader = BacktestDataLoader()
        df = loader.load(request.symbol, request.start, request.end, request.interval)
        if df is None or df.empty:
            raise ValueError(f"No data for {request.symbol}")
        df = generate_signals(df)
        multiplier = loader.get_multiplier(request.symbol)
        backtester = Backtester(
            initial_capital=request.capital,
            risk_per_trade=request.risk_per_trade,
        )
        result = backtester.run(df, request.symbol, multiplier)
        return result.to_dict()

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _run)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
```

<!-- CODEBASE REFERENCE COMPLETE — ALL 13 MODULES DOCUMENTED -->
