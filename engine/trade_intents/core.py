"""Pure paper trade-intent risk preview math.

The browser may request a maximum quantity/risk fraction, but the server owns
final sizing. Unlike the legacy position sizer, this module deliberately allows
quantity=0 when the risk budget cannot support one unit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from utils.position_sizing import get_contract_multiplier

Direction = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]


class TradeIntentError(ValueError):
    """Raised when a paper trade intent is invalid or cannot be sized safely."""


@dataclass(frozen=True)
class TradeIntentPreview:
    symbol: str
    direction: Direction
    order_type: OrderType
    entry_price: float
    stop_loss: float
    take_profit: float
    account_equity: float
    max_risk_fraction: float
    max_trade_loss_usd: float
    risk_budget_usd: float
    contract_multiplier: float
    risk_points_per_unit: float
    risk_usd_per_unit: float
    reward_points_per_unit: float
    reward_usd_per_unit: float
    reward_risk: float
    requested_quantity: int | None
    max_quantity_by_risk: int
    max_quantity_by_contract_cap: int
    final_quantity: int
    final_risk_usd: float
    final_risk_fraction: float
    final_reward_usd: float
    can_submit: bool
    blocking_reason: str | None


def _positive(name: str, value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise TradeIntentError(f"{name} must be a positive finite number")
    return numeric


def compute_trade_intent_preview(
    *,
    symbol: str,
    direction: Direction,
    order_type: OrderType,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    account_equity: float,
    max_risk_fraction: float = 0.005,
    max_trade_loss_usd: float = 50.0,
    requested_quantity: int | None = None,
    max_contracts: int = 2,
) -> TradeIntentPreview:
    """Compute authoritative zero-allowed risk sizing for a futures intent.

    Risk budget is the LOWER of:
      * account_equity * requested max_risk_fraction, and
      * the existing SafetyLayer MAX_TRADE_LOSS_USD ceiling.

    ``requested_quantity`` is a ceiling only. The server may reduce it. If the
    risk budget cannot support one contract, final_quantity is 0 / NO TRADE.
    """
    sym = symbol.strip().upper()
    if not sym:
        raise TradeIntentError("symbol is required")
    if direction not in {"BUY", "SELL"}:
        raise TradeIntentError("direction must be BUY or SELL")
    if order_type not in {"MARKET", "LIMIT"}:
        raise TradeIntentError("order_type must be MARKET or LIMIT")

    entry = _positive("entry_price", entry_price)
    stop = _positive("stop_loss", stop_loss)
    target = _positive("take_profit", take_profit)
    equity = _positive("account_equity", account_equity)
    max_loss = _positive("max_trade_loss_usd", max_trade_loss_usd)

    risk_fraction = float(max_risk_fraction)
    if not math.isfinite(risk_fraction) or not 0 < risk_fraction <= 0.01:
        raise TradeIntentError("max_risk_fraction must be in (0, 0.01]")
    if not isinstance(max_contracts, int) or max_contracts < 1:
        raise TradeIntentError("max_contracts must be an integer >= 1")
    if requested_quantity is not None and (
        not isinstance(requested_quantity, int) or requested_quantity < 1
    ):
        raise TradeIntentError("requested_quantity must be an integer >= 1 when supplied")

    if direction == "BUY":
        if stop >= entry:
            raise TradeIntentError("BUY stop_loss must be below entry_price")
        if target <= entry:
            raise TradeIntentError("BUY take_profit must be above entry_price")
    else:
        if stop <= entry:
            raise TradeIntentError("SELL stop_loss must be above entry_price")
        if target >= entry:
            raise TradeIntentError("SELL take_profit must be below entry_price")

    multiplier = float(get_contract_multiplier(sym))
    risk_points = abs(entry - stop)
    reward_points = abs(target - entry)
    risk_per_unit = risk_points * multiplier
    reward_per_unit = reward_points * multiplier
    risk_budget = min(equity * risk_fraction, max_loss)

    max_by_risk = math.floor(risk_budget / risk_per_unit) if risk_per_unit > 0 else 0
    quantity = min(max_by_risk, max_contracts)
    if requested_quantity is not None:
        quantity = min(quantity, requested_quantity)

    final_risk = quantity * risk_per_unit
    final_reward = quantity * reward_per_unit
    final_risk_fraction = final_risk / equity if equity > 0 else 0.0
    can_submit = quantity >= 1
    blocking_reason = None if can_submit else (
        f"Risk budget ${risk_budget:.2f} cannot support one {sym} unit at "
        f"${risk_per_unit:.2f} stop risk"
    )

    return TradeIntentPreview(
        symbol=sym,
        direction=direction,
        order_type=order_type,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        account_equity=equity,
        max_risk_fraction=risk_fraction,
        max_trade_loss_usd=max_loss,
        risk_budget_usd=risk_budget,
        contract_multiplier=multiplier,
        risk_points_per_unit=risk_points,
        risk_usd_per_unit=risk_per_unit,
        reward_points_per_unit=reward_points,
        reward_usd_per_unit=reward_per_unit,
        reward_risk=reward_per_unit / risk_per_unit,
        requested_quantity=requested_quantity,
        max_quantity_by_risk=max_by_risk,
        max_quantity_by_contract_cap=max_contracts,
        final_quantity=quantity,
        final_risk_usd=final_risk,
        final_risk_fraction=final_risk_fraction,
        final_reward_usd=final_reward,
        can_submit=can_submit,
        blocking_reason=blocking_reason,
    )
