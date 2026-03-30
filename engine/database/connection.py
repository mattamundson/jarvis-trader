"""
PostgreSQL Connection Pool Manager
===================================
Async connection pooling for JARVIS TRADER trade logging.

Provides graceful fallback if Postgres is unavailable — the system
logs warnings but continues to operate without crashing.
"""
import asyncio
import logging
from typing import Optional

import asyncpg
from asyncpg import Pool

from config import settings

logger = logging.getLogger(__name__)

__all__ = ["init_pool", "close_pool", "get_pool"]


# Global pool reference
_pool: Optional[Pool] = None


async def init_pool() -> Optional[Pool]:
    """
    Initialize async PostgreSQL connection pool.

    Returns:
        Pool instance on success, None if Postgres is unavailable.
        The system will degrade gracefully — all database operations
        will return None or skip silently if pool is unavailable.

    Raises:
        Nothing — always returns gracefully. Logs warnings if connection fails.
    """
    global _pool

    if _pool is not None:
        logger.info("[DB] Pool already initialized")
        return _pool

    try:
        # Parse connection string and create pool
        logger.info(f"[DB] Initializing PostgreSQL pool from {settings.POSTGRES_URL[:50]}...")

        _pool = await asyncpg.create_pool(
            settings.POSTGRES_URL,
            min_size=2,
            max_size=10,
            command_timeout=10,
            max_cached_statement_lifetime=3600,
            max_cacheable_statement_size=15000,
        )

        logger.info("[DB] PostgreSQL connection pool initialized successfully")
        logger.info(f"[DB] Pool: min={_pool._minsize}, max={_pool._maxsize}")

        return _pool

    except asyncpg.InvalidCatalogNameError as e:
        logger.error(f"[DB] Database does not exist: {e}")
        logger.error("[DB] HINT: Run `createdb jarvis_trader` or ensure PostgreSQL is running")
        return None

    except asyncpg.CannotConnectNowError as e:
        logger.warning(f"[DB] PostgreSQL server not available (will retry): {e}")
        logger.warning("[DB] JARVIS TRADER will continue in degraded mode (no persistent logging)")
        return None

    except (asyncpg.PostgresError, asyncpg.ConnectionDoesNotExistError) as e:
        logger.warning(f"[DB] PostgreSQL connection error: {e}")
        logger.warning("[DB] Trade logging disabled — system will continue")
        return None

    except Exception as e:
        logger.warning(f"[DB] Unexpected error initializing pool: {e}")
        logger.warning("[DB] Trade logging disabled — system will continue")
        return None


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool

    if _pool is None:
        return

    try:
        await _pool.close()
        logger.info("[DB] PostgreSQL pool closed")
        _pool = None
    except Exception as e:
        logger.error(f"[DB] Error closing pool: {e}")


def get_pool() -> Optional[Pool]:
    """
    Get the current connection pool.

    Returns:
        Pool instance or None if unavailable.
    """
    return _pool


async def execute(
    query: str,
    *args,
    timeout: float = 10.0,
) -> Optional[list]:
    """
    Execute a query and return rows.

    Args:
        query: SQL query string (use $1, $2 for parameters)
        *args: Query parameters
        timeout: Command timeout in seconds

    Returns:
        List of rows (as asyncpg.Record objects) or None if pool unavailable
    """
    pool = get_pool()
    if pool is None:
        logger.warning(f"[DB] Query skipped (no pool): {query[:50]}")
        return None

    try:
        async with pool.acquire() as conn:
            return await asyncio.wait_for(
                conn.fetch(query, *args),
                timeout=timeout
            )
    except asyncio.TimeoutError:
        logger.error(f"[DB] Query timeout (>10s): {query[:50]}")
        return None
    except Exception as e:
        logger.error(f"[DB] Query failed: {e}")
        logger.debug(f"[DB] Query: {query[:100]}")
        return None


async def execute_one(
    query: str,
    *args,
    timeout: float = 10.0,
) -> Optional[dict]:
    """
    Execute a query and return single row as dict.

    Args:
        query: SQL query string
        *args: Query parameters
        timeout: Command timeout in seconds

    Returns:
        Single row as dict, or None if no rows or error
    """
    pool = get_pool()
    if pool is None:
        return None

    try:
        async with pool.acquire() as conn:
            record = await asyncio.wait_for(
                conn.fetchrow(query, *args),
                timeout=timeout
            )
            return dict(record) if record else None
    except asyncio.TimeoutError:
        logger.error(f"[DB] Query timeout: {query[:50]}")
        return None
    except Exception as e:
        logger.error(f"[DB] Query failed: {e}")
        return None


async def execute_insert(
    query: str,
    *args,
    timeout: float = 10.0,
) -> Optional[int]:
    """
    Execute an INSERT query with RETURNING id.

    Args:
        query: SQL INSERT query with RETURNING id
        *args: Query parameters
        timeout: Command timeout

    Returns:
        Inserted record ID, or None on error
    """
    pool = get_pool()
    if pool is None:
        logger.debug(f"[DB] INSERT skipped (no pool)")
        return None

    try:
        async with pool.acquire() as conn:
            record = await asyncio.wait_for(
                conn.fetchrow(query, *args),
                timeout=timeout
            )
            return record[0] if record else None
    except asyncio.TimeoutError:
        logger.error(f"[DB] INSERT timeout: {query[:50]}")
        return None
    except Exception as e:
        logger.error(f"[DB] INSERT failed: {e}")
        logger.debug(f"[DB] Query: {query[:100]}")
        return None


async def execute_many(
    query: str,
    args_list: list,
    timeout: float = 10.0,
) -> bool:
    """
    Execute a query with multiple parameter sets (bulk insert).

    Args:
        query: SQL query string
        args_list: List of parameter tuples
        timeout: Command timeout

    Returns:
        True if successful, False otherwise
    """
    pool = get_pool()
    if pool is None:
        logger.debug(f"[DB] Bulk insert skipped (no pool) — {len(args_list)} rows")
        return False

    if not args_list:
        return True

    try:
        async with pool.acquire() as conn:
            await asyncio.wait_for(
                conn.executemany(query, args_list),
                timeout=timeout
            )
            logger.debug(f"[DB] Bulk insert: {len(args_list)} rows")
            return True
    except asyncio.TimeoutError:
        logger.error(f"[DB] Bulk insert timeout — {len(args_list)} rows")
        return False
    except Exception as e:
        logger.error(f"[DB] Bulk insert failed: {e}")
        return False
