"""
JARVIS TRADER — Discord Webhook: Autonomous Approval Queue
==========================================================

Sends rich Discord embeds when candidates enter or leave the autonomous
pipeline approval queue.

Design constraints:
  - Default-OFF: no-op unless JARVIS_DISCORD_APPROVAL_WEBHOOK is set.
  - Best-effort: any failure is logged as WARNING; callers are never blocked.
  - No order-path changes: this is observability only.
  - 5-second timeout per call; uses aiohttp-free httpx (already a dep).

Environment:
  JARVIS_DISCORD_APPROVAL_WEBHOOK   — full Discord webhook URL (required to send)
  DASHBOARD_PUBLIC_URL              — base URL for "approve via engine" hints (default http://localhost:3010)
  JARVIS_ENGINE_PUBLIC_URL          — engine API base URL for curl snippets (default http://127.0.0.1:8010)

Usage:
  from notifications.discord_webhook import post_approval_candidate, post_approval_result
  asyncio.create_task(post_approval_candidate(candidate_dict))
  asyncio.create_task(post_approval_result(17, "approved", order_id="INV-123"))

Rate limit note: Discord webhooks are limited to ~30 requests/min per channel.
The autonomous tick is 300 s (5 min) by default, so even with 4 symbols this
posts at most 4 messages per tick — well inside the limit.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac_module
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_ENV = "JARVIS_DISCORD_APPROVAL_WEBHOOK"
_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _webhook_url() -> str:
    """Read the webhook URL from env fresh on every call (never cached)."""
    return (os.environ.get(_WEBHOOK_ENV) or "").strip()


def _engine_url() -> str:
    raw = (os.environ.get("JARVIS_ENGINE_PUBLIC_URL") or "").strip()
    return raw or "http://127.0.0.1:8010"


def _dashboard_url() -> str:
    try:
        from config import settings as _cfg

        base = (getattr(_cfg, "DASHBOARD_PUBLIC_URL", None) or "").strip()
    except Exception:
        base = ""
    if not base:
        base = (os.environ.get("DASHBOARD_PUBLIC_URL") or "http://localhost:3010").strip()
    return base.rstrip("/")


def _iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _footer() -> dict:
    return {"text": "JARVIS Autonomous Pipeline"}


# ---------------------------------------------------------------------------
# HMAC helpers — §6.2 forged-reaction protection
# ---------------------------------------------------------------------------


def _hmac_key() -> bytes | None:
    """Return the signing key bytes from JARVIS_APPROVAL_HMAC_KEY, or None if not set."""
    raw = os.environ.get("JARVIS_APPROVAL_HMAC_KEY", "").strip()
    return raw.encode() if raw else None


def _sign_candidate_id(candidate_id: int) -> str | None:
    """Return a 16-char HMAC-SHA256 hex token for the given candidate ID, or None if key absent."""
    key = _hmac_key()
    if key is None:
        return None
    return _hmac_module.new(key, str(candidate_id).encode(), hashlib.sha256).hexdigest()[:16]


async def _post(embed: dict, content: str = "") -> None:
    """POST a single rich embed to the approval webhook. Silently no-ops if not configured."""
    url = _webhook_url()
    if not url:
        logger.debug("[discord_webhook] JARVIS_DISCORD_APPROVAL_WEBHOOK not set — skipping")
        return

    payload: dict = {"username": "JARVIS", "embeds": [embed]}
    if content:
        payload["content"] = content
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "[discord_webhook] webhook returned HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
    except Exception as exc:
        logger.warning("[discord_webhook] post failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Public notification functions
# ---------------------------------------------------------------------------


async def post_approval_candidate(candidate: dict) -> None:
    """
    Post a rich embed for a newly enqueued approval candidate.

    candidate dict must have at minimum: id, symbol, direction, confidence,
    expires_at. Extra keys (verdict_json, entry_price, stop, targets) are
    surfaced when present.

    Safe to fire-and-forget via asyncio.create_task().
    """
    url = _webhook_url()
    if not url:
        return

    try:
        candidate_id = int(candidate.get("id") or candidate.get("candidate_id") or 0)
        symbol = str(candidate.get("symbol") or "?").upper()
        direction = str(candidate.get("direction") or "?").upper()
        confidence = float(candidate.get("confidence") or 0.0)
        expires_at = str(candidate.get("expires_at") or "")
        ttl_seconds = int(candidate.get("ttl_seconds") or 1800)

        # Best-effort: extract prices from verdict_json or top-level keys
        entry_price: Optional[float] = None
        stop_price: Optional[float] = None
        t1_price: Optional[float] = None
        t2_price: Optional[float] = None

        # Try top-level price keys first (scheduler injects these when available)
        for k in ("entry_price", "limit_price"):
            if candidate.get(k) is not None:
                try:
                    entry_price = float(candidate[k])
                except (TypeError, ValueError):
                    pass
                break

        verdict = candidate.get("verdict") or {}
        if not verdict and candidate.get("verdict_json"):
            import json

            try:
                verdict = json.loads(candidate["verdict_json"])
            except Exception:
                verdict = {}

        if verdict:
            trade_dec = verdict.get("trade_decision") or {}
            if entry_price is None:
                for k in ("entry_price", "limit_price", "stop_price"):
                    raw = trade_dec.get(k)
                    if raw is not None:
                        try:
                            entry_price = float(raw)
                        except (TypeError, ValueError):
                            pass
                        break
            raw_stop = trade_dec.get("stop_loss") or trade_dec.get("stop_price")
            if raw_stop is not None:
                try:
                    stop_price = float(raw_stop)
                except (TypeError, ValueError):
                    pass
            targets = trade_dec.get("targets") or []
            if len(targets) >= 1:
                try:
                    t1_price = float(targets[0])
                except (TypeError, ValueError):
                    pass
            if len(targets) >= 2:
                try:
                    t2_price = float(targets[1])
                except (TypeError, ValueError):
                    pass

        # Colour: LONG = green, SHORT = red
        is_long = direction in ("LONG", "BUY")
        color = 0x00C853 if is_long else 0xD50000

        # TTL display: convert expires_at to "X min TTL" if parseable
        ttl_display = f"{ttl_seconds // 60} min TTL"
        try:
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            remaining = int((exp_dt - now_dt).total_seconds())
            ttl_display = f"{max(0, remaining) // 60} min remaining"
        except Exception:
            pass

        # Build fields
        fields: list[dict] = [
            {"name": "Symbol", "value": symbol, "inline": True},
            {"name": "Direction", "value": direction, "inline": True},
            {"name": "Confidence", "value": f"{confidence:.0%}", "inline": True},
        ]
        if entry_price is not None:
            fields.append({"name": "Entry", "value": f"${entry_price:.2f}", "inline": True})
        if stop_price is not None:
            fields.append({"name": "Stop", "value": f"${stop_price:.2f}", "inline": True})
        if t1_price is not None:
            fields.append({"name": "T1", "value": f"${t1_price:.2f}", "inline": True})
        if t2_price is not None:
            fields.append({"name": "T2", "value": f"${t2_price:.2f}", "inline": True})
        fields.append({"name": "Expires", "value": ttl_display, "inline": True})

        # Action hints
        engine = _engine_url()
        hermes_hint = f'`jarvis-approval-queue "approve {candidate_id}"`'
        curl_hint = (
            f'`curl -X POST "{engine}/approvals/{candidate_id}/approve"`\n'
            f'  `-H "X-API-Key: <key>"`'
        )
        fields.append(
            {
                "name": "Approve via API",
                "value": curl_hint[:512],
                "inline": False,
            }
        )
        fields.append(
            {
                "name": "Approve via Hermes",
                "value": hermes_hint,
                "inline": False,
            }
        )

        embed = {
            "title": f"New trade candidate (ID {candidate_id})",
            "description": (
                "Reaction guide: approve via Hermes or curl below. "
                "Candidate expires automatically when TTL hits zero."
            ),
            "color": color,
            "fields": fields,
            "footer": _footer(),
            "timestamp": _iso_ts(),
        }
        hmac_token = _sign_candidate_id(candidate_id)
        content_str = f"approval candidate (ID {candidate_id})"
        if hmac_token:
            content_str += f" | auth:{hmac_token}"
        await _post(embed, content=content_str)

    except Exception as exc:
        logger.warning("[discord_webhook] post_approval_candidate failed (non-fatal): %s", exc)


async def post_approval_result(
    candidate_id: int,
    action: str,
    order_id: Optional[str] = None,
    notes: str = "",
    symbol: str = "",
    direction: str = "",
) -> None:
    """
    Post the resolution of an approval candidate: approved, rejected, or expired.

    action: one of "approved", "rejected", "expired"
    order_id: IB fill/order ID (approved path only)
    notes: rejection reason or expiry context
    symbol / direction: optional — surfaced when provided for quick scan

    Safe to fire-and-forget via asyncio.create_task().
    """
    url = _webhook_url()
    if not url:
        return

    try:
        action_lower = (action or "").lower()

        if action_lower == "approved":
            color = 0x00C853
            title = f"Approved — candidate {candidate_id}"
            icon = "Approved"
        elif action_lower == "rejected":
            color = 0xD50000
            title = f"Rejected — candidate {candidate_id}"
            icon = "Rejected"
        else:
            color = 0x607D8B
            title = f"Expired — candidate {candidate_id}"
            icon = "Expired (TTL)"

        fields: list[dict] = []
        if symbol:
            fields.append({"name": "Symbol", "value": symbol.upper(), "inline": True})
        if direction:
            fields.append({"name": "Direction", "value": direction.upper(), "inline": True})
        if order_id:
            fields.append({"name": "Order ID", "value": order_id, "inline": True})
        if notes:
            fields.append({"name": "Notes", "value": notes[:500], "inline": False})

        embed = {
            "title": title,
            "description": icon,
            "color": color,
            "fields": fields,
            "footer": _footer(),
            "timestamp": _iso_ts(),
        }
        await _post(embed)

    except Exception as exc:
        logger.warning("[discord_webhook] post_approval_result failed (non-fatal): %s", exc)
