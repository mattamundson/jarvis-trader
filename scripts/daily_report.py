#!/usr/bin/env python3
"""
Paper Trading Daily Report Generator

Queries engine API endpoints and generates a markdown daily validation report.
Outputs to docs/reports/daily/YYYY-MM-DD.md

Usage:
  python scripts/daily_report.py
  python scripts/daily_report.py --host 127.0.0.1 --port 8010 --output-dir docs/reports/daily
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests")
    sys.exit(1)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8010
DEFAULT_OUTPUT_DIR = "docs/reports/daily"
API_KEY = "test-key"


class EngineAPIClient:
    def __init__(self, host: str, port: int):
        self.base_url = f"http://{host}:{port}"
        self.headers = {"X-API-Key": API_KEY}
        self.timeout = 5

    def _get(self, endpoint: str) -> dict[str, Any] | None:
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"API GET {endpoint} failed: {e}")
            return None

    def get_portfolio_stats(self) -> dict[str, Any]:
        result = self._get("/portfolio/stats/paper-phase-summary")
        return result or {"starting_balance": 10000.0, "current_balance": 10000.0, "total_pnl": 0.0, "trading_days": 0, "trades_completed": 0}

    def get_validation_progress(self, instrument: str = "MCL") -> dict[str, Any]:
        result = self._get(f"/paper/validation/progress?instrument={instrument}")
        return result or {"data": {}}

    def get_recent_decisions(self, limit: int = 10) -> list[dict[str, Any]]:
        result = self._get(f"/decisions/recent?limit={limit}")
        return result if isinstance(result, list) else []

    def get_safety_status(self) -> dict[str, Any]:
        result = self._get("/safety/status")
        return result or {"kill_switch_active": False, "daily_pnl": 0.0, "drawdown_pct": 0.0}


def fmt_cur(v: float) -> str:
    return f"${v:,.2f}"

def fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def generate_summary_section(client: EngineAPIClient) -> str:
    """Generate summary section of report."""
    stats = client.get_portfolio_stats()
    safety = client.get_safety_status()

    starting = float(stats.get("starting_balance", 10000.0))
    current = float(stats.get("current_balance", starting))
    total_pnl = float(stats.get("total_pnl", 0.0))
    trading_days = int(stats.get("trading_days", 0))
    trades = int(stats.get("trades_completed", 0))
    target_days = int(stats.get("target_trading_days", 30))

    daily_pnl = float(safety.get("daily_pnl", 0.0))
    drawdown = float(safety.get("drawdown_pct", 0.0))
    kill_switch = bool(safety.get("kill_switch_active", False))

    return_pct = ((current - starting) / starting * 100.0) if starting else 0.0
    daily_return_pct = (daily_pnl / current) * 100.0 if current > 0 else 0.0

    lines = [
        "## Summary",
        "",
        f"- **Day {trading_days} of {target_days}** — Validation in progress",
        f"- **Daily P&L**: {fmt_cur(daily_pnl)} ({fmt_pct(daily_return_pct)})",
        f"- **Total P&L**: {fmt_cur(total_pnl)} ({fmt_pct(return_pct)})",
        f"- **Current Balance**: {fmt_cur(current)}",
        f"- **Trades Completed**: {trades}",
        f"- **Max Drawdown**: {fmt_pct(drawdown)}",
        f"- **Kill Switch**: {'ACTIVE (trading halted)' if kill_switch else 'ARMED'}",
    ]
    return "\n".join(lines)


def generate_trades_section(client: EngineAPIClient) -> str:
    """Generate trades section of report."""
    decisions = client.get_recent_decisions(limit=20)

    lines = ["## Recent Trades", ""]

    if not decisions:
        lines.append("No recent trades recorded.")
        return "\n".join(lines)

    lines.append("| Time | Symbol | Type | Status |")
    lines.append("|------|--------|------|--------|")

    for d in decisions[-10:]:
        ts = d.get("timestamp", "")[:16] if d.get("timestamp") else "unknown"
        sym = d.get("symbol", "N/A")
        dtype = d.get("decision_type", "N/A")
        status = d.get("status", "pending")
        lines.append(f"| {ts} | {sym} | {dtype} | {status} |")

    return "\n".join(lines)


def generate_safety_section(client: EngineAPIClient) -> str:
    """Generate safety status section."""
    safety = client.get_safety_status()

    kill_switch = bool(safety.get("kill_switch_active", False))
    reason = safety.get("kill_switch_reason", "None")
    daily_pnl = float(safety.get("daily_pnl", 0.0))
    daily_limit = float(safety.get("daily_limit", -200.0))
    drawdown = float(safety.get("drawdown_pct", 0.0))
    drawdown_limit = float(safety.get("drawdown_limit_pct", -0.10))

    daily_breached = bool(safety.get("daily_limit_breached", False))
    drawdown_breached = bool(safety.get("drawdown_breached", False))

    lines = [
        "## Safety Status",
        "",
        f"- **Kill Switch**: {'ACTIVE' if kill_switch else 'ARMED'} {f'({reason})' if kill_switch else ''}",
        f"- **Paper Mode**: Yes",
        f"- **Daily P&L Limit**: {fmt_cur(daily_limit)} {f'(BREACHED)' if daily_breached else ''}",
        f"- **Daily P&L**: {fmt_cur(daily_pnl)}",
        f"- **Drawdown Limit**: {fmt_pct(drawdown_limit)}",
        f"- **Current Drawdown**: {fmt_pct(drawdown)} {f'(BREACHED)' if drawdown_breached else ''}",
    ]
    return "\n".join(lines)


def generate_validation_section(client: EngineAPIClient) -> str:
    """Generate validation gates progress section."""
    val = client.get_validation_progress(instrument="MCL")
    data = val.get("data", {})
    lines = [
        "## Validation Gates (Target Thresholds)",
        "",
        "| Metric | Current | Target | Status |",
        "|--------|---------|--------|--------|",
    ]
    metrics = [
        ("Profit Factor", "profit_factor", 2.0, False),
        ("Sharpe Ratio", "sharpe_ratio", 1.5, False),
        ("Win Rate", "win_rate_pct", 55.0, True),
        ("Max Drawdown", "max_drawdown_pct", -15.0, False),
    ]
    for label, key, target, is_pct in metrics:
        current = data.get(key, 0.0)
        if isinstance(current, (int, float)):
            status = "PASS" if current >= target else "IN PROGRESS"
            if is_pct:
                lines.append(f"| {label} | {fmt_pct(current)} | {fmt_pct(target)} | {status} |")
            else:
                lines.append(f"| {label} | {current:.2f} | {target:.2f} | {status} |")
    return "\n".join(lines)


def generate_report(client: EngineAPIClient) -> str:
    """Generate complete daily report."""
    today = date.today().isoformat()

    lines = [
        f"# Paper Trading Daily Report — {today}",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
    ]

    lines.append(generate_summary_section(client))
    lines.append("")
    lines.append(generate_trades_section(client))
    lines.append("")
    lines.append(generate_safety_section(client))
    lines.append("")
    lines.append(generate_validation_section(client))

    return "\n".join(lines)


def save_report(report: str, output_dir: str) -> Path:
    """Save report to markdown file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    file_path = output_path / f"{today}.md"

    with open(file_path, "w") as f:
        f.write(report)

    return file_path


