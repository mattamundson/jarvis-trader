"""Tests for session_manager.py — Goose-inspired session/thread persistence.

All tests use tmp_path (pytest fixture) for isolated SQLite files.
"""
import pytest

from db.session_manager import SessionManager


def test_create_session_returns_int_id(tmp_path):
    """Verify create_session returns an int > 0."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    session_id = manager.create_session("test_session")

    assert isinstance(session_id, int)
    assert session_id > 0


def test_create_thread_under_session(tmp_path):
    """Verify create_thread returns unique ids for multiple threads."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    session_id = manager.create_session("test_session")
    thread_id_1 = manager.create_thread(session_id, "bull_researcher")
    thread_id_2 = manager.create_thread(session_id, "bear_researcher")

    assert isinstance(thread_id_1, int)
    assert isinstance(thread_id_2, int)
    assert thread_id_1 > 0
    assert thread_id_2 > 0
    assert thread_id_1 != thread_id_2


def test_append_and_retrieve_messages_in_order(tmp_path):
    """Verify messages are stored and retrieved in created_at order."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    session_id = manager.create_session("test_session")
    thread_id = manager.create_thread(session_id, "analyst")

    msg_id_1 = manager.append_message(thread_id, "user", "First message")
    msg_id_2 = manager.append_message(thread_id, "assistant", "Second message")
    msg_id_3 = manager.append_message(thread_id, "user", "Third message")

    messages = manager.get_thread_messages(thread_id)

    assert len(messages) == 3
    assert messages[0]["content"] == "First message"
    assert messages[1]["content"] == "Second message"
    assert messages[2]["content"] == "Third message"
    assert messages[0]["created_at"] <= messages[1]["created_at"]
    assert messages[1]["created_at"] <= messages[2]["created_at"]


def test_visibility_filter_agent(tmp_path):
    """Verify visibility='agent' filter returns only agent_visible==1 messages."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    session_id = manager.create_session("test_session")
    thread_id = manager.create_thread(session_id, "analyst")

    # Agent-only message
    manager.append_message(
        thread_id, "assistant", "Agent-only content",
        agent_visible=True, user_visible=False,
    )
    # User-only message
    manager.append_message(
        thread_id, "user", "User-only content",
        agent_visible=False, user_visible=True,
    )

    agent_messages = manager.get_thread_messages(thread_id, visibility="agent")

    assert len(agent_messages) == 1
    assert agent_messages[0]["content"] == "Agent-only content"
    assert agent_messages[0]["agent_visible"] == 1


def test_multiple_threads_per_session(tmp_path):
    """Verify list_threads returns all threads under a session."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    session_id = manager.create_session("test_session")
    thread_id_1 = manager.create_thread(session_id, "bull_researcher")
    thread_id_2 = manager.create_thread(session_id, "bear_researcher")

    threads = manager.list_threads(session_id)

    assert len(threads) == 2
    thread_agents = {t["agent_name"] for t in threads}
    assert "bull_researcher" in thread_agents
    assert "bear_researcher" in thread_agents


def test_ensure_schema_idempotent(tmp_path):
    """Verify calling SessionManager twice on the same path is safe."""
    db_path = tmp_path / "test.db"

    manager1 = SessionManager(db_path)
    session_id_1 = manager1.create_session("session_1")

    # Create another manager on the same path — should not error
    manager2 = SessionManager(db_path)
    session_id_2 = manager2.create_session("session_2")

    # Both sessions should exist
    threads = manager2.list_threads(session_id_1)
    assert isinstance(threads, list)
    # No assertion on count; just verify no error


def test_metadata_json_roundtrip(tmp_path):
    """Verify metadata dict is JSON-encoded and decoded correctly."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(db_path)

    metadata = {"instrument": "MCL", "strategy": "STC", "capital": 5000}
    session_id = manager.create_session("test_session", metadata=metadata)

    # Read back from DB
    with manager._connect() as conn:
        row = conn.execute(
            "SELECT metadata_json FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

    import json
    recovered = json.loads(row["metadata_json"])

    assert recovered == metadata
    assert recovered["instrument"] == "MCL"
    assert recovered["capital"] == 5000
