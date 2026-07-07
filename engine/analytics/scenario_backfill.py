"""
JARVIS TRADER — Entry-Timing Scenario Wiring Helper
=====================================================
For a closed paper_trade dict, fetches bars around the entry (reusing the
same MarketDataManager waterfall as excursion_backfill.py), locates the
entry bar within those bars, and runs compute_entry_timing_scenarios().

Design choices:
- Guard missing bars → returns None, never crashes.
- Does NOT auto-run on import; call run_scenarios_for_trade() explicitly.
- Reuses _parse_utc() and _filter_bars_to_window() from excursion_backfill
  to stay DRY — imported at call time to avoid circular dependencies.
- Callable from the endpoint, a script, or a REPL.

Usage (from the engine working directory, with the engine venv activated):
    python -m analytics.scenario_backfill
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.analytics.scenario_backfill")

# Default offsets: 3 bars earlier through 3 bars later
DEFAULT_OFFSETS = [-3, -2, -1, 0, 1, 2, 3]


def _locate_entry_bar(bars_df, entry_dt) -> Optional[int]:
    """
    Find the index of the bar whose timestamp is closest to *entry_dt* and
    at or before it (i.e. the bar that was active when the trade entered).

    Returns None when the entry time cannot be matched to any bar.
    """
    import pandas as pd

    if bars_df is None or bars_df.empty:
        return None

    if "timestamp" in bars_df.columns:
        ts = pd.to_datetime(bars_df["timestamp"], utc=True, errors="coerce")
    elif isinstance(bars_df.index, pd.DatetimeIndex):
        idx = bars_df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
        ts = idx.to_series().reset_index(drop=True)
    else:
        # Unknown format: fall back to the first bar
        return 0

    # Bars at or before entry
    candidates = ts[ts <= entry_dt]
    if candidates.empty:
        # If all bars are after entry (e.g. insufficient history), use bar 0
        return 0

    # The last bar that is <= entry time
    return int(candidates.index[-1])


async def run_scenarios_for_trade(
    trade: dict,
    data_manager: Any,
    offsets: Optional[list[int]] = None,
) -> Optional[list[dict]]:
    """
    Fetch bars for *trade* and return entry-timing scenario rows.

    Parameters
    ----------
    trade:
        A closed paper_trade dict with at least:
        ``trade_id``, ``symbol``, ``side``, ``entry_price``, ``exit_price``,
        ``quantity``, ``entry_time``, ``exit_time``.
    data_manager:
        Engine MarketDataManager instance.
    offsets:
        Bar offsets to evaluate (default: DEFAULT_OFFSETS).

    Returns
    -------
    list[dict] of scenario rows from compute_entry_timing_scenarios(), or
    None when bars are unavailable or inputs are invalid.
    """
    from analytics.excursion_backfill import _filter_bars_to_window, _parse_utc
    from analytics.scenario import compute_entry_timing_scenarios
    from utils.position_sizing import get_contract_multiplier

    if offsets is None:
        offsets = DEFAULT_OFFSETS

    trade_id = trade.get("trade_id", "?")
    symbol = trade.get("symbol", "")
    side = trade.get("side", "buy")
    entry_price = float(trade.get("entry_price") or 0)
    exit_price = float(trade.get("exit_price") or 0)
    qty = float(trade.get("quantity") or 1)

    entry_dt = _parse_utc(trade.get("entry_time"))
    exit_dt = _parse_utc(trade.get("exit_time"))

    if not entry_dt or not exit_dt:
        logger.debug("[scenario] trade %s — missing entry/exit timestamps", str(trade_id)[:8])
        return None

    if entry_price <= 0 or exit_price <= 0:
        logger.debug(
            "[scenario] trade %s — non-positive price (entry=%s exit=%s)",
            str(trade_id)[:8],
            entry_price,
            exit_price,
        )
        return None

    # Fetch bars: extra buffer so we have bars before entry for negative offsets
    max_pre_bars = abs(min(offsets)) if offsets else 3
    window_days = max(1, (exit_dt - entry_dt).days + 1)
    # Add 2 days for pre-entry buffer (covers up to ~max_pre_bars 1m bars)
    fetch_days = window_days + max(2, (max_pre_bars // 390) + 2)

    try:
        bars_df = await data_manager.get_bars(
            symbol,
            lookback_days=fetch_days,
            timeframe="1m",
            is_futures=True,
        )
    except Exception as exc:
        logger.warning("[scenario] trade %s — get_bars failed: %s", str(trade_id)[:8], exc)
        return None

    if bars_df is None or (hasattr(bars_df, "empty") and bars_df.empty):
        logger.debug("[scenario] trade %s — no bars available", str(trade_id)[:8])
        return None

    # Widen the filter window to include pre-entry bars (for negative offsets)
    from datetime import timedelta

    window_bars = _filter_bars_to_window(
        bars_df,
        entry_dt - timedelta(minutes=max_pre_bars + 5),
        exit_dt,
    )

    if len(window_bars) == 0:
        logger.debug("[scenario] trade %s — zero bars in window", str(trade_id)[:8])
        return None

    entry_bar_idx = _locate_entry_bar(window_bars, entry_dt)
    if entry_bar_idx is None:
        logger.debug("[scenario] trade %s — could not locate entry bar", str(trade_id)[:8])
        return None

    multiplier = get_contract_multiplier(symbol)
    scenarios = compute_entry_timing_scenarios(
        side=side,
        actual_entry_price=entry_price,
        exit_price=exit_price,
        bars_df=window_bars,
        entry_bar_index=entry_bar_idx,
        offsets=offsets,
        multiplier=multiplier,
        qty=qty,
    )

    logger.info(
        "[scenario] trade %s %s %s: %d offsets computed",
        str(trade_id)[:8],
        symbol,
        side,
        len(scenarios),
    )
    return scenarios


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    engine_dir = Path(__file__).resolve().parent.parent
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))

    async def _demo():
        """Run a quick demo against the last closed trade in the DB."""
        from data.market_data import get_data_manager
        from database import get_db

        db = get_db()
        dm = get_data_manager()

        with db._lock:
            conn = db._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM paper_trades WHERE status='closed' "
                    "ORDER BY exit_time DESC LIMIT 1"
                ).fetchone()
            finally:
                conn.close()

        if not row:
            print("No closed trades found.")
            return

        trade = dict(row)
        print(f"Running scenarios for trade {trade.get('trade_id', '?')[:8]} ...")
        result = await run_scenarios_for_trade(trade, dm)
        if result:
            for row_s in result:
                print(row_s)
        else:
            print("No scenarios produced (bars unavailable or invalid trade).")

    asyncio.run(_demo())
    sys.exit(0)
