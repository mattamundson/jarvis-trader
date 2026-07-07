"""
JARVIS TRADER — Trade Review Service
=======================================
Automated post-trade LLM analysis.  Triggered after every trade close,
runs asynchronously, never blocks the trade close response.

Grades every closed trade A–F:
  A — aligned regime + conviction + clean execution, captured target
  B — valid setup, minor execution issue (early entry, late exit)
  C — marginal setup (mixed regime, borderline conviction)
  D — identifiable mistake (wrong regime, low conviction, overrode signal)
  F — rule violation (traded against system direction, no pipeline signal)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("jarvis_trader.analytics.trade_review")

_service: Optional["TradeReviewService"] = None

SYSTEM_PROMPT = """You are the JARVIS TRADER post-trade analyst.
Your job is to objectively grade every closed paper trade and extract
actionable lessons to improve future execution.

Respond ONLY with valid JSON matching this exact schema — no prose, no markdown:
{
  "grade": "A"|"B"|"C"|"D"|"F",
  "setup_quality": "good"|"fair"|"poor",
  "strengths": ["string", ...],
  "weaknesses": ["string", ...],
  "rule_violations": ["string", ...],
  "lessons": "one or two sentence narrative",
  "improvement_tags": ["tag1", "tag2", ...]
}

Grade rubric:
  A — Regime + conviction aligned, clean execution, hit target or managed stop correctly
  B — Valid setup, minor execution issue (early entry, late exit, partial fill)
  C — Marginal setup (mixed regime, borderline conviction ≤5), execution OK
  D — Identifiable mistake: wrong regime, low conviction, manual override of signal
  F — Rule violation: traded without pipeline signal, opposite to system direction

