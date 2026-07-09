#!/usr/bin/env python3
"""
JARVIS TRADER — Daily Performance Report
Run at end of day to get a snapshot of paper trading performance.
Usage: python scripts/daily_report.py [--date YYYY-MM-DD]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import URLError

ENGINE_URL = "http://localhost:8010"

def fetch(path: str) -> dict:
    """Fetch JSON from engine endpoint."""
    try:
        with urlopen(f"{ENGINE_URL}{path}", timeout=5) as r:
            return json.loads(r.read())
    except URLError as e:
        print(f"  [ERROR] Could not reach engine: {e}")
        return {}
    except Exception as e:
        print(f"  [ERROR] {e}")
        return {}

def fmt_pnl(v: float) -> str:
    """Format P&L with sign and color-hint prefix."""
    if v > 0:
        return f"+${v:,.2f}"
    elif v < 0:
        return f"-${abs(v):,.2f}"
    return "$0.00"

def pct(v: float) -> str:
    return f"{v:.1f}%"

def hr(char="-", width=60) -> str:
    return char * width

def main():
    parser = argparse.ArgumentParser(description="JARVIS TRADER Daily Report")
    parser.add_argument("--date", help="Report date (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()

    today = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print()
    print(hr("="))
    print("  JARVIS TRADER — Paper Trading Report")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(hr("="))

    # --- Session today ---
    print()
    print("  TODAY'S SESSION")
    print(hr())
    session = fetch("/portfolio/stats/session-today")
    if session:
        print(f"  Date:          {session.get('date', today)}")
        print(f"  Market Session:{session.get('session', 'N/A'):>10}")
        print(f"  Trades Today:  {session.get('trades_today', 0):>10}")
        print(f"  P&L Today:     {fmt_pnl(session.get('pnl_today', 0)):>10}")
        print(f"  Win Rate:      {pct(session.get('win_rate_today', 0)):>10}")
        print(f"  Open Positions:{session.get('open_positions', 0):>10}")

    # --- 7-day rolling ---
    print()
    print("  7-DAY ROLLING PERFORMANCE")
    print(hr())
    weekly = fetch("/portfolio/stats/weekly")
    if weekly:
        print(f"  Trades:        {weekly.get('total_trades', 0):>10}")
        print(f"  Win Rate:      {pct(weekly.get('win_rate', 0)):>10}")
        print(f"  Total P&L:     {fmt_pnl(weekly.get('total_pnl', 0)):>10}")
        print(f"  Avg P&L:       {fmt_pnl(weekly.get('avg_pnl', 0)):>10}")
        print(f"  Best Trade:    {fmt_pnl(weekly.get('best_trade', 0)):>10}")
        print(f"  Worst Trade:   {fmt_pnl(weekly.get('worst_trade', 0)):>10}")
        print(f"  Trading Days:  {weekly.get('trading_days', 0):>10}")

    # --- Overall performance ---
    print()
    print("  OVERALL PERFORMANCE")
    print(hr())
    perf = fetch("/analytics/performance")
    if perf:
        pf = perf.get('profit_factor', 0)
        sharpe = perf.get('sharpe_ratio', 0)
        wr = perf.get('win_rate', 0)
        trades = perf.get('total_trades', 0)
        pf_ok = "PASS" if pf >= 2.0 else "FAIL"
        sr_ok = "PASS" if sharpe >= 1.5 else "FAIL"
        wr_ok = "PASS" if wr >= 55.0 else "FAIL"
        tr_ok = "PASS" if trades >= 30 else f"NEED {max(0, 30-trades)} more"
        print(f"  Profit Factor: {pf:>8.2f}  [{pf_ok}] (target: >=2.0)")
        print(f"  Sharpe Ratio:  {sharpe:>8.2f}  [{sr_ok}] (target: >=1.5)")
        print(f"  Win Rate:      {pct(wr):>8}  [{wr_ok}] (target: >=55%)")
        print(f"  Total Trades:  {trades:>8}  [{tr_ok}] (target: >=30)")
        print(f"  Total P&L:     {fmt_pnl(perf.get('total_pnl', 0)):>10}")
        print(f"  Max Drawdown:  {fmt_pnl(perf.get('max_drawdown', 0)):>10}")

    # --- Risk status ---
    print()
    print("  RISK STATUS")
    print(hr())
    cb = fetch("/safety/circuit-breakers")
    if cb:
        ks = cb.get('kill_switch_active', False)
        daily_b = cb.get('daily_limit_breached', False)
        dd_b = cb.get('drawdown_breached', False)
        print(f"  Kill Switch:   {'ACTIVE !!!' if ks else 'OFF':>10}")
        print(f"  Daily Limit:   {'BREACHED' if daily_b else 'OK':>10}  (remaining: {fmt_pnl(cb.get('daily_remaining', 0))})")
        print(f"  Max Drawdown:  {'BREACHED' if dd_b else 'OK':>10}  (used: {pct(cb.get('current_drawdown_pct', 0)*100)})")

    # --- Paper phase summary ---
    print()
    print("  PAPER PHASE PROGRESS")
    print(hr())
    summary = fetch("/portfolio/stats/paper-phase-summary")
    if summary:
        balance = summary.get('current_balance', summary.get('balance', 0))
        ret = summary.get('total_return_pct', summary.get('return_pct', 0))
        days = summary.get('trading_days', 0)
        print(f"  Current Balance: {fmt_pnl(balance):>10}")
        print(f"  Total Return:  {pct(ret):>10}")
        print(f"  Trading Days:  {days:>10} / 30")
        days_pct = min(100, days / 30 * 100)
        bar = "#" * int(days_pct / 5) + "." * (20 - int(days_pct / 5))
        print(f"  Progress: [{bar}] {days_pct:.0f}%")

    # --- Readiness check ---
    print()
    print("  READINESS CHECK")
    print(hr())
    readiness = fetch("/validation/readiness-check")
    checks = readiness.get('checks', [])
    if checks:
        passed = sum(1 for c in checks if c.get('status') == 'pass')
        total_c = len(checks)
        for c in checks:
            status = "+" if c.get('status') == 'pass' else "x"
            print(f"  {status} {c.get('name', 'Unknown')}: {c.get('message', '')}")
        print(f"  Score: {passed}/{total_c}")

    print()
    print(hr("="))
    print(f"  End of Report — {today}")
    print(hr("="))
    print()

if __name__ == "__main__":
    main()
