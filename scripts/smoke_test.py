#!/usr/bin/env python3
"""
JARVIS TRADER — Engine Smoke Test
Hits all major GET endpoints and reports pass/fail.
Status codes 200-499 are considered PASS (some endpoints return 503 while
engine is still starting up).  Only connection errors and 5xx responses
are treated as FAIL.

Usage: python scripts/smoke_test.py [--url http://localhost:8010]
"""
import sys
import argparse
import urllib.request
import urllib.error
import json

BASE_URL = "http://localhost:8010"

ENDPOINTS = [
    # Core health
    ("GET", "/health"),
    ("GET", "/health/detailed"),

    # Portfolio
    ("GET", "/portfolio/paper/positions"),
    ("GET", "/portfolio/paper/performance"),
    ("GET", "/portfolio/history/trades"),
    ("GET", "/portfolio/history/daily-pnl"),
    ("GET", "/portfolio/stats/summary"),
    ("GET", "/portfolio/stats/drawdown"),
    ("GET", "/portfolio/stats/trading-days"),
    ("GET", "/portfolio/stats/paper-phase-summary"),
    ("GET", "/portfolio/stats/streaks"),
    ("GET", "/portfolio/stats/session-today"),
    ("GET", "/portfolio/stats/commissions"),
    ("GET", "/portfolio/stats/weekly"),
    ("GET", "/portfolio/export/trades.csv"),
    ("GET", "/portfolio/export/daily-pnl.csv"),

    # Pipeline & Signals
    ("GET", "/pipeline/history"),
    ("GET", "/signals/recent"),
    ("GET", "/signals/stats"),

    # Analytics
    ("GET", "/analytics/performance"),
    ("GET", "/analytics/performance/rolling?days=7"),
    ("GET", "/analytics/performance/rolling?days=30"),
    ("GET", "/analytics/performance/compare"),
    ("GET", "/analytics/regime"),
    ("GET", "/analytics/mtf?symbol=MES"),
    ("GET", "/analytics/trades/by-day"),
    ("GET", "/analytics/trades/by-symbol"),
    ("GET", "/analytics/trades/by-hour"),

    # Market
    ("GET", "/market/session"),
    ("GET", "/market/earnings"),

    # Watchlist
    ("GET", "/watchlist/scan"),

    # Safety
    ("GET", "/safety/circuit-breakers"),

    # IB Gateway
    ("GET", "/ib/connection-test"),
    ("GET", "/ib/reconcile"),

    # Position sizing
    ("GET", "/position-sizing/calculate?account_value=10000&atr=5.0"),

    # Validation
    ("GET", "/validation/readiness-check"),

    # System
    ("GET", "/system/preflight"),

    # Settings
    ("GET", "/settings/risk"),

    # Journal
    ("GET", "/journal/trades"),
    ("GET", "/journal/notes"),

    # Alerts
    ("GET", "/alerts/history"),
    ("GET", "/alerts/stats"),

    # Webhook
    ("GET", "/webhook/dedup-stats"),

    # Notifications
    ("POST", "/notifications/whatsapp/test"),
]


def check(method: str, path: str, base_url: str) -> tuple[bool, int, str]:
    """
    Make a request to base_url+path.
    Returns (passed, status_code, note).
    Passes if status < 500.  Connection errors are FAIL with status 0.
    POST endpoints send an empty JSON body {}.
    """
    url = f"{base_url}{path}"
    try:
        if method == "POST":
            data = json.dumps({}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json"},
            )
        else:
            req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return (True, resp.status, "")
    except urllib.error.HTTPError as e:
        passed = e.code < 500
        return (passed, e.code, f"HTTP {e.code}")
    except Exception as ex:
        return (False, 0, str(ex)[:80])


def main():
    parser = argparse.ArgumentParser(description="JARVIS TRADER engine smoke test")
    parser.add_argument(
        "--url",
        default=BASE_URL,
        help=f"Engine base URL (default: {BASE_URL})",
    )
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    print(f"JARVIS TRADER Smoke Test  {base_url}")
    print("=" * 62)

    results = []
    for method, path in ENDPOINTS:
        passed, status, note = check(method, path, base_url)
        results.append((passed, path, status, note))

    # Print results table
    print()
    col_w = max(len(r[1]) for r in results) + 2
    for passed, path, status, note in results:
        marker = "[PASS]" if passed else "[FAIL]"
        note_str = f"  -- {note}" if note else ""
        status_str = str(status) if status else "---"
        print(f"  {marker} {path:<{col_w}} {status_str}{note_str}")

    total = len(results)
    passed_count = sum(1 for r in results if r[0])
    failed_count = total - passed_count

    print()
    print(f"Results: {passed_count}/{total} endpoints passed", end="")
    if failed_count:
        print(f"  ({failed_count} failed)")
        failed_paths = [r[1] for r in results if not r[0]]
        print(f"  Failed: {', '.join(failed_paths)}")
    else:
        print("  -- all clear")

    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
