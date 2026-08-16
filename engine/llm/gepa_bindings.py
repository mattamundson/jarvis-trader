"""
GEPA production bindings — jarvis-trader Pilot 1 (compound-agent-system)
=========================================================================

Binds engine/llm/prompt_evolution.py's Protocol-based GEPAOptimizer to real
components: SqliteTradeEvalSource reads real closed-trade outcomes via
AgentFeedbackTracker, SonnetPromptMutator and SonnetPromptScorer call
engine/llm/client.py's existing Sonnet wrapper.

Additive only. Does not modify prompt_evolution.py or agent_feedback.py's
load_weights() hot path (consumed live in engine/agents/debate.py).

Never writes to engine/agents/*.py — see engine/llm/gepa_runner.py and
compound-agent-system's docs/proposals/ convention for how a winning
candidate reaches a human-reviewed PR instead of an automatic edit.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from analytics.agent_feedback import AgentFeedbackTracker
from llm.client import JarvisLLMClient
from llm.prompt_evolution import EvalTrade

logger = logging.getLogger(__name__)

SONNET_MODEL = "claude-sonnet-4-6"


def _rows_to_eval_trades(rows: list[dict]) -> list[EvalTrade]:
    trades = []
    for row in rows:
        trades.append(EvalTrade(
            trade_id=row["trade_id"],
            symbol=row["symbol"],
            timestamp=row["timestamp"],
            context=row["context"],
            actual_winning_side=row["actual_winning_side"],
            pnl_usd=row["pnl_usd"],
        ))
    return trades


def _query_trade_outcomes(db_path: Path, limit: int) -> list[dict]:
    """Same query shape as AgentFeedbackTracker.get_recent_trades_for_eval, against
    an explicit DB file — used when db_path overrides the module default (e.g.
    smoke-testing from an isolated worktree without a local copy of the live DB)."""
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
        rows = conn.execute("""
            SELECT trade_id, timestamp, symbol, direction, pnl_usd, outcome,
                   technical_signal, news_signal, social_signal, fundamental_signal, corey_signal
            FROM trade_outcomes
            WHERE pnl_usd IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()

    trades = []
    for (trade_id, timestamp, symbol, direction, pnl_usd, outcome,
         technical, news, social, fundamental, corey) in rows:
        opposite = "SHORT" if direction == "LONG" else "LONG"
        actual_winning_side = direction if outcome == "WIN" else opposite
        trades.append({
            "trade_id": trade_id, "symbol": symbol, "timestamp": timestamp,
            "context": {
                "technical": technical, "news": news, "social": social,
                "fundamental": fundamental, "corey": corey,
            },
            "actual_winning_side": actual_winning_side,
            "pnl_usd": pnl_usd,
        })
    return trades


class SqliteTradeEvalSource:
    """TradeEvalSource bound to real trade_outcomes data.

    db_path=None (default) uses AgentFeedbackTracker's own DB_PATH resolution
    (relative to wherever agent_feedback.py is loaded from). An explicit
    db_path reads that file directly, read-only — used for cross-checkout
    smoke-testing without disturbing the live DB.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def get_trades(self, limit: int = 100) -> list[EvalTrade]:
        if self.db_path is not None:
            rows = _query_trade_outcomes(self.db_path, limit)
        else:
            rows = AgentFeedbackTracker().get_recent_trades_for_eval(limit)
        return _rows_to_eval_trades(rows)


class SonnetPromptMutator:
    """PromptMutator bound to engine/llm/client.py's Sonnet wrapper."""

    def __init__(self, llm_client: Optional[JarvisLLMClient] = None):
        self.llm = llm_client or JarvisLLMClient()

    async def mutate(self, prompt: str, n_variants: int) -> list[tuple[str, str]]:
        instruction = (
            f"You are mutating a trading-analyst system prompt for offline evaluation. "
            f"Produce exactly {n_variants} distinct mutated variants of the prompt below. "
            f"Each mutation should try ONE of: add an evidence requirement, tighten the "
            f"scoring rubric, add a worked example, simplify/shorten, or clarify an "
            f"ambiguous instruction. Never remove safety or evidence-requirement language "
            f"that is already present.\n\n"
            f"Return each variant as:\nVARIANT: <full mutated prompt text>\n"
            f"NOTE: <one-line description of what you changed>\n---\n"
            f"(repeat for each variant, separated by ---)\n\n"
            f"Original prompt:\n{prompt}"
        )
        result = await self.llm.call(
            model=SONNET_MODEL, system="", messages=[{"role": "user", "content": instruction}],
            max_tokens=2048, agent_name="gepa_prompt_mutator",
        )
        if not result.success:
            logger.warning("SonnetPromptMutator: LLM call failed: %s", result.error)
            return []
        return self._parse_variants(result.content or "")

    @staticmethod
    def _parse_variants(text: str) -> list[tuple[str, str]]:
        variants = []
        for block in text.split("---"):
            variant_match = re.search(r"VARIANT:\s*(.+?)(?=\nNOTE:|\Z)", block, re.DOTALL)
            note_match = re.search(r"NOTE:\s*(.+?)$", block, re.DOTALL)
            if variant_match:
                variant_text = variant_match.group(1).strip()
                note = note_match.group(1).strip() if note_match else "unlabeled mutation"
                if variant_text:
                    variants.append((variant_text, note))
        return variants


class SonnetPromptScorer:
    """PromptScorer bound to engine/llm/client.py's Sonnet wrapper. Runs a candidate
    prompt as the system prompt against one trade's context, returns the predicted side."""

    def __init__(self, llm_client: Optional[JarvisLLMClient] = None):
        self.llm = llm_client or JarvisLLMClient()

    async def predict(self, prompt: str, context: dict) -> str:
        user_msg = (
            f"Analyst signals available at decision time: {context}\n\n"
            f"Based on your system prompt's instructions, respond with exactly one word: "
            f"LONG, SHORT, or FLAT."
        )
        result = await self.llm.call(
            model=SONNET_MODEL, system=prompt, messages=[{"role": "user", "content": user_msg}],
            max_tokens=16, agent_name="gepa_prompt_scorer", temperature=0.0,
        )
        if not result.success:
            logger.warning("SonnetPromptScorer: LLM call failed: %s", result.error)
            return "FLAT"
        text = (result.content or "").strip().upper()
        for side in ("LONG", "SHORT", "FLAT"):
            if side in text:
                return side
        return "FLAT"
