"""
Token Cost Optimizer for JARVIS TRADER pipeline.

Strategies based on @seelffff's research (rtk CLI patterns adapted to Python):
1. Anthropic Prompt Caching — 60-70% reduction on repeated system prompts
2. Model tiering — Haiku for low-stakes analysis (10x cheaper)
3. Context pruning — Remove low-IC agents from expensive debate context
4. Response compression — Structured output reduces output tokens

Usage:
    optimizer = TokenOptimizer()

    # Add cache_control to static system prompt
    system_block = optimizer.add_prompt_cache(agent_system_prompt)
    # Pass as system= param in anthropic client.messages.create():
    #   await client.messages.create(system=[system_block], ...)

    # Select optimal model for agent
    model = optimizer.select_model("technical", signal_strength=0.8)

    # Compress analyst report for debate context
    compressed = optimizer.compress_analyst_report(report, agent_name="news", ic_score=0.05)

Integration with JarvisLLMClient:
    # Enable prompt caching by adding beta headers to the client:
    #   client = anthropic.AsyncAnthropic(
    #       api_key=api_key,
    #       default_headers=optimizer.get_cache_headers()
    #   )
    # Then wrap system prompts:
    #   system=[optimizer.add_prompt_cache(system_prompt)]
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constants — align with JarvisLLMClient.COST_PER_MTOK keys
# ---------------------------------------------------------------------------
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_OPUS = "claude-opus-4-7"

# Agents that ALWAYS use Sonnet or better (final decision makers)
HIGH_STAKES_AGENTS = {"trader", "risk_manager", "fund_manager"}

# Agents eligible for Haiku when signal is weak (exploratory / supporting analysts)
HAIKU_ELIGIBLE_AGENTS = {"social", "fundamental", "news", "corey"}

# IC threshold below which an analyst context is pruned entirely from debate
IC_PRUNE_THRESHOLD = 0.05

# Signal threshold below which Haiku routing is applied for eligible agents
HAIKU_SIGNAL_THRESHOLD = 0.40


@dataclass
class OptimizationStats:
    """Track token/cost optimization savings within a session."""
    cached_prompts: int = 0
    haiku_routes: int = 0
    pruned_contexts: int = 0
    estimated_tokens_saved: int = 0


class TokenOptimizer:
    """
    Token cost optimizer for the JARVIS TRADER LLM pipeline.

    All methods are side-effect free and non-destructive — they return
    modified copies, never mutate inputs. Safe to use or skip.

    Design notes:
    - add_prompt_cache() wraps a system prompt string in the Anthropic
      prompt-caching content block format. Requires anthropic-beta header
      (see get_cache_headers()).
    - select_model() routes supporting analysts to Haiku when signal is weak,
      always uses Sonnet for final decision agents.
    - compress_analyst_report() drops zero-IC analysts and trims verbose prose
      to a minimal key-value summary for the debate stage.
    """

    def __init__(
        self,
        prompt_cache_enabled: bool = True,
        haiku_routing_enabled: bool = True,
    ):
        self.stats = OptimizationStats()
        self._prompt_cache_enabled = prompt_cache_enabled
        self._haiku_routing_enabled = haiku_routing_enabled

    # ------------------------------------------------------------------
    # 1. Prompt Caching
    # ------------------------------------------------------------------

    def add_prompt_cache(self, system_prompt: str) -> dict:
        """
        Wrap a system prompt string in an Anthropic prompt-caching content block.

        Anthropic's beta prompt caching feature caches the system prompt for
        up to 5 minutes, saving ~70% of input tokens on repeated pipeline calls
        (cache read costs $0.30/MTok vs $3.00/MTok for full input on Sonnet).

        Returns a system content block dict:
            {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}

        Usage:
            system_block = optimizer.add_prompt_cache(agent_system_prompt)
            result = await client.messages.create(
                model=model,
                system=[system_block],   # <-- list wrapping required
                messages=messages,
                ...
            )

        Requires: anthropic-beta header — see get_cache_headers().
        When caching is disabled, returns a plain text block without cache_control.
        """
        if not self._prompt_cache_enabled:
            return {"type": "text", "text": system_prompt}

        self.stats.cached_prompts += 1
        # Conservative estimate: ~400 tokens saved per cached call (Sonnet input rate)
        self.stats.estimated_tokens_saved += 400

        return {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }

    def get_cache_headers(self) -> dict:
        """
        Return Anthropic beta headers required for prompt caching.

        Add to the AsyncAnthropic client at construction time:
            client = anthropic.AsyncAnthropic(
                api_key=api_key,
                default_headers=optimizer.get_cache_headers()
            )

        Without this header, cache_control blocks are silently ignored.
        """
        return {"anthropic-beta": "prompt-caching-2024-07-31"}

    # ------------------------------------------------------------------
    # 2. Model Tiering
    # ------------------------------------------------------------------

    def select_model(
        self,
        agent_name: str,
        signal_strength: float = 0.5,
        force_quality: bool = False,
    ) -> str:
        """
        Select the optimal model tier for a given agent + signal combination.

        Routing logic:
        - force_quality=True or agent in HIGH_STAKES_AGENTS → Sonnet (always)
        - HAIKU_ELIGIBLE_AGENTS + signal_strength < 0.40 → Haiku (10x cheaper)
        - All other cases → Sonnet

        Cost impact:
            Haiku:  $0.80 input / $4.00 output per MTok
            Sonnet: $3.00 input / $15.00 output per MTok
            Saving: ~73% on input tokens when routing weak-signal analysts to Haiku

        Args:
            agent_name:      Pipeline agent identifier (case-insensitive)
            signal_strength: Absolute signal magnitude, 0.0–1.0
            force_quality:   Override all routing; always return Sonnet

        Returns:
            Model ID string compatible with JarvisLLMClient.call()
        """
        if force_quality:
            return MODEL_SONNET

        if agent_name.lower() in HIGH_STAKES_AGENTS:
            return MODEL_SONNET

        if (
            self._haiku_routing_enabled
            and agent_name.lower() in HAIKU_ELIGIBLE_AGENTS
            and signal_strength < HAIKU_SIGNAL_THRESHOLD
        ):
            self.stats.haiku_routes += 1
            self.stats.estimated_tokens_saved += 1200  # ~$0.003 saved per call
            logger.debug(
                "Token routing: %s signal_strength=%.2f → %s (10x cheaper than Sonnet)",
                agent_name,
                signal_strength,
                MODEL_HAIKU,
            )
            return MODEL_HAIKU

        return MODEL_SONNET

    # ------------------------------------------------------------------
    # 3. Context Pruning + Compression
    # ------------------------------------------------------------------

    def compress_analyst_report(
        self,
        report: Any,
        agent_name: str,
        ic_score: float = 0.5,
        max_reasons: int = 3,
    ) -> Optional[str]:
        """
        Compress an analyst report to a minimal debate context string.

        If the agent's IC score is below IC_PRUNE_THRESHOLD (0.05), the report
        is pruned entirely — the agent has no statistically significant predictive
        value and including their verbose prose wastes debate context tokens.

        Otherwise, extract: direction, signal magnitude, confidence, IC, reasons.
        This typically reduces ~800-token prose reports to ~50-token summaries.

        Compatible with all analyst report types:
            SocialReport  — .signal, .confidence, .key_factors
            TechnicalReport — .signal, .confidence, .reasons
            FundamentalReport — .score, .conviction, .analysis
            NewsReport — .sentiment_score, .confidence

        Args:
            report:      Analyst report object (any type with signal-like attr)
            agent_name:  Name for logging and prefix in compressed output
            ic_score:    Information Coefficient 0.0–0.5. Below 0.05 → pruned.
            max_reasons: Max reason entries to include (avoids verbosity)

        Returns:
            Compressed one-line string for debate context, or None if pruned
        """
        if ic_score < IC_PRUNE_THRESHOLD:
            self.stats.pruned_contexts += 1
            self.stats.estimated_tokens_saved += 200
            logger.debug(
                "Context pruned: %s IC=%.3f below threshold=%.3f",
                agent_name,
                ic_score,
                IC_PRUNE_THRESHOLD,
            )
            return None

        if report is None:
            return None

        # Extract signal — handle multiple field name conventions
        raw_signal = (
            getattr(report, "signal", None)
            or getattr(report, "bias", None)
            or getattr(report, "sentiment_score", None)
            or getattr(report, "score", None)
            or 0.0
        )
        try:
            signal = float(raw_signal)
        except (TypeError, ValueError):
            signal = 0.0

        # Extract confidence
        raw_conf = getattr(report, "confidence", None) or getattr(report, "conviction", None) or 0.5
        try:
            confidence = float(raw_conf)
        except (TypeError, ValueError):
            confidence = 0.5

        # Derive directional label
        if signal > 0:
            direction = "BULLISH"
        elif signal < 0:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Extract reasons/factors
        reasons_raw = (
            getattr(report, "key_factors", None)
            or getattr(report, "reasons", None)
            or getattr(report, "analysis", None)
            or []
        )
        if isinstance(reasons_raw, str):
            reasons_str = reasons_raw[:300] + "..." if len(reasons_raw) > 300 else reasons_raw
        elif isinstance(reasons_raw, list):
            reasons_str = "; ".join(str(r) for r in reasons_raw[:max_reasons])
        else:
            reasons_str = ""

        compressed = (
            f"{agent_name.upper()}: {direction} signal={signal:.2f} "
            f"conf={confidence:.2f} IC={ic_score:.3f}"
        )
        if reasons_str:
            compressed += f" | {reasons_str}"

        self.stats.estimated_tokens_saved += 100
        return compressed

    # ------------------------------------------------------------------
    # 4. Stats / Reporting
    # ------------------------------------------------------------------

    def estimate_pipeline_savings(self) -> dict:
        """
        Estimate total token cost savings for the current session.

        Cost rates used (USD per 1M tokens, April 2026):
            Sonnet input:      $3.00
            Haiku input:       $0.80
            Cache read input:  $0.30

        Returns:
            Dict with savings breakdown and USD estimates
        """
        SONNET_INPUT_COST = 3.0    # $/MTok
        HAIKU_INPUT_COST = 0.80    # $/MTok
        CACHE_READ_COST = 0.30     # $/MTok

        # Haiku routing savings: per-route avg 1,500 tokens at Sonnet price delta
        haiku_tokens = self.stats.haiku_routes * 1500
        haiku_usd = haiku_tokens * (SONNET_INPUT_COST - HAIKU_INPUT_COST) / 1_000_000

        # Prompt caching savings: per-cache avg 400 tokens at Sonnet→cache delta
        cache_tokens = self.stats.cached_prompts * 400
        cache_usd = cache_tokens * (SONNET_INPUT_COST - CACHE_READ_COST) / 1_000_000

        return {
            "haiku_routes": self.stats.haiku_routes,
            "cached_prompts": self.stats.cached_prompts,
            "pruned_contexts": self.stats.pruned_contexts,
            "estimated_tokens_saved": self.stats.estimated_tokens_saved,
            "estimated_usd_saved": round(haiku_usd + cache_usd, 4),
            "haiku_savings_usd": round(haiku_usd, 4),
            "cache_savings_usd": round(cache_usd, 4),
        }

    def log_summary(self) -> None:
        """Log a one-line optimization summary at INFO level."""
        s = self.estimate_pipeline_savings()
        logger.info(
            "TokenOptimizer session: haiku_routes=%d cached=%d pruned=%d "
            "est_saved=%d tokens (~$%.4f)",
            s["haiku_routes"],
            s["cached_prompts"],
            s["pruned_contexts"],
            s["estimated_tokens_saved"],
            s["estimated_usd_saved"],
        )


# ---------------------------------------------------------------------------
# Module-level singleton — shared across the pipeline
# ---------------------------------------------------------------------------
_optimizer_instance: Optional[TokenOptimizer] = None


def get_optimizer() -> TokenOptimizer:
    """
    Get (or create) the module-level TokenOptimizer singleton.

    Using a singleton ensures stats accumulate across all pipeline stages
    within a single process lifetime. Safe to call from multiple agents.
    """
    global _optimizer_instance
    if _optimizer_instance is None:
        _optimizer_instance = TokenOptimizer()
    return _optimizer_instance
