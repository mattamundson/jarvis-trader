#!/usr/bin/env python3
"""
Paper Trading End-of-Day Summary Generator

Queries engine API for evening review: scorecard, trades, risk, gates, next day outlook.
Saves to docs/reports/eod/YYYY-MM-DD.md

Usage:
  python scripts/eod_summary.py
  python scripts/eod_summary.py --host localhost --port 8010 --output-dir docs/reports/eod
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
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
DEFAULT_OUTPUT_DIR = "docs/reports/eod"
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
        return result or {"starting_balance": 10000.0, "current_balance": 10000.0, "total_pnl": 0.0, "trades_completed": 0}

    def get_portfolio_performance(self) -> dict[str, Any]:
        result = self._get("/portfolio/paper/performance")
        return result or {"daily_pnl": 0.0, "win_rate": 0.0, "total_trades": 0}

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

def load_previous_report(output_dir: str) -> dict[str, Any] | None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    prev_file = Path(output_dir) / f"{yesterday}.md"
    if not prev_file.exists():
        return None
    try:
        with open(prev_file) as f:
            return {"exists": True, "content": f.read()}
    except Exception as e:
        logger.warning(f"Failed to load previous report: {e}")
        return None


def generate_summary(client: EngineAPIClient) -> str:
    """Generate complete EOD summary."""
    today = date.today().isoformat()
    stats = client.get_portfolio_stats()
    perf = client.get_portfolio_performance()
    safety = client.get_safety_status()
    val = client.get_validation_progress(instrument="MCL")
    decisions = client.get_recent_decisions(limit=10)

    data = val.get("data", {})
    daily_pnl = float(perf.get("daily_pnl", 0.0))
    win_rate = float(perf.get("win_rate", 0.0))
    trades = int(perf.get("total_trades", 0))
    current_balance = float(stats.get("current_balance", 10000.0))
    daily_return_pct = (daily_pnl / current_balance * 100.0) if current_balance > 0 else 0.0
    kill_switch = bool(safety.get("kill_switch_active", False))
    drawdown = float(safety.get("drawdown_pct", 0.0))
    trading_days = int(stats.get("trading_days", 0))
    target_days = int(stats.get("target_trading_days", 30))

    lines = [
        f"# EOD Summary — {today}",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
        "## Today's Scorecard",
        "",
        f"**Daily P&L:** {fmt_cur(daily_pnl)} ({fmt_pct(daily_return_pct)}) | **Win Rate:** {fmt_pct(win_rate)} | **Trades:** {trades}",
        "",
        "## Trade Log",
        "",
    ]

    if decisions:
        lines.extend(["| Time | Symbol | Type | P&L |", "|------|--------|------|-----|"])
        for d in decisions[-5:]:
            ts = d.get("timestamp", "")[:16] if d.get("timestamp") else "unknown"
            sym = d.get("symbol", "N/A")
            dtype = d.get("decision_type", "TRADE")
            pnl = d.get("pnl", 0.0)
            pnl_str = fmt_cur(float(pnl)) if isinstance(pnl, (int, float)) else "—"
            lines.append(f"| {ts} | {sym} | {dtype} | {pnl_str} |")
    else:
        lines.append("No trades today.")

    lines.extend([
        "",
        "## Risk Dashboard",
        "",
        f"**Kill Switch:** {'ACTIVE' if kill_switch else 'ARMED'} | **Drawdown:** {fmt_pct(drawdown)}/10.00%",
        "",
        f"## Validation Gates (Day {trading_days}/{target_days})",
        "",
        "| Gate | Current | Target | Status |",
        "|------|---------|--------|--------|",
    ])

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

    open_positions = len([d for d in decisions if d.get("status") == "open"])
    lines.extend([
        "",
        "## Tomorrow's Watch",
        "",
        f"- **Open Positions:** {open_positions}",
        "- **Market Hours:** 8:30am–3:00pm CT",
        "- **Next Focus:** Monitor gates, track P&L",
        "",
    ])

    return "\n".join(lines)


def save_summary(summary: str, output_dir: str) -> Path:
    """Save summary to markdown file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    file_path = output_path / f"{today}.md"
    with open(file_path, "w") as f:
        f.write(summary)
    return file_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate end-of-day summary for evening review"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Engine host (default: localhost)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Engine port (default: 8010)")
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory (default: docs/reports/eod)"
    )

    args = parser.parse_args()
    logger.info(f"Connecting to engine at {args.host}:{args.port}")
    client = EngineAPIClient(args.host, args.port)

    logger.info("Generating EOD summary...")
    summary = generate_summary(client)

    logger.info(f"Saving summary to {args.output_dir}")
    file_path = save_summary(summary, args.output_dir)

    logger.info(f"Summary saved: {file_path}")
    print(summary)


if __name__ == "__main__":
    main()
