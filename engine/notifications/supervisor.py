"""
JARVIS TRADER — SupervisorAgent (Hermes pattern adaptation)
==============================================================
In-process Python supervisor that gates openclaw_notifier outputs with
Claude Sonnet classification. Reduces daily alert noise by ACK'ing clean
events and only escalating events that need Matt's judgment.

Pattern source
--------------
Graeme (@gkisokay), "The Setup That Saved Me Hours Every Day: OpenClaw + Hermes"
https://x.com/gkisokay/status/2037902655016804496

The load-bearing ideas from the tweet:
  1. A supervisor role that NEVER generates content — only verifies and routes.
  2. A marker state machine with ACK as a terminal state (provably bounds the loop).
  3. Cognitive offload — Matt only sees events that need judgment.

JARVIS adaptation
-----------------
The tweet runs Hermes as a second Discord bot with an inter-agent channel. JARVIS
already has JarvisLLMClient, TokenProxy, and AdvisorClient primitives, so we keep
the load-bearing ideas (markers, ACK-terminal, role separation) and swap the
transport: the supervisor is a single in-process class that wraps notify_*()
calls synchronously, with sub-100ms latency and a single env var kill switch.

Plan: C:/Users/mattm/.claude/plans/bubbly-tickling-dolphin.md

API contract
------------
  SupervisorMarker       enum: ACK | REVIEW | ESCALATE | HOLD_FOR_INFO
  SupervisorEvent        event_type, payload, correlation_id, ts
  SupervisorDecision     marker, reason, pass_through, event, latency_ms, cost_usd
  SupervisorAgent.review(event)            -> async SupervisorDecision
  SupervisorAgent.scan_cron_jobs(path)     -> async list[SupervisorDecision]
  SupervisorAgent.stats()                  -> dict
  get_supervisor()                         -> SupervisorAgent (singleton)
  reset_supervisor()                       -> None (test hook)

Reliability
-----------
  * Fail-open ESCALATE on any exception (never swallow on error).
  * kill_switch and ib_disconnect bypass the LLM entirely (always ESCALATE).
  * Env var SUPERVISOR_ENABLED=false degrades the whole module to no-op.
  * _record() errors are swallowed (decision log failure never breaks notify).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env var defaults — read at module load, overridable via __init__ params
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    val = (os.getenv(name) or "").strip().lower()
    if not val:
        return default
    return val in ("true", "1", "yes", "on")


_DEFAULT_ENABLED = _env_bool("SUPERVISOR_ENABLED", default=False)
_DEFAULT_MODEL = os.getenv("SUPERVISOR_MODEL", "claude-sonnet-4-6")
try:
    _DEFAULT_TIMEOUT = float(os.getenv("SUPERVISOR_LLM_TIMEOUT_SECONDS", "3.0"))
except ValueError:
    _DEFAULT_TIMEOUT = 3.0
try:
    _DEFAULT_CONFIDENCE_FLOOR = float(os.getenv("SUPERVISOR_ESCALATE_CONFIDENCE_FLOOR", "0.55"))
except ValueError:
    _DEFAULT_CONFIDENCE_FLOOR = 0.55


# ---------------------------------------------------------------------------
# Marker enum + dataclasses
# ---------------------------------------------------------------------------


class SupervisorMarker(str, Enum):
    """Four-marker state machine (Hermes protocol)."""

    ACK = "ACK"                  # terminal — notification swallowed
    REVIEW = "REVIEW"            # pass-through with warning banner
    ESCALATE = "ESCALATE"        # pass-through unchanged (user needs to see this)
    HOLD_FOR_INFO = "HOLD_FOR_INFO"  # log only, do not notify


@dataclass
class SupervisorEvent:
    """A notifier event to classify."""

    event_type: str
    payload: Dict[str, Any]
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)


@dataclass
class SupervisorDecision:
    """The supervisor's verdict on a single event."""

    marker: SupervisorMarker
    reason: str
    pass_through: bool
    event: SupervisorEvent
    latency_ms: int
    cost_usd: float = 0.0


# ---------------------------------------------------------------------------
# SupervisorAgent
# ---------------------------------------------------------------------------


