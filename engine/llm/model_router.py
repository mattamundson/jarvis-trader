"""
JARVIS TRADER — Model Router (Phase 3.1)
========================================
Dynamically routes tasks to the most appropriate Claude model based on
capability and cost-efficiency.

Routing Matrix:
  Opus   — Inconclusive debates, post-trade analysis, complex reasoning
  Sonnet — Standard pipeline agents (technical, fundamental, risk, etc.)
  Haiku  — Health checks, cache operations, bookmark clustering, social sentiment
"""

import logging

logger = logging.getLogger("jarvis_trader.model_router")

# Define standard models
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_LOCAL = "hermes3:latest" # For local inference fallback

# Define task categories
TASK_CATEGORIES = {
    # Opus tasks (High intellect, high cost)
    "post_trade_analysis": MODEL_OPUS,
    "inconclusive_debate": MODEL_OPUS,
    "complex_reasoning": MODEL_OPUS,

    # Sonnet tasks (Balanced intellect, medium cost)
    "standard_pipeline": MODEL_SONNET,
    "technical_analyst": MODEL_SONNET,
    "news_analyst": MODEL_SONNET,
    "fundamental_analyst": MODEL_SONNET,
    "bull_researcher": MODEL_SONNET,
    "bear_researcher": MODEL_SONNET,
    "debate_orchestrator": MODEL_SONNET,
    "trader": MODEL_SONNET,
    "risk_manager": MODEL_SONNET,
    "fund_manager": MODEL_SONNET,
    "pattern_vision": MODEL_SONNET,

    # Haiku tasks (Fast, low cost)
    "health_check": MODEL_HAIKU,
    "cache_operation": MODEL_HAIKU,
    "bookmark_clustering": MODEL_HAIKU,
    "social_analyst": MODEL_HAIKU,
    "fast_summary": MODEL_HAIKU,
}

def route_task(task_type: str, default_model: str = MODEL_SONNET, use_local: bool = False) -> str:
    """
    Return the optimal model for the given task type.
    If use_local is True, bypasses cloud models and returns local model.
    """
    if use_local:
        return MODEL_LOCAL

    model = TASK_CATEGORIES.get(task_type, default_model)
    logger.debug(f"[ModelRouter] Routed task '{task_type}' to model '{model}'")
    return model
