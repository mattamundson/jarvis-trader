"""Reports and analytics router."""

import logging
from datetime import datetime, timedelta
from datetime import timezone as _tz
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)


def get_db_path() -> str:
    """Return the SQLite database path (mirrors discord_router pattern)."""
    import os

    return os.environ.get("DB_PATH", "data/jarvis_trader.db")


# Global references (injected from main.py)
_db_manager = None


def inject_dependencies(db_manager):
    """Inject global dependencies from main.py"""
    global _db_manager
    _db_manager = db_manager


@router.get("/performance/7d")
async def get_7d_performance() -> dict[str, Any]:
    """Get 7-day performance summary."""
    try:
        from database.schema import get_db

        db = get_db()

        # Get all closed trades and filter to 7-day window
        cutoff = (datetime.now(_tz.utc) - timedelta(days=7)).isoformat()
        all_rows = db.get_closed_trades(limit=500)
        rows = [r for r in all_rows if r.get("exit_time", "") >= cutoff]

        if not rows or len(rows) == 0:
            return {
                "period": "7d",
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "trading_days": 0,
            }

        # Aggregate
        total = len(rows)
        wins = sum(1 for r in rows if r.get("pnl", 0) > 0)
        losses = total - wins
        total_pnl = sum(r.get("pnl", 0) for r in rows)
        pnls = [r.get("pnl", 0) for r in rows if r.get("pnl", 0)]

        return {
            "period": "7d",
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / total if total > 0 else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
            "trading_days": 0,
        }
    except Exception as e:
        logger.error(f"[REPORTS] 7d performance error: {e}")
        raise HTTPException(500, f"Failed to get 7d performance: {e}") from e


