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
from paper.validation_gate_config import EXECUTION_FIDELITY_GATES, PAPER_VALIDATION_GATES
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

# Honesty floors. Below these the underlying statistic is degenerate (rests on
# too few trades, or has near-zero gross loss/win) and the check must report
# INSUFFICIENT_DATA rather than a confident pass/fail. A WFE snapshot resting on
# a handful of trades produces meaningless profit factors (e.g. 3173 or 0.000)
# that previously read as "healthy" / "overfitting" — both noise, not signal.
_WFE_MIN_TRADES = 10
_WFE_DEGENERATE_PF = 50.0  # PF this large => gross loss ~ 0 => degenerate

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


def _load_wfe_latest(symbol: str) -> Optional[tuple[float, Optional[int]]]:
    """Return (profit_factor, trades) for the most recent WFE snapshot, or None.

    The trade count rides along so the caller can gate degenerate profit factors
    (e.g. a PF of 3173 produced by a 3-trade snapshot) to insufficient_data.
    `trades` may be None for legacy rows that did not record it.
    """
    conn = _db_conn()
    if not conn:
        return None
    try:
        cur = conn.execute(
            """
            SELECT profit_factor, trades FROM wfe_snapshots
            WHERE  symbol = ?
            ORDER  BY created_at DESC
            LIMIT  1
            """,
            (symbol,),
        )
        row = cur.fetchone()
        conn.close()
        if not row or row["profit_factor"] is None:
            return None
        trades = row["trades"]
        return float(row["profit_factor"]), (int(trades) if trades is not None else None)
    except Exception as exc:
        logger.warning("proactive_validation: WFE query failed: %s", exc)
        conn.close()
        return None


def _wfe_honesty_status(
    pf: float, trades: Optional[int]
) -> Optional[tuple[Literal["insufficient_data"], str]]:
    """Gate a degenerate WFE snapshot to insufficient_data.

    Returns ``(status, message)`` when the snapshot is too small or its profit
    factor is degenerate to trust; returns ``None`` when the caller should apply
    the normal pass/warn/fail thresholds. Pure — no I/O — so it is exhaustively
    unit-testable without a database.
    """
    if trades is None or trades < _WFE_MIN_TRADES:
        n = "unknown" if trades is None else trades
        return (
            "insufficient_data",
            f"WFE rests on {n} trades (< {_WFE_MIN_TRADES}) — not yet reliable",
        )
    if pf >= _WFE_DEGENERATE_PF or pf <= 0.0:
        return (
            "insufficient_data",
            f"WFE profit factor {pf:.3f} is degenerate "
            "(near-zero gross loss/win) — not reliable",
        )
    return None


def _mc_honesty_status(
    p_value: float, verdict: str, prob_profitable: float
) -> Optional[tuple[Literal["insufficient_data"], str]]:
    """Gate a degenerate or self-contradictory MC bootstrap to insufficient_data.

    Returns ``(status, message)`` when the result cannot be trusted; ``None``
    when the caller should apply the normal pass/warn/fail logic. Pure — no I/O.

    Two failure signatures, both small-sample artifacts:
      - No dispersion: every (>=99.5%) or no (<=0.5%) bootstrap path profitable,
        so the significance estimate is meaningless.
      - Incoherence: the MC's own verdict and the permutation significance
        disagree (e.g. verdict=EXCELLENT but p=1.000) — treat as no evidence.
    """
    if prob_profitable >= 99.5 or prob_profitable <= 0.5:
        return (
            "insufficient_data",
            f"MC degenerate — {prob_profitable:.1f}% of paths profitable "
            "(no dispersion); sample too small to test",
        )
    good_verdict = verdict in ("EXCELLENT", "GOOD")
    significant = p_value <= 0.10
    if good_verdict != significant:
        return (
            "insufficient_data",
            f"MC inconclusive — verdict {verdict} but p={p_value:.3f}; "
            "signals disagree, treat as no evidence",
        )
    return None


