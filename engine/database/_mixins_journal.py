"""
JARVIS TRADER -- Journal Mixin
================================
DatabaseManager mixin providing CRUD methods for the trade_journal
and journal_notes tables.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class JournalMixin:
    """Methods for the ``trade_journal`` and ``journal_notes`` tables."""

    # -- trade_journal --------------------------------------------------------

    def add_journal_entry(
        self,
        trade_id: str,
        note: str,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
        timestamp: Optional[str] = None,
        regime_tier: Optional[int] = None,
        deciding_stage: Optional[str] = None,
        bull_score: Optional[float] = None,
        bear_score: Optional[float] = None,
        debate_confidence: Optional[float] = None,
        timeframe: Optional[str] = None,
    ) -> int:
        """
        Insert a new journal entry linked to a trade.

        Parameters
        ----------
        trade_id:   UUID of the associated paper trade (soft FK, not enforced).
        note:       Free-text journal body.
        tags:       Comma-separated tag string, e.g. "missed_entry,good_setup".
        mood:       One of "confident", "uncertain", "frustrated", "neutral".
        lesson:     What was learned from this trade.
        timestamp:  ISO-8601 UTC; defaults to now.
        regime_tier:        Market regime tier at decision (optional).
        deciding_stage:     Pipeline stage that drove decision (optional).
        bull_score:         Bull researcher score (optional).
        bear_score:         Bear researcher score (optional).
        debate_confidence:  Debate stage confidence (optional).
        timeframe:          Signal timeframe ('1h' or '15m', optional).

        Returns the auto-incremented ``id`` of the new row.
        """
        ts = timestamp or _utcnow()
        sql = """
            INSERT INTO trade_journal
                (trade_id, timestamp, note, tags, mood, lesson,
                 regime_tier, deciding_stage, bull_score, bear_score, debate_confidence, timeframe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            trade_id,
            ts,
            note,
            tags,
            mood,
            lesson,
            regime_tier,
            deciding_stage,
            bull_score,
            bear_score,
            debate_confidence,
            timeframe,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(f"[DB] add_journal_entry id={row_id} trade_id={trade_id[:8]}")
                return row_id
            finally:
                conn.close()

    def get_journal_entries(
        self,
        trade_id: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Return journal entries, optionally filtered by trade_id and/or tag.

        Parameters
        ----------
        trade_id:  If provided, return only entries for this trade UUID.
        tag:       If provided, return only entries whose tags column contains
                   this exact tag token (case-insensitive substring match on
                   comma-separated list).
        limit:     Maximum number of rows to return (default 50).

        Results are ordered newest-first.
        """
        clauses: list = []
        params: list = []
        if trade_id:
            clauses.append("trade_id = ?")
            params.append(trade_id)
        if tag:
            # Match the tag anywhere in the comma-separated tags field.
            clauses.append("(',' || LOWER(tags) || ',') LIKE ?")
            params.append(f"%,{tag.lower()},%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM trade_journal {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_journal_tags(self) -> List[str]:
        """
        Return a sorted list of unique tag tokens used across all journal entries.

        Tags are stored as comma-separated strings; this method splits every
        row and deduplicates the individual tokens.
        """
        sql = "SELECT tags FROM trade_journal WHERE tags IS NOT NULL AND tags != ''"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()

        seen: set = set()
        for row in rows:
            for token in row["tags"].split(","):
                stripped = token.strip()
                if stripped:
                    seen.add(stripped)
        return sorted(seen)

    def update_journal_entry(
        self,
        entry_id: int,
        note: Optional[str] = None,
        tags: Optional[str] = None,
        mood: Optional[str] = None,
        lesson: Optional[str] = None,
    ) -> bool:
        """
        Partially update a journal entry.  Only supplied (non-None) fields
        are changed.  Returns True if the row existed, False otherwise.
        """
        set_clauses: list = []
        params: list = []
        if note is not None:
            set_clauses.append("note = ?")
            params.append(note)
        if tags is not None:
            set_clauses.append("tags = ?")
            params.append(tags)
        if mood is not None:
            set_clauses.append("mood = ?")
            params.append(mood)
        if lesson is not None:
            set_clauses.append("lesson = ?")
            params.append(lesson)

        if not set_clauses:
            return True  # nothing to update, treat as no-op success

        params.append(entry_id)
        sql = f"UPDATE trade_journal SET {', '.join(set_clauses)} WHERE id = ?"

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    logger.debug(f"[DB] update_journal_entry id={entry_id}")
                return updated
            finally:
                conn.close()

    def delete_journal_entry(self, entry_id: int) -> bool:
        """
        Delete a journal entry by its integer primary key.
        Returns True if a row was deleted, False if id was not found.
        """
        sql = "DELETE FROM trade_journal WHERE id = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (entry_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.debug(f"[DB] delete_journal_entry id={entry_id}")
                return deleted
            finally:
                conn.close()

    # -- journal_notes --------------------------------------------------------

    def insert_journal_note(
        self,
        note_type: str,
        title: str,
        body: str = "",
        tags: Optional[List] = None,
        trade_id: Optional[str] = None,
    ) -> int:
        """
        Insert a new journal note.

        Parameters
        ----------
        note_type:  One of "observation", "lesson", "alert".
        title:      Short title for the note (required).
        body:       Free-text body (optional).
        tags:       List of tag strings; stored as JSON array.
        trade_id:   Optional UUID of a linked paper trade (soft FK).

        Returns the auto-incremented ``id`` of the new row.
        """
        now = _utcnow()
        sql = """
            INSERT INTO journal_notes
                (trade_id, note_type, title, body, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            trade_id,
            note_type,
            title,
            body,
            json.dumps(tags or []),
            now,
            now,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                row_id: int = cur.lastrowid  # type: ignore[assignment]
                logger.debug(
                    f"[DB] insert_journal_note id={row_id} type={note_type} title={title!r}"
                )
                return row_id
            finally:
                conn.close()

    def get_journal_notes(
        self,
        limit: int = 50,
        note_type: Optional[str] = None,
        trade_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Return journal notes, newest first.

        Parameters
        ----------
        limit:      Maximum rows to return (default 50, capped at 200).
        note_type:  Filter by type -- "observation" | "lesson" | "alert".
        trade_id:   Filter to notes linked to a specific paper trade.

        ``tags`` is deserialised from JSON array before returning.
        """
        conditions: list = []
        params: list = []
        if note_type:
            conditions.append("note_type = ?")
            params.append(note_type)
        if trade_id:
            conditions.append("trade_id = ?")
            params.append(trade_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(min(limit, 200))

        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    f"SELECT * FROM journal_notes {where} ORDER BY created_at DESC LIMIT ?",
                    params,
                )
                col_names = [d[0] for d in cursor.description]
                notes = []
                for row in cursor.fetchall():
                    note = dict(zip(col_names, row, strict=False))
                    try:
                        note["tags"] = json.loads(note.get("tags") or "[]")
                    except Exception:
                        note["tags"] = []
                    notes.append(note)
                return notes
            finally:
                conn.close()

    def delete_journal_note(self, note_id: int) -> bool:
        """
        Delete a journal note by its integer primary key.
        Returns True if a row was deleted, False if id was not found.
        """
        sql = "DELETE FROM journal_notes WHERE id = ?"
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, (note_id,))
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    logger.debug(f"[DB] delete_journal_note id={note_id}")
                return deleted
            finally:
                conn.close()
