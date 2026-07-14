"""
Paper Trading Validation Metrics
=================================
Computes Sharpe ratio, max drawdown, win rate, and progress toward
30-day validation targets directly from the SQLite paper_trades table.

This module is intentionally standalone — no dependency on the paper.*
validation tracker chain, so it always reflects ground-truth DB state.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "jarvis_trader.db"

# Canonical targets (aligned with paper.validation_gate_config.PAPER_VALIDATION_GATES)
TARGETS = {
    "min_days": 30,
    "min_sharpe": 1.5,
    "max_drawdown_pct": 15.0,   # expressed as positive %; passes when drawdown <= this
    "min_win_rate_pct": 55.0,   # percent (55.0 = 55%)
    "min_profit_factor": 2.0,
    "min_trades": 60,
}


class ValidationMetrics:
    """Compute validation dashboard metrics from SQLite paper_trades."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db = db_path

    def compute(self) -> dict:
        """Compute all validation metrics. Returns full status dict."""
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(self._db))
            conn.row_factory = sqlite3.Row
            return self._compute(conn)
        except Exception as e:
            logger.error(f"ValidationMetrics.compute failed: {e}", exc_info=True)
            return {"error": str(e)}
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── internal ─────────────────────────────────────────────────────────────

    def _compute(self, conn: sqlite3.Connection) -> dict:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]

        # Locate trade table
        trade_table: Optional[str] = None
        for candidate in ["paper_trades", "trades", "trade_log", "paper_trade_log"]:
            if candidate in tables:
                trade_table = candidate
                break

        if not trade_table:
            return {
                "status": "no_trades",
                "message": "No trade table found — execution loop may not be recording yet",
                "targets": TARGETS,
                "tables_found": tables,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch closed trades only
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM {trade_table}
                WHERE LOWER(status) IN ('closed', 'filled', 'done')
                ORDER BY entry_time ASC
                """
            ).fetchall()
        except Exception:
            # Fallback — the primary query above failed for some reason other
            # than a missing status column (e.g. a transient error or an
            # unrelated schema issue). Re-apply the same terminal-status
            # filter in Python so contaminated/duplicate/pending rows can't
            # leak into the go/no-go readiness gate just because the SQL
            # path degraded. Only skip filtering if the column itself is
            # genuinely absent from this table.
            rows = conn.execute(
                f"SELECT * FROM {trade_table} ORDER BY entry_time ASC"
            ).fetchall()
            if rows and "status" in rows[0].keys():
                rows = [
                    r for r in rows
                    if str(r["status"]).lower() in ("closed", "filled", "done")
                ]

        if not rows:
            return {
                "status": "no_trades",
                "message": "Trade table exists but has no closed trades yet",
                "targets": TARGETS,
                "trade_table": trade_table,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        trades = [dict(r) for r in rows]
        total_trades = len(trades)

        # ── PnL field detection ───────────────────────────────────────────
        pnl_field: Optional[str] = next(
            (k for k in trades[0].keys() if "pnl" in k.lower() or "profit" in k.lower()),
            None,
        )
        if pnl_field:
            pnls = [float(t[pnl_field]) for t in trades if t[pnl_field] is not None]
        else:
            # Derive from entry/exit price if available
            pnls = []
            for t in trades:
                ep = t.get("entry_price")
                xp = t.get("exit_price")
                qty = t.get("quantity") or 1
                if ep is not None and xp is not None:
                    pnls.append((float(xp) - float(ep)) * float(qty))

        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        win_rate = wins / len(pnls) if pnls else 0.0
        win_rate_pct = win_rate * 100.0
        total_pnl = sum(pnls)

        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = sum(abs(p) for p in pnls if p < 0)
        profit_factor = (
            (gross_profit / gross_loss)
            if gross_loss > 0
            else (9999.0 if gross_profit > 0 else 0.0)
        )

        # ── Sharpe ratio (annualized, daily P&L grouping) ────────────────
        sharpe = self._compute_sharpe(trades) if total_trades >= 2 else None

        # ── Max drawdown ─────────────────────────────────────────────────
        max_drawdown_pct = self._compute_max_drawdown_pct(pnls)

        # ── Days elapsed ─────────────────────────────────────────────────
        days_elapsed = self._compute_days_elapsed(trades)

        # ── Targets met ──────────────────────────────────────────────────
        targets_met = {
            "days_30":            days_elapsed >= TARGETS["min_days"],
            "sharpe_1_5":         (sharpe or 0.0) >= TARGETS["min_sharpe"],
            "drawdown_15pct":     max_drawdown_pct <= TARGETS["max_drawdown_pct"],
            "win_rate_55pct":     win_rate_pct >= TARGETS["min_win_rate_pct"],
            "profit_factor_2_0":  profit_factor >= TARGETS["min_profit_factor"],
            "min_trades_60":      total_trades >= TARGETS["min_trades"],
        }
        all_targets_met = all(targets_met.values())
        targets_met_count = sum(targets_met.values())

        return {
            "status": "validated" if all_targets_met else "in_progress",
            "all_targets_met": all_targets_met,
            "targets_met": targets_met,
            "targets_met_count": f"{targets_met_count}/{len(targets_met)}",
            "metrics": {
                "days_elapsed":      days_elapsed,
                "days_remaining":    max(0, TARGETS["min_days"] - days_elapsed),
                "total_trades":      total_trades,
                "winning_trades":    wins,
                "losing_trades":     losses,
                "win_rate":          round(win_rate, 4),
                "win_rate_pct":      f"{win_rate_pct:.1f}%",
                "profit_factor":     round(profit_factor, 3),
                "sharpe_ratio":      round(sharpe, 3) if sharpe is not None else None,
                "max_drawdown_pct":  round(max_drawdown_pct, 2),
                "total_pnl":         round(total_pnl, 2),
                "gross_profit":      round(gross_profit, 2),
                "gross_loss":        round(gross_loss, 2),
                "avg_trade_pnl":     round(total_pnl / total_trades, 2) if total_trades else 0,
            },
            "targets": TARGETS,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_table": trade_table,
        }

    def _compute_sharpe(
        self,
        trades: list[dict],
        risk_free_rate: float = 0.04,
    ) -> Optional[float]:
        """Annualized Sharpe ratio from daily P&L buckets."""
        daily: defaultdict[date, float] = defaultdict(float)

        pnl_field: Optional[str] = next(
            (k for k in trades[0].keys() if "pnl" in k.lower() or "profit" in k.lower()),
            None,
        ) if trades else None

        for t in trades:
            # Use exit_time for daily bucketing (realized P&L date)
            ts_str = t.get("exit_time") or t.get("entry_time") or ""
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                day = dt.date()
            except (ValueError, TypeError):
                continue

            if pnl_field and t.get(pnl_field) is not None:
                daily[day] += float(t[pnl_field])
            else:
                ep = t.get("entry_price")
                xp = t.get("exit_price")
                qty = t.get("quantity") or 1
                if ep is not None and xp is not None:
                    daily[day] += (float(xp) - float(ep)) * float(qty)

        returns = list(daily.values())
        if len(returns) < 2:
            return None

        n = len(returns)
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return None

        # Annualize
        annual_return = mean * 252
        annual_std = std * math.sqrt(252)
        sharpe = (annual_return - risk_free_rate) / annual_std
        return max(0.0, sharpe)

    def _compute_max_drawdown_pct(self, pnls: list[float]) -> float:
        """Max peak-to-trough drawdown as a positive percentage of starting capital."""
        if not pnls:
            return 0.0
        starting_capital = 10_000.0
        peak = starting_capital
        cumulative = starting_capital
        max_dd = 0.0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            if peak > 0:
                dd = (peak - cumulative) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd
        return round(max_dd, 2)

    def _compute_days_elapsed(self, trades: list[dict]) -> int:
        """Days from first trade entry_time to today."""
        if not trades:
            return 0
        first_ts = trades[0].get("entry_time") or trades[0].get("exit_time") or ""
        try:
            dt = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
            return (date.today() - dt.date()).days
        except (ValueError, TypeError):
            return 0


# ── Module-level composite scoring functions ─────────────────────────────────


def composite_score(
    profit_factor: float,
    sharpe: float,
    wfe: float,
    max_drawdown_pct: float,
) -> float:
    """
    Composite strategy performance score for optimization target.

    Modeled after n-autoresearch's val_bpb (lower=better) but inverted:
    Higher composite_score = better strategy.

    Weights:
    - Profit Factor: 35% (primary edge indicator, capped at 6x)
    - Sharpe Ratio:  35% (risk-adjusted return quality, capped at 5.0)
    - WFE:           20% (walk-forward robustness, 0-1)
    - Drawdown:      10% (stability; 0% DD = full score, 20% DD = 0)

    Returns:
        float in range [0.0, 1.0]
    """
    pf_score = min(profit_factor, 6.0) / 6.0
    sharpe_score = min(max(sharpe, 0.0), 5.0) / 5.0
    wfe_score = max(0.0, min(wfe, 1.0))
    dd_score = 1.0 - min(max_drawdown_pct, 0.20) / 0.20

    return (
        pf_score * 0.35
        + sharpe_score * 0.35
        + wfe_score * 0.20
        + dd_score * 0.10
    )


def composite_score_from_results(backtest_results: dict) -> float:
    """
    Convenience wrapper — extract metrics from backtest result dict and compute score.

    Args:
        backtest_results: Dict with keys profit_factor, sharpe_ratio,
                          walk_forward_efficiency, max_drawdown_pct
    """
    return composite_score(
        profit_factor=backtest_results.get("profit_factor", 1.0),
        sharpe=backtest_results.get("sharpe_ratio", 0.0),
        wfe=backtest_results.get("walk_forward_efficiency", 0.0),
        max_drawdown_pct=backtest_results.get("max_drawdown_pct", 0.0),
    )


def composite_score_with_diagnostics(
    profit_factor: float,
    sharpe: float,
    wfe: float,
    max_drawdown_pct: float,
    *,
    n_trials: int,
    n_obs: int,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> dict:
    """composite_score plus a REPORT-ONLY Deflated Sharpe (DSR) diagnostic.

    Closes the gap flagged in `.claude/rules/ml-pitfalls-defense.md` pitfall #3:
    the raw ``composite_score`` blends PF/Sharpe/WFE/DD without any
    multiple-testing correction, so a Sharpe that is really the maximum over
    ``n_trials`` grid combinations is taken at face value. This wrapper attaches
    the DSR (Bailey & Lopez de Prado, SSRN-2460551) as context.

    IMPORTANT — report-only: the returned ``composite_score`` is byte-identical
    to ``composite_score(...)`` and is NOT influenced by the DSR. Nothing here
    gates a go/no-go decision. Per the rule, turning the DSR into an actual gate
    is a separate ``[safety-review]``/Tier-3 change; this is the diagnostic that
    precedes it. Reuses ``backtest.deflated_sharpe`` — the DSR math is not
    reimplemented here.

    Args:
        profit_factor, sharpe, wfe, max_drawdown_pct: as in ``composite_score``.
        n_trials: N independent trials (grid combinations explored) that the
            ``sharpe`` is the maximum over. ``1`` = no selection bias to correct.
        n_obs: T sample size (trades or bars) the ``sharpe`` was computed on.
            ``sharpe`` and ``n_obs`` must be consistent (same series).
        skew, kurt: return-series skew and RAW kurtosis (3.0 = Gaussian).

    Returns:
        {
            "composite_score": float,          # unchanged, == composite_score(...)
            "deflated_sharpe": dict,           # full deflated_sharpe_ratio() output
            "dsr": float,                      # convenience: DSR p-value (0..1)
            "dsr_passes_at_10pct": bool,       # convenience flag (report-only)
        }
    """
    score = composite_score(profit_factor, sharpe, wfe, max_drawdown_pct)
    # Lazy import: deflated_sharpe pulls numpy/scipy, not needed at module load.
    from backtest.deflated_sharpe import deflated_sharpe_ratio

    dsr = deflated_sharpe_ratio(
        sharpe=sharpe,
        n_trials=n_trials,
        n_obs=n_obs,
        skew=skew,
        kurt=kurt,
    )
    return {
        "composite_score": score,
        "deflated_sharpe": dsr,
        "dsr": dsr["dsr"],
        "dsr_passes_at_10pct": dsr["passes_at_10pct"],
    }


def composite_score_with_diagnostics_from_results(backtest_results: dict) -> dict:
    """Dict wrapper for ``composite_score_with_diagnostics``.

    Reads the DSR inputs from the same result dict, tolerating the common key
    aliases used across the backtest surfaces:
      - n_trials  <- ``n_trials`` | ``grid_combos`` | ``n_combos`` (default 1)
      - n_obs     <- ``n_obs`` | ``total_oos_trades`` | ``total_trades`` |
                     ``n_trades`` (default 0 -> DSR reports degenerate)
      - skew/kurt <- ``skew`` / ``kurt`` (default Gaussian)

    ``n_trials`` defaulting to 1 means "no correction applied" — an honest
    no-op, not a silent pass — when the caller does not record the trial count.
    """
    return composite_score_with_diagnostics(
        profit_factor=backtest_results.get("profit_factor", 1.0),
        sharpe=backtest_results.get("sharpe_ratio", 0.0),
        wfe=backtest_results.get("walk_forward_efficiency", 0.0),
        max_drawdown_pct=backtest_results.get("max_drawdown_pct", 0.0),
        n_trials=int(
            backtest_results.get("n_trials")
            or backtest_results.get("grid_combos")
            or backtest_results.get("n_combos")
            or 1
        ),
        n_obs=int(
            backtest_results.get("n_obs")
            or backtest_results.get("total_oos_trades")
            or backtest_results.get("total_trades")
            or backtest_results.get("n_trades")
            or 0
        ),
        skew=float(backtest_results.get("skew", 0.0)),
        kurt=float(backtest_results.get("kurt", 3.0)),
    )
