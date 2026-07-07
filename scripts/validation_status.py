#!/usr/bin/env python3
"""Paper Trading Validation Status — 30-Day Progress Tracker
Usage: python scripts/validation_status.py [--host HOST] [--port PORT]
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("Error: requests not installed. Install with: pip install requests")
    sys.exit(1)

GREEN, RED, YELLOW, RESET, BOLD = "\033[92m", "\033[91m", "\033[93m", "\033[0m", "\033[1m"
THRESHOLDS = {
    "profit_factor": 2.0, "sharpe_ratio": 1.5, "win_rate_pct": 55.0,
    "min_trades": 60, "min_days": 30, "max_drawdown_pct": 15.0,
}
TARGET_DAYS = 30


def progress_bar(current: int, target: int, width: int = 20) -> str:
    """Unicode progress bar."""
    pct = min(100, max(0, int(current * 100 / target)))
    filled = int(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


def check_gate(name: str, thresh: float, current: float, is_max: bool = False) -> tuple[str, bool]:
    """Format gate line and return (line, passed)."""
    passed = current <= thresh if is_max else current >= thresh
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    suffix = "%" if "Rate" in name or "Drawdown" in name else ""
    fmt = f"{name:20} ≥ {thresh:.1f}{suffix:3s}   Current: {current:.1f}{suffix:3s}   {status}"
    return fmt, passed


def main():
    parser = argparse.ArgumentParser(description="Paper validation progress tracker")
    parser.add_argument("--host", default="localhost", help="Engine host")
    parser.add_argument("--port", type=int, default=8010, help="Engine port")
    parser.add_argument("--instrument", default="MCL", help="Instrument to track")
    args = parser.parse_args()

    # Fetch data
    try:
        p = requests.get(f"http://{args.host}:{args.port}/paper/validation/progress?instrument={args.instrument}", timeout=5).json()
        progress = p.get("data", {})
        port = requests.get(f"http://{args.host}:{args.port}/portfolio/stats/paper-phase-summary", timeout=5).json()
    except Exception as e:
        print(f"{RED}Error: {e}{RESET}", file=sys.stderr)
        sys.exit(1)

    # Extract metrics
    total_trades = progress.get("total_trades", 0)
    days_active = progress.get("days_active", 0)
    profit_factor = progress.get("profit_factor", 0.0)
    sharpe_ratio = progress.get("sharpe_ratio", 0.0)
    win_rate_pct = progress.get("win_rate_pct", 0.0)
    max_drawdown_pct = progress.get("max_drawdown_pct", 0.0)
    balance = port.get("current_balance", 0.0)
    total_pnl = port.get("total_pnl", 0.0)
    start_date = port.get("start_date", "")

    # Calculations
    days_remaining = max(0, TARGET_DAYS - days_active)
    trades_needed = max(0, THRESHOLDS["min_trades"] - total_trades)
    daily_pnl = total_pnl / max(1, port.get("trading_days", 1))
    pct = int(days_active * 100 / TARGET_DAYS)

    # Gate checks
    gates = [
        check_gate("Profit Factor", THRESHOLDS["profit_factor"], profit_factor),
        check_gate("Sharpe Ratio", THRESHOLDS["sharpe_ratio"], sharpe_ratio),
        check_gate("Win Rate", THRESHOLDS["win_rate_pct"], win_rate_pct),
        (f"Trade Count      ≥ {int(THRESHOLDS['min_trades']):2d}      Current: {total_trades:2d}      " + (f"{GREEN}PASS{RESET}" if total_trades >= THRESHOLDS["min_trades"] else f"{RED}FAIL{RESET} (need {trades_needed} more)"), total_trades >= THRESHOLDS["min_trades"]),
        check_gate("Max Drawdown", THRESHOLDS["max_drawdown_pct"], max_drawdown_pct, is_max=True),
        (f"Trading Days     ≥ {int(THRESHOLDS['min_days']):2d}      Current: {days_active:2d}      " + (f"{GREEN}PASS{RESET}" if days_active >= THRESHOLDS["min_days"] else f"{RED}FAIL{RESET} (need {days_remaining} more)"), days_active >= THRESHOLDS["min_days"]),
    ]
    gates_passing = sum(1 for _, passed in gates if passed)

    # Output
    print(f"\n{BOLD}═══════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}JARVIS TRADER — 30-Day Paper Validation Status{RESET}")
    print(f"{BOLD}═══════════════════════════════════════════════════════{RESET}\n")
    print(f"Day {days_active} of {TARGET_DAYS}  {progress_bar(days_active, TARGET_DAYS)}  {pct:3d}%  ({days_remaining} days remaining)\n")
    print(f"{BOLD}VALIDATION GATES{RESET}")
    print(f"{BOLD}─────────────────────────────────────────────────────{RESET}")
    for line, _ in gates:
        print(line)
    print(f"\n{BOLD}PORTFOLIO{RESET}")
    print(f"{BOLD}─────────────────────────────────────────────────────{RESET}")
    print(f"Balance: ${balance:,.2f}    Daily P&L: {GREEN if daily_pnl >= 0 else RED}{daily_pnl:+.2f}{RESET}    Total P&L: {GREEN if total_pnl >= 0 else RED}{total_pnl:+,.2f}{RESET}")
    if start_date:
        print(f"Started: {start_date}")
    print(f"\n{BOLD}SUMMARY{RESET}")
    print(f"{gates_passing}/6 gates passing — " + (f"{GREEN}ALL GATES PASSED{RESET}" if gates_passing == 6 else f"{YELLOW}In Progress{RESET}"))
    print()


if __name__ == "__main__":
    main()
