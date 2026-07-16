"""
JARVIS TRADER — Post-Trade Analysis (Phase 3.3)
===============================================
After every closed paper trade, Opus writes a 200-word analysis:
what fired, what worked, what didn't.
Stored in the trade_post_mortem table for weekly meta-learning.
"""

import json
import logging
import os
from datetime import datetime, timezone

from llm.client import JarvisLLMClient
from llm.model_router import MODEL_OPUS, route_task

logger = logging.getLogger("jarvis_trader.post_mortem")

_POST_MORTEM_PROMPT = """
You are a quantitative trading evaluator. Review this closed trade and the market context
that surrounded it.

Trade Execution:
Symbol: {symbol}
Side: {side}
Quantity: {quantity}
Entry Price: {entry_price}
Exit Price: {exit_price}
PnL: ${pnl}
Exit Reason: {exit_reason}

Market Context at Entry:
{market_context}

Write a rigorous 200-word post-mortem analysis covering:
1. What signal/thesis fired the entry?
2. What worked (did price move as expected)?
3. What didn't work (was the stop too tight, was the regime wrong)?
4. One actionable lesson for the strategy engine.

Return your response in valid JSON format:
{{
    "analysis": "<your 200-word analysis>",
    "what_worked": "<brief summary>",
    "what_failed": "<brief summary>",
    "lesson": "<one sentence lesson>"
}}
"""


class PostTradeAnalyzer:
    def __init__(self, db_manager, llm_client=None):
        self.db = db_manager
        self.llm = llm_client or JarvisLLMClient(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        self.model = route_task("post_trade_analysis", default_model=MODEL_OPUS)

        # Ensure table exists
        self._ensure_table()

    def _ensure_table(self):
        if not self.db:
            return
        try:
            with self.db._lock:
                conn = self.db._connect()
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_post_mortem (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT,
                        pnl REAL,
                        analysis TEXT,
                        lesson TEXT,
                        created_at TEXT
                    )
                """
                )
                conn.commit()
                conn.close()
        except Exception as e:
            logger.error(f"[PostMortem] Failed to init table: {e}")

    async def analyze_trade(self, trade_id: str, trade_data: dict, market_context: dict) -> dict:
        """
        Generate and store a post-mortem analysis for a closed trade.
        """
        if not self.llm:
            return {"error": "LLM client unavailable"}

        logger.info(
            f"[PostMortem] Starting analysis for trade {trade_id} ({trade_data.get('symbol')})"
        )

        prompt = _POST_MORTEM_PROMPT.format(
            symbol=trade_data.get("symbol", "UNKNOWN"),
            side=trade_data.get("side", "UNKNOWN"),
            quantity=trade_data.get("quantity", 0),
            entry_price=trade_data.get("entry_price", 0.0),
            exit_price=trade_data.get("exit_price", 0.0),
            pnl=trade_data.get("pnl", 0.0),
            exit_reason=trade_data.get("exit_reason", "UNKNOWN"),
            market_context=json.dumps(market_context, indent=2)[
                :1000
            ],  # Truncate to avoid context bloat
        )

        try:
            # Route through .call() (not the raw SDK client) so this inherits
            # the Anthropic -> Gemini -> OpenAI fallback chain, retries, and
            # cost tracking. The prior raw-client call bypassed all of that:
            # any Anthropic-specific failure (e.g. credit exhaustion) simply
            # failed the post-mortem outright instead of failing over.
            result_llm = await self.llm.call(
                model=self.model,
                system="",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                agent_name="post_mortem",
                temperature=0.0,
            )
            if not getattr(result_llm, "success", False):
                raise RuntimeError(
                    f"post_mortem LLM call failed: {getattr(result_llm, 'error', 'unknown')}"
                )

            result_text = result_llm.content

            # Extract JSON block
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(result_text[start:end])

                # Persist
                if self.db:
                    with self.db._lock:
                        conn = self.db._connect()
                        conn.execute(
                            "INSERT OR REPLACE INTO trade_post_mortem (trade_id, symbol, pnl, analysis, lesson, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                trade_id,
                                trade_data.get("symbol"),
                                trade_data.get("pnl", 0.0),
                                parsed.get("analysis", ""),
                                parsed.get("lesson", ""),
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        conn.commit()
                        conn.close()

                logger.info(f"[PostMortem] Successfully analyzed trade {trade_id}")
                return parsed
            else:
                raise ValueError("No JSON found in response")

        except Exception as e:
            logger.error(f"[PostMortem] Analysis failed for {trade_id}: {e}")
            return {"error": str(e)}
