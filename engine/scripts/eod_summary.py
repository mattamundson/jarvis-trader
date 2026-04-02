"""
JARVIS TRADER — End-of-Day Summary Generator

Runs at 4:05pm CT (after market close at 4:00pm CT).
Generates daily journal entry with trades, P&L, and lessons learned.

Calls:
  1. GET /portfolio — Final equity and positions
  2. GET /safety/status — Final daily P&L and drawdown
  3. GET /decisions/recent — Trades taken today
  4. GET /learning/patterns — Learning system insights (if available)

Outputs:
  - Formatted journal entry to console
  - Saves to data/daily_journals/YYYY-MM-DD.md

Usage:
  python scripts/eod_summary.py
  Or scheduled in PM2 at 4:05pm CT
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    import urllib.request
    import urllib.error
    httpx = None  # type: ignore

logger = logging.getLogger("eod_summary")

ENGINE_URL = "http://localhost:8010"
HEALTH_TIMEOUT = 10

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

JOURNALS_DIR = DATA_DIR / "daily_journals"
JOURNALS_DIR.mkdir(parents=True, exist_ok=True)


def _setup_logging() -> None:
    """Configure logging to file and console."""
    log_file = Path(__file__).parent.parent / "logs" / "eod_summary.log"
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


def _make_request(endpoint: str, method: str = "GET") -> dict[str, Any] | list[Any] | None:
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


def _get_ct_now() -> datetime:
    """Get current time in CT."""
    return datetime.now(timezone.utc).astimezone()


def _get_ct_date_str() -> str:
    """Get today's date as YYYY-MM-DD in CT."""
    ct_now = _get_ct_now()
    return ct_now.strftime("%Y-%m-%d")


