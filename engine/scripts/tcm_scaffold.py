"""
Transaction Cost Model (TCM) Scaffold — Phase 0 HB-5
======================================================
Addresses HB-5: "No transaction cost model — ALL backtest metrics are fictional."

This module provides a realistic cost model for all JARVIS instruments.
It is a SCAFFOLD — it provides calibrated estimates and the correct interface
so every backtest and live signal can apply costs consistently.

All metrics (Sharpe, Calmar, WFE) reported before this module was in place
are PRE-TCM and should be marked as such. After TCM is wired in, expect:
  - ETF strategies (Strategy C+): Sharpe ↓ ~0.1-0.2 (low turnover saves them)
  - Futures strategies (MCL/MNQ): Sharpe ↓ 0.3-0.8 (higher per-trade costs)
  - RL policy (MES PPO-LSTM): Sharpe ↓ 0.5-1.5 (very high turnover)

Usage:
    from engine.scripts.tcm_scaffold import TCM
    
    # Single trade
    cost = TCM.round_trip("MES", quantity=1, price=5600.0)
    
    # Adjust a returns series
    returns_net = TCM.apply_to_returns(returns, trades_df, capital=10_000)
    
    # Get cost summary for a backtest
    summary = TCM.backtest_cost_summary(trades_df, capital=10_000)

Run standalone:
    python3 -m engine.scripts.tcm_scaffold --instrument MES --price 5600 --qty 1
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── Per-instrument cost table ─────────────────────────────────────────────────
# All costs are per CONTRACT or per SHARE, in USD, per SIDE.
# Round-trip cost = 2 × per-side cost (entry + exit).
#
# Futures (CME/NYMEX):
#   Exchange fee + NFA + clearing. Source: IBKR fee schedule 2026.
#   MES/MNQ: $0.35 exchange + $0.02 NFA + $0.35 clearing = $0.72/side
#   Slippage: 1 tick adverse. MES tick = $1.25, MNQ tick = $0.50.
#
# ETFs (equities):
#   IBKR tiered: ~$0.005/share (capped at 1% of trade value for small lots).
#   Slippage: ~0.5 bps on ETFs (tight bid-ask, high liquidity).

@dataclass(frozen=True)
class InstrumentCosts:
    """Cost parameters for a single instrument."""
    commission_per_side: float       # USD per contract/share per side
    slippage_per_side: float         # USD per contract/share per side (1-tick estimate)
    tick_size: float                 # Used to compute slippage in ticks
    tick_value: float                # USD value of one tick
    instrument_type: str             # "futures" or "equity"
    notes: str = ""


COST_TABLE: dict[str, InstrumentCosts] = {
    # ── Futures ──────────────────────────────────────────────────────────────
    "MES": InstrumentCosts(
        commission_per_side=0.72,
        slippage_per_side=1.25,   # 1-tick @ $1.25/tick (conservative market open)
        tick_size=0.25,
        tick_value=1.25,
        instrument_type="futures",
        notes="Micro E-mini S&P 500. 1 tick = 0.25 pts = $1.25",
    ),
    "MNQ": InstrumentCosts(
        commission_per_side=0.72,
        slippage_per_side=0.50,   # 1-tick @ $0.50/tick
        tick_size=0.25,
        tick_value=0.50,
        instrument_type="futures",
        notes="Micro E-mini Nasdaq-100. 1 tick = 0.25 pts = $0.50",
    ),
    "MCL": InstrumentCosts(
        commission_per_side=0.85,
        slippage_per_side=1.00,   # 1-tick @ $1.00/tick (crude oil spread wider)
        tick_size=0.01,
        tick_value=1.00,
        instrument_type="futures",
        notes="Micro WTI Crude Oil. 1 tick = $0.01/bbl × 100 = $1.00",
    ),
    "MGC": InstrumentCosts(
        commission_per_side=0.85,
        slippage_per_side=1.00,   # 1-tick @ $0.10/troy oz × 10 oz = $1.00
        tick_size=0.10,
        tick_value=1.00,
        instrument_type="futures",
        notes="Micro Gold. 1 tick = $0.10/troy oz × 10 oz = $1.00",
    ),
    "ES": InstrumentCosts(
        commission_per_side=1.28,
        slippage_per_side=12.50,  # 1-tick @ $12.50/tick (full E-mini)
        tick_size=0.25,
        tick_value=12.50,
        instrument_type="futures",
        notes="E-mini S&P 500. 1 tick = 0.25 pts = $12.50",
    ),
    "NQ": InstrumentCosts(
        commission_per_side=1.28,
        slippage_per_side=5.00,
        tick_size=0.25,
        tick_value=5.00,
        instrument_type="futures",
        notes="E-mini Nasdaq-100. 1 tick = 0.25 pts = $5.00",
    ),
    # ── Equities / ETFs ──────────────────────────────────────────────────────
    "XLK": InstrumentCosts(
        commission_per_side=0.005,   # $0.005/share IBKR tiered
        slippage_per_side=0.01,      # ~0.5 bps × ~$200/share ≈ $0.01/share
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="Technology Select Sector SPDR. Very liquid.",
    ),
    "QQQ": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.012,     # ~0.5 bps × ~$480 ≈ $0.024 round-trip
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="Invesco QQQ Trust. Extremely liquid.",
    ),
    "SPY": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.02,
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="SPDR S&P 500 ETF Trust. Most liquid equity instrument.",
    ),
    "SHY": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.001,     # Treasury ETF — negligible spread
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="iShares 1-3 Year Treasury Bond ETF. Near-zero slippage.",
    ),
    "IEF": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.002,
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="iShares 7-10 Year Treasury Bond ETF.",
    ),
    "TLT": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.005,
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="iShares 20+ Year Treasury Bond ETF.",
    ),
    "GLD": InstrumentCosts(
        commission_per_side=0.005,
        slippage_per_side=0.01,
        tick_size=0.01,
        tick_value=0.01,
        instrument_type="equity",
        notes="SPDR Gold Shares.",
    ),
}

# Default fallback for unlisted instruments
_DEFAULT_FUTURES_COSTS = InstrumentCosts(
    commission_per_side=1.00,
    slippage_per_side=2.00,
    tick_size=0.01,
    tick_value=1.00,
    instrument_type="futures",
    notes="Generic fallback — update COST_TABLE for this instrument",
)
_DEFAULT_EQUITY_COSTS = InstrumentCosts(
    commission_per_side=0.005,
    slippage_per_side=0.02,
    tick_size=0.01,
    tick_value=0.01,
    instrument_type="equity",
    notes="Generic fallback — update COST_TABLE for this instrument",
)


class TCM:
    """
    Transaction Cost Model — static methods only.
    All costs in USD.
    """

    @staticmethod
    def get_costs(symbol: str) -> InstrumentCosts:
        """Return cost parameters for a symbol, with fallback."""
        return COST_TABLE.get(symbol.upper(), _DEFAULT_EQUITY_COSTS)

    @staticmethod
    def per_side(symbol: str, quantity: int, price: float = 0.0) -> float:
        """
        Total cost for ONE SIDE of a trade (entry OR exit only).
        
        For equities: min($0.005 × qty, 1% × notional) — IBKR tiered cap.
        For futures: flat per-contract (not notional-capped).
        """
        c = TCM.get_costs(symbol)
        raw = (c.commission_per_side + c.slippage_per_side) * quantity
        if c.instrument_type == "equity" and price > 0:
            cap = 0.01 * price * quantity  # IBKR 1% of trade value cap
            return min(raw, cap)
        return raw

    @staticmethod
    def round_trip(symbol: str, quantity: int, price: float = 0.0) -> float:
        """Total round-trip cost (entry + exit) in USD."""
        return 2.0 * TCM.per_side(symbol, quantity, price)

    @staticmethod
    def round_trip_bps(symbol: str, quantity: int, price: float) -> float:
        """Round-trip cost as basis points of notional."""
        notional = quantity * price
        if notional <= 0:
            return 0.0
        return (TCM.round_trip(symbol, quantity, price) / notional) * 10_000

    @staticmethod
    def apply_to_returns(
        returns: pd.Series,
        trades: pd.DataFrame,
        capital: float = 10_000.0,
    ) -> pd.Series:
        """
        Apply transaction costs to a returns series.
        
        Parameters
        ----------
        returns : pd.Series
            Gross daily/weekly return series (indexed by date).
        trades : pd.DataFrame
            Trade log with columns: date, symbol, quantity, price.
            Each row = one trade (entry OR exit — costs applied once per row).
        capital : float
            Starting capital for scaling costs as % of portfolio.
            
        Returns
        -------
        pd.Series : Net returns after transaction costs.
        """
        if trades.empty:
            return returns.copy()

        # Aggregate costs by date
        cost_by_date: dict = {}
        for _, row in trades.iterrows():
            date = pd.Timestamp(row["date"])
            symbol = str(row.get("symbol", ""))
            qty = abs(int(row.get("quantity", 1)))
            price = float(row.get("price", 0.0))
            cost = TCM.per_side(symbol, qty, price)
            cost_by_date[date] = cost_by_date.get(date, 0.0) + cost

        cost_series = pd.Series(cost_by_date)
        cost_returns = cost_series / capital  # As fraction of capital
        cost_returns = cost_returns.reindex(returns.index, fill_value=0.0)

        net_returns = returns - cost_returns
        logger.info(
            "TCM applied: total_cost=$%.2f over %d days, avg_drag=%.4f%% daily",
            cost_series.sum(),
            len(cost_series),
            cost_returns.mean() * 100,
        )
        return net_returns

    @staticmethod
    def backtest_cost_summary(
        trades: pd.DataFrame,
        capital: float = 10_000.0,
        periods_per_year: int = 52,
    ) -> dict:
        """
        Compute aggregate cost statistics for a full backtest.
        
        Parameters
        ----------
        trades : pd.DataFrame
            Trade log with columns: symbol, quantity, price, date.
        capital : float
            Starting capital.
        periods_per_year : int
            52 for weekly, 252 for daily.
            
        Returns
        -------
        dict with keys:
            total_cost_usd, cost_per_trade_avg, annual_drag_pct,
            cost_as_pct_of_capital, n_trades, by_symbol
        """
        if trades.empty:
            return {
                "total_cost_usd": 0.0,
                "cost_per_trade_avg": 0.0,
                "annual_drag_pct": 0.0,
                "cost_as_pct_of_capital": 0.0,
                "n_trades": 0,
                "by_symbol": {},
                "warning": "No trades provided",
            }

        costs_by_symbol: dict[str, float] = {}
        total_cost = 0.0

        for _, row in trades.iterrows():
            symbol = str(row.get("symbol", "UNKNOWN"))
            qty = abs(int(row.get("quantity", 1)))
            price = float(row.get("price", 0.0))
            cost = TCM.per_side(symbol, qty, price)
            total_cost += cost
            costs_by_symbol[symbol] = costs_by_symbol.get(symbol, 0.0) + cost

        n_trades = len(trades)
        n_periods = max(1, len(trades["date"].unique()) if "date" in trades else 1)
        n_years = n_periods / periods_per_year

        return {
            "total_cost_usd": round(total_cost, 2),
            "cost_per_trade_avg": round(total_cost / n_trades, 4),
            "annual_drag_pct": round((total_cost / capital / max(n_years, 0.1)) * 100, 3),
            "cost_as_pct_of_capital": round((total_cost / capital) * 100, 4),
            "n_trades": n_trades,
            "by_symbol": {k: round(v, 2) for k, v in costs_by_symbol.items()},
            "note": (
                "TCM scaffold v1 — all costs are per-side (entry or exit). "
                "Round-trip = 2× these figures. "
                "Calibrated to IBKR tiered pricing 2026."
            ),
        }

    @staticmethod
    def strategy_c_weekly_cost(
        holdings: dict[str, float],
        capital: float = 10_000.0,
        prices: Optional[dict[str, float]] = None,
    ) -> dict:
        """
        Estimate transaction cost for one Strategy C+ weekly rebalance.
        
        Parameters
        ----------
        holdings : dict
            Symbol → target weight (e.g. {'XLK': 0.28, 'QQQ': 0.28, 'SHY': 0.44})
        capital : float
            Account value.
        prices : dict, optional
            Symbol → current price. If None, uses rough estimates.
            
        Returns
        -------
        dict with cost breakdown per symbol and total drag.
        """
        _price_estimates = {"XLK": 205.0, "QQQ": 483.0, "SHY": 86.0, "IEF": 96.0}
        prices = prices or _price_estimates
        
        breakdown = {}
        total_cost = 0.0
        
        for symbol, weight in holdings.items():
            if weight < 0.005:
                continue
            target_usd = capital * weight
            price = prices.get(symbol, 100.0)
            shares = max(1, round(target_usd / price))
            cost = TCM.round_trip(symbol, shares, price)
            cost_bps = TCM.round_trip_bps(symbol, shares, price)
            breakdown[symbol] = {
                "weight": round(weight, 4),
                "target_usd": round(target_usd, 2),
                "shares": shares,
                "round_trip_cost_usd": round(cost, 4),
                "round_trip_bps": round(cost_bps, 2),
            }
            total_cost += cost
        
        annual_drag_pct = (total_cost * 52 / capital) * 100
        
        return {
            "capital": capital,
            "total_rebalance_cost_usd": round(total_cost, 4),
            "annual_drag_pct": round(annual_drag_pct, 3),
            "by_symbol": breakdown,
            "note": (
                "Assumes full rebalance each week. "
                "Actual cost is lower when weights don't change (no rebalance needed)."
            ),
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS TCM Scaffold — cost estimator")
    parser.add_argument("--instrument", "-i", default="MES", help="Symbol (e.g. MES, XLK)")
    parser.add_argument("--price", "-p", type=float, default=5600.0, help="Current price")
    parser.add_argument("--qty", "-q", type=int, default=1, help="Quantity (contracts/shares)")
    parser.add_argument("--capital", "-c", type=float, default=10_000.0, help="Account capital")
    parser.add_argument("--strategy-c", action="store_true", help="Show Strategy C+ weekly cost")
    args = parser.parse_args()

    if args.strategy_c:
        # Friday signal holdings
        holdings = {"XLK": 0.2797, "QQQ": 0.2797, "SHY": 0.4406}
        result = TCM.strategy_c_weekly_cost(holdings, args.capital)
        print("\n=== Strategy C+ Weekly Rebalance Cost ===")
        print(f"Capital: ${result['capital']:,.0f}")
        print(f"Total cost: ${result['total_rebalance_cost_usd']:.4f}")
        print(f"Annual drag (52× rebalances): {result['annual_drag_pct']:.3f}%")
        print("\nBy symbol:")
        for sym, d in result["by_symbol"].items():
            print(f"  {sym:<6} {d['shares']} shares  target=${d['target_usd']:.0f}  "
                  f"cost=${d['round_trip_cost_usd']:.4f}  ({d['round_trip_bps']:.2f} bps)")
        print(f"\nNote: {result['note']}")
        return

    c = TCM.get_costs(args.instrument)
    rt = TCM.round_trip(args.instrument, args.qty, args.price)
    rt_bps = TCM.round_trip_bps(args.instrument, args.qty, args.price)
    notional = args.qty * args.price
    pct_of_capital = rt / args.capital * 100

    print(f"\n=== TCM: {args.instrument.upper()} ===")
    print(f"Instrument type: {c.instrument_type}")
    print(f"Quantity:        {args.qty} {'contracts' if c.instrument_type == 'futures' else 'shares'}")
    print(f"Price:           ${args.price:,.2f}")
    print(f"Notional:        ${notional:,.2f}")
    print(f"")
    print(f"Commission/side: ${c.commission_per_side:.4f}")
    print(f"Slippage/side:   ${c.slippage_per_side:.4f} (1-tick estimate)")
    print(f"Total per side:  ${TCM.per_side(args.instrument, args.qty, args.price):.4f}")
    print(f"Round-trip cost: ${rt:.4f}  ({rt_bps:.2f} bps of notional)")
    print(f"As % of capital: {pct_of_capital:.4f}%  (capital=${args.capital:,.0f})")
    print(f"")
    print(f"Notes: {c.notes}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _main()
