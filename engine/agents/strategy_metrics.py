"""
JARVIS TRADER — Strategy Validation Metrics (informational, LLM-facing)
=========================================================================
Gives the trade-decision agents (TraderAgent, RiskManagerAgent) visibility
into the SAME statistical-validation signal that already hard-gates paper
order submission via `backtest.gate_v2_policy.is_strategy_authorized()`
(see `approval/service.py::ensure_approval_allowed()`), plus a live,
per-decision risk snapshot computed from the symbol's own recent closed
trades — the same recent-trade window already fetched for the Half-Kelly
sizing block in `agents/trader.py::decide()`.

This module is PURELY INFORMATIONAL. It does not gate, veto, or block
anything — that hard gate already exists and is untouched by this module.
Both functions here are synchronous, side-effect-free, and NEVER raise:
any internal failure is caught, logged at debug level, and the function
returns `None` so a metrics lookup can never block or crash a trade
decision.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["get_gate_v2_metrics", "compute_recent_risk_metrics"]

# Mirrors the minimum-sample-size convention already used by the Half-Kelly
# sizing gate in utils/position_sizing.py::compute_rolling_edge — fewer than
# this many closed trades and edge stats are considered too noisy to trust.
MIN_TRADES_FOR_RISK_METRICS = 10


def get_gate_v2_metrics(symbol: str) -> Optional[dict]:
    """Thin, read-only wrapper over `backtest.gate_v2_policy.get_last_verdict`.

    Flattens the newest non-stale `VerdictSnapshot` for `symbol` into a
    plain dict for prompt rendering. Returns `None` when no verdict exists,
    the verdict is stale, or anything goes wrong — this must never be able
    to block a trade decision.
    """
    try:
        from backtest.gate_v2_policy import get_last_verdict  # noqa: PLC0415

        snapshot = get_last_verdict(symbol)
        if snapshot is None:
            return None

        metrics = snapshot.gate_v2_metrics or {}

        return {
            "symbol": snapshot.symbol,
            "family": snapshot.family,
            "verdict": snapshot.verdict,
            "passed_via": snapshot.passed_via,
            "core_verdict": snapshot.core_verdict,
            "alt_verdict": snapshot.alt_verdict,
            "pf_ci_lower": metrics.get("pf_ci_lower"),
            "p_edge": metrics.get("p_edge"),
            "mc_95th_dd": metrics.get("mc_95th_dd"),
            "mc_95th_dd_pct": metrics.get("mc_95th_dd_pct"),
            "dsr": metrics.get("dsr"),
            "wfo_consistency": metrics.get("wfo_consistency"),
            "fixed_params_min_pf": metrics.get("fixed_params_min_pf"),
            "created_at": snapshot.created_at,
            "age_days": round(snapshot.age_days(), 1),
        }
    except Exception as exc:  # pragma: no cover — defensive, never block a decision
        logger.debug("[strategy_metrics] get_gate_v2_metrics(%s) failed: %s", symbol, exc)
        return None


def compute_recent_risk_metrics(closed_trades: list, initial_capital: float) -> Optional[dict]:
    """Compute Sharpe/Sortino/Calmar/MaxDD for a symbol's recent closed trades.

    Reuses the canonical formulas in `backtest.metrics` (via `calculate_metrics`)
    rather than reimplementing them — same invariants (per-trade returns, not
    per-bar equity diffs) apply here.

    `closed_trades` is the same shape already fetched in the Half-Kelly sizing
    block of `agents/trader.py::decide()` — a list of dicts, each carrying a
    'pnl' or 'realized_pnl' key (raw DB rows use 'pnl'; some callers normalize
    to 'realized_pnl'). Any other keys are ignored.

    Returns `None` when fewer than `MIN_TRADES_FOR_RISK_METRICS` trades are
    available (mirrors the Half-Kelly `sufficient_data` gate in
    `utils/position_sizing.py::compute_rolling_edge`) or on any internal error.
    """
    try:
        if not closed_trades or len(closed_trades) < MIN_TRADES_FOR_RISK_METRICS:
            return None
        if not initial_capital or initial_capital <= 0:
            return None

        from backtest.metrics import calculate_metrics  # noqa: PLC0415
        from backtest.trade_manager import BacktestResult, Trade  # noqa: PLC0415

        pnls = [
            float(t.get("pnl", t.get("realized_pnl", 0)) or 0)
            for t in closed_trades
        ]

        trades = [
            Trade(
                entry_date=datetime.now(),
                symbol="",
                direction="long" if pnl >= 0 else "short",
                entry_price=0.0,
                stop_price=0.0,
                target_1=0.0,
                target_2=0.0,
                contracts=1,
                multiplier=1.0,
                pnl=pnl,
            )
            for pnl in pnls
        ]

        # Post-trade equity snapshots (no flat non-trade bars) — consistent
        # with the "per-trade returns, not per-bar diffs" invariant that
        # backtest/metrics.py's Sharpe/Sortino computation relies on.
        equity_curve = [initial_capital]
        running = initial_capital
        for pnl in pnls:
            running += pnl
            equity_curve.append(running)

        result = BacktestResult(
            symbol="",
            start_date="",
            end_date="",
            initial_capital=initial_capital,
            final_capital=equity_curve[-1],
            trades=trades,
            equity_curve=equity_curve,
        )
        calculate_metrics(result)

        return {
            "n_trades": len(trades),
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "calmar_ratio": result.calmar_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
        }
    except Exception as exc:  # pragma: no cover — defensive, never block a decision
        logger.debug("[strategy_metrics] compute_recent_risk_metrics failed: %s", exc)
        return None
