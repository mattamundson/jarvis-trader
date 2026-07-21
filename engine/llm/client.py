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
import os
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
    # Provider observability (2026-06-06): which leg is actually serving and how
    # many legs are wired. The boolean `healthy` alone hides the real fragility —
    # e.g. running on the Gemini fallback with the Anthropic primary credit-dead
    # and nothing behind Gemini is "healthy" but one failure from dark.
    "active_provider": None,  # last provider that served a successful call
    "primary_provider": None,  # the configured primary (anthropic|ollama|vertex)
    "providers_configured": [],  # wired legs, primary-first then failover order
    # Cumulative resilience counters (process lifetime). Mirrored from the
    # active client's instance counters at each failover/fallback so /health
    # can surface them without a handle on the client singleton.
    "vertex_failover_count": 0,
    "google_fallback_count": 0,
}


def get_llm_path_state() -> dict:
    """Returns a copy of the current LLM-path health snapshot."""
    return dict(_LLM_PATH_STATE)


def _provider_from_model(model: str) -> str:
    """Map a served model id to its provider family for active-leg reporting."""
    m = (model or "").lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("deepseek"):
        return "deepseek"
    if "ollama" in m or m.startswith("llama") or m.startswith("qwen"):
        return "ollama"
    if m.startswith("kimi"):
        return "kimi"
    return "anthropic"  # claude-* (direct or via Vertex — Vertex passes served_by)


def get_llm_provider_summary() -> dict:
    """Provider-redundancy snapshot for /health.

    Returns which leg is serving now, how many legs are wired, and a
    `single_leg_warning` that fires when the pipeline is one provider-failure
    from going dark — either only one leg is configured, or the primary is
    degraded and the active fallback is the last one with nothing behind it.
    """
    s = _LLM_PATH_STATE
    configured = list(s.get("providers_configured") or [])
    active = s.get("active_provider")
    primary = s.get("primary_provider")
    healthy = bool(s.get("healthy", True))
    # primary_healthy: the configured primary is the active server (not failing over)
    primary_healthy = healthy and (active is None or active == primary)

    single_leg = len(configured) <= 1
    if not single_leg and active is not None and active != primary:
        # Running on a fallback — is there another wired leg behind the active one?
        try:
            idx = configured.index(active)
            single_leg = idx >= len(configured) - 1
        except ValueError:
            single_leg = False

    return {
        "active_provider": active,
        "primary_provider": primary,
        "providers_configured": configured,
        "providers_available": len(configured),
        "primary_healthy": primary_healthy,
        "single_leg_warning": single_leg,
    }


# Hard wall-clock ceiling for a SINGLE provider call. This is a defensive
# backstop ABOVE each provider's own httpx/SDK read timeout: on 2026-06-04 a
# single technical_analyst Gemini call ran ~3.9h (logged latency 13981666ms)
# and froze the entire async pipeline for ~13h of wall-clock — no scans, no
# decisions, no trades — because the per-read httpx timeout never tripped on a
# stalled connection. asyncio.wait_for guarantees no single call can exceed the
# ceiling regardless of how the transport stalls. Override via env.
_DEFAULT_LLM_HARD_TIMEOUT_SECONDS = 120.0

# Cap on simultaneous outbound LLM calls (see JarvisLLMClient.__init__). A scan
# fans out 4 analysts + debate bull/bear/tail across multiple symbols, so without
# a bound the pipeline can put dozens of calls in flight at once, saturating the
# single event loop (starving /health + the scheduler under a network flap) and
# opening a burst of un-pooled connections. Tunable via LLM_MAX_CONCURRENCY.
_DEFAULT_LLM_MAX_CONCURRENCY = 6


def _granular_httpx_timeout(read_seconds: float) -> httpx.Timeout:
    """Per-phase httpx timeout instead of one float for every phase.

    ``httpx.AsyncClient(timeout=60)`` sets connect/read/write/pool all to 60s, so a
    network flap during the TLS/connect phase blocks for the full read budget
    (60-180s) before failing over. Bounding connect/write/pool tightly makes a
    flap-during-connect fail in ~10s while preserving the caller's longer read
    budget for the actual generation.
    """
    connect = min(10.0, read_seconds)
    return httpx.Timeout(connect=connect, read=read_seconds, write=10.0, pool=10.0)


class LLMHardTimeoutError(Exception):
    """Raised when one provider call exceeds the hard wall-clock ceiling.

    Treated by call()'s except blocks like any other provider failure, so the
    normal fallback chain (Vertex -> Gemini -> OpenAI -> unhealthy) still fires. The point
    is bounding: a hung call fails fast instead of freezing the event loop.
    """


