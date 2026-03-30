"""
PostgreSQL Repository Layer
============================
Async data access layer for JARVIS TRADER trade logging.

Provides high-level functions to insert and query trading data:
  - Orders (filled, pending, rejected)
  - Agent decisions (technical, news, social, fundamental, debate, trader, risk, fund)
  - Portfolio snapshots (equity, cash, positions)
  - Safety events (kill switch, circuit breaker, rejections)
  - Performance metrics (daily P&L, win rate)
"""

import json
import logging
from typing import Optional

from .connection import execute, execute_insert, execute_one, get_pool

logger = logging.getLogger(__name__)

__all__ = [
    "insert_order",
    "insert_decision",
    "insert_portfolio_snapshot",
    "insert_safety_event",
    "insert_alert",
    "get_recent_orders",
    "get_recent_decisions",
    "get_daily_pnl",
]


# ── Orders (Trade Execution) ───────────────────────────────────────────────


async def insert_order(
    order_data: dict,
) -> Optional[int]:
    """
    Insert a new order into the orders table.

    Args:
        order_data: Dict with keys:
            symbol (str), quantity (int), order_type (str),
            limit_price (float, optional), stop_price (float, optional),
            is_futures (bool), is_options (bool),
            status (str), broker (str, optional), broker_order_id (str, optional),
            fill_price (float, optional), fill_quantity (int, optional),
            commission (float, optional), pnl (float, optional),
            triggered_by (str, optional), signal_score (float, optional),
            approved_by (str, optional), notes (str, optional)

    Returns:
        Inserted order ID, or None if error
    """
    pool = get_pool()
    if pool is None:
        logger.debug(f"[DB] Order insert skipped (no pool): {order_data.get('symbol')}")
        return None

    query = """
        INSERT INTO orders (
            symbol, quantity, order_type, limit_price, stop_price,
            is_futures, is_options, status, broker, broker_order_id,
            fill_price, fill_quantity, commission, pnl,
            triggered_by, signal_score, approved_by, notes
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14,
            $15, $16, $17, $18
        )
        RETURNING id
    """

    params = (
        order_data.get("symbol"),
        order_data.get("quantity", 0),
        order_data.get("order_type", "market"),
        order_data.get("limit_price"),
        order_data.get("stop_price"),
        order_data.get("is_futures", False),
        order_data.get("is_options", False),
        order_data.get("status", "pending"),
        order_data.get("broker"),
        order_data.get("broker_order_id"),
        order_data.get("fill_price"),
        order_data.get("fill_quantity"),
        order_data.get("commission"),
        order_data.get("pnl"),
        order_data.get("triggered_by"),
        order_data.get("signal_score"),
        order_data.get("approved_by"),
        order_data.get("notes"),
    )

    order_id = await execute_insert(query, *params)
    if order_id:
        logger.debug(
            f"[DB] Order {order_id} inserted: {order_data.get('symbol')} {order_data.get('quantity')}"
        )
    return order_id


# ── Agent Decisions (Full Decision Provenance) ──────────────────────────────


