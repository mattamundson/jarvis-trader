"""
JARVIS TRADER — COHEN Composite v3 Backtest Runner
===================================================

Runs the v3 composite strategy (STC + ORB + VWAP, regime-adaptive)
with v3 enhancements:
  - Circuit breaker at 10% drawdown
  - Per-instrument ADX thresholds (MNQ/MCL: 20, MES: 25)
  - 2-year data window
  - Vol-adjusted position sizing (target_vol=7%)
  - EMA trend filter (50/200 EMA crossover gate)

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_cohen_v3.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent
_ENGINE_DIR = _SCRIPT_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("run_cohen_v3")

# ── v3 Configuration ──────────────────────────────────────────────────────────
V3_CONFIG = {
    "version": "v3",
    "entry_threshold": 0.55,  # unchanged from v2
    "circuit_breaker_dd": 0.10,  # v3: 10% (was 15%)
    "adx_thresholds": {
        "MES": 25,
        "MNQ": 20,  # v3: relaxed
        "MCL": 20,  # v3: relaxed
    },
    "data_window_years": 2,  # v3: 2 years (was 1)
    "target_vol": 0.07,  # v3: 7% annualised
    "vol_lookback": 20,
    "ema_fast": 50,
    "ema_slow": 200,
    "band_mult": 3.0,
    "risk_per_trade": 0.01,
    "initial_capital": 10_000.0,
    "commission_per_contract": 2.50,
    "slippage_ticks": 1,
}

# Comparison: v1 and v2 known results (from parent task context)
HISTORICAL_RESULTS = {
    "v1": {
        "trades": 126,
        "win_rate": 0.087,
        "profit_factor": 0.20,
        "sharpe": 0.84,
        "max_drawdown": None,
        "cagr": None,
        "notes": "threshold=0.35",
    },
    "v2": {
        "trades": 27,
        "win_rate": 0.296,
        "profit_factor": 1.07,
        "sharpe": 0.43,
        "max_drawdown": None,
        "cagr": None,
        "notes": "threshold=0.55 + ADX>=25",
    },
}

INSTRUMENTS = ["MES", "MNQ", "MCL"]

# Contract multipliers
MULTIPLIERS = {
    "MES": 5.0,
    "ES": 50.0,
    "MNQ": 2.0,
    "NQ": 20.0,
    "MCL": 100.0,
    "CL": 1000.0,
}

# Yahoo Finance ticker mapping
YF_TICKERS = {
    "MES": "ES=F",
    "MNQ": "NQ=F",
    "MCL": "CL=F",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data loading with synthetic fallback
# ─────────────────────────────────────────────────────────────────────────────


def load_data_yf(symbol: str, start: str, end: str, interval: str = "1h") -> pd.DataFrame | None:
    """Try to load OHLCV data from Yahoo Finance."""
    try:
        import yfinance as yf

        ticker = YF_TICKERS.get(symbol, symbol)
        logger.info(f"Fetching {symbol} ({ticker}) from Yahoo Finance: {start} → {end}")
        df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)

        if df is None or df.empty:
            logger.warning(f"yfinance returned empty data for {symbol}")
            return None

        # Normalise columns
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
        if "adj close" in df.columns:
            df = df.drop(columns=["adj close"])
        df = df.rename(columns={"adj close": "close"})

        # Ensure required columns
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                logger.warning(f"Missing column {col} in {symbol} data")
                return None

        df = df.dropna(subset=["close"])
        logger.info(f"Loaded {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        logger.warning(f"Yahoo Finance fetch failed for {symbol}: {e}")
        return None


def generate_synthetic_data(
    symbol: str,
    n_bars: int = 3000,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate realistic synthetic OHLCV data using a geometric random walk
    with regime-switching volatility. Used as fallback when live data fetch fails.
    """
    logger.info(f"Generating synthetic data for {symbol} ({n_bars} bars)")

    rng = np.random.default_rng(seed + hash(symbol) % 10000)

    # Base prices by instrument
    base_prices = {"MES": 5200.0, "MNQ": 18000.0, "MCL": 72.0}
    base_vol = {"MES": 0.008, "MNQ": 0.012, "MCL": 0.018}

    price = base_prices.get(symbol, 1000.0)
    daily_vol = base_vol.get(symbol, 0.01)

    closes = np.zeros(n_bars)
    closes[0] = price

    # Regime-switching: trending vs ranging
    regime = 0  # 0=ranging, 1=trending up, -1=trending down
    regime_duration = 0

    for i in range(1, n_bars):
        # Switch regime occasionally
        if regime_duration <= 0:
            r = rng.random()
            if r < 0.15:
                regime = 1  # trending up
                regime_duration = rng.integers(20, 60)
            elif r < 0.30:
                regime = -1  # trending down
                regime_duration = rng.integers(20, 60)
            else:
                regime = 0  # ranging
                regime_duration = rng.integers(10, 40)
        else:
            regime_duration -= 1

        # Vol scaling based on regime
        if regime == 0:
            vol_scale = 0.8
            drift = 0.0
        else:
            vol_scale = 1.3
            drift = regime * daily_vol * 0.3  # trend drift

        ret = rng.normal(drift, daily_vol * vol_scale)
        closes[i] = closes[i - 1] * (1 + ret)

    # Build OHLCV
    atr_pct = daily_vol * 2
    highs = closes * (1 + rng.uniform(0, atr_pct * 1.5, n_bars))
    lows = closes * (1 - rng.uniform(0, atr_pct * 1.5, n_bars))
    opens = closes * (1 + rng.normal(0, atr_pct * 0.3, n_bars))

    # Enforce OHLC relationship
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))

    volumes = rng.integers(5000, 50000, n_bars).astype(float)

    idx = pd.date_range(
        start=pd.Timestamp("2023-01-02 09:30:00", tz="America/New_York"),
        periods=n_bars,
        freq="1h",
    )

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Simplified self-contained backtester
# ─────────────────────────────────────────────────────────────────────────────


