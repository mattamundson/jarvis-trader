"""
JARVIS TRADER — Database Package
==================================
Dual-layer persistence:
  - SQLite: Fast local caching for paper trades, positions, P&L
  - PostgreSQL: Persistent trade logging with async pooling

Usage
-----
    from database import init_db, get_db
    from database.connection import init_pool
    from database import repository

    # SQLite (local)
    db = init_db()
    trade_id = db.insert_trade(symbol="AAPL", side="buy", quantity=100, entry_price=175.50)

    # PostgreSQL (persistent audit log)
    await init_pool()  # Called in app lifespan
    order_id = await repository.insert_order({"symbol": "MES", "quantity": 1, ...})
"""

from .schema import DatabaseManager, init_db, get_db

# PostgreSQL modules require asyncpg — guard for environments where
# asyncpg is not installed (e.g. paper-trading-only / backtest mode).
try:
    from . import connection
    from . import repository
    _pg_available = True
except ImportError:
    connection = None  # type: ignore[assignment]
    repository = None  # type: ignore[assignment]
    _pg_available = False

__all__ = [
    # SQLite
    "DatabaseManager",
    "init_db",
    "get_db",
    # PostgreSQL (may be None if asyncpg not installed)
    "connection",
    "repository",
    "_pg_available",
]
