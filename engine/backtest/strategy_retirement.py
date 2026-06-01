"""
Strategy Retirement Criteria — P3-39.

Determines when a strategy with a gate v2 PASS verdict should be RETIRED
(verdict permanently revoked) versus refreshed (verdict re-run with new data).

Complements paper_tracker.check_kill_conditions() (which halts paper trading)
and live_readiness.py (which gates go/no-go on the validation window).

THREE SIGNALS:
    RETIRE  — structural edge breakdown; do not refresh, retire the hypothesis
    PAUSE   — degraded but possibly temporary; halt trading, investigate first
    HOLD    — within expected variance; continue trading

Retirement checks (require paper trade data):
    R1  Rolling 20-trade win rate < 40% (MES trend IS WR ~57%; 40% = 2.8σ below)
    R2  Rolling 20-trade profit factor < 0.80 (consistently net-losing on recent trades)
    R3  Consecutive loss streak >= 7 (P≈0.3% for a 57%-WR strategy; structural signal)
    R4  Equity drawdown from paper peak > 8% (tighter than paper_tracker 10% kill)

Pause checks (softer warnings):
    P1  Rolling 10-trade win rate < 45%
    P2  Consecutive loss streak >= 5
    P3  Equity drawdown from paper peak > 5%
    P4  Paper PF (all trades) < 1.10 after >= 30 trades

Usage (from engine/ directory):
    .venv/Scripts/python backtest/strategy_retirement.py --symbol MES
    .venv/Scripts/python backtest/strategy_retirement.py --all

FastAPI integration: GET /safety/retirement-status?symbol={sym}
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Retirement (RETIRE) thresholds
RETIRE_ROLLING_WR: float = 0.40  # rolling 20-trade win rate below this
RETIRE_ROLLING_PF: float = 0.80  # rolling 20-trade profit factor below this
RETIRE_CONSEC_LOSSES: int = 7  # consecutive loss streak >= this
RETIRE_PEAK_DRAWDOWN_PCT: float = 8.0  # drawdown from equity peak >= this (%)

# Pause thresholds
PAUSE_ROLLING_WR_10: float = 0.45  # rolling 10-trade win rate below this
PAUSE_CONSEC_LOSSES: int = 5  # consecutive loss streak >= this
PAUSE_PEAK_DRAWDOWN_PCT: float = 5.0  # drawdown from equity peak >= this (%)
PAUSE_LIFETIME_PF_MIN_TRADES: int = 30  # minimum trades before checking lifetime PF
PAUSE_LIFETIME_PF: float = 1.10  # lifetime PF below this after >= 30 trades

ROLLING_WINDOW_20 = 20
ROLLING_WINDOW_10 = 10


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RetirementCheck:
    check_id: str  # e.g. "R1", "P2"
    description: str
    triggered: bool
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    severity: str = "RETIRE"  # "RETIRE" | "PAUSE"


@dataclass
class RetirementStatus:
    timestamp: str
    symbol: str
    recommendation: str  # "RETIRE" | "PAUSE" | "HOLD"
    triggered_checks: list[RetirementCheck] = field(default_factory=list)
    all_checks: list[RetirementCheck] = field(default_factory=list)
    total_trades: int = 0
    rolling_20_wr: Optional[float] = None
    rolling_20_pf: Optional[float] = None
    rolling_10_wr: Optional[float] = None
    consec_losses: Optional[int] = None
    peak_drawdown_pct: Optional[float] = None
    lifetime_pf: Optional[float] = None
    error: Optional[str] = None

    def __str__(self) -> str:
        lines = [f"RetirementStatus [{self.recommendation}] — {self.symbol} @ {self.timestamp}"]
        lines.append(
            f"  Trades: {self.total_trades} | "
            f"20-WR: {self._fmt(self.rolling_20_wr, '.1%')} | "
            f"20-PF: {self._fmt(self.rolling_20_pf)} | "
            f"10-WR: {self._fmt(self.rolling_10_wr, '.1%')} | "
            f"Streak: {self.consec_losses} L | "
            f"Peak-DD: {self._fmt(self.peak_drawdown_pct, '.1f')}% | "
            f"Life-PF: {self._fmt(self.lifetime_pf)}"
        )
        for c in self.triggered_checks:
            lines.append(f"  [{c.severity}] {c.check_id}: {c.description}")
        if not self.triggered_checks:
            lines.append("  All checks clear.")
        if self.error:
            lines.append(f"  ERROR: {self.error}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["triggered_checks"] = [asdict(c) for c in self.triggered_checks]
        d["all_checks"] = [asdict(c) for c in self.all_checks]
        return d

    @staticmethod
    def _fmt(val, fmt: str = ".4f") -> str:
        if val is None:
            return "—"
        try:
            return format(float(val), fmt)
        except (TypeError, ValueError):
            return str(val)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _rolling_metrics(pnls: list[float], window: int) -> tuple[Optional[float], Optional[float]]:
    """Return (win_rate, profit_factor) for the last `window` trades."""
    if len(pnls) < window:
        return None, None
    recent = pnls[-window:]
    wins = [p for p in recent if p > 0]
    losses = [p for p in recent if p <= 0]
    wr = len(wins) / len(recent)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses)) if losses else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else None
    return wr, pf


def _consecutive_losses(pnls: list[float]) -> int:
    """Count trailing consecutive losing trades."""
    streak = 0
    for p in reversed(pnls):
        if p <= 0:
            streak += 1
        else:
            break
    return streak


def _peak_drawdown_pct(pnls: list[float], initial_capital: float) -> float:
    """Percentage drawdown from equity peak."""
    if not pnls or initial_capital <= 0:
        return 0.0
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = equity - peak
        if dd < max_dd:
            max_dd = dd
    return abs(max_dd / initial_capital) * 100.0


def check_retirement_criteria(
    symbol: str,
    pnls: list[float],
    initial_capital: float = 10_000.0,
) -> RetirementStatus:
    """
    Evaluate retirement criteria against a list of trade P&Ls.

    Parameters
    ----------
    symbol : str
        Instrument symbol (e.g. "MES", "MGC").
    pnls : list[float]
        Completed trade P&Ls in chronological order.
    initial_capital : float
        Initial paper trading capital (used for drawdown % computation).

    Returns
    -------
    RetirementStatus with recommendation: "RETIRE" | "PAUSE" | "HOLD"
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    status = RetirementStatus(
        timestamp=now_iso,
        symbol=symbol,
        recommendation="HOLD",
        total_trades=len(pnls),
    )

    if not pnls:
        status.error = "No paper trade data available"
        return status

    # Compute metrics
    wr_20, pf_20 = _rolling_metrics(pnls, ROLLING_WINDOW_20)
    wr_10, _ = _rolling_metrics(pnls, ROLLING_WINDOW_10)
    streak = _consecutive_losses(pnls)
    dd_pct = _peak_drawdown_pct(pnls, initial_capital)

    wins_all = [p for p in pnls if p > 0]
    losses_all = [p for p in pnls if p <= 0]
    gross_profit = sum(wins_all)
    gross_loss = abs(sum(losses_all))
    lifetime_pf = (gross_profit / gross_loss) if gross_loss > 0 else None

    status.rolling_20_wr = round(wr_20, 4) if wr_20 is not None else None
    status.rolling_20_pf = round(pf_20, 4) if pf_20 is not None else None
    status.rolling_10_wr = round(wr_10, 4) if wr_10 is not None else None
    status.consec_losses = streak
    status.peak_drawdown_pct = round(dd_pct, 2)
    status.lifetime_pf = round(lifetime_pf, 4) if lifetime_pf is not None else None

    checks: list[RetirementCheck] = []

    # ── RETIRE checks ────────────────────────────────────────────────────────

    checks.append(
        RetirementCheck(
            check_id="R1",
            description=(
                (
                    f"Rolling {ROLLING_WINDOW_20}-trade win rate "
                    f"{wr_20:.1%} < {RETIRE_ROLLING_WR:.0%} retire threshold"
                )
                if wr_20 is not None
                else f"Insufficient data for rolling {ROLLING_WINDOW_20}-trade WR"
            ),
            triggered=wr_20 is not None and wr_20 < RETIRE_ROLLING_WR,
            current_value=wr_20,
            threshold=RETIRE_ROLLING_WR,
            severity="RETIRE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="R2",
            description=(
                (
                    f"Rolling {ROLLING_WINDOW_20}-trade PF "
                    f"{pf_20:.3f} < {RETIRE_ROLLING_PF:.2f} retire threshold"
                )
                if pf_20 is not None
                else f"Insufficient data for rolling {ROLLING_WINDOW_20}-trade PF"
            ),
            triggered=pf_20 is not None and pf_20 < RETIRE_ROLLING_PF,
            current_value=pf_20,
            threshold=RETIRE_ROLLING_PF,
            severity="RETIRE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="R3",
            description=f"Consecutive loss streak {streak} >= {RETIRE_CONSEC_LOSSES} retire threshold",
            triggered=streak >= RETIRE_CONSEC_LOSSES,
            current_value=float(streak),
            threshold=float(RETIRE_CONSEC_LOSSES),
            severity="RETIRE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="R4",
            description=f"Peak drawdown {dd_pct:.1f}% >= {RETIRE_PEAK_DRAWDOWN_PCT:.0f}% retire threshold",
            triggered=dd_pct >= RETIRE_PEAK_DRAWDOWN_PCT,
            current_value=dd_pct,
            threshold=RETIRE_PEAK_DRAWDOWN_PCT,
            severity="RETIRE",
        )
    )

    # ── PAUSE checks ─────────────────────────────────────────────────────────

    checks.append(
        RetirementCheck(
            check_id="P1",
            description=(
                (
                    f"Rolling {ROLLING_WINDOW_10}-trade win rate "
                    f"{wr_10:.1%} < {PAUSE_ROLLING_WR_10:.0%} pause threshold"
                )
                if wr_10 is not None
                else f"Insufficient data for rolling {ROLLING_WINDOW_10}-trade WR"
            ),
            triggered=wr_10 is not None and wr_10 < PAUSE_ROLLING_WR_10,
            current_value=wr_10,
            threshold=PAUSE_ROLLING_WR_10,
            severity="PAUSE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="P2",
            description=f"Consecutive loss streak {streak} >= {PAUSE_CONSEC_LOSSES} pause threshold",
            triggered=streak >= PAUSE_CONSEC_LOSSES,
            current_value=float(streak),
            threshold=float(PAUSE_CONSEC_LOSSES),
            severity="PAUSE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="P3",
            description=f"Peak drawdown {dd_pct:.1f}% >= {PAUSE_PEAK_DRAWDOWN_PCT:.0f}% pause threshold",
            triggered=dd_pct >= PAUSE_PEAK_DRAWDOWN_PCT,
            current_value=dd_pct,
            threshold=PAUSE_PEAK_DRAWDOWN_PCT,
            severity="PAUSE",
        )
    )

    checks.append(
        RetirementCheck(
            check_id="P4",
            description=(
                (
                    f"Lifetime PF {lifetime_pf:.3f} < {PAUSE_LIFETIME_PF:.2f} "
                    f"(after {len(pnls)} >= {PAUSE_LIFETIME_PF_MIN_TRADES} trades)"
                )
                if lifetime_pf is not None and len(pnls) >= PAUSE_LIFETIME_PF_MIN_TRADES
                else f"Insufficient trades for lifetime PF check ({len(pnls)} < {PAUSE_LIFETIME_PF_MIN_TRADES})"
            ),
            triggered=(
                lifetime_pf is not None
                and len(pnls) >= PAUSE_LIFETIME_PF_MIN_TRADES
                and lifetime_pf < PAUSE_LIFETIME_PF
            ),
            current_value=lifetime_pf,
            threshold=PAUSE_LIFETIME_PF,
            severity="PAUSE",
        )
    )

    status.all_checks = checks
    status.triggered_checks = [c for c in checks if c.triggered]

    # Determine recommendation
    retire_checks = [c for c in status.triggered_checks if c.severity == "RETIRE"]
    pause_checks = [c for c in status.triggered_checks if c.severity == "PAUSE"]

    if retire_checks:
        status.recommendation = "RETIRE"
    elif pause_checks:
        status.recommendation = "PAUSE"
    else:
        status.recommendation = "HOLD"

    return status


