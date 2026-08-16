"""
JARVIS TRADER -- Alerts Mixin
================================
DatabaseManager mixin providing CRUD methods for the alert_log table
and pipeline_runs table.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class AlertsMixin:
    """Methods for the ``alert_log`` and ``pipeline_runs`` tables."""

    # -- alert_log ------------------------------------------------------------

    def insert_alert_log(
        self,
        alert_type: str,
        message: str,
        channel: str = "whatsapp",
        symbol: Optional[str] = None,
        status: str = "sent",
        error: Optional[str] = None,
    ) -> int:
        """
        Insert an alert log row and return the new auto-incremented id.

        Parameters
        ----------
        alert_type:
            Category of alert -- e.g. 'trade_opened', 'trade_closed',
            'morning_briefing', 'vix_alert', 'circuit_breaker', 'notification'.
        message:
            The full message text that was sent (or attempted).
        channel:
            Delivery channel, default 'whatsapp'.
        symbol:
            Optional ticker symbol (None for non-trade alerts).
        status:
            ``sent`` | ``failed`` | ``suppressed`` | ``suppressed_cooldown`` (pipeline rate limit)
        error:
            Error text when status='failed', None otherwise.
        """
        created_at = _utcnow()
        sql = """
            INSERT INTO alert_log (alert_type, symbol, message, channel, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (alert_type, symbol, message, channel, status, error, created_at)
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                new_id = cur.lastrowid
                logger.debug(
                    f"[DB] insert_alert_log id={new_id} type={alert_type} "
                    f"status={status} symbol={symbol}"
                )
                return new_id
            finally:
                conn.close()

    def get_alert_history(
        self,
        limit: int = 100,
        alert_type: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return alert log rows ordered newest-first.

        Parameters
        ----------
        limit:
            Maximum rows to return (default 100, hard-capped by the caller).
        alert_type:
            If supplied, filter to rows with this alert_type value.

        Returns
        -------
        list[dict]
            Each dict contains: id, alert_type, symbol, message, channel,
            status, error, created_at.
        """
        conditions: list = []
        params: list = []
        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(min(limit, 500))

        sql = f"""
            SELECT id, alert_type, symbol, message, channel, status, error, created_at
            FROM alert_log
            {where}
            ORDER BY created_at DESC
            LIMIT ?
        """
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(sql, params)
                col_names = [d[0] for d in cursor.description]
                return [dict(zip(col_names, row, strict=False)) for row in cursor.fetchall()]
            finally:
                conn.close()

    def count_alert_history(
        self,
        alert_type: Optional[str] = None,
    ) -> int:
        """
        Return the TRUE total row count for ``alert_log``, ignoring any
        pagination ``limit`` -- i.e. ``SELECT COUNT(*)``, not
        ``len(get_alert_history(limit=...))``.

        Parameters mirror :meth:`get_alert_history` (minus ``limit``) so the
        count reflects the same filter the caller applied to the page.
        """
        conditions: list = []
        params: list = []
        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"SELECT COUNT(*) AS n FROM alert_log {where}"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    # -- pipeline_runs --------------------------------------------------------

    def insert_pipeline_run(self, run_data: dict) -> int:
        """
        Insert a pipeline run record and return the auto-incremented rowid.

        Expected keys in run_data
        -------------------------
        run_id          str   -- 8-char UUID prefix (required)
        symbol          str   -- ticker (required)
        status          str   -- "completed" | "error" | "skipped" (required)
        webhook_action  str   -- "LONG" | "SHORT" | "CLOSE" | None
        source          str   -- default "tradingview"
        final_action    str   -- "buy" | "sell" | "hold" | "pending_human_approval"
        final_quantity  int   -- contract / share count
        requires_human  bool  -- whether human approval is needed
        summary         str   -- human-readable one-liner from pipeline
        error_message   str   -- populated when status="error"
        duration_ms     float -- elapsed milliseconds for the full run
        created_at      str   -- ISO-8601 UTC; defaults to now
        """
        created_at = run_data.get("created_at") or _utcnow()
        sql = """
            INSERT INTO pipeline_runs
                (run_id, symbol, webhook_action, source, final_action,
                 final_quantity, requires_human, summary, status,
                 error_message, duration_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            run_data["run_id"],
            run_data["symbol"].upper(),
            run_data.get("webhook_action"),
            run_data.get("source", "tradingview"),
            run_data.get("final_action"),
            run_data.get("final_quantity"),
            int(bool(run_data.get("requires_human", False))),
            run_data.get("summary"),
            run_data["status"],
            run_data.get("error_message"),
            run_data.get("duration_ms"),
            created_at,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_pipeline_run id={row_id} run_id={run_data['run_id']} "
                    f"symbol={run_data['symbol']} status={run_data['status']}"
                )
                return row_id
            finally:
                conn.close()

    def get_pipeline_history(
        self,
        limit: int = 50,
        symbol: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return recent pipeline run records, newest first.

        Parameters
        ----------
        limit:   Maximum rows to return (default 50, capped at 200).
        symbol:  Optional ticker filter (case-insensitive).

        Returns a list of dicts with all pipeline_runs columns.
        ``requires_human`` is cast to bool before returning.
        """
        limit = min(limit, 200)
        clauses: list = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM pipeline_runs {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["requires_human"] = bool(d.get("requires_human", 0))
                    result.append(d)
                return result
            finally:
                conn.close()
