"""
QuantAgent Research Agent — LLM-backed strategy hypothesis generator.

Generates StrategyHypothesis proposals for consumption by the backtest +
gate-v2 pipeline. Enable via ENABLE_RESEARCH_AGENT=1; defaults OFF so it
never fires in prod.

Cost gate: daily budget enforced against `engine/data/jarvis_trader.db`
table `research_agent_costs`. Default budget: $5.00/day (override via
RESEARCH_AGENT_DAILY_BUDGET_USD env var).

Off-pipeline: this agent is NEVER called during a normal pipeline run.
It feeds StrategyTuner.generate_hypothesis() and the weekend cron.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def is_research_agent_enabled() -> bool:
    """Return True only when ENABLE_RESEARCH_AGENT is explicitly set to '1'."""
    return os.environ.get("ENABLE_RESEARCH_AGENT", "0").strip() == "1"


# ---------------------------------------------------------------------------
# Cost gate constants
# ---------------------------------------------------------------------------

# Haiku pricing (claude-haiku-4-5-20251001): $0.80/MTok input, $4.00/MTok output
_HAIKU_INPUT_PER_MTOK = 0.80
_HAIKU_OUTPUT_PER_MTOK = 4.00
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Typical call: ~600 input tokens + ~400 output tokens
_COST_PER_CALL_ESTIMATE = (600 / 1_000_000) * _HAIKU_INPUT_PER_MTOK + (
    400 / 1_000_000
) * _HAIKU_OUTPUT_PER_MTOK


def _get_db_path() -> Path:
    """Resolve path to jarvis_trader.db relative to this file's engine root."""
    # engine/agents/research_agent.py -> engine/ -> engine/data/jarvis_trader.db
    return Path(__file__).resolve().parent.parent / "data" / "jarvis_trader.db"


def _get_daily_budget() -> float:
    """Daily spend budget in USD. Override via RESEARCH_AGENT_DAILY_BUDGET_USD."""
    try:
        return float(os.environ.get("RESEARCH_AGENT_DAILY_BUDGET_USD", "5.00"))
    except (TypeError, ValueError):
        return 5.00


def _ensure_cost_table(conn: sqlite3.Connection) -> None:
    """Create research_agent_costs table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_agent_costs (
            date TEXT PRIMARY KEY,
            usd_spent REAL DEFAULT 0
        )
        """
    )
    conn.commit()


