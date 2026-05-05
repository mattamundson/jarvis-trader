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
import os
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal, Optional

import anthropic
import httpx
from anthropic import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .cost_tracker import CostTracker

try:
    from utils.token_proxy import get_token_proxy
    _TOKEN_PROXY_AVAILABLE = True
except Exception as _tp_err:
    _TOKEN_PROXY_AVAILABLE = False

try:
    from utils.context_mgmt import drop_tool_responses, needs_compaction
    _CONTEXT_MGMT_AVAILABLE = True
except Exception:
    _CONTEXT_MGMT_AVAILABLE = False

logger = logging.getLogger(__name__)


# LLM-path health signal for /health endpoint. Updated by the terminal
# except-block below when we see the underlying Anthropic body. Read by
# health_router.py to report `llm_path_healthy` without needing a new probe.
_LLM_PATH_STATE: dict = {
    "healthy": True,
    "last_failure_ts": None,
    "last_failure_reason": None,
    "last_failure_agent": None,
}


def get_llm_path_state() -> dict:
    """Returns a copy of the current LLM-path health snapshot."""
    return dict(_LLM_PATH_STATE)


def _is_credit_exhaustion(body_or_text: object) -> bool:
    """Detect Anthropic credit-balance-too-low signature in an error body/string."""
    if body_or_text is None:
        return False
    s = str(body_or_text).lower()
    return "credit balance is too low" in s or "credit_balance_too_low" in s or "credit balance too low" in s


_TEMPERATURE_DEPRECATED_PREFIXES = ("claude-opus-4-7",)