@router.get("/quantstats")
async def get_quantstats(
    run_id: str | None = Query(
        None, description="Optional run identifier to filter paper_trades by notes field"
    ),
    days: int = Query(90, ge=7, le=365, description="Look-back window in calendar days"),
    db_path: str = Depends(get_db_path),
) -> dict[str, Any]:
    """Return a QuantStats metrics blob for the paper trading window.

    Prefers ``pnl_snapshots`` (equity-curve based); falls back to aggregating
    ``paper_trades.pnl`` by exit date.  Returns the shell with nulls (200) when
    no trades exist in the window — never raises on empty data.
    """
    try:
        from reports.quantstats_metrics import _load_pnl_series, compute_quantstats_metrics

        series, source, n_trades, start, end = _load_pnl_series(db_path, run_id, days)
        metrics = compute_quantstats_metrics(series, source=source)
        metrics.update(
            {"n_trades": n_trades, "start_date": start, "end_date": end, "source": source}
        )
        return metrics
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[REPORTS] quantstats error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _build_performance_report_html(
    summary: dict,
    compare: dict,
    trades: list,
    daily_pnl: list,
    generated_at: str,
) -> str:
    """Build a self-contained HTML performance report."""

    def fmt_pct(v, decimals=1):
        if v is None:
            return "N/A"
        return f"{v * 100:.{decimals}f}%"

    def fmt_num(v, decimals=2):
        if v is None:
            return "N/A"
        return f"{v:.{decimals}f}"

    def fmt_usd(v):
        if v is None:
            return "N/A"
        return f"${v:,.2f}"

    pf = summary.get("profit_factor")
    sharpe = summary.get("sharpe_ratio")
    win_rate = summary.get("win_rate")
    max_dd = summary.get("max_drawdown", 0)
    total_trades = summary.get("total_trades", 0)
    gross_pnl = summary.get("gross_pnl", 0)

    pf_pass = pf and pf >= 2.0
    sharpe_pass = sharpe and sharpe >= 1.5

    pf_class = "pass" if pf_pass else ("fail" if pf else "neutral")
    sharpe_class = "pass" if sharpe_pass else ("fail" if sharpe else "neutral")

    gross_pnl_safe = gross_pnl or 0
    pnl_class = "pass" if gross_pnl_safe >= 0 else "fail"

    trade_rows = ""
    for t in trades[:100]:
        pnl = t.get("pnl", 0) or 0
        color = "#22c55e" if pnl >= 0 else "#ef4444"
        entry_price = t.get("entry_price", 0) or 0
        exit_price = t.get("exit_price", 0) or 0
        trade_rows += (
            "<tr>"
            f"<td>{t.get('symbol', '?')}</td>"
            f"<td>{t.get('side', '?').upper()}</td>"
            f"<td>{t.get('quantity', '?')}</td>"
            f"<td>${entry_price:.2f}</td>"
            f"<td>${exit_price:.2f}</td>"
            f'<td style="color:{color}">{fmt_usd(pnl)}</td>'
            f"<td>{str(t.get('entry_time', ''))[:10]}</td>"
            "</tr>"
        )

    _pnl_data = [r.get("realized_pnl", 0) for r in daily_pnl[-30:]]  # noqa: F841

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JARVIS TRADER - Performance Report</title>
<style>
body {{ font-family: Arial, sans-serif; background: #0a0a0a; color: #e5e5e5; padding: 24px; }}
h1 {{ margin-bottom: 4px; }}
p {{ color: #b5b5b5; }}
section {{ margin-top: 24px; padding: 16px; border: 1px solid #262626; background: #161616; border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #262626; }}
.pass {{ color: #22c55e; }}
.fail {{ color: #ef4444; }}
.neutral {{ color: #a3a3a3; }}
</style>
</head>
<body>
<h1>JARVIS TRADER - Performance Report</h1>
<p>Generated {generated_at[:10]} | Paper Trading Phase</p>
<section>
<h2>Summary</h2>
<p>Profit Factor: <span class="{pf_class}">{fmt_num(pf)}</span></p>
<p>Sharpe Ratio: <span class="{sharpe_class}">{fmt_num(sharpe)}</span></p>
<p>Win Rate: <span class="neutral">{fmt_pct(win_rate)}</span></p>
<p>Max Drawdown: <span class="fail">{fmt_pct(max_dd)}</span></p>
<p>Total Trades: <span class="neutral">{total_trades}</span></p>
<p>Gross P&amp;L: <span class="{pnl_class}">{fmt_usd(gross_pnl)}</span></p>
</section>
<section>
<h2>Trade History (latest 100)</h2>
<table>
<thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Date</th></tr></thead>
<tbody>{trade_rows}</tbody>
</table>
</section>
</body>
</html>"""


@router.get("/performance")
async def generate_performance_report(format: str = "html"):
    """Generate a self-contained HTML performance report."""
    if not _db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        from datetime import datetime, timezone

        from fastapi.responses import HTMLResponse, Response

        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(_db_manager)
        summary = calc.calculate_summary()
        compare = calc.compare_to_backtest()

        trades = _db_manager.get_trade_history(limit=200)
        daily_pnl = _db_manager.get_daily_pnl(days=90)

        now = datetime.now(timezone.utc)

        html = _build_performance_report_html(
            summary=summary,
            compare=compare,
            trades=trades,
            daily_pnl=daily_pnl,
            generated_at=now.isoformat(),
        )

        if format == "html":
            return HTMLResponse(content=html)
        return Response(
            content=html,
            media_type="text/html",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="jarvis-performance-{now.strftime("%Y%m%d")}.html"'
                )
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/regime-conditional")
async def get_regime_conditional(
    days: int = Query(90, ge=7, le=365, description="Look-back window in calendar days"),
    db_path: str = Depends(get_db_path),
) -> dict[str, Any]:
    """Return per-regime (RISK_ON / RISK_OFF / NORMAL) quantstats metrics.

    Slices the same daily-returns series used by /reports/quantstats and
    pairs each day with a synthetic macro regime label derived from the
    ``pnl_snapshots.vix_value`` column (if present) or a FRED-based
    score stored in a ``macro_regime_log`` table.

    Wiring note
    -----------
    No engine-side process currently writes a per-day RISK_ON/RISK_OFF/NORMAL
    label to the database.  ``fundamental_analyst.py`` computes macro_regime
    on demand (not persisted), and ``fred_data.py`` returns a spot label
    without a time series.  Therefore the endpoint accepts an optional
    ``regime_labels`` query parameter (JSON-encoded list of
    ``{"date": "YYYY-MM-DD", "regime": "RISK_ON"|"RISK_OFF"|"NORMAL"}``
    objects) to allow callers to supply labels externally.

    When no labels are supplied, the endpoint returns the full per-regime
    skeleton populated with ``"note": "no data"`` for each regime and a
    ``wiring_gap`` explanation so dashboards can surface the gap rather
    than silently returning empty results.
    """
    from reports.quantstats_metrics import _load_pnl_series

    try:
        from analytics.regime_analysis import regime_conditional_analysis
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"regime_analysis module missing: {exc}") from exc

    # ------------------------------------------------------------------
    # Load the returns series (same source as /reports/quantstats)
    # ------------------------------------------------------------------
    try:
        series, source, n_trades, start, end = _load_pnl_series(db_path, None, days)
    except Exception as exc:
        logger.error("[REPORTS] regime-conditional: failed to load pnl series: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load returns: {exc}") from exc

    # ------------------------------------------------------------------
    # Attempt to load regime labels from macro_regime_log table
    # ------------------------------------------------------------------
    import sqlite3

    import pandas as pd

    regime_labels: pd.Series | None = None

    try:
        with sqlite3.connect(db_path) as conn:
            has_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='macro_regime_log'"
            ).fetchone()
            if has_table:
                rows = conn.execute(
                    "SELECT date, regime FROM macro_regime_log ORDER BY date ASC"
                ).fetchall()
                if rows:
                    df_r = pd.DataFrame(rows, columns=["date", "regime"])
                    df_r["date"] = pd.to_datetime(df_r["date"])
                    regime_labels = df_r.set_index("date")["regime"]
                    logger.info(
                        "[REPORTS] regime-conditional: loaded %d regime rows from macro_regime_log",
                        len(regime_labels),
                    )
    except Exception as exc:
        logger.warning("[REPORTS] regime-conditional: regime label load skipped: %s", exc)

    # ------------------------------------------------------------------
    # Run analysis
    # ------------------------------------------------------------------
    if series.empty or regime_labels is None or regime_labels.empty:
        from analytics.regime_analysis import KNOWN_REGIMES

        no_data_regimes = {r: {"n_days": 0, "note": "no data"} for r in KNOWN_REGIMES}
        return {
            "regime_metrics": no_data_regimes,
            "source": source,
            "n_trades": n_trades,
            "start_date": start,
            "end_date": end,
            "wiring_gap": (
                "No per-day macro regime labels are available. "
                "regime_conditional_analysis is endpoint-only until a regime "
                "time-series is persisted to the 'macro_regime_log' table "
                "(schema: date TEXT, regime TEXT). "
                "fundamental_analyst.py computes macro_regime on demand but "
                "does not persist it. To wire: add an async task that calls "
                "FundamentalAnalyst.assess_macro_conditions() daily and "
                "inserts the resulting macro_regime into macro_regime_log."
            ),
        }

    metrics = regime_conditional_analysis(series, regime_labels)
    meta = metrics.pop("_meta", {})

    return {
        "regime_metrics": metrics,
        "source": source,
        "n_trades": n_trades,
        "start_date": start,
        "end_date": end,
        "meta": meta,
    }


@router.get("/edge-ledger")
async def get_edge_ledger(
    rebuild: bool = Query(False, description="Re-mine verdict files before returning rows"),
) -> dict[str, Any]:
    """Return the ranked edge ledger across all gate v2 verdicts.

    PASS rows appear first (sorted by DSR descending), followed by INSUFFICIENT_SAMPLE,
    then FAIL rows (sorted by primary_block, then nearest-to-pass pf_ci_lower first).
    Each row carries the full gate_v2_metrics subset plus alt_failures and primary_block.

    Pass ``?rebuild=true`` to re-mine the verdict JSON files and append new rows
    before returning (idempotent -- duplicate rows are never written).
    """
    try:
        import sys
        from pathlib import Path as _Path

        _engine_root = _Path(__file__).resolve().parents[1]
        if str(_engine_root) not in sys.path:
            sys.path.insert(0, str(_engine_root))

        from generation.edge_ledger import build, ranked_ledger

        if rebuild:
            n_new, n_total = build()
            logger.info("[REPORTS] edge-ledger rebuild: +%d new rows, %d total", n_new, n_total)

        rows = ranked_ledger()
        n_pass = sum(1 for r in rows if r.get("verdict") == "PASS")
        n_fail = sum(1 for r in rows if r.get("verdict") == "FAIL")
        n_other = len(rows) - n_pass - n_fail

        return {
            "total": len(rows),
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_other": n_other,
            "rows": rows,
        }
    except Exception as exc:
        logger.error("[REPORTS] edge-ledger error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
