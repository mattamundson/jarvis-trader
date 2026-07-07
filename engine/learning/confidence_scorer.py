"""
Confidence Scoring Module — Adjusts pipeline conviction based on symbol performance.

When enough trades accumulate for a symbol, this module boosts or reduces the
pipeline's final conviction based on win rate and R-ratio metrics.

Usage:
    from learning.confidence_scorer import get_confidence_adjustment
    adjustment = await get_confidence_adjustment("MES", db_manager)
    # adjustment is in [0.60, 1.40], default 1.0

Trade outcome data is queried from paper_trades table (or trade_outcomes in
production) with the following columns:
    symbol: Trading symbol (MES, MNQ, MCL, etc.)
    pnl: Realized P&L in USD
    outcome: 'winning_trade', 'losing_trade', or 'breakeven_trade'
    created_at: Timestamp when trade closed

The confidence_adjustment is computed as:
    win_rate = wins / total
    avg_winner = mean(pnl) where pnl > 0
    avg_loser = abs(mean(pnl)) where pnl < 0
    r_ratio = avg_winner / avg_loser (default 1.0 if no losers)

    Multiplier logic:
        0.65 (heavy discount) ← win_rate <= 0.35
        0.80 (discount)       ← win_rate <= 0.42
        1.10 (slight boost)   ← win_rate >= 0.55
        1.20 (solid boost)    ← win_rate >= 0.60 AND r_ratio >= 1.5
        1.35 (strong boost)   ← win_rate >= 0.65 AND r_ratio >= 1.8
        1.00 (neutral)        ← else

Wrapped in try/except: any exception returns 1.0 with warning log, NEVER raises.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum sample size for confidence adjustment to apply
MIN_TRADES_REQUIRED = 20

# Multiplier bounds
MIN_MULTIPLIER = 0.60
MAX_MULTIPLIER = 1.40


async def get_confidence_adjustment(
    symbol: str,
    db_manager: Optional[object],
) -> float:
    """
    Compute confidence adjustment multiplier for a symbol based on recent trade history.

    Args:
        symbol: Trading symbol (e.g., 'MES', 'MNQ', 'MCL')
        db_manager: DatabaseManager instance (or None)

    Returns:
        Multiplier in range [0.60, 1.40]. Default 1.0 when:
        - db_manager is None
        - Fewer than MIN_TRADES_REQUIRED trades found
        - Any exception occurs (always wrapped, never raises)

    Behavior:
        - Queries paper_trades table for symbol, ordered by created_at DESC
        - If count < 20: returns 1.0
        - Computes win_rate, avg_winner, avg_loser, r_ratio
        - Applies multiplier logic based on thresholds
        - Clamps result to [MIN_MULTIPLIER, MAX_MULTIPLIER]
        - All exceptions return 1.0 with warning log
    """
    try:
        # Guard: db_manager unavailable
        if db_manager is None:
            logger.debug(f"[Confidence] {symbol}: db_manager is None, returning 1.0")
            return 1.0

        # Guard: symbol validation
        if not symbol or not isinstance(symbol, str):
            logger.warning(f"[Confidence] Invalid symbol: {symbol}, returning 1.0")
            return 1.0

        symbol = symbol.upper().strip()

        # Query trade outcomes for this symbol
        # Using paper_trades table as the source of trade history
        trades = await _fetch_symbol_trades(db_manager, symbol)

        if not trades:
            logger.debug(f"[Confidence] {symbol}: No trades found, returning 1.0")
            return 1.0

        trade_count = len(trades)
        if trade_count < MIN_TRADES_REQUIRED:
            logger.debug(
                f"[Confidence] {symbol}: Only {trade_count} trades < {MIN_TRADES_REQUIRED}, "
                f"returning 1.0"
            )
            return 1.0

        # Compute win_rate, R-ratio, and other metrics
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)

        # Apply multiplier logic
        multiplier = _compute_multiplier(win_rate, r_ratio)

        logger.info(
            f"[Confidence] {symbol}: {trade_count} trades, "
            f"win_rate={win_rate:.1%}, r_ratio={r_ratio:.2f} → multiplier={multiplier:.2f}"
        )

        return multiplier

    except Exception as e:
        logger.warning(f"[Confidence] {symbol}: Exception during computation: {e}, returning 1.0")
        return 1.0


async def _fetch_symbol_trades(db_manager: object, symbol: str) -> list[dict]:
    """
    Fetch recent trades for a symbol from paper_trades table.

    Returns list of dicts with pnl and outcome fields. Returns empty list on error.
    """
    try:
        # The live DatabaseManager (database/manager.py, re-exported via
        # database/schema.py and used by main.py's init_db) exposes a SYNC
        # fetch_all(sql, params) -> list[dict]. Older/production managers may
        # instead expose query()/query_async(). Probe fetch_all first because it
        # is the method the running engine actually has — without this branch the
        # scorer silently degraded to a 1.0 (no-op) multiplier on every call.
        #
        # NOTE: the local paper_trades schema has no `outcome`/`created_at`
        # columns — win/loss is derived from the pnl sign in
        # _compute_trade_metrics — and it orders by exit_time. Only `status =
        # 'closed'` rows are counted so cancelled / phantom / contaminated fills
        # (e.g. the 2026-06-29 stale-price contamination) can't poison win-rate.
        fetch_all_query = (
            "SELECT pnl FROM paper_trades "
            "WHERE symbol = ? AND status = 'closed' AND pnl IS NOT NULL "
            "ORDER BY COALESCE(exit_time, entry_time) DESC LIMIT 100"
        )
        legacy_query = (
            "SELECT pnl, outcome FROM paper_trades "
            "WHERE symbol = ? ORDER BY created_at DESC LIMIT 100"
        )

        if hasattr(db_manager, "fetch_all"):
            trades = db_manager.fetch_all(fetch_all_query, (symbol,))
        elif hasattr(db_manager, "query_async"):
            trades = await db_manager.query_async(legacy_query, (symbol,))
        elif hasattr(db_manager, "query"):
            trades = db_manager.query(legacy_query, (symbol,))
        else:
            logger.warning("[Confidence] db_manager has no query method, returning []")
            return []

        # Ensure trades is a list of dicts
        if not isinstance(trades, list):
            trades = list(trades) if trades else []

        return trades

    except Exception as e:
        logger.debug(f"[Confidence] Error fetching trades for {symbol}: {e}")
        return []


def _compute_trade_metrics(trades: list[dict]) -> tuple[float, float, float, float]:
    """
    Compute win_rate, avg_winner, avg_loser, and r_ratio from trades list.

    Args:
        trades: List of dicts with 'pnl' and 'outcome' keys

    Returns:
        Tuple: (win_rate, avg_winner, avg_loser, r_ratio)
        All floats. r_ratio defaults to 1.0 if no losers.
    """
    if not trades:
        return 0.0, 0.0, 0.0, 1.0

    total = len(trades)
    winners = []
    losers = []
    wins = 0

    for trade in trades:
        pnl = float(trade.get("pnl") or 0)
        outcome = str(trade.get("outcome") or "").lower()

        # Check if winning trade
        if pnl > 0 or outcome == "winning_trade":
            wins += 1
            winners.append(
                pnl if pnl > 0 else 1.0
            )  # Use 1.0 if pnl not positive but marked winning
        elif pnl < 0 or outcome == "losing_trade":
            losers.append(abs(pnl))

    win_rate = wins / total if total > 0 else 0.0

    # Average winner and loser
    avg_winner = sum(winners) / len(winners) if winners else 0.0
    avg_loser = sum(losers) / len(losers) if losers else 0.0

    # R-ratio: avg_winner / avg_loser
    r_ratio = avg_winner / avg_loser if avg_loser > 0 else 1.0

    return win_rate, avg_winner, avg_loser, r_ratio


def _compute_multiplier(win_rate: float, r_ratio: float) -> float:
    """
    Apply multiplier scoring logic based on win_rate and r_ratio.

    Returns float in [MIN_MULTIPLIER, MAX_MULTIPLIER].
    """
    # Strong edge: high win rate with strong R-ratio
    if win_rate >= 0.65 and r_ratio >= 1.8:
        return 1.35

    # Solid edge: good win rate with solid R-ratio
    if win_rate >= 0.60 and r_ratio >= 1.5:
        return 1.20

    # Slight edge: decent win rate
    if win_rate >= 0.55:
        return 1.10

    # Poor performance: heavy discount
    if win_rate <= 0.35:
        return 0.65

    # Below average: light discount
    if win_rate <= 0.42:
        return 0.80

    # Neutral: default case
    return 1.0
