"""Systematic turn-of-month order runner (default-off, dry-run only).

The last mile for the ``MES_turn_of_month`` systematic strategy described in
``docs/BETA_HARVEST_GATE_PROPOSAL.md`` / ``docs/TOM_CROSS_INDEX_RESULTS.md`` /
``live_promotion_gate.turn_of_month_current_evidence()``: a strategy_id-tagged
``OrderRequest`` generator that determines whether "today" falls in the
turn-of-month trading window and, if so, builds a dry-run order and routes it
through ``SafetyLayer.check_order()`` for a risk-check preview.

Wiring status: nothing on a live code path (main.py, pipeline.py, any
scheduler) imports this module. It exists to be called manually, or from a
future scheduled job once Amo decides to activate it -- that activation, and
the decision to actually submit the resulting order to a broker, are
explicitly OUT of scope here. ``run_tom_dry_check`` never touches
``ib_gateway`` or any execution/order-submission path; it only returns the
``RiskCheckResult`` ``SafetyLayer`` would have produced. The strategy is also
gated by the promotion pipeline already wired into ``SafetyLayer.check_order``
(``PROMOTED_STRATEGIES`` is empty today, so any resulting order is
denied/shadow-recorded there regardless of this module).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from backtest.live_promotion_gate import turn_of_month_current_evidence
from risk.safety_layer import OrderRequest, RiskCheckResult, SafetyLayer

TOM_STRATEGY_ID = "MES_turn_of_month"
TOM_SYMBOL = "MES"

# Matches session_anomaly_backtest.turn_of_month_mask's defaults: the last
# n_end trading days of a month through the first n_start trading days of
# the next.
TOM_N_END = 1
TOM_N_START = 3

_TOM_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def _trading_days_around(as_of: date) -> pd.DatetimeIndex:
    """Approximate NYSE trading days spanning the two months either side of `as_of`.

    Uses US federal holidays via pandas' ``CustomBusinessDay`` -- an
    approximation of the real NYSE calendar (it misses a handful of
    NYSE-only closures such as Good Friday). Acceptable here: this module is
    a dry-run signal generator (see module docstring), not a backtest, and a
    missed holiday shifts the window by at most one trading day.
    """
    start = (pd.Timestamp(as_of) - pd.DateOffset(months=2)).replace(day=1)
    end = pd.Timestamp(as_of) + pd.DateOffset(months=2)
    return pd.date_range(start, end, freq=_TOM_BDAY)


def is_tom_window(as_of: date, *, n_end: int = TOM_N_END, n_start: int = TOM_N_START) -> bool:
    """True if `as_of` falls in the turn-of-month trading window.

    Window definition matches ``session_anomaly_backtest.turn_of_month_mask``:
    the last `n_end` trading days of a month, or the first `n_start` trading
    days of the following month. `as_of` must itself be a trading day.
    """
    idx = _trading_days_around(as_of)
    ts = pd.Timestamp(as_of)
    if ts not in idx:
        return False  # as_of isn't a trading day per this calendar (weekend/holiday)

    ym = idx.year * 12 + idx.month
    this_ym = ts.year * 12 + ts.month
    month_days = idx[ym == this_ym]
    rank_from_start = int((month_days <= ts).sum())
    rank_from_end = len(month_days) - rank_from_start + 1
    return rank_from_start <= n_start or rank_from_end <= n_end


@dataclass
class TomSignal:
    as_of: date
    in_window: bool
    order: OrderRequest | None


def build_tom_order(as_of: date, *, quantity: int = 1) -> TomSignal:
    """Build the (dry-run) OrderRequest for the TOM strategy if `as_of` is in
    the turn-of-month window, else a no-signal ``TomSignal``.

    Long-only, matching ``evaluate_turn_of_month``'s backtest definition.
    Never submits anything -- callers decide what (if anything) to do with
    the returned ``OrderRequest``.
    """
    in_window = is_tom_window(as_of)
    if not in_window:
        return TomSignal(as_of=as_of, in_window=False, order=None)
    order = OrderRequest(
        symbol=TOM_SYMBOL,
        quantity=abs(int(quantity)),
        order_type="market",
        is_futures=True,
        strategy_id=TOM_STRATEGY_ID,
    )
    return TomSignal(as_of=as_of, in_window=True, order=order)


def run_tom_dry_check(
    safety_layer: SafetyLayer,
    as_of: date,
    portfolio_equity: float,
    *,
    quantity: int = 1,
) -> RiskCheckResult | None:
    """Dry-run: build today's TOM order (if any) and pass it through
    ``SafetyLayer.check_order()`` for a risk-check preview. Returns ``None``
    if `as_of` isn't in the TOM window (no signal, nothing to check).

    Never places an order -- ``SafetyLayer.check_order`` performs risk
    evaluation only; nothing here calls an execution/broker path.
    """
    signal = build_tom_order(as_of, quantity=quantity)
    if signal.order is None:
        return None
    return safety_layer.check_order(signal.order, portfolio_equity)


def tom_evidence_summary() -> dict:
    """Passthrough to the current promotion-gate evidence for this strategy,
    so a caller inspecting a dry-run result can also see why it is (still,
    as of writing) blocked from live promotion."""
    return turn_of_month_current_evidence()
