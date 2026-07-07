#!/usr/bin/env python
"""
Daily Live-Readiness Gauge — $250/day × 14-trading-day ROI Trigger

Evaluates the 7 hard gates defined in backtest.roi_readiness against the
last 14 trading days of paper trading data, posts a headline to Discord,
and saves a Markdown report.

Usage (from jarvis-trader root):
    engine/.venv/Scripts/python -m engine.scripts.daily_live_readiness
    engine/.venv/Scripts/python -m engine.scripts.daily_live_readiness --date 2026-05-07
    engine/.venv/Scripts/python -m engine.scripts.daily_live_readiness --no-discord
    engine/.venv/Scripts/python -m engine.scripts.daily_live_readiness --json

Or from inside engine/ directory:
    .venv/Scripts/python -m scripts.daily_live_readiness

Output:
    - Markdown report saved to engine/data/live_readiness_reports/<YYYY-MM-DD>.md
    - Discord headline (1-line): [GATES 5/7] PnL pass=NO ($-2/day) | streak=0 | days_to_live=14
    - stdout: same headline (captured by Task Scheduler log)
    - --json: structured JSON dump of the full result

Scheduling:
    Task: Jarvis-DailyLiveReadiness
    Trigger: 16:35 ET weekdays (5 min after post-trade report at 16:30)
    Action: engine/.venv/Scripts/python -m engine.scripts.daily_live_readiness
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from backtest.roi_readiness import ROIReadinessResult

# ---------------------------------------------------------------------------
# Path bootstrap — works both as -m engine.scripts.daily_live_readiness (from
# jarvis-trader root) and as -m scripts.daily_live_readiness (from engine/).
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("daily_live_readiness")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ET = ZoneInfo("America/New_York")
_REPORT_DIR = _ENGINE_DIR / "data" / "live_readiness_reports"
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_STATE_FILE = _ENGINE_DIR / "data" / "live_readiness_state.json"

# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------


def _FMT_MONEY(x):
    return f"${x:+.2f}" if x is not None else "—"


def _status_emoji(status: str) -> str:
    return {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(status, "⚪")


def render_report(result: "ROIReadinessResult", report_date: date) -> str:
    from backtest.roi_readiness import ROIReadinessResult  # noqa: F401 (for typing)

    lines: list[str] = []
    lines.append(f"# JARVIS Live-Readiness Gauge — {report_date.isoformat()}")
    lines.append(f"*Generated {datetime.now().astimezone(_ET).strftime('%Y-%m-%dT%H:%M %Z')}*")
    lines.append("")

    # Top-line status
    emoji = _status_emoji(result.status)
    lines.append(f"## Status: {emoji} {result.status} ({result.pass_count}/7 gates pass)")
    lines.append("")
    lines.append(
        f"**Streak:** {result.consecutive_passing_days} consecutive passing day(s)  "
        f"**|**  **Days to live:** {result.days_to_live} "
        f"(target: 14 consecutive passing days)"
    )
    lines.append("")
    lines.append(
        "> **Rule:** streak resets to 0 on ANY gate failure. "
        "All 7 gates must pass on the same calendar day for it to count."
    )
    lines.append("")

    # Gate table
    lines.append("## Gate Results")
    lines.append("")
    lines.append("| Gate | Name | Result | Observed | Threshold |")
    lines.append("|------|------|--------|----------|-----------|")
    for g in result.gates:
        status_str = "✅ PASS" if g.passed else "❌ FAIL"
        obs = g.observed.replace("|", "\\|")
        thr = g.threshold.replace("|", "\\|")
        lines.append(f"| {g.gate_id} | {g.name} | {status_str} | {obs} | {thr} |")
    lines.append("")

    # Detailed notes per gate
    lines.append("## Gate Details")
    for g in result.gates:
        marker = "✅" if g.passed else "❌"
        lines.append(f"### {marker} {g.gate_id}: {g.name}")
        lines.append(f"- **Result:** {'PASS' if g.passed else 'FAIL'}")
        lines.append(f"- **Observed:** {g.observed}")
        lines.append(f"- **Threshold:** {g.threshold}")
        if g.notes:
            lines.append(f"- **Notes:** {g.notes}")
        lines.append("")

    # Days-to-live gauge
    lines.append("## Days-to-Live Gauge")
    lines.append("")
    streak = result.consecutive_passing_days
    target = 14
    filled = min(streak, target)
    bar = "█" * filled + "░" * (target - filled)
    lines.append("```")
    lines.append(f"Progress: [{bar}] {streak}/{target} days")
    lines.append(f"Days remaining: {result.days_to_live}")
    lines.append("```")
    lines.append("")
    lines.append(
        "> A single gate failure on any day resets the streak to 0. "
        "The counter only advances on days where all 7 gates pass simultaneously."
    )
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(
        "*JARVIS live-readiness gauge — paper trading validation period. "
        "Gate v2 PASS strategies: MES R11, MGC R4. "
        "DO_NOT_TRADE: MCL, MNQ, M2K.*"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord headline
# ---------------------------------------------------------------------------


async def _post_discord_headline(result: "ROIReadinessResult") -> None:
    """Post a 1-line headline to Discord via discord_notifier."""
    try:
        from notifications.discord_notifier import _send_embed  # noqa: E402
    except ImportError:
        logger.warning("discord_notifier not importable — Discord post skipped")
        return

    g1 = next((g for g in result.gates if g.gate_id == "G1"), None)
    pnl_pass = "YES" if (g1 and g1.passed) else "NO"
    pnl_obs = g1.observed if g1 else "?"

    color = {"GREEN": 0x2ECC71, "YELLOW": 0xF1C40F, "RED": 0xE74C3C}.get(result.status, 0x95A5A6)

    headline = (
        f"[GATES {result.pass_count}/7] "
        f"PnL pass={pnl_pass} ({pnl_obs}) | "
        f"streak={result.consecutive_passing_days} | "
        f"days_to_live={result.days_to_live}"
    )

    embed = {
        "title": f"Live-Readiness Gauge — {result.status}",
        "description": headline,
        "color": color,
        "fields": [
            {
                "name": "Gate",
                "value": "\n".join(g.gate_id for g in result.gates),
                "inline": True,
            },
            {
                "name": "Result",
                "value": "\n".join("✅ PASS" if g.passed else "❌ FAIL" for g in result.gates),
                "inline": True,
            },
            {
                "name": "Observed",
                "value": "\n".join(g.observed[:60] for g in result.gates),
                "inline": True,
            },
        ],
        "footer": {
            "text": (
                f"streak={result.consecutive_passing_days}d | "
                f"days_to_live={result.days_to_live} | "
                f"eval={result.snapshot_date.isoformat()}"
            )
        },
    }

    await _send_embed(embed, alert_type="live_readiness")
    logger.info("Discord live-readiness headline posted: %s", headline)


def _write_state_file(result: "ROIReadinessResult", state_path: Path = _STATE_FILE) -> None:
    """Write machine-readable go/no-go state JSON for other tools to consume."""
    state = {
        "evaluated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
        "snapshot_date": result.snapshot_date.isoformat(),
        "status": result.status,
        "go": result.status == "GREEN",
        "pass_count": result.pass_count,
        "total_gates": len(result.gates),
        "consecutive_passing_days": result.consecutive_passing_days,
        "days_to_live": result.days_to_live,
        "gates": [
            {
                "gate_id": g.gate_id,
                "name": g.name,
                "passed": g.passed,
                "observed": g.observed,
                "threshold": g.threshold,
            }
            for g in result.gates
        ],
    }
    try:
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        logger.info("State file written: %s", state_path)
    except OSError as exc:
        logger.warning("Could not write state file %s: %s", state_path, exc)


def _build_discord_headline(result: "ROIReadinessResult") -> str:
    """Build the 1-line headline string (used for stdout and Discord)."""
    g1 = next((g for g in result.gates if g.gate_id == "G1"), None)
    pnl_pass = "YES" if (g1 and g1.passed) else "NO"
    pnl_obs = g1.observed if g1 else "?"

    return (
        f"[GATES {result.pass_count}/7] "
        f"PnL pass={pnl_pass} ({pnl_obs}) | "
        f"streak={result.consecutive_passing_days} | "
        f"days_to_live={result.days_to_live}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--date",
        default=None,
        help="Evaluation date YYYY-MM-DD (default: today ET)",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Skip Discord post",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output (suppresses markdown rendering)",
    )
    args = parser.parse_args()

    # Resolve evaluation date
    if args.date:
        try:
            report_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            return 1
    else:
        report_date = datetime.now(_ET).date()

    logger.info("Evaluating live-readiness for %s", report_date)

    # Import and run evaluation (graceful crash protection)
    try:
        from backtest.roi_readiness import evaluate  # noqa: E402

        result = evaluate(as_of=report_date)
    except Exception as exc:
        logger.error("ROI readiness evaluation failed: %s", exc, exc_info=True)
        if args.json:
            print(json.dumps({"error": str(exc)}))
        return 2

    # JSON mode
    if args.json:
        out = asdict(result)
        out["snapshot_date"] = result.snapshot_date.isoformat()
        print(json.dumps(out, indent=2, default=str))
        # Exit 0 on successful evaluation; status is in the JSON payload.
        return 0

    # Render markdown report
    try:
        report_md = render_report(result, report_date)
    except Exception as exc:
        logger.warning("Report rendering failed: %s", exc)
        report_md = f"# Report rendering error\n\n```\n{exc}\n```\n"

    # Save report
    try:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _REPORT_DIR / f"{report_date.isoformat()}.md"
        report_path.write_text(report_md, encoding="utf-8")
        logger.info("Report saved → %s", report_path)
    except OSError as exc:
        logger.error("Could not save report: %s", exc)

    # Discord
    if not args.no_discord:
        try:
            asyncio.run(_post_discord_headline(result))
        except Exception as exc:
            logger.warning("Discord post failed: %s", exc)
    else:
        logger.info("Discord post skipped (--no-discord)")

    # Stdout headline (captured by Task Scheduler log)
    headline = _build_discord_headline(result)
    print(f"[JARVIS-LIVE-READINESS] {report_date} | {headline}")

    # Print gate table to stdout
    print(f"\nStatus: {result.status} ({result.pass_count}/7 gates)")
    for g in result.gates:
        marker = "PASS" if g.passed else "FAIL"
        print(f"  [{marker}] {g.gate_id}: {g.observed}")

    # Write machine-readable state file (consumed by dashboard, regime_alert, etc.)
    _write_state_file(result)

    # Exit 0 on successful evaluation (report saved + headline emitted).
    # Gate status (GREEN/YELLOW/RED) is data, not a task-runner failure signal.
    # A RED status during paper validation is a normal expected outcome and
    # should not surface as a Last Result = 1 in Task Scheduler. The exit
    # code only reflects whether the worker itself failed (return 2 above).
    return 0


if __name__ == "__main__":
    sys.exit(main())