def _get_today_spend(db_path: Path) -> float:
    """Return today's cumulative spend in USD (0.0 if no record yet)."""
    today = date.today().isoformat()
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_cost_table(conn)
            row = conn.execute(
                "SELECT usd_spent FROM research_agent_costs WHERE date = ?", (today,)
            ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as exc:
        logger.warning("research_agent_costs read failed: %s", exc)
        return 0.0


def _increment_today_spend(db_path: Path, amount: float) -> None:
    """Add amount to today's spend record (upsert)."""
    today = date.today().isoformat()
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_cost_table(conn)
            conn.execute(
                """
                INSERT INTO research_agent_costs (date, usd_spent)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET usd_spent = usd_spent + excluded.usd_spent
                """,
                (today, amount),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("research_agent_costs write failed: %s", exc)


# ---------------------------------------------------------------------------
# Contract model — interface is stable; do not change field names or types
# ---------------------------------------------------------------------------


class StrategyHypothesis(BaseModel):
    """
    A fully-specified strategy hypothesis ready for backtesting + gate-v2 scoring.

    Fields mirror the inputs expected by StrategyTuner.suggest_adjustments and
    the gate-v2 verdict pathway.  The 'confidence' field is set by the generating
    agent and re-evaluated by gate-v2 before any trade routing occurs.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    # Identity
    name: str = Field(..., description="Short slug, e.g. 'mes-mean-rev-v1'")
    symbol: str = Field(..., description="Root futures symbol, e.g. 'MES', 'MNQ'")
    timeframe: str = Field(..., description="Bar timeframe, e.g. '1h', '15m', '1d'")

    # Logic
    entry_rules: list[str] = Field(
        ...,
        min_length=1,
        description="Human-readable entry conditions, one string per rule",
    )
    exit_rules: list[str] = Field(
        ...,
        min_length=1,
        description="Human-readable exit conditions, one string per rule",
    )

    # Weighting / parameters
    signal_weights: dict[str, float] = Field(
        default_factory=dict,
        description="Feature name -> relative weight used in signal scoring",
    )
    risk_params: dict[str, float] = Field(
        default_factory=dict,
        description="Risk parameter overrides, e.g. stop_atr_mult, tp_atr_mult",
    )

    # Metadata
    rationale: str = Field(..., description="Plain-English reason this hypothesis was generated")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Agent's prior confidence (0..1); gate-v2 re-evaluates after backtest",
    )


# ---------------------------------------------------------------------------
# Hardcoded fallback — private; used when LLM is off or parse fails
# ---------------------------------------------------------------------------

_HARDCODED_MES_MEAN_REV = StrategyHypothesis(
    name="mes-mean-rev-v1",
    symbol="MES",
    timeframe="1h",
    entry_rules=[
        "STC oscillator crosses above 20 (oversold reversal)",
        "Price is within 0.5 ATR of the prior session VWAP",
        "15-min RSI(14) < 35 at entry bar open",
    ],
    exit_rules=[
        "Take-profit at entry + 2.5 * ATR(14)",
        "Stop-loss at entry - 1.5 * ATR(14)",
        "Exit at end of regular trading session if neither TP nor SL hit",
    ],
    signal_weights={
        "stc_crossover": 0.45,
        "vwap_proximity": 0.30,
        "rsi_oversold": 0.25,
    },
    risk_params={
        "stop_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "atr_period": 14,
    },
    rationale=(
        "MES intraday mean-reversion hypothesis: auction-theory literature suggests "
        "that short-term deviations from VWAP in liquid micro futures are self-correcting "
        "within the same RTH session.  STC + RSI confluence filters out trending days."
    ),
    confidence=0.0,  # gate-v2 will score after backtest
)


# ---------------------------------------------------------------------------
# System prompt template — kept as a module-level constant for readability
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quantitative researcher generating futures strategy hypotheses for \
systematic backtesting. You must output a single JSON object — no prose, no \
markdown fences — that strictly conforms to the following schema:

{
  "name":         string,  // short slug, e.g. "mes-vwap-rev-v1"
  "symbol":       string,  // futures root symbol passed by the caller
  "timeframe":    string,  // bar timeframe, e.g. "1h", "15m", "1d"
  "entry_rules":  [string, ...],  // 1-3 items maximum; reference existing engine features only
  "exit_rules":   [string, ...],  // 1-3 items maximum
  "signal_weights": {string: float, ...},  // feature name -> relative weight (0.0-1.0 range)
  "risk_params":  {                         // MUST include stop_atr_mult in [1.0, 5.0]
    "stop_atr_mult": float,
    "tp_atr_mult": float,
    ...
  },
  "rationale":    string,  // one sentence explaining why this hypothesis is plausible
  "confidence":   float    // your prior estimate, 0.0-0.5 max (gate-v2 will re-evaluate)
}

Constraints:
- entry_rules: maximum 3 rules.
- signal_weights keys MUST be engine feature names only: \
stc_crossover, vwap_proximity, rsi_oversold, rsi_overbought, atr_breakout, \
volume_surge, regime_bull, regime_bear, stc_os_level, stc_ob_level.
- risk_params.stop_atr_mult MUST be between 1.0 and 5.0.
- confidence MUST be between 0.0 and 0.5 — hypotheses are pre-backtest; \
do not claim high confidence without evidence.
- Output ONLY the JSON object. No other text."""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ResearchAgent:
    """
    Generates StrategyHypothesis objects for downstream backtesting.

    When ENABLE_RESEARCH_AGENT=0 (default): returns the hardcoded MES
    mean-reversion fallback immediately — zero LLM cost.

    When ENABLE_RESEARCH_AGENT=1: calls JarvisLLMClient via AdvisorClient's
    lazy-load pattern on haiku tier.  Daily cost gate enforced against
    engine/data/jarvis_trader.db (table: research_agent_costs).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _get_db_path()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def propose(
        self,
        symbol: str,
        context: dict[str, Any] | None = None,
    ) -> StrategyHypothesis:
        """
        Return a strategy hypothesis for *symbol*.

        Args:
            symbol:  Root futures symbol, e.g. "MES".
            context: Optional market context dict — recent_trades, current_params,
                     regime, suggestions.

        Returns:
            A StrategyHypothesis with all required fields populated.  Never raises.
        """
        if not is_research_agent_enabled():
            logger.debug(
                "ResearchAgent.propose: ENABLE_RESEARCH_AGENT off — returning stub (symbol=%s)",
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        # --- cost gate (pre-call) ---
        today_spend = _get_today_spend(self._db_path)
        budget = _get_daily_budget()
        if today_spend >= budget:
            logger.warning(
                "ResearchAgent: daily budget exhausted "
                "(spent=$%.4f, limit=$%.4f) — returning stub for %s",
                today_spend,
                budget,
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        # --- LLM call ---
        try:
            from agents.advisor_client import AdvisorClient  # lazy import

            client = AdvisorClient()
            if not client.is_available():
                logger.warning(
                    "ResearchAgent: AdvisorClient unavailable (no API key?) — returning stub for %s",
                    symbol,
                )
                return self._hardcoded_mes_mean_reversion(symbol)

            prompt = self._build_prompt(symbol, context or {})
            result = await client.llm.call(
                model=_HAIKU_MODEL,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.7,
                agent_name="research_agent",
            )
        except Exception as exc:
            logger.warning(
                "ResearchAgent.propose: LLM call raised %s — returning stub for %s",
                exc,
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        # --- cost accounting (post-call) ---
        actual_cost = _COST_PER_CALL_ESTIMATE
        if result.success:
            # Use actual token counts when available
            actual_cost = (result.input_tokens / 1_000_000) * _HAIKU_INPUT_PER_MTOK + (
                result.output_tokens / 1_000_000
            ) * _HAIKU_OUTPUT_PER_MTOK
        _increment_today_spend(self._db_path, actual_cost)

        if not result.success:
            logger.warning(
                "ResearchAgent.propose: LLM returned failure (error=%s) — returning stub for %s",
                result.error,
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        # --- parse & validate ---
        return self._parse_hypothesis(result.content, symbol=symbol)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _hardcoded_mes_mean_reversion(self, symbol: str | None = None) -> StrategyHypothesis:
        """Return the hardcoded fallback, optionally re-binding the symbol field."""
        if symbol is None or symbol == _HARDCODED_MES_MEAN_REV.symbol:
            return _HARDCODED_MES_MEAN_REV
        return _HARDCODED_MES_MEAN_REV.model_copy(update={"symbol": symbol})

    def _build_prompt(self, symbol: str, context: dict[str, Any]) -> str:
        """
        Build a compact user prompt embedding recent trade history and params.

        Keeps the prompt small for haiku-tier to reduce cost.  Truncates
        recent_trades to the 5 most recent entries.
        """
        parts: list[str] = [f"SYMBOL: {symbol}"]

        recent_trades: list[dict] = context.get("recent_trades", [])
        if recent_trades:
            sample = recent_trades[-5:]  # 5 most recent
            trades_summary = []
            for t in sample:
                won = t.get("won", False)
                pnl = t.get("pnl", 0.0)
                risk = t.get("risk", 1.0)
                r_mult = pnl / max(risk, 1.0)
                trades_summary.append(
                    f"  - {'WIN' if won else 'LOSS'} pnl={pnl:.2f} R={r_mult:.2f}"
                )
            parts.append("RECENT_TRADES (last 5):\n" + "\n".join(trades_summary))

        current_params: dict = context.get("current_params", {})
        if current_params:
            param_lines = [f"  {k}={v}" for k, v in list(current_params.items())[:10]]
            parts.append("CURRENT_PARAMS:\n" + "\n".join(param_lines))

        regime = context.get("regime")
        if regime:
            parts.append(f"REGIME: {regime}")

        suggestions = context.get("suggestions", [])
        if suggestions:
            sug_lines = []
            for s in suggestions[:3]:
                if hasattr(s, "param_name"):
                    sug_lines.append(
                        f"  - {s.param_name}: {s.current_value} -> {s.suggested_value}"
                        f" ({s.reason})"
                    )
            if sug_lines:
                parts.append("TUNER_SUGGESTIONS:\n" + "\n".join(sug_lines))

        parts.append(
            "\nGenerate a single strategy hypothesis JSON for backtesting. "
            "Consider the trade history and current parameters above."
        )
        return "\n\n".join(parts)

    def _parse_hypothesis(self, raw: str, symbol: str) -> StrategyHypothesis:
        """
        Extract JSON from LLM output and validate as StrategyHypothesis.

        Handles:
          - Bare JSON objects
          - JSON wrapped in ```json ... ``` fences

        On any parse or validation failure: logs a warning and returns the
        hardcoded fallback.  Never raises.
        """
        # Strip markdown code fences gracefully
        cleaned = raw.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        # Locate the outermost JSON object
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
            logger.warning(
                "ResearchAgent._parse_hypothesis: no JSON object found in LLM output "
                "(symbol=%s) — falling back to stub. raw[:200]=%r",
                symbol,
                raw[:200],
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        json_str = cleaned[brace_start : brace_end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning(
                "ResearchAgent._parse_hypothesis: JSON decode failed (%s) "
                "(symbol=%s) — falling back to stub",
                exc,
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        # Force the symbol field to match the requested symbol
        data["symbol"] = symbol

        try:
            hypothesis = StrategyHypothesis.model_validate(data)
        except Exception as exc:
            logger.warning(
                "ResearchAgent._parse_hypothesis: Pydantic validation failed (%s) "
                "(symbol=%s) — falling back to stub",
                exc,
                symbol,
            )
            return self._hardcoded_mes_mean_reversion(symbol)

        logger.info(
            "ResearchAgent: parsed hypothesis %r for %s (confidence=%.2f)",
            hypothesis.name,
            symbol,
            hypothesis.confidence,
        )
        return hypothesis