async def insert_decision(
    agent_name: str,
    symbol: str,
    signal: float,
    confidence: float,
    reasoning: str,
    raw_output: dict = None,
    indicators: dict = None,
    model_used: str = None,
    tokens_used: int = None,
    latency_ms: int = None,
    order_id: int = None,
    timeframe: str = None,
) -> Optional[int]:
    """
    Insert an agent decision record (full audit trail).

    Args:
        agent_name: Name of agent (technical, news, social, fundamental, etc.)
        symbol: Trading symbol (e.g., MES, SPY)
        signal: Signal value (-1.0 to 1.0)
        confidence: Confidence (0.0 to 1.0)
        reasoning: Full LLM reasoning text
        raw_output: Complete LLM output dict (optional)
        indicators: Technical indicator values (optional JSON dict)
        model_used: Model name (e.g., claude-sonnet-4-6)
        tokens_used: LLM token count
        latency_ms: Latency in milliseconds
        order_id: Related order ID (if this decision triggered an order)
        timeframe: Timeframe (e.g., 1m, 5m, 1h, 1d)

    Returns:
        Inserted decision ID, or None if error
    """
    pool = get_pool()
    if pool is None:
        logger.debug(f"[DB] Decision insert skipped (no pool): {agent_name} {symbol}")
        return None

    query = """
        INSERT INTO agent_decisions (
            agent_name, symbol, signal, confidence, reasoning,
            indicators, model_used, tokens_used, latency_ms,
            order_id, timeframe
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11
        )
        RETURNING id
    """

    # Convert indicators dict to JSON
    indicators_json = json.dumps(indicators or {}) if indicators else None

    params = (
        agent_name,
        symbol,
        signal,
        confidence,
        reasoning,
        indicators_json,
        model_used,
        tokens_used,
        latency_ms,
        order_id,
        timeframe,
    )

    decision_id = await execute_insert(query, *params)
    if decision_id:
        logger.debug(
            f"[DB] Decision {decision_id}: {agent_name} {symbol} signal={signal:.2f} conf={confidence:.0%}"
        )
    return decision_id


# ── Portfolio Snapshots (Account State) ────────────────────────────────────


async def insert_portfolio_snapshot(
    total_equity: float,
    cash_balance: float,
    unrealized_pnl: float = None,
    realized_pnl: float = None,
    daily_pnl: float = None,
    margin_used: float = None,
    margin_available: float = None,
    positions_json: dict = None,
    source: str = "ibkr",
) -> Optional[int]:
    """
    Insert a portfolio snapshot (account state at a point in time).

    Args:
        total_equity: Total account equity
        cash_balance: Available cash
        unrealized_pnl: Unrealized P&L
        realized_pnl: Realized P&L (today)
        daily_pnl: Daily P&L
        margin_used: Margin used
        margin_available: Available margin
        positions_json: List of open positions [{"symbol": "MES", "qty": 1, ...}]
        source: Data source (ibkr, schwab, paper)

    Returns:
        Inserted snapshot ID, or None if error
    """
    pool = get_pool()
    if pool is None:
        logger.debug("[DB] Portfolio snapshot skipped (no pool)")
        return None

    query = """
        INSERT INTO portfolio_snapshots (
            source, total_equity, cash_balance, unrealized_pnl, realized_pnl,
            daily_pnl, margin_used, margin_available, positions
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9
        )
        RETURNING id
    """

    positions_json_str = json.dumps(positions_json or []) if positions_json else None

    params = (
        source,
        total_equity,
        cash_balance,
        unrealized_pnl,
        realized_pnl,
        daily_pnl,
        margin_used,
        margin_available,
        positions_json_str,
    )

    snapshot_id = await execute_insert(query, *params)
    if snapshot_id:
        logger.debug(
            f"[DB] Portfolio snapshot {snapshot_id}: equity={total_equity:.2f}, cash={cash_balance:.2f}"
        )
    return snapshot_id


# ── Safety Events (Alerts & Circuit Breakers) ──────────────────────────────


async def insert_safety_event(
    event_type: str,
    details: dict = None,
    reason: str = None,
    resolved: bool = False,
) -> Optional[int]:
    """
    Insert a safety event (kill switch, circuit breaker, order rejection, etc.).

    Args:
        event_type: Type of event (kill_switch_activate, kill_switch_deactivate,
                    max_loss_breach, max_drawdown_breach, order_rejected, etc.)
        details: Event details as dict (auto-JSON serialized)
        reason: Human-readable reason for the event
        resolved: Is the event resolved

    Returns:
        Inserted event ID, or None if error
    """
    pool = get_pool()
    if pool is None:
        logger.debug(f"[DB] Safety event skipped (no pool): {event_type}")
        return None

    query = """
        INSERT INTO safety_events (
            event_type, reason, details, resolved
        ) VALUES (
            $1, $2, $3, $4
        )
        RETURNING id
    """

    details_json = json.dumps(details or {}) if details else None

    params = (
        event_type,
        reason,
        details_json,
        resolved,
    )

    event_id = await execute_insert(query, *params)
    if event_id:
        logger.info(f"[DB] Safety event {event_id}: {event_type} — {reason or ''}")
    return event_id


