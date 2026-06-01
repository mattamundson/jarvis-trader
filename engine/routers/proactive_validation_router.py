"""
JARVIS TRADER — Proactive Validation Suite
GET /validate/proactive-suite?symbol=MCL

Aggregates 8 validation checks into one response so JARVIS can call a
single endpoint at session start instead of querying 8 fragmented routes.

Checks run (in order):
  1. Validation gates  — PF, Sharpe, WR, max DD via ValidationTracker
  2. Trade count       — N vs 60-trade minimum
  3. Time elapsed      — days vs 30-day minimum
  4. WFE status        — latest wfe_snapshots entry vs 0.50 threshold
  5. MC edge test      — bootstrap p-value: is the paper edge real?
  6. Consecutive loss  — current streak vs 5-trade threshold
  7. Win rate trend    — last-20 WR vs lifetime WR (decline > 10pp = warn)
  8. Slippage actuals  — avg slippage_ticks vs 1.5-tick threshold

Overall:
  READY              — all 8 pass
  CAUTION            — ≥1 warn, 0 fail
  NOT_READY          — ≥1 fail
  INSUFFICIENT_DATA  — fewer than 10 closed trades (MC unreliable)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backtest.backtester import BacktestResult, Trade
from backtest.monte_carlo import run_monte_carlo
from paper.validation_gate_config import PAPER_VALIDATION_GATES
from paper.validation_tracker import ValidationTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["Proactive Validation"])

# Multipliers by symbol (contract value per point)
_MULTIPLIERS: dict[str, float] = {
    "MES": 5.0,
    "ES": 50.0,
    "MNQ": 2.0,
    "NQ": 20.0,
    "MCL": 100.0,
    "CL": 1000.0,
    "MGC": 10.0,
    "GC": 100.0,
}

# WFE baselines from Sprint 21 PRD (same as wfe_router.py)
_WFE_BASELINES: dict[str, float] = {
    "MCL": 0.82,
    "MNQ": 0.57,
    "MES": 0.09,  # OVERFIT — caution
}
_WFE_WARN_THRESHOLD = 0.50
_WFE_FAIL_THRESHOLD = 0.30

# MC minimum trades for a reliable bootstrap test
_MC_MIN_TRADES = 10

# Consecutive loss thresholds
_CONSEC_LOSS_WARN = 3
_CONSEC_LOSS_FAIL = 5

# Win rate trajectory: flag if recent 20-trade WR is >10pp below lifetime WR
_WR_TREND_WARN_PP = 10.0

# Slippage thresholds (ticks)
_SLIPPAGE_WARN_TICKS = 1.5
_SLIPPAGE_FAIL_TICKS = 3.0

# Resolve canonical DB path
_DB_PATH = Path(__file__).parent.parent / "data" / "jarvis_trader.db"
_DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ValidationCheck(BaseModel):
    name: str
    status: Literal["pass", "warn", "fail", "insufficient_data"]
    value: str
    threshold: str
    message: str


class ProactiveValidationReport(BaseModel):
    symbol: str
    generated_at: str
    overall: Literal["READY", "CAUTION", "NOT_READY", "INSUFFICIENT_DATA"]
    checks: list[ValidationCheck]
    summary: str
    next_milestone: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_conn() -> Optional[sqlite3.Connection]:
    """Open a read-only SQLite connection if the DB exists."""
    if _DB_PATH.exists():
        try:
            conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as exc:
            logger.warning("proactive_validation: DB open failed: %s", exc)
    return None


def _load_closed_trades(symbol: str) -> list[sqlite3.Row]:
    """Load closed paper_trades rows for symbol from SQLite."""
    conn = _db_conn()
    if not conn:
        return []
    try:
        cur = conn.execute(
            """
            SELECT symbol, side, quantity, entry_price, exit_price,
                   entry_time, exit_time, pnl, slippage_ticks
            FROM   paper_trades
            WHERE  symbol = ? AND status = 'closed' AND pnl IS NOT NULL
            ORDER  BY exit_time ASC
            """,
            (symbol,),
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as exc:
        logger.warning("proactive_validation: query failed: %s", exc)
        conn.close()
        return []


def _load_wfe_latest(symbol: str) -> Optional[float]:
    """Return the most recent WFE profit_factor for symbol from wfe_snapshots."""
    conn = _db_conn()
    if not conn:
        return None
    try:
        cur = conn.execute(
            """
            SELECT profit_factor FROM wfe_snapshots
            WHERE  symbol = ?
            ORDER  BY created_at DESC
            LIMIT  1
            """,
            (symbol,),
        )
        row = cur.fetchone()
        conn.close()
        return float(row["profit_factor"]) if row else None
    except Exception as exc:
        logger.warning("proactive_validation: WFE query failed: %s", exc)
        conn.close()
        return None


def _rows_to_backtest_result(rows: list[sqlite3.Row], symbol: str) -> BacktestResult:
    """Convert closed paper_trades DB rows into a BacktestResult for MC simulation."""
    multiplier = _MULTIPLIERS.get(symbol, 1.0)
    trades: list[Trade] = []
    for r in rows:
        pnl = float(r["pnl"]) if r["pnl"] is not None else 0.0
        entry_dt = datetime.fromisoformat(str(r["entry_time"]).replace("Z", ""))
        exit_dt = datetime.fromisoformat(str(r["exit_time"]).replace("Z", ""))
        direction = "long" if str(r["side"]).lower() in ("buy", "buy_to_open", "long") else "short"
        ep = float(r["entry_price"] or 0.0)
        xp = float(r["exit_price"] or 0.0)
        trades.append(
            Trade(
                entry_date=entry_dt,
                symbol=symbol,
                direction=direction,
                entry_price=ep,
                stop_price=ep * 0.99,   # placeholder — MC only uses pnl
                target_1=ep * 1.015,    # placeholder
                target_2=ep * 1.030,    # placeholder
                contracts=int(r["quantity"] or 1),
                multiplier=multiplier,
                exit_date=exit_dt,
                exit_price=xp,
                pnl=pnl,
            )
        )
    return BacktestResult(
        symbol=symbol,
        start_date=trades[0].entry_date.isoformat() if trades else "",
        end_date=trades[-1].exit_date.isoformat() if trades else "",
        initial_capital=5000.0,
        final_capital=5000.0 + sum(t.pnl for t in trades),
        trades=trades,
    )


def _overall_status(checks: list[ValidationCheck]) -> Literal["READY", "CAUTION", "NOT_READY", "INSUFFICIENT_DATA"]:
    statuses = [c.status for c in checks]
    if all(s == "insufficient_data" for s in statuses):
        return "INSUFFICIENT_DATA"
    if "fail" in statuses:
        return "NOT_READY"
    if "warn" in statuses:
        return "CAUTION"
    if "insufficient_data" in statuses:
        return "CAUTION"  # partial data — cautious but not blocking
    return "READY"


# ---------------------------------------------------------------------------
# The 8 individual checks
# ---------------------------------------------------------------------------


def _check_validation_gates(progress: dict) -> ValidationCheck:
    """Check 1: PF, Sharpe, WR, max DD, trade count, days via ValidationTracker."""
    if progress.get("status") == "not_started":
        return ValidationCheck(
            name="Validation Gates",
            status="insufficient_data",
            value="No trades",
            threshold="PF≥2.0, Sharpe≥1.5, WR≥55%, DD≤15%",
            message="No paper trades recorded yet",
        )
    pf = progress.get("pass_fail", {})
    gates = PAPER_VALIDATION_GATES
    passing = sum(1 for v in pf.values() if v) if pf else 0
    total_gates = len(gates)

    pf_val = progress.get("profit_factor", 0.0)
    sh_val = progress.get("sharpe_ratio", 0.0)
    wr_val = progress.get("win_rate_pct", 0.0)
    dd_val = progress.get("max_drawdown_pct", 0.0)

    status: Literal["pass", "warn", "fail", "insufficient_data"] = "pass"
    if passing < total_gates:
        failed = [k for k, v in pf.items() if not v]
        # Any hard metric fail = fail; count/days shortfalls = warn
        hard_fails = [f for f in failed if f not in ("min_trades", "min_days")]
        status = "fail" if hard_fails else "warn"

    return ValidationCheck(
        name="Validation Gates",
        status=status,
        value=f"{passing}/{total_gates} passing | PF:{pf_val:.2f} Sharpe:{sh_val:.2f} WR:{wr_val:.1f}% DD:{dd_val:.1f}%",
        threshold=f"PF≥{gates['profit_factor']} Sharpe≥{gates['sharpe_ratio']} WR≥{gates['win_rate_pct']}% DD≤{gates['max_drawdown_pct']}%",
        message=f"{passing}/{total_gates} gates passing" if status != "pass" else "All metric gates passing",
    )


def _check_trade_count(total_trades: int) -> ValidationCheck:
    """Check 2: Trade count vs 60-trade minimum."""
    minimum = int(PAPER_VALIDATION_GATES["min_trades"])
    pct = min(100, round(total_trades / minimum * 100))
    if total_trades >= minimum:
        return ValidationCheck(
            name="Trade Count",
            status="pass",
            value=f"{total_trades} trades",
            threshold=f"≥{minimum}",
            message=f"Trade minimum met ({total_trades}/{minimum})",
        )
    status = "warn" if total_trades >= minimum * 0.5 else "fail"
    return ValidationCheck(
        name="Trade Count",
        status=status,
        value=f"{total_trades}/{minimum} ({pct}%)",
        threshold=f"≥{minimum}",
        message=f"Need {minimum - total_trades} more trades",
    )


def _check_time_elapsed(days_active: int) -> ValidationCheck:
    """Check 3: Days active vs 30-day minimum."""
    minimum = int(PAPER_VALIDATION_GATES["min_days"])
    pct = min(100, round(days_active / minimum * 100))
    if days_active >= minimum:
        return ValidationCheck(
            name="Time Elapsed",
            status="pass",
            value=f"{days_active} days",
            threshold=f"≥{minimum} days",
            message=f"Time minimum met ({days_active}/{minimum} days)",
        )
    status = "warn" if days_active >= minimum * 0.5 else "fail"
    return ValidationCheck(
        name="Time Elapsed",
        status=status,
        value=f"{days_active}/{minimum} days ({pct}%)",
        threshold=f"≥{minimum} days",
        message=f"Need {minimum - days_active} more days",
    )


def _check_wfe(symbol: str) -> ValidationCheck:
    """Check 4: Latest WFE snapshot vs threshold."""
    wfe_val = _load_wfe_latest(symbol)
    baseline = _WFE_BASELINES.get(symbol)

    if wfe_val is None:
        return ValidationCheck(
            name="WFE Status",
            status="insufficient_data",
            value="No WFE snapshots",
            threshold=f"≥{_WFE_WARN_THRESHOLD}",
            message="No WFE snapshots yet — POST /wfe/snapshot to generate",
        )

    if wfe_val >= _WFE_WARN_THRESHOLD:
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "pass"
        msg = f"WFE healthy ({wfe_val:.3f})"
    elif wfe_val >= _WFE_FAIL_THRESHOLD:
        status = "warn"
        msg = f"WFE below warn threshold ({wfe_val:.3f} < {_WFE_WARN_THRESHOLD})"
    else:
        status = "fail"
        msg = f"WFE critically low ({wfe_val:.3f} < {_WFE_FAIL_THRESHOLD}) — strategy may be overfitting"

    baseline_str = f" (backtest baseline {baseline:.2f})" if baseline else ""
    return ValidationCheck(
        name="WFE Status",
        status=status,
        value=f"WFE: {wfe_val:.3f}{baseline_str}",
        threshold=f"warn<{_WFE_WARN_THRESHOLD} fail<{_WFE_FAIL_THRESHOLD}",
        message=msg,
    )


def _check_mc_edge(rows: list[sqlite3.Row], symbol: str) -> ValidationCheck:
    """Check 5: Bootstrap MC edge significance test."""
    if len(rows) < _MC_MIN_TRADES:
        return ValidationCheck(
            name="MC Edge Significance",
            status="insufficient_data",
            value=f"{len(rows)} trades",
            threshold=f"≥{_MC_MIN_TRADES} trades for reliable test",
            message=f"Need {_MC_MIN_TRADES - len(rows)} more closed trades for MC test",
        )

    br = _rows_to_backtest_result(list(rows), symbol)
    mc = run_monte_carlo(br, n_simulations=5_000, initial_capital=5000.0, symbol=symbol, seed=42)

    # prob_better_than_original = % of shuffled sims that beat the original sequence
    # Low prob_better = original sequence is hard to beat = edge is real
    # This is equivalent to (1 - p_value) in a permutation test
    prob_better = mc["confidence"]["prob_better_than_original"]
    p_value = prob_better / 100.0  # convert to 0-1 range
    verdict = mc.get("verdict", "POOR")
    prob_profitable = mc["confidence"]["prob_profitable"]

    if p_value <= 0.05 and verdict in ("EXCELLENT", "GOOD"):
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "pass"
        msg = f"Edge is statistically significant (p={p_value:.3f})"
    elif p_value <= 0.10:
        status = "warn"
        msg = f"Marginal edge significance (p={p_value:.3f}) — accumulate more trades"
    else:
        status = "fail"
        msg = f"Edge not yet significant (p={p_value:.3f}) — {prob_profitable:.1f}% of paths profitable"

    return ValidationCheck(
        name="MC Edge Significance",
        status=status,
        value=f"p={p_value:.3f} | verdict={verdict} | {prob_profitable:.1f}% paths profitable",
        threshold="p≤0.05 for significance",
        message=msg,
    )


def _check_consecutive_losses(consecutive_losses: int) -> ValidationCheck:
    """Check 6: Current consecutive loss streak."""
    if consecutive_losses == 0:
        return ValidationCheck(
            name="Loss Streak",
            status="pass",
            value="0 consecutive losses",
            threshold=f"warn≥{_CONSEC_LOSS_WARN} fail≥{_CONSEC_LOSS_FAIL}",
            message="No active loss streak",
        )
    if consecutive_losses >= _CONSEC_LOSS_FAIL:
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "fail"
        msg = f"ACTIVE STREAK: {consecutive_losses} consecutive losses — review strategy"
    elif consecutive_losses >= _CONSEC_LOSS_WARN:
        status = "warn"
        msg = f"Loss streak building: {consecutive_losses} consecutive"
    else:
        status = "pass"
        msg = f"{consecutive_losses} consecutive losses (within threshold)"

    return ValidationCheck(
        name="Loss Streak",
        status=status,
        value=f"{consecutive_losses} consecutive losses",
        threshold=f"warn≥{_CONSEC_LOSS_WARN} fail≥{_CONSEC_LOSS_FAIL}",
        message=msg,
    )


def _check_wr_trend(rows: list[sqlite3.Row], lifetime_wr: float) -> ValidationCheck:
    """Check 7: Win rate trajectory — last 20 trades vs lifetime."""
    if len(rows) < 20:
        return ValidationCheck(
            name="WR Trend",
            status="insufficient_data",
            value=f"{len(rows)} trades",
            threshold="Need 20 trades for trend analysis",
            message=f"Insufficient trades for trend analysis ({len(rows)}/20)",
        )

    recent = list(rows)[-20:]
    recent_wins = sum(1 for r in recent if float(r["pnl"] or 0) > 0)
    recent_wr = (recent_wins / 20) * 100
    decline = lifetime_wr - recent_wr

    if decline > _WR_TREND_WARN_PP:
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "warn"
        msg = f"WR declining: last-20 {recent_wr:.1f}% vs lifetime {lifetime_wr:.1f}% ({decline:.1f}pp drop)"
    elif decline > _WR_TREND_WARN_PP * 2:
        status = "fail"
        msg = f"WR deteriorating: last-20 {recent_wr:.1f}% vs lifetime {lifetime_wr:.1f}%"
    else:
        status = "pass"
        msg = f"WR stable: last-20 {recent_wr:.1f}% vs lifetime {lifetime_wr:.1f}%"

    return ValidationCheck(
        name="WR Trend",
        status=status,
        value=f"Last-20: {recent_wr:.1f}% | Lifetime: {lifetime_wr:.1f}%",
        threshold=f"Decline >{_WR_TREND_WARN_PP}pp = warn",
        message=msg,
    )


def _check_slippage(rows: list[sqlite3.Row]) -> ValidationCheck:
    """Check 8: Average slippage_ticks vs 1.5-tick threshold."""
    ticks = [float(r["slippage_ticks"]) for r in rows if r["slippage_ticks"] is not None]
    if not ticks:
        return ValidationCheck(
            name="Slippage Actuals",
            status="insufficient_data",
            value="No slippage data",
            threshold=f"warn>{_SLIPPAGE_WARN_TICKS} ticks",
            message="No slippage_ticks recorded in paper trades",
        )

    avg_ticks = sum(ticks) / len(ticks)
    max_ticks = max(ticks)

    if avg_ticks >= _SLIPPAGE_FAIL_TICKS:
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "fail"
        msg = f"High slippage: avg {avg_ticks:.2f} ticks (>{_SLIPPAGE_FAIL_TICKS} threshold) — edge may not survive live fills"
    elif avg_ticks >= _SLIPPAGE_WARN_TICKS:
        status = "warn"
        msg = f"Slippage elevated: avg {avg_ticks:.2f} ticks — monitor at live deployment"
    else:
        status = "pass"
        msg = f"Slippage within bounds: avg {avg_ticks:.2f} ticks"

    return ValidationCheck(
        name="Slippage Actuals",
        status=status,
        value=f"avg {avg_ticks:.2f} ticks | max {max_ticks:.1f} ticks ({len(ticks)} trades)",
        threshold=f"warn>{_SLIPPAGE_WARN_TICKS} fail>{_SLIPPAGE_FAIL_TICKS} ticks",
        message=msg,
    )


# ---------------------------------------------------------------------------
# Next milestone helper
# ---------------------------------------------------------------------------


def _next_milestone(checks: list[ValidationCheck], total_trades: int, days_active: int) -> str:
    min_trades = int(PAPER_VALIDATION_GATES["min_trades"])
    min_days = int(PAPER_VALIDATION_GATES["min_days"])

    if total_trades < min_trades:
        return f"Need {min_trades - total_trades} more trades to reach minimum ({total_trades}/{min_trades})"
    if days_active < min_days:
        return f"Need {min_days - days_active} more days of paper trading ({days_active}/{min_days} days)"
    failing = [c.name for c in checks if c.status == "fail"]
    if failing:
        return f"Resolve failing checks: {', '.join(failing)}"
    warning = [c.name for c in checks if c.status == "warn"]
    if warning:
        return f"Monitor: {', '.join(warning)}"
    return "All milestones met — ready for live evaluation"


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------


@router.get("/proactive-suite", response_model=ProactiveValidationReport)
async def get_proactive_validation(
    symbol: str = Query(default="MCL", description="Instrument symbol (MCL, MNQ, MES)"),
) -> ProactiveValidationReport:
    """
    Run all 8 proactive validation checks for a symbol and return a structured report.

    This is the single endpoint JARVIS calls at session start to get a complete
    validation picture without querying 8 fragmented routes. Always returns live
    data — never cached.
    """
    sym = symbol.upper()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # Load live data
    rows = _load_closed_trades(sym)
    tracker = ValidationTracker(data_dir=str(_DATA_DIR), db_path=str(_DB_PATH) if _DB_PATH.exists() else None)
    progress = tracker.get_progress(sym)

    total_trades = progress.get("total_trades", 0) if isinstance(progress, dict) else 0
    days_active = progress.get("days_active", 0) if isinstance(progress, dict) else 0
    consecutive_losses = progress.get("consecutive_losses", 0) if isinstance(progress, dict) else 0
    lifetime_wr = progress.get("win_rate_pct", 0.0) if isinstance(progress, dict) else 0.0

    # Run all 8 checks
    checks = [
        _check_validation_gates(progress),
        _check_trade_count(total_trades),
        _check_time_elapsed(days_active),
        _check_wfe(sym),
        _check_mc_edge(rows, sym),
        _check_consecutive_losses(consecutive_losses),
        _check_wr_trend(rows, lifetime_wr),
        _check_slippage(rows),
    ]

    overall = _overall_status(checks)

    # Summary line
    pass_count = sum(1 for c in checks if c.status == "pass")
    warn_count = sum(1 for c in checks if c.status == "warn")
    fail_count = sum(1 for c in checks if c.status == "fail")
    insufficient_count = sum(1 for c in checks if c.status == "insufficient_data")

    parts = [f"{pass_count}/8 checks passing"]
    if warn_count:
        warns = [c.name for c in checks if c.status == "warn"]
        parts.append(f"{warn_count} caution ({', '.join(warns)})")
    if fail_count:
        fails = [c.name for c in checks if c.status == "fail"]
        parts.append(f"{fail_count} FAIL ({', '.join(fails)})")
    if insufficient_count:
        parts.append(f"{insufficient_count} insufficient data")
    summary = " — ".join(parts)

    return ProactiveValidationReport(
        symbol=sym,
        generated_at=generated_at,
        overall=overall,
        checks=checks,
        summary=summary,
        next_milestone=_next_milestone(checks, total_trades, days_active),
    )