class SupervisorAgent:
    """
    In-process supervisor that classifies notifier events as ACK/REVIEW/
    ESCALATE/HOLD_FOR_INFO via Claude Sonnet, and decides whether to let
    the notification fire or swallow it.

    Always-escalate events (kill_switch, ib_disconnect) bypass the LLM
    entirely — they are safety-critical and must never be swallowed.
    """

    # Events that are NEVER ACK'd — pass through regardless of LLM verdict.
    ALWAYS_ESCALATE_EVENTS: frozenset = frozenset({"kill_switch", "ib_disconnect"})

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        db_path: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
        confidence_floor: float = _DEFAULT_CONFIDENCE_FLOOR,
        enabled: Optional[bool] = None,
    ):
        """
        Args:
            llm_client: Optional JarvisLLMClient. If None, lazy-loads one
                from ANTHROPIC_API_KEY; if that fails, supervisor fails-open.
            db_path:    Path to the sqlite decision log. Relative paths are
                resolved against the engine root (matches DatabaseManager).
            model:      Model id passed to llm_client.call().
            timeout_seconds: Hard wall-clock cap on a single review() call.
            confidence_floor: Used in the system prompt {floor} placeholder.
            enabled:    Explicit override for the SUPERVISOR_ENABLED env var.
                Set True in tests to force-enable without mutating env.
        """
        self.llm = llm_client if llm_client is not None else self._try_lazy_load_llm()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.confidence_floor = confidence_floor
        self._enabled_override: Optional[bool] = enabled
        self._db_path = self._resolve_db_path(db_path)
        self._stats: Dict[str, Any] = {
            "total": 0,
            "ack": 0,
            "review": 0,
            "escalate": 0,
            "hold": 0,
            "errors": 0,
        }

    # -- Construction helpers -------------------------------------------------

    @staticmethod
    def _resolve_db_path(db_path: Optional[str]) -> Path:
        """Mirror DatabaseManager's path resolution (engine_root/data/jarvis_trader.db)."""
        if db_path:
            p = Path(db_path)
            if p.is_absolute():
                return p
            # relative to engine/ root (this file lives in engine/notifications/)
            return Path(__file__).parent.parent / db_path
        return Path(__file__).parent.parent / "data" / "jarvis_trader.db"

    @staticmethod
    def _try_lazy_load_llm() -> Optional[Any]:
        """Attempt to construct a JarvisLLMClient. Never raises."""
        try:
            from llm.client import JarvisLLMClient  # type: ignore
        except Exception:
            try:
                from engine.llm.client import JarvisLLMClient  # type: ignore
            except Exception as e:
                logger.info(
                    "SupervisorAgent: JarvisLLMClient not importable (%s); "
                    "supervisor will fail-open.",
                    e,
                )
                return None

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.info(
                "SupervisorAgent: ANTHROPIC_API_KEY not set; supervisor will fail-open."
            )
            return None

        try:
            return JarvisLLMClient(api_key=api_key)
        except Exception as e:
            logger.warning(
                "SupervisorAgent: failed to construct JarvisLLMClient (%s); "
                "supervisor will fail-open.",
                e,
            )
            return None

    # -- Public properties ---------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True if the supervisor should actively gate notifications."""
        if self._enabled_override is not None:
            return self._enabled_override
        return _env_bool("SUPERVISOR_ENABLED", default=False)

    def is_available(self) -> bool:
        """Whether the supervisor has a working LLM client."""
        return self.llm is not None

    # -- Core classification -------------------------------------------------

    async def review(self, event: SupervisorEvent) -> SupervisorDecision:
        """
        Review a notifier event and return a SupervisorDecision.

        Rules:
          1. Always-escalate events (kill_switch, ib_disconnect) bypass the
             LLM entirely and always pass through.
          2. If the supervisor is disabled or has no LLM, fail-open ESCALATE.
          3. Otherwise call the LLM with a hard timeout. On any error, fail
             open with reason="llm_error: {ExcType}".
          4. Parse the LLM's JSON response. On invalid output, fail-open.
          5. Record every decision to the supervisor_decisions table.
        """
        started = time.time()
        self._stats["total"] += 1

        # Rule 1 — always-escalate events bypass the LLM entirely.
        if event.event_type in self.ALWAYS_ESCALATE_EVENTS:
            decision = SupervisorDecision(
                marker=SupervisorMarker.ESCALATE,
                reason=f"always-escalate event type: {event.event_type}",
                pass_through=True,
                event=event,
                latency_ms=int((time.time() - started) * 1000),
            )
            self._stats["escalate"] += 1
            self._record(decision)
            return decision

        # Rule 2 — disabled or no LLM: fail-open ESCALATE.
        if not self.enabled or self.llm is None:
            decision = SupervisorDecision(
                marker=SupervisorMarker.ESCALATE,
                reason="supervisor disabled or LLM unavailable",
                pass_through=True,
                event=event,
                latency_ms=int((time.time() - started) * 1000),
            )
            self._stats["escalate"] += 1
            self._record(decision)
            return decision

        # Rule 3 — LLM classification with hard timeout.
        try:
            from .supervisor_prompts import SUPERVISOR_SYSTEM_PROMPT, build_user_prompt

            system = SUPERVISOR_SYSTEM_PROMPT.format(floor=self.confidence_floor)
            user = build_user_prompt(event)
            result = await asyncio.wait_for(
                self.llm.call(
                    model=self.model,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    max_tokens=120,
                    agent_name="supervisor",
                    temperature=0.1,
                    allow_fallback=True,
                ),
                timeout=self.timeout_seconds,
            )
            if not getattr(result, "success", False):
                raise RuntimeError(f"LLM call failed: {getattr(result, 'error', 'unknown')}")
            marker, reason = self._parse_marker(result.content)
            cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
        except Exception as exc:
            logger.warning(
                "Supervisor LLM review failed (fail-open ESCALATE): %s", exc
            )
            self._stats["errors"] += 1
            decision = SupervisorDecision(
                marker=SupervisorMarker.ESCALATE,
                reason=f"llm_error: {type(exc).__name__}",
                pass_through=True,
                event=event,
                latency_ms=int((time.time() - started) * 1000),
            )
            self._stats["escalate"] += 1
            self._record(decision)
            return decision

        # Rule 5 — record and return.
        pass_through = marker not in (SupervisorMarker.ACK, SupervisorMarker.HOLD_FOR_INFO)
        decision = SupervisorDecision(
            marker=marker,
            reason=reason,
            pass_through=pass_through,
            event=event,
            latency_ms=int((time.time() - started) * 1000),
            cost_usd=cost,
        )
        self._bump_marker_stat(marker)
        self._record(decision)
        return decision

    def _bump_marker_stat(self, marker: SupervisorMarker) -> None:
        key_map = {
            SupervisorMarker.ACK: "ack",
            SupervisorMarker.REVIEW: "review",
            SupervisorMarker.ESCALATE: "escalate",
            SupervisorMarker.HOLD_FOR_INFO: "hold",
        }
        self._stats[key_map[marker]] += 1

    # -- Marker parser -------------------------------------------------------

    @staticmethod
    def _parse_marker(content: str) -> tuple[SupervisorMarker, str]:
        """
        Parse a JSON marker response from the LLM. Raises ValueError on any
        invalid input so review() can catch and fail-open.
        """
        text = (content or "").strip()

        # Strip ```json ... ``` code fences if present.
        if text.startswith("```"):
            # Remove leading/trailing fence lines.
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        data: Any
        try:
            data = json.loads(text)
        except Exception as exc:
            # Try to extract the first {...} substring.
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(text[start : end + 1])
            else:
                raise ValueError(f"non-JSON supervisor response: {text[:120]!r}") from exc

        if not isinstance(data, dict) or "marker" not in data:
            raise ValueError(f"missing 'marker' field in response: {str(data)[:120]}")

        raw_marker = str(data["marker"]).strip().upper()
        try:
            marker = SupervisorMarker(raw_marker)
        except ValueError as exc:
            raise ValueError(f"invalid marker value: {raw_marker!r}") from exc

        reason = str(data.get("reason", "")).strip()[:200]
        return marker, reason

    # -- DB recording --------------------------------------------------------

    def _record(self, decision: SupervisorDecision) -> None:
        """
        Persist a decision to the supervisor_decisions table. Never raises —
        a failure here must never break the notification path.
        """
        try:
            ts_iso = datetime.fromtimestamp(decision.event.ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            payload_json = json.dumps(decision.event.payload, default=str)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=5)
            try:
                conn.execute(
                    """
                    INSERT INTO supervisor_decisions (
                        ts, event_type, marker, reason, payload_json,
                        latency_ms, pass_through, correlation_id, cost_usd
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts_iso,
                        decision.event.event_type,
                        decision.marker.value,
                        decision.reason,
                        payload_json,
                        decision.latency_ms,
                        1 if decision.pass_through else 0,
                        decision.event.correlation_id,
                        decision.cost_usd,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Supervisor _record failed (non-fatal): %s", exc)

    # -- Stats ---------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return noise-reduction metrics for the /supervisor/stats endpoint."""
        total = max(1, self._stats["total"])
        return {
            **self._stats,
            "ack_rate": self._stats["ack"] / total,
            "escalate_rate": self._stats["escalate"] / total,
            "noise_reduction_pct": (self._stats["ack"] + self._stats["hold"]) / total,
            "enabled": self.enabled,
            "available": self.is_available(),
            "model": self.model,
            "confidence_floor": self.confidence_floor,
            "timeout_seconds": self.timeout_seconds,
        }

    # -- Cron watcher --------------------------------------------------------

    async def scan_cron_jobs(
        self,
        jobs_json_path: str = "/root/.openclaw/cron/jobs.json",
    ) -> List[SupervisorDecision]:
        """
        Poll the OpenClaw cron jobs.json (via WSL) and escalate any job with
        consecutiveFailures >= 2 AND a non-empty lastError. Mirrors the
        tweet's canonical "stale signal" escalation example.

        Returns the list of escalation decisions (empty on no failures or
        parse errors).
        """
        decisions: List[SupervisorDecision] = []

        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "-u", "root", "-e", "cat", jobs_json_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.debug(
                    "Cron scan: wsl cat failed rc=%s stderr=%s",
                    result.returncode,
                    (result.stderr or "")[:120],
                )
                return decisions
            data = json.loads(result.stdout)
        except Exception as exc:
            logger.debug("Cron scan failed (non-fatal): %s", exc)
            return decisions

        jobs = data.get("jobs") if isinstance(data, dict) else data
        if not isinstance(jobs, list):
            return decisions

        for job in jobs:
            if not isinstance(job, dict):
                continue
            state = job.get("state") or {}
            if not isinstance(state, dict):
                continue
            consecutive = int(
                state.get("consecutiveFailures")
                or state.get("consecutive_failures")
                or 0
            )
            last_error = state.get("lastError") or state.get("last_error")
            if consecutive >= 2 and last_error:
                job_name = job.get("name") or job.get("id") or "unknown"
                event = SupervisorEvent(
                    event_type="cron_failure",
                    payload={
                        "job_name": job_name,
                        "schedule": job.get("schedule"),
                        "consecutive_failures": consecutive,
                        "last_error": str(last_error)[:200],
                    },
                )
                decision = SupervisorDecision(
                    marker=SupervisorMarker.ESCALATE,
                    reason=(
                        f"cron job {job_name} failed {consecutive}x: "
                        f"{str(last_error)[:80]}"
                    ),
                    pass_through=True,
                    event=event,
                    latency_ms=0,
                )
                self._stats["total"] += 1
                self._stats["escalate"] += 1
                self._record(decision)
                decisions.append(decision)

                # Fire the escalation via the existing notifier.
                try:
                    from .openclaw_notifier import send_raw

                    msg = (
                        f"JARVIS SUPERVISOR — cron failure\n"
                        f"Job: {job_name}\n"
                        f"Consecutive failures: {consecutive}\n"
                        f"Last error: {str(last_error)[:120]}"
                    )
                    await send_raw(msg)
                except Exception as send_exc:
                    logger.warning(
                        "Cron escalation send_raw failed (non-fatal): %s", send_exc
                    )

        return decisions


# ---------------------------------------------------------------------------
# Singleton accessors
# ---------------------------------------------------------------------------


_instance: Optional[SupervisorAgent] = None


def get_supervisor() -> SupervisorAgent:
    """Lazily construct and return the module-level SupervisorAgent singleton."""
    global _instance
    if _instance is None:
        _instance = SupervisorAgent()
    return _instance


def reset_supervisor() -> None:
    """Clear the singleton. Test hook — do not call in production."""
    global _instance
    _instance = None
