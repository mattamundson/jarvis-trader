"""
JARVIS TRADER -- DatabaseManager
==================================
Assembles all mixin classes into a single thread-safe DatabaseManager.

Design decisions
----------------
* No ORM -- plain sqlite3 for zero extra dependencies.
* Connection-per-call pattern: each public method opens a connection,
  executes, commits, and closes.  This avoids shared-connection threading
  hazards without the complexity of a connection pool.
* A threading.Lock serialises concurrent writes (rare in practice, since
  FastAPI runs in one event loop, but the lock makes this safe if helpers
  are ever called from background threads or APScheduler jobs).
* WAL journal mode is set on each new connection for better read concurrency.
* All timestamps are stored as ISO-8601 UTC strings ("YYYY-MM-DDTHH:MM:SS").
* JSON blobs (signal_data_json, strategy_params) are stored as TEXT;
  callers pass pre-serialised strings or dicts (auto-serialised here).

Tables
------
  paper_trades   -- individual trade records (open & closed)
  decisions      -- pipeline decision log with agent reasoning
  daily_pnl      -- end-of-day P&L snapshots
  positions      -- current open positions (live mirror)
  settings       -- key/value config store
  pipeline_runs  -- history of every TradingPipeline execution
  system_state   -- key/value persistence (e.g. kill switch across restarts)
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._mixins_alerts import AlertsMixin
from ._mixins_analytics import AnalyticsMixin
from ._mixins_canaries import CanariesMixin
from ._mixins_decisions import DecisionsMixin
from ._mixins_journal import JournalMixin
from ._mixins_llm_costs import LLMCostsMixin
from ._mixins_memory import MemoryMixin
from ._mixins_pending_approvals import PendingApprovalsMixin
from ._mixins_pnl import DailyPnLMixin
from ._mixins_positions import PositionsMixin
from ._mixins_reviews import ReviewsMixin
from ._mixins_settings import SettingsMixin
from ._mixins_system_state import SystemStateMixin
from ._mixins_trades import TradesMixin
from .migrations import run_migrations

logger = logging.getLogger("jarvis_trader.database")


class DatabaseManager(
    TradesMixin,
    AnalyticsMixin,
    CanariesMixin,
    DecisionsMixin,
    DailyPnLMixin,
    PositionsMixin,
    SettingsMixin,
    SystemStateMixin,
    JournalMixin,
    AlertsMixin,
    PendingApprovalsMixin,
    LLMCostsMixin,
    ReviewsMixin,
    MemoryMixin,
):
    """
    Thread-safe SQLite manager for JARVIS TRADER.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Defaults to ``data/jarvis_trader.db``
        relative to the *engine* package root (i.e. one directory above
        this file's parent).
    """

    def __init__(self, db_path: str = "data/jarvis_trader.db") -> None:
        # Resolve relative paths against the engine root (two levels up from here)
        engine_root = Path(__file__).parent.parent
        self._db_path: Path = (
            Path(db_path) if Path(db_path).is_absolute() else engine_root / db_path
        )
        self._lock = threading.Lock()
        logger.info(f"DatabaseManager initialised -- db_path={self._db_path}")

    # -- Internal connection factory ------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """
        Open a new SQLite connection to the database file.

        * Creates parent directories if they do not exist.
        * Enables WAL journal mode for better concurrent read performance.
        * Sets row_factory so rows behave like dicts (sqlite3.Row).
        * Enables foreign-key enforcement.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, faster than FULL
        conn.execute("PRAGMA cache_size=10000")  # 10000 pages ≈ 40 MB default page size
        conn.execute("PRAGMA temp_store=MEMORY")  # keep temp tables in RAM
        return conn

    # -- Lifecycle ------------------------------------------------------------

    def initialize(self) -> None:
        """
        Create tables (if not present) and run any pending migrations.

        Safe to call multiple times -- all operations are idempotent.
        Should be called once at application startup before any other method.
        """
        logger.info("Initialising database schema...")
        with self._lock:
            conn = self._connect()
            try:
                run_migrations(conn)
            finally:
                conn.close()
        logger.info(f"Database ready at {self._db_path}")

    # -- Diagnostics ----------------------------------------------------------

    # -- Low-level Query API (Safe wrappers) ----------------------------------
    # Use these for custom queries in learning/consolidator modules where
    # a dedicated mixin method doesn't yet exist.

    def execute(self, sql: str, params: tuple = ()) -> int:
        """
        Execute a DML/DDL statement (INSERT, UPDATE, DELETE, CREATE).
        Returns the number of rows affected (rowcount).
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute a query and return the first row as a dict, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def health_check(self) -> Dict[str, Any]:
        """
        Return a dict with row counts per table and the current schema version.

        Useful for the /health or /status endpoints.
        """
        tables = [
            "paper_trades",
            "decisions",
            "daily_pnl",
            "positions",
            "settings",
            "trade_journal",
            "pipeline_runs",
            "agent_memory",
        ]
        counts: Dict[str, int] = {}
        schema_version: int = 0

        with self._lock:
            conn = self._connect()
            try:
                for table in tables:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    counts[table] = row["n"] if row else 0
                sv_row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
                if sv_row and sv_row["v"] is not None:
                    schema_version = sv_row["v"]
            finally:
                conn.close()

        return {
            "db_path": str(self._db_path),
            "schema_version": schema_version,
            "row_counts": counts,
        }

    def ping(self) -> bool:
        """Cheap liveness probe: is the database reachable?

        `health_check()` runs 8 full COUNT(*) scans (whole-table on a 325MB DB) and
        is the dominant cost of a cold /health call — but /health only needs to know
        the DB answers, not the row counts. `SELECT 1` is O(1). Raises on failure so
        the caller can distinguish reachable from not.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("SELECT 1").fetchone()
                return True
            finally:
                conn.close()


# -- Singleton factory --------------------------------------------------------

_db_instance: Optional[DatabaseManager] = None
_db_lock = threading.Lock()


def init_db(db_path: Optional[str] = None) -> DatabaseManager:
    """
    Create (or return) the module-level DatabaseManager singleton and
    ensure the schema is up-to-date.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Only used on the *first* call; subsequent
        calls return the already-created singleton regardless of db_path.
        Defaults to ``data/jarvis_trader.db`` relative to the engine root.

    Returns
    -------
    DatabaseManager
        The initialised singleton instance.
    """
    global _db_instance
    with _db_lock:
        if _db_instance is None:
            kwargs: dict = {}
            if db_path is not None:
                kwargs["db_path"] = db_path
            _db_instance = DatabaseManager(**kwargs)
            _db_instance.initialize()
            logger.info("Database singleton created and initialised.")
        return _db_instance


def get_db() -> DatabaseManager:
    """
    Return the existing DatabaseManager singleton.

    Raises
    ------
    RuntimeError
        If ``init_db()`` has not been called yet.
    """
    if _db_instance is None:
        raise RuntimeError(
            "DatabaseManager has not been initialised.  "
            "Call init_db() before using this function."
        )
    return _db_instance
