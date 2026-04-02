"""
OptionsAutoRoller — automatic position management rules.

Rules:
  - Close at 50% profit (buy back at 50% of credit received)
  - Roll at 21 DTE to next month (if still profitable)
  - Stop at 2x loss (max loss = 2 × initial credit)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger("jarvis_trader.markets.options.auto_roller")

CLOSE_AT_PROFIT_PCT = 0.50   # Close when 50% of max profit reached
ROLL_AT_DTE = 21              # Roll when 21 days to expiry
STOP_LOSS_MULTIPLIER = 2.0   # Stop when loss = 2x initial credit


@dataclass
class RollerAction:
    action: str  # "close" | "roll" | "stop" | "hold"
    reason: str
    position_id: str
    symbol: str
    current_value: float
    initial_credit: float


class OptionsAutoRoller:
    """
    Evaluates open options positions and determines management actions.
    Called each strategy cycle to check all open positions.
    """

    def evaluate_position(
        self,
        position_id: str,
        symbol: str,
        expiry_date: str,
        initial_credit: float,
        current_debit_to_close: float,
    ) -> RollerAction:
        """
        Evaluate a single options position and return the appropriate action.

        Args:
            position_id: unique position identifier
            symbol: underlying symbol
            expiry_date: YYYY-MM-DD expiry
            initial_credit: premium received when trade was opened
            current_debit_to_close: current cost to close (buy back)
        """
        try:
            expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
            dte = (expiry - date.today()).days
        except ValueError:
            dte = 999

        current_pnl = initial_credit - current_debit_to_close
        profit_pct = current_pnl / initial_credit if initial_credit > 0 else 0

        # Stop loss: current debit > 2x initial credit
        if current_debit_to_close >= initial_credit * STOP_LOSS_MULTIPLIER:
            return RollerAction(
                action="stop",
                reason=f"Stop loss: debit {current_debit_to_close:.2f} = {current_debit_to_close/initial_credit:.1f}x credit",
                position_id=position_id,
                symbol=symbol,
                current_value=current_debit_to_close,
                initial_credit=initial_credit,
            )

        # Take profit: 50% of max profit
        if profit_pct >= CLOSE_AT_PROFIT_PCT:
            return RollerAction(
                action="close",
                reason=f"Take profit: {profit_pct:.0%} of max profit",
                position_id=position_id,
                symbol=symbol,
                current_value=current_debit_to_close,
                initial_credit=initial_credit,
            )

        # Roll at 21 DTE
        if dte <= ROLL_AT_DTE:
            return RollerAction(
                action="roll",
                reason=f"Roll: {dte} DTE ≤ {ROLL_AT_DTE}",
                position_id=position_id,
                symbol=symbol,
                current_value=current_debit_to_close,
                initial_credit=initial_credit,
            )

        return RollerAction(
            action="hold",
            reason=f"Hold: {dte} DTE, P&L {profit_pct:.0%}",
            position_id=position_id,
            symbol=symbol,
            current_value=current_debit_to_close,
            initial_credit=initial_credit,
        )
