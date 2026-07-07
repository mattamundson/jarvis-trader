#!/usr/bin/env python3
"""
JARVIS TRADER — Session Context Injector
Runs at SessionStart hook. Determines market session and engine health.
Outputs JSON for Claude Code additionalContext injection.
"""
import json
import sys
from datetime import datetime, timezone, timedelta

# Central Time offset (UTC-5 CST / UTC-6 CDT)
CT_OFFSET = -5  # Adjust for DST if needed

def get_ct_time():
    utc = datetime.now(timezone.utc)
    ct = utc + timedelta(hours=CT_OFFSET)
    return ct

def get_market_session(ct: datetime) -> str:
    weekday = ct.weekday()  # 0=Mon, 6=Sun
    hour = ct.hour
    minute = ct.minute
    time_decimal = hour + minute / 60.0

    # Weekend
    if weekday == 5:  # Saturday
        return "WEEKEND"
    if weekday == 6 and time_decimal < 17.0:  # Sunday before 5pm CT
        return "WEEKEND"

    # Friday after-hours
    if weekday == 4 and time_decimal >= 16.0:
        return "WEEKEND"

    # Market sessions (CT)
    if 5.0 <= time_decimal < 8.5:
        return "PRE_MARKET"
    elif 8.5 <= time_decimal < 9.583:  # 8:30am to 9:35am
        return "RTH_OPEN_AVOID"  # First 5min of RTH - avoid new entries
    elif 9.583 <= time_decimal < 15.5:  # 9:35am to 3:30pm
        return "RTH_ACTIVE"
    elif 15.5 <= time_decimal < 16.0:  # 3:30pm to 4pm
        return "RTH_CLOSE_AVOID"  # Last 15min - avoid new entries
    elif 16.0 <= time_decimal < 17.0:
        return "AFTER_HOURS"
    else:
        return "OVERNIGHT"

def check_engine_health() -> dict:
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            "http://localhost:8010/health",
            headers={"X-API-Key": "jarvis-dev-key-change-me"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return {"status": "UP", "version": data.get("version", "unknown")}
    except Exception:
        return {"status": "DOWN"}

def check_safety_status() -> dict:
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:8010/safety/status",
            headers={"X-API-Key": "jarvis-dev-key-change-me"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            kill_switch = data.get("kill_switch_active", False)
            daily_pnl = data.get("daily_pnl_pct", 0.0)
            return {
                "kill_switch": "ACTIVE" if kill_switch else "INACTIVE",
                "daily_pnl_pct": round(daily_pnl * 100, 2),
                "live_trading": data.get("live_trading_enabled", False),
            }
    except Exception:
        return {"kill_switch": "UNKNOWN", "daily_pnl_pct": None, "live_trading": False}

def main():
    ct = get_ct_time()
    session = get_market_session(ct)
    engine = check_engine_health()
    safety = check_safety_status()

    # Build session label
    session_labels = {
        "PRE_MARKET": "Pre-Market (pipeline analysis OK, no entries yet)",
        "RTH_OPEN_AVOID": "RTH Open — first 5 min, AVOID new entries (gap-fill volatility)",
        "RTH_ACTIVE": "RTH Active — PRIMARY TRADING WINDOW, all signals valid",
        "RTH_CLOSE_AVOID": "RTH Close — last 15 min, AVOID new entries",
        "AFTER_HOURS": "After-Hours — earnings zone, avoid futures entries",
        "OVERNIGHT": "Overnight — micro futures active, max 1 contract",
        "WEEKEND": "Weekend — markets closed, backtest/review/prepare only",
    }

    # Kill switch warning
    kill_switch_warning = ""
    if safety["kill_switch"] == "ACTIVE":
        kill_switch_warning = "\n⚠️  KILL SWITCH IS ACTIVE — TRADING HALTED. Daily P&L or drawdown limit breached. Tier 3 required to deactivate."

    # Daily P&L warning
    pnl_warning = ""
    pnl = safety.get("daily_pnl_pct")
    if pnl is not None and pnl <= -1.5:
        pnl_warning = f"\n⚠️  WARNING: Daily P&L at {pnl}% — approaching -2% halt threshold."

    context = f"""JARVIS TRADER SESSION CONTEXT
Time (CT): {ct.strftime('%A %Y-%m-%d %H:%M')}
Market Session: {session} — {session_labels.get(session, session)}
Engine (port 8010): {engine['status']}{' v' + engine.get('version', '') if engine['status'] == 'UP' else ''}
Kill Switch: {safety['kill_switch']}
Daily P&L: {pnl}% | Live Trading: {'ENABLED ⚠️' if safety['live_trading'] else 'DISABLED (paper mode)'}
{kill_switch_warning}{pnl_warning}"""

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context.strip()
        }
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()