def run_eod_summary() -> int:
    """Generate and save EOD summary. Return 0 on success."""
    _setup_logging()
    logger.info("=" * 70)
    logger.info("JARVIS TRADER End-of-Day Summary — Starting")

    ct_now = _get_ct_now()
    journal_time = ct_now.strftime("%A, %B %d, %Y | %I:%M%p %Z")

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"JARVIS TRADER — Daily Journal | {journal_time}")
    lines.append("=" * 70)
    lines.append("")

    portfolio_data = _make_request("/portfolio")
    if portfolio_data is None:
        lines.append("ERROR: Cannot fetch portfolio data.")
        logger.error("Portfolio data unavailable")
        print("\n".join(lines))
        return 1

    equity = portfolio_data.get("total_equity", 0.0)
    cash = portfolio_data.get("cash_balance", 0.0)
    realized_pnl = portfolio_data.get("realized_pnl", 0.0)
    unrealized_pnl = portfolio_data.get("unrealized_pnl", 0.0)
    daily_pnl = portfolio_data.get("daily_pnl", 0.0)
    positions = portfolio_data.get("positions", [])

    lines.append("PORTFOLIO EOD")
    if isinstance(equity, (int, float)):
        lines.append(f"  Total Equity:     ${equity:,.2f}")
    if isinstance(cash, (int, float)):
        lines.append(f"  Cash Balance:     ${cash:,.2f}")
    if isinstance(realized_pnl, (int, float)):
        lines.append(f"  Realized P&L:     ${realized_pnl:+,.2f}")
    if isinstance(unrealized_pnl, (int, float)):
        lines.append(f"  Unrealized P&L:   ${unrealized_pnl:+,.2f}")
    if isinstance(daily_pnl, (int, float)):
        pnl_pct = (daily_pnl / equity * 100) if equity > 0 else 0.0
        lines.append(f"  Daily P&L:        ${daily_pnl:+,.2f} ({pnl_pct:+.2f}%)")

    if positions:
        lines.append(f"  Open Positions:   {len(positions)}")
        for pos in positions:
            symbol = pos.get("symbol", "?")
            qty = pos.get("quantity", 0)
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            unreal = pos.get("unrealized_pnl", 0)

            if isinstance(qty, (int, float)) and isinstance(entry, (int, float)) and isinstance(current, (int, float)):
                lines.append(f"    - {symbol}: {qty:+.0f} @ {entry:.2f} (current: {current:.2f}, U/L: ${unreal:+,.2f})")
            else:
                lines.append(f"    - {symbol}: {qty} @ {entry}")
    else:
        lines.append("  Open Positions:   NONE")

    lines.append("")

    safety_data = _make_request("/safety/status")
    if safety_data:
        lines.append("RISK METRICS EOD")
        kill_switch = safety_data.get("kill_switch_active", False)
        if kill_switch:
            reason = safety_data.get("kill_switch_reason", "unknown")
            lines.append(f"  Kill Switch:      ACTIVE ({reason})")
        else:
            lines.append("  Kill Switch:      OFF")

        daily_pnl_val = safety_data.get("daily_pnl", 0.0)
        equity_peak = safety_data.get("equity_peak", equity)
        drawdown = safety_data.get("drawdown_pct", 0.0)

        if isinstance(daily_pnl_val, (int, float)):
            pnl_pct = (daily_pnl_val / equity_peak * 100) if equity_peak > 0 else 0.0
            lines.append(f"  Daily P&L %:      {pnl_pct:+.2f}% (limit: -2.0%)")

        if isinstance(drawdown, (int, float)):
            lines.append(f"  Drawdown:         {drawdown*100:+.2f}% (limit: -10.0%)")

        lines.append("")

    decisions_data = _make_request("/decisions/recent?limit=20")
    if decisions_data and isinstance(decisions_data, list):
        today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time())

        trades = []
        for dec in decisions_data:
            action = dec.get("action", "").lower()
            if action in ("buy", "sell"):
                ts_str = dec.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str) if ts_str else None
                    if ts and ts >= today_start:
                        trades.append(dec)
                except (ValueError, TypeError):
                    trades.append(dec)

        if trades:
            lines.append(f"TRADES TAKEN TODAY ({len(trades)} trades)")
            for i, trade in enumerate(trades, 1):
                symbol = trade.get("symbol", "?")
                action = trade.get("action", "?").upper()
                confidence = trade.get("confidence", 0.0)
                summary = trade.get("summary", "")

                if isinstance(confidence, (int, float)):
                    lines.append(f"  {i}. {symbol} {action} | Confidence: {confidence:.2f}")
                else:
                    lines.append(f"  {i}. {symbol} {action}")

                if summary:
                    lines.append(f"     {summary[:100]}")

            lines.append("")
        else:
            lines.append("TRADES TAKEN TODAY: None")
            lines.append("")

    validation_data = _make_request("/paper/validation/progress")
    if validation_data:
        lines.append("30-DAY VALIDATION PROGRESS")
        current_day = validation_data.get("current_day", 0)
        running_days = validation_data.get("running_days", 0)
        total_trades = validation_data.get("total_trades", 0)
        target_trades = validation_data.get("target_trades", 30)
        trades_today = validation_data.get("trades_today", 0)

        if isinstance(current_day, int):
            lines.append(f"  Current Day:      Day {current_day}/30")
        if isinstance(running_days, int):
            lines.append(f"  Running Days:     {running_days}")
        if isinstance(total_trades, int):
            lines.append(f"  Total Trades:     {total_trades} (target: {target_trades})")
        if isinstance(trades_today, int):
            lines.append(f"  Trades Today:     {trades_today}")

        lines.append("")

    learning_data = _make_request("/learning/patterns")
    if learning_data and isinstance(learning_data, dict):
        patterns = learning_data.get("patterns", [])
        recommendations = learning_data.get("recommendations", [])

        if patterns:
            lines.append("LEARNING SYSTEM — PATTERNS DETECTED")
            for pattern in patterns[:3]:
                pattern_name = pattern.get("name", "?")
                confidence = pattern.get("confidence", 0.0)
                if isinstance(confidence, (int, float)):
                    lines.append(f"  - {pattern_name} (confidence: {confidence:.2f})")
                else:
                    lines.append(f"  - {pattern_name}")
            lines.append("")

        if recommendations:
            lines.append("LEARNING SYSTEM — RECOMMENDATIONS")
            for rec in recommendations[:3]:
                action = rec.get("action", "?")
                reason = rec.get("reason", "")
                if reason:
                    lines.append(f"  - {action}: {reason[:80]}")
                else:
                    lines.append(f"  - {action}")
            lines.append("")

    lines.append("=" * 70)
    lines.append("END OF DAY NOTES")
    lines.append("  Reflect on today's trades, setups, and execution.")
    lines.append("  Use learning system insights for tomorrow's plan.")
    lines.append("=" * 70)
    lines.append("")

    journal_text = "\n".join(lines)
    print(journal_text)

    journal_file = JOURNALS_DIR / f"{_get_ct_date_str()}.md"
    try:
        with open(journal_file, "w", encoding="utf-8") as f:
            f.write(journal_text)
        logger.info(f"Journal saved to {journal_file}")
    except Exception as exc:
        logger.error(f"Could not save journal: {exc}")

    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = run_eod_summary()
    sys.exit(exit_code)
