"""
JARVIS TRADER — Memory Bridge (Phase 3.5)
=========================================
Provides a high-level interface for agents to store and retrieve long-term
working memory snippets. This bridges the gap between discrete pipeline
sessions and persistent agent learning.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.llm.memory_bridge")


class MemoryBridge:
    """
    Manages long-term working memory for LLM agents.
    Backbacked by the agent_memory table in SQLite.
    """

    def __init__(self, db_manager):
        self.db = db_manager

    def remember(
        self,
        agent_name: str,
        content: str,
        symbol: Optional[str] = None,
        topic: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store a new memory snippet for an agent.
        """
        if not self.db:
            logger.warning("[MemoryBridge] DB manager unavailable, skipping storage")
            return ""

        try:
            memory_id = self.db.store_memory(
                agent_name=agent_name,
                content=content,
                symbol=symbol,
                topic=topic,
                metadata=metadata,
            )
            logger.info(
                f"[MemoryBridge] {agent_name} stored memory for {symbol or 'global'}: {topic}"
            )
            return memory_id
        except Exception as e:
            logger.error(f"[MemoryBridge] Failed to store memory: {e}")
            return ""

    def recall(
        self,
        agent_name: str,
        symbol: Optional[str] = None,
        topic: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """
        Retrieve recent memory snippets and format them for an LLM prompt.
        Includes historical lessons from trade_post_mortem for relevant agents.
        """
        if not self.db:
            return ""

        lines = [f"### {agent_name.upper()} WORKING MEMORY ###"]
        mem_found = False

        try:
            # 1. Standard working memory
            memories = self.db.retrieve_memory(
                agent_name=agent_name, symbol=symbol, topic=topic, limit=limit
            )

            if memories:
                mem_found = True
                for m in memories:
                    ts = m["created_at"][:16].replace("T", " ")
                    sym_tag = f" ({m['symbol']})" if m["symbol"] else ""
                    lines.append(f"- [{ts}]{sym_tag} {m['topic']}: {m['content']}")

            # 2. Historical Lessons (from trade_post_mortem)
            # Relevant for Research and Trader agents
            if agent_name in ("bull-researcher", "bear-researcher", "trader"):
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS trade_post_mortem "
                    "(trade_id TEXT PRIMARY KEY, symbol TEXT, pnl REAL, "
                    "analysis TEXT, lesson TEXT, created_at TEXT)"
                )
                lessons_sql = "SELECT lesson, created_at, pnl FROM trade_post_mortem"
                l_params = []
                if symbol:
                    lessons_sql += " WHERE symbol = ?"
                    l_params.append(symbol)
                lessons_sql += " ORDER BY created_at DESC LIMIT 3"

                lessons = self.db.fetch_all(lessons_sql, tuple(l_params))
                if lessons:
                    mem_found = True
                    lines.append("\n### HISTORICAL LESSONS FROM RECENT TRADES ###")
                    for entry in lessons:
                        ts = entry["created_at"][:10]
                        outcome = "WIN" if entry["pnl"] > 0 else "LOSS"
                        lines.append(f"- [{ts}] {outcome}: {entry['lesson']}")

            if not mem_found:
                return ""

            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.error(f"[MemoryBridge] Failed to recall memory: {e}")
            return ""

    def get_summary_stats(self) -> Dict[str, int]:
        """
        Return memory counts per agent.
        """
        if not self.db:
            return {}
        return self.db.get_memory_stats()
