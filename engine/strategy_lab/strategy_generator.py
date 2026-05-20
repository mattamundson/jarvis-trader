"""
LLM-powered strategy variation generator.
Uses claude-sonnet-4-6 (via JarvisLLMClient → Gemini fallback) to generate
parameter variants of the baseline STC+ATR strategy.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

STRATEGY_GENERATION_PROMPT = """You are an autonomous trading strategy researcher for micro futures (MES/MNQ on CME).

Current baseline strategy:
- STC oscillator (OS=15, OB=83) as primary entry signal
- ATR-based stop (0.70x ATR) and target (1.50x ATR)
- 5-layer regime filter enabled
- Primary timeframe: 1h

Your task: Generate ONE variation by modifying parameters within these bounds:
- stc_oversold: 13-25 (integer)
- stc_overbought: 78-95 (integer)
- atr_stop_mult: 0.40-1.20 (float, 2 decimals)
- atr_target_mult: 1.00-3.00 (float, 2 decimals)
- timeframe: one of "15m", "30m", "1h", "4h"
- adx_min_threshold: 15-35 (integer, minimum ADX to allow entry)
- vwap_filter_enabled: true or false

Rules:
1. stc_oversold must be < stc_overbought - 20 (keep meaningful separation)
2. atr_target_mult must be > atr_stop_mult (positive expected value)
3. Vary at least 2 parameters from baseline

Respond with ONLY valid JSON, no explanation:
{
  "strategy_name": "short_descriptive_name_no_spaces",
  "description": "one sentence explaining the hypothesis",
  "parameters": {
    "stc_oversold": 15,
    "stc_overbought": 83,
    "atr_stop_mult": 0.70,
    "atr_target_mult": 1.50,
    "timeframe": "1h",
    "adx_min_threshold": 20,
    "vwap_filter_enabled": true
  }
}

Previous attempts (avoid duplicating these parameter sets):
{previous_attempts}

Focus for this iteration: {focus_area}"""


def generate_strategy_variant(
    llm_client,
    previous_attempts: list,
    focus_area: str = "improve win rate",
) -> dict:
    """
    Ask Claude to generate a new strategy parameter variant.

    Args:
        llm_client: JarvisLLMClient instance (provides retry + Gemini fallback +
            cost tracking; see engine/llm/client.py)
        previous_attempts: List of previous result dicts (used to avoid duplicates)
        focus_area: Optimization objective for this iteration

    Returns:
        Dict with 'strategy_name', 'description', 'parameters' keys

    Raises:
        ValueError: If LLM response cannot be parsed as valid JSON
        RuntimeError: If JarvisLLMClient.call() returns success=False
    """
    prev_summary = [
        {
            "name": a.get("strategy_name", "unknown"),
            "verdict": a.get("verdict", "pending"),
            "params": a.get("parameters", {}),
        }
        for a in previous_attempts[-10:]  # Last 10 to control context size
    ]

    prompt = STRATEGY_GENERATION_PROMPT.format(
        previous_attempts=json.dumps(prev_summary, indent=2),
        focus_area=focus_area,
    )

    # JarvisLLMClient.call() is async; this function is sync (called from a
    # CLI/cron loop, not inside an event loop), so we drive it with asyncio.run.
    result = asyncio.run(
        llm_client.call(
            model="claude-sonnet-4-6",
            system="",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            agent_name="strategy_lab",
        )
    )
    if not result.success:
        raise RuntimeError(result.error or "LLM call failed without error message")

    raw = result.content.strip()

    # Strip markdown code fences if present
    for fence in ["```json", "```"]:
        if fence in raw:
            raw = raw.split(fence, 1)[1]
            if "```" in raw:
                raw = raw.split("```", 1)[0]
            raw = raw.strip()
            break

    try:
        variant = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw response: {raw[:200]}") from e

    # Validate required fields
    required = ["strategy_name", "parameters"]
    missing = [f for f in required if f not in variant]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")

    required_params = [
        "stc_oversold",
        "stc_overbought",
        "atr_stop_mult",
        "atr_target_mult",
        "timeframe",
    ]
    missing_params = [p for p in required_params if p not in variant.get("parameters", {})]
    if missing_params:
        raise ValueError(f"LLM parameters missing: {missing_params}")

    return variant
