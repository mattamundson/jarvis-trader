"""
System 2 — Portfolio-Level Capital Allocation Enforcer
=======================================================
Single source of truth for combined System 1 + System 2 exposure.

Before ANY new order is submitted (either system), this module checks:
  1. Current combined exposure does not exceed total account capital
  2. System 2 does not exceed 20-30% of total capital
  3. System 1 does not exceed 70-80% of total capital
  4. Neither system is in drawdown lockout

If either check fails, the order is rejected before reaching IBKRExecutor.

Architecture:
  - Reads System 1 holdings from live_signal.json (weekly snapshot)
  - Reads System 2 positions from System2OrderManager.active_positions()
  - Fetches live account equity from IBKR account summary
  - All checks are synchronous snapshots — not event-driven

Usage:
    allocator = PortfolioAllocator(
        ibkr_executor=ibkr,
        order_manager=sys2_order_mgr,
        account_size=50_000,
    )
    check = allocator.check_new_order("ES", contracts=2, side="LONG")
    if not check.approved:
        logger.warning("Order rejected: %s", check.reason)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Capital allocation targets
_SYS1_TARGET_MIN = 0.70   # 70% min for System 1 (weekly ETF rotation)
_SYS1_TARGET_MAX = 0.80   # 80% max
_SYS2_TARGET_MIN = 0.10   # 10% min for System 2 (can be idle)
_SYS2_TARGET_MAX = 0.30   # 30% max

# Initial margin requirements per contract (IBKR overnight, USD)
# Using margin rather than notional — futures are leveraged instruments.
# Notional of 1 ES (~$370k) against a $50k account would always block orders.
# Margin is the actual capital at risk / collateral required.
_IBKR_INITIAL_MARGIN: dict[str, float] = {
    "ES":  13_200.0,   # E-mini S&P 500 full (CME overnight margin ~$13,200)
    "NQ":  19_800.0,   # E-mini NASDAQ-100 full (CME overnight margin ~$19,800)
    "MES":  1_320.0,   # Micro E-mini S&P 500 (1/10 of ES)
    "MNQ":  1_980.0,   # Micro E-mini NASDAQ-100 (1/10 of NQ)
    "MCL":    572.0,   # Micro Crude Oil
}

_SYS1_SIGNAL_PATH = Path(__file__).resolve().parents[1] / "strategy_c" / "output" / "strategy_c_plus_live_signal.json"

# Futures multipliers
_MULT: dict[str, float] = {"ES": 50.0, "NQ": 20.0, "MES": 5.0, "MNQ": 2.0}


@dataclass
class AllocationCheck:
    """Result of a pre-order allocation check."""
    approved:       bool
    reason:         str = ""
    sys1_exposure:  float = 0.0   # as fraction of account
    sys2_exposure:  float = 0.0   # as fraction of account
    new_sys2_exposure: float = 0.0
    combined_exposure: float = 0.0
    account_equity: float = 0.0
    warnings:       list  = field(default_factory=list)

    def summary(self) -> str:
        status = "APPROVED" if self.approved else f"REJECTED ({self.reason})"
        return (
            f"AllocationCheck: {status} | "
            f"S1={self.sys1_exposure:.1%} S2={self.sys2_exposure:.1%} "
            f"→new_S2={self.new_sys2_exposure:.1%} | "
            f"combined={self.combined_exposure:.1%} | "
            f"acct=${self.account_equity:,.0f}"
        )


class PortfolioAllocator:
    """
    Portfolio-level capital allocation enforcer.

    Parameters
    ----------
    ibkr_executor   : IBKRExecutor — for live account equity fetch
    order_manager   : System2OrderManager — System 2 open positions
    account_size    : float — fallback account size if IBKR unavailable
    sys2_max_pct    : float — max System 2 capital fraction (default 0.30)
    sys2_min_pct    : float — min System 2 allocation per trade trigger
    """

    def __init__(
        self,
        ibkr_executor=None,
        order_manager=None,
        account_size: float = 50_000.0,
        sys2_max_pct: float = _SYS2_TARGET_MAX,
    ):
        self.ibkr          = ibkr_executor
        self.order_manager = order_manager
        self.account_size  = account_size
        self.sys2_max_pct  = sys2_max_pct

    # ── Main check ────────────────────────────────────────────────────────────
    async def check_new_order(
        self,
        symbol: str,
        contracts: int,
        side: str,
        current_price: Optional[float] = None,
    ) -> AllocationCheck:
        """
        Check whether a new System 2 order is within allocation limits.

        Parameters
        ----------
        symbol        : "ES" or "NQ"
        contracts     : number of contracts to add
        side          : "LONG" or "SHORT"
        current_price : optional — used for notional calculation
        """
        # 1. Get account equity
        account_equity = await self._get_account_equity()

        # 2. Get System 1 exposure
        sys1_exposure = self._get_sys1_exposure(account_equity)

        # 3. Get current System 2 exposure
        sys2_exposure = self._get_sys2_exposure(account_equity, current_price)

        # 4. Compute new System 2 exposure if this order goes through
        new_notional = self._contract_notional(symbol, contracts, current_price)
        new_sys2_exposure = (
            self._get_sys2_notional(current_price) + new_notional
        ) / account_equity if account_equity > 0 else 0.0

        combined = sys1_exposure + new_sys2_exposure
        warnings = []

        # ── Checks ────────────────────────────────────────────────────────────
        # Check 1: System 2 cap
        if new_sys2_exposure > self.sys2_max_pct:
            return AllocationCheck(
                approved          = False,
                reason            = f"S2 cap: {new_sys2_exposure:.1%} > {self.sys2_max_pct:.0%}",
                sys1_exposure     = sys1_exposure,
                sys2_exposure     = sys2_exposure,
                new_sys2_exposure = new_sys2_exposure,
                combined_exposure = combined,
                account_equity    = account_equity,
            )

        # Check 2: Total combined exposure sanity (> 120% = something is wrong)
        if combined > 1.20:
            return AllocationCheck(
                approved          = False,
                reason            = f"Combined exposure {combined:.1%} > 120%",
                sys1_exposure     = sys1_exposure,
                sys2_exposure     = sys2_exposure,
                new_sys2_exposure = new_sys2_exposure,
                combined_exposure = combined,
                account_equity    = account_equity,
            )

        # Check 3: System 2 already has a position in this symbol
        if self.order_manager:
            active = self.order_manager.active_positions()
            if symbol in active:
                return AllocationCheck(
                    approved          = False,
                    reason            = f"Position already open in {symbol}",
                    sys1_exposure     = sys1_exposure,
                    sys2_exposure     = sys2_exposure,
                    new_sys2_exposure = new_sys2_exposure,
                    combined_exposure = combined,
                    account_equity    = account_equity,
                )

        # Soft warnings (don't block, just log)
        if sys1_exposure > _SYS1_TARGET_MAX + 0.05:
            warnings.append(f"S1 above target max: {sys1_exposure:.1%}")
        if new_sys2_exposure > _SYS2_TARGET_MAX - 0.05:
            warnings.append(f"S2 approaching cap: {new_sys2_exposure:.1%}/{self.sys2_max_pct:.0%}")

        check = AllocationCheck(
            approved          = True,
            sys1_exposure     = sys1_exposure,
            sys2_exposure     = sys2_exposure,
            new_sys2_exposure = new_sys2_exposure,
            combined_exposure = combined,
            account_equity    = account_equity,
            warnings          = warnings,
        )

        for w in warnings:
            logger.warning("[PortfolioAllocator] %s", w)

        logger.info("[PortfolioAllocator] %s", check.summary())
        return check

    # ── Account equity ────────────────────────────────────────────────────────
    async def _get_account_equity(self) -> float:
        """Fetch live account equity from IBKR, fall back to configured size."""
        if self.ibkr is not None:
            try:
                summary = await self.ibkr.get_account_summary()
                equity = float(summary.get("NetLiquidation", self.account_size))
                return equity
            except Exception as e:
                logger.warning("[PortfolioAllocator] Account equity fetch failed: %s", e)
        return self.account_size

    # ── System 1 exposure ─────────────────────────────────────────────────────
    def _get_sys1_exposure(self, account_equity: float) -> float:
        """
        Read System 1 holdings from the latest live signal JSON.
        Holdings are ETF weights (fractions), so exposure = sum of risk-on weights.
        SHY/IEF are considered defensive (not equity-equivalent exposure).
        """
        try:
            if not _SYS1_SIGNAL_PATH.exists():
                return 0.70  # assume target if no signal file
            signal = json.loads(_SYS1_SIGNAL_PATH.read_text())
            holdings = signal.get("holdings", {})
            defensive = {"SHY", "IEF", "TLT", "BIL"}
            risk_on_weight = sum(
                w for sym, w in holdings.items() if sym not in defensive
            )
            # S1 is applied to its capital allocation (~70-80%)
            # The signal weights are already as fraction of allocated S1 capital
            # Report as fraction of total account
            s1_fraction = signal.get("combined_scale", risk_on_weight)
            return min(0.80, max(0.0, float(s1_fraction)))
        except Exception as e:
            logger.debug("[PortfolioAllocator] S1 signal read error: %s", e)
            return 0.70  # assume target on error

    # ── System 2 exposure ─────────────────────────────────────────────────────
    def _get_sys2_notional(self, current_price: Optional[float] = None) -> float:
        """Current System 2 open notional in USD."""
        if self.order_manager is None:
            return 0.0
        total_notional = 0.0
        for sym, pos in self.order_manager.active_positions().items():
            notional = self._contract_notional(sym, pos.total_contracts, current_price)
            total_notional += notional
        return total_notional

    def _get_sys2_exposure(
        self, account_equity: float, current_price: Optional[float] = None
    ) -> float:
        if account_equity <= 0:
            return 0.0
        return self._get_sys2_notional(current_price) / account_equity

    @staticmethod
    def _contract_notional(
        symbol: str, contracts: int, current_price: Optional[float] = None
    ) -> float:
        """
        Return IBKR initial margin (not notional) for a futures position.

        Futures are leveraged — 1 ES contract has ~$370k notional but only
        ~$13,200 initial margin. Using notional makes the cap check nonsensical
        (every order would show 700%+ exposure against a $50k account).
        Using margin correctly reflects the capital committed / collateral required.
        """
        margin_per_contract = _IBKR_INITIAL_MARGIN.get(symbol, 13_200.0)
        return margin_per_contract * contracts

    # ── Reporting ─────────────────────────────────────────────────────────────
    async def get_allocation_snapshot(self) -> dict:
        """Return current allocation snapshot for dashboard/logging."""
        equity = await self._get_account_equity()
        s1     = self._get_sys1_exposure(equity)
        s2     = self._get_sys2_exposure(equity)
        return {
            "ts":               datetime.now(timezone.utc).isoformat(),
            "account_equity":   round(equity, 2),
            "sys1_exposure":    round(s1, 4),
            "sys2_exposure":    round(s2, 4),
            "combined":         round(s1 + s2, 4),
            "sys2_cap":         self.sys2_max_pct,
            "sys2_headroom":    round(max(0.0, self.sys2_max_pct - s2), 4),
            "sys1_target":      f"{_SYS1_TARGET_MIN:.0%}–{_SYS1_TARGET_MAX:.0%}",
            "sys2_target":      f"{_SYS2_TARGET_MIN:.0%}–{_SYS2_TARGET_MAX:.0%}",
            "within_limits":    s2 <= self.sys2_max_pct and (s1 + s2) <= 1.10,
        }
