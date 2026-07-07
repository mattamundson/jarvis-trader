"""
Phase 3 Live-Trading Readiness — Programmatic GO/WAIT/NO-GO check
=================================================================
Each criterion is a self-contained check against the live SQLite DB (or other
locally observable state).  The output is informational only — it tells Matt
how many criteria pass, it does NOT flip any flag.

INVARIANTS (enforced here, never violated):
- LIVE_TRADING_ENABLED is never read or written here.
- safety_layer.py is never imported or mutated.
- engine/config.py is never mutated.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_60D = timedelta(days=60)
_30D = timedelta(days=30)

# Thresholds — all sourced from PHASE3_READINESS.md / rules/jarvis-trader.md
_MIN_PAPER_DAYS = 60
_MIN_PAPER_TRADES = 100
_MIN_WIN_RATE = 0.55  # 55%
_MIN_PROFIT_FACTOR = 1.5
_MAX_DRAWDOWN = 0.08  # 8%
_MIN_SORTINO = 1.0
_MAX_CONSECUTIVE_LOSSES = 5
_MAX_KILL_SWITCH_INVOCATIONS = 2
_MAX_RESTART_PER_DAY = 1.0  # average over 30 days
_MIN_SAFETY_COVERAGE = 0.95  # 95%


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Phase3Criterion(ABC):
    """Single measurable gate for Phase 3 readiness."""

    name: str
    description: str
    severity: Literal["blocker", "warning", "info"]

    @abstractmethod
    def check(self, db_path: str) -> tuple[bool, str]:
        """
        Run the check.

        Parameters
        ----------
        db_path:
            Absolute path to the jarvis_trader SQLite database.

        Returns
        -------
        (passed: bool, evidence: str)
            evidence is a human-readable string explaining the result.
        """


# ---------------------------------------------------------------------------
# Helper: open DB read-only
# ---------------------------------------------------------------------------


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 datetime string (with or without timezone)."""
    s = s.strip()
    # SQLite stores times in various formats; normalise the most common ones.
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


# ---------------------------------------------------------------------------
# Criterion implementations
# ---------------------------------------------------------------------------