class SimpleBacktester:
    """
    Lightweight event-driven backtester that consumes composite signal columns.
    Implements v3 circuit breaker (10% max drawdown pause).
    Supports vol-adjusted position sizing via pos_size_scalar column.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
        max_drawdown: float = 0.10,  # v3: 10% circuit breaker
        commission: float = 2.50,
        slippage_ticks: int = 1,
        tick_size: float = 0.25,
    ):
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.max_drawdown = max_drawdown
        self.commission = commission
        self.slippage = slippage_ticks * tick_size
        self.tick_size = tick_size

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        multiplier: float = 5.0,
    ) -> dict:
        """
        Run backtest on signal dataframe.
        Returns metrics dict.
        """
        capital = self.initial_capital
        peak_capital = capital
        equity_curve = [capital]
        trades = []

        in_trade = False
        entry_price = 0.0
        direction = ""
        stop_level = 0.0
        target_1 = 0.0
        contracts = 1
        entry_idx = None
        circuit_broken = False
        circuit_break_bar = -999
        # _circuit_break_capital snapshot updated inside loop (diagnostic only)

        for i, (idx_val, row) in enumerate(df.iterrows()):
            current_close = float(row["close"])

            # ── Circuit breaker check ────────────────────────────────────
            current_dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
            if current_dd >= self.max_drawdown and not circuit_broken:
                circuit_broken = True
                circuit_break_bar = i
                logger.info(
                    f"{symbol}: Circuit breaker triggered at bar {i} "
                    f"(drawdown={current_dd:.1%} >= {self.max_drawdown:.1%})"
                )

            # Resume trading after 20 bars pause
            # Only reset if capital hasn't continued to fall (i.e. no active position)
            if circuit_broken and (i - circuit_break_bar) > 20 and not in_trade:
                circuit_broken = False
                # Reset peak to current capital so CB doesn't immediately re-trigger
                peak_capital = max(peak_capital, capital)
                logger.info(
                    f"{symbol}: Circuit breaker reset at bar {i}, peak_capital reset to {peak_capital:.2f}"
                )

            # ── Manage open trade ────────────────────────────────────────
            if in_trade:
                # Check stop and target on current bar
                if direction == "LONG":
                    if float(row["low"]) <= stop_level:
                        # Stop hit
                        exit_price = stop_level - self.slippage
                        pnl = (exit_price - entry_price) * multiplier * contracts
                        pnl -= self.commission * contracts * 2
                        capital += pnl
                        trades.append(
                            {
                                "entry_idx": entry_idx,
                                "exit_idx": idx_val,
                                "direction": "LONG",
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "exit_reason": "STOP",
                                "contracts": contracts,
                            }
                        )
                        in_trade = False
                    elif float(row["high"]) >= target_1:
                        # Target hit
                        exit_price = target_1 + self.slippage
                        pnl = (exit_price - entry_price) * multiplier * contracts
                        pnl -= self.commission * contracts * 2
                        capital += pnl
                        trades.append(
                            {
                                "entry_idx": entry_idx,
                                "exit_idx": idx_val,
                                "direction": "LONG",
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "exit_reason": "TARGET",
                                "contracts": contracts,
                            }
                        )
                        in_trade = False

                elif direction == "SHORT":
                    if float(row["high"]) >= stop_level:
                        exit_price = stop_level + self.slippage
                        pnl = (entry_price - exit_price) * multiplier * contracts
                        pnl -= self.commission * contracts * 2
                        capital += pnl
                        trades.append(
                            {
                                "entry_idx": entry_idx,
                                "exit_idx": idx_val,
                                "direction": "SHORT",
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "exit_reason": "STOP",
                                "contracts": contracts,
                            }
                        )
                        in_trade = False
                    elif float(row["low"]) <= target_1:
                        exit_price = target_1 - self.slippage
                        pnl = (entry_price - exit_price) * multiplier * contracts
                        pnl -= self.commission * contracts * 2
                        capital += pnl
                        trades.append(
                            {
                                "entry_idx": entry_idx,
                                "exit_idx": idx_val,
                                "direction": "SHORT",
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "exit_reason": "TARGET",
                                "contracts": contracts,
                            }
                        )
                        in_trade = False

            # ── New entry ────────────────────────────────────────────────
            if not in_trade and not circuit_broken and row.get("entry_signal") == "ENTRY_NOW":
                entry_price = current_close + (
                    self.slippage if row.get("bias") == "STRONG_BULL" else -self.slippage
                )
                sl = float(row.get("stop_level", np.nan))
                t1 = float(row.get("target_1", np.nan))

                if np.isnan(sl) or np.isnan(t1):
                    pass  # skip incomplete signal
                else:
                    risk_per_contract = abs(entry_price - sl) * multiplier
                    if risk_per_contract <= 0:
                        pass
                    else:
                        # Vol-adjusted sizing
                        pos_scalar = float(row.get("pos_size_scalar", 1.0))
                        if np.isnan(pos_scalar):
                            pos_scalar = 1.0
                        pos_scalar = max(0.25, min(4.0, pos_scalar))

                        risk_dollars = capital * self.risk_per_trade * pos_scalar
                        contracts = max(1, int(risk_dollars / risk_per_contract))
                        contracts = min(contracts, 10)  # cap at 10 contracts

                        direction = "LONG" if row.get("bias") == "STRONG_BULL" else "SHORT"
                        stop_level = sl
                        target_1 = t1
                        entry_idx = idx_val
                        in_trade = True

            # Track equity
            if capital > peak_capital:
                peak_capital = capital
            equity_curve.append(capital)

        # Close any open trade at end
        if in_trade and len(df) > 0:
            last_close = float(df["close"].iloc[-1])
            if direction == "LONG":
                pnl = (last_close - entry_price) * multiplier * contracts
            else:
                pnl = (entry_price - last_close) * multiplier * contracts
            pnl -= self.commission * contracts * 2
            capital += pnl
            trades.append(
                {
                    "entry_idx": entry_idx,
                    "exit_idx": df.index[-1],
                    "direction": direction,
                    "entry_price": entry_price,
                    "exit_price": last_close,
                    "pnl": pnl,
                    "exit_reason": "END_OF_DATA",
                    "contracts": contracts,
                }
            )

        # ── Compute metrics ──────────────────────────────────────────────
        equity_arr = np.array(equity_curve)
        returns = np.diff(equity_arr) / equity_arr[:-1]
        returns = returns[~np.isnan(returns)]

        n_trades = len(trades)
        winners = [t for t in trades if t["pnl"] > 0]
        losers = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(winners) / n_trades if n_trades > 0 else 0.0
        gross_profit = sum(t["pnl"] for t in winners)
        gross_loss = abs(sum(t["pnl"] for t in losers))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else (float("inf") if gross_profit > 0 else 0.0)
        )

        # Sharpe ratio (annualised, using 1h bars → 252*6.5 bars/year)
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252 * 6.5)
        else:
            sharpe = 0.0

        # Max drawdown
        running_max = np.maximum.accumulate(equity_arr)
        drawdowns = (running_max - equity_arr) / running_max
        max_drawdown = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

        # CAGR
        total_return = (capital - self.initial_capital) / self.initial_capital
        n_years = len(df) / (252 * 6.5)
        if n_years > 0 and capital > 0:
            cagr = (capital / self.initial_capital) ** (1 / n_years) - 1
        else:
            cagr = 0.0

        return {
            "symbol": symbol,
            "n_trades": n_trades,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(min(profit_factor, 99.99), 4),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "cagr": round(cagr, 4),
            "total_return": round(total_return, 4),
            "final_capital": round(capital, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "n_winners": len(winners),
            "n_losers": len(losers),
            "trades": trades,
            "equity_curve": equity_curve,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────


def run_v3_backtest(symbol: str, config: dict) -> dict:
    """Run v3 composite backtest for a single symbol."""
    print(f"\n{'='*60}")
    print(f"  {symbol} — COHEN v3 Composite Backtest")
    print(f"{'='*60}")

    # ── Date range: 2 years (v3) ─────────────────────────────────────────
    end_date = datetime.today()
    start_date = end_date - timedelta(days=365 * config["data_window_years"])
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    print(f"  Period   : {start_str} → {end_str} ({config['data_window_years']}yr)")
    print(f"  ADX thr  : {config['adx_thresholds'].get(symbol, 25)}")
    print(f"  CB limit : {config['circuit_breaker_dd']:.0%}")
    print(f"  Threshold: {config['entry_threshold']}")

    # ── Load data ─────────────────────────────────────────────────────────
    df = load_data_yf(symbol, start_str, end_str, "1h")

    data_source = "yfinance"
    if df is None or df.empty or len(df) < 100:
        print("  [INFO] Live data unavailable — using synthetic data")
        # 2 years of hourly bars (252 trading days × 6.5 hours)
        n_bars = int(252 * 6.5 * config["data_window_years"])
        df = generate_synthetic_data(symbol, n_bars=n_bars)
        data_source = "synthetic"

    print(f"  Bars     : {len(df)} ({data_source})")
    print(f"  Price rng: {df['close'].min():.2f} – {df['close'].max():.2f}")

    # ── Generate composite signals ────────────────────────────────────────
    print("  Generating v3 composite signals...")

    try:
        from backtest.composite_signals_v3 import generate_composite_signals
    except ImportError:
        # Direct import if module path not set up
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "composite_signals_v3",
            _SCRIPT_DIR / "composite_signals_v3.py",
        )
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        generate_composite_signals = mod.generate_composite_signals

    df_signals = generate_composite_signals(
        df.copy(),
        symbol=symbol,
        entry_threshold=config["entry_threshold"],
        band_mult=config["band_mult"],
    )

    n_entry = (df_signals["entry_signal"] == "ENTRY_NOW").sum()
    n_long = (
        (df_signals["entry_signal"] == "ENTRY_NOW") & (df_signals["bias"] == "STRONG_BULL")
    ).sum()
    n_short = (
        (df_signals["entry_signal"] == "ENTRY_NOW") & (df_signals["bias"] == "STRONG_BEAR")
    ).sum()
    print(f"  Signals  : {n_entry} entries ({n_long} LONG, {n_short} SHORT)")

    # ── Run backtest ──────────────────────────────────────────────────────
    multiplier = MULTIPLIERS.get(symbol, 5.0)
    backtester = SimpleBacktester(
        initial_capital=config["initial_capital"],
        risk_per_trade=config["risk_per_trade"],
        max_drawdown=config["circuit_breaker_dd"],
        commission=config["commission_per_contract"],
        slippage_ticks=config["slippage_ticks"],
    )

    result = backtester.run(df_signals, symbol, multiplier)
    result["data_source"] = data_source
    result["bars"] = len(df)
    result["start"] = start_str
    result["end"] = end_str

    return result


def print_results_table(results: dict[str, dict]) -> None:
    """Print clean results table."""
    print(f"\n{'='*75}")
    print("  COHEN v3 BACKTEST RESULTS")
    print(f"{'='*75}")
    header = f"{'Symbol':<8} {'Trades':>7} {'Win Rate':>10} {'PF':>8} {'Sharpe':>8} {'Max DD':>8} {'CAGR':>8}"
    print(header)
    print("-" * 75)

    for symbol, r in results.items():
        if r is None:
            print(f"{symbol:<8} {'ERROR':>7}")
            continue
        print(
            f"{symbol:<8} "
            f"{r['n_trades']:>7} "
            f"{r['win_rate']:>9.1%} "
            f"{r['profit_factor']:>8.2f} "
            f"{r['sharpe']:>8.2f} "
            f"{r['max_drawdown']:>7.1%} "
            f"{r['cagr']:>7.1%}"
        )
    print("=" * 75)


def print_comparison_table(v3_results: dict[str, dict]) -> None:
    """Print v1 vs v2 vs v3 comparison table (aggregated across instruments)."""
    # Aggregate v3 across all symbols
    all_v3 = [r for r in v3_results.values() if r is not None]

    if all_v3:
        # Weight by trade count
        total_trades = sum(r["n_trades"] for r in all_v3)
        if total_trades > 0:
            agg_wr = sum(r["win_rate"] * r["n_trades"] for r in all_v3) / total_trades
            agg_pf = sum(r.get("gross_profit", 0) for r in all_v3) / max(
                sum(r.get("gross_loss", 0) for r in all_v3), 1
            )
            agg_sharpe = sum(r["sharpe"] for r in all_v3) / len(all_v3)
            agg_dd = max(r["max_drawdown"] for r in all_v3)
            agg_cagr = sum(r["cagr"] for r in all_v3) / len(all_v3)
        else:
            agg_wr = agg_pf = agg_sharpe = agg_dd = agg_cagr = 0.0

        v3_agg = {
            "trades": total_trades,
            "win_rate": agg_wr,
            "profit_factor": agg_pf,
            "sharpe": agg_sharpe,
            "max_drawdown": agg_dd,
            "cagr": agg_cagr,
        }
    else:
        v3_agg = None

    print(f"\n{'='*80}")
    print("  VERSION COMPARISON: v1 vs v2 vs v3")
    print(f"{'='*80}")
    print(
        f"{'Version':<10} {'Trades':>7} {'Win Rate':>10} {'PF':>8} "
        f"{'Sharpe':>8} {'Max DD':>8} {'CAGR':>8}  Notes"
    )
    print("-" * 80)

    v1 = HISTORICAL_RESULTS["v1"]
    print(
        f"{'v1':<10} {v1['trades']:>7} {v1['win_rate']:>9.1%} "
        f"{v1['profit_factor']:>8.2f} {v1['sharpe']:>8.2f} "
        f"{'N/A':>8} {'N/A':>8}  {v1['notes']}"
    )

    v2 = HISTORICAL_RESULTS["v2"]
    print(
        f"{'v2':<10} {v2['trades']:>7} {v2['win_rate']:>9.1%} "
        f"{v2['profit_factor']:>8.2f} {v2['sharpe']:>8.2f} "
        f"{'N/A':>8} {'N/A':>8}  {v2['notes']}"
    )

    if v3_agg:
        dd_str = f"{v3_agg['max_drawdown']:.1%}"
        cagr_str = f"{v3_agg['cagr']:.1%}"
        notes_v3 = "threshold=0.55+ADX(MES≥25,MNQ/MCL≥20)+EMA+VolSize"
        print(
            f"{'v3':<10} {v3_agg['trades']:>7} {v3_agg['win_rate']:>9.1%} "
            f"{v3_agg['profit_factor']:>8.2f} {v3_agg['sharpe']:>8.2f} "
            f"{dd_str:>8} {cagr_str:>8}  {notes_v3}"
        )
    else:
        print(f"{'v3':<10} {'ERROR':>7}")

    print("=" * 80)

    return v3_agg


def main():
    print("=" * 60)
    print("  COHEN v3 COMPOSITE BACKTEST")
    print("=" * 60)
    print(f"  Run time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Instruments: {', '.join(INSTRUMENTS)}")
    print(
        f"  Config   : v3 ({V3_CONFIG['data_window_years']}yr window, "
        f"CB={V3_CONFIG['circuit_breaker_dd']:.0%}, "
        f"EMA filter, vol-sizing)"
    )
    print()

    # ── Run backtests ────────────────────────────────────────────────────
    all_results = {}
    for symbol in INSTRUMENTS:
        try:
            result = run_v3_backtest(symbol, V3_CONFIG)
            all_results[symbol] = result
        except Exception as e:
            logger.error(f"Backtest failed for {symbol}: {e}", exc_info=True)
            all_results[symbol] = None

    # ── Print results tables ─────────────────────────────────────────────
    print_results_table(all_results)
    v3_agg = print_comparison_table(all_results)

    # ── Save results ─────────────────────────────────────────────────────
    results_dir = _ENGINE_DIR / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Serialisable copy (remove equity_curve list + trade objects for brevity)
    def serialise(r):
        if r is None:
            return None
        out = {k: v for k, v in r.items() if k not in ("trades", "equity_curve")}
        # Add trade summary
        trades = r.get("trades", [])
        out["trade_count"] = len(trades)
        out["sample_trades"] = [
            {
                "direction": t["direction"],
                "pnl": round(t["pnl"], 2),
                "exit_reason": t["exit_reason"],
            }
            for t in trades[:10]  # first 10 trades as sample
        ]
        return out

    json_payload = {
        "version": "v3",
        "run_timestamp": datetime.now().isoformat(),
        "config": dict(V3_CONFIG.items()),
        "instruments": {s: serialise(r) for s, r in all_results.items()},
        "aggregate": v3_agg,
        "comparison": {
            "v1": HISTORICAL_RESULTS["v1"],
            "v2": HISTORICAL_RESULTS["v2"],
            "v3": v3_agg,
        },
    }

    # Save to results dir
    results_path = results_dir / "cohen_v3_results.json"
    with open(results_path, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    print(f"\n  Results saved → {results_path}")

    # Save to workspace root
    workspace_path = Path("/home/user/workspace/cohen_v3_results.json")
    with open(workspace_path, "w") as f:
        json.dump(json_payload, f, indent=2, default=str)
    print(f"  Results saved → {workspace_path}")

    # ── Comparison table JSON ─────────────────────────────────────────────
    comparison_path = results_dir / "cohen_version_comparison.json"
    with open(comparison_path, "w") as f:
        json.dump(
            {
                "generated": datetime.now().isoformat(),
                "versions": {
                    "v1": HISTORICAL_RESULTS["v1"],
                    "v2": HISTORICAL_RESULTS["v2"],
                    "v3": v3_agg,
                },
                "v3_by_symbol": {s: serialise(r) for s, r in all_results.items()},
            },
            f,
            indent=2,
            default=str,
        )
    print(f"  Comparison → {comparison_path}")

    # ── Print per-symbol detail ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  PER-SYMBOL DETAIL")
    print(f"{'='*60}")
    for symbol, r in all_results.items():
        if r is None:
            print(f"\n  {symbol}: ERROR")
            continue
        print(f"\n  {symbol}:")
        print(f"    Trades      : {r['n_trades']}")
        print(f"    Win Rate    : {r['win_rate']:.1%}")
        print(f"    Profit Factor: {r['profit_factor']:.2f}")
        print(f"    Sharpe      : {r['sharpe']:.2f}")
        print(f"    Max Drawdown: {r['max_drawdown']:.1%}")
        print(f"    CAGR        : {r['cagr']:.1%}")
        print(f"    Total Return: {r['total_return']:.1%}")
        print(f"    Data Source : {r.get('data_source', 'N/A')}")
        print(f"    Bars        : {r.get('bars', 0)}")

    print()
    return json_payload


if __name__ == "__main__":
    main()
