#!/usr/bin/env python3
"""
Paper Trading End-of-Day Summary Generator — JARVIS TRADER v2 (QuantStats Edition)
====================================================================================
Queries engine API for evening review: scorecard, trades, risk, gates, next-day
outlook. Also generates a full QuantStats HTML tearsheet saved alongside the
markdown report.

Outputs:
  docs/reports/eod/YYYY-MM-DD.md          — markdown summary (existing)
  docs/reports/eod/html/YYYY-MM-DD.html   — QuantStats HTML tearsheet (NEW)

Usage:
  python scripts/eod_summary.py
  python scripts/eod_summary.py --host localhost --port 8010
  python scripts/eod_summary.py --no-tearsheet   # skip HTML if QS unavailable
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)

try:
    import quantstats as qs
    qs.extend_pandas()
    QS_AVAILABLE = True
except ImportError:
    QS_AVAILABLE = False

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_HOST       = "localhost"
DEFAULT_PORT       = 8010
DEFAULT_OUTPUT_DIR = "docs/reports/eod"
API_KEY            = "test-key"


# ── Engine API client (unchanged interface) ───────────────────────────────

class EngineAPIClient:
    def __init__(self, host: str, port: int):
        self.base_url = f"http://{host}:{port}"
        self.headers  = {"X-API-Key": API_KEY}
        self.timeout  = 5

    def _get(self, endpoint: str) -> dict[str, Any] | None:
        try:
            resp = requests.get(
                f"{self.base_url}{endpoint}", headers=self.headers, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API GET {endpoint} failed: {e}")
            return None

    def get_portfolio_stats(self) -> dict[str, Any]:
        return self._get("/portfolio/stats/paper-phase-summary") or {
            "starting_balance": 10_000.0,
            "current_balance":  10_000.0,
            "total_pnl":        0.0,
            "trades_completed": 0,
        }

    def get_portfolio_performance(self) -> dict[str, Any]:
        return self._get("/portfolio/paper/performance") or {
            "daily_pnl":    0.0,
            "win_rate":     0.0,
            "total_trades": 0,
        }

    def get_validation_progress(self, instrument: str = "MCL") -> dict[str, Any]:
        return self._get(f"/paper/validation/progress?instrument={instrument}") or {"data": {}}

    def get_recent_decisions(self, limit: int = 10) -> list[dict[str, Any]]:
        result = self._get(f"/decisions/recent?limit={limit}")
        return result if isinstance(result, list) else []

    def get_safety_status(self) -> dict[str, Any]:
        return self._get("/safety/status") or {
            "kill_switch_active": False,
            "daily_pnl":         0.0,
            "drawdown_pct":      0.0,
        }

    def get_daily_trade_returns(self) -> list[dict]:
        """
        Fetch daily P&L trade log for return-series construction.
        Endpoint: /paper/trades/log  →  [{exit_date, pnl}, …]
        Falls back to decisions endpoint if unavailable.
        """
        result = self._get("/paper/trades/log")
        if result and isinstance(result, list):
            return result
        # Fallback: use recent decisions
        decisions = self.get_recent_decisions(limit=200)
        return [
            {"exit_date": d.get("timestamp", ""), "pnl": d.get("pnl", 0.0)}
            for d in decisions
            if d.get("pnl") is not None
        ]


# ── Return-series builder ─────────────────────────────────────────────────

def build_returns_from_engine(client: EngineAPIClient, starting_capital: float = 10_000.0) -> pd.Series | None:
    """
    Build a daily return Series from the engine's trade log.
    Returns None if insufficient data (< 5 data points).
    """
    trades = client.get_daily_trade_returns()
    if not trades:
        logger.warning("No trade data available for return-series construction.")
        return None

    rows = []
    for t in trades:
        pnl = t.get("pnl") or t.get("profit") or t.get("net_pnl")
        ts  = t.get("exit_date") or t.get("date") or t.get("timestamp")
        if pnl is not None and ts:
            try:
                rows.append({"date": pd.to_datetime(ts), "pnl": float(pnl)})
            except Exception:
                continue

    if len(rows) < 5:
        logger.warning(f"Only {len(rows)} trades — need ≥ 5 for meaningful tearsheet.")
        return None

    df     = pd.DataFrame(rows).sort_values("date").set_index("date")
    equity = starting_capital + df["pnl"].cumsum()
    returns = equity.pct_change().dropna()
    returns.index = returns.index.tz_localize(None)
    return returns


# ── HTML tearsheet generator ──────────────────────────────────────────────

def generate_eod_tearsheet(
    returns:    pd.Series,
    output_dir: str,
    benchmark:  str = "SPY",
    title:      str | None = None,
) -> Path | None:
    """
    Generate a QuantStats HTML tearsheet and save to:
        {output_dir}/html/YYYY-MM-DD.html

    Returns the saved Path, or None if generation failed.
    """
    if not QS_AVAILABLE:
        logger.warning("quantstats not installed — skipping HTML tearsheet. Run: pip install quantstats")
        return None

    today    = date.today().isoformat()
    html_dir = Path(output_dir) / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / f"{today}.html"

    report_title = title or f"JARVIS TRADER — EOD Tearsheet {today}"

    try:
        qs.reports.html(
            returns,
            benchmark=benchmark,
            output=str(html_path),
            title=report_title,
            download_filename=str(html_path),
            grayscale=False,
        )
        logger.info(f"HTML tearsheet saved: {html_path}")
        return html_path
    except Exception as e:
        logger.error(f"QuantStats HTML generation failed: {e}")
        return None


# ── Markdown summary (extended with QS metrics banner) ───────────────────

def _fmt_cur(v: float) -> str:
    return f"${v:,.2f}"

def _fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def generate_summary(
    client:      EngineAPIClient,
    returns:     pd.Series | None = None,
    html_path:   Path | None = None,
) -> str:
    today    = date.today().isoformat()
    stats    = client.get_portfolio_stats()
    perf     = client.get_portfolio_performance()
    safety   = client.get_safety_status()
    val      = client.get_validation_progress(instrument="MCL")
    decisions = client.get_recent_decisions(limit=10)

    data            = val.get("data", {})
    daily_pnl       = float(perf.get("daily_pnl", 0.0))
    win_rate        = float(perf.get("win_rate", 0.0))
    trades          = int(perf.get("total_trades", 0))
    current_balance = float(stats.get("current_balance", 10_000.0))
    daily_return_pct = (daily_pnl / current_balance * 100.0) if current_balance > 0 else 0.0
    kill_switch     = bool(safety.get("kill_switch_active", False))
    drawdown        = float(safety.get("drawdown_pct", 0.0))
    trading_days    = int(stats.get("trading_days", 0))
    target_days     = int(stats.get("target_trading_days", 30))

    lines = [
        f"# EOD Summary — {today}",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
    ]

    # ── QuantStats banner (new) ────────────────────────────────────────────
    if returns is not None and QS_AVAILABLE and len(returns) >= 5:
        try:
            qs_sharpe  = qs.stats.sharpe(returns)
            qs_sortino = qs.stats.sortino(returns)
            qs_calmar  = qs.stats.calmar(returns)
            qs_tail    = qs.stats.tail_ratio(returns)
            qs_dd      = abs(qs.stats.max_drawdown(returns))
            qs_skew    = qs.stats.skew(returns)
            qs_exp     = qs.stats.exposure(returns)

            lines += [
                "## QuantStats Metrics (computed from return series)",
                "",
                f"| Sharpe | Sortino | Calmar | Tail Ratio | MaxDD | Skew | Exposure |",
                f"|-------:|--------:|-------:|-----------:|------:|-----:|---------:|",
                f"| {qs_sharpe:.3f} | {qs_sortino:.3f} | {qs_calmar:.3f} "
                f"| {qs_tail:.3f} | {qs_dd*100:.1f}% | {qs_skew:.3f} | {qs_exp*100:.1f}% |",
                "",
            ]
            if html_path:
                lines.append(f"> 📊 Full tearsheet: `{html_path}`")
                lines.append("")
        except Exception as e:
            logger.warning(f"QS metrics banner failed: {e}")
    elif html_path is None:
        if not QS_AVAILABLE:
            lines.append("> ⚠ Install `quantstats` for enhanced metrics: `pip install quantstats`\n")

    # ── Scorecard ─────────────────────────────────────────────────────────
    lines += [
        "## Today's Scorecard",
        "",
        f"**Daily P&L:** {_fmt_cur(daily_pnl)} ({_fmt_pct(daily_return_pct)}) "
        f"| **Win Rate:** {_fmt_pct(win_rate)} | **Trades:** {trades}",
        "",
        "## Trade Log",
        "",
    ]

    if decisions:
        lines += ["| Time | Symbol | Type | P&L |", "|------|--------|------|-----|"]
        for d in decisions[-5:]:
            ts     = d.get("timestamp", "")[:16] if d.get("timestamp") else "unknown"
            sym    = d.get("symbol", "N/A")
            dtype  = d.get("decision_type", "TRADE")
            pnl    = d.get("pnl", 0.0)
            pnl_s  = _fmt_cur(float(pnl)) if isinstance(pnl, (int, float)) else "—"
            lines.append(f"| {ts} | {sym} | {dtype} | {pnl_s} |")
    else:
        lines.append("No trades today.")

    lines += [
        "",
        "## Risk Dashboard",
        "",
        f"**Kill Switch:** {'ACTIVE' if kill_switch else 'ARMED'} | **Drawdown:** {_fmt_pct(drawdown)}/10.00%",
        "",
        f"## Validation Gates (Day {trading_days}/{target_days})",
        "",
        "| Gate | Current | Target | Status |",
        "|------|---------|--------|--------|",
    ]

    gate_metrics = [
        ("Profit Factor", "profit_factor",   2.0,   False),
        ("Sharpe Ratio",  "sharpe_ratio",    1.5,   False),
        ("Win Rate",      "win_rate_pct",    55.0,  True),
        ("Max Drawdown",  "max_drawdown_pct",-15.0, False),
    ]
    for label, key, target, is_pct in gate_metrics:
        current = data.get(key, 0.0)
        if isinstance(current, (int, float)):
            status = "PASS" if current >= target else "IN PROGRESS"
            if is_pct:
                lines.append(f"| {label} | {_fmt_pct(current)} | {_fmt_pct(target)} | {status} |")
            else:
                lines.append(f"| {label} | {current:.2f} | {target:.2f} | {status} |")

    open_pos = len([d for d in decisions if d.get("status") == "open"])
    lines += [
        "",
        "## Tomorrow's Watch",
        "",
        f"- **Open Positions:** {open_pos}",
        "- **Market Hours:** 8:30am–3:00pm CT",
        "- **Next Focus:** Monitor gates, track P&L",
        "",
    ]

    return "\n".join(lines)


# ── Save helpers ──────────────────────────────────────────────────────────

def save_summary(summary: str, output_dir: str) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    file_path = output_path / f"{date.today().isoformat()}.md"
    with open(file_path, "w") as f:
        f.write(summary)
    return file_path


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="EOD summary + QuantStats HTML tearsheet — JARVIS TRADER"
    )
    parser.add_argument("--host",          default=DEFAULT_HOST)
    parser.add_argument("--port",          type=int, default=DEFAULT_PORT)
    parser.add_argument("--output-dir",    default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--benchmark",     default="SPY",  help="Benchmark ticker for tearsheet (default: SPY)")
    parser.add_argument("--no-tearsheet",  action="store_true", help="Skip HTML tearsheet generation")
    parser.add_argument("--capital",       type=float, default=10_000.0, help="Starting capital (default: 10000)")
    args = parser.parse_args()

    logger.info(f"Connecting to engine at {args.host}:{args.port}")
    client = EngineAPIClient(args.host, args.port)

    # Build return series
    returns  = None
    html_path = None

    if not args.no_tearsheet:
        logger.info("Building return series from engine trade log …")
        stats   = client.get_portfolio_stats()
        capital = float(stats.get("starting_balance", args.capital))
        returns = build_returns_from_engine(client, starting_capital=capital)

        if returns is not None:
            logger.info(f"Return series: {len(returns)} data points")
            html_path = generate_eod_tearsheet(
                returns,
                output_dir=args.output_dir,
                benchmark=args.benchmark,
            )
        else:
            logger.warning("Insufficient trade data — skipping HTML tearsheet.")

    # Generate markdown
    logger.info("Generating EOD markdown summary …")
    summary = generate_summary(client, returns=returns, html_path=html_path)

    file_path = save_summary(summary, args.output_dir)
    logger.info(f"Markdown saved: {file_path}")

    if html_path:
        logger.info(f"HTML tearsheet: {html_path}")

    print(summary)


if __name__ == "__main__":
    main()
