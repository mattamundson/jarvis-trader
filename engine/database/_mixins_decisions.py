"""
JARVIS TRADER — Decisions Mixin
=================================
DatabaseManager mixin providing CRUD methods for the decisions table.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ._helpers import _from_json, _to_json, _utcnow

logger = logging.getLogger("jarvis_trader.database")


class DecisionsMixin:
    """Methods for the ``decisions`` table."""

    def insert_decision(
        self,
        *,
        symbol: str,
        action: str,
        confidence: Optional[float] = None,
        regime: Optional[str] = None,
        signal_data: Optional[Any] = None,
        reasoning: Optional[str] = None,
        timestamp: Optional[str] = None,
        full_pipeline_data: Optional[Any] = None,
    ) -> int:
        """
        Log a pipeline decision.

        Parameters
        ----------
        symbol:             Ticker symbol (e.g. "AAPL").
        action:             Decision string: "buy" | "sell" | "hold" | "exit_long" | "exit_short".
        confidence:         Agent confidence score in [0.0, 1.0].
        regime:             Market regime label at decision time (e.g. "bullish", "ranging").
        signal_data:        Dict or JSON string of raw indicator values / agent scores.
        reasoning:          Full LLM reasoning text.
        timestamp:          ISO-8601 UTC; defaults to now.
        full_pipeline_data: Complete pipeline result dict — all 5 stage outputs stored as JSON.
                            Enables GET /decisions/{id}/detail to return the full breakdown.

        Returns the auto-incremented ``id``.
        """
        ts = timestamp or _utcnow()
        sql = """
            INSERT INTO decisions
                (symbol, timestamp, action, confidence, regime, signal_data_json, reasoning,
                 full_pipeline_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            symbol.upper(),
            ts,
            action.lower(),
            confidence,
            regime,
            _to_json(signal_data),
            reasoning,
            _to_json(full_pipeline_data),
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_decision id={row_id} symbol={symbol} "
                    f"action={action} confidence={confidence}"
                )
                return row_id
            finally:
                conn.close()

    def get_decisions(
        self,
        symbol: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Query the decisions log.

        Parameters
        ----------
        symbol: Filter by ticker (optional).
        action: Filter by action type (optional).
        limit:  Maximum rows to return (default 100).

        JSON fields (signal_data_json) are deserialised before returning.
        """
        clauses = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if action:
            clauses.append("action = ?")
            params.append(action.lower())

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM decisions {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["signal_data_json"] = _from_json(d.get("signal_data_json"))
                    result.append(d)
                return result
            finally:
                conn.close()

    def get_decision_by_id(self, decision_id: int) -> Optional[Dict]:
        """
        Fetch a single decision row by primary key, deserialising all JSON fields.

        Returns the row dict (including full_pipeline_json as a parsed dict),
        or None if not found.
        """
        sql = "SELECT * FROM decisions WHERE id = ? LIMIT 1"
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (decision_id,)).fetchone()
                if row is None:
                    return None
                d = dict(row)
                d["signal_data_json"] = _from_json(d.get("signal_data_json"))
                d["full_pipeline_json"] = _from_json(d.get("full_pipeline_json"))
                return d
            finally:
                conn.close()
