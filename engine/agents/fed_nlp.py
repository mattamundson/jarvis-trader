"""
JARVIS TRADER — Fed NLP Agent (Phase 6.5)
=========================================
Analyzes FOMC statements and dot plots to identify shifts in monetary
policy stance (Hawkish/Dovish).

Implements Roadmap P6.5.
"""

import json
import logging
from datetime import datetime, timezone

from llm.client import JarvisLLMClient
from llm.model_router import MODEL_OPUS, route_task

logger = logging.getLogger("jarvis_trader.agents.fed_nlp")

_FED_NLP_PROMPT = """
You are a central bank policy analyst. Review the new FOMC statement and compare it to
the previous statement and dot plot. Identify the 5 most significant changes in
language or outlook.

New Statement:
{new_statement}

Previous Statement:
{old_statement}

Dot Plot Context:
{dot_plot}

Identify:
1. Significant language removals/additions.
2. Shift in economic assessment (growth, inflation, employment).
3. Guidance changes.
4. Dot plot implications.
5. Overall directional bias (HAWKISH / DOVISH / NEUTRAL).

Return your response in valid JSON format:
{{
    "bias": "HAWKISH" | "DOVISH" | "NEUTRAL",
    "confidence": <float 0-1>,
    "key_changes": ["<change 1>", "<change 2>", "<change 3>", "<change 4>", "<change 5>"],
    "summary": "<2 sentence assessment>",
    "diff_analysis": "<detailed paragraph comparing the two statements>"
}}
"""

class FedNLPAgent:
    def __init__(self, db_manager, llm_client=None):
        self.db = db_manager
        self.llm = llm_client or JarvisLLMClient()
        self.model = route_task("complex_reasoning", default_model=MODEL_OPUS)

    async def analyze_fomc(self, new_statement: str, dot_plot: str = "") -> dict:
        """
        Analyze a new FOMC statement against the historical baseline.
        """
        logger.info("[FedNLP] Starting analysis of new FOMC statement")

        # 1. Fetch latest historical statement
        old_statement = ""
        if self.db:
            try:
                row = self.db.fetch_one("SELECT statement FROM fomc_history ORDER BY meeting_date DESC LIMIT 1")
                if row:
                    old_statement = row["statement"]
            except Exception as e:
                logger.error(f"[FedNLP] Failed to fetch history: {e}")

        # 2. Call LLM
        prompt = _FED_NLP_PROMPT.format(
            new_statement=new_statement,
            old_statement=old_statement or "None available (first run).",
            dot_plot=dot_plot or "None provided."
        )

        try:
            llm_result = await self.llm.call(
                model=self.model,
                system="You are a senior economist specializing in FOMC analysis.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                agent_name="fed_nlp"
            )

            if not llm_result.success:
                raise RuntimeError(llm_result.error)

            result_text = llm_result.content.strip()

            # Extract JSON block
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(result_text[start:end])

                # 3. Persist new statement to history
                if self.db:
                    try:
                        self.db.execute(
                            "INSERT INTO fomc_history (meeting_date, statement, dot_plot, analysis, created_at) VALUES (?, ?, ?, ?, ?)",
                            (
                                datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                new_statement,
                                dot_plot,
                                json.dumps(parsed),
                                datetime.now(timezone.utc).isoformat()
                            )
                        )
                    except Exception as e:
                        logger.error(f"[FedNLP] Failed to persist history: {e}")

                logger.info("[FedNLP] Successfully analyzed and persisted FOMC statement")
                return parsed
            else:
                raise ValueError("No JSON found in response")

        except Exception as e:
            logger.error(f"[FedNLP] Analysis failed: {e}")
            return {"error": str(e)}
