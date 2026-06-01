"""
Discord Webhook Notifier — send JARVIS alerts as rich embeds to Discord channels.

Reads DISCORD_WEBHOOK_URL from environment. All functions are fire-and-forget
async coroutines that silently no-op when the URL is not set or TESTING=1.

Environment variables:
  DISCORD_WEBHOOK_URL            — full Discord webhook URL (required to send)
  DISCORD_ENABLED                — "false" to disable without removing the URL (default: true)
  JARVIS_DISCORD_APPROVAL_WEBHOOK — separate webhook for approval channel (optional)

Usage:
  from notifications.discord_notifier import discord_signal, discord_kill_switch
  await discord_signal(symbol="MCL", action="BUY", confidence=0.87, reason="STC cross above 15")
  await discord_kill_switch(reason="daily_loss_limit", message="-2.1% P&L exceeded")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_URL = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
_ENABLED = os.getenv("DISCORD_ENABLED", "true").lower() not in ("false", "0", "no")
_TESTING = os.getenv("TESTING", "0") in ("1", "true", "yes")

_CT = ZoneInfo("America/Chicago")

# Optional db reference injected from main.py for alert logging
_db = None


def inject_db(db_manager) -> None:
    """Wire in the DatabaseManager so sends are logged to alert_log table."""
    global _db
    _db = db_manager


def _ct_time() -> str:
    return datetime.now(_CT).strftime("%I:%M %p CT")


def _iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ready() -> bool:
    if _TESTING:
        return False
    if not _ENABLED:
        return False
    if not _WEBHOOK_URL:
        return False
    return True


async def _send(content: str) -> bool:
    """POST plain-text content to the Discord webhook. Returns True on success."""
    if not _ready():
        logger.debug("Discord notifier not configured or disabled — skipping send.")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _WEBHOOK_URL,
                json={"content": content, "username": "JARVIS"},
            )
            if resp.status_code in (200, 204):
                return True
            logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Discord webhook send failed: %s", exc)
        return False


async def _send_embed(
    embed: dict,
    content: str | None = None,
    webhook_url: str | None = None,
    alert_type: str = "discord",
) -> bool:
    """POST a rich embed to the Discord webhook. Returns True on success."""
    url = webhook_url or _WEBHOOK_URL
    if _TESTING:
        logger.debug("Discord notifier TESTING — skipping embed send.")
        return False
    if not _ENABLED:
        logger.debug("Discord notifier disabled — skipping embed send.")
        return False
    if not url:
        logger.debug("Discord notifier: no webhook URL — skipping embed send.")
        return False

    payload: dict = {"username": "JARVIS", "embeds": [embed]}
    if content:
        payload["content"] = content

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code in (200, 204):
                _log_alert(alert_type, embed.get("description") or embed.get("title", ""))
                return True
            logger.warning("Discord embed webhook returned %s: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Discord embed webhook send failed: %s", exc)
        return False


def _log_alert(alert_type: str, message: str) -> None:
    """Fire-and-forget: log successful send to alert_log table."""
    if _db is None:
        return
    try:
        if hasattr(_db, "insert_alert_log"):
            _db.insert_alert_log(
                alert_type=alert_type,
                message=message[:500],
                channel="discord",
            )
    except Exception as exc:
        logger.debug("alert_log insert failed (non-fatal): %s", exc)


def _footer() -> dict:
    return {"text": "JARVIS Trader"}


# ---------------------------------------------------------------------------
# Public notification functions
# ---------------------------------------------------------------------------


async def discord_signal(
    symbol: str,
    action: str,
    confidence: float,
    reason: str = "",
) -> bool:
    """Send a trade signal alert as a rich embed."""
    pct = int(confidence * 100)
    is_long = action.upper() in ("BUY", "LONG")
    color = 0x00C853 if is_long else 0xD50000

    fields = [
        {"name": "Symbol", "value": symbol.upper(), "inline": True},
        {"name": "Direction", "value": action.upper(), "inline": True},
        {"name": "Confidence", "value": f"{pct}%", "inline": True},
    ]
    if reason:
        fields.append({"name": "Reason", "value": reason[:200], "inline": False})

    embed = {
        "title": "📊 JARVIS Signal",
        "color": color,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="signal")


async def discord_kill_switch(
    reason: str = "",
    message: str = "",
) -> bool:
    """Send a kill-switch activated alert."""
    fields = []
    if reason:
        fields.append({"name": "Reason", "value": reason.replace("_", " ").upper(), "inline": False})
    if message:
        fields.append({"name": "Detail", "value": message[:300], "inline": False})

    embed = {
        "title": "🛑 Kill Switch ACTIVATED",
        "description": "All trading halted.",
        "color": 0xD50000,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="kill_switch")


async def discord_kill_switch_deactivated() -> bool:
    """Send a kill-switch cleared alert."""
    embed = {
        "title": "✅ Kill Switch CLEARED",
        "description": "Trading resumed.",
        "color": 0x00C853,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="kill_switch_deactivated")


async def discord_approval_required(
    symbol: str,
    action: str,
    confidence: float,
    reason: str = "",
    approval_url: str = "http://localhost:3010/trades/pending-approvals",
) -> bool:
    """Send a pending approval alert."""
    pct = int(confidence * 100)

    fields = [
        {"name": "Symbol", "value": symbol.upper(), "inline": True},
        {"name": "Direction", "value": action.upper(), "inline": True},
        {"name": "Confidence", "value": f"{pct}%", "inline": True},
        {"name": "Dashboard", "value": approval_url, "inline": False},
    ]
    if reason:
        fields.append({"name": "Reason", "value": reason[:200], "inline": False})

    embed = {
        "title": "⏳ Approval Required",
        "color": 0xFFAB00,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="approval_required")


async def discord_trade_closed(
    symbol: str,
    action: str,
    pnl: float,
    reason: str = "",
    daily_pnl: float | None = None,
) -> bool:
    """Send a trade closed alert."""
    is_win = pnl >= 0
    color = 0x00C853 if is_win else 0xD50000
    sign = "+" if pnl >= 0 else ""
    result_word = "WIN" if is_win else "LOSS"

    fields = [
        {"name": "Symbol", "value": symbol.upper(), "inline": True},
        {"name": "Direction", "value": action.upper(), "inline": True},
        {"name": "P&L", "value": f"{sign}${pnl:.2f} ({result_word})", "inline": True},
    ]
    if daily_pnl is not None:
        daily_sign = "+" if daily_pnl >= 0 else ""
        fields.append({"name": "Daily Total", "value": f"{daily_sign}${daily_pnl:.2f}", "inline": True})
    if reason:
        fields.append({"name": "Reason", "value": reason[:200], "inline": False})

    embed = {
        "title": "🏁 Trade Closed",
        "color": color,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="trade_closed")


async def discord_trade_opened(
    symbol: str,
    action: str,
    quantity: float,
    entry_price: float,
) -> bool:
    """Send a trade opened alert."""
    is_long = action.upper() in ("BUY", "LONG")
    color = 0x00C853 if is_long else 0xD50000

    embed = {
        "title": "🚀 Trade Opened",
        "color": color,
        "fields": [
            {"name": "Symbol", "value": symbol.upper(), "inline": True},
            {"name": "Direction", "value": action.upper(), "inline": True},
            {"name": "Qty", "value": str(int(quantity)), "inline": True},
            {"name": "Entry", "value": f"${entry_price:.2f}", "inline": True},
        ],
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="trade_opened")


async def discord_target(
    market: str,
    pnl: float,
    target: float,
) -> bool:
    """Send a daily target hit alert."""
    embed = {
        "title": "🎯 Daily Target Hit",
        "color": 0x7C4DFF,
        "fields": [
            {"name": "Market", "value": market.upper(), "inline": True},
            {"name": "P&L", "value": f"+${pnl:.2f}", "inline": True},
            {"name": "Target", "value": f"${target:.2f}", "inline": True},
        ],
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="target")


async def discord_ib_disconnect(last_connected_at: str = "") -> bool:
    """Send an IB disconnect alert."""
    fields = []
    if last_connected_at:
        fields.append({"name": "Last Connected", "value": last_connected_at, "inline": True})

    embed = {
        "title": "⚠️ IB Gateway Disconnected",
        "description": "IBKR disconnected during market hours. Restart IB Gateway.",
        "color": 0xFF6D00,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="ib_disconnect")


async def discord_regime_change(
    symbol: str,
    old_regime: str,
    new_regime: str,
) -> bool:
    """Send a regime change alert."""
    embed = {
        "title": "📈 Regime Change",
        "color": 0x2979FF,
        "fields": [
            {"name": "Symbol", "value": symbol.upper(), "inline": True},
            {"name": "Previous", "value": old_regime, "inline": True},
            {"name": "New", "value": new_regime, "inline": True},
        ],
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="regime_change")


async def discord_morning_brief(brief_text: str) -> bool:
    """Send morning intelligence brief as a rich embed."""
    lines = brief_text.strip().splitlines()
    title = lines[0].strip() if lines else "Morning Intelligence Brief"
    description = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    embed = {
        "title": title[:256],
        "description": description[:4000] if description else None,
        "color": 0x2979FF,
        "footer": {"text": "JARVIS Morning Intelligence"},
        "timestamp": _iso_ts(),
    }
    # Remove None values
    embed = {k: v for k, v in embed.items() if v is not None}
    return await _send_embed(embed, alert_type="morning_brief")


async def discord_validation_alert(
    gate_name: str,
    old_status: str,
    new_status: str,
    current_value: float,
    target_value: float,
) -> bool:
    """Send a validation gate status change alert."""
    is_pass = new_status == "PASS"
    color = 0x00C853 if is_pass else 0xFFAB00
    status_label = "✅ PASS" if is_pass else "⚠️ FAIL"

    embed = {
        "title": f"Validation Gate: {gate_name.replace('_', ' ').title()}",
        "color": color,
        "fields": [
            {"name": "Status", "value": f"{old_status} → {status_label}", "inline": True},
            {"name": "Value", "value": f"{current_value:.2f}", "inline": True},
            {"name": "Target", "value": f"{target_value:.2f}", "inline": True},
        ],
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="validation_alert")


async def discord_eod_summary(
    total_trades: int,
    wins: int,
    losses: int,
    daily_pnl: float,
    best_trade_pnl: float = 0.0,
    worst_trade_pnl: float = 0.0,
    regime_state: str = "",
) -> bool:
    """Send end-of-day summary embed."""
    is_positive = daily_pnl >= 0
    color = 0x00C853 if is_positive else 0xD50000
    pnl_sign = "+" if is_positive else ""
    win_rate = int(wins / total_trades * 100) if total_trades > 0 else 0

    fields = [
        {"name": "Daily P&L", "value": f"{pnl_sign}${daily_pnl:.2f}", "inline": True},
        {"name": "Trades", "value": str(total_trades), "inline": True},
        {"name": "Win Rate", "value": f"{win_rate}%", "inline": True},
        {"name": "Wins", "value": str(wins), "inline": True},
        {"name": "Losses", "value": str(losses), "inline": True},
    ]
    if best_trade_pnl != 0.0:
        fields.append({"name": "Best Trade", "value": f"+${best_trade_pnl:.2f}", "inline": True})
    if worst_trade_pnl != 0.0:
        fields.append({"name": "Worst Trade", "value": f"-${abs(worst_trade_pnl):.2f}", "inline": True})
    if regime_state:
        fields.append({"name": "Regime", "value": regime_state, "inline": True})

    embed = {
        "title": "📋 End-of-Day Summary",
        "color": color,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="eod_summary")


async def discord_test() -> bool:
    """Send a test embed. Used for setup verification only."""
    embed = {
        "title": "🤖 JARVIS Discord Connected",
        "description": "Alert routing is live.",
        "color": 0x2979FF,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="test")


async def discord_mes_forward_outcome(
    date_str: str,
    side: str,
    reason: str,
    open_price: float | None,
    close_price: float | None,
    outcome_delta: float | None,
) -> bool:
    """Send the daily MES forward-recorder outcome as a rich embed.

    Called by the 15:15 CT outcome job so each accumulated row is visible
    same-day without opening the dashboard. Green if the hypothesis was
    profitable, red if it lost, neutral grey for skip days.
    """
    # Colour key:
    #   long/short with positive delta  → green
    #   long/short with negative delta  → red
    #   skip OR missing outcome         → grey
    if outcome_delta is not None and side in ("long", "short"):
        color = 0x00C853 if outcome_delta > 0 else 0xD50000
        hit_icon = "✅" if outcome_delta > 0 else "❌"
    else:
        color = 0x607D8B
        hit_icon = "⏸"

    delta_str = (
        f"{outcome_delta:+.2f} pts"
        if outcome_delta is not None
        else "—"
    )
    open_str = f"{open_price:.2f}" if open_price is not None else "—"
    close_str = f"{close_price:.2f}" if close_price is not None else "—"

    fields = [
        {"name": "Date", "value": date_str, "inline": True},
        {"name": "Side", "value": side.upper(), "inline": True},
        {"name": "Result", "value": f"{hit_icon} {delta_str}", "inline": True},
        {"name": "Open", "value": open_str, "inline": True},
        {"name": "Close", "value": close_str, "inline": True},
        {"name": "Reason", "value": reason[:200] if reason else "—", "inline": False},
    ]

    embed = {
        "title": "🧪 MES Forward-Recorder",
        "description": (
            "Observational experiment — *no position was taken.* "
            "Evaluated after ~8–12 weeks of accumulated rows."
        ),
        "color": color,
        "fields": fields,
        "footer": _footer(),
        "timestamp": _iso_ts(),
    }
    return await _send_embed(embed, alert_type="mes_forward_outcome")