def _temperature_deprecated(model: str) -> bool:
    """True if the model rejects the `temperature` param with BadRequestError.

    Anthropic deprecated sampling temperature for claude-opus-4-7; passing it
    returns a 400. All other models still accept it. Prefix match covers suffix
    variants like "claude-opus-4-7[1m]".
    """
    if not model:
        return False
    return any(model.startswith(p) for p in _TEMPERATURE_DEPRECATED_PREFIXES)


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

    # Cost per million tokens (as of 2026-03-29; Opus 4.7 added 2026-04-16, same tier as 4.6)
    COST_PER_MTOK = {
        "claude-opus-4-7": {"input": 15.0, "output": 75.0},
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
        "hermes3:latest": {"input": 0.0, "output": 0.0},
    }

    # Model fallback chain when overloaded
    FALLBACK_CHAIN = {
        "claude-opus-4-7": "claude-sonnet-4-6",
        "claude-opus-4-6": "claude-sonnet-4-6",
        "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
        "claude-haiku-4-5-20251001": None,  # No fallback from Haiku
    }

    MODEL_CONTEXT_LIMITS = {
        "claude-opus-4-7": 200_000,
        "claude-opus-4-6": 200_000,
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5-20251001": 200_000,
        "hermes3:latest": 4_096,
    }

    def __init__(self, api_key: str, db_path: str = "data/llm_costs.db"):
        """
        Initialize the LLM client.

        Args:
            api_key: Anthropic API key
            db_path: Path to SQLite cost tracking database
        """
        self.provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
        self.api_key = "" if self.provider == "ollama" else api_key
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "hermes3:latest")
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        self.ollama_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
        self.client = None if self.provider == "ollama" else anthropic.AsyncAnthropic(api_key=api_key)
        self.cost_tracker = CostTracker(db_path=db_path)
        self.default_model = self.ollama_model if self.provider == "ollama" else "claude-sonnet-4-6"
        self.fast_model = self.ollama_model if self.provider == "ollama" else "claude-haiku-4-5-20251001"
        self.compaction_count = 0
        logger.info(f"✅ JarvisLLMClient initialized with cost tracking at {db_path}")

    async def _handle_success(
        self,
        result,
        current_model: str,
        start_time: float,
        retries: int,
        agent_name: str,
        tier: str = "default",
        proxy=None,
        compressed_key=None,
        cache_salt: str = "",
    ) -> LLMCallResult:
        """Handle successful API call."""
        # Any success clears the credit-exhaustion health flag (transient recovery)
        if not _LLM_PATH_STATE["healthy"]:
            _LLM_PATH_STATE["healthy"] = True
            logger.info(
                "LLM path healthy again after prior failure "
                f"(was: {_LLM_PATH_STATE['last_failure_reason']})"
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
            f"[{current_model}] {agent_name} | tier:{tier} | "
            f"in:{input_tokens} out:{output_tokens} | "
            f"cost:${cost:.4f} | latency:{latency_ms}ms | retries:{retries}"
        )

        result_obj = LLMCallResult(
            success=True,
            model=current_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            retries=retries,
            content=result.content[0].text,
        )

        # TokenProxy — cache successful result
        if proxy is not None and compressed_key is not None:
            try:
                proxy.set_cached(compressed_key, result_obj, model=str(current_model), salt=cache_salt)
            except Exception:
                pass  # graceful — cache write failure never breaks API call

        return result_obj

    async def _handle_failure(
        self,
        last_error: Exception,
        current_model: str,
        start_time: float,
        retries: int,
        agent_name: str,
        tier: str = "default",
    ) -> LLMCallResult:
        """Handle failed API call after retries exhausted."""
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
            f"[{current_model}] ❌ {agent_name} failed after {retries} retries | tier:{tier} | "
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

    async def _try_fallback(
        self,
        current_model: str,
        allow_fallback: bool,
    ) -> Optional[str]:
        """Try fallback model if available."""
        if not allow_fallback or current_model not in self.FALLBACK_CHAIN:
            return None
        return self.FALLBACK_CHAIN[current_model]

    def _resolve_model_for_tier(self, model: str, tier: Literal["fast", "default", "advisor"]) -> str:
        if tier == "fast":
            return self.fast_model
        if model:
            return model
        return self.default_model

    def _estimate_tokens(self, system: str, messages: list[dict]) -> int:
        total_chars = len(system or "")
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, dict):
                total_chars += len(str(content))
            else:
                total_chars += len(str(content))
        return max(1, total_chars // 4)

    async def _summarize_for_compaction(self, middle_messages: list[dict], agent_name: str) -> str:
        if not middle_messages:
            return "No prior context."

        middle_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in middle_messages
        )
        middle_text = middle_text[:12000]

        if not middle_text.strip():
            return "Prior context omitted."

        if not _CONTEXT_MGMT_AVAILABLE:
            return f"{len(middle_messages)} messages summarized for context compaction."

        try:
            summary_result = await self._call_with_retry(
                model=self.fast_model,
                system=(
                    "Summarize the prior conversation context for a trading agent. "
                    "Preserve the important decisions, constraints, market state, and unresolved risks. "
                    "Return plain text only in under 120 words."
                ),
                messages=[{"role": "user", "content": middle_text}],
                max_tokens=220,
                temperature=0.2,
            )
            return summary_result.content[0].text.strip()
        except Exception as exc:
            logger.debug("[%s] fast compaction summary failed: %s", agent_name, exc)
            return f"{len(middle_messages)} prior messages summarized for context compaction."

    async def _maybe_compact_messages(
        self,
        system: str,
        messages: list[dict],
        model: str,
        agent_name: str,
    ) -> list[dict]:
        if not messages or not _CONTEXT_MGMT_AVAILABLE:
            return messages

        context_limit = self.MODEL_CONTEXT_LIMITS.get(model, 200_000)
        current_tokens = self._estimate_tokens(system, messages)
        if not needs_compaction(current_tokens, context_limit):
            return messages

        user_assistant_indices = [
            i for i, message in enumerate(messages) if message.get("role") in ("user", "assistant")
        ]
        if len(user_assistant_indices) <= 4:
            return messages

        tail_start = len(messages)
        count = 0
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") in ("user", "assistant"):
                count += 1
                if count >= 4:
                    tail_start = i
                    break

        middle_messages = messages[:tail_start]
        tail_messages = messages[tail_start:]
        summary = await self._summarize_for_compaction(middle_messages, agent_name)

        compacted = [{"role": "user", "content": f"Prior context summary: {summary}"}]
        compacted.extend(tail_messages)

        for drop_ratio in (0.1, 0.2, 0.5, 1.0):
            if not needs_compaction(self._estimate_tokens(system, compacted), context_limit):
                break
            compacted = drop_tool_responses(compacted, drop_ratio)

        self.compaction_count += 1
        logger.info("[%s] context compaction triggered for %s (count=%d)", model, agent_name, self.compaction_count)
        return compacted

    async def call(
        self,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int = 1024,
        agent_name: str = "unknown",
        temperature: float = 0.7,
        allow_fallback: bool = True,
        tier: Literal["fast", "default", "advisor"] = "default",
        compact: bool = True,
    ) -> LLMCallResult:
        """
        Make an async API call to Claude with retry logic and instrumentation.

        Args:
            model: Model name (e.g. "claude-opus-4-7")
            system: System prompt
            messages: List of message dicts with "role" and "content"
            max_tokens: Max tokens in response
            agent_name: Name of calling agent (for logging)
            temperature: Sampling temperature
            allow_fallback: If True and model is overloaded, try fallback

        Returns:
            LLMCallResult with success, tokens, cost, latency, retries
        """
        working_messages = [dict(message) for message in messages]
        current_model = self._resolve_model_for_tier(model, tier)
        if self.provider == "ollama":
            current_model = self.ollama_model

        if compact:
            try:
                working_messages = await self._maybe_compact_messages(
                    system=system,
                    messages=working_messages,
                    model=current_model,
                    agent_name=agent_name,
                )
            except Exception as exc:
                logger.debug("[%s] context compaction skipped for %s: %s", current_model, agent_name, exc)

        # TokenProxy — compress + cache check
        proxy = None
        compressed_key = None
        cache_salt = f"{current_model}::{tier}::{agent_name}"
        if _TOKEN_PROXY_AVAILABLE and working_messages:
            try:
                proxy = get_token_proxy()
                last_msg = working_messages[-1]
                if isinstance(last_msg, dict) and "content" in last_msg and isinstance(last_msg["content"], str):
                    compressed, cached = proxy.optimize(last_msg["content"], model=str(current_model), salt=cache_salt)
                    if cached is not None:
                        return cached  # cache hit — skip API call entirely
                    last_msg["content"] = compressed
                    compressed_key = compressed
            except Exception:
                # graceful — never let token proxy break API calls
                proxy = None
                compressed_key = None

        start_time = time.time()
        retries = 0
        last_error = None

        # Retry loop with exponential backoff
        while True:
            try:
                result = await self._call_with_retry(
                    model=current_model,
                    system=system,
                    messages=working_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return await self._handle_success(
                    result, current_model, start_time, retries, agent_name,
                    tier=tier, proxy=proxy, compressed_key=compressed_key, cache_salt=cache_salt
                )

            except RateLimitError as e:
                last_error = e
                logger.warning(
                    f"[{current_model}] Rate limit (429) for {agent_name} — attempt {retries + 1}/3"
                )
                retries += 1

                if retries >= 3:
                    fallback = await self._try_fallback(current_model, allow_fallback)
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

            except (APIConnectionError, APIStatusError) as e:
                last_error = e
                status = getattr(e, "status_code", "unknown")
                logger.warning(
                    f"[{current_model}] API error ({status}) for {agent_name} — attempt {retries + 1}/3"
                )
                retries += 1

                if retries >= 3:
                    fallback = await self._try_fallback(current_model, allow_fallback)
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
                body_str: str = ""
                raw = getattr(e, "last_attempt", None)
                if raw is not None:
                    try:
                        underlying = raw.exception()
                        body = getattr(underlying, "body", None) or getattr(
                            getattr(underlying, "response", None), "text", None
                        )
                        body_str = str(body) if body else str(underlying)
                        logger.error(
                            f"[{current_model}] {agent_name} final failure: "
                            f"{type(underlying).__name__}: {body or underlying}"
                        )
                    except Exception:
                        body_str = str(e)
                        logger.error(f"[{current_model}] Unexpected error for {agent_name}: {e}")
                else:
                    body_str = str(e)
                    logger.error(f"[{current_model}] Unexpected error for {agent_name}: {e}")

                if _is_credit_exhaustion(body_str):
                    _LLM_PATH_STATE["healthy"] = False
                    _LLM_PATH_STATE["last_failure_ts"] = datetime.now(timezone.utc).isoformat()
                    _LLM_PATH_STATE["last_failure_reason"] = body_str[:500]
                    _LLM_PATH_STATE["last_failure_agent"] = agent_name
                    try:
                        from notifications.openclaw_notifier import notify_credits_exhausted
                        asyncio.create_task(
                            notify_credits_exhausted(reason=body_str[:300], agent=agent_name)
                        )
                    except Exception as notify_err:
                        logger.debug(f"credits-exhausted notifier failed: {notify_err}")
                break

        return await self._handle_failure(
            last_error, current_model, start_time, retries, agent_name, tier=tier
        )

    def _messages_to_ollama_prompt(self, system: str, messages: list[dict]) -> str:
        parts: list[str] = []
        if system:
            parts.append(f"System:\n{system}")
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            parts.append(f"{role.title()}:\n{content}")
        parts.append("Assistant:")
        return "\n\n".join(parts)

    async def _call_ollama(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ):
        prompt = self._messages_to_ollama_prompt(system, messages)
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.ollama_keep_alive,
            "options": {
                "num_ctx": self.ollama_num_ctx,
                "num_predict": min(max_tokens, self.ollama_num_predict),
                "temperature": temperature,
            },
        }
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.ollama_host}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = data.get("response", "")
        input_tokens = int(data.get("prompt_eval_count") or self._estimate_tokens(system, messages))
        output_tokens = int(data.get("eval_count") or max(1, len(text) // 4))
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text)],
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
        Low-level async call to the configured LLM provider.
        Retries are handled at the call() level.
        """
        if self.provider == "ollama":
            return await self._call_ollama(system, messages, max_tokens, temperature)

        kwargs = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if not _temperature_deprecated(model):
            kwargs["temperature"] = temperature
        return await self.client.messages.create(**kwargs)

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD cost for a single API call."""
        if model not in self.COST_PER_MTOK:
            logger.warning(f"Unknown model {model} — no cost calculation")
            return 0.0

        costs = self.COST_PER_MTOK[model]
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    async def track_raw_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        agent_name: str = "unknown",
        success: bool = True,
    ) -> None:
        """
        Record cost metrics for an LLM call made via raw HTTP (not via .call()).

        Use this in agents that build their own httpx/requests calls so that their
        token usage still appears in the /llm/stats endpoint.

        Args:
            model: Model name, e.g. "claude-sonnet-4-6"
            input_tokens: Input token count from the API response usage field
            output_tokens: Output token count from the API response usage field
            latency_ms: Elapsed wall-clock milliseconds for the HTTP round-trip
            agent_name: Calling agent identifier (for per-agent cost breakdown)
            success: True if the HTTP call returned a 2xx status
        """
        cost = self._calculate_cost(model, input_tokens, output_tokens)
        await self.cost_tracker.log_call(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            agent_name=agent_name,
            success=success,
        )

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


# Module-level billing error flag — set to True by callers that receive a
# billing/credit error from the Anthropic API so the health endpoint can
# surface "llm_available": false without crashing.
_billing_error_active: bool = False


def set_billing_error_active(active: bool) -> None:
    """Mark or clear the billing error flag."""
    global _billing_error_active
    _billing_error_active = active


def is_billing_error_active() -> bool:
    """Return True if a billing/credit error has been detected."""
    return _billing_error_active