class PaperTradingWindowCriterion(Phase3Criterion):
    """C1 — at least 60 calendar days of paper trading history."""

    name: str = "paper_trading_window"
    description: str = (
        "Oldest closed paper trade must be at least 60 calendar days ago. "
        "Ensures the engine has been validated across at least two full "
        "monthly cycles before live capital is at risk."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        try:
            conn = _open_db(db_path)
            try:
                row = conn.execute(
                    "SELECT MIN(exit_time) AS oldest FROM paper_trades "
                    "WHERE status = 'closed' AND exit_time IS NOT NULL"
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        if not row or not row["oldest"]:
            return False, "No closed paper trades found"

        try:
            oldest_dt = _parse_iso(row["oldest"])
        except ValueError as exc:
            return False, f"Cannot parse oldest exit_time: {exc}"

        age_days = (_now_utc() - oldest_dt).days
        passed = age_days >= _MIN_PAPER_DAYS
        evidence = (
            f"Oldest closed trade: {row['oldest']} ({age_days}d ago); "
            f"threshold: {_MIN_PAPER_DAYS}d"
        )
        return passed, evidence


class PaperTradesCountCriterion(Phase3Criterion):
    """C2 — at least 100 completed paper trades."""

    name: str = "paper_trades_count"
    description: str = (
        "At least 100 closed paper trades required. Statistical significance "
        "threshold: fewer than 100 trades cannot distinguish edge from luck."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        try:
            conn = _open_db(db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM paper_trades WHERE status = 'closed'"
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        cnt = row["cnt"] if row else 0
        passed = cnt >= _MIN_PAPER_TRADES
        return passed, f"Closed paper trades: {cnt}; threshold: {_MIN_PAPER_TRADES}"


class WinRateCriterion(Phase3Criterion):
    """C3 — win rate >= 55% over the last 60 days."""

    name: str = "win_rate"
    description: str = (
        "Win rate (closed trades where pnl > 0) must be >= 55% over the last "
        "60 calendar days. A 55% floor with positive expectancy confirms the "
        "strategy has durable directional edge."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        cutoff = (_now_utc() - _60D).isoformat()
        try:
            conn = _open_db(db_path)
            try:
                row = conn.execute(
                    "SELECT "
                    "  COUNT(*) AS total, "
                    "  SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins "
                    "FROM paper_trades "
                    "WHERE status = 'closed' AND pnl IS NOT NULL "
                    "  AND exit_time >= ?",
                    (cutoff,),
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        total = row["total"] if row else 0
        wins = row["wins"] if row else 0

        if total == 0:
            return False, "No closed trades with PnL in the last 60 days"

        win_rate = wins / total
        passed = win_rate >= _MIN_WIN_RATE
        return (
            passed,
            f"Win rate: {wins}/{total} = {win_rate:.1%}; threshold: {_MIN_WIN_RATE:.0%}",
        )


class ProfitFactorCriterion(Phase3Criterion):
    """C4 — profit factor >= 1.5 over the last 60 days."""

    name: str = "profit_factor"
    description: str = (
        "Profit factor (gross profit / gross loss) >= 1.5 over the last 60 "
        "calendar days. PF 1.5 after slippage/commissions implies genuine "
        "positive expectancy; PF < 1.5 in live conditions typically degrades "
        "further due to wider spreads."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        cutoff = (_now_utc() - _60D).isoformat()
        try:
            conn = _open_db(db_path)
            try:
                row = conn.execute(
                    "SELECT "
                    "  SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0.0 END) AS gross_profit, "
                    "  SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0.0 END) AS gross_loss "
                    "FROM paper_trades "
                    "WHERE status = 'closed' AND pnl IS NOT NULL "
                    "  AND exit_time >= ?",
                    (cutoff,),
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        gross_profit = float(row["gross_profit"] or 0.0) if row else 0.0
        gross_loss = float(row["gross_loss"] or 0.0) if row else 0.0

        if gross_loss == 0.0:
            if gross_profit == 0.0:
                return False, "No closed trades with PnL in the last 60 days"
            pf = float("inf")
            return True, f"Profit factor: inf (no losses); threshold: {_MIN_PROFIT_FACTOR}"

        pf = gross_profit / gross_loss
        passed = pf >= _MIN_PROFIT_FACTOR
        return (
            passed,
            f"Profit factor: {pf:.2f} (gross_profit=${gross_profit:.2f}, "
            f"gross_loss=${gross_loss:.2f}); threshold: {_MIN_PROFIT_FACTOR}",
        )


class MaxDrawdownCriterion(Phase3Criterion):
    """C5 — max drawdown <= 8% from realized peak over the last 60 days.

    Uses ``realized_peak_equity`` (migration_029) instead of ``peak_equity`` to
    avoid phantom drawdowns caused by mark-to-market swings on open positions.

    Distinction from the kill switch:
    - Kill switch (safety_layer.py) uses ``peak_equity`` (MTM) for the -10%
      drawdown halt.  That is INTENTIONAL — an open position with an unrealized
      gain that then reverses IS a real intraday exposure risk.
    - C5 (this criterion) uses ``realized_peak_equity`` to measure strategy
      quality over 60 calendar days.  Phantom drawdowns from MTM swings that
      fully reverse intraday are noise for strategy evaluation.
    - Both columns coexist; safety_layer.py is never imported or modified here.
    """

    name: str = "max_drawdown"
    description: str = (
        "Maximum drawdown from realized equity peak must stay <= 8% over the "
        "last 60 days (measured from pnl_snapshots.realized_peak_equity). "
        "Uses realized equity (closed trades only) to exclude phantom drawdowns "
        "from mark-to-market swings on open positions. "
        "The kill switch still uses peak_equity (MTM) — that is intentional and "
        "unchanged. The 8% threshold is 20% stricter than the kill-switch's 10%."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        cutoff = (_now_utc() - _60D).strftime("%Y-%m-%d")
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT date, portfolio_equity, peak_equity, realized_peak_equity "
                    "FROM pnl_snapshots "
                    "WHERE date >= ? "
                    "ORDER BY date ASC",
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        if not rows:
            return False, "No pnl_snapshots data in the last 60 days"

        # Determine whether the realized_peak_equity column is populated.
        # It is NULL for rows written before migration_029 ran.  Fall back
        # to peak_equity for those rows so the check degrades gracefully on
        # DBs that haven't run the migration yet.
        has_realized = any(r["realized_peak_equity"] is not None for r in rows)
        if not has_realized:
            # Fallback: use MTM peak_equity (pre-migration_029 behaviour).
            # Log a warning so the operator knows the phantom-drawdown fix is
            # not yet active and should run migrations.
            fallback_note = (
                " [WARN: realized_peak_equity NULL for all rows — "
                "migration_029 not applied; using MTM peak_equity as fallback]"
            )
            max_dd = 0.0
            peak = 0.0
            worst_date = None
            for r in rows:
                eq = float(r["portfolio_equity"] or 0.0)
                pk = float(r["peak_equity"] or 0.0)
                if pk > peak:
                    peak = pk
                if peak > 0.0:
                    dd = (peak - eq) / peak
                    if dd > max_dd:
                        max_dd = dd
                        worst_date = r["date"]
            passed = max_dd <= _MAX_DRAWDOWN
            return (
                passed,
                f"Max drawdown (MTM fallback): {max_dd:.1%} on {worst_date or 'N/A'}; "
                f"threshold: {_MAX_DRAWDOWN:.0%}{fallback_note}",
            )

        # Primary path: use realized_peak_equity (migration_029).
        # For rows where realized_peak_equity is still NULL (written before
        # migration_029 ran the backfill), fall back to that row's peak_equity.
        max_dd = 0.0
        realized_peak = 0.0
        worst_date = None
        for r in rows:
            eq = float(r["portfolio_equity"] or 0.0)
            # Prefer realized_peak_equity; fall back to peak_equity per row
            rpk_raw = r["realized_peak_equity"]
            rpk = float(rpk_raw) if rpk_raw is not None else float(r["peak_equity"] or 0.0)
            if rpk > realized_peak:
                realized_peak = rpk
            if realized_peak > 0.0:
                dd = (realized_peak - eq) / realized_peak
                if dd > max_dd:
                    max_dd = dd
                    worst_date = r["date"]

        passed = max_dd <= _MAX_DRAWDOWN
        return (
            passed,
            f"Max drawdown (realized peak): {max_dd:.1%} on {worst_date or 'N/A'}; "
            f"threshold: {_MAX_DRAWDOWN:.0%} "
            f"(realized_peak={realized_peak:.2f}, excludes open-position MTM)",
        )


class SortinoRatioCriterion(Phase3Criterion):
    """C6 — annualised Sortino ratio >= 1.0 over the last 60 days."""

    name: str = "sortino_ratio"
    description: str = (
        "Annualised Sortino ratio >= 1.0 over the last 60 calendar days "
        "(computed from daily P&L series in pnl_snapshots). Sortino penalises "
        "downside volatility only, making it more appropriate than Sharpe for "
        "skewed futures strategies."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        cutoff = (_now_utc() - _60D).strftime("%Y-%m-%d")
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT date, daily_pnl, portfolio_equity "
                    "FROM pnl_snapshots "
                    "WHERE date >= ? "
                    "ORDER BY date ASC",
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        if len(rows) < 10:
            return (
                False,
                f"Insufficient pnl_snapshots ({len(rows)} rows, need >= 10); "
                "cannot compute Sortino",
            )

        # daily returns as fraction of starting equity
        returns = []
        for r in rows:
            eq = float(r["portfolio_equity"] or 0.0)
            pnl = float(r["daily_pnl"] or 0.0)
            starting = eq - pnl
            if starting > 0.0:
                returns.append(pnl / starting)

        if len(returns) < 10:
            return (
                False,
                f"Insufficient non-zero equity rows ({len(returns)}); cannot compute Sortino",
            )

        mean_r = sum(returns) / len(returns)
        # downside deviation: only negative returns vs 0 (MAR=0)
        neg_sq = [r**2 for r in returns if r < 0.0]
        if not neg_sq:
            # No negative returns — Sortino is infinite, trivially pass
            return True, "Sortino: infinite (no down-days in 60d window)"

        downside_std = math.sqrt(sum(neg_sq) / len(returns))  # use len(returns), not len(neg_sq)
        if downside_std == 0.0:
            return True, "Sortino: infinite (downside std = 0)"

        sortino_daily = mean_r / downside_std
        sortino_ann = sortino_daily * math.sqrt(252)
        passed = sortino_ann >= _MIN_SORTINO
        return (
            passed,
            f"Sortino (annualised): {sortino_ann:.2f}; threshold: {_MIN_SORTINO}",
        )


class ConsecutiveLossStreakCriterion(Phase3Criterion):
    """C7 — no losing streak > 5 in the last 60 days."""

    name: str = "consecutive_loss_streak"
    description: str = (
        "Maximum consecutive losing trade streak <= 5 over the last 60 days. "
        "A streak > 5 indicates either a regime break or a systematic error "
        "that must be investigated before live capital is committed."
    )
    severity: Literal["blocker", "warning", "info"] = "warning"

    def check(self, db_path: str) -> tuple[bool, str]:
        cutoff = (_now_utc() - _60D).isoformat()
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT pnl FROM paper_trades "
                    "WHERE status = 'closed' AND pnl IS NOT NULL "
                    "  AND exit_time >= ? "
                    "ORDER BY exit_time ASC",
                    (cutoff,),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        if not rows:
            return False, "No closed trades in the last 60 days"

        max_streak = 0
        current_streak = 0
        for r in rows:
            pnl = float(r["pnl"] or 0.0)
            if pnl < 0.0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        passed = max_streak <= _MAX_CONSECUTIVE_LOSSES
        return (
            passed,
            f"Max losing streak: {max_streak}; threshold: <= {_MAX_CONSECUTIVE_LOSSES}",
        )


class KillSwitchInvocationsCriterion(Phase3Criterion):
    """C8 — kill switch triggered <= 2 times in the last 60 days."""

    name: str = "kill_switch_invocations"
    description: str = (
        "Kill switch was triggered at most 2 times over the last 60 days. "
        "More than 2 automatic triggers implies repeated hard-limit breaches "
        "that must be resolved before live deployment."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        """
        Count kill switch invocations from engine logs in the last 60 days.

        Primary source: engine/logs/ directory, scanning for
        'KILL SWITCH ACTIVATED' in log lines within the 60-day window.
        Fallback: if logs are absent or unreadable, read the system_state
        table (only captures current state, not history — treated as 0
        invocations if switch is currently inactive).
        """
        cutoff = _now_utc() - _60D
        engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(engine_dir, "logs")

        count = 0
        source = "logs"
        if os.path.isdir(log_dir):
            try:
                for fname in os.listdir(log_dir):
                    if not fname.endswith((".log", ".txt")):
                        continue
                    fpath = os.path.join(log_dir, fname)
                    try:
                        with open(fpath, encoding="utf-8", errors="replace") as fh:
                            for line in fh:
                                if "KILL SWITCH ACTIVATED" not in line:
                                    continue
                                # Try to extract timestamp from common log formats
                                # e.g. "2026-05-08T10:18:18..." or "2026-05-08 10:18:18"
                                parts = line.split()
                                if parts:
                                    try:
                                        ts = _parse_iso(parts[0])
                                        if ts >= cutoff:
                                            count += 1
                                    except ValueError:
                                        # timestamp not parseable → count it conservatively
                                        count += 1
                    except OSError:
                        continue
            except OSError as exc:
                source = f"log scan failed ({exc}), using system_state"
                count = 0
        else:
            source = "no logs dir, using system_state"

        if source.startswith("no logs") or source.startswith("log scan failed"):
            # Fallback: check system_state — only current state, not history
            try:
                conn = _open_db(db_path)
                try:
                    row = conn.execute(
                        "SELECT value FROM system_state WHERE key = 'kill_switch_active'"
                    ).fetchone()
                finally:
                    conn.close()
                if row and row["value"] == "true":
                    count = 1  # currently active = at least 1 invocation
            except Exception:
                pass

        passed = count <= _MAX_KILL_SWITCH_INVOCATIONS
        return (
            passed,
            f"Kill switch activations (last 60d, source={source}): {count}; "
            f"threshold: <= {_MAX_KILL_SWITCH_INVOCATIONS}",
        )


class EngineUptimeStabilityCriterion(Phase3Criterion):
    """C9 — engine restart rate < 1/day average over the last 30 days."""

    name: str = "engine_uptime_stability"
    description: str = (
        "Engine restart count must average < 1 per day over the last 30 days. "
        "Frequent restarts during paper trading predict instability under live "
        "market conditions. Source: engine/data/pm2_restart_history.json."
    )
    severity: Literal["blocker", "warning", "info"] = "warning"

    def check(self, db_path: str) -> tuple[bool, str]:
        import json

        engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sidecar = os.path.join(engine_dir, "data", "pm2_restart_history.json")

        cutoff = _now_utc() - _30D
        restart_count = 0
        source = "pm2_restart_history.json"

        if os.path.exists(sidecar):
            try:
                with open(sidecar, encoding="utf-8") as fh:
                    history = json.load(fh)
                # History is a list of ISO timestamps or a dict with 'restarts' list
                if isinstance(history, list):
                    timestamps = history
                elif isinstance(history, dict):
                    timestamps = history.get("restarts", [])
                else:
                    timestamps = []

                for ts_raw in timestamps:
                    try:
                        ts = _parse_iso(str(ts_raw))
                        if ts >= cutoff:
                            restart_count += 1
                    except ValueError:
                        pass
            except (OSError, ValueError) as exc:
                source = f"sidecar read failed: {exc}"

            rate = restart_count / 30.0
            passed = rate < _MAX_RESTART_PER_DAY
            return (
                passed,
                f"Restarts in last 30d (source={source}): {restart_count} "
                f"({rate:.2f}/day); threshold: < {_MAX_RESTART_PER_DAY}/day",
            )

        # Fallback: try pm2_restart_count_72h.json sidecar
        sidecar72 = os.path.join(engine_dir, "data", "pm2_restart_count_72h.json")
        if os.path.exists(sidecar72):
            try:
                import json as _json

                data = _json.loads(open(sidecar72, encoding="utf-8").read())
                count_72h = int(data.get("restarts_72h", 0) or 0)
                # Extrapolate: 72h rate → 30d rate (conservative)
                estimated_30d = int(count_72h * (30 * 24 / 72))
                rate = estimated_30d / 30.0
                passed = rate < _MAX_RESTART_PER_DAY
                return (
                    passed,
                    f"Restarts (extrapolated from 72h={count_72h}, est 30d={estimated_30d}, "
                    f"{rate:.2f}/day); threshold: < {_MAX_RESTART_PER_DAY}/day",
                )
            except Exception as exc:
                source = f"72h sidecar failed: {exc}"

        # No restart data available — treat as 0 restarts (benefit of doubt)
        return (
            True,
            "No restart history available (pm2_restart_history.json absent); "
            "assuming stable (benefit of doubt)",
        )


class SafetyLayerTestCoverageCriterion(Phase3Criterion):
    """C10 — safety_layer.py test coverage >= 95%."""

    name: str = "safety_layer_test_coverage"
    description: str = (
        "engine/tests/test_safety_layer.py must achieve >= 95% line coverage "
        "of engine/risk/safety_layer.py (measured via coverage.py). The safety "
        "layer is the only hard-line defense against runaway orders; gaps in "
        "its test coverage are unacceptable before live capital."
    )
    severity: Literal["blocker", "warning", "info"] = "blocker"

    def check(self, db_path: str) -> tuple[bool, str]:
        engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Locate Python in the engine venv
        venv_python = os.path.join(engine_dir, ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            venv_python = os.path.join(engine_dir, ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            return False, "Engine venv python not found; cannot run coverage"

        try:
            result = subprocess.run(
                [
                    venv_python,
                    "-m",
                    "pytest",
                    "tests/test_safety_layer.py",
                    "--cov=risk",
                    "--cov-report=term-missing",
                    "-q",
                    "--no-header",
                    "--tb=no",
                ],
                capture_output=True,
                text=True,
                cwd=engine_dir,
                timeout=240,
            )
        except subprocess.TimeoutExpired:
            return False, "Coverage run timed out (>240s)"
        except OSError as exc:
            return False, f"Cannot run coverage: {exc}"

        # Parse coverage percentage from pytest-cov output
        # Typical line: "risk/safety_layer        1735   103   94%   ..."
        # or: "TOTAL                     ..."
        output = result.stdout + result.stderr
        coverage_pct = None
        for line in output.splitlines():
            line_lower = line.lower()
            if "safety_layer" in line_lower and "%" in line:
                parts = line.split()
                for part in reversed(parts):
                    part = part.rstrip("%")
                    try:
                        coverage_pct = float(part)
                        break
                    except ValueError:
                        continue
                if coverage_pct is not None:
                    break

        if coverage_pct is None:
            # Could not parse — check if tests just passed without coverage
            if result.returncode == 0:
                return (
                    False,
                    "Tests passed but could not parse coverage percentage from output",
                )
            return (
                False,
                f"Coverage run failed (exit={result.returncode}); "
                f"last 3 lines: {output.strip().splitlines()[-3:]}",
            )

        passed = coverage_pct >= (_MIN_SAFETY_COVERAGE * 100)
        return (
            passed,
            f"safety_layer.py test coverage: {coverage_pct:.0f}%; "
            f"threshold: {_MIN_SAFETY_COVERAGE:.0%}",
        )


# ---------------------------------------------------------------------------
# Edge-mode decoupling (OPT-IN — default behavior is unchanged)
# ---------------------------------------------------------------------------
# Two NEW criteria + an OPT-IN evaluator that lets the walk-forward edge proof
# (gate-v2 PASS on 2+ years of OOS data) + a small sample of REAL execution
# fidelity substitute for the paper-accrual edge gates (100 trades / 60 days).
#
# SAFETY DESIGN (why this cannot weaken the current posture):
#   - The default mode is "paper_accrual" — evaluate_all_criteria and the 10
#     criteria in _ALL_CRITERIA are UNCHANGED and remain the default everywhere.
#   - The two new criteria declare severity "info", so even when added to a
#     report they never block by default.
#   - The "wfo_plus_fidelity" mode is reached ONLY via READINESS_EDGE_MODE or an
#     explicit argument, and it requires ExecutionFidelity to PASS — which itself
#     requires ALLOW_PAPER_SIMULATED_ORDERS=True (real fills). While that flag is
#     False the mode yields NO-GO, so it is inert until forward-test is enabled.
#   - This module remains informational only (per the file invariants): it never
#     reads/writes LIVE_TRADING_ENABLED, never imports safety_layer, never mutates
#     config. Live trading still requires the separate hardcoded flags + the human
#     [safety-review] checklist.

VERDICT_TTL_DAYS = 30

# Max age of the latest health_snapshots row that may certify execution fidelity.
# A days-old "broker up" snapshot must not vouch for current broker/kill-switch
# state on the live-readiness path.
HEALTH_SNAPSHOT_TTL_MIN = 15

EDGE_MODE_PAPER_ACCRUAL = "paper_accrual"
EDGE_MODE_WFO_FIDELITY = "wfo_plus_fidelity"
_VALID_EDGE_MODES = (EDGE_MODE_PAPER_ACCRUAL, EDGE_MODE_WFO_FIDELITY)

# Edge-accrual criteria — demoted to informational under wfo_plus_fidelity mode
# because the walk-forward analysis already proves edge.
_EDGE_ACCRUAL_NAMES = frozenset(
    {
        "paper_trading_window",
        "paper_trades_count",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "sortino_ratio",
    }
)


def _edge_mode() -> str:
    """Resolve the readiness edge mode from env (default: paper_accrual)."""
    raw = os.environ.get("READINESS_EDGE_MODE", EDGE_MODE_PAPER_ACCRUAL).strip().lower()
    return raw if raw in _VALID_EDGE_MODES else EDGE_MODE_PAPER_ACCRUAL


def _paper_sim_enabled() -> bool:
    """Read ONLY ALLOW_PAPER_SIMULATED_ORDERS (never LIVE_TRADING_ENABLED).

    Indirection so tests can monkeypatch. Lazy-imports config to avoid a
    module-load dependency; falls back to the env var if config is unavailable.
    """
    try:
        from config import settings

        return bool(getattr(settings, "ALLOW_PAPER_SIMULATED_ORDERS", False))
    except Exception:
        return os.environ.get("ALLOW_PAPER_SIMULATED_ORDERS", "false").strip().lower() in (
            "1",
            "true",
            "yes",
        )


def _verdicts_dir() -> str:
    engine_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_dir, "data", "gate_v2_verdicts")


def _scan_current_pass_symbols(verdicts_dir: str, now: datetime | None = None) -> set[str]:
    """Symbols with a current (<= VERDICT_TTL_DAYS old) gate-v2 PASS verdict."""
    import json as _json

    now = now or _now_utc()
    out: set[str] = set()
    if not os.path.isdir(verdicts_dir):
        return out
    for fname in os.listdir(verdicts_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(verdicts_dir, fname), encoding="utf-8") as fh:
                v = _json.load(fh)
        except (OSError, ValueError):
            continue
        if str(v.get("verdict", "")).upper() != "PASS":
            continue
        created = v.get("created_at")
        if not created:
            continue
        try:
            age_days = (now - _parse_iso(str(created))).days
        except ValueError:
            continue
        if age_days <= VERDICT_TTL_DAYS:
            sym = str(v.get("symbol", "")).upper()
            if sym:
                out.add(sym)
    return out


class WalkForwardEdgeCriterion(Phase3Criterion):
    """C11 (edge-mode) — every actively-traded symbol has a current gate-v2 PASS.

    The walk-forward edge proof: gate-v2 PASS on 2+ years of out-of-sample data.
    Under READINESS_EDGE_MODE=wfo_plus_fidelity this is the evidence that lets the
    paper-accrual edge gates be treated as informational. Declared severity 'info'
    so it NEVER affects the default (paper_accrual) verdict.
    """

    name: str = "walk_forward_edge"
    description: str = (
        "Every actively-traded symbol has a current (<= 30-day) gate-v2 PASS "
        "verdict. This is the walk-forward edge proof (out-of-sample on 2+ years) "
        "that substitutes for paper-accrual edge gates under wfo_plus_fidelity mode."
    )
    severity: Literal["blocker", "warning", "info"] = "info"

    def check(self, db_path: str) -> tuple[bool, str]:
        verdicts_dir = _verdicts_dir()
        current_pass = _scan_current_pass_symbols(verdicts_dir)
        if not current_pass:
            return False, f"No current gate-v2 PASS verdicts (<= {VERDICT_TTL_DAYS}d)"

        traded: set[str] = set()
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT DISTINCT symbol FROM paper_trades WHERE status = 'closed'"
                ).fetchall()
                traded = {str(r["symbol"]).upper() for r in rows if r["symbol"]}
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        if not traded:
            return (
                True,
                f"No closed paper trades yet; current PASS verdicts: {sorted(current_pass)}",
            )

        missing = traded - current_pass
        if not missing:
            return True, f"All traded symbols have current PASS verdicts: {sorted(traded)}"
        return (
            False,
            f"Traded symbols missing current PASS verdict: {sorted(missing)} "
            f"(have: {sorted(current_pass)})",
        )


class ExecutionFidelityCriterion(Phase3Criterion):
    """C12 (edge-mode) — execution fidelity on REAL broker fills.

    Requires ALLOW_PAPER_SIMULATED_ORDERS=True (so real fills exist), >= min_fills
    closed trades, avg slippage within bounds, broker connected, kill switch
    inactive, and realized PF >= 1.0 (sign-check, NOT the 2.0 edge gate). Declared
    severity 'info' so it never affects the default verdict; promoted to blocker
    only under wfo_plus_fidelity mode. Inert while ALLOW_PAPER_SIMULATED_ORDERS is
    False (returns FAIL → wfo mode yields NO-GO).
    """

    name: str = "execution_fidelity"
    description: str = (
        "Execution fidelity on REAL IB paper fills: >= 15 fills with MEASURED "
        "slippage, avg slippage <= 1.5 ticks, broker connected on a FRESH health "
        "snapshot, kill switch inactive, realized PF >= 1.0 (sign-check). Requires "
        "ALLOW_PAPER_SIMULATED_ORDERS=True; inert otherwise."
    )
    severity: Literal["blocker", "warning", "info"] = "info"

    def check(self, db_path: str) -> tuple[bool, str]:
        if not _paper_sim_enabled():
            return (
                False,
                "ALLOW_PAPER_SIMULATED_ORDERS=False: orders are simulated, no real "
                "broker fills to measure. Enable the IBKR paper order path before "
                "relying on execution fidelity.",
            )

        try:
            from paper.validation_gate_config import EXECUTION_FIDELITY_GATES

            min_fills = int(EXECUTION_FIDELITY_GATES["min_fills"])
            max_slip = float(EXECUTION_FIDELITY_GATES["max_avg_slippage_ticks"])
            pf_floor = float(EXECUTION_FIDELITY_GATES["min_realized_pf_floor"])
        except Exception:
            min_fills, max_slip, pf_floor = 15, 1.5, 1.0

        try:
            conn = _open_db(db_path)
            try:
                trade_rows = conn.execute(
                    "SELECT pnl, slippage_ticks FROM paper_trades "
                    "WHERE status = 'closed' AND pnl IS NOT NULL"
                ).fetchall()
                health = conn.execute(
                    "SELECT ts_utc, ibkr_data, ibkr_exec, kill_switch "
                    "FROM health_snapshots ORDER BY ts_utc DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()
        except Exception as exc:
            return False, f"DB error: {exc}"

        n = len(trade_rows)
        if n < min_fills:
            return False, f"Only {n} real fills; need >= {min_fills} for fidelity"

        slips = [
            float(r["slippage_ticks"]) for r in trade_rows if r["slippage_ticks"] is not None
        ]
        # Hardening 1: intent rows with NULL slippage are not fidelity evidence.
        # Require >= min_fills rows that carry a MEASURED slippage_ticks value
        # before the slippage bound can be trusted; otherwise 15 unmatched rows
        # would pass while the slippage check is silently skipped (the old
        # `if slips and ...` guard short-circuited when every row was NULL).
        if len(slips) < min_fills:
            return (
                False,
                f"Only {len(slips)}/{n} fills carry measured slippage; reconcile "
                f"real IB fills (>= {min_fills} with slippage_ticks) before relying "
                "on execution fidelity",
            )
        avg_slip = sum(slips) / len(slips)
        if avg_slip > max_slip:
            return False, f"Avg slippage {avg_slip:.2f}t > {max_slip}t threshold"

        pnls = [float(r["pnl"]) for r in trade_rows]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
        if pf < pf_floor:
            return False, f"Realized PF {pf:.2f} < {pf_floor} floor"

        if health is None:
            return False, "No health snapshot for broker/kill-switch state"
        # Hardening 2: a stale snapshot cannot certify the broker is up NOW.
        # Reject anything older than HEALTH_SNAPSHOT_TTL_MIN minutes (or an
        # unparseable / missing timestamp) so a days-old "all green" row can't
        # vouch for a link that may have dropped since it was written.
        ts_raw = health["ts_utc"]
        try:
            age_min = (_now_utc() - _parse_iso(str(ts_raw))).total_seconds() / 60.0
        except (ValueError, TypeError):
            return False, f"Unparseable health snapshot timestamp: {ts_raw!r}"
        if age_min > HEALTH_SNAPSHOT_TTL_MIN:
            return (
                False,
                f"Health snapshot stale ({age_min:.1f} min old > "
                f"{HEALTH_SNAPSHOT_TTL_MIN} min TTL); cannot certify broker is up now",
            )
        data_ok = bool(health["ibkr_data"]) if health["ibkr_data"] is not None else False
        exec_ok = bool(health["ibkr_exec"]) if health["ibkr_exec"] is not None else False
        ks_active = bool(health["kill_switch"]) if health["kill_switch"] is not None else False
        if not (data_ok and exec_ok):
            return False, f"Broker link degraded (data={data_ok}, exec={exec_ok})"
        if ks_active:
            return False, "Kill switch ACTIVE"

        pf_disp = "inf" if pf == float("inf") else f"{pf:.2f}"
        return (
            True,
            f"{n} real fills, avg slip {avg_slip:.2f}t, PF {pf_disp}, broker up, "
            "kill switch inactive",
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ALL_CRITERIA: list[Phase3Criterion] = [
    PaperTradingWindowCriterion(),
    PaperTradesCountCriterion(),
    WinRateCriterion(),
    ProfitFactorCriterion(),
    MaxDrawdownCriterion(),
    SortinoRatioCriterion(),
    ConsecutiveLossStreakCriterion(),
    KillSwitchInvocationsCriterion(),
    EngineUptimeStabilityCriterion(),
    SafetyLayerTestCoverageCriterion(),
]

# Criteria set for wfo_plus_fidelity mode: the 4 operational/safety criteria +
# the 2 WFO/fidelity substitutes (promoted to blockers) + the 6 edge-accrual
# criteria (demoted to info). _ALL_CRITERIA above is intentionally untouched.
_WFO_MODE_CRITERIA: list[Phase3Criterion] = [
    WalkForwardEdgeCriterion(),
    ExecutionFidelityCriterion(),
    ConsecutiveLossStreakCriterion(),
    KillSwitchInvocationsCriterion(),
    EngineUptimeStabilityCriterion(),
    SafetyLayerTestCoverageCriterion(),
    PaperTradingWindowCriterion(),
    PaperTradesCountCriterion(),
    WinRateCriterion(),
    ProfitFactorCriterion(),
    MaxDrawdownCriterion(),
    SortinoRatioCriterion(),
]


def _effective_severity(name: str, declared: str, mode: str) -> str:
    """Severity used for verdict computation under a given edge mode.

    paper_accrual: declared severity (unchanged).
    wfo_plus_fidelity: edge-accrual criteria -> info; WFO/fidelity -> blocker.
    """
    if mode == EDGE_MODE_WFO_FIDELITY:
        if name in _EDGE_ACCRUAL_NAMES:
            return "info"
        if name in ("walk_forward_edge", "execution_fidelity"):
            return "blocker"
    return declared


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def evaluate_all_criteria(db_path: str) -> dict:
    """
    Run every Phase 3 criterion and return a structured result.

    Parameters
    ----------
    db_path:
        Absolute path to the jarvis_trader SQLite database.

    Returns
    -------
    dict with keys:
        summary: {
            pass: int,
            fail: int,
            total: int,
            severity_breakdown: {blocker: {...}, warning: {...}, info: {...}},
            overall: "GO" | "WAIT" | "NO-GO"
        }
        criteria: [
            {name, status, evidence, severity}, ...
        ]
        evaluated_at: ISO-8601 timestamp

    Overall logic:
        GO     — ALL blocker criteria pass AND at most 1 warning fails
        NO-GO  — ANY blocker criterion fails
        WAIT   — All blockers pass but more than 1 warning fails
    """
    results = []
    severity_breakdown: dict[str, dict] = {
        "blocker": {"pass": 0, "fail": 0},
        "warning": {"pass": 0, "fail": 0},
        "info": {"pass": 0, "fail": 0},
    }

    blocker_fail_count = 0
    warning_fail_count = 0

    for criterion in _ALL_CRITERIA:
        try:
            passed, evidence = criterion.check(db_path)
        except Exception as exc:
            passed = False
            evidence = f"Unhandled exception in check: {exc}"
            logger.exception("Phase3 criterion %s raised", criterion.name)

        severity = criterion.severity
        status = "PASS" if passed else "FAIL"
        severity_breakdown[severity]["pass" if passed else "fail"] += 1

        if not passed:
            if severity == "blocker":
                blocker_fail_count += 1
            elif severity == "warning":
                warning_fail_count += 1

        results.append(
            {
                "name": criterion.name,
                "description": criterion.description,
                "status": status,
                "evidence": evidence,
                "severity": severity,
            }
        )

    total_pass = sum(1 for r in results if r["status"] == "PASS")
    total_fail = len(results) - total_pass

    # Determine overall verdict
    if blocker_fail_count > 0:
        overall = "NO-GO"
    elif warning_fail_count > 1:
        overall = "WAIT"
    else:
        overall = "GO"

    return {
        "summary": {
            "pass": total_pass,
            "fail": total_fail,
            "total": len(results),
            "severity_breakdown": severity_breakdown,
            "overall": overall,
        },
        "criteria": results,
        "evaluated_at": _now_utc().isoformat(),
    }


def evaluate_with_edge_mode(db_path: str, mode: str | None = None) -> dict:
    """Evaluate readiness under a chosen edge mode (OPT-IN; default unchanged).

    mode=None reads READINESS_EDGE_MODE (default "paper_accrual").

    paper_accrual (DEFAULT):
        Identical to evaluate_all_criteria — the 10 standard criteria, standard
        severities — plus an ``edge_mode`` key. Byte-identical verdict.

    wfo_plus_fidelity (OPT-IN):
        The walk-forward edge proof (gate-v2 PASS) + real-fill execution fidelity
        become BLOCKERS; the 6 paper-accrual edge gates (window, count, win-rate,
        PF, drawdown, sortino) are demoted to INFO. The 4 operational/safety
        criteria keep their declared severity. Because ExecutionFidelity requires
        ALLOW_PAPER_SIMULATED_ORDERS=True (real fills), this mode yields NO-GO
        while that flag is False — inert until forward-test is enabled.

    Same return shape as evaluate_all_criteria, with an added top-level
    ``edge_mode`` key.
    """
    mode = (mode or _edge_mode()).strip().lower()
    if mode not in _VALID_EDGE_MODES:
        mode = EDGE_MODE_PAPER_ACCRUAL

    if mode == EDGE_MODE_PAPER_ACCRUAL:
        report = evaluate_all_criteria(db_path)
        report["edge_mode"] = EDGE_MODE_PAPER_ACCRUAL
        return report

    # wfo_plus_fidelity
    results = []
    severity_breakdown: dict[str, dict] = {
        "blocker": {"pass": 0, "fail": 0},
        "warning": {"pass": 0, "fail": 0},
        "info": {"pass": 0, "fail": 0},
    }
    blocker_fail_count = 0
    warning_fail_count = 0

    for criterion in _WFO_MODE_CRITERIA:
        try:
            passed, evidence = criterion.check(db_path)
        except Exception as exc:
            passed = False
            evidence = f"Unhandled exception in check: {exc}"
            logger.exception("Phase3 criterion %s raised", criterion.name)

        severity = _effective_severity(criterion.name, criterion.severity, mode)
        status = "PASS" if passed else "FAIL"
        severity_breakdown[severity]["pass" if passed else "fail"] += 1

        if not passed:
            if severity == "blocker":
                blocker_fail_count += 1
            elif severity == "warning":
                warning_fail_count += 1

        results.append(
            {
                "name": criterion.name,
                "description": criterion.description,
                "status": status,
                "evidence": evidence,
                "severity": severity,
            }
        )

    total_pass = sum(1 for r in results if r["status"] == "PASS")
    total_fail = len(results) - total_pass

    if blocker_fail_count > 0:
        overall = "NO-GO"
    elif warning_fail_count > 1:
        overall = "WAIT"
    else:
        overall = "GO"

    return {
        "summary": {
            "pass": total_pass,
            "fail": total_fail,
            "total": len(results),
            "severity_breakdown": severity_breakdown,
            "overall": overall,
        },
        "criteria": results,
        "evaluated_at": _now_utc().isoformat(),
        "edge_mode": EDGE_MODE_WFO_FIDELITY,
    }


def _render_markdown(report: dict) -> str:
    """Render the evaluate_all_criteria output as human-readable Markdown."""
    summary = report["summary"]
    overall = summary["overall"]
    lines = [
        "# Phase 3 Live-Trading Readiness Report",
        "",
        f"**Evaluated at:** {report['evaluated_at']}",
        "",
        "## Verdict",
        "",
        "```",
        f"  {overall}",
        "```",
        "",
        f"Pass: **{summary['pass']}/{summary['total']}**  "
        f"| Fail: **{summary['fail']}**  "
        f"| Blockers failing: **{summary['severity_breakdown']['blocker']['fail']}**  "
        f"| Warnings failing: **{summary['severity_breakdown']['warning']['fail']}**",
        "",
        "## Criteria",
        "",
        "| # | Name | Severity | Status | Evidence |",
        "|---|------|----------|--------|----------|",
    ]
    for i, c in enumerate(report["criteria"], start=1):
        status_icon = "PASS" if c["status"] == "PASS" else "FAIL"
        sev = c["severity"].upper()
        evidence = c["evidence"].replace("|", "/")
        lines.append(f"| {i} | `{c['name']}` | {sev} | {status_icon} | {evidence} |")

    lines += [
        "",
        "## What This Report Does NOT Cover",
        "",
        "The programmatic check is **necessary but not sufficient**.",
        "Matt must also confirm:",
        "",
        "- [ ] Hardware kill switch wired (physical emergency stop)",
        "- [ ] Account-level OCO orders configured at broker",
        "- [ ] Live IB Gateway port 4001 unblocked at network level",
        "- [ ] Phase 3 PR with `[safety-review]` tag approved",
        "- [ ] Capital commitment confirmed and documented",
        "",
        "See `docs/runbooks/PHASE3_READINESS_CRITERIA.md` for full detail.",
    ]
    return "\n".join(lines)
