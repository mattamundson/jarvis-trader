"""
JARVIS TRADER -- Outcome hygiene
================================
Single source of truth for filtering corrupt and duplicate rows out of the
``trade_outcomes`` calibration table before any consumer reads them.

Background
----------
On 2026-06-02 the calibration DB (engine/data/agent_feedback.db) held three
byte-identical MES rows carrying an impossible +$10,102.98 P&L (demo-seed /
decoupled-NAV corruption) plus two test fixtures. A single corrupted or
N-times-logged row silently dominates the Brier/IC surface AND the live
directional-accuracy agent weights, so every read path routes through the
guards here, and the write path (AgentFeedbackTracker.record_outcome) rejects
the same classes at ingestion.

Guards
------
* Magnitude -- a single closed micro-futures paper trade cannot realistically
  realize a P&L beyond the max single-order value (config.MAX_SINGLE_ORDER_VALUE
  = $5,000). Outcomes whose ``|pnl_usd|`` exceeds the bound are upstream P&L
  corruption and are dropped.
* Duplicate -- rows sharing the same wall-clock second AND identical
  ``(signal, pnl)`` are one logical trade logged N times (the triplicate
  artifact). Keep only the first. The second-level timestamp in the key makes a
  false collapse of two genuinely independent trades effectively impossible.

Both guards log at WARNING and never drop silently.
"""

from __future__ import annotations

import logging
import os
from typing import List, Sequence, Tuple

logger = logging.getLogger(__name__)

# Plausibility bound for a single-trade realized P&L. Aligned to
# config.MAX_SINGLE_ORDER_VALUE ($5,000); env-overridable for unusual accounts.
MAX_PLAUSIBLE_ABS_PNL_USD = float(os.getenv("CALIBRATION_MAX_ABS_PNL_USD", "5000.0"))


def is_plausible_pnl(pnl: float | None) -> bool:
    """True when a single-trade P&L is within the plausibility bound.

    ``None`` (legacy rows with no recorded P&L) is treated as plausible -- it
    carries no magnitude to reject on.
    """
    if pnl is None:
        return True
    return abs(pnl) <= MAX_PLAUSIBLE_ABS_PNL_USD


def sanitize_outcome_rows(
    rows: Sequence[tuple],
    *,
    context: str,
    signal_idx: int = 0,
    pnl_idx: int = 1,
    ts_idx: int = 2,
    return_counts: bool = False,
):
    """Drop corrupt and duplicate outcome rows; preserve full row tuples.

    Parameters
    ----------
    rows
        DB rows as tuples. ``signal_idx`` / ``pnl_idx`` / ``ts_idx`` locate the
        signal, pnl_usd and timestamp fields within each tuple, so the same
        helper serves the ``(signal, pnl, ts)`` shape used by the Brier/IC
        fetch paths and the ``(direction, outcome, signal, ts, pnl)`` shape used
        by the directional-accuracy path.
    context
        Short label for the log line (e.g. ``"Brier/news"``).
    return_counts
        When True, return ``(cleaned, n_corrupt, n_dup)`` instead of just
        ``cleaned``.

    Returns the surviving full row tuples in input order.
    """
    cleaned: List[tuple] = []
    seen: set = set()
    n_corrupt = 0
    n_dup = 0
    for row in rows:
        raw_signal = row[signal_idx]
        raw_pnl = row[pnl_idx]
        if raw_signal is None:
            continue
        signal = float(raw_signal)
        pnl = float(raw_pnl) if raw_pnl is not None else None
        if pnl is not None and abs(pnl) > MAX_PLAUSIBLE_ABS_PNL_USD:
            n_corrupt += 1
            continue
        ts = row[ts_idx]
        pnl_key = round(pnl, 6) if pnl is not None else None
        key = ((ts or "")[:19], round(signal, 6), pnl_key)
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)
        cleaned.append(row)
    if n_corrupt or n_dup:
        logger.warning(
            "[Calibration] %s: excluded %d corrupt (|pnl|>$%.0f) + %d duplicate "
            "outcome rows; %d of %d retained",
            context,
            n_corrupt,
            MAX_PLAUSIBLE_ABS_PNL_USD,
            n_dup,
            len(cleaned),
            len(rows),
        )
    if return_counts:
        return cleaned, n_corrupt, n_dup
    return cleaned


def window_integrity(conn, cutoff_iso: str) -> Tuple[int, int]:
    """Agent-independent integrity scan of trade_outcomes within a window.

    Returns ``(rows_excluded_corrupt, rows_excluded_duplicate)`` for rows with
    ``timestamp >= cutoff_iso``:

    * corrupt   -- ``|pnl_usd| > MAX_PLAUSIBLE_ABS_PNL_USD``
    * duplicate -- extra rows beyond the first within each
      ``(symbol, timestamp-to-second, pnl_usd)`` group (distinct trade_ids).

    ``conn`` is an open sqlite3 connection. Best-effort: returns ``(0, 0)`` if
    the table/columns are missing.
    """
    try:
        rows = conn.execute(
            "SELECT symbol, timestamp, pnl_usd FROM trade_outcomes WHERE timestamp >= ?",
            (cutoff_iso,),
        ).fetchall()
    except Exception:
        return 0, 0
    n_corrupt = 0
    n_dup = 0
    seen: set = set()
    for symbol, ts, pnl in rows:
        if pnl is not None and abs(float(pnl)) > MAX_PLAUSIBLE_ABS_PNL_USD:
            n_corrupt += 1
            continue
        key = (symbol, (ts or "")[:19], round(float(pnl), 6) if pnl is not None else None)
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)
    return n_corrupt, n_dup
