"""
JARVIS TRADER — Options vertical-spread backtest runner (SPY/QQQ) [Strategy Novel #3]
=====================================================================================
Replays a fixed, a-priori systematic signal rule against REAL historical SPY/QQQ
options chains (via ``backtest.options_chain_cache.PolygonChainCache``) using the
``backtest.options_backtester.OptionsBacktester`` scaffold, and emits results in the
gate-v2 research-script JSON format so ``scripts/gate_v2_orchestrator.py`` can score it.

A-PRIORI CONFIG (locked before any data is seen — NO post-hoc tuning)
--------------------------------------------------------------------
* Signal rule:      RSI(14) mean reversion on daily closes.
                    RSI < 35  -> LONG  (bull call debit spread)
                    RSI > 65  -> SHORT (bear put debit spread)
                    Cooldown: 10 trading days after each signal (no clustering).
* Spread:           vertical debit spread, long leg nearest 0.30 |delta|, width 1 strike.
* Expiry:           nearest monthly (3rd Friday) with DTE >= 30.
* Cost model:       mid = daily close/VWAP; bid/ask = mid * (1 ± 2%); FlatSlippage
                    (+5 bps) applied by the scaffold. Contract multiplier x100.

Because n_combos=1, DSR in gate v2 sees NO selection bias from grid search — this is
the honest single-config claim, and the gate's core thresholds apply as-is.

Usage (from engine/, after building the chain cache):
    set POLYGON_API_KEY=...   (or rely on engine .env via load_dotenv)
    .venv/Scripts/python -m scripts.options_vertical_spread_backtest --symbol SPY \
        --start 2024-07-01 --end 2025-12-31 --output backtest/results/SPY_options_rank1.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.options_backtester import OptionsBacktester, Signal  # noqa: E402
from backtest.options_chain_cache import PolygonChainCache  # noqa: E402

logger = logging.getLogger(__name__)

CONTRACT_MULTIPLIER = 100  # SPY/QQQ options: 100 shares per contract
INITIAL_CAPITAL = 10_000.0


# ---------------------------------------------------------------------------
# Signal generation — deterministic, a-priori RSI mean reversion
# ---------------------------------------------------------------------------


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI over a close series. First ``period`` values are None."""
    out: list[float] = [None] * len(closes)  # type: ignore[list-item]
    if len(closes) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def generate_signals(
    bars: dict[date, dict],
    symbol: str,
    rsi_buy: float = 35.0,
    rsi_sell: float = 65.0,
    cooldown_days: int = 10,
) -> list[Signal]:
    """Signals from a locked RSI(14) mean-reversion rule (no tuning)."""
    trading_days = sorted(bars)
    closes = [bars[d]["close"] for d in trading_days]
    rsi_vals = rsi(closes, 14)

    signals: list[Signal] = []
    last_signal_idx = -10**9
    for i, d in enumerate(trading_days):
        if i < 15 or rsi_vals[i] is None:
            continue
        if i - last_signal_idx < cooldown_days:
            continue
        r = rsi_vals[i]
        side: str | None = None
        if r <= rsi_buy:
            side = "LONG"
        elif r >= rsi_sell:
            side = "SHORT"
        if side is None:
            continue
        signals.append(
            Signal(
                timestamp=datetime.combine(d, datetime.min.time()),
                symbol=symbol,
                side=side,
                confidence=1.0,
            )
        )
        last_signal_idx = i
    return signals


class _ListSignalSource:
    """Trivial SignalSource adapter over a pre-built list."""

    def __init__(self, signals: list[Signal]):
        self._signals = signals

    def signals(self) -> list[Signal]:
        return list(self._signals)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _target_delta_strike(spot: float, sigma: float, years: float, side: str) -> float:
    """Theoretical strike whose Black-Scholes delta is 0.30 (mechanical rule).

    call: d1 = Phi^-1(0.30) = -0.5244  -> K = S*exp(+|d1|*sigma*sqrt(T) + 0.5*sigma^2*T)
    put:  d1 = Phi^-1(0.70) = +0.5244  -> K = S*exp(-|d1|*sigma*sqrt(T) + 0.5*sigma^2*T)
    """
    import math

    d1 = -0.5244 if side.upper() == "LONG" else 0.5244
    return spot * math.exp(-d1 * sigma * math.sqrt(years) + 0.5 * sigma * sigma * years)


def _realized_vol(bars: dict[date, dict], as_of: date, window: int = 20) -> float:
    """Annualised realized vol from the last ``window`` closes <= as_of."""
    import math

    import numpy as np

    dates = sorted(d for d in bars if d <= as_of)[- (window + 1):]
    if len(dates) < 10:
        return 0.15
    closes = np.array([bars[d]["close"] for d in dates], dtype=float)
    logrets = np.diff(np.log(closes))
    return float(np.std(logrets, ddof=1) * math.sqrt(252))


class _BandedChainProvider:
    """ChainProvider adapter that applies a focused strike band + step per
    signal date (deterministic a-priori rule; keeps API calls bounded)."""

    def __init__(self, cache: PolygonChainCache, bands: dict[date, tuple[float, float]], step: float):
        self._cache = cache
        self._bands = bands
        self._step = step

    def get_chain(self, symbol: str, as_of: datetime, target_dte: int):
        band = self._bands.get(as_of.date())
        if band is not None:
            return self._cache.get_chain(
                symbol, as_of, target_dte, strike_band=band, strike_step=self._step
            )
        return self._cache.get_chain(symbol, as_of, target_dte)


