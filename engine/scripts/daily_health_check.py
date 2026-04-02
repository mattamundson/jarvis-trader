"""
JARVIS TRADER — Daily Health Check Script

Standalone script that validates engine health and paper trading readiness.
Called manually or via PM2 cron job every 30 minutes during market hours.

Calls:
  1. GET /health — Engine uptime and status
  2. GET /safety/status — Kill switch, P&L, drawdown, order rate
  3. GET /portfolio — Equity balance
  4. GET /paper/validation/progress — 30-day validation metrics (if available)

Outputs:
  - One-line summary to console
  - Appends to data/daily_health_log.json
  - Exit code 0 for healthy, 1 for issues

Usage:
  python scripts/daily_health_check.py
  Or scheduled in PM2: pm2 start ecosystem.config.js
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    import urllib.request
    import urllib.error
    httpx = None  # type: ignore

logger = logging.getLogger("daily_health_check")

ENGINE_URL = "http://localhost:8010"
HEALTH_TIMEOUT = 10

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / "daily_health_log.json"


def _setup_logging() -> None:
    """Configure logging to file and console."""
    log_file = Path(__file__).parent.parent / "logs" / "health_check.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _make_request(endpoint: str, method: str = "GET") -> dict[str, Any] | None:
    """Make HTTP request to engine endpoint. Return JSON or None on failure."""
    url = f"{ENGINE_URL}{endpoint}"

    if httpx is not None:
        try:
            resp = httpx.request(method, url, timeout=HEALTH_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"{endpoint}: HTTP {resp.status_code}")
            return None
        except Exception as exc:
            logger.warning(f"{endpoint}: {type(exc).__name__}: {exc}")
            return None

    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT) as resp:
            if resp.status == 200:
                import json

                return json.loads(resp.read().decode("utf-8"))
            logger.warning(f"{endpoint}: HTTP {resp.status}")
            return None
    except Exception as exc:
        logger.warning(f"{endpoint}: {type(exc).__name__}: {exc}")
        return None


def _get_ct_timestamp() -> str:
    """Return current time in CT as ISO string."""
    now_utc = datetime.now(timezone.utc)
    now_ct = now_utc.astimezone(
        timezone(
            None  # Get local timezone, works on configured systems
        )
        if hasattr(timezone, "__init__")
        else None
    )
    return now_utc.isoformat()


def _format_currency(value: float) -> str:
    """Format float as currency string."""
    return f"${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"


def run_health_check() -> int:
    """Run all health checks. Return 0 if healthy, 1 if issues found."""
    _setup_logging()
    logger.info("=" * 70)
    logger.info("JARVIS TRADER Daily Health Check started")

    timestamp = _get_ct_timestamp()
    is_healthy = True
    issues = []

    health_data = _make_request("/health")
    if health_data is None:
        logger.error("Engine is DOWN — cannot connect to /health")
        is_healthy = False
        issues.append("Engine offline")
    else:
        logger.info(f"Health: {health_data.get('status')} (uptime: {health_data.get('uptime_seconds', 0):.1f}s)")

    safety_data = _make_request("/safety/status")
    if safety_data is None:
        logger.warning("Could not fetch safety status")
        is_healthy = False
        issues.append("Safety status unavailable")
    else:
        kill_switch = safety_data.get("kill_switch_active", False)
        daily_pnl = safety_data.get("daily_pnl", 0.0)
        equity = safety_data.get("current_equity", 0.0)
        drawdown = safety_data.get("drawdown_pct", 0.0)
        order_rate = safety_data.get("orders_last_minute", 0)

        if kill_switch:
            reason = safety_data.get("kill_switch_reason", "unknown")
            logger.error(f"KILL SWITCH ACTIVE: {reason}")
            is_healthy = False
            issues.append(f"Kill switch active: {reason}")

        pnl_pct = (daily_pnl / equity * 100) if equity > 0 else 0.0
        if pnl_pct <= -2.0:
            logger.error(f"Daily P&L limit breached: {pnl_pct:.2f}% (limit: -2.0%)")
            is_healthy = False
            issues.append(f"Daily loss limit hit: {pnl_pct:.2f}%")
        else:
            logger.info(f"Daily P&L: {_format_currency(daily_pnl)} ({pnl_pct:+.2f}%)")

        if drawdown <= -0.10:
            logger.error(f"Drawdown limit breached: {drawdown*100:.2f}% (limit: -10.0%)")
            is_healthy = False
            issues.append(f"Drawdown limit hit: {drawdown*100:.2f}%")
        else:
            logger.info(f"Drawdown: {drawdown*100:.2f}% (limit: -10.0%)")

        if order_rate > 10:
            logger.warning(f"Order rate high: {order_rate}/min (safety: 10/min)")
            is_healthy = False
            issues.append(f"Order rate excessive: {order_rate}/min")

    portfolio_data = _make_request("/portfolio")
    if portfolio_data is None:
        logger.warning("Could not fetch portfolio")
        is_healthy = False
        issues.append("Portfolio unavailable")
    else:
        equity = portfolio_data.get("total_equity", 0.0)
        cash = portfolio_data.get("cash_balance", 0.0)
        unrealized_pnl = portfolio_data.get("unrealized_pnl", 0.0)
        positions = portfolio_data.get("positions", [])

        logger.info(f"Portfolio: Equity={_format_currency(equity)} | Cash={_format_currency(cash)} | Unrealized={_format_currency(unrealized_pnl)}")
        logger.info(f"Open positions: {len(positions)}")

    validation_data = _make_request("/paper/validation/progress")
    day_num = 0
    validation_summary = "N/A"
    if validation_data is not None:
        day_num = validation_data.get("current_day", 0)
        trades_today = validation_data.get("trades_today", 0)
        running_days = validation_data.get("running_days", 0)
        target_trades = validation_data.get("target_trades", 0)

        validation_summary = f"Day {day_num}/30 | {running_days}d running | {trades_today} trades | Target: {target_trades}"
        logger.info(f"Validation: {validation_summary}")

    summary_line = _build_summary(day_num, equity, daily_pnl, len(positions), is_healthy)
    logger.info(f"SUMMARY: {summary_line}")

    _append_log(
        {
            "timestamp": timestamp,
            "status": "HEALTHY" if is_healthy else "AT_RISK",
            "summary": summary_line,
            "issues": issues,
            "engine_online": health_data is not None,
            "kill_switch_active": safety_data.get("kill_switch_active", False) if safety_data else None,
            "daily_pnl": daily_pnl if safety_data else None,
            "drawdown_pct": drawdown if safety_data else None,
            "equity": portfolio_data.get("total_equity", 0.0) if portfolio_data else None,
            "open_positions": len(positions) if portfolio_data else None,
            "validation": validation_summary,
        }
    )

    logger.info("=" * 70)
    return 0 if is_healthy else 1


def _build_summary(day: int, equity: float, pnl: float, trades: int, healthy: bool) -> str:
    """Build one-line summary string."""
    status = "ON_TRACK" if healthy else "AT_RISK"
    pnl_str = f"${pnl:+,.0f}" if pnl != 0 else "$0"

    if day > 0:
        return f"Day {day}/30 | Equity: {_format_currency(equity)} | P&L: {pnl_str} | Trades: {trades} | {status}"

    return f"Equity: {_format_currency(equity)} | P&L: {pnl_str} | Trades: {trades} | {status}"


def _append_log(entry: dict[str, Any]) -> None:
    """Append health check entry to daily_health_log.json."""
    logs = []

    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception as exc:
            logger.warning(f"Could not read log file: {exc}")

    logs.append(entry)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
        logger.info(f"Logged to {LOG_FILE}")
    except Exception as exc:
        logger.error(f"Could not write log file: {exc}")


if __name__ == "__main__":
    exit_code = run_health_check()
    sys.exit(exit_code)
