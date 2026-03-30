"""
JARVIS TRADER — Robust LLM Client
===================================
Wraps anthropic.AsyncAnthropic with retry logic, token tracking, cost calculation,
and detailed logging. Handles rate limits, timeouts, and connection errors with
exponential backoff (1s → 2s → 4s).

Tracks daily costs per model and provides fallback escalation:
  Opus (best) → Sonnet (balanced) → Haiku (fast) when overloaded

Cost per token (as of 2026-03-29):
  Opus:   $15 / MTok input, $75 / MTok output
  Sonnet: $3 / MTok input,  $15 / MTok output
  Haiku:  $0.80 / MTok input, $4 / MTok output
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anthropic
from anthropic import RateLimitError, APIConnectionError, APIStatusError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)

from .cost_tracker import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class LLMCallResult:
    """Result of an LLM API call with metrics."""
    success: bool
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    retries: int
    content: str = ""
    error: Optional[str] = None


class JarvisLLMClient:
    """
    Robust, instrumented LLM client with retry logic, token tracking,
    and cost monitoring.

    Features:
    - Async client wrapping anthropic.AsyncAnthropic
    - Retry with exponential backoff: 3 attempts, 1s → 2s → 4s
    - Retries on 429 (rate limit), 500, 503, and connection errors
    - Counts input/output tokens per call
    - Tracks daily cost per model
    - Fallback: Opus → Sonnet → Haiku if overloaded
    - Comprehensive logging with model, tokens, latency, cost, retries
    - get_daily_stats() method
    """

    # Cost per million tokens (as of 2026-03-29)
    COST_PER_MTOK = {
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    }

    # Model fallback chain when overloaded
    FALLBACK_CHAIN = {
        "claude-opus-4-6": "claude-sonnet-4-6",
        "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
        "claude-haiku-4-5-20251001": None,  # No fallback from Haiku
    }

    def __init__(self, api_key: str, db_path: str = "data/llm_costs.db"):
        """
        Initialize the LLM client.

        Args:
            api_key: Anthropic API key
            db_path: Path to SQLite cost tracking database
        """
        self.api_key = api_key
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.cost_tracker = CostTracker(db_path=db_path)
        logger.info(f"✅ JarvisLLMClient initialized with cost tracking at {db_path}")

    async def call(
        self,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int = 1024,
        agent_name: str = "unknown",
        temperature: float = 0.7,
        allow_fallback: bool = True,
    ) -> LLMCallResult:
        """
        Make an async API call to Claude with retry logic and instrumentation.

        Args:
            model: Model name (e.g. "claude-opus-4-6")
            system: System prompt
            messages: List of message dicts with "role" and "content"
            max_tokens: Max tokens in response
            agent_name: Name of calling agent (for logging)
            temperature: Sampling temperature
            allow_fallback: If True and model is overloaded, try fallback

        Returns:
            LLMCallResult with success, tokens, cost, latency, retries
        """
        start_time = time.time()
        retries = 0
        last_error = None
        current_model = model

        # Retry loop with exponential backoff
        while True:
            try:
                result = await self._call_with_retry(
                    model=current_model,
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                latency_ms = int((time.time() - start_time) * 1000)
                input_tokens = result.usage.input_tokens
                output_tokens = result.usage.output_tokens
                cost = self._calculate_cost(current_model, input_tokens, output_tokens)

                # Log to database
                await self.cost_tracker.log_call(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    model=current_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    agent_name=agent_name,
                    success=True,
                )

                # Log to console
                logger.info(
                    f"[{current_model}] {agent_name} | "
                    f"in:{input_tokens} out:{output_tokens} | "
                    f"cost:${cost:.4f} | latency:{latency_ms}ms | retries:{retries}"
                )

                return LLMCallResult(
                    success=True,
                    model=current_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    retries=retries,
                    content=result.content[0].text,
                )

            except RateLimitError as e:
                last_error = e
                logger.warning(f"[{current_model}] Rate limit (429) for {agent_name} — attempt {retries + 1}/3")
                retries += 1

                if retries >= 3:
                    if allow_fallback and current_model in self.FALLBACK_CHAIN:
                        fallback = self.FALLBACK_CHAIN[current_model]
                        if fallback:
                            logger.warning(
                                f"[{current_model}] Max retries exhausted. "
                                f"Falling back to {fallback} for {agent_name}"
                            )
                            current_model = fallback
                            retries = 0
                            start_time = time.time()
                            continue
                    break

                # Exponential backoff: 1s, 2s, 4s
                delay = 2 ** (retries - 1)
                await asyncio.sleep(delay)

            except (APIConnectionError, APIStatusError) as e:
                last_error = e
                status = getattr(e, "status_code", "unknown")
                logger.warning(f"[{current_model}] API error ({status}) for {agent_name} — attempt {retries + 1}/3")
                retries += 1

                if retries >= 3:
                    if allow_fallback and current_model in self.FALLBACK_CHAIN:
                        fallback = self.FALLBACK_CHAIN[current_model]
                        if fallback:
                            logger.warning(
                                f"[{current_model}] Max retries exhausted. "
                                f"Falling back to {fallback} for {agent_name}"
                            )
                            current_model = fallback
                            retries = 0
                            start_time = time.time()
                            continue
                    break

                delay = 2 ** (retries - 1)
                await asyncio.sleep(delay)

            except Exception as e:
                last_error = e
                logger.error(f"[{current_model}] Unexpected error for {agent_name}: {e}")
                break

        # All retries exhausted or unexpected error
        latency_ms = int((time.time() - start_time) * 1000)
        error_msg = str(last_error) if last_error else "Unknown error"

        # Log failure to database
        await self.cost_tracker.log_call(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=current_model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
            agent_name=agent_name,
            success=False,
        )

        logger.error(
            f"[{current_model}] ❌ {agent_name} failed after {retries} retries | "
            f"latency:{latency_ms}ms | error:{error_msg}"
        )

        return LLMCallResult(
            success=False,
            model=current_model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
            retries=retries,
            error=error_msg,
        )

    @retry(
        stop=stop_after_attempt(1),  # Single attempt; retries handled at call() level
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, APIStatusError)),
    )
    async def _call_with_retry(
        self,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ):
        """
        Low-level async call to Anthropic API.
        Retries are handled at the call() level.
        """
        return await self.client.messages.create(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD cost for a single API call."""
        if model not in self.COST_PER_MTOK:
            logger.warning(f"Unknown model {model} — no cost calculation")
            return 0.0

        costs = self.COST_PER_MTOK[model]
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    async def get_daily_stats(self) -> dict:
        """
        Get daily cost and usage statistics.

        Returns:
            Dict with total_cost, total_calls, calls_per_model, etc.
        """
        return await self.cost_tracker.get_daily_summary()

    async def get_monthly_stats(self) -> dict:
        """Get monthly cost and usage statistics."""
        return await self.cost_tracker.get_monthly_summary()

    async def close(self):
        """Close the cost tracker database connection."""
        await self.cost_tracker.close()
