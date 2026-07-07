"""
JARVIS TRADER — MAE/MFE Backfill
==================================
Callable + script that backfills mae_pct/mfe_pct/mae_usd/mfe_usd for existing
closed paper_trades rows where the columns are NULL.

Usage (from the engine working directory, with the engine venv activated):
    python -m analytics.excursion_backfill
    # or
    python analytics/excursion_backfill.py

Does NOT auto-run on import — the function run_backfill() must be called
explicitly (or via __main__ below).

Architecture
------------
- Fetches up to ``limit`` closed trades with NULL mae_pct.
- For each trade, fetches 1-minute bars spanning entry_time -> exit_time from
  the engine's MarketDataManager (TV MCP -> IBKR -> Polygon waterfall).
- Calls compute_excursion() and writes the four columns back.
- Trades whose bars are unavailable are skipped (left NULL) — never crashes.

Caveats
-------
- Requires a running MarketDataManager (i.e., the engine venv + data layer).
  When called from outside the engine, pass a ``data_manager`` argument.
- TV MCP is the primary source (Tier 0); falls back to IBKR/Polygon.
- Historical bars availability depends on the configured bar sources.
  Paper trades older than ~7 days may have no bars available.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.analytics.excursion_backfill")


def _parse_utc(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a tz-aware UTC datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _filter_bars_to_window(bars_df, entry_dt: datetime, exit_dt: datetime):
    """
    Slice a bars DataFrame to the [entry_dt, exit_dt] window.

    Assumes bars_df has either a 'timestamp' column (TradingView/Polygon format)
    or a DatetimeIndex (IBKR format).  Returns the sliced DataFrame.
    """
    import pandas as pd

    if bars_df is None or bars_df.empty:
        return bars_df

    # Coerce timestamps
    if "timestamp" in bars_df.columns:
        ts = pd.to_datetime(bars_df["timestamp"], utc=True, errors="coerce")
        mask = (ts >= entry_dt) & (ts <= exit_dt)
        return bars_df.loc[mask].reset_index(drop=True)
    elif isinstance(bars_df.index, pd.DatetimeIndex):
        # IBKR returns a DatetimeIndex
        idx = bars_df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
        mask = (idx >= entry_dt) & (idx <= exit_dt)
        return bars_df.loc[mask].reset_index(drop=True)
    else:
        # Unknown format — return as-is and let compute_excursion handle it
        return bars_df


async def _backfill_one(
    trade: dict,
    data_manager: Any,
    db_manager: Any,
) -> bool:
    """
    Backfill a single trade.  Returns True on success, False on skip.
    """
    from analytics.excursion import compute_excursion
    from utils.position_sizing import get_contract_multiplier

    trade_id = trade.get("trade_id", "?")
    symbol = trade.get("symbol", "")
    side = trade.get("side", "buy")
    entry_price = float(trade.get("entry_price") or 0)
    qty = float(trade.get("quantity") or 1)
    entry_time_raw = trade.get("entry_time")
    exit_time_raw = trade.get("exit_time")

    entry_dt = _parse_utc(entry_time_raw)
    exit_dt = _parse_utc(exit_time_raw)

    if not entry_dt or not exit_dt or entry_price <= 0:
        logger.debug("[backfill] skip trade %s — missing entry/exit timestamps or price", trade_id[:8])
        return False

    # Compute window length; fetch at least 1 extra day for buffer
    window_days = max(1, (exit_dt - entry_dt).days + 1)

    try:
        bars_df = await data_manager.get_bars(
            symbol,
            lookback_days=window_days + 1,
            timeframe="1m",
            is_futures=True,
        )
    except Exception as exc:
        logger.warning("[backfill] trade %s — get_bars failed: %s", trade_id[:8], exc)
        return False

    if bars_df is None or (hasattr(bars_df, "empty") and bars_df.empty):
        logger.debug("[backfill] trade %s — no bars available from data source", trade_id[:8])
        return False

    window_bars = _filter_bars_to_window(bars_df, entry_dt, exit_dt)
    if len(window_bars) == 0:
        logger.debug("[backfill] trade %s — zero bars in entry->exit window", trade_id[:8])
        return False

    multiplier = get_contract_multiplier(symbol)
    result = compute_excursion(side, entry_price, window_bars, multiplier=multiplier, qty=qty)

    if result["mae_pct"] is None:
        logger.debug("[backfill] trade %s — compute_excursion returned None", trade_id[:8])
        return False

    sql = """
        UPDATE paper_trades
           SET mae_pct = ?,
               mfe_pct = ?,
               mae_usd = ?,
               mfe_usd = ?
         WHERE trade_id = ?
    """
    with db_manager._lock:
        conn = db_manager._connect()
        try:
            conn.execute(
                sql,
                (result["mae_pct"], result["mfe_pct"], result["mae_usd"], result["mfe_usd"], trade_id),
            )
            conn.commit()
        finally:
            conn.close()

    logger.info(
        "[backfill] trade %s %s %s: MAE=%.4f%% (%.2f$) MFE=%.4f%% (%.2f$) bars=%d",
        trade_id[:8], symbol, side,
        (result["mae_pct"] or 0) * 100, result["mae_usd"] or 0,
        (result["mfe_pct"] or 0) * 100, result["mfe_usd"] or 0,
        result["bar_count"],
    )
    return True


async def run_backfill(
    db_manager: Any = None,
    data_manager: Any = None,
    limit: int = 200,
) -> dict:
    """
    Backfill MAE/MFE for closed paper_trades where mae_pct IS NULL.

    Parameters
    ----------
    db_manager:
        Engine DatabaseManager instance.  Resolved from ``database.get_db``
        when not supplied (requires engine startup context).
    data_manager:
        Engine MarketDataManager instance.  Resolved from the module-level
        singleton when not supplied.
    limit:
        Maximum number of trades to process in one call.

    Returns
    -------
    dict with keys: processed, updated, skipped, errors
    """
    import pandas as pd  # noqa: F401 — ensure pandas is importable

    if db_manager is None:
        from database import get_db
        db_manager = get_db()

    if data_manager is None:
        try:
            from data.market_data import get_data_manager
            data_manager = get_data_manager()
        except (ImportError, AttributeError):
            logger.error("[backfill] could not resolve MarketDataManager; pass data_manager= explicitly")
            return {"processed": 0, "updated": 0, "skipped": 0, "errors": 1}

    # Fetch closed trades with NULL mae_pct
    sql = """
        SELECT trade_id, symbol, side, quantity, entry_price, entry_time, exit_time
          FROM paper_trades
         WHERE status = 'closed'
           AND mae_pct IS NULL
         ORDER BY exit_time DESC
         LIMIT ?
    """
    with db_manager._lock:
        conn = db_manager._connect()
        try:
            rows = conn.execute(sql, (limit,)).fetchall()
            trades = [dict(r) for r in rows]
        finally:
            conn.close()

    logger.info("[backfill] found %d closed trades with NULL mae_pct (limit=%d)", len(trades), limit)

    processed = 0
    updated = 0
    skipped = 0
    errors = 0

    for trade in trades:
        processed += 1
        try:
            ok = await _backfill_one(trade, data_manager, db_manager)
            if ok:
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            errors += 1
            logger.exception("[backfill] unhandled error on trade %s: %s", trade.get("trade_id", "?")[:8], exc)

    logger.info(
        "[backfill] complete — processed=%d updated=%d skipped=%d errors=%d",
        processed, updated, skipped, errors,
    )
    return {"processed": processed, "updated": updated, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Add engine to path if running as script from a parent directory
    engine_dir = Path(__file__).resolve().parent.parent
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))

    result = asyncio.run(run_backfill())
    print(f"Backfill result: {result}")
    sys.exit(0 if result["errors"] == 0 else 1)
