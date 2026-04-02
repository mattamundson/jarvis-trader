"""
JARVIS TRADER — Pre-Market Intelligence Brief Generator

Runs at 6:30am CT (before market open at 8:30am CT).
Generates formatted market intelligence brief for the trader.

Calls:
  1. GET /health — Engine status
  2. GET /macro/snapshot — VIX, yields, DXY, macro regime
  3. GET /prices/snapshot — Overnight price changes
  4. GET /sentiment/recent — Reddit sentiment on watchlist
  5. GET /portfolio — Current equity and positions
  6. GET /decisions/recent — Recent pipeline decisions
  7. GET /scheduler/status — Scheduler state

Outputs:
  - Formatted brief to console
  - Saves to data/morning_briefs/YYYY-MM-DD.md

Usage:
  python scripts/morning_brief.py
  Or scheduled in PM2 at 6:30am CT
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

logger = logging.getLogger("morning_brief")

ENGINE_URL = "http://localhost:8010"
HEALTH_TIMEOUT = 10

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BRIEFS_DIR = DATA_DIR / "morning_briefs"
BRIEFS_DIR.mkdir(parents=True, exist_ok=True)


def _setup_logging() -> None:
    """Configure logging to file and console."""
    log_file = Path(__file__).parent.parent / "logs" / "morning_brief.log"
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


def run_brief() -> int:
    """Generate and save morning brief. Return 0 on success."""
    _setup_logging()
    logger.info("=" * 70)
    logger.info("JARVIS TRADER Pre-Market Brief — Starting")

    ct_now = _get_ct_now()
    brief_time = ct_now.strftime("%A, %B %d, %Y | %I:%M%p %Z")

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"JARVIS TRADER — Pre-Market Brief | {brief_time}")
    lines.append("=" * 70)
    lines.append("")

    health_data = _make_request("/health")
    if health_data is None:
        lines.append("ERROR: Engine is OFFLINE. Cannot generate brief.")
        logger.error("Engine offline — aborting brief")
        print("\n".join(lines))
        return 1

    status = health_data.get("status", "unknown")
    uptime_sec = health_data.get("uptime_seconds", 0)
    uptime_hr = int(uptime_sec // 3600)
    uptime_min = int((uptime_sec % 3600) // 60)

    lines.append("SYSTEM STATUS")
    lines.append(f"  Status:  {status.upper()}")
    lines.append(f"  Uptime:  {uptime_hr}h {uptime_min}m")
    lines.append("")

    safety_data = _make_request("/safety/status")
    if safety_data:
        kill_switch = safety_data.get("kill_switch_active", False)
        if kill_switch:
            reason = safety_data.get("kill_switch_reason", "unknown")
            lines.append(f"  WARNING: KILL SWITCH ACTIVE — {reason}")

    macro_data = _make_request("/macro/snapshot")
    if macro_data:
        lines.append("MACRO SNAPSHOT")
        vix = macro_data.get("vix", "N/A")
        vix_regime = macro_data.get("vix_regime", "unknown")
        ten_yr = macro_data.get("ten_year_yield", "N/A")
        dxy = macro_data.get("dxy", "N/A")
        macro_regime = macro_data.get("macro_regime", "unknown")

        if isinstance(vix, (int, float)):
            lines.append(f"  VIX:       {vix:.2f} ({vix_regime})")
        else:
            lines.append(f"  VIX:       {vix} ({vix_regime})")

        if isinstance(ten_yr, (int, float)):
            lines.append(f"  10yr Yld:  {ten_yr:.3f}%")
        else:
            lines.append(f"  10yr Yld:  {ten_yr}")

        if isinstance(dxy, (int, float)):
            lines.append(f"  DXY:       {dxy:.1f}")
        else:
            lines.append(f"  DXY:       {dxy}")

        lines.append(f"  Regime:    {macro_regime}")

        notes = macro_data.get("macro_notes", "")
        if notes:
            lines.append(f"  Notes:     {notes}")

        events = macro_data.get("upcoming_events", [])
        if events:
            lines.append("  Events:")
            for event in events[:3]:
                lines.append(f"    - {event}")
        lines.append("")
    else:
        lines.append("MACRO: Not available (FRED API not configured)")
        lines.append("")

    prices_data = _make_request("/prices/snapshot")
    if prices_data:
        lines.append("MARKET SNAPSHOT")
        lines.append(f"{'Symbol':<8} {'Price':>12} {'Prev Close':>12} {'% Change':>10}")
        lines.append("-" * 45)

        for symbol in ["MES", "MNQ", "MCL", "SPY", "QQQ"]:
            if symbol in prices_data:
                price_info = prices_data[symbol]
                last_price = price_info.get("last_price", "N/A")
                prev_close = price_info.get("prev_close", "N/A")
                change_pct = price_info.get("change_pct", "N/A")

                if (
                    isinstance(last_price, (int, float))
                    and isinstance(prev_close, (int, float))
                    and isinstance(change_pct, (int, float))
                ):
                    lines.append(
                        f"{symbol:<8} {last_price:>12.2f} {prev_close:>12.2f} {change_pct:>9.2f}%"
                    )
                else:
                    lines.append(
                        f"{symbol:<8} {str(last_price):>12} {str(prev_close):>12} {str(change_pct):>10}"
                    )

        lines.append("")
    else:
        lines.append("PRICES: Not available")
        lines.append("")

    sentiment_data = _make_request("/sentiment/recent")
    if sentiment_data and isinstance(sentiment_data, list) and len(sentiment_data) > 0:
        lines.append("OVERNIGHT SENTIMENT (Reddit)")

        for item in sentiment_data[:5]:
            symbol = item.get("symbol", "?")
            score = item.get("score", 0.0)
            post_count = item.get("post_count", 0)

            if score > 0.2:
                sentiment = "BULLISH"
            elif score < -0.2:
                sentiment = "BEARISH"
            else:
                sentiment = "NEUTRAL"

            if isinstance(score, (int, float)) and isinstance(post_count, int):
                lines.append(
                    f"  {symbol:>6}: {sentiment:>8} (score: {score:+.2f}, {post_count} posts)"
                )
            else:
                lines.append(f"  {symbol:>6}: {sentiment:>8}")

        lines.append("")
    else:
        lines.append("SENTIMENT: Not available")
        lines.append("")

    portfolio_data = _make_request("/portfolio")
    if portfolio_data:
        lines.append("PORTFOLIO")
        equity = portfolio_data.get("total_equity", 0.0)
        daily_pnl = portfolio_data.get("daily_pnl", 0.0)
        positions = portfolio_data.get("positions", [])

        if isinstance(equity, (int, float)):
            lines.append(f"  Equity:       ${equity:,.2f}")
        if isinstance(daily_pnl, (int, float)):
            pnl_pct = (daily_pnl / equity * 100) if equity > 0 else 0.0
            pnl_str = f"${daily_pnl:+,.2f}" if daily_pnl != 0 else "$0.00"
            lines.append(f"  Daily P&L:    {pnl_str} ({pnl_pct:+.2f}%)")

        if positions:
            lines.append(f"  Positions:    {len(positions)} open")
        else:
            lines.append("  Positions:    NONE (clean slate)")

        lines.append("")
    else:
        lines.append("PORTFOLIO: Not available")
        lines.append("")

    decisions_data = _make_request("/decisions/recent?limit=5")
    if decisions_data and isinstance(decisions_data, list):
        non_holds = [d for d in decisions_data if d.get("action", "").lower() != "hold"]
        if non_holds:
            lines.append("RECENT DECISIONS (non-HOLD)")
            for dec in non_holds:
                action = dec.get("action", "?").upper()
                symbol = dec.get("symbol", "?")
                conf = dec.get("confidence", 0.0)
                if isinstance(conf, (int, float)):
                    lines.append(f"  {symbol}: {action} (confidence: {conf:.2f})")
                else:
                    lines.append(f"  {symbol}: {action}")
            lines.append("")
        else:
            lines.append("RECENT DECISIONS: All HOLD — no setup yet")
            lines.append("")
    else:
        lines.append("DECISIONS: Not available")
        lines.append("")

    scheduler_data = _make_request("/scheduler/status")
    if scheduler_data:
        running = scheduler_data.get("running", False)
        jobs = scheduler_data.get("jobs", [])
        total_decisions = scheduler_data.get("total_decisions_logged", 0)

        scheduler_status = "RUNNING" if running else "STOPPED"
        lines.append("SCHEDULER")
        lines.append(f"  Status:               {scheduler_status}")
        if jobs and len(jobs) > 0:
            next_run = jobs[0].get("next_run", "unknown")
            lines.append(f"  Next scan:            {next_run}")
        lines.append(f"  Total decisions:      {total_decisions}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("Matt's Schedule Today")
    lines.append("  8:00–8:30am CT:  Active prep window (Matt)")
    lines.append("  8:30–9:35am CT:  Avoid noise (high volatility)")
    lines.append("  9:35–11:30am CT: Primary trading window (LIVE)")
    lines.append("  1:00–3:30pm CT:  Secondary trading window (LIVE)")
    lines.append("=" * 70)
    lines.append("")

    brief_text = "\n".join(lines)
    print(brief_text)

    brief_file = BRIEFS_DIR / f"{_get_ct_date_str()}.md"
    try:
        with open(brief_file, "w", encoding="utf-8") as f:
            f.write(brief_text)
        logger.info(f"Brief saved to {brief_file}")
    except Exception as exc:
        logger.error(f"Could not save brief: {exc}")

    return 0


if __name__ == "__main__":
    exit_code = run_brief()
    sys.exit(exit_code)