def _is_credit_exhaustion(body_or_text: object) -> bool:
    """Detect Anthropic credit-balance-too-low signature in an error body/string."""
    if body_or_text is None:
        return False
    s = str(body_or_text).lower()
    return (
        "credit balance is too low" in s
        or "credit_balance_too_low" in s
        or "credit balance too low" in s
    )


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
    # Gemini cost via OpenAI-compatible endpoint (Phase 3, 2026-05-20):
    # gemini-2.5-flash: $0.30/MTok input, $2.50/MTok output (~10x cheaper than Sonnet)
    # gemini-2.0-flash: $0.10/MTok input, $0.40/MTok output (~30x cheaper than Sonnet)
    COST_PER_MTOK = {
        "claude-opus-4-7": {"input": 15.0, "output": 75.0},
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
        "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
        "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
        "hermes3:latest": {"input": 0.0, "output": 0.0},
        # Kimi K3 (Moonshot AI), added 2026-07-18. Live-verified pricing at
        # platform.kimi.ai/docs/pricing/chat-k3: cache-hit input is $0.30/MTok,
        # but the client doesn't yet parse cache-hit token counts from the
        # response, so the conservative cache-miss rate is used here — this
        # will overstate cost on cache hits, never understate it.
        "kimi-k3": {"input": 3.0, "output": 15.0},
    }

    # Model fallback chain when overloaded
    FALLBACK_CHAIN = {
        "claude-opus-4-7": "claude-sonnet-4-6",
        "claude-opus-4-6": "claude-sonnet-4-6",
        "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
        "claude-haiku-4-5-20251001": None,  # No fallback from Haiku
        "deepseek-reasoner": "claude-sonnet-4-6",
    }

    # Phase 3 (2026-05-20): Anthropic → Gemini failover map. Used when an
    # Anthropic call hits credit-exhaustion or persistent 5xx and a Google
    # API key is configured.
    #
    # 2026-06-04: Haiku previously mapped to gemini-2.0-flash, which 404s at the
    # OpenAI-compat endpoint (resource-not-found — not a transient 5xx) while
    # gemini-2.5-flash returns 200 with the same key/endpoint. With Anthropic
    # credit-exhausted, that broke the failover for every Haiku-tier agent
    # (news_analyst, social_analyst) — they 404'd on both the proactive Gemini
    # primary path and the credit-exhaustion fallback. Route Haiku to the
    # known-good 2.5-flash; still ~10x cheaper than Sonnet. (Cost-table and
    # context-limit entries for 2.0-flash are retained so it can be restored via
    # config if Google re-enables it.)
    #
    # 2026-06-22: with Anthropic credit-exhausted for days, the decision-grade
    # tiers (Opus/Sonnet — trader, risk_manager, fund_manager, debate, bull/bear
    # researcher) ran on 2.5-FLASH, the cheap/fast tier. Promote those to
    # gemini-2.5-pro: materially stronger reasoning, same key/endpoint, and the
    # _call_google thinking-token floor + reasoning_effort=none guard already
    # cover all gemini-2.5* models, so pro returns full content (verified 200+OK).
    # Haiku stays on flash (enrichment/classification — not trade decisions).
    GOOGLE_FAILOVER_MAP = {
        "claude-opus-4-7": "gemini-2.5-pro",
        "claude-opus-4-6": "gemini-2.5-pro",
        "claude-sonnet-4-6": "gemini-2.5-pro",
        "claude-haiku-4-5-20251001": "gemini-2.5-flash",
    }

    # Phase 3.6 (2026-06-06): OpenAI is the last-resort fallback when both
    # Anthropic and Gemini are unavailable. Opus/Sonnet → gpt-4o (equivalent
    # capability tier); Haiku → gpt-4o-mini (fast/cheap tier).
    OPENAI_FAILOVER_MAP = {
        "claude-opus-4-7": "gpt-4o",
        "claude-opus-4-6": "gpt-4o",
        "claude-sonnet-4-6": "gpt-4o",
        "claude-haiku-4-5-20251001": "gpt-4o-mini",
    }

    # Agents routed to Gemini 2.5-flash as primary provider (not as fallback).
    # These are context-enrichment / classification tasks — not trade decisions.
    # Keeps credit consumption on cost-efficient Gemini; Anthropic reserved for
    # trader, risk_manager, fund_manager, and debate-stage agents.
    GEMINI_PRIMARY_AGENTS: frozenset[str] = frozenset(
        {
            "news_analyst",
            "social_analyst",
            "deep_analyzer",
            "technical_analyst",
            "fundamental_analyst",
            "hermes-upgrade-classifier",
            "bookmark_clusterer",
            "kairos_dreaming",
        }
    )

    MODEL_CONTEXT_LIMITS = {
        "claude-opus-4-7": 200_000,
        "claude-opus-4-6": 200_000,
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5-20251001": 200_000,
        "gemini-2.5-pro": 1_000_000,
        "gemini-2.5-flash": 1_000_000,
        "gemini-2.0-flash": 1_000_000,
        "gpt-4o": 128_000,
        "gpt-4o-mini": 128_000,
        "deepseek-reasoner": 64_000,
        "hermes3:latest": 4_096,
        "kimi-k3": 1_048_576,
    }

    # Class-level default — read at line 445/650 etc. Subclasses or callers that
    # bypass __init__ (mocks, __new__, pickle) get the default rather than an
    # AttributeError.  __init__ overwrites with the env-derived value.
    provider: str = "ollama"

    def __init__(self, api_key: Optional[str] = None, db_path: str = "data/llm_costs.db"):
        """
        Initialize the LLM client.

        Args:
            api_key: Anthropic API key (not required when JARVIS_LLM_PROVIDER=ollama)
            db_path: Path to SQLite cost tracking database
        """
        self.provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
        self.api_key = "" if self.provider == "ollama" else (api_key or "")
        # Hard wall-clock ceiling for any single provider call (see module note).
        # Bounds transport stalls that slip past the per-read httpx/SDK timeout.
        try:
            self._llm_hard_timeout_seconds = float(
                os.getenv("LLM_CALL_HARD_TIMEOUT_SECONDS", str(_DEFAULT_LLM_HARD_TIMEOUT_SECONDS))
            )
        except (TypeError, ValueError):
            self._llm_hard_timeout_seconds = _DEFAULT_LLM_HARD_TIMEOUT_SECONDS
        if self._llm_hard_timeout_seconds <= 0:
            self._llm_hard_timeout_seconds = _DEFAULT_LLM_HARD_TIMEOUT_SECONDS
        # Bound simultaneous in-flight LLM calls so a scan's concurrent fan-out
        # (asyncio.gather of analysts + debate researchers across symbols) cannot
        # saturate the event loop and starve /health + the scheduler under a
        # network flap. Tunable via LLM_MAX_CONCURRENCY.
        try:
            _max_concurrency = int(
                os.getenv("LLM_MAX_CONCURRENCY", str(_DEFAULT_LLM_MAX_CONCURRENCY))
            )
        except (TypeError, ValueError):
            _max_concurrency = _DEFAULT_LLM_MAX_CONCURRENCY
        if _max_concurrency <= 0:
            _max_concurrency = _DEFAULT_LLM_MAX_CONCURRENCY
        self._llm_max_concurrency = _max_concurrency
        self._llm_call_semaphore = asyncio.Semaphore(_max_concurrency)
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "hermes3:latest")
        self.ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        self.ollama_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
        # Per-agent model overrides. Format: "agent_a=model_x,agent_b=model_y".
        # Use '=' for agent→model so Ollama tag colons (e.g. "llama3.2:3b") survive parsing.
        # Empty / unparseable entries fall back to OLLAMA_MODEL.
        self.ollama_model_per_agent: dict[str, str] = {}
        per_agent_raw = os.getenv("OLLAMA_MODEL_PER_AGENT", "").strip()
        if per_agent_raw:
            for spec in per_agent_raw.split(","):
                spec = spec.strip()
                if not spec or "=" not in spec:
                    continue
                agent, model_name = spec.split("=", 1)
                agent = agent.strip()
                model_name = model_name.strip()
                if agent and model_name:
                    self.ollama_model_per_agent[agent] = model_name
        # Per-agent context window overrides. Format: "agent_a=2048,agent_b=3072".
        # Falls back to OLLAMA_NUM_CTX for agents not listed. Reduces KV-cache
        # allocation on CPU for lightweight agents (e.g. social_analyst, news_analyst).
        self.ollama_num_ctx_per_agent: dict[str, int] = {}
        per_ctx_raw = os.getenv("OLLAMA_NUM_CTX_PER_AGENT", "").strip()
        if per_ctx_raw:
            for spec in per_ctx_raw.split(","):
                spec = spec.strip()
                if not spec or "=" not in spec:
                    continue
                agent, ctx_str = spec.split("=", 1)
                agent = agent.strip()
                ctx_str = ctx_str.strip()
                try:
                    if agent and ctx_str:
                        self.ollama_num_ctx_per_agent[agent] = int(ctx_str)
                except ValueError:
                    logger.warning(
                        f"OLLAMA_NUM_CTX_PER_AGENT: invalid value '{ctx_str}' for agent '{agent}' — skipped"
                    )
        # Phase 3.5 (2026-06-03): Claude-on-Vertex transport (default OFF).
        # When JARVIS_CLAUDE_USE_VERTEX is truthy and provider != ollama, route
        # Claude through Vertex AI (AsyncAnthropicVertex) instead of the Anthropic
        # direct API — billing consolidation + a Vertex failover leg. Vertex model
        # IDs use the publisher @version form; JARVIS_VERTEX_MODEL_MAP translates
        # direct names -> Vertex IDs at the single wire point (_call_with_retry).
        # Unmapped names pass through unchanged. Absent flag => byte-identical to
        # the direct path.
        self.use_vertex = self.provider != "ollama" and os.getenv(
            "JARVIS_CLAUDE_USE_VERTEX", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.vertex_project = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID", "").strip()
        self.vertex_region = os.getenv("ANTHROPIC_VERTEX_REGION", "").strip()
        self.vertex_model_map: dict[str, str] = {}
        _vmap_raw = os.getenv("JARVIS_VERTEX_MODEL_MAP", "").strip()
        if _vmap_raw:
            for spec in _vmap_raw.split(","):
                spec = spec.strip()
                if not spec or "=" not in spec:
                    continue
                direct, vertex_id = spec.split("=", 1)
                direct, vertex_id = direct.strip(), vertex_id.strip()
                if direct and vertex_id:
                    self.vertex_model_map[direct] = vertex_id

        if self.provider == "ollama":
            self.client = None
        elif self.use_vertex:
            self.client = self._build_vertex_client()
            logger.info(
                "🔵 Claude-on-Vertex transport active "
                f"(project={self.vertex_project or 'ADC-default'}, "
                f"region={self.vertex_region or 'ADC-default'})"
            )
        else:
            self.client = anthropic.AsyncAnthropic(api_key=api_key)

        # Phase 3.5 failover (default OFF): on Anthropic credit-exhaustion, retry
        # the call via Claude-on-Vertex BEFORE the Gemini fallback. Same model
        # family = best output continuity, and GCP-billed so unaffected by the
        # Anthropic credit outage. Only meaningful when the primary is direct
        # Anthropic (not ollama, not already Vertex-primary). Silently disables
        # if the Vertex client can't be built (e.g. ADC not configured yet), so
        # it is safe to leave wired; flipping JARVIS_LLM_VERTEX_FAILOVER arms it.
        self.vertex_failover_enabled = (
            self.provider != "ollama"
            and not self.use_vertex
            and os.getenv("JARVIS_LLM_VERTEX_FAILOVER", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.vertex_failover_count = 0
        self._failover_vertex_client = None
        if self.vertex_failover_enabled:
            try:
                self._failover_vertex_client = self._build_vertex_client()
                logger.info(
                    "🔵 Claude-on-Vertex credit-exhaustion failover armed "
                    f"(project={self.vertex_project or 'ADC-default'}, "
                    f"region={self.vertex_region or 'ADC-default'})"
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("vertex failover disabled — could not build Vertex client: %s", exc)
                self.vertex_failover_enabled = False
        self.cost_tracker = CostTracker(db_path=db_path)
        self.default_model = self.ollama_model if self.provider == "ollama" else "claude-sonnet-4-6"
        self.fast_model = (
            self.ollama_model if self.provider == "ollama" else "claude-haiku-4-5-20251001"
        )
        self.compaction_count = 0

        # Phase 3 (2026-05-20): Google/Gemini provider — transparent fallback
        # when the Anthropic primary path hits credit-exhaustion or 5xx errors.
        # Reads GOOGLE_API_KEY or GEMINI_API_KEY from env. Absent key silently
        # disables the fallback (no behavior change from pre-Phase-3). Uses
        # Gemini's OpenAI-compatible endpoint so we reuse the messages/choices
        # shape without adding google-generativeai as a runtime dep.
        self.google_api_key = (
            os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        ).strip()
        self.google_endpoint = os.getenv(
            "GOOGLE_OPENAI_ENDPOINT",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        ).strip()
        self.google_fallback_enabled = self.google_api_key != "" and os.getenv(
            "JARVIS_LLM_GOOGLE_FALLBACK", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self.google_fallback_count = 0  # incremented on each successful fallback

        # 2026-07-17: decision-tier primary override. Anthropic pricing is no
        # longer viable for always-on decision traffic (Sonnet $3/$15 per MTok
        # vs gemini-2.5-pro $1.25/$10), and the 2026-06-22 credit outage already
        # proved pro serves the decision tier well — it just did so via the
        # credit-exhaustion failover, which pays a doomed Anthropic call on every
        # decision first. Naming a Gemini model here makes it the PRIMARY for the
        # decision tier (trader, risk_manager, fund_manager, debate/researchers),
        # with Anthropic/OpenAI still behind it as fallbacks.
        #
        # Unset (default) => byte-identical to the previous Anthropic-primary
        # behavior. Only Gemini values take effect today; a non-Gemini value is
        # inert (logged at startup) rather than silently mis-routing, which is
        # the trap JARVIS_LLM_PROVIDER=openai fell into — that var only ever
        # distinguished ollama from everything-else, so it looked configured
        # while changing nothing.
        self.decision_primary_model = os.getenv("JARVIS_DECISION_PRIMARY", "").strip()
        if self.decision_primary_model and not self.decision_primary_model.startswith(
            ("gemini", "kimi")
        ):
            logger.warning(
                "JARVIS_DECISION_PRIMARY='%s' is not a supported decision primary "
                "(only gemini-* or kimi-* models route as primary today) — ignoring; "
                "decision tier stays on %s.",
                self.decision_primary_model,
                "ollama" if self.provider == "ollama" else "anthropic",
            )

        # Phase 3.4 (2026-05-22): DeepSeek-R1 support for reasoning chains.
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.deepseek_endpoint = os.getenv(
            "DEEPSEEK_ENDPOINT", "https://api.deepseek.com/v1/chat/completions"
        ).strip()

        # Phase 3.6 (2026-06-06): OpenAI last-resort fallback — fires when both
        # Anthropic and Gemini fail (credit-exhaustion or 5xx). Uses the standard
        # OpenAI chat completions endpoint. Silently disabled when OPENAI_API_KEY
        # is absent. Override endpoint via OPENAI_ENDPOINT for Azure OpenAI.
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_endpoint = os.getenv(
            "OPENAI_ENDPOINT",
            "https://api.openai.com/v1/chat/completions",
        ).strip()
        self.openai_fallback_enabled = self.openai_api_key != "" and os.getenv(
            "JARVIS_LLM_OPENAI_FALLBACK", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self.openai_fallback_count = 0

        # 2026-07-18: Kimi K3 (Moonshot AI) as an alternate decision-tier
        # PRIMARY, selected the same way as the Gemini primary above --
        # JARVIS_DECISION_PRIMARY names "kimi-k3" instead of a gemini-* model.
        # Unlike Gemini, Kimi is not wired into the Anthropic credit-exhaustion
        # cascade (GOOGLE_FAILOVER_MAP/OPENAI_FAILOVER_MAP) -- it only serves
        # when explicitly chosen as the decision primary, with Anthropic/OpenAI
        # still behind it as fallbacks on failure. API-only today (Moonshot's
        # open weights release 2026-07-27); no local/self-hosted path yet.
        self.kimi_api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
        self.kimi_endpoint = os.getenv(
            "MOONSHOT_ENDPOINT", "https://api.moonshot.ai/v1/chat/completions"
        ).strip()

        google_status = (
            "enabled"
            if self.google_fallback_enabled
            else ("disabled (no key)" if not self.google_api_key else "disabled (env flag)")
        )
        openai_status = (
            "enabled"
            if self.openai_fallback_enabled
            else ("disabled (no key)" if not self.openai_api_key else "disabled (env flag)")
        )
        deepseek_status = "enabled" if self.deepseek_api_key else "disabled (no key)"
        kimi_status = "enabled" if self.kimi_api_key else "disabled (no key)"
        decision_primary_usable = (
            self.decision_primary_model.startswith("gemini") and self.google_fallback_enabled
        ) or (self.decision_primary_model.startswith("kimi") and bool(self.kimi_api_key))
        decision_primary_status = (
            self.decision_primary_model if decision_primary_usable else "anthropic (default)"
        )
        logger.info(
            f"✅ JarvisLLMClient initialized with cost tracking at {db_path} "
            f"(provider={self.provider}, decision_primary={decision_primary_status}, "
            f"google_fallback={google_status}, "
            f"openai_fallback={openai_status}, deepseek={deepseek_status}, kimi={kimi_status})"
        )

        # Snapshot the wired legs for /health provider-redundancy reporting.
        # Order matters: primary first, then the credit-exhaustion failover order
        # (vertex -> gemini -> openai), so get_llm_provider_summary can tell
        # whether the active leg has another behind it.
        # A configured Gemini decision primary IS the primary for trade
        # decisions — report it as such so /health's single_leg_warning and the
        # dashboard's provider badge describe the path decisions actually take,
        # not the historical Anthropic-first one.
        gemini_decision_primary_active = (
            self.provider != "ollama"
            and self.google_fallback_enabled
            and self.decision_primary_model.startswith("gemini")
        )
        kimi_decision_primary_active = (
            self.provider != "ollama"
            and bool(self.kimi_api_key)
            and self.decision_primary_model.startswith("kimi")
        )
        decision_primary_active = gemini_decision_primary_active or kimi_decision_primary_active
        base_provider = "vertex" if self.use_vertex else self.provider
        primary_provider = (
            "kimi"
            if kimi_decision_primary_active
            else "gemini"
            if gemini_decision_primary_active
            else base_provider
        )
        configured = [primary_provider]
        if decision_primary_active and base_provider != primary_provider:
            # The former primary (anthropic/vertex) stays wired BEHIND the Gemini
            # primary as a real fallback leg — keep it listed so
            # single_leg_warning doesn't fire on a fully-redundant chain.
            configured.append(base_provider)
        if self.vertex_failover_enabled:
            configured.append("vertex")
        if self.google_fallback_enabled and primary_provider != "gemini":
            configured.append("gemini")
        if self.openai_fallback_enabled:
            configured.append("openai")
        _LLM_PATH_STATE["primary_provider"] = primary_provider
        _LLM_PATH_STATE["providers_configured"] = configured

    async def _bounded(self, coro, *, what: str, model: str, agent_name: str):
        """Run a provider coroutine under a hard wall-clock ceiling.

        ``asyncio.wait_for`` cancels the coroutine — closing the underlying HTTP
        request — if it exceeds ``LLM_CALL_HARD_TIMEOUT_SECONDS``. This is the
        backstop that the 2026-06-04 13h freeze needed: it does not depend on the
        provider's own timeout firing. Raises ``LLMHardTimeoutError`` on breach so
        the caller's existing fallback / failure handling treats it like any other
        provider error.

        Defensive getattr: some tests build the client via ``__new__`` without
        running ``__init__``, so fall back to the module default ceiling.
        """
        ceiling = getattr(self, "_llm_hard_timeout_seconds", _DEFAULT_LLM_HARD_TIMEOUT_SECONDS)
        # Gate on the concurrency semaphore so at most _llm_max_concurrency provider
        # calls run at once (defensive getattr: some tests build via __new__ without
        # __init__). The coroutine is not awaited until a slot is free, and the hard
        # ceiling clock starts only once the call begins -- queue wait does not count
        # against it.
        semaphore = getattr(self, "_llm_call_semaphore", None)
        try:
            if semaphore is None:
                return await asyncio.wait_for(coro, timeout=ceiling)
            async with semaphore:
                return await asyncio.wait_for(coro, timeout=ceiling)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            logger.error(
                "[%s] %s for %s exceeded hard ceiling %.0fs -- cancelled to protect "
                "the event loop (no single LLM call may freeze the pipeline)",
                model,
                what,
                agent_name,
                ceiling,
            )
            raise LLMHardTimeoutError(
                f"{what} for {agent_name} exceeded {ceiling:.0f}s hard ceiling"
            ) from exc

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
        served_by: str | None = None,
    ) -> LLMCallResult:
        """Handle successful API call."""
        # Record which leg actually served so /health can report the active
        # provider. Most paths self-identify by model name; the Vertex failover
        # passes a claude-* model so it sets served_by="vertex" explicitly.
        _LLM_PATH_STATE["active_provider"] = served_by or _provider_from_model(current_model)
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
                proxy.set_cached(
                    compressed_key, result_obj, model=str(current_model), salt=cache_salt
                )
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

    def _resolve_google_primary(self, agent_name: str) -> Optional[str]:
        """Which Gemini model (if any) should serve this agent as PRIMARY.

        Two independent routes, cheapest-intent first:

        * Enrichment/classification agents (GEMINI_PRIMARY_AGENTS) are always
          pinned to flash — they are not trade decisions and have been Gemini-
          primary since 2026-06-04.
        * Everything else (the decision tier: trader, risk_manager,
          fund_manager, debate/researchers) routes to JARVIS_DECISION_PRIMARY
          when that names a Gemini model. Unset => None => unchanged
          Anthropic-primary behavior.

        Returns None when Gemini should not serve as primary for this agent.
        """
        if agent_name in self.GEMINI_PRIMARY_AGENTS:
            return "gemini-2.5-flash"
        if self.decision_primary_model.startswith("gemini"):
            return self.decision_primary_model
        return None

    def _resolve_kimi_primary(self, agent_name: str) -> Optional[str]:
        """Which Kimi model (if any) should serve this agent as PRIMARY.

        Mirrors _resolve_google_primary for the Kimi/Moonshot provider family.
        Enrichment/classification agents (GEMINI_PRIMARY_AGENTS) never route
        here even if JARVIS_DECISION_PRIMARY names a Kimi model -- they stay
        pinned to gemini-2.5-flash, same precedent as the Gemini resolver.
        """
        if agent_name in self.GEMINI_PRIMARY_AGENTS:
            return None
        if self.decision_primary_model.startswith("kimi"):
            return self.decision_primary_model
        return None

    def _resolve_model_for_tier(
        self, model: str, tier: Literal["fast", "default", "advisor"]
    ) -> str:
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
            elif isinstance(content, list):
                # Multi-modal content
                for part in content:
                    if isinstance(part, dict):
                        # Text part
                        if part.get("type") == "text":
                            total_chars += len(part.get("text", ""))
                        # Image part (base64)
                        elif part.get("type") == "image":
                            # Base64 is ~33% larger than raw bytes, but we just need a proxy
                            # We'll use a constant or proportional estimate
                            total_chars += len(part.get("source", {}).get("data", "")) // 10
            elif isinstance(content, dict):
                total_chars += len(str(content))
            else:
                total_chars += len(str(content))
        return max(1, total_chars // 4)

    async def _summarize_for_compaction(self, middle_messages: list[dict], agent_name: str) -> str:
        if not middle_messages:
            return "No prior context."

        middle_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in middle_messages
        )
        middle_text = middle_text[:12000]

        if not middle_text.strip():
            return "Prior context omitted."

        if not _CONTEXT_MGMT_AVAILABLE:
            return f"{len(middle_messages)} messages summarized for context compaction."

        try:
            summary_result = await self._bounded(
                self._call_with_retry(
                    model=self.fast_model,
                    system=(
                        "Summarize the prior conversation context for a trading agent. "
                        "Preserve the important decisions, constraints, market state, and unresolved risks. "
                        "Return plain text only in under 120 words."
                    ),
                    messages=[{"role": "user", "content": middle_text}],
                    max_tokens=220,
                    temperature=0.2,
                ),
                what="compaction summary",
                model=self.fast_model,
                agent_name=agent_name,
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
        logger.info(
            "[%s] context compaction triggered for %s (count=%d)",
            model,
            agent_name,
            self.compaction_count,
        )
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
            current_model = self.ollama_model_per_agent.get(agent_name, self.ollama_model)

        if compact:
            try:
                working_messages = await self._maybe_compact_messages(
                    system=system,
                    messages=working_messages,
                    model=current_model,
                    agent_name=agent_name,
                )
            except Exception as exc:
                logger.debug(
                    "[%s] context compaction skipped for %s: %s", current_model, agent_name, exc
                )

        # TokenProxy — compress + cache check
        proxy = None
        compressed_key = None
        cache_salt = f"{current_model}::{tier}::{agent_name}"
        if _TOKEN_PROXY_AVAILABLE and working_messages:
            try:
                proxy = get_token_proxy()
                last_msg = working_messages[-1]
                if (
                    isinstance(last_msg, dict)
                    and "content" in last_msg
                    and isinstance(last_msg["content"], str)
                ):
                    compressed, cached = proxy.optimize(
                        last_msg["content"], model=str(current_model), salt=cache_salt
                    )
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

        # Proactive Gemini routing — avoids burning Anthropic credits when a
        # Gemini tier is the intended primary. Falls through to the Anthropic
        # retry loop on any Gemini failure, so this is never a single point of
        # failure.
        google_primary_model = self._resolve_google_primary(agent_name)
        if (
            self.provider != "ollama"
            and self.google_fallback_enabled
            and google_primary_model is not None
        ):
            # Enrichment/classification agents (news/technical/fundamental, etc.)
            # are pinned to the cost-efficient flash tier as their PRIMARY — they
            # are not trade decisions, and several call with a sonnet model id, so
            # routing them through GOOGLE_FAILOVER_MAP (which now sends sonnet->pro)
            # would silently 4x their always-on cost. Decision agents route here
            # only when JARVIS_DECISION_PRIMARY names a Gemini model.
            google_model = google_primary_model
            try:
                google_result = await self._bounded(
                    self._call_google(
                        system=system,
                        messages=working_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        model=google_model,
                    ),
                    what="gemini primary call",
                    model=google_model,
                    agent_name=agent_name,
                )
                self.google_fallback_count += 1
                _LLM_PATH_STATE["google_fallback_count"] = self.google_fallback_count
                return await self._handle_success(
                    google_result,
                    google_model,
                    start_time,
                    retries,
                    agent_name,
                    tier=tier,
                    proxy=proxy,
                    compressed_key=compressed_key,
                    cache_salt=cache_salt,
                )
            except Exception as gex:
                logger.warning(
                    "[%s] Gemini primary failed for %s — falling through to Anthropic: %s",
                    google_model,
                    agent_name,
                    gex,
                )

        # Proactive Kimi K3 routing — mirrors the Gemini primary block above
        # for the alternate decision-tier provider. Mutually exclusive with it
        # in practice since JARVIS_DECISION_PRIMARY is a single value that can
        # only start with "gemini" or "kimi", never both. Falls through to the
        # Anthropic retry loop on any failure, same as the Gemini path.
        kimi_primary_model = self._resolve_kimi_primary(agent_name)
        if self.provider != "ollama" and self.kimi_api_key and kimi_primary_model is not None:
            try:
                kimi_result = await self._bounded(
                    self._call_kimi(
                        system=system,
                        messages=working_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        model=kimi_primary_model,
                    ),
                    what="kimi primary call",
                    model=kimi_primary_model,
                    agent_name=agent_name,
                )
                return await self._handle_success(
                    kimi_result,
                    kimi_primary_model,
                    start_time,
                    retries,
                    agent_name,
                    tier=tier,
                    proxy=proxy,
                    compressed_key=compressed_key,
                    cache_salt=cache_salt,
                    served_by="kimi",
                )
            except Exception as kex:
                logger.warning(
                    "[%s] Kimi primary failed for %s — falling through to Anthropic: %s",
                    kimi_primary_model,
                    agent_name,
                    kex,
                )

        # Retry loop with exponential backoff
        while True:
            try:
                result = await self._bounded(
                    self._call_with_retry(
                        model=current_model,
                        system=system,
                        messages=working_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        agent_name=agent_name,
                    ),
                    what="primary provider call",
                    model=current_model,
                    agent_name=agent_name,
                )
                return await self._handle_success(
                    result,
                    current_model,
                    start_time,
                    retries,
                    agent_name,
                    tier=tier,
                    proxy=proxy,
                    compressed_key=compressed_key,
                    cache_salt=cache_salt,
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
                    # Phase 3.5: Claude-on-Vertex failover FIRST — same model
                    # family (best output continuity) and GCP-billed, so it is
                    # unaffected by the Anthropic credit outage. Falls through to
                    # the Gemini fallback below if Vertex is disabled or also fails.
                    if self.vertex_failover_enabled and self._failover_vertex_client is not None:
                        logger.warning(
                            f"[{current_model}] credit-exhaustion for {agent_name} -- "
                            f"attempting Claude-on-Vertex failover"
                        )
                        start_time = time.time()
                        try:
                            vertex_result = await self._bounded(
                                self._call_vertex_failover(
                                    current_model,
                                    system,
                                    working_messages,
                                    max_tokens,
                                    temperature,
                                ),
                                what="vertex failover call",
                                model=current_model,
                                agent_name=agent_name,
                            )
                            self.vertex_failover_count += 1
                            _LLM_PATH_STATE["vertex_failover_count"] = self.vertex_failover_count
                            _LLM_PATH_STATE["healthy"] = True
                            _LLM_PATH_STATE["last_failure_ts"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            _LLM_PATH_STATE["last_failure_reason"] = (
                                f"anthropic credit-exhaustion -> vertex failover ok "
                                f"(count: {self.vertex_failover_count})"
                            )
                            _LLM_PATH_STATE["last_failure_agent"] = agent_name
                            return await self._handle_success(
                                vertex_result,
                                current_model,
                                start_time,
                                retries,
                                agent_name,
                                tier=tier,
                                proxy=proxy,
                                compressed_key=compressed_key,
                                cache_salt=cache_salt,
                                served_by="vertex",
                            )
                        except Exception as vex:
                            logger.warning(
                                f"[{current_model}] Vertex failover failed for "
                                f"{agent_name} -- trying Gemini next: {vex}"
                            )
                            # fall through to the Gemini fallback below

                    # Phase 3: Anthropic credits exhausted — try transparent
                    # Gemini fallback before declaring the call failed. The
                    # fallback preserves quality tier (Opus/Sonnet -> 2.5-flash,
                    # Haiku -> 2.0-flash) and returns a normal LLMCallResult so
                    # call sites are provider-agnostic.
                    if self.google_fallback_enabled:
                        google_model = self.GOOGLE_FAILOVER_MAP.get(
                            current_model, "gemini-2.5-flash"
                        )
                        logger.warning(
                            f"[{current_model}] credit-exhaustion for {agent_name} -- "
                            f"attempting Gemini fallback ({google_model})"
                        )
                        start_time = time.time()
                        try:
                            google_result = await self._bounded(
                                self._call_google(
                                    system=system,
                                    messages=working_messages,
                                    max_tokens=max_tokens,
                                    temperature=temperature,
                                    model=google_model,
                                ),
                                what="gemini fallback call",
                                model=google_model,
                                agent_name=agent_name,
                            )
                            self.google_fallback_count += 1
                            _LLM_PATH_STATE["google_fallback_count"] = self.google_fallback_count
                            # Successful failover -- mark path healthy with note
                            _LLM_PATH_STATE["healthy"] = True
                            _LLM_PATH_STATE["last_failure_ts"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            _LLM_PATH_STATE["last_failure_reason"] = (
                                f"anthropic credit-exhaustion -> gemini fallback ok "
                                f"(count: {self.google_fallback_count})"
                            )
                            _LLM_PATH_STATE["last_failure_agent"] = agent_name
                            return await self._handle_success(
                                google_result,
                                google_model,
                                start_time,
                                retries,
                                agent_name,
                                tier=tier,
                                proxy=proxy,
                                compressed_key=compressed_key,
                                cache_salt=cache_salt,
                            )
                        except Exception as gex:
                            logger.error(
                                f"[{google_model}] Gemini fallback also failed for "
                                f"{agent_name}: {type(gex).__name__}: {gex}"
                            )
                            # fall through to OpenAI fallback below

                    # Phase 3.6: both Anthropic and Gemini failed (or Gemini is
                    # disabled) — last-resort OpenAI before declaring the path
                    # unhealthy. Opus/Sonnet → gpt-4o, Haiku → gpt-4o-mini.
                    if self.openai_fallback_enabled:
                        openai_model = self.OPENAI_FAILOVER_MAP.get(current_model, "gpt-4o-mini")
                        logger.warning(
                            f"[{current_model}] Anthropic+Gemini both failed for {agent_name} -- "
                            f"attempting OpenAI fallback ({openai_model})"
                        )
                        start_time = time.time()
                        try:
                            openai_result = await self._bounded(
                                self._call_openai(
                                    system=system,
                                    messages=working_messages,
                                    max_tokens=max_tokens,
                                    temperature=temperature,
                                    model=openai_model,
                                ),
                                what="openai fallback call",
                                model=openai_model,
                                agent_name=agent_name,
                            )
                            self.openai_fallback_count += 1
                            _LLM_PATH_STATE["healthy"] = True
                            _LLM_PATH_STATE["last_failure_ts"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            _LLM_PATH_STATE["last_failure_reason"] = (
                                f"anthropic+gemini failed -> openai fallback ok "
                                f"(count: {self.openai_fallback_count})"
                            )
                            _LLM_PATH_STATE["last_failure_agent"] = agent_name
                            return await self._handle_success(
                                openai_result,
                                openai_model,
                                start_time,
                                retries,
                                agent_name,
                                tier=tier,
                                proxy=proxy,
                                compressed_key=compressed_key,
                                cache_salt=cache_salt,
                            )
                        except Exception as oex:
                            logger.error(
                                f"[{openai_model}] OpenAI fallback also failed for "
                                f"{agent_name}: {type(oex).__name__}: {oex}"
                            )
                            # fall through to unhealthy-path handling below

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
        model: str | None = None,
        agent_name: str = "unknown",
    ):
        prompt = self._messages_to_ollama_prompt(system, messages)
        num_ctx = self.ollama_num_ctx_per_agent.get(agent_name, self.ollama_num_ctx)
        payload = {
            "model": model or self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.ollama_keep_alive,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": min(max_tokens, self.ollama_num_predict),
                "temperature": temperature,
            },
        }
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
        async with httpx.AsyncClient(timeout=_granular_httpx_timeout(timeout)) as client:
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

    async def _call_google(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        model: str,
    ):
        """Single call to Gemini via OpenAI-compatible endpoint.

        Returns a SimpleNamespace shaped like an Anthropic response so the
        rest of the success/cost-tracking path is provider-agnostic. Raises
        httpx exceptions on transport failure; the caller's retry/fallback
        logic decides what to do with them.

        Notes:
          - "system" is collapsed into a leading {"role":"system"} message.
          - tool/cache/extra fields are not forwarded; this is the minimum
            shape needed by the trading agents that go through call().
        """
        if not self.google_api_key:
            raise RuntimeError("google_api_key not configured")

        openai_messages: list[dict] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            # Gemini OpenAI endpoint accepts the same role names as OpenAI.
            openai_messages.append({"role": role, "content": content})

        # gemini-2.5* are *thinking* models: over the OpenAI-compat endpoint the
        # max_tokens budget is shared between internal reasoning and the visible
        # answer, so a small budget (the analysts pass 256-1024) gets consumed by
        # thinking and the JSON response truncates mid-object (observed: cut at
        # '"confidence":'). Floor the output budget for thinking models so content
        # survives the reasoning spend. Non-thinking models (gemini-2.0-flash) keep
        # the caller's value. Tunable via GEMINI_MIN_OUTPUT_TOKENS; only ever raises.
        effective_max_tokens = max_tokens
        is_pro = model.startswith("gemini-2.5") and "pro" in model
        if model.startswith("gemini-2.5"):
            # pro can never disable thinking (see reasoning_effort note below), so
            # the same 2048 floor that's enough for flash (which runs effort=none)
            # leaves pro's visible answer starved on large debate prompts. Live
            # 2026-07-15: bull/bear_researcher calls with in:~5600 (full debate
            # context) returned out:1/26/46/47/55/58 — thinking consumed nearly
            # the whole 2048 budget, and the trader's JSON truncated mid-object
            # ('...target_1' with no closing brace) at out:281. Give pro a much
            # higher floor since raising max_tokens only raises the ceiling, not
            # a mandatory spend. Tunable via GEMINI_PRO_MIN_OUTPUT_TOKENS.
            default_floor = "8192" if is_pro else "2048"
            env_var = "GEMINI_PRO_MIN_OUTPUT_TOKENS" if is_pro else "GEMINI_MIN_OUTPUT_TOKENS"
            try:
                floor = int(os.getenv(env_var, default_floor))
            except (TypeError, ValueError):
                floor = int(default_floor)
            effective_max_tokens = max(max_tokens, floor)

        payload: dict = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": effective_max_tokens,
            "temperature": temperature,
        }
        # The token floor alone is not enough under heavy reasoning load: a real
        # analyst prompt (in:~1200, many output fields) makes gemini-2.5-flash
        # spend ~1900+ of a 2048 budget on internal thinking, leaving ~80 tokens
        # for the visible JSON, which truncates mid-object (live 2026-06-06:
        # out:80, cut at '"volat'). Disable thinking on 2.5 models via the
        # OpenAI-compat reasoning_effort knob so the whole budget goes to the
        # answer. Tunable/escape-hatch via GEMINI_REASONING_EFFORT (none|low|
        # medium|high); "none" disables thinking. Non-2.5 models are unaffected.
        #
        # EXCEPT gemini-2.5-pro: Google rejects reasoning_effort="none" (budget 0)
        # on pro with HTTP 400 "Budget 0 is invalid. This model only works in
        # thinking mode." (verified live 2026-07-06 — a Google-side change since
        # the 06-22 "pro verified 200 OK" note). pro is the decision-tier
        # credit-exhaustion failover (GOOGLE_FAILOVER_MAP: opus/sonnet -> pro), so
        # sending "none" would 400 every decision-tier failover. Pro keeps thinking
        # on (knob omitted) unless GEMINI_REASONING_EFFORT is explicitly set to a
        # non-"none" value; the token floor above lets the answer survive the spend.
        if model.startswith("gemini-2.5"):
            default_effort = "" if is_pro else "none"
            effort = os.getenv("GEMINI_REASONING_EFFORT", default_effort).strip().lower()
            if is_pro and effort in ("", "none"):
                # pro cannot disable thinking; omit the knob (thinking stays on).
                effort = ""
            if effort:
                payload["reasoning_effort"] = effort
        timeout = float(os.getenv("GOOGLE_TIMEOUT_SECONDS", "60"))
        headers = {
            "Authorization": f"Bearer {self.google_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_granular_httpx_timeout(timeout)) as client:
            response = await client.post(self.google_endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                # The HTTPStatusError string form omits the response body, so the
                # caller's "%s"/"{gex}" logging only ever shows "404 Not Found" —
                # which can't distinguish a revoked/invalid API key from an
                # unknown model id. Surface the body (truncated) at the source so
                # the dominant Gemini-fallback failure is diagnosable in one look.
                try:
                    body = response.text[:500]
                except Exception:  # pragma: no cover - defensive
                    body = "<unreadable>"
                logger.warning(
                    "[%s] Gemini endpoint returned HTTP %d: %s",
                    model,
                    response.status_code,
                    body,
                )
            response.raise_for_status()
            data = response.json()

        # OpenAI-shape response: {"choices":[{"message":{"content":...}}],"usage":{...}}
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Gemini response missing choices: {str(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or self._estimate_tokens(system, messages))
        output_tokens = int(usage.get("completion_tokens") or max(1, len(text) // 4))
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text)],
        )

    async def _call_openai(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        model: str,
    ):
        """Single call to OpenAI via the chat completions endpoint.

        Returns a SimpleNamespace shaped like an Anthropic response so the
        rest of the success/cost-tracking path is provider-agnostic. Modeled
        on _call_google() — both use the OpenAI messages/choices shape.
        Supports Azure OpenAI via OPENAI_ENDPOINT override.
        """
        if not self.openai_api_key:
            raise RuntimeError("openai_api_key not configured")

        openai_messages: list[dict] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            openai_messages.append({"role": role, "content": content})

        payload: dict = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_granular_httpx_timeout(timeout)) as http_client:
            response = await http_client.post(self.openai_endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    body = response.text[:500]
                except Exception:  # pragma: no cover - defensive
                    body = "<unreadable>"
                logger.warning(
                    "[%s] OpenAI endpoint returned HTTP %d: %s",
                    model,
                    response.status_code,
                    body,
                )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenAI response missing choices: {str(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or self._estimate_tokens(system, messages))
        output_tokens = int(usage.get("completion_tokens") or max(1, len(text) // 4))
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text)],
        )

    async def _call_deepseek(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        model: str,
    ):
        """Single call to DeepSeek via OpenAI-compatible endpoint.

        Returns a SimpleNamespace shaped like an Anthropic response.
        Extracts reasoning_content if available (specific to DeepSeek-R1).
        """
        if not self.deepseek_api_key:
            raise RuntimeError("deepseek_api_key not configured")

        openai_messages: list[dict] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            # DeepSeek OpenAI endpoint accepts the same role names as OpenAI.
            openai_messages.append({"role": role, "content": content})

        payload: dict = {
            "model": model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "180"))
        async with httpx.AsyncClient(timeout=_granular_httpx_timeout(timeout)) as client:
            response = await client.post(self.deepseek_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # OpenAI-shape response: {"choices":[{"message":{"content":...}}],"usage":{...}}
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"DeepSeek response missing choices: {str(data)[:300]}")

        choice = choices[0].get("message") or {}
        text = choice.get("content", "")
        # DeepSeek specific reasoning field
        reasoning = choice.get("reasoning_content", "")

        # Wrap reasoning in <think> tags if present to match the expected skill pattern
        if reasoning:
            text = f"<think>\n{reasoning}\n</think>\n\n{text}"

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or self._estimate_tokens(system, messages))
        output_tokens = int(usage.get("completion_tokens") or max(1, len(text) // 4))

        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text)],
        )

    async def _call_kimi(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        model: str,
    ):
        """Single call to Kimi K3 (Moonshot AI) via its OpenAI-compatible endpoint.

        Returns a SimpleNamespace shaped like an Anthropic response, same
        convention as _call_google/_call_openai/_call_deepseek. Per the
        platform.kimi.ai quickstart, K3 always reasons server-side and fixes
        temperature/top_p/penalties -- those must be OMITTED from the request,
        not just left at a default, and the output budget field is
        `max_completion_tokens` (not `max_tokens`). `temperature` (this
        method's own param) is accepted only for call-site symmetry with the
        other _call_* methods and is intentionally unused.
        """
        if not self.kimi_api_key:
            raise RuntimeError("kimi_api_key not configured")

        openai_messages: list[dict] = []
        if system:
            openai_messages.append({"role": "system", "content": system})
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            openai_messages.append({"role": role, "content": content})

        # K3 always runs max thinking effort (no way to disable it -- see the
        # reasoning_effort note below) and the completion budget is shared
        # between internal reasoning and the visible answer, same failure
        # class as gemini-2.5-pro above. Shadow-tested 2026-07-20 against real
        # Trader/BullResearcher prompts at the production budget (1200): BOTH
        # calls truncated mid-JSON (Trader cut mid-number, BullResearcher cut
        # mid-word). Re-run at 6000 produced complete, valid JSON using only
        # 603/1708 tokens -- so the failure is pure budget starvation, not a
        # prompt or model-quality problem. Floor comfortably above the highest
        # observed real need. Tunable via KIMI_MIN_OUTPUT_TOKENS; only ever raises.
        try:
            floor = int(os.getenv("KIMI_MIN_OUTPUT_TOKENS", "4096"))
        except (TypeError, ValueError):
            floor = 4096
        effective_max_tokens = max(max_tokens, floor)

        payload: dict = {
            "model": model,
            "messages": openai_messages,
            "max_completion_tokens": effective_max_tokens,
        }
        # K3 supports only reasoning_effort="max" today (its own default) --
        # omit the field entirely unless explicitly overridden, rather than
        # risk sending an unsupported value as other levels roll out.
        effort = os.getenv("KIMI_REASONING_EFFORT", "").strip().lower()
        if effort:
            payload["reasoning_effort"] = effort

        # K3 always runs at max thinking effort, which is noticeably slower
        # than a typical chat completion even for trivial prompts (observed
        # 2026-07-18: a one-sentence request took well over 60s) -- default
        # timeout is generous accordingly.
        timeout = float(os.getenv("KIMI_TIMEOUT_SECONDS", "180"))
        headers = {
            "Authorization": f"Bearer {self.kimi_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=_granular_httpx_timeout(timeout)) as http_client:
            response = await http_client.post(self.kimi_endpoint, json=payload, headers=headers)
            if response.status_code >= 400:
                try:
                    body = response.text[:500]
                except Exception:  # pragma: no cover - defensive
                    body = "<unreadable>"
                logger.warning(
                    "[%s] Kimi endpoint returned HTTP %d: %s",
                    model,
                    response.status_code,
                    body,
                )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Kimi response missing choices: {str(data)[:300]}")
        text = (choices[0].get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or self._estimate_tokens(system, messages))
        output_tokens = int(usage.get("completion_tokens") or max(1, len(text) // 4))
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
        agent_name: str = "unknown",
    ):
        """
        Low-level async call to the configured LLM provider.
        Retries are handled at the call() level.
        """
        if self.provider == "ollama":
            return await self._call_ollama(
                system, messages, max_tokens, temperature, model=model, agent_name=agent_name
            )

        # DeepSeek-R1 (Phase 3.4) — primary reasoning provider
        if model == "deepseek-reasoner":
            return await self._call_deepseek(
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
            )

        # Vertex uses publisher @version model IDs; translate at the wire only.
        # Cost tracking, health, and logging keep the direct name (current_model).
        # Defensive getattr: low-level callers (and some tests) construct the
        # client via __new__ without running __init__, so use_vertex /
        # vertex_model_map may be unset — default to the direct (non-Vertex) path.
        call_model = (
            getattr(self, "vertex_model_map", {}).get(model, model)
            if getattr(self, "use_vertex", False)
            else model
        )
        kwargs = {
            "model": call_model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if not _temperature_deprecated(model):
            kwargs["temperature"] = temperature
        try:
            return await self.client.messages.create(**kwargs)
        except APIStatusError as e:
            body = getattr(e, "body", None)
            if _is_credit_exhaustion(str(body or e)):
                # Re-raise as plain Exception so call()'s except Exception block
                # triggers the Vertex → Gemini → OpenAI fallback chain. Leaving
                # it as APIStatusError would land in the retry handler, burning
                # 6 round-trips (3 retries + tier downgrade) on a permanent error.
                raise Exception(str(body or e)) from e
            raise

    def _build_vertex_client(self):
        """Construct an AsyncAnthropicVertex client from the configured project/
        region (ADC auth; no API key). Shared by the Vertex primary transport
        and the credit-exhaustion failover leg so they stay in lock-step."""
        from anthropic import AsyncAnthropicVertex

        _vx_kwargs = {}
        if self.vertex_project:
            _vx_kwargs["project_id"] = self.vertex_project
        if self.vertex_region:
            _vx_kwargs["region"] = self.vertex_region
        return AsyncAnthropicVertex(**_vx_kwargs)

    async def _call_vertex_failover(
        self,
        model: str,
        system: str,
        messages: list,
        max_tokens: int,
        temperature: float,
    ):
        """One Claude-on-Vertex call used as a credit-exhaustion failover.

        Returns the native Anthropic Message shape so the success/cost path stays
        provider-agnostic — cost is keyed on the original alias (``model``) by the
        caller. Translates the alias to the Vertex publisher @version id via the
        same ``vertex_model_map`` the primary transport uses.
        """
        vertex_model = self.vertex_model_map.get(model, model)
        kwargs = {
            "model": vertex_model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if not _temperature_deprecated(model):
            kwargs["temperature"] = temperature
        return await self._failover_vertex_client.messages.create(**kwargs)

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