def build_focused_bands(
    bars: dict[date, dict],
    signals: list[Signal],
    target_dte: int = 30,
    step: float = 5.0,
) -> dict[date, tuple[float, float]]:
    """Per-signal strike band centered on the theoretical 30-delta strike.

    Band = [K_target - 2 rungs, K_target + 3 rungs]: margin on the ATM side
    for delta drift, extension OTM for the short leg. No outcome data is used
    — the rule is purely mechanical from closes (a-priori).
    """
    bands: dict[date, tuple[float, float]] = {}
    for sig in signals:
        d = sig.timestamp.date()
        spot = bars[d]["close"]
        sigma = _realized_vol(bars, d)
        k = _target_delta_strike(spot, sigma, target_dte / 365.0, sig.side)
        lo = max(k - 2 * step, 0.9 * spot)
        hi = min(k + 3 * step, 1.15 * spot)
        bands[d] = (lo, hi)
    return bands


def run_backtest(
    symbol: str,
    start: date,
    end: date,
    cache: PolygonChainCache,
    *,
    target_dte: int = 30,
    target_delta: float = 0.30,
    width_strikes: int = 1,
    contracts_per_signal: int = 1,
    strike_step: float = 5.0,
) -> dict:
    """Run the scaffold over the window; return the gate-v2 results dict."""
    t0 = time.time()

    # Underlying bars: fetch a padded window so expiries past `end` resolve too.
    bars = cache.get_underlying_bars(
        symbol, start - timedelta(days=15), end + timedelta(days=75)
    )
    trading_days = sorted(d for d in bars if start <= d <= end)
    if not trading_days:
        raise RuntimeError(f"no underlying bars in [{start}, {end}] for {symbol}")

    # Signals over the in-window trading days only (rule is symbol-agnostic).
    in_window = {d: bars[d] for d in trading_days}
    raw_signals = generate_signals(in_window, symbol)

    # Focused strike bands (mechanical a-priori rule) + banded chain provider.
    bands = build_focused_bands(bars, raw_signals, target_dte=target_dte, step=strike_step)
    provider = _BandedChainProvider(cache, bands, step=strike_step)

    # Underlying price at each expiry (close on the expiry day).
    underlying_at_expiry: dict[date, float] = {}
    for d, row in bars.items():
        if row["close"] > 0:
            underlying_at_expiry[d] = row["close"]

    bt = OptionsBacktester(
        chain_provider=provider,
        signal_source=_ListSignalSource(raw_signals),
        target_dte=target_dte,
        target_delta=target_delta,
        width_strikes=width_strikes,
        contracts_per_signal=contracts_per_signal,
    )
    result = bt.run(underlying_at_expiry)

    # Convert premium-point P&L to dollars (x100 multiplier x contracts).
    trades_out = []
    net_pnl = 0.0
    for trade in result.trades:
        pnl_usd = trade.pnl_usd * CONTRACT_MULTIPLIER * contracts_per_signal
        net_pnl += pnl_usd
        trades_out.append(
            {
                "entry_time": trade.signal.timestamp.strftime("%Y-%m-%d"),
                "exit_time": trade.spread.long_leg.contract.expiry.isoformat(),
                "entry": round(trade.spread.net_debit * CONTRACT_MULTIPLIER, 2),
                "exit": round(
                    (trade.spread.realised_pnl + trade.spread.net_debit)
                    * CONTRACT_MULTIPLIER,
                    2,
                ),
                "pnl": round(pnl_usd, 2),
            }
        )

    wins = sum(1 for t in trades_out if t["pnl"] > 0)
    gross_win = sum(t["pnl"] for t in trades_out if t["pnl"] > 0)
    gross_loss = -sum(t["pnl"] for t in trades_out if t["pnl"] < 0)
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    spec = {
        "strategy": "options_vertical_spread",
        "signal_rule": "rsi14_meanrev_35_65_cooldown10",
        "target_dte": target_dte,
        "target_delta": target_delta,
        "width_strikes": width_strikes,
        "contracts_per_signal": contracts_per_signal,
        "relative_half_spread": cache.relative_half_spread,
        "multiplier": CONTRACT_MULTIPLIER,
        "initial_capital": INITIAL_CAPITAL,
    }
    doc = {
        "symbol": symbol,
        "interval": "1d",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "spec": spec,
        "n_combos": 1,
        "elapsed_sec": round(time.time() - t0, 1),
        "results": [
            {
                "params": spec,
                "total_trades": len(trades_out),
                "pf": round(pf, 4) if pf != float("inf") else "inf",
                "wr": round(wins / len(trades_out), 4) if trades_out else 0.0,
                "net_pnl": round(net_pnl, 2),
                "ret_pct": round(net_pnl / INITIAL_CAPITAL * 100.0, 2),
                "trades": trades_out,
            }
        ],
    }
    logger.info(
        "[options_backtest] %s: %d trades net=%.2f PF=%s WR=%.1f%% (%.1fs)",
        symbol, len(trades_out), net_pnl, doc["results"][0]["pf"],
        (doc["results"][0]["wr"] * 100.0), doc["elapsed_sec"],
    )
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="Options vertical-spread backtest (SPY/QQQ)")
    ap.add_argument("--symbol", required=True, choices=["SPY", "QQQ"])
    ap.add_argument("--start", default="2024-07-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--output", required=True, help="gate-v2 results JSON path")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--requests-per-minute", type=float, default=5.0)
    ap.add_argument("--half-spread", type=float, default=0.02)
    ap.add_argument("--strike-step", type=float, default=5.0,
                    help="strike ladder spacing in dollars (5 = every $5 strike)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cache = PolygonChainCache(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        requests_per_minute=args.requests_per_minute,
        relative_half_spread=args.half_spread,
    )
    doc = run_backtest(
        args.symbol,
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        cache,
        strike_step=args.strike_step,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    print(f"[options_backtest] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
