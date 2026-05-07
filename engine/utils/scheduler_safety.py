"""
JARVIS TRADER — Scheduler safety layer
======================================
Staggered scheduling, quiet-hours gating, and idempotent run-tracking for
APScheduler jobs.

Pattern source
--------------
Adapted from garrytan/gbrain (github.com/garrytan/gbrain) ``cron-scheduler``
skill. The load-bearing ideas we keep:

  1. **Deterministic stagger** — jobs that would otherwise fire on identical
     minute boundaries get per-job minute offsets derived from the job id,
     so 4 crons configured for ``:00`` don't thunder-herd the LLM/IB API.
  2. **Quiet-hours gate** — jobs tagged as ``respect_quiet_hours`` skip
     execution silently while the local clock falls inside a configured
     window (e.g. overnight maintenance, weekend market close). Non-tagged
     jobs (kill-switch, IB reconnect) still run.
  3. **Idempotent re-entry** — consecutive runs of the same job within a
     short debounce window collapse to a single execution. Defends against
     accidental double-registration and APScheduler misfire floods.

Why a wrapper, not a scheduler replacement
------------------------------------------
APScheduler is already wired into ``engine/main.py`` and the four
schedulers in ``engine/schedulers/``. Replacing it would be a 4-week rewrite
with no benefit. Instead this module provides:

  * ``StaggeredCronRunner`` — wraps an async callable with the three gates.
  * ``staggered_offset(job_id, spread_minutes)`` — deterministic jitter.
  * ``in_quiet_hours(now, start, end, tz)`` — quiet-hours predicate.

Callers wrap their job function with ``StaggeredCronRunner.wrap`` and then
register the wrapper with APScheduler as usual — the rest of the pipeline
is unchanged.

License
-------
gbrain is MIT. This port preserves the pattern, not the code; only the
naming and the three-gate structure carry across.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from datetime import time as dtime
from typing import Any, Awaitable, Callable, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python 3.9+ has zoneinfo
    ZoneInfo = None  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stagger helper
# ---------------------------------------------------------------------------


def staggered_offset(job_id: str, spread_minutes: int = 5) -> int:
    """Return a deterministic minute offset in ``[0, spread_minutes)``.

    Computed from the MD5 of ``job_id`` so the same job always gets the
    same offset — crashes and restarts don't reshuffle schedules.

    Args:
        job_id: APScheduler job identifier (e.g. ``"eod_snapshot"``).
        spread_minutes: Maximum stagger window in minutes. Default 5 — wide
            enough to break LLM/IB thundering herds, narrow enough that a
            job scheduled for ``20:05`` still runs in the 20:05–20:09 window.

    Returns:
        An integer minute offset ``0 <= offset < spread_minutes``.
    """
    if spread_minutes <= 0:
        return 0
    digest = hashlib.md5(job_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % spread_minutes


# ---------------------------------------------------------------------------
# Quiet-hours predicate
# ---------------------------------------------------------------------------


def in_quiet_hours(
    now: datetime,
    start: Optional[dtime],
    end: Optional[dtime],
    tz_name: str = "America/Chicago",
) -> bool:
    """Return True iff ``now`` is inside the ``[start, end)`` local window.

    Handles wrap-around across midnight (``start=22:00, end=06:00``). If
    either bound is ``None``, no quiet hours are in effect.
    """
    if start is None or end is None:
        return False
    if ZoneInfo is None:  # pragma: no cover
        local_now = now
    else:
        try:
            local_now = now.astimezone(ZoneInfo(tz_name))
        except Exception:
            local_now = now
    local_time = local_now.time()

    if start <= end:
        return start <= local_time < end
    # Wrap-around window (e.g. 22:00–06:00): inside if before end OR after start.
    return local_time >= start or local_time < end


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class _LastRun:
    """Tracks the most recent run of a job for idempotent debounce."""

    ts: float = 0.0
    result: Any = None


@dataclass
class StaggeredCronRunner:
    """Wrap an async job callable with stagger + quiet-hours + dedupe gates.

    Usage::

        runner = StaggeredCronRunner(
            job_id="eod_snapshot",
            respect_quiet_hours=False,
            dedupe_seconds=30,
        )
        scheduler.add_job(
            runner.wrap(my_async_fn),
            CronTrigger(..., minute=5 + runner.stagger_offset),
            id="eod_snapshot",
        )

    The runner is stateless at construction time — offsets and gates are
    pure functions of ``job_id``. The only mutable state is ``_last_run``
    used for dedupe; it lives on the runner instance, so construct one per
    registered job.
    """

    job_id: str
    respect_quiet_hours: bool = True
    quiet_start: Optional[dtime] = None  # e.g. time(22, 0)
    quiet_end: Optional[dtime] = None    # e.g. time(6, 0)
    quiet_tz: str = "America/Chicago"
    spread_minutes: int = 5
    dedupe_seconds: float = 10.0
    _last_run: _LastRun = field(default_factory=_LastRun)

    @property
    def stagger_offset(self) -> int:
        """Deterministic minute offset to add to the base cron schedule."""
        return staggered_offset(self.job_id, self.spread_minutes)

    def should_skip(self, now: Optional[datetime] = None) -> Optional[str]:
        """Return a skip reason, or ``None`` to proceed.

        Check order matches user intent:
          1. Quiet hours (only if the job opted in).
          2. Dedupe window (runs within ``dedupe_seconds`` of the last one).
        """
        now = now or datetime.now(timezone.utc)

        if self.respect_quiet_hours and in_quiet_hours(
            now, self.quiet_start, self.quiet_end, self.quiet_tz
        ):
            return "quiet_hours"

        elapsed = time.time() - self._last_run.ts
        if self._last_run.ts > 0 and elapsed < self.dedupe_seconds:
            return f"dedupe ({elapsed:.1f}s < {self.dedupe_seconds}s)"

        return None

    def wrap(
        self,
        fn: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        """Return a wrapped coroutine that applies the safety gates before calling ``fn``.

        The wrapper:
          - Checks ``should_skip``; logs + returns ``None`` on skip.
          - Records ``time.time()`` *before* calling ``fn`` so a long-running
            job still blocks a simultaneous re-entry during its own window.
          - Propagates exceptions (the caller/APScheduler handles error
            logging and next-fire-time rescheduling).
        """

        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            reason = self.should_skip()
            if reason is not None:
                logger.info(
                    "[scheduler_safety] skipping %s: %s", self.job_id, reason
                )
                return None
            self._last_run.ts = time.time()
            result = await fn(*args, **kwargs)
            self._last_run.result = result
            return result

        _wrapped.__name__ = getattr(fn, "__name__", "wrapped_job")
        _wrapped.__qualname__ = f"StaggeredCronRunner({self.job_id}).wrap.{_wrapped.__name__}"
        return _wrapped


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(raw: str) -> Optional[dtime]:
    """Parse ``"HH:MM"`` into a ``datetime.time``, or return ``None``."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        hh, mm = raw.split(":", 1)
        return dtime(hour=int(hh), minute=int(mm))
    except (ValueError, TypeError):
        logger.warning("[scheduler_safety] invalid HH:MM string: %r", raw)
        return None


def quiet_hours_from_env(
    start_var: str = "JARVIS_QUIET_HOURS_START",
    end_var: str = "JARVIS_QUIET_HOURS_END",
    tz_var: str = "JARVIS_QUIET_HOURS_TZ",
) -> tuple[Optional[dtime], Optional[dtime], str]:
    """Read quiet-hours config from env.

    Returns ``(start, end, tz_name)`` with defaults ``(None, None, "America/Chicago")``
    if the env vars are unset or malformed — "no quiet hours" is the safe
    default so nothing goes silent unexpectedly.
    """
    start = _parse_hhmm(os.getenv(start_var, ""))
    end = _parse_hhmm(os.getenv(end_var, ""))
    tz_name = os.getenv(tz_var, "America/Chicago").strip() or "America/Chicago"
    return start, end, tz_name