def _load_latest_health() -> Optional[sqlite3.Row]:
    """Return the most recent health_snapshots row (broker + kill-switch state)."""
    conn = _db_conn()
    if not conn:
        return None
    try:
        cur = conn.execute(
            """
            SELECT reachable, ibkr_data, ibkr_exec, kill_switch, ts_utc
            FROM   health_snapshots
            ORDER  BY ts_utc DESC
            LIMIT  1
            """
        )
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as exc:
        logger.warning("execution_fidelity: health query failed: %s", exc)
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
    snapshot = _load_wfe_latest(symbol)
    baseline = _WFE_BASELINES.get(symbol)

    if snapshot is None:
        return ValidationCheck(
            name="WFE Status",
            status="insufficient_data",
            value="No WFE snapshots",
            threshold=f"≥{_WFE_WARN_THRESHOLD}",
            message="No WFE snapshots yet — POST /wfe/snapshot to generate",
        )

    wfe_val, wfe_trades = snapshot

    honesty = _wfe_honesty_status(wfe_val, wfe_trades)
    if honesty:
        h_status, h_msg = honesty
        n_str = wfe_trades if wfe_trades is not None else "?"
        return ValidationCheck(
            name="WFE Status",
            status=h_status,
            value=f"WFE: {wfe_val:.3f} (n={n_str})",
            threshold=f"≥{_WFE_WARN_THRESHOLD}, n≥{_WFE_MIN_TRADES}",
            message=h_msg,
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

    honesty = _mc_honesty_status(p_value, verdict, prob_profitable)
    if honesty:
        h_status, h_msg = honesty
        return ValidationCheck(
            name="MC Edge Significance",
            status=h_status,
            value=f"p={p_value:.3f} | verdict={verdict} | {prob_profitable:.1f}% paths profitable",
            threshold="p≤0.05 for significance",
            message=h_msg,
        )

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


# ---------------------------------------------------------------------------
# Execution-fidelity gate (ADVISORY — gates nothing; see validation_gate_config)
# ---------------------------------------------------------------------------
#
# Answers "does live execution match the backtest's assumptions?" (slippage,
# fill price, broker link, kill-switch) on a SMALL sample of real fills — NOT
# "does the strategy have edge?" (that is proven by the gate-v2 WFO). This
# endpoint is observational instrumentation: it does not touch live_readiness.py
# or phase3_criteria.py, and it cannot enable live trading. Substituting fidelity
# for the edge gate in the live-readiness VERDICT is a separate [safety-review]
# change requiring explicit approval. See docs/TRADE_SYSTEM_SCOPE_AND_ROADMAP.md
# Part 4.


class ExecutionFidelityReport(BaseModel):
    symbol: str
    generated_at: str
    overall: Literal["APPROVED", "INSUFFICIENT_DATA", "NOT_APPROVED"]
    measuring_real_fills: bool
    checks: list[ValidationCheck]
    summary: str
    advisory_note: str


def _check_fill_sample(total_trades: int) -> ValidationCheck:
    """Fidelity 1: sample size vs fidelity min_fills (NOT the 60-trade edge gate)."""
    minimum = int(EXECUTION_FIDELITY_GATES["min_fills"])
    if total_trades >= minimum:
        return ValidationCheck(
            name="Fill Sample",
            status="pass",
            value=f"{total_trades} fills",
            threshold=f"≥{minimum}",
            message=f"Fidelity sample met ({total_trades}/{minimum})",
        )
    return ValidationCheck(
        name="Fill Sample",
        status="insufficient_data",
        value=f"{total_trades}/{minimum}",
        threshold=f"≥{minimum}",
        message=f"Need {minimum - total_trades} more fills for fidelity confidence",
    )


def _check_broker_link(health: Optional[sqlite3.Row]) -> ValidationCheck:
    """Fidelity 2: latest health snapshot — IBKR data + execution both connected."""
    if health is None:
        return ValidationCheck(
            name="Broker Link",
            status="insufficient_data",
            value="No health snapshot",
            threshold="ibkr_data=1 AND ibkr_exec=1",
            message="No health_snapshots row available",
        )
    data_ok = bool(health["ibkr_data"]) if health["ibkr_data"] is not None else False
    exec_ok = bool(health["ibkr_exec"]) if health["ibkr_exec"] is not None else False
    if data_ok and exec_ok:
        status: Literal["pass", "warn", "fail", "insufficient_data"] = "pass"
        msg = "IBKR data + execution both connected"
    else:
        status = "fail"
        msg = f"IBKR link degraded (data={data_ok}, exec={exec_ok})"
    return ValidationCheck(
        name="Broker Link",
        status=status,
        value=f"data={data_ok} exec={exec_ok} @ {health['ts_utc']}",
        threshold="ibkr_data=1 AND ibkr_exec=1",
        message=msg,
    )


def _check_kill_switch_state(health: Optional[sqlite3.Row]) -> ValidationCheck:
    """Fidelity 3: kill switch must be inactive in the latest health snapshot."""
    if health is None:
        return ValidationCheck(
            name="Kill Switch",
            status="insufficient_data",
            value="No health snapshot",
            threshold="kill_switch=0",
            message="No health_snapshots row available",
        )
    active = bool(health["kill_switch"]) if health["kill_switch"] is not None else False
    return ValidationCheck(
        name="Kill Switch",
        status="fail" if active else "pass",
        value="ACTIVE" if active else "inactive",
        threshold="kill_switch=0",
        message="Kill switch ACTIVE — halt in effect" if active else "Kill switch inactive",
    )


def _check_pf_floor(rows: list[sqlite3.Row]) -> ValidationCheck:
    """Fidelity 4: realized PF sign-check (>=1.0). NOT the 2.0 edge gate."""
    floor = float(EXECUTION_FIDELITY_GATES["min_realized_pf_floor"])
    pnls = [float(r["pnl"]) for r in rows if r["pnl"] is not None]
    if not pnls:
        return ValidationCheck(
            name="PF Floor",
            status="insufficient_data",
            value="No closed pnl",
            threshold=f"PF≥{floor} (sign-check)",
            message="No realized P&L recorded",
        )
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        pf = float("inf") if gross_profit > 0 else 0.0
    else:
        pf = gross_profit / gross_loss
    pf_disp = "inf" if pf == float("inf") else f"{pf:.2f}"
    status: Literal["pass", "warn", "fail", "insufficient_data"] = "pass" if pf >= floor else "fail"
    return ValidationCheck(
        name="PF Floor",
        status=status,
        value=f"PF={pf_disp} ({len(pnls)} fills)",
        threshold=f"PF≥{floor} (sign-check, NOT edge)",
        message="Realized PF above breakeven floor"
        if status == "pass"
        else f"Realized PF {pf_disp} below {floor} floor",
    )


def _check_real_fill_reconciliation(
    symbol: str, measuring_real_fills: bool
) -> ValidationCheck:
    """Fidelity 6: real JARVIS fills reconciled against paper_trades intent.

    Reads ibkr_fills filtered to JARVIS-tagged orderRefs (DUP662235 demo-seed
    activity excluded) and matches each to a paper_trades entry, measuring entry
    slippage. This is what makes fidelity *measured* rather than self-referential.
    insufficient_data until the IBKR order path is live
    (ALLOW_PAPER_SIMULATED_ORDERS=True) and matched JARVIS fills exist.
    """
    if not measuring_real_fills:
        return ValidationCheck(
            name="Real-Fill Reconciliation",
            status="insufficient_data",
            value="simulated mode",
            threshold="JARVIS real fills matched to intent",
            message="ALLOW_PAPER_SIMULATED_ORDERS=False — no real IB fills to reconcile",
        )
    try:
        from execution.ibkr_reconciler import compare_fills_to_trades

        cmp = compare_fills_to_trades(_DB_PATH, symbol)
    except Exception as exc:
        logger.warning("real-fill reconciliation failed: %s", exc)
        return ValidationCheck(
            name="Real-Fill Reconciliation",
            status="insufficient_data",
            value="reconciler error",
            threshold="JARVIS real fills matched to intent",
            message=f"Reconciliation error: {exc}",
        )
    if cmp["n_matched"] == 0:
        return ValidationCheck(
            name="Real-Fill Reconciliation",
            status="insufficient_data",
            value=(
                f"{cmp['n_real_fills']} JARVIS fills, "
                f"{cmp['n_demo_excluded']} demo excluded, 0 matched"
            ),
            threshold="≥1 JARVIS fill matched to a paper_trade",
            message="No JARVIS real fills matched to paper_trades intent yet",
        )
    return ValidationCheck(
        name="Real-Fill Reconciliation",
        status="pass",
        value=(
            f"{cmp['n_matched']} matched, avg|slip|={cmp['avg_abs_slippage_pts']} pts, "
            f"max={cmp['max_abs_slippage_pts']} pts; {cmp['n_demo_excluded']} demo excluded"
        ),
        threshold="JARVIS fills matched to intent",
        message="Real IB fills reconciled against paper_trades intent",
    )


@router.get("/execution-fidelity", response_model=ExecutionFidelityReport)
async def get_execution_fidelity(
    symbol: str = Query(default="MES", description="Instrument symbol (MCL, MNQ, MES, MGC)"),
) -> ExecutionFidelityReport:
    """
    ADVISORY execution-fidelity report — does live execution match backtest
    assumptions? Gates NOTHING (does not alter live-readiness). Edge is proven
    separately by the gate-v2 WFO. See docs/TRADE_SYSTEM_SCOPE_AND_ROADMAP.md Part 4.
    """
    sym = symbol.upper()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    # Honesty flag: fidelity on simulated paper_trades is self-referential — the
    # simulator defines its own slippage. Only real broker fills make this meaningful.
    try:
        from config import settings

        measuring_real_fills = bool(getattr(settings, "ALLOW_PAPER_SIMULATED_ORDERS", False))
    except Exception:
        measuring_real_fills = False

    rows = _load_closed_trades(sym)
    health = _load_latest_health()
    total_trades = len(rows)

    checks = [
        _check_fill_sample(total_trades),
        _check_slippage(rows),
        _check_broker_link(health),
        _check_kill_switch_state(health),
        _check_pf_floor(rows),
        _check_real_fill_reconciliation(sym, measuring_real_fills),
    ]

    statuses = [c.status for c in checks]
    if "fail" in statuses:
        overall: Literal["APPROVED", "INSUFFICIENT_DATA", "NOT_APPROVED"] = "NOT_APPROVED"
    elif "insufficient_data" in statuses:
        overall = "INSUFFICIENT_DATA"
    else:
        overall = "APPROVED"

    pass_count = sum(1 for c in checks if c.status == "pass")
    summary = f"{pass_count}/{len(checks)} fidelity checks passing — {overall}"

    if not measuring_real_fills:
        advisory_note = (
            "SIMULATED MODE (ALLOW_PAPER_SIMULATED_ORDERS=False): paper_trades are "
            "internally simulated, so slippage/fill metrics are self-referential and "
            "NOT yet a true execution-fidelity signal. Enable the IBKR order path for "
            "real fills. This endpoint is advisory and gates no live-trading decision."
        )
    else:
        advisory_note = (
            "Measuring real IBKR paper fills. Advisory only — does not gate "
            "live trading; the live-readiness verdict is unchanged. Edge is proven "
            "separately by the gate-v2 WFO."
        )

    return ExecutionFidelityReport(
        symbol=sym,
        generated_at=generated_at,
        overall=overall,
        measuring_real_fills=measuring_real_fills,
        checks=checks,
        summary=summary,
        advisory_note=advisory_note,
    )


# ---------------------------------------------------------------------------
# Slippage analytics — per-symbol distribution of persisted entry slippage
# ---------------------------------------------------------------------------
# Reads paper_trades.slippage_ticks (migration 038), populated on reconcile() by
# execution.ibkr_reconciler.persist_entry_slippage from matched real IB fills.
# Read-only + advisory; gates nothing.


class SlippageAnalyticsReport(BaseModel):
    symbol: str
    generated_at: str
    measuring_real_fills: bool
    n: int  # closed trades carrying a persisted slippage_ticks value
    mean_abs_slippage_ticks: Optional[float]
    p95_abs_slippage_ticks: Optional[float]
    max_abs_slippage_ticks: Optional[float]
    note: str


@router.get("/slippage-analytics", response_model=SlippageAnalyticsReport)
async def get_slippage_analytics(
    symbol: str = Query(default="MES", description="Instrument symbol (MCL, MNQ, MES, MGC)"),
) -> SlippageAnalyticsReport:
    """ADVISORY per-symbol entry-slippage distribution from real IB fills.

    Slippage is persisted onto paper_trades.slippage_ticks at reconcile time
    (persist_entry_slippage). Until ALLOW_PAPER_SIMULATED_ORDERS=True and a
    reconcile cycle has matched JARVIS fills, this reports n=0. Gates nothing.
    """
    sym = symbol.upper()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    try:
        from config import settings

        measuring_real_fills = bool(getattr(settings, "ALLOW_PAPER_SIMULATED_ORDERS", False))
    except Exception:
        measuring_real_fills = False

    rows = _load_closed_trades(sym)
    ticks = sorted(
        abs(float(r["slippage_ticks"])) for r in rows if r["slippage_ticks"] is not None
    )
    n = len(ticks)

    if n:
        mean_ = round(sum(ticks) / n, 4)
        # Nearest-rank p95 (advisory; small-n robust, no interpolation).
        p95_idx = max(0, min(n - 1, int(round(0.95 * (n - 1)))))
        p95 = round(ticks[p95_idx], 4)
        mx = round(ticks[-1], 4)
        note = (
            f"{n} closed {sym} trades with persisted slippage; "
            f"mean|slip|={mean_} ticks, p95={p95}, max={mx}."
        )
    else:
        mean_ = p95 = mx = None
        if not measuring_real_fills:
            note = (
                "No persisted slippage — ALLOW_PAPER_SIMULATED_ORDERS=False, so no real "
                "IB fills are reconciled. Enable the IBKR order path to populate slippage."
            )
        else:
            note = (
                "No persisted slippage yet — run POST /brokers/reconcile once JARVIS-tagged "
                "real fills exist for this symbol; persist_entry_slippage fills slippage_ticks."
            )

    return SlippageAnalyticsReport(
        symbol=sym,
        generated_at=generated_at,
        measuring_real_fills=measuring_real_fills,
        n=n,
        mean_abs_slippage_ticks=mean_,
        p95_abs_slippage_ticks=p95,
        max_abs_slippage_ticks=mx,
        note=note,
    )
