"""
JARVIS TRADER — Entry-Timing Scenario Analytics
================================================
Pure, I/O-free module for "what-if" entry-timing analysis.

For each offset in *offsets* (negative = earlier, positive = later, 0 = actual),
the hypothetical entry price is the *open* of the bar at
``entry_bar_index + offset`` (clamped to [0, len(bars_df)-1]).  PnL is
recomputed against the **same** exit price; delta is the difference from the
actual (offset-0) result.

offset=0 is the sanity anchor: its pnl_usd MUST match the caller-supplied
actual trade PnL (within floating-point tolerance) when the actual entry price
equals that bar's open.  Because real fills rarely land exactly on the open, the
module accepts ``actual_entry_price`` explicitly and uses it only for the offset=0
row — every other offset uses the bar's open.

The function is pure: bars_df in, list of dicts out — no I/O.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("jarvis_trader.analytics.scenario")

# Recognized long-side labels (mirrors excursion.py convention)
_LONG_SIDES = frozenset({"buy", "long", "buy_to_open", "buy to open"})


def compute_entry_timing_scenarios(
    side: str,
    actual_entry_price: float,
    exit_price: float,
    bars_df,  # pd.DataFrame with at least an 'open' column
    entry_bar_index: int,
    offsets: list[int],
    multiplier: float = 1.0,
    qty: float = 1.0,
) -> list[dict]:
    """
    Compute entry-timing scenarios for a single closed trade.

    Parameters
    ----------
    side:
        Trade direction — any label in ``_LONG_SIDES`` is LONG; everything
        else is SHORT.
    actual_entry_price:
        The actual fill price (used for offset=0 so the baseline matches the
        real trade PnL exactly).
    exit_price:
        Exit fill price — held constant across all scenarios.
    bars_df:
        pd.DataFrame of bars covering at least the trade entry window.
        Must contain an ``open`` column.  Rows are expected to be sorted
        chronologically (ascending time); ``entry_bar_index`` is the integer
        position of the actual entry bar within this frame.
    entry_bar_index:
        Row index of the actual entry bar in *bars_df* (0-based).
        Offsets are applied relative to this index.
    offsets:
        List of integer bar offsets to evaluate.  offset=0 returns the actual
        trade PnL using ``actual_entry_price``; negative offsets are earlier
        bars; positive are later.  Out-of-range offsets are clamped to the
        valid index range.
    multiplier:
        Dollar-per-point contract multiplier (e.g. 5.0 for MES).
    qty:
        Number of contracts.

    Returns
    -------
    list[dict], one entry per offset, each containing:
        offset_bars          int    Requested offset
        hypothetical_entry   float  Entry price for this scenario (bar open, or
                                    actual_entry_price for offset=0)
        pnl_usd              float  Hypothetical PnL in dollars
        pnl_pct              float  Hypothetical PnL as fraction of entry
        delta_vs_actual_usd  float  pnl_usd - actual_pnl_usd (positive = better)

    Returns an empty list when inputs are invalid (bars missing, non-positive
    prices) — never raises.
    """
    # ---------- guards ----------
    if bars_df is None or (hasattr(bars_df, "__len__") and len(bars_df) == 0):
        logger.warning("compute_entry_timing_scenarios: bars_df is empty or None")
        return []

    if "open" not in bars_df.columns:
        logger.warning("compute_entry_timing_scenarios: bars_df missing 'open' column")
        return []

    if actual_entry_price <= 0 or exit_price <= 0:
        logger.warning(
            "compute_entry_timing_scenarios: non-positive price "
            "(entry=%s, exit=%s); skipping",
            actual_entry_price,
            exit_price,
        )
        return []

    n_bars = len(bars_df)
    is_long = side.lower().strip() in _LONG_SIDES

    def _pnl(entry: float, exit_p: float) -> float:
        """Dollar PnL for a single contract at given prices."""
        if is_long:
            return (exit_p - entry) * multiplier * qty
        else:
            return (entry - exit_p) * multiplier * qty

    def _pnl_pct(entry: float, exit_p: float) -> float:
        if entry == 0:
            return 0.0
        if is_long:
            return (exit_p - entry) / entry
        else:
            return (entry - exit_p) / entry

    # Baseline: actual trade (offset=0 always uses actual_entry_price)
    actual_pnl_usd = _pnl(actual_entry_price, exit_price)

    results: list[dict] = []

    for offset in offsets:
        clamped_idx = max(0, min(entry_bar_index + offset, n_bars - 1))

        if offset == 0:
            # Anchor: reproduce actual trade exactly
            hyp_entry = actual_entry_price
        else:
            try:
                hyp_entry = float(bars_df["open"].iloc[clamped_idx])
            except (IndexError, ValueError, TypeError) as exc:
                logger.debug(
                    "compute_entry_timing_scenarios: could not read open at idx %d: %s",
                    clamped_idx,
                    exc,
                )
                hyp_entry = actual_entry_price  # fallback to avoid skipping the row

        hyp_pnl_usd = _pnl(hyp_entry, exit_price)
        hyp_pnl_pct = _pnl_pct(hyp_entry, exit_price)
        delta = hyp_pnl_usd - actual_pnl_usd

        results.append(
            {
                "offset_bars": offset,
                "hypothetical_entry": round(hyp_entry, 6),
                "pnl_usd": round(hyp_pnl_usd, 4),
                "pnl_pct": round(hyp_pnl_pct, 6),
                "delta_vs_actual_usd": round(delta, 4),
            }
        )

    return results
