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
from typing import NamedTuple, Sequence

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