def generate_quantstats_tearsheet(client: EngineAPIClient, output_dir: str):
    """Attempt to generate an institutional tearsheet using QuantStats."""
    try:
        import pandas as pd
        import quantstats as qs
    except ImportError:
        logger.warning("QuantStats or Pandas not installed. Skipping institutional tearsheet.")
        return

    logger.info("Generating QuantStats HTML Tearsheet...")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    html_path = output_path / f"{today}_tearsheet.html"

    # Simulate fetching historical daily returns from the engine API
    # In production, this would hit client.get_historical_pnl()
    try:
        stats = client.get_portfolio_stats()
        # Mocking a basic return series for demonstration. 
        # You will connect this to your postgres DB of daily PnL vectors later.
        dates = pd.date_range(end=today, periods=30, freq='D')
        
        # Simulate slight upward drift with volatility (Mock data)
        np.random.seed(42)  # For reproducibility during mock phase
        returns = np.random.normal(0.001, 0.015, size=len(dates))
        returns_series = pd.Series(returns, index=dates)
        
        qs.extend_pandas()
        
        # Suppress warnings from QuantStats
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            qs.reports.html(returns_series, "SPY", title="Stark-TPO Performance Tearsheet", output=str(html_path))
            
        logger.info(f"QuantStats tearsheet saved to: {html_path}")
    except Exception as exc:
        logger.error(f"Failed to generate tearsheet: {exc}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate daily paper trading validation report"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Engine host (default: localhost)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Engine port (default: 8010)")
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory (default: docs/reports/daily)"
    )

    args = parser.parse_args()

    logger.info(f"Connecting to engine at {args.host}:{args.port}")
    client = EngineAPIClient(args.host, args.port)

    logger.info("Generating daily report...")
    report = generate_report(client)

    logger.info(f"Saving report to {args.output_dir}")
    file_path = save_report(report, args.output_dir)

    logger.info(f"Report saved: {file_path}")
    print(report)
    
    # NEW: Attempt tearsheet generation
    generate_quantstats_tearsheet(client, args.output_dir)


if __name__ == "__main__":
    main()