Improvement tags should be short snake_case labels like: early_exit, manual_override,
low_conviction, stop_too_tight, no_pipeline_signal, good_risk_management, etc."""


def init_review_service(llm_client: Any, db_manager: Any) -> None:
    """Call once at engine startup after llm_client and db_manager are ready."""
    global _service
    _service = TradeReviewService(llm_client, db_manager)
    logger.info("[REVIEW] TradeReviewService initialised")


async def queue_trade_review(trade: Any) -> None:
    """
    Entry point called from tracker.close_trade().
    Silently skips if service not initialised (e.g. during tests).
    """
    if _service is None:
        logger.debug(
            "[REVIEW] Service not initialised — skipping review for %s", trade.trade_id[:8]
        )
        return
    try:
        await _service.review_trade(trade)
    except Exception as exc:
        logger.warning("[REVIEW] review_trade failed for %s: %s", trade.trade_id[:8], exc)


class TradeReviewService:
    """Builds prompt, calls LLM, parses response, persists to trade_reviews."""

    def __init__(self, llm_client: Any, db_manager: Any) -> None:
        self._llm = llm_client
        self._db = db_manager

    async def review_trade(self, trade: Any) -> None:
        """Full review pipeline for one closed trade."""
        trade_id = trade.trade_id

        # Write pending row immediately so the dashboard can show "Pending"
        self._write_pending(trade)

        prompt = self._build_prompt(trade)
        try:
            llm_result = await self._llm.call(
                model="claude-sonnet-4-6",
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                agent_name="trade_review",
                temperature=0.3,
            )
            if not llm_result.success:
                raise RuntimeError(f"LLM call failed: {llm_result.error}")

            parsed = self._parse_response(llm_result.content)
            params = self._extract_params(trade)

            self._db.upsert_trade_review(
                trade_id=trade_id,
                symbol=trade.symbol,
                direction=self._direction(trade),
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                pnl_usd=trade.pnl,
                pnl_pct=self._pnl_pct(trade),
                hold_minutes=self._hold_minutes(trade),
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                atr_value=trade.atr_value,
                rr_ratio=params.get("rr_ratio"),
                actual_r=self._actual_r(trade),
                regime=params.get("regime"),
                conviction=params.get("conviction"),
                bull_score=params.get("bull_score"),
                bear_score=params.get("bear_score"),
                pipeline_summary=params.get("summary"),
                grade=parsed.get("grade"),
                setup_quality=parsed.get("setup_quality"),
                strengths=parsed.get("strengths"),
                weaknesses=parsed.get("weaknesses"),
                rule_violations=parsed.get("rule_violations"),
                lessons=parsed.get("lessons"),
                improvement_tags=parsed.get("improvement_tags"),
                llm_model=llm_result.model,
                review_status="complete",
            )
            logger.info(
                "[REVIEW] %s %s grade=%s hold=%.0fm pnl=%+.2f",
                trade.symbol,
                self._direction(trade),
                parsed.get("grade", "?"),
                self._hold_minutes(trade) or 0,
                trade.pnl or 0,
            )
        except Exception as exc:
            logger.warning("[REVIEW] Analysis failed for %s: %s", trade_id[:8], exc)
            self._db.upsert_trade_review(
                trade_id=trade_id,
                symbol=trade.symbol,
                direction=self._direction(trade),
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                pnl_usd=trade.pnl,
                pnl_pct=self._pnl_pct(trade),
                hold_minutes=self._hold_minutes(trade),
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                atr_value=trade.atr_value,
                lessons=f"Review failed: {exc}",
                review_status="failed",
            )

    def _write_pending(self, trade: Any) -> None:
        """Create a pending placeholder row so dashboard shows the trade immediately."""
        try:
            self._db.upsert_trade_review(
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                direction=self._direction(trade),
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                pnl_usd=trade.pnl,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                review_status="pending",
            )
        except Exception as exc:
            logger.debug("[REVIEW] Could not write pending row: %s", exc)

    def _build_prompt(self, trade: Any) -> str:
        params = self._extract_params(trade)
        direction = self._direction(trade)
        hold = self._hold_minutes(trade)
        hold_str = f"{hold:.0f}m" if hold else "unknown"
        pnl = trade.pnl or 0.0
        pnl_pct = self._pnl_pct(trade) or 0.0
        rr_ratio = params.get("rr_ratio")
        actual_r = self._actual_r(trade)

        # Determine outcome label
        if trade.take_profit and trade.exit_price:
            if direction == "LONG":
                outcome = (
                    "Target hit"
                    if trade.exit_price >= trade.take_profit * 0.98
                    else "Manual close / Stopped out"
                )
            else:
                outcome = (
                    "Target hit"
                    if trade.exit_price <= trade.take_profit * 1.02
                    else "Manual close / Stopped out"
                )
        elif trade.stop_loss and trade.exit_price:
            if direction == "LONG":
                outcome = (
                    "Stopped out" if trade.exit_price <= trade.stop_loss * 1.02 else "Manual close"
                )
            else:
                outcome = (
                    "Stopped out" if trade.exit_price >= trade.stop_loss * 0.98 else "Manual close"
                )
        else:
            outcome = "Manual close"

        lines = [
            "JARVIS TRADER — Post-Trade Analysis",
            f"Trade: {trade.symbol} {direction} x{trade.quantity}",
            f"Entry: ${trade.entry_price:.2f} @ {trade.entry_time}  "
            f"Exit: ${trade.exit_price:.2f} @ {trade.exit_time}",
            f"Hold: {hold_str}  P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)",
            "",
            "--- ENTRY CONTEXT ---",
            f"Regime: {params.get('regime', 'unknown')} | "
            f"Bias: {params.get('bias', 'unknown')} | "
            f"Conviction: {params.get('conviction', 'unknown')}/10",
        ]

        bull = params.get("bull_score")
        bear = params.get("bear_score")
        if bull is not None and bear is not None:
            lines.append(f"Debate: Bull {bull:.1f}/10 vs Bear {bear:.1f}/10")

        summary = params.get("summary", "")
        if summary:
            lines.append(f'Pipeline summary: "{summary}"')

        source = params.get("source", "")
        if source:
            lines.append(f"Signal source: {source}")

        lines += ["", "--- RISK PLAN ---"]
        stop_dist = None
        if trade.stop_loss and trade.entry_price:
            stop_dist = abs(trade.entry_price - trade.stop_loss)
            lines.append(
                f"Stop: ${trade.stop_loss:.2f} ({stop_dist:.1f} pts)"
                + (f"  Target: ${trade.take_profit:.2f}" if trade.take_profit else "  Target: none")
            )
        if trade.atr_value:
            lines.append(f"ATR: {trade.atr_value:.2f}")
        if rr_ratio:
            lines.append(f"Planned R:R: {rr_ratio:.1f}:1")
        if actual_r is not None:
            lines.append(f"Actual R: {actual_r:+.2f}R")
        lines.append(f"Outcome: {outcome}")

        lines += ["", "Grade this trade A/B/C/D/F and return JSON analysis."]
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Strip markdown fences and parse JSON from LLM response."""
        text = response_text.strip()
        # Remove ```json ... ``` or ``` ... ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract the first JSON object from the text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"No JSON found in response: {text[:200]}") from None

        # Validate grade
        valid_grades = {"A", "B", "C", "D", "F"}
        if data.get("grade") not in valid_grades:
            data["grade"] = None

        # Ensure list fields are lists
        for list_field in ("strengths", "weaknesses", "rule_violations", "improvement_tags"):
            if not isinstance(data.get(list_field), list):
                data[list_field] = []

        return data

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _direction(trade: Any) -> str:
        action = (trade.action or "").lower()
        if "buy" in action or action in ("long",):
            return "LONG"
        if "sell" in action or action in ("short",):
            return "SHORT"
        return action.upper()

    @staticmethod
    def _extract_params(trade: Any) -> Dict[str, Any]:
        """Pull strategy_params dict from trade, handling both str and dict."""
        raw = getattr(trade, "strategy_params", None) or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                raw = {}
        if not isinstance(raw, dict):
            raw = {}

        # Compute rr_ratio if not present
        if "rr_ratio" not in raw and trade.take_profit and trade.stop_loss and trade.entry_price:
            try:
                if "buy" in (trade.action or "").lower():
                    num = trade.take_profit - trade.entry_price
                    den = trade.entry_price - trade.stop_loss
                else:
                    num = trade.entry_price - trade.take_profit
                    den = trade.stop_loss - trade.entry_price
                if den > 0:
                    raw["rr_ratio"] = round(num / den, 2)
            except Exception:
                pass
        return raw

    @staticmethod
    def _hold_minutes(trade: Any) -> Optional[float]:
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            t_entry = datetime.strptime(trade.entry_time[:19], fmt).replace(tzinfo=timezone.utc)
            t_exit = datetime.strptime(trade.exit_time[:19], fmt).replace(tzinfo=timezone.utc)
            return (t_exit - t_entry).total_seconds() / 60
        except Exception:
            return None

    @staticmethod
    def _pnl_pct(trade: Any) -> Optional[float]:
        try:
            if trade.pnl is not None and trade.entry_price:
                return round((trade.pnl / (trade.entry_price * trade.quantity)) * 100, 2)
        except Exception:
            pass
        return None

    @staticmethod
    def _actual_r(trade: Any) -> Optional[float]:
        try:
            if trade.pnl is None or not trade.stop_loss or not trade.entry_price:
                return None
            stop_dist = abs(trade.entry_price - trade.stop_loss)
            if stop_dist == 0:
                return None
            risk_usd = stop_dist * trade.quantity
            return round(trade.pnl / risk_usd, 2)
        except Exception:
            return None
