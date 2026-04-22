"""
JARVIS TRADER — Settings Mixin
================================
DatabaseManager mixin providing CRUD methods for the settings key/value table.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ._helpers import _from_json, _to_json, _utcnow

logger = logging.getLogger("jarvis_trader.database")


class SettingsMixin:
    """Methods for the ``settings`` key/value table."""

    def set_setting(self, key: str, value: Any) -> None:
        """
        Store a key/value setting.

        ``value`` can be any JSON-serialisable type.  Dicts and lists are
        automatically serialised.  The row is inserted or replaced.
        """
        sql = """
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, (key, _to_json(value), _utcnow()))
                conn.commit()
                logger.debug(f"[DB] set_setting key={key!r}")
            finally:
                conn.close()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a setting by key.

        Returns ``default`` if the key does not exist.  JSON values are
        automatically deserialised.
        """
        sql = "SELECT value FROM settings WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (key,)).fetchone()
                if row is None:
                    return default
                return _from_json(row["value"])
            finally:
                conn.close()

    def get_all_settings(self) -> Dict[str, Any]:
        """Return all settings as a plain dict {key: value}."""
        sql = "SELECT key, value FROM settings ORDER BY key ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
                return {r["key"]: _from_json(r["value"]) for r in rows}
            finally:
                conn.close()

    def delete_setting(self, key: str) -> bool:
        """Delete a setting by key.  Returns True if it existed."""
        sql = "DELETE FROM settings WHERE key = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
