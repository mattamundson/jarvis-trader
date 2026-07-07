"""
JARVIS TRADER — System State Mixin
====================================
DatabaseManager mixin providing CRUD methods for the system_state key/value
table.  Used to persist safety-critical engine state (e.g. kill switch) across
process restarts.
"""

from __future__ import annotations

import logging
from typing import Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class SystemStateMixin:
    """Methods for the ``system_state`` key/value table."""

    def get_system_state(self, key: str) -> Optional[str]:
        """
        Retrieve a system state value by key.

        Returns None if the key does not exist.
        Values are always raw TEXT strings — no JSON deserialisation.
        """
        sql = "SELECT value FROM system_state WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (key,)).fetchone()
                return row["value"] if row is not None else None
            finally:
                conn.close()

    def set_system_state(self, key: str, value: str) -> None:
        """
        Store a system state key/value pair.

        Performs an upsert (INSERT OR REPLACE).  The updated_at timestamp is
        set to the current UTC time automatically.
        """
        sql = """
            INSERT OR REPLACE INTO system_state (key, value, updated_at)
            VALUES (?, ?, ?)
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, (key, value, _utcnow()))
                conn.commit()
                logger.debug("[DB] set_system_state key=%r", key)
            finally:
                conn.close()

    def delete_system_state(self, key: str) -> bool:
        """Delete a system state key.  Returns True if it existed."""
        sql = "DELETE FROM system_state WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
