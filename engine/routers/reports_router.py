"""Reports and analytics router."""

import logging
from datetime import datetime, timedelta
from datetime import timezone as _tz
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)

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


# ── Migrated from main.py inline routes ──────────────────────────────────────


@router.get("/performance")
async def generate_performance_report(format: str = "html"):
    """Generate a self-contained HTML performance report."""
    if not _db_manager:
        raise HTTPException(status_code=503, detail="Database not initialized")

    try:
        from datetime import datetime, timezone

        from analytics.performance import PerformanceCalculator

        calc = PerformanceCalculator(_db_manager)
        summary = calc.calculate_summary()
        compare = calc.compare_to_backtest()

        # Get trade history
        trades = _db_manager.get_trade_history(limit=200)
        daily_pnl = _db_manager.get_daily_pnl(days=90)

        now = datetime.now(timezone.utc)

        # Build HTML report
        html = _build_performance_report_html(
            summary=summary,
            compare=compare,
            trades=trades,
            daily_pnl=daily_pnl,
            generated_at=now.isoformat(),
        )

        from fastapi.responses import HTMLResponse, Response

        if format == "html":
            return HTMLResponse(content=html)
        else:
            # Return as downloadable file
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

    # Summary metrics
    pf = summary.get("profit_factor")
    sharpe = summary.get("sharpe_ratio")
    win_rate = summary.get("win_rate")
    max_dd = summary.get("max_drawdown", 0)
    total_trades = summary.get("total_trades", 0)
    gross_pnl = summary.get("gross_pnl", 0)

    # Validation status
    pf_pass = pf and pf >= 2.0
    sharpe_pass = sharpe and sharpe >= 1.5

    pf_class = "pass" if pf_pass else ("fail" if pf else "neutral")
    pf_status_class = "pass" if pf_pass else "fail"
    pf_status_txt = "Pass (>= 2.0)" if pf_pass else ("Fail (>= 2.0)" if pf else "No data")

    sharpe_class = "pass" if sharpe_pass else ("fail" if sharpe else "neutral")
    sharpe_status_class = "pass" if sharpe_pass else "fail"
    sharpe_status_txt = (
        "Pass (>= 1.5)" if sharpe_pass else ("Fail (>= 1.5)" if sharpe else "No data")
    )

    gross_pnl_safe = gross_pnl or 0
    pnl_class = "pass" if gross_pnl_safe >= 0 else "fail"

    # Trade rows
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

    # Daily P&L data for chart
    pnl_data = [r.get("realized_pnl", 0) for r in daily_pnl[-30:]]
    pnl_json = str(pnl_data).replace("None", "0")
    dates_json = str([str(r.get("date", ""))[:10] for r in daily_pnl[-30:]])

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>JARVIS TRADER - Performance Report</title>\n"
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>\n'
        "<style>\n"
        "  * { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\n"
        "          background: #0a0a0a; color: #e5e5e5; padding: 24px; }\n"
        "  h1 { font-size: 1.5rem; margin-bottom: 4px; }\n"
        "  .subtitle { color: #6b6b6b; font-size: 0.875rem; margin-bottom: 24px; }\n"
        "  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));"
        " gap: 12px; margin-bottom: 24px; }\n"
        "  .card { background: #161616; border: 1px solid #262626; border-radius: 8px; padding: 16px; }\n"
        "  .card-label { font-size: 0.75rem; color: #6b6b6b; text-transform: uppercase; letter-spacing: 0.05em; }\n"
        "  .card-value { font-size: 1.5rem; font-weight: 600; margin-top: 4px; }\n"
        "  .card-status { font-size: 0.75rem; margin-top: 4px; }\n"
        "  .pass { color: #22c55e; }\n"
        "  .fail { color: #ef4444; }\n"
        "  .neutral { color: #6b6b6b; }\n"
        "  .section { background: #161616; border: 1px solid #262626; border-radius: 8px;"
        " padding: 20px; margin-bottom: 16px; }\n"
        "  .section h2 { font-size: 1rem; margin-bottom: 16px; color: #a3a3a3; }\n"
        "  table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }\n"
        "  th { text-align: left; padding: 8px 12px; border-bottom: 1px solid #262626;"
        " color: #6b6b6b; font-weight: 500; }\n"
        "  td { padding: 8px 12px; border-bottom: 1px solid #1a1a1a; }\n"
        "  tr:hover td { background: #1a1a1a; }\n"
        "  canvas { max-height: 200px; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>JARVIS TRADER - Performance Report</h1>\n"
        f'<p class="subtitle">Generated {generated_at[:10]} | Paper Trading Phase</p>\n'
        "\n"
        '<div class="grid">\n'
        '  <div class="card">\n'
        '    <div class="card-label">Profit Factor</div>\n'
        f'    <div class="card-value {pf_class}">{fmt_num(pf)}</div>\n'
        f'    <div class="card-status {pf_status_class}">{pf_status_txt}</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Sharpe Ratio</div>\n'
        f'    <div class="card-value {sharpe_class}">{fmt_num(sharpe)}</div>\n'
        f'    <div class="card-status {sharpe_status_class}">{sharpe_status_txt}</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Win Rate</div>\n'
        f'    <div class="card-value neutral">{fmt_pct(win_rate)}</div>\n'
        '    <div class="card-status neutral">Target &gt;= 50%</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Max Drawdown</div>\n'
        f'    <div class="card-value fail">{fmt_pct(max_dd)}</div>\n'
        '    <div class="card-status neutral">Limit &lt;= -15%</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Total Trades</div>\n'
        f'    <div class="card-value neutral">{total_trades}</div>\n'
        '    <div class="card-status neutral">Target &gt;= 30</div>\n'
        "  </div>\n"
        '  <div class="card">\n'
        '    <div class="card-label">Gross P&amp;L</div>\n'
        f'    <div class="card-value {pnl_class}">{fmt_usd(gross_pnl)}</div>\n'
        '    <div class="card-status neutral">Paper account</div>\n'
        "  </div>\n"
        "</div>\n"
        "\n"
        '<div class="section">\n'
        "  <h2>Daily P&amp;L - Last 30 Days</h2>\n"
        '  <canvas id="pnlChart"></canvas>\n'
        "</div>\n"
        "\n"
        '<div class="section">\n'
        "  <h2>Trade History (latest 100)</h2>\n"
        "  <table>\n"
        "    <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th>"
        "<th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Date</th></tr></thead>\n"
        f"    <tbody>{trade_rows}</tbody>\n"
        "  </table>\n"
        "</div>\n"
        "\n"
        "<script>\n"
        "const ctx = document.getElementById('pnlChart').getContext('2d');\n"
        f"const pnlData = {pnl_json};\n"
        f"const labels = {dates_json};\n"
        "new Chart(ctx, {\n"
        "  type: 'bar',\n"
        "  data: {\n"
        "    labels: labels,\n"
        "    datasets: [{\n"
        "      label: 'Daily P&L',\n"
        "      data: pnlData,\n"
        "      backgroundColor: pnlData.map(v => v >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'),\n"
        "      borderColor: pnlData.map(v => v >= 0 ? '#22c55e' : '#ef4444'),\n"
        "      borderWidth: 1,\n"
        "    }],\n"
        "  },\n"
        "  options: {\n"
        "    responsive: true,\n"
        "    plugins: { legend: { display: false } },\n"
        "    scales: {\n"
        "      x: { ticks: { color: '#6b6b6b', maxTicksLimit: 10 } },\n"
        "      y: { ticks: { color: '#6b6b6b' }, grid: { color: '#1a1a1a' } },\n"
        "    },\n"
        "  },\n"
        "});\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )
