"""
QuantAgent Research Agent — stub skeleton (US-RAG-001).
Generates StrategyHypothesis proposals for consumption by the backtest +
gate-v2 pipeline. No real LLM call yet — paper schema not locked.
Enable via ENABLE_RESEARCH_AGENT=1; defaults OFF so it never fires in prod.
"""

from __future__ import annotations

import logging
import os
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
# Contract model
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
# Agent
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


class ResearchAgent:
    """
    Generates StrategyHypothesis objects for downstream backtesting.

    Stub implementation: always returns a hardcoded MES mean-reversion hypothesis.
    Real LLM-backed generation will replace propose() once the QuantAgent paper
    schema is locked and ENABLE_RESEARCH_AGENT is wired into the pipeline.
    """

    async def propose(
        self,
        symbol: str,
        context: dict[str, Any] | None = None,
    ) -> StrategyHypothesis:
        """
        Return a strategy hypothesis for *symbol*.

        Args:
            symbol:  Root futures symbol, e.g. "MES".
            context: Optional market context dict (ignored by stub).

        Returns:
            A StrategyHypothesis with all required fields populated.
        """
        if not is_research_agent_enabled():
            logger.warning(
                "ResearchAgent.propose called but ENABLE_RESEARCH_AGENT is not set; "
                "returning stub hypothesis regardless (caller should gate on flag)."
            )

        logger.debug(
            "ResearchAgent.propose: symbol=%s (stub — returning hardcoded MES mean-rev)", symbol
        )

        # Stub: return the hardcoded hypothesis with the requested symbol injected.
        # When the real LLM path ships, replace this block with the actual call.
        hypothesis = _HARDCODED_MES_MEAN_REV.model_copy(update={"symbol": symbol})
        return hypothesis
