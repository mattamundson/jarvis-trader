"""JARVIS TRADER — Write-time bar-quality gate.

Screens assembled OHLCV rows *before* they hit ``market_data_bars`` so the
contaminated-tick classes that produced fake backtest edges (the 2026-06-11
edge re-assessment) can never enter the table again:

* **Impossible bars** — non-positive or non-finite OHLC, or OHLC logic
  violations (high < low, high below open/close, low above open/close).
* **Range explosions** — a single bar whose high/low span is an absurd
  fraction of its own price (the MES ``+7489%`` fake prints).
* **Lone neighbour jumps** — one bar whose close deviates from *both* its
  time-neighbours by more than a threshold (an isolated bad tick), while a
  genuine trend/gap that carries forward is left alone.
* **Blocked sources** — feed tags that must never reach prod (``smoke_test``).

Design notes
------------
* This is a **per-bar** screen, deliberately *not* the aggregate 0–1
  :class:`~data.validation_rules.DataValidator` score: one bad tick in a
  500-bar batch barely moves an average, so a batch score cannot reject the
  exact row that is poison. ``DataValidator`` stays as the pipeline-level
  "should I run on this data" check; this gate is the storage guard.
* Thresholds are generous — they sit far above any real futures move so the
  false-positive rate against MES/MGC/MCL/MNQ is ~0, yet far below the
  contamination (74× jumps, 100%+ ranges) so every known bad class is caught.
* Shadow → enforce follows the house ``GATE_*`` convention
  (cf. ``GATE_V2_ENFORCE_SAMPLE_ADEQUACY``): env-gated, read at call time, a
  one-line ``.env`` flip with no code edit. Shadow (default) logs verdicts and
  writes everything; enforce drops the rejected rows.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import NamedTuple, Optional, Sequence

logger = logging.getLogger("jarvis_trader.bar_quality")

# Row tuple layout produced by bars_repository.save_bars():
#   (symbol, interval, ts_iso, open, high, low, close, volume, source, fetched_at)
_OPEN, _HIGH, _LOW, _CLOSE = 3, 4, 5, 6
_TS, _SOURCE = 2, 8

Row = Sequence[object]

# --- Thresholds (generous; env-overridable at call time) --------------------

#: Max intra-bar span (high-low)/low before a bar is an impossible "explosion".
#: Real liquid-futures bars span well under 10%; 0.50 leaves enormous headroom
#: while still rejecting the contamination class outright.
MAX_RANGE_FRAC: float = 0.50

#: Max |close-neighbour_close|/neighbour_close for a *lone* outlier. A bar must
#: jump from BOTH neighbours by this much to be rejected, so a real gap/trend
#: that persists is never touched. The MES fake prints were ~74×.
MAX_JUMP_FRAC: float = 0.50

#: Feed source tags that must never persist to prod.
BLOCKED_SOURCES: frozenset[str] = frozenset({"smoke_test"})

_TRUTHY = {"1", "true", "yes", "on"}


class BarReject(NamedTuple):
    """A rejected row with its original batch index and machine-readable reason."""

    index: int
    reason: str
    detail: str


def gate_enabled() -> bool:
    """Whether the gate runs at all (shadow or enforce). Default ON.

    ``BAR_QUALITY_GATE_ENABLED=0`` fully disables screening (logging included).
    """
    return os.getenv("BAR_QUALITY_GATE_ENABLED", "1").strip().lower() in _TRUTHY


def gate_enforced() -> bool:
    """Shadow → enforce switch. Default OFF (shadow: log, write everything).

    Set ``BAR_QUALITY_GATE_ENFORCE=1`` to drop rejected rows before insert.
    Evaluated at call time so it can be toggled without re-import.
    """
    return os.getenv("BAR_QUALITY_GATE_ENFORCE", "0").strip().lower() in _TRUTHY


def _max_range_frac() -> float:
    try:
        return float(os.getenv("BAR_QUALITY_MAX_RANGE_FRAC", "") or MAX_RANGE_FRAC)
    except ValueError:
        return MAX_RANGE_FRAC


def _max_jump_frac() -> float:
    try:
        return float(os.getenv("BAR_QUALITY_MAX_JUMP_FRAC", "") or MAX_JUMP_FRAC)
    except ValueError:
        return MAX_JUMP_FRAC


def _finite(*vals: object) -> bool:
    try:
        return all(math.isfinite(float(v)) for v in vals)
    except (TypeError, ValueError):
        return False


def screen_bars(rows: Sequence[Row]) -> list[BarReject]:
    """Return the list of rows that fail quality screening.

    Pure: no I/O, no env reads — thresholds are resolved by the caller's env
    helpers so this stays trivially testable. Indices are positions in ``rows``.
    """
    max_range = _max_range_frac()
    max_jump = _max_jump_frac()
    rejects: list[BarReject] = []
    bad: set[int] = set()

    # --- Per-bar physical checks --------------------------------------------
    for i, r in enumerate(rows):
        o, h, low, c = r[_OPEN], r[_HIGH], r[_LOW], r[_CLOSE]
        src = str(r[_SOURCE]).strip().lower()

        if src in BLOCKED_SOURCES:
            rejects.append(BarReject(i, "BLOCKED_SOURCE", f"source={src!r}"))
            bad.add(i)
            continue

        if not _finite(o, h, low, c):
            rejects.append(BarReject(i, "NONFINITE", f"ohlc=({o},{h},{low},{c})"))
            bad.add(i)
            continue

        of, hf, lf, cf = float(o), float(h), float(low), float(c)

        if min(of, hf, lf, cf) <= 0:
            rejects.append(BarReject(i, "NONPOSITIVE", f"ohlc=({of},{hf},{lf},{cf})"))
            bad.add(i)
            continue

        if hf < lf or hf < max(of, cf) or lf > min(of, cf):
            rejects.append(BarReject(i, "OHLC_LOGIC", f"ohlc=({of},{hf},{lf},{cf})"))
            bad.add(i)
            continue

        if (hf - lf) / lf > max_range:
            rejects.append(
                BarReject(i, "RANGE_EXPLOSION", f"range={(hf - lf) / lf:.3f} h={hf} l={lf}")
            )
            bad.add(i)

    # --- Lone neighbour-jump check (time-ordered, skips already-bad rows) ----
    # Build a time-sorted view of the rows still standing; a bar is a lone
    # outlier only if it diverges from BOTH chronological neighbours.
    order = sorted(
        (i for i in range(len(rows)) if i not in bad),
        key=lambda i: str(rows[i][_TS]),
    )
    for pos in range(1, len(order) - 1):
        i = order[pos]
        c = float(rows[i][_CLOSE])
        cp = float(rows[order[pos - 1]][_CLOSE])
        cn = float(rows[order[pos + 1]][_CLOSE])
        if cp <= 0 or cn <= 0:
            continue
        up = abs(c - cp) / cp
        dn = abs(c - cn) / cn
        if up > max_jump and dn > max_jump:
            rejects.append(
                BarReject(i, "NEIGHBOR_JUMP", f"close={c} prev={cp} next={cn} dev={up:.2f}")
            )
            bad.add(i)

    rejects.sort(key=lambda rj: rj.index)
    return rejects


def apply_gate(
    rows: list[Row],
    *,
    symbol: str = "?",
    interval: str = "?",
) -> tuple[list[Row], list[BarReject]]:
    """Screen ``rows`` and, in enforce mode, drop the rejected ones.

    Returns ``(rows_to_write, rejects)``. Always logs a one-line verdict when
    anything is rejected; the ``rejects`` list is returned regardless of mode so
    callers/tests can assert on it. When the gate is disabled, returns the rows
    unchanged with an empty reject list.
    """
    if not gate_enabled() or not rows:
        return rows, []

    rejects = screen_bars(rows)
    if not rejects:
        return rows, []

    enforced = gate_enforced()
    by_reason: dict[str, int] = {}
    for rj in rejects:
        by_reason[rj.reason] = by_reason.get(rj.reason, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
    sample = "; ".join(f"[{rj.index}]{rj.reason}:{rj.detail}" for rj in rejects[:3])

    logger.warning(
        "[bar_quality] %s %s - %s %d/%d bars (%s) | %s",
        symbol,
        interval,
        "REJECTED" if enforced else "FLAGGED(shadow)",
        len(rejects),
        len(rows),
        summary,
        sample,
    )

    if not enforced:
        return rows, rejects

    bad_idx = {rj.index for rj in rejects}
    kept = [r for i, r in enumerate(rows) if i not in bad_idx]
    return kept, rejects


# =============================================================================
# Read-time freshness gate (interval-scaled, decision-path) — SOTA plan P1.4
# =============================================================================
#
# The screen above is a WRITE-time guard: it keeps malformed ticks out of
# ``market_data_bars``. It says nothing about a read that lands on GOOD but
# OLD bars — a feed that has gone quietly stale (IBKR disconnected, no new
# prints) still hands back well-formed historical rows, so the write-time
# screen never fires and a decision can be made on data that is minutes-to-
# hours stale. This is the READ-time counterpart: consulted at decision time
# (``engine/agents/pipeline.py::pre_filter_signal``, before the LLM pipeline
# runs), any traded symbol whose newest bar is older than an interval-scaled
# ceiling is forced to NO_TRADE/HOLD.
#
# "Interval-scaled" matters because a fixed ceiling is either too loose for
# fast timeframes (a 5m strategy trading on a bar that is 2h old is not
# "slightly stale", it is a different session) or too tight for slow ones (a
# 4h bar is not stale at 90 minutes old). The ceiling instead scales with the
# bar's own interval: ``max(floor, multiplier * interval_seconds)``.
#
# Fails OPEN only when the comparison itself is impossible (no determinable
# bar age, or an unparseable interval token) — mirrors the "indeterminate ->
# skip this anchor" contract of ``latest_bar_age_seconds`` in
# ``engine/risk/entry_price_sanity.py``, so a timestamp-less frame never
# false-trips. Whenever a real age vs. threshold comparison IS possible, it
# fails CLOSED (NO_TRADE) — this is a fail-safe gate, not a soft warning.

_ENV_FRESHNESS_ENABLED = "BAR_FRESHNESS_GATE_ENABLED"
_ENV_FRESHNESS_MULTIPLIER = "BAR_FRESHNESS_STALE_MULTIPLIER"
_ENV_FRESHNESS_FLOOR = "BAR_FRESHNESS_MIN_FLOOR_SECONDS"

#: A bar older than this many multiples of its own interval is stale. 3x
#: tolerates one missed print plus ordinary feed jitter without masking a
#: genuinely frozen feed.
DEFAULT_STALE_MULTIPLIER: float = 3.0

#: Absolute floor so a fast interval (e.g. 1m * 3 = 180s) is never tripped by
#: sub-minute polling/fetch latency alone.
DEFAULT_MIN_FLOOR_SECONDS: int = 300

#: Interval token -> seconds. Covers the timeframe strings used across the
#: pipeline (engine/agents/pipeline.py, engine/data/market_data.py).
_INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3_600,
    "2h": 7_200,
    "4h": 14_400,
    "1d": 86_400,
    "d": 86_400,
    "day": 86_400,
    "daily": 86_400,
    "1w": 604_800,
    "w": 604_800,
    "week": 604_800,
    "weekly": 604_800,
}

_INTERVAL_TOKEN_RE = re.compile(r"^(\d+)\s*([a-zA-Z]+)$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400, "w": 604_800}


def interval_to_seconds(interval: str) -> Optional[int]:
    """Best-effort parse of a timeframe token ("5m", "1h", "1d", ...) to seconds.

    Returns ``None`` when the token cannot be interpreted at all, so callers
    fail open (freshness indeterminate) rather than fabricate a threshold.
    """
    if not interval:
        return None
    key = str(interval).strip().lower()
    if key in _INTERVAL_SECONDS:
        return _INTERVAL_SECONDS[key]
    match = _INTERVAL_TOKEN_RE.match(key)
    if not match:
        return None
    raw_n, unit = match.groups()
    try:
        n = int(raw_n)
    except ValueError:
        return None
    unit_seconds = _UNIT_SECONDS.get(unit[0])
    if unit_seconds is None or n <= 0:
        return None
    return n * unit_seconds


def freshness_gate_enabled() -> bool:
    """Whether the read-time freshness gate runs at all. Default ON (opt-out).

    ``BAR_FRESHNESS_GATE_ENABLED=0`` fully disables the decision-time
    staleness check. Read fresh on every call so it can be toggled at
    runtime without a restart, matching the opt-out convention already used
    by ``is_bar_freshness_check_enabled`` in engine/risk/entry_price_sanity.py.
    """
    return os.getenv(_ENV_FRESHNESS_ENABLED, "1").strip().lower() in _TRUTHY


def _stale_multiplier() -> float:
    try:
        return float(os.getenv(_ENV_FRESHNESS_MULTIPLIER, "") or DEFAULT_STALE_MULTIPLIER)
    except ValueError:
        return DEFAULT_STALE_MULTIPLIER


def _min_floor_seconds() -> int:
    try:
        return int(os.getenv(_ENV_FRESHNESS_FLOOR, "") or DEFAULT_MIN_FLOOR_SECONDS)
    except ValueError:
        return DEFAULT_MIN_FLOOR_SECONDS


def stale_threshold_seconds(interval: str) -> Optional[float]:
    """Interval-scaled staleness ceiling in seconds, or ``None`` if the
    interval token cannot be parsed."""
    interval_s = interval_to_seconds(interval)
    if interval_s is None:
        return None
    return max(_min_floor_seconds(), _stale_multiplier() * interval_s)


class FreshnessVerdict(NamedTuple):
    """Result of a read-time freshness check for one symbol/interval pair."""

    is_stale: bool
    age_seconds: Optional[float]
    threshold_seconds: Optional[float]
    reason: str


def check_freshness(age_seconds: Optional[float], interval: str) -> FreshnessVerdict:
    """Pure predicate: is a bar of ``age_seconds`` age stale for ``interval``?

    No I/O — callers supply the already-computed bar age (e.g. via
    ``latest_bar_age_seconds`` from engine/risk/entry_price_sanity.py) so this
    stays trivially testable, mirroring ``screen_bars``'s purity above.
    """
    if age_seconds is None:
        return FreshnessVerdict(
            False, None, None, "bar age indeterminate — freshness check skipped"
        )
    threshold = stale_threshold_seconds(interval)
    if threshold is None:
        return FreshnessVerdict(
            False,
            age_seconds,
            None,
            f"interval {interval!r} unparseable — freshness check skipped",
        )
    if age_seconds > threshold:
        return FreshnessVerdict(
            True,
            age_seconds,
            threshold,
            f"newest bar is {age_seconds:.0f}s old (> {threshold:.0f}s interval-scaled "
            f"ceiling for interval={interval!r}) — fail-safe NO_TRADE",
        )
    return FreshnessVerdict(False, age_seconds, threshold, "fresh")
