"""Session/thread persistence ported from Goose crates/goose/src/session/session_manager.rs.

Hierarchical Session -> Thread -> ThreadMessage for JARVIS debate pipeline.
Standalone — no engine imports. Caller provides the DB path.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

MIGRATION_SQL = """-- Goose-inspired session/thread persistence for JARVIS debate pipeline
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  agent_name TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS thread_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  agent_visible INTEGER NOT NULL DEFAULT 1,
  user_visible INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id)
);

CREATE INDEX IF NOT EXISTS idx_threads_session ON threads(session_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages_thread ON thread_messages(thread_id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotent — safe to call on every connection."""
    conn.executescript(MIGRATION_SQL)
    conn.commit()


class SessionManager:
    """Thread-safe session/thread/message persistence for debate pipeline.

    Usage:
        manager = SessionManager("/path/to/db.sqlite")
        session_id = manager.create_session("my_run", metadata={"instrument": "MCL"})
        thread_id = manager.create_thread(session_id, "bull_researcher")
        msg_id = manager.append_message(thread_id, "user", "What's the bullish case?")
        messages = manager.get_thread_messages(thread_id)
        manager.close_session(session_id)
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self._connect() as conn:
            ensure_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_session(self, name: str, metadata: Optional[dict] = None) -> int:
        """Create a new session.

        Args:
            name: Session name (e.g., "2026-04-10_MCL_bullcase")
            metadata: Optional dict to store (JSON-serialized)

        Returns:
            session_id as int
        """
        now = time.time()
        meta_json = json.dumps(metadata) if metadata else None
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sessions(name, created_at, updated_at, metadata_json) VALUES (?,?,?,?)",
                (name, now, now, meta_json),
            )
            conn.commit()
            return cur.lastrowid

    def create_thread(self, session_id: int, agent_name: str) -> int:
        """Create a thread under a session.

        Args:
            session_id: Parent session ID
            agent_name: Name of the agent (e.g., "bull_researcher", "bear_researcher")

        Returns:
            thread_id as int
        """
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO threads(session_id, agent_name, created_at) VALUES (?,?,?)",
                (session_id, agent_name, now),
            )
            conn.commit()
            return cur.lastrowid

    def append_message(
        self,
        thread_id: int,
        role: str,
        content: str,
        agent_visible: bool = True,
        user_visible: bool = True,
    ) -> int:
        """Append a message to a thread.

        Args:
            thread_id: Parent thread ID
            role: Message role (e.g., "user", "assistant", "system")
            content: Message text
            agent_visible: Whether visible to agents (default True)
            user_visible: Whether visible to end-user (default True)

        Returns:
            message_id as int
        """
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO thread_messages
                   (thread_id, role, content, agent_visible, user_visible, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (thread_id, role, content, int(agent_visible), int(user_visible), now),
            )
            conn.commit()
            return cur.lastrowid

    def list_threads(
        self, session_id: int, visibility: Optional[str] = None
    ) -> list[dict]:
        """List threads in a session.

        Args:
            session_id: Parent session ID
            visibility: None (all), 'agent' (only threads with agent_visible==1 messages),
                       'user' (only threads with user_visible==1 messages)

        Returns:
            List of dicts with keys: id, session_id, agent_name, created_at
        """
        with self._connect() as conn:
            if visibility is None:
                query = "SELECT id, session_id, agent_name, created_at FROM threads WHERE session_id = ? ORDER BY id"
                cur = conn.execute(query, (session_id,))
            elif visibility == "agent":
                query = """SELECT DISTINCT t.id, t.session_id, t.agent_name, t.created_at
                           FROM threads t
                           WHERE t.session_id = ?
                             AND EXISTS (
                               SELECT 1 FROM thread_messages tm
                               WHERE tm.thread_id = t.id AND tm.agent_visible = 1
                             )
                           ORDER BY t.id"""
                cur = conn.execute(query, (session_id,))
            elif visibility == "user":
                query = """SELECT DISTINCT t.id, t.session_id, t.agent_name, t.created_at
                           FROM threads t
                           WHERE t.session_id = ?
                             AND EXISTS (
                               SELECT 1 FROM thread_messages tm
                               WHERE tm.thread_id = t.id AND tm.user_visible = 1
                             )
                           ORDER BY t.id"""
                cur = conn.execute(query, (session_id,))
            else:
                raise ValueError(f"Invalid visibility filter: {visibility}")

            return [dict(row) for row in cur.fetchall()]

    def get_thread_messages(
        self, thread_id: int, visibility: Optional[str] = None
    ) -> list[dict]:
        """Get messages in a thread.

        Args:
            thread_id: Thread ID
            visibility: None (all), 'agent' (only agent_visible==1),
                       'user' (only user_visible==1)

        Returns:
            List of dicts with keys: id, thread_id, role, content,
                                     agent_visible, user_visible, created_at
        """
        with self._connect() as conn:
            if visibility is None:
                query = """SELECT id, thread_id, role, content, agent_visible, user_visible, created_at
                          FROM thread_messages WHERE thread_id = ? ORDER BY created_at"""
                cur = conn.execute(query, (thread_id,))
            elif visibility == "agent":
                query = """SELECT id, thread_id, role, content, agent_visible, user_visible, created_at
                          FROM thread_messages WHERE thread_id = ? AND agent_visible = 1 ORDER BY created_at"""
                cur = conn.execute(query, (thread_id,))
            elif visibility == "user":
                query = """SELECT id, thread_id, role, content, agent_visible, user_visible, created_at
                          FROM thread_messages WHERE thread_id = ? AND user_visible = 1 ORDER BY created_at"""
                cur = conn.execute(query, (thread_id,))
            else:
                raise ValueError(f"Invalid visibility filter: {visibility}")

            return [dict(row) for row in cur.fetchall()]

    def close_session(self, session_id: int) -> None:
        """Mark a session as closed (update updated_at timestamp).

        Args:
            session_id: Session ID to close
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()


# Wired via engine/services/agent_gateway.py:GatewaySessionStore.
# Architecture pivoted from per-pipeline-run scope to per-messaging-channel
# scope — each (channel, user_id, agent) gets a persistent session and thread
# so conversational history survives across pipeline invocations.
# close_session is intentionally not called: channel sessions are long-lived.
