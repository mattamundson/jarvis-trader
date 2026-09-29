"""
Transaction Cost Model (TCM) — Strategy C+ Weekly ETF Rebalancing
==================================================================
Computes realistic all-in execution costs for weekly ETF rebalancing.

Cost components:
  1. ETF expense ratios (annual, pro-rated to weekly)
  2. Bid-ask spread (2-way, per rebalance)
  3. Market impact / slippage (MOC or MKT order execution)
  4. Broker commissions (per-trade)

All costs expressed as a fraction of position value (e.g., 0.0015 = 15 bps).

Default calibration (T1-3, 2026-06-17):
  ETF expense ratios (annualized):
    SPY:  0.0945%  XLK:  0.0895%  QQQ:  0.20%
    EFA:  0.32%    USMV: 0.15%    MTUM: 0.15%
    XLV:  0.0895%  IEF:  0.15%    SHY:  0.15%
  Spread (one-way): SPY/QQQ/XLK/XLV ~0.01%, EFA/IEF/SHY ~0.02%
  Slippage:
    MOC Friday: 0.02% (low market-impact, end-of-day crossing)
    MKT Monday: 0.05% (gap risk + intraday spread)
  Commission: $0.005/share → ~0.10 bps on SPY@500 (immaterial)

T1-5 note: MOC Friday is recommended over MKT Monday.
  - Eliminates weekend gap risk
  - No Monday open slippage (gapping, thin pre-market)
  - MOC fills at official closing price — auditable, reproducible
  - Only downside: signal lag (execute Friday instead of Monday)
    is offset by T+1 lag already in the signal generator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# ── ETF Annual Expense Ratios ─────────────────────────────────────────────────
# Source: fund prospectuses as of 2026-06-01
ETF_EXPENSE_RATIOS: Dict[str, float] = {
    "SPY":  0.000945,
    "QQQ":  0.0020,
    "XLK":  0.000895,
    "EFA":  0.0032,
    "USMV": 0.0015,
    "MTUM": 0.0015,
    "XLV":  0.000895,
    "IEF":  0.0015,
    "SHY":  0.0015,
    # Defaults for any unlisted ETF
    "_default": 0.0020,
}

# ── Bid-Ask Spread (one-way, at mid) ─────────────────────────────────────────
# Liquid large-caps: ~1 bp each side; less liquid: ~2 bp each side
ETF_SPREAD_ONEWAY: Dict[str, float] = {
    "SPY":  0.0001,
    "QQQ":  0.0001,
    "XLK":  0.0001,
    "XLV":  0.0001,
    "EFA":  0.0002,
    "USMV": 0.0002,
    "MTUM": 0.0002,
    "IEF":  0.0002,
    "SHY":  0.0001,
    "_default": 0.0002,
}

# ── Execution Slippage ────────────────────────────────────────────────────────
SLIPPAGE_MOC_FRIDAY = 0.0002    # 2 bps — MOC order, end-of-day cross
SLIPPAGE_MKT_MONDAY = 0.0005    # 5 bps — MKT open order, gap + thin book
SLIPPAGE_TWAP_30MIN  = 0.0003   # 3 bps — TWAP over first 30min Monday

# ── Commission (per-share, round-trip) ───────────────────────────────────────
COMMISSION_PER_SHARE = 0.005    # $0.005/share = ~1 bp on SPY@500, immaterial

WEEKS_PER_YEAR = 52.18


@dataclass
class PositionCostEstimate:
    """Full cost breakdown for a single position/rebalance."""
    ticker: str
    position_value: float
    expense_ratio_weekly: float
    spread_cost: float          # 2-way (buy + sell spread)
    slippage: float
    commission_est: float
    total_cost: float
    total_cost_bps: float


class TransactionCostModel:
    """
    Weekly ETF rebalancing cost model for Strategy C+.

    Parameters
    ----------
    execution_mode : str
        'moc_friday' (recommended), 'mkt_monday', or 'twap_30min'
    include_expense_ratio : bool
        Whether to include ETF expense ratios (default True)
    include_spread : bool
        Whether to include bid-ask spread costs (default True)
    include_slippage : bool
        Whether to include execution slippage (default True)
    rebalance_threshold_pct : float
        Only incur spread/slippage costs if position weight changes by more
        than this threshold. Reduces turnover costs on stable weeks. Default 0.01 (1%).
    """

    def __init__(
        self,
        execution_mode: str = "moc_friday",
        include_expense_ratio: bool = True,
        include_spread: bool = True,
        include_slippage: bool = True,
        rebalance_threshold_pct: float = 0.01,
    ):
        self.execution_mode = execution_mode
        self.include_expense_ratio = include_expense_ratio
        self.include_spread = include_spread
        self.include_slippage = include_slippage
        self.rebalance_threshold_pct = rebalance_threshold_pct

        # Slippage by mode
        _slippage_map = {
            "moc_friday":  SLIPPAGE_MOC_FRIDAY,
            "mkt_monday":  SLIPPAGE_MKT_MONDAY,
            "twap_30min":  SLIPPAGE_TWAP_30MIN,
        }
        self._slippage_rate = _slippage_map.get(execution_mode, SLIPPAGE_MOC_FRIDAY)

    def weekly_cost_rate(
        self,
        ticker: str,
        is_rebalancing: bool = True,
    ) -> float:
        """
        Total cost rate (as fraction of position value) for one week of holding.

        Parameters
        ----------
        ticker : str
            ETF ticker symbol
        is_rebalancing : bool
            True if position is being bought/sold this week (spread + slippage apply).
            False if position is just being held (only expense ratio applies).

        Returns
        -------
        float : cost fraction (e.g., 0.0003 = 3 bps)
        """
        total = 0.0

        # 1. Expense ratio (weekly fraction)
        if self.include_expense_ratio:
            annual_er = ETF_EXPENSE_RATIOS.get(ticker, ETF_EXPENSE_RATIOS["_default"])
            total += annual_er / WEEKS_PER_YEAR

        if not is_rebalancing:
            return total

        # 2. Bid-ask spread (2-way: you pay spread on buy AND sell)
        if self.include_spread:
            spread = ETF_SPREAD_ONEWAY.get(ticker, ETF_SPREAD_ONEWAY["_default"])
            total += 2 * spread  # round-trip

        # 3. Execution slippage
        if self.include_slippage:
            total += self._slippage_rate

        return total

    def estimate_portfolio_weekly_cost(
        self,
        holdings: dict,
        prev_holdings: dict,
        portfolio_value: float = 100_000.0,
    ) -> dict:
        """
        Estimate total weekly cost for a portfolio rebalance.

        Parameters
        ----------
        holdings : dict[ticker, weight]
            New target weights (e.g., {'XLK': 0.277, 'QQQ': 0.277, 'SHY': 0.446})
        prev_holdings : dict[ticker, weight]
            Prior week's weights (for turnover detection)
        portfolio_value : float
            Notional portfolio value for dollar estimates

        Returns
        -------
        dict with total_cost_pct, total_cost_dollars, breakdown_by_ticker
        """
        total_cost_pct = 0.0
        breakdown = {}

        all_tickers = set(list(holdings.keys()) + list(prev_holdings.keys()))

        for ticker in all_tickers:
            new_wt = holdings.get(ticker, 0.0)
            old_wt = prev_holdings.get(ticker, 0.0)
            avg_wt = (new_wt + old_wt) / 2.0

            # Determine if we're rebalancing this position
            wt_change = abs(new_wt - old_wt)
            is_rebalancing = wt_change > self.rebalance_threshold_pct

            if avg_wt < 0.001:
                continue  # Negligible position

            rate = self.weekly_cost_rate(ticker, is_rebalancing=is_rebalancing)
            position_cost_pct = avg_wt * rate
            total_cost_pct += position_cost_pct

            breakdown[ticker] = {
                "weight": round(avg_wt, 4),
                "wt_change": round(wt_change, 4),
                "is_rebalancing": is_rebalancing,
                "cost_rate_bps": round(rate * 10000, 2),
                "position_cost_bps": round(position_cost_pct * 10000, 2),
            }

        return {
            "total_cost_pct": round(total_cost_pct, 6),
            "total_cost_bps": round(total_cost_pct * 10000, 3),
            "total_cost_dollars": round(total_cost_pct * portfolio_value, 2),
            "annual_drag_pct": round(total_cost_pct * WEEKS_PER_YEAR * 100, 3),
            "execution_mode": self.execution_mode,
            "breakdown": breakdown,
        }

    def annual_cost_summary(
        self,
        avg_holdings: dict,
        avg_rebalance_rate: float = 0.80,
    ) -> dict:
        """
        Estimate annual cost drag for a typical portfolio configuration.

        Parameters
        ----------
        avg_holdings : dict[ticker, weight]
            Representative average weekly holdings
        avg_rebalance_rate : float
            Fraction of weeks with actual rebalancing (default 0.80)

        Returns
        -------
        dict with annual_cost_pct and component breakdown
        """
        # Weekly cost assuming avg_rebalance_rate weeks have full costs
        weekly_rebal = self.estimate_portfolio_weekly_cost(
            avg_holdings, {t: 0 for t in avg_holdings}  # assume full turnover
        )
        weekly_hold = self.estimate_portfolio_weekly_cost(
            avg_holdings, avg_holdings  # no turnover
        )

        blended_weekly = (
            avg_rebalance_rate * weekly_rebal["total_cost_pct"]
            + (1 - avg_rebalance_rate) * weekly_hold["total_cost_pct"]
        )
        annual_pct = blended_weekly * WEEKS_PER_YEAR

        return {
            "annual_drag_pct": round(annual_pct * 100, 3),
            "annual_drag_bps": round(annual_pct * 10000, 1),
            "weekly_rebal_cost_bps": round(weekly_rebal["total_cost_bps"], 2),
            "weekly_hold_cost_bps": round(weekly_hold["total_cost_bps"], 2),
            "execution_mode": self.execution_mode,
            "note": (
                "MOC Friday reduces slippage 5bps→2bps vs MKT Monday. "
                "Annual drag estimate assumes 80% rebalance rate."
            ),
        }
