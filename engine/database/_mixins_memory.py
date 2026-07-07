"""
Database Mixin for Agent Memory (Phase 3.5)
===========================================
Provides persistence for agent working memory snippets.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.database.memory")

class MemoryMixin:
    """
    Mixin for storing and retrieving agent-specific memory snippets.
    """

    def store_memory(
        self,
        agent_name: str,
        content: str,
        symbol: Optional[str] = None,
        topic: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a new memory snippet.
        """
        import uuid
        memory_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})

        sql = """
            INSERT INTO agent_memory (id, agent_name, symbol, topic, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (memory_id, agent_name, symbol, topic, content, meta_json, ts)

        # self.execute is provided by DatabaseManager
        self.execute(sql, params)
        return memory_id

    def retrieve_memory(
        self,
        agent_name: str,
        symbol: Optional[str] = None,
        topic: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent memory snippets for an agent.
        """
        sql = "SELECT * FROM agent_memory WHERE agent_name = ?"
        params = [agent_name]

        if symbol:
            sql += " AND (symbol = ? OR symbol IS NULL)"
            params.append(symbol)

        if topic:
            sql += " AND topic = ?"
            params.append(topic)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        return self.fetch_all(sql, tuple(params))

    def get_memory_stats(self) -> Dict[str, int]:
        """
        Return memory counts grouped by agent.
        """
        sql = "SELECT agent_name, COUNT(*) as count FROM agent_memory GROUP BY agent_name"
        rows = self.fetch_all(sql)
        return {r["agent_name"]: r["count"] for r in rows}