# ── Alerts (Notifications) ─────────────────────────────────────────────────


async def insert_alert(
    level: str,
    title: str,
    body: str = None,
    source: str = None,
) -> Optional[int]:
    """
    Insert an alert (info, warning, critical).

    Args:
        level: Alert level (info, warning, critical)
        title: Alert title
        body: Alert body text
        source: Source agent/system

    Returns:
        Inserted alert ID, or None if error
    """
    pool = get_pool()
    if pool is None:
        return None

    query = """
        INSERT INTO alerts (level, title, body, source)
        VALUES ($1, $2, $3, $4)
        RETURNING id
    """

    params = (level, title, body, source)

    return await execute_insert(query, *params)


# ── Queries (Read Operations) ──────────────────────────────────────────────


async def get_recent_orders(
    symbol: str = None,
    limit: int = 50,
) -> list:
    """
    Get recent orders.

    Args:
        symbol: Filter by symbol (optional)
        limit: Max rows to return

    Returns:
        List of order dicts
    """
    pool = get_pool()
    if pool is None:
        return []

    if symbol:
        query = """
            SELECT * FROM orders
            WHERE symbol = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await execute(query, symbol, limit)
    else:
        query = """
            SELECT * FROM orders
            ORDER BY created_at DESC
            LIMIT $1
        """
        rows = await execute(query, limit)

    return [dict(row) for row in rows] if rows else []


async def get_recent_decisions(
    agent_name: str = None,
    symbol: str = None,
    limit: int = 50,
) -> list:
    """
    Get recent agent decisions.

    Args:
        agent_name: Filter by agent (optional)
        symbol: Filter by symbol (optional)
        limit: Max rows

    Returns:
        List of decision dicts
    """
    pool = get_pool()
    if pool is None:
        return []

    if agent_name and symbol:
        query = """
            SELECT * FROM agent_decisions
            WHERE agent_name = $1 AND symbol = $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        rows = await execute(query, agent_name, symbol, limit)
    elif agent_name:
        query = """
            SELECT * FROM agent_decisions
            WHERE agent_name = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await execute(query, agent_name, limit)
    elif symbol:
        query = """
            SELECT * FROM agent_decisions
            WHERE symbol = $1
            ORDER BY created_at DESC
            LIMIT $2
        """
        rows = await execute(query, symbol, limit)
    else:
        query = """
            SELECT * FROM agent_decisions
            ORDER BY created_at DESC
            LIMIT $1
        """
        rows = await execute(query, limit)

    return [dict(row) for row in rows] if rows else []


async def get_daily_pnl(date: str) -> Optional[dict]:
    """
    Get daily P&L summary for a given date.

    Args:
        date: Date string (YYYY-MM-DD)

    Returns:
        Dict with daily metrics, or None if not found
    """
    pool = get_pool()
    if pool is None:
        return None

    query = """
        SELECT * FROM performance_daily
        WHERE trade_date = $1::DATE
    """

    return await execute_one(query, date)


async def get_portfolio_snapshots(
    limit: int = 10,
) -> list:
    """
    Get recent portfolio snapshots.

    Args:
        limit: Max rows to return

    Returns:
        List of snapshot dicts
    """
    pool = get_pool()
    if pool is None:
        return []

    query = """
        SELECT * FROM portfolio_snapshots
        ORDER BY captured_at DESC
        LIMIT $1
    """

    rows = await execute(query, limit)
    return [dict(row) for row in rows] if rows else []


async def get_safety_events(
    resolved: bool = False,
    limit: int = 50,
) -> list:
    """
    Get safety events.

    Args:
        resolved: Filter by resolved status
        limit: Max rows

    Returns:
        List of event dicts
    """
    pool = get_pool()
    if pool is None:
        return []

    query = """
        SELECT * FROM safety_events
        WHERE resolved = $1
        ORDER BY created_at DESC
        LIMIT $2
    """

    rows = await execute(query, resolved, limit)
    return [dict(row) for row in rows] if rows else []