# ---------------------------------------------------------------------------
# Live integration: load paper trades from DB and run checks
# ---------------------------------------------------------------------------


def check_retirement_from_db(symbol: str) -> RetirementStatus:
    """Load paper trade P&Ls from SQLite and run retirement criteria."""
    try:
        from database.manager import init_db

        db = init_db()
    except Exception as exc:
        logger.warning("retirement: DB init failed: %s", exc)
        return RetirementStatus(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            symbol=symbol,
            recommendation="HOLD",
            error=f"DB unavailable: {exc}",
        )

    try:
        rows = db.execute_query(
            "SELECT pnl, initial_capital FROM paper_trades WHERE symbol = ? ORDER BY recorded_at ASC",
            (symbol,),
        )
    except Exception as exc:
        logger.warning("retirement: query failed for %s: %s", symbol, exc)
        return RetirementStatus(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            symbol=symbol,
            recommendation="HOLD",
            error=f"Query error: {exc}",
        )

    if not rows:
        return RetirementStatus(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            symbol=symbol,
            recommendation="HOLD",
            error="No paper trades found in DB",
        )

    pnls = [float(r[0]) for r in rows if r[0] is not None]
    initial_capital = float(rows[0][1]) if rows[0][1] else 10_000.0

    return check_retirement_criteria(symbol, pnls, initial_capital)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    _engine_root = Path(__file__).resolve().parent.parent
    if str(_engine_root) not in sys.path:
        sys.path.insert(0, str(_engine_root))

    import logging as _logging

    _logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Strategy retirement criteria check")
    parser.add_argument("--symbol", default=None, help="Symbol to check (e.g. MES)")
    parser.add_argument(
        "--all", dest="check_all", action="store_true", help="Check all symbols in paper_config"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.check_all:
        from backtest.paper_config import (
            MCL_PAPER_CONFIG,
            MES_TREND_PAPER_CONFIG,
            MGC_PAPER_CONFIG,
            MNQ_PAPER_CONFIG,
        )

        configs = [MES_TREND_PAPER_CONFIG, MGC_PAPER_CONFIG, MCL_PAPER_CONFIG, MNQ_PAPER_CONFIG]
        symbols = [c["symbol"] for c in configs]
    elif args.symbol:
        symbols = [args.symbol]
    else:
        parser.print_help()
        sys.exit(0)

    any_retire = False
    import json as _json

    for sym in symbols:
        result = check_retirement_from_db(sym)
        if args.json:
            print(_json.dumps(result.to_dict(), indent=2))
        else:
            print(result)
            print()
        if result.recommendation == "RETIRE":
            any_retire = True

    sys.exit(1 if any_retire else 0)
