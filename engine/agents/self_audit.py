"""
JARVIS TRADER — Weekly Self-Audit Agent (Phase 7.6)
===================================================
Meta-agent that runs every Sunday to review the past week's trading performance.
It synthesizes trade results, post-mortems, and market regimes to identify
patterns and recommend strategy adjustments.

Output: docs/weekly_audit.md
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from llm.client import JarvisLLMClient
from llm.model_router import MODEL_OPUS, route_task

logger = logging.getLogger("jarvis_trader.agents.self_audit")

_AUDIT_PROMPT = """
You are the JARVIS Meta-Auditor. Your task is to perform a deep-learning review of the
past week's trading performance.

WEEKLY PERFORMANCE SUMMARY:
Total Trades: {total_trades}
Total PnL: ${total_pnl:.2f}
Win Rate: {win_rate:.1%}
Best Trade: {best_trade}
Worst Trade: {worst_trade}

TRADE POST-MORTEMS (LAST 10):
{post_mortems}

Your goal is to identify common failure modes and winning signatures.
Review the lessons learned and look for cross-trade patterns (e.g. "We consistently
lose on MNQ when the daily regime is VOLATILE").

Write a rigorous weekly audit report in Markdown format.
Include:
1. **Executive Summary**: Overall verdict on the week's edge.
2. **Winning Patterns**: What setups are consistently producing alpha?
3. **Failure Modes**: What is dragging down performance? (Stops too tight, bad regimes, etc.)
4. **Strategy Deltas**: Three specific, actionable recommendations for the engine.
   - e.g. "Increase ATR multiplier for MGC to 2.5 during RTH."
   - e.g. "Block LONG entries on MES if VIX > 30."

Return your response as a valid JSON object:
{{
    "report_md": "<your full markdown report>",
    "top_lesson": "<the single most important takeaway>",
    "recommended_deltas": ["<delta 1>", "<delta 2>", "<delta 3>"]
}}
"""

class WeeklySelfAuditAgent:
    def __init__(self, db_manager, llm_client=None):
        self.db = db_manager
        self.llm = llm_client or JarvisLLMClient()
        self.model = route_task("complex_reasoning", default_model=MODEL_OPUS)
        self.audit_dir = Path("docs/audits")
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    async def run_audit(self) -> dict:
        """
        Perform the weekly performance audit.
        """
        logger.info("[SelfAudit] Starting weekly meta-analysis")

        # 1. Fetch data from last 7 days
        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        try:
            # Stats
            stats_sql = """
                SELECT
                    COUNT(*) as total,
                    SUM(pnl) as pnl,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    MAX(pnl) as best,
                    MIN(pnl) as worst
                FROM paper_trades
                WHERE exit_time >= ? AND status = 'closed'
            """
            stats = self.db.fetch_one(stats_sql, (seven_days_ago,))

            if not stats or stats["total"] == 0:
                logger.info("[SelfAudit] No trades found in the last 7 days. Skipping audit.")
                return {"message": "No trades found"}

            # Post-mortems
            pm_sql = """
                SELECT symbol, pnl, analysis, lesson, created_at
                FROM trade_post_mortem
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT 20
            """
            post_mortems = self.db.fetch_all(pm_sql, (seven_days_ago,))

            pm_text = ""
            for pm in post_mortems:
                pm_text += f"--- {pm['symbol']} ({pm['created_at'][:10]}) ---\n"
                pm_text += f"PnL: ${pm['pnl']:.2f}\n"
                pm_text += f"Analysis: {pm['analysis'][:300]}...\n"
                pm_text += f"Lesson: {pm['lesson']}\n\n"

            # 2. Call LLM
            prompt = _AUDIT_PROMPT.format(
                total_trades=stats["total"],
                total_pnl=stats["pnl"] or 0.0,
                win_rate=stats["wins"] / stats["total"] if stats["total"] > 0 else 0,
                best_trade=f"${stats['best']:.2f}" if stats["best"] else "N/A",
                worst_trade=f"${stats['worst']:.2f}" if stats["worst"] else "N/A",
                post_mortems=pm_text or "No post-mortems available."
            )

            llm_result = await self.llm.call(
                model=self.model,
                system="You are the lead quant auditor for the JARVIS TRADER fleet.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2500,
                agent_name="weekly_self_audit"
            )

            if not llm_result.success:
                raise RuntimeError(llm_result.error)

            result_text = llm_result.content.strip()

            # Extract JSON block
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(result_text[start:end])
                report_md = parsed.get("report_md", "")

                # 3. Save report to disk
                report_path = self.audit_dir / f"weekly_audit_{datetime.now().strftime('%Y-%m-%d')}.md"
                report_path.write_text(report_md, encoding="utf-8")

                # Update symlink or main file
                latest_path = Path("docs/weekly_audit.md")
                latest_path.write_text(report_md, encoding="utf-8")

                logger.info(f"[SelfAudit] Successfully generated audit at {report_path}")
                return parsed
            else:
                raise ValueError("No JSON found in response")

        except Exception as e:
            logger.error(f"[SelfAudit] Audit failed: {e}")
            return {"error": str(e)}
