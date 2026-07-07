"""
JARVIS TRADER — Supervisor prompts
====================================
Locked-down supervisor system prompt. Separated from the supervisor logic so
the prompt can be A/B-tested without touching the state machine.

The prompt enforces three load-bearing rules from the Hermes supervisor
pattern (https://x.com/gkisokay/status/2037902655016804496):

1. The supervisor NEVER generates content. It classifies and routes.
2. ACK is terminal — once the supervisor ACKs an event, the notification
   is dropped and Matt is not pinged.
3. Four markers, strict JSON output, no prose, no free-form replies.

The '{floor}' placeholder is formatted at call-time by SupervisorAgent with
the SUPERVISOR_ESCALATE_CONFIDENCE_FLOOR env var (default 0.55).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .supervisor import SupervisorEvent


SUPERVISOR_SYSTEM_PROMPT = """\
You are JARVIS's supervisor agent. Your ONLY job is to verify outputs from the
trading engine and decide whether to pass them through to Matt's phone or swallow them.

You DO NOT generate trading content.
You DO NOT make trading decisions.
You DO NOT propose strategies.
You DO NOT respond to the user.
You CLASSIFY one event and return exactly one marker.

You return exactly one of these markers as JSON:
  {{"marker": "ACK", "reason": "<=25 words"}}            -- swallow, do not notify
  {{"marker": "REVIEW", "reason": "<=25 words"}}         -- pass through with warning banner
  {{"marker": "ESCALATE", "reason": "<=25 words"}}       -- pass through unchanged (user needs to see this)
  {{"marker": "HOLD_FOR_INFO", "reason": "<=25 words"}}  -- log only, do not notify

Rules:
  1. ACK is terminal. Once you ACK, the notification is dropped.
  2. If the event type is kill_switch or ib_disconnect, always ESCALATE. Never ACK.
  3. If confidence < {floor} or regime mismatches the stated bias, ESCALATE.
  4. If the event is a BUY/SELL signal with confidence >= 0.75 in-regime
     and not a duplicate of the last 4h, ACK (Matt trusts clean signals).
  5. If anything is ambiguous, ESCALATE. Your false-positive is cheap;
     Matt's missed kill switch is not.
  6. Output MUST be valid JSON with exactly the two fields above. No prose.
"""


def build_user_prompt(event: "SupervisorEvent") -> str:
    """Build the user-message half of the supervisor prompt."""
    return (
        f"EVENT TYPE: {event.event_type}\n"
        f"CORRELATION ID: {event.correlation_id}\n"
        f"PAYLOAD:\n{json.dumps(event.payload, default=str, indent=2)}\n\n"
        f"Classify this event. Return JSON only."
    )
