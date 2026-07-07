# P0 Source Code — Feature Flags · Context Management · KAIROS


### `engine/flags/__init__.py`
```python
"""
JARVIS TRADER — Feature Flags
==============================
Two-layer feature flag system:
  - Layer 1 (static):  compile-time defaults from TradingConfig
  - Layer 2 (runtime): per-flag overrides persisted to SQLite

Usage
-----
    from flags import get_flags

    flags = get_flags()
    if flags.is_enabled("ENABLE_TILT_DETECTION"):
        ...

In main.py lifespan:
    from flags import FeatureFlags, set_flags_instance
    feature_flags = FeatureFlags(config=settings, db=db_manager)
    set_flags_instance(feature_flags)
"""

from .registry import FeatureFlags, get_flags, set_flags_instance

__all__ = ["FeatureFlags", "get_flags", "set_flags_instance"]

```

### `engine/flags/registry.py`
```python
"""
JARVIS TRADER — Feature Flags Registry
========================================
FeatureFlags class: two-layer flag resolution.

Layer 1 — Static defaults from TradingConfig (compile-time).
Layer 2 — Runtime overrides persisted to the SQLite feature_flags table.

Runtime overrides take precedence over config defaults.
Resetting a flag removes the override and falls back to the config default.

Thread safety: All SQLite operations are serialised via the DatabaseManager's
internal lock (connection-per-call pattern, same as all other DB operations).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.flags")

# ---------------------------------------------------------------------------
# Flag definitions — name, config-level default, metadata
# ---------------------------------------------------------------------------

FLAG_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "ENABLE_KAIROS",
        "default": False,
        "description": "Always-on proactive monitoring daemon",
        "category": "ai",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_SPECULATION",
        "default": False,
        "description": "Pre-execution speculation engine",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_TILT_DETECTION",
        "default": True,
        "description": "Tilt/revenge trading detection",
        "category": "risk",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_DREAM_CONSOLIDATION",
        "default": False,
        "description": "Nightly pattern consolidation",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_CONTEXT_COMPACTION",
        "default": True,
        "description": "4-tier LLM context management",
        "category": "ai",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_CRYPTO",
        "default": False,
        "description": "Crypto market module (Freqtrade)",
        "category": "market",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_POLYMARKET",
        "default": False,
        "description": "Polymarket module (US regulatory risk)",
        "category": "market",
        "requires_restart": True,
    },
    {
        "name": "ENABLE_RL_TRADING",
        "default": False,
        "description": "RL-based strategy execution",
        "category": "experimental",
        "requires_restart": False,
    },
    {
        "name": "ENABLE_SIGNAL_SANITIZATION",
        "default": False,
        "description": "Anti-signal-leakage log sanitization",
        "category": "security",
        "requires_restart": False,
    },
]

# Build a fast lookup dict: name -> definition
_FLAG_META: Dict[str, Dict[str, Any]] = {f["name"]: f for f in FLAG_DEFINITIONS}

# ---------------------------------------------------------------------------
# Singleton plumbing
# ---------------------------------------------------------------------------

_instance: Optional["FeatureFlags"] = None


def get_flags() -> "FeatureFlags":
    """
    Return the application-level FeatureFlags singleton.

    Raises RuntimeError if set_flags_instance() has not been called yet.
    This mirrors the pattern used by other engine singletons.
    """
    if _instance is None:
        raise RuntimeError(
            "FeatureFlags singleton is not initialised. "
            "Call set_flags_instance() in the FastAPI lifespan startup block."
        )
    return _instance


def set_flags_instance(instance: "FeatureFlags") -> None:
    """Register the application-level FeatureFlags singleton."""
    global _instance
    _instance = instance
    logger.info("FeatureFlags singleton registered (%d flags defined)", len(FLAG_DEFINITIONS))


# ---------------------------------------------------------------------------
# FeatureFlags class
# ---------------------------------------------------------------------------


class FeatureFlags:
    """
    Two-layer feature flag system.

    Layer 1 — Static defaults read from a TradingConfig instance.
    Layer 2 — Runtime overrides persisted in the SQLite ``feature_flags`` table.

    The runtime layer always takes precedence over the config layer.
    Callers should interact exclusively through is_enabled() / set_flag() /
    reset_flag() / list_flags(); direct SQL access is internal.

    Parameters
    ----------
    config:
        A TradingConfig instance (or any object with matching ENABLE_* attributes).
    db:
        A DatabaseManager instance used for persistence.
    """

    def __init__(self, config: Any, db: Any) -> None:
        self._config = config
        self._db = db
        logger.info("FeatureFlags initialised with %d flag definitions", len(FLAG_DEFINITIONS))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self, flag_name: str) -> bool:
        """
        Return True if the named flag is enabled.

        Resolution order (highest priority first):
          1. Runtime override in SQLite feature_flags table
          2. Config field on TradingConfig (e.g. settings.ENABLE_KAIROS)
          3. FLAG_DEFINITIONS default value

        Parameters
        ----------
        flag_name:
            Upper-case flag name, e.g. "ENABLE_TILT_DETECTION".

        Returns
        -------
        bool
            Resolved enabled state.
        """
        if flag_name not in _FLAG_META:
            logger.warning("is_enabled called for unknown flag %r — returning False", flag_name)
            return False

        # 1. Check runtime override in SQLite
        runtime = self._get_runtime_override(flag_name)
        if runtime is not None:
            return runtime

        # 2. Check TradingConfig field
        config_val = getattr(self._config, flag_name, None)
        if config_val is not None:
            return bool(config_val)

        # 3. Fall back to FLAG_DEFINITIONS default
        return bool(_FLAG_META[flag_name]["default"])

    def set_flag(self, flag_name: str, enabled: bool, updated_by: str = "api") -> None:
        """
        Persist a runtime override for the named flag to SQLite.

        Parameters
        ----------
        flag_name:
            Upper-case flag name.
        enabled:
            Desired enabled state.
        updated_by:
            Identifier of who/what made the change (default "api").

        Raises
        ------
        ValueError
            If flag_name is not in FLAG_DEFINITIONS.
        """
        if flag_name not in _FLAG_META:
            raise ValueError(
                f"Unknown feature flag: {flag_name!r}. " f"Valid flags: {sorted(_FLAG_META.keys())}"
            )

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        enabled_int = 1 if enabled else 0

        with self._db._lock:
            conn = self._db._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO feature_flags (name, enabled, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        enabled    = excluded.enabled,
                        updated_at = excluded.updated_at,
                        updated_by = excluded.updated_by
                    """,
                    (flag_name, enabled_int, now_utc, updated_by),
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("Feature flag %r set to %s by %s", flag_name, enabled, updated_by)

    def reset_flag(self, flag_name: str) -> None:
        """
        Remove the runtime override for the named flag.

        After reset, is_enabled() will fall back to the TradingConfig value
        or the FLAG_DEFINITIONS default.

        Parameters
        ----------
        flag_name:
            Upper-case flag name.

        Raises
        ------
        ValueError
            If flag_name is not in FLAG_DEFINITIONS.
        """
        if flag_name not in _FLAG_META:
            raise ValueError(
                f"Unknown feature flag: {flag_name!r}. " f"Valid flags: {sorted(_FLAG_META.keys())}"
            )

        with self._db._lock:
            conn = self._db._connect()
            try:
                conn.execute("DELETE FROM feature_flags WHERE name = ?", (flag_name,))
                conn.commit()
            finally:
                conn.close()

        logger.info("Feature flag %r runtime override removed (reset to config default)", flag_name)

    def list_flags(self) -> List[Dict[str, Any]]:
        """
        Return metadata for all registered flags including their current state.

        Returns
        -------
        list[dict]
            One dict per flag with keys:
              name, enabled, description, category, requires_restart, source
            where ``source`` is "runtime" if a SQLite override exists, else "config".
        """
        # Load all runtime overrides in one query
        runtime_map: Dict[str, bool] = {}
        with self._db._lock:
            conn = self._db._connect()
            try:
                rows = conn.execute("SELECT name, enabled FROM feature_flags").fetchall()
                for row in rows:
                    runtime_map[row["name"]] = bool(row["enabled"])
            finally:
                conn.close()

        result = []
        for defn in FLAG_DEFINITIONS:
            flag_name = defn["name"]
            if flag_name in runtime_map:
                enabled = runtime_map[flag_name]
                source = "runtime"
            else:
                config_val = getattr(self._config, flag_name, None)
                if config_val is not None:
                    enabled = bool(config_val)
                else:
                    enabled = bool(defn["default"])
                source = "config"

            result.append(
                {
                    "name": flag_name,
                    "enabled": enabled,
                    "description": defn["description"],
                    "category": defn["category"],
                    "requires_restart": defn["requires_restart"],
                    "source": source,
                }
            )

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_runtime_override(self, flag_name: str) -> Optional[bool]:
        """
        Fetch the runtime override for flag_name from SQLite.

        Returns None if no override exists (caller should fall through to config).
        """
        with self._db._lock:
            conn = self._db._connect()
            try:
                row = conn.execute(
                    "SELECT enabled FROM feature_flags WHERE name = ?", (flag_name,)
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            return None
        return bool(row["enabled"])

```

### `engine/routers/flags_router.py`
```python
"""
JARVIS TRADER — Feature Flags API Router
==========================================
CRUD endpoints for the two-layer feature flag system.

Endpoints
---------
  GET    /flags/           — list all flags with current state
  GET    /flags/{name}     — get a single flag by name
  PUT    /flags/{name}     — set a runtime override (enable/disable)
  DELETE /flags/{name}     — reset to config default (remove runtime override)

To register in main.py:
    from routers.flags_router import router as flags_router, set_flags as set_flags_router
    app.include_router(flags_router, prefix="/flags", tags=["feature-flags"])
    set_flags_router(feature_flags)  # call after FeatureFlags is initialised in lifespan
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flags.registry import _FLAG_META, FeatureFlags

# ---------------------------------------------------------------------------
# Module-level singleton — injected at startup via set_flags()
# ---------------------------------------------------------------------------

_flags: Optional[FeatureFlags] = None


def set_flags(flags_instance: FeatureFlags) -> None:
    """
    Inject the application-level FeatureFlags instance into this router.

    Call once from main.py after FeatureFlags has been initialised.
    """
    global _flags
    _flags = flags_instance


def _get_flags() -> FeatureFlags:
    """Return the injected FeatureFlags instance, or raise 503 if not set."""
    if _flags is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "FeatureFlags not initialised. "
                "Call set_flags_instance() in the FastAPI lifespan startup block."
            ),
        )
    return _flags


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FlagResponse(BaseModel):
    """Single feature flag with all metadata."""

    name: str
    enabled: bool
    description: str
    category: str
    requires_restart: bool
    source: str  # "config" | "runtime"


class FlagUpdateRequest(BaseModel):
    """Payload for PUT /flags/{name}."""

    enabled: bool


class FlagUpdateResponse(BaseModel):
    """Response for PUT /flags/{name}."""

    name: str
    enabled: bool
    description: str
    category: str
    requires_restart: bool
    source: str
    restart_required: bool
    message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["feature-flags"])


@router.get("/", response_model=List[FlagResponse], summary="List all feature flags")
async def list_flags() -> List[Dict[str, Any]]:
    """
    Return all registered feature flags with their current enabled state.

    Each flag shows whether it is sourced from a runtime override ("runtime")
    or from the TradingConfig / FLAG_DEFINITIONS default ("config").
    """
    flags = _get_flags()
    return flags.list_flags()


@router.get("/{name}", response_model=FlagResponse, summary="Get a single feature flag")
async def get_flag(name: str) -> Dict[str, Any]:
    """
    Return metadata and current state for a single feature flag.

    Parameters
    ----------
    name : str
        Upper-case flag name, e.g. ``ENABLE_TILT_DETECTION``.
    """
    name_upper = name.upper()
    if name_upper not in _FLAG_META:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown feature flag: {name!r}. "
            f"Use GET /flags/ to see all valid flag names.",
        )

    flags = _get_flags()
    all_flags = flags.list_flags()
    for flag in all_flags:
        if flag["name"] == name_upper:
            return flag

    # Should never reach here, but guard anyway
    raise HTTPException(status_code=500, detail="Flag found in metadata but not in list_flags()")


@router.put(
    "/{name}",
    response_model=FlagUpdateResponse,
    summary="Set a runtime override for a feature flag",
)
async def set_flag(name: str, body: FlagUpdateRequest) -> Dict[str, Any]:
    """
    Enable or disable a feature flag at runtime.

    The override is persisted to SQLite and survives engine restarts.
    If the flag ``requires_restart`` is True, a warning is included in
    the response — the change is persisted immediately but the feature
    will not activate until the engine process is restarted.

    Parameters
    ----------
    name : str
        Upper-case flag name, e.g. ``ENABLE_KAIROS``.
    body : FlagUpdateRequest
        JSON body: ``{"enabled": true}`` or ``{"enabled": false}``.
    """
    name_upper = name.upper()
    if name_upper not in _FLAG_META:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown feature flag: {name!r}. "
            f"Use GET /flags/ to see all valid flag names.",
        )

    flags = _get_flags()
    try:
        flags.set_flag(name_upper, body.enabled, updated_by="api")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    meta = _FLAG_META[name_upper]
    requires_restart = bool(meta["requires_restart"])

    if requires_restart:
        message = (
            f"Flag {name_upper!r} persisted. "
            "This flag requires_restart=True — restart the engine for the change to take effect."
        )
    else:
        message = f"Flag {name_upper!r} updated successfully. Change is active immediately."

    return {
        "name": name_upper,
        "enabled": body.enabled,
        "description": meta["description"],
        "category": meta["category"],
        "requires_restart": requires_restart,
        "source": "runtime",
        "restart_required": requires_restart,
        "message": message,
    }


@router.delete(
    "/{name}",
    response_model=FlagResponse,
    summary="Reset a feature flag to its config default",
)
async def reset_flag(name: str) -> Dict[str, Any]:
    """
    Remove any runtime override for the named flag.

    After reset, the flag resolves to the TradingConfig value or the
    FLAG_DEFINITIONS default. The response reflects the post-reset state.

    Parameters
    ----------
    name : str
        Upper-case flag name, e.g. ``ENABLE_KAIROS``.
    """
    name_upper = name.upper()
    if name_upper not in _FLAG_META:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown feature flag: {name!r}. "
            f"Use GET /flags/ to see all valid flag names.",
        )

    flags = _get_flags()
    try:
        flags.reset_flag(name_upper)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Return the post-reset state
    all_flags = flags.list_flags()
    for flag in all_flags:
        if flag["name"] == name_upper:
            return flag

    raise HTTPException(status_code=500, detail="Flag found in metadata but not in list_flags()")

```

### `engine/llm/context_manager.py`
```python
"""
JARVIS TRADER — Pipeline Context Manager
==========================================
Implements a 4-tier context compaction strategy to prevent LLM context window
overflow during multi-agent pipeline runs.

Tier thresholds (by token utilization):
  NONE      < 50%  — no action needed
  TRIM     50-70%  — strip raw OHLCV arrays from message content
  TIME_CLEAR 70-85% — also remove stale analyst results (> 10 min old)
  SUMMARIZE 85-95% — also LLM-summarize prior stages via Haiku
  EMERGENCY  > 95% — keep only system prompt + last 2 messages

Usage:
    cm = PipelineContextManager(llm_client=client)
    cm.reset_for_pipeline_run()
    budget = cm.get_budget(model, messages)
    if budget.tier > CompactionTier.NONE:
        messages = cm.compact_messages(messages, budget.tier, model)
        messages = await cm.maybe_summarize(messages, model)
    stats = cm.get_stats()
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


class CompactionTier(IntEnum):
    NONE = 0  # < 50% — no action
    TRIM = 1  # 50-70% — strip raw OHLCV arrays
    TIME_CLEAR = 2  # 70-85% — remove stale analyst results
    SUMMARIZE = 3  # 85-95% — LLM-summarize prior stages (Haiku)
    EMERGENCY = 4  # > 95% — keep only system prompt + last 2 messages


@dataclass
class ContextBudget:
    """Snapshot of current token usage and recommended compaction tier."""

    model: str
    max_context_tokens: int
    current_input_tokens: int
    utilization: float  # 0.0 to 1.0
    tier: CompactionTier


@dataclass
class CompactionEvent:
    """Record of a single compaction action for statistics tracking."""

    timestamp: str
    tier: CompactionTier
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    pipeline_run_id: Optional[str] = None


class PipelineContextManager:
    """
    Manages LLM context across a pipeline run.
    Applies tiered compaction to prevent context overflow and maintain quality.

    This class is optional — inject it into TradingPipeline via context_manager
    parameter. If not injected, the pipeline operates exactly as before.

    Thread safety: each pipeline run should call reset_for_pipeline_run() first.
    The instance is safe to reuse across sequential runs.
    """

    # Model context windows (tokens)
    CONTEXT_WINDOWS = {
        "claude-opus-4-6": 200_000,
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5-20251001": 200_000,
    }
    DEFAULT_CONTEXT_WINDOW = 200_000

    # Compaction tier thresholds (utilization fraction)
    TIER_THRESHOLDS = {
        CompactionTier.TRIM: 0.50,
        CompactionTier.TIME_CLEAR: 0.70,
        CompactionTier.SUMMARIZE: 0.85,
        CompactionTier.EMERGENCY: 0.95,
    }

    # Time-based clearing: remove analyst results older than this many minutes
    STALE_ANALYSIS_MINUTES = 10

    def __init__(self, llm_client=None, config=None):
        """
        Args:
            llm_client: Optional JarvisLLMClient — required only for SUMMARIZE tier.
                        If None, SUMMARIZE tier falls back to TIME_CLEAR behavior.
            config: Optional TradingConfig instance. When provided, enables per-agent
                    token limits and prompt caching controls. When None, safe defaults
                    are used (cache_control enabled, default token limits).
        """
        self._client = llm_client
        self._compaction_events: list[CompactionEvent] = []
        self._pipeline_start_time: Optional[datetime] = None
        self._agent_timestamps: dict[str, datetime] = {}  # agent_name -> completion time
        self._cache_control_applied: int = 0  # tracks cache_control applications this session

        # Minimal config shim so methods work without a real TradingConfig
        if config is None:

            class _DefaultConfig:
                ENABLE_CONTEXT_COMPACTION = True
                AGENT_MAX_TOKENS: dict = {}

            self.config = _DefaultConfig()
        else:
            self.config = config

    # ── Token Estimation ───────────────────────────────────────────────────────

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """
        Rough token estimate: ~4 chars per token for English text.

        This is intentionally fast — it avoids calling the tokenizer.
        Accuracy is sufficient for tier detection (within ~20%).
        """
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return max(total_chars // 4, 1)

    # ── Budget Calculation ─────────────────────────────────────────────────────

    def get_budget(self, model: str, messages: list[dict]) -> ContextBudget:
        """
        Calculate current context budget and determine the appropriate tier.

        Args:
            model: Model name (used to look up context window size)
            messages: Current message list

        Returns:
            ContextBudget with utilization fraction and recommended tier
        """
        max_tokens = self.CONTEXT_WINDOWS.get(model, self.DEFAULT_CONTEXT_WINDOW)
        current_tokens = self.estimate_tokens(messages)
        utilization = current_tokens / max_tokens

        tier = CompactionTier.NONE
        # Check from highest to lowest — stop at first threshold exceeded
        for t in [
            CompactionTier.EMERGENCY,
            CompactionTier.SUMMARIZE,
            CompactionTier.TIME_CLEAR,
            CompactionTier.TRIM,
        ]:
            if utilization >= self.TIER_THRESHOLDS[t]:
                tier = t
                break

        return ContextBudget(
            model=model,
            max_context_tokens=max_tokens,
            current_input_tokens=current_tokens,
            utilization=utilization,
            tier=tier,
        )

    # ── Compaction Dispatch ────────────────────────────────────────────────────

    def compact_messages(
        self,
        messages: list[dict],
        tier: CompactionTier,
        model: str,
    ) -> list[dict]:
        """
        Apply synchronous compaction strategy. Returns compacted message list.

        Note: SUMMARIZE tier requires async — call maybe_summarize() separately
        after this method for the LLM-based summarization step.

        Args:
            messages: Current message list
            tier: Compaction tier to apply (from get_budget())
            model: Model name (used for logging only here)

        Returns:
            New (potentially smaller) message list
        """
        if tier == CompactionTier.NONE:
            return messages

        tokens_before = self.estimate_tokens(messages)

        if tier == CompactionTier.TRIM:
            messages = self._trim_ohlcv_data(messages)

        elif tier == CompactionTier.TIME_CLEAR:
            messages = self._trim_ohlcv_data(messages)
            messages = self._clear_stale_analysis(messages)

        elif tier == CompactionTier.SUMMARIZE:
            # Sync portion — async summarization happens in maybe_summarize()
            messages = self._trim_ohlcv_data(messages)
            messages = self._clear_stale_analysis(messages)

        elif tier == CompactionTier.EMERGENCY:
            # Keep only system message(s) + last 2 non-system messages
            system_msgs = [m for m in messages if m.get("role") == "system"]
            other_msgs = [m for m in messages if m.get("role") != "system"]
            messages = system_msgs + (other_msgs[-2:] if other_msgs else [])
            logger.warning(
                f"EMERGENCY context compaction triggered for {model}. "
                f"Kept {len(messages)} messages ({len(system_msgs)} system + "
                f"{len(messages) - len(system_msgs)} other)."
            )

        tokens_after = self.estimate_tokens(messages)
        event = CompactionEvent(
            timestamp=datetime.now().isoformat(),
            tier=tier,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
        )
        self._compaction_events.append(event)

        logger.info(
            f"Context compaction tier={tier.name}: "
            f"{tokens_before} -> {tokens_after} tokens "
            f"({event.tokens_saved} saved, {event.tokens_saved / max(tokens_before, 1):.1%} reduction)"
        )

        return messages

    # ── OHLCV Trimming ─────────────────────────────────────────────────────────

    def _trim_ohlcv_data(self, messages: list[dict]) -> list[dict]:
        """
        Remove raw OHLCV arrays from messages, keeping summaries.

        Targets JSON arrays with 4-6 numbers per element — the classic
        [timestamp, open, high, low, close, volume] pattern.  Replaces
        sequences of 5+ such arrays with a placeholder token.
        """
        import re

        # Pattern explanation:
        # \[              — opening bracket of first sub-array
        # \s*\d+\.?\d*   — first number (timestamp or OHLCV value)
        # (?:,\s*\d+...)  — 3 to 5 more numbers (OHLCV fields)
        # \]              — closing bracket
        # (?:,\s*\[...]){5,}  — followed by 5+ more identical arrays
        ohlcv_pattern = re.compile(
            r"\[\s*\d+\.?\d*"
            r"(?:,\s*\d+\.?\d*){3,5}"
            r"\s*\]"
            r"(?:\s*,\s*\[\s*\d+\.?\d*(?:,\s*\d+\.?\d*){3,5}\s*\]){5,}"
        )

        trimmed = []
        for msg in messages:
            content = str(msg.get("content", ""))
            new_content = ohlcv_pattern.sub("[... OHLCV data trimmed ...]", content)
            trimmed.append({**msg, "content": new_content})
        return trimmed

    # ── Stale Analysis Clearing ────────────────────────────────────────────────

    def _clear_stale_analysis(self, messages: list[dict]) -> list[dict]:
        """
        Remove analyst stage messages older than STALE_ANALYSIS_MINUTES.

        Messages are considered stale only when they carry a _jarvis_timestamp
        metadata key (set by mark_agent_message()). Untagged messages are kept.
        System messages are always preserved.
        """
        cutoff = datetime.now() - timedelta(minutes=self.STALE_ANALYSIS_MINUTES)
        result = []

        for msg in messages:
            # Always keep system messages
            if msg.get("role") == "system":
                result.append(msg)
                continue

            # Only drop messages that have an explicit jarvis timestamp AND are stale
            meta_time = msg.get("_jarvis_timestamp")
            if meta_time:
                try:
                    msg_time = datetime.fromisoformat(meta_time)
                    if msg_time < cutoff:
                        agent = msg.get("_jarvis_agent", "unknown")
                        logger.debug(
                            f"Dropping stale analyst message from {agent} "
                            f"(age: {(datetime.now() - msg_time).total_seconds():.0f}s)"
                        )
                        continue  # Drop this stale message
                except (ValueError, TypeError):
                    pass  # Malformed timestamp — keep the message

            result.append(msg)

        return result

    # ── Message Tagging ────────────────────────────────────────────────────────

    def mark_agent_message(self, messages: list[dict], agent_name: str) -> list[dict]:
        """
        Tag messages with timestamp metadata for stale detection.

        Call this when adding analyst results to the message list so that
        TIME_CLEAR compaction can identify and remove them later.

        Args:
            messages: Messages to tag
            agent_name: Name of the agent that produced these messages

        Returns:
            New list with _jarvis_timestamp and _jarvis_agent fields added
        """
        now = datetime.now().isoformat()
        self._agent_timestamps[agent_name] = datetime.now()
        return [{**m, "_jarvis_timestamp": now, "_jarvis_agent": agent_name} for m in messages]

    # ── Prompt Caching ─────────────────────────────────────────────────────────

    def add_cache_control_to_system_prompt(self, messages: list[dict]) -> list[dict]:
        """
        Add cache_control to the first user message content to enable prompt caching.

        Anthropic caches the first 1024+ tokens. This dramatically cuts cost for
        repeated pipeline runs using the same system prompts (up to ~90% savings on
        cached portions). cache_control is applied to the first user-role message so
        that Anthropic caches the system prompt context alongside it.

        Only applied when ENABLE_CONTEXT_COMPACTION is True.
        Returns a new list (does not mutate input).
        """
        if not self.config.ENABLE_CONTEXT_COMPACTION:
            return messages

        result = []
        cached = False
        for msg in messages:
            if not cached and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    new_msg = dict(msg)
                    new_msg["content"] = [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                    result.append(new_msg)
                    cached = True
                    self._cache_control_applied += 1
                    logger.debug(
                        f"Prompt cache_control applied to first user message "
                        f"(total applications this session: {self._cache_control_applied})"
                    )
                    continue
            result.append(msg)
        return result

    def get_agent_max_tokens(self, agent_name: str) -> int:
        """
        Return per-agent max_tokens from config, defaulting to 1500.

        Args:
            agent_name: The agent identifier (e.g. "technical_analyst", "trader")

        Returns:
            Integer token limit for the specified agent
        """
        limits = getattr(self.config, "AGENT_MAX_TOKENS", {})
        return limits.get(agent_name, 1500)

    # ── Async Summarization ────────────────────────────────────────────────────

    async def maybe_summarize(self, messages: list[dict], model: str) -> list[dict]:
        """
        If at SUMMARIZE tier, use Haiku to compress prior stages into a summary.

        This is the async complement to compact_messages() for the SUMMARIZE tier.
        Safe to call regardless of tier — it will no-op if below threshold.

        Args:
            messages: Current (already sync-compacted) message list
            model: Model currently in use (to determine budget)

        Returns:
            Potentially further-compressed message list
        """
        if not self._client:
            return messages

        budget = self.get_budget(model, messages)
        if budget.tier < CompactionTier.SUMMARIZE:
            return messages

        non_system = [m for m in messages if m.get("role") != "system"]
        if len(non_system) < 3:
            # Not enough content to meaningfully summarize
            return messages

        summary_prompt = (
            "Summarize the following trading analysis context in under 200 words.\n"
            "Keep: key signals, regime state, any trade recommendations, risk flags.\n"
            "Drop: raw numbers, repetitive analysis, OHLCV data.\n\n"
            "Context to summarize:\n" + json.dumps(non_system[-10:], indent=2)[:4000]
        )

        try:
            result = await self._client.call(
                model="claude-haiku-4-5-20251001",
                system="You are a concise trading context summarizer.",
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=300,
                agent_name="context_manager_summarizer",
            )

            if not result.success:
                logger.warning(f"Context summarization LLM call failed: {result.error}")
                return messages

            # Extract text from result — handle both LLMCallResult.content (str)
            # and raw dict response shapes
            if hasattr(result, "content") and isinstance(result.content, str):
                summary_content = result.content
            elif isinstance(result, dict):
                summary_content = result.get("content", [{}])[0].get("text", "")
            else:
                summary_content = str(result)

            system_msgs = [m for m in messages if m.get("role") == "system"]
            compressed = system_msgs + [
                {
                    "role": "assistant",
                    "content": f"[Context summary from prior analysis]: {summary_content}",
                }
            ]

            tokens_before = self.estimate_tokens(messages)
            tokens_after = self.estimate_tokens(compressed)
            logger.info(
                f"LLM context summarization: {tokens_before} -> {tokens_after} tokens "
                f"({tokens_before - tokens_after} saved)"
            )
            return compressed

        except Exception as e:
            logger.error(f"Context summarization failed unexpectedly: {e}")
            return messages

    # ── Statistics ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Return compaction statistics for dashboard display.

        Returns:
            Dict with total events, per-tier counts, tokens saved, recent events
        """
        tier_counts = {t.name: 0 for t in CompactionTier}
        total_saved = 0

        for event in self._compaction_events:
            tier_counts[event.tier.name] += 1
            total_saved += event.tokens_saved

        return {
            "total_compaction_events": len(self._compaction_events),
            "tier_counts": tier_counts,
            "total_tokens_saved": total_saved,
            "cache_control_applied": self._cache_control_applied,
            "recent_events": [
                {
                    "tier": e.tier.name,
                    "saved": e.tokens_saved,
                    "ts": e.timestamp,
                }
                for e in self._compaction_events[-10:]
            ],
        }

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def reset_for_pipeline_run(self) -> None:
        """
        Call at the start of each pipeline run to reset per-run state.

        Does NOT reset the compaction_events list — those accumulate across
        all runs so the dashboard can show historical stats.
        """
        self._pipeline_start_time = datetime.now()
        self._agent_timestamps.clear()
        logger.debug("PipelineContextManager reset for new pipeline run")

```

### `engine/kairos/__init__.py`
```python
"""
KAIROS — Proactive Monitoring Daemon
======================================
Always-on background monitoring for JARVIS TRADER.

Components:
  KairosDaemon     — background asyncio task, runs watchers on each tick
  BaseWatcher      — ABC for all rule-based watchers
  Observation      — single observation data class
  Severity         — info / warning / critical
  ObservationLog   — append-only JSONL log (one file per day)
  KairosDreamer    — nightly pattern consolidation (optional LLM)

Usage in FastAPI lifespan:
    from kairos import KairosDaemon, set_kairos_instance
    from kairos.watchers import (
        RegimeChangeWatcher, STCCrossoverWatcher, RiskLimitWatcher,
        VIXSpikeWatcher, VolumeAnomalyWatcher, SpreadWideningWatcher,
        CorrelationBreakWatcher,
    )

    daemon = KairosDaemon(config=settings, safety_layer=safety_layer, ...)
    daemon.register_watcher(RegimeChangeWatcher())
    # ... register other watchers ...
    await daemon.start()
    set_kairos_instance(daemon)
"""

from .daemon import KairosDaemon, get_kairos, set_kairos_instance
from .dreaming import KairosDreamer
from .observation_log import ObservationLog
from .watchers import BaseWatcher, Observation, Severity

__all__ = [
    "KairosDaemon",
    "get_kairos",
    "set_kairos_instance",
    "BaseWatcher",
    "Observation",
    "Severity",
    "ObservationLog",
    "KairosDreamer",
]

```

### `engine/kairos/daemon.py`
```python
"""
KAIROS — Proactive Monitoring Daemon
======================================
Always-on background task running inside the FastAPI lifespan.

Design rules:
- ZERO LLM calls in the monitoring loop — pure Python watchers only.
- Tick interval: 60 s during market hours (CT 8:30–16:00 weekdays), 300 s off-hours.
- Each tick builds a market snapshot, runs all registered watchers, logs and emits
  any observations, and optionally sends notifications.
- Tolerant of missing dependencies: data_manager=None, safety_layer=None, etc.
  all produce graceful degradation rather than errors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .observation_log import ObservationLog
from .watchers import BaseWatcher

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Module-level singleton ─────────────────────────────────────────────────

_kairos_instance: Optional["KairosDaemon"] = None


def get_kairos() -> Optional["KairosDaemon"]:
    """Return the active KairosDaemon singleton (or None if not started)."""
    return _kairos_instance


def set_kairos_instance(daemon: "KairosDaemon") -> None:
    """Register the global KairosDaemon singleton."""
    global _kairos_instance
    _kairos_instance = daemon


# ── KairosDaemon ──────────────────────────────────────────────────────────


class KairosDaemon:
    """
    KAIROS: Always-on proactive monitoring daemon.

    Runs as an asyncio background task within FastAPI lifespan.
    Tick-based cycle: 60 s market hours, 300 s off-hours.
    ZERO LLM calls in monitoring loop — pure Python rules via watchers.
    """

    def __init__(
        self,
        config,
        data_manager=None,
        safety_layer=None,
        ws_manager=None,
        notifier=None,
    ) -> None:
        self._config = config
        self._data = data_manager
        self._safety = safety_layer
        self._ws = ws_manager
        self._notifier = notifier
        self._running = False
        self._tick_count = 0
        self._start_time: Optional[datetime] = None
        self._last_tick_time: Optional[datetime] = None
        self._watchers: list[BaseWatcher] = []
        self._log = ObservationLog()
        self._task: Optional[asyncio.Task] = None
        self._error_count = 0

    # ── Watcher registration ───────────────────────────────────────────────

    def register_watcher(self, watcher: BaseWatcher) -> None:
        """Add a watcher to the monitoring loop."""
        self._watchers.append(watcher)
        logger.info(f"KAIROS: registered watcher '{watcher.name}'")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            logger.warning("KAIROS: already running — ignoring duplicate start()")
            return
        self._running = True
        self._start_time = datetime.now()
        self._task = asyncio.create_task(self._run_loop(), name="kairos_daemon")
        logger.info(f"KAIROS: daemon started with {len(self._watchers)} watchers registered")

    async def stop(self) -> None:
        """Stop the background monitoring loop and clean up."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("KAIROS: daemon stopped")

    # ── Main loop ─────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Infinite monitoring loop — ticks and sleeps until stopped."""
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error_count += 1
                logger.error(f"KAIROS tick error (total errors={self._error_count}): {exc}")

            interval = self._get_tick_interval()
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    def _get_tick_interval(self) -> int:
        """
        Return tick interval in seconds.
        Market hours (America/Chicago): Mon-Fri 08:30-16:00 → 60 s.
        Off-hours or weekends → 300 s.
        Falls back to simple UTC hour check if pytz is unavailable.
        """
        config_fast = getattr(self._config, "KAIROS_TICK_SECONDS", 60)
        config_slow = getattr(self._config, "KAIROS_OFF_HOURS_TICK_SECONDS", 300)

        try:
            from datetime import time as dt_time

            import pytz

            tz = pytz.timezone("America/Chicago")
            now = datetime.now(tz)
            is_weekday = now.weekday() < 5
            market_open = dt_time(8, 30)
            market_close = dt_time(16, 0)
            is_market_hours = market_open <= now.time() <= market_close
            if is_weekday and is_market_hours:
                return config_fast
            return config_slow

        except ImportError:
            # Fallback: rough UTC check (CT market hours ≈ 14:30–22:00 UTC)
            from datetime import timezone as tz_module

            now_utc = datetime.now(tz_module.utc)
            is_weekday = now_utc.weekday() < 5
            is_rough_market = 14 <= now_utc.hour < 22
            if is_weekday and is_rough_market:
                return config_fast
            return config_slow

    # ── Single tick ────────────────────────────────────────────────────────

    async def tick(self) -> None:
        """Execute one monitoring cycle: build snapshot → run watchers → emit."""
        self._tick_count += 1
        self._last_tick_time = datetime.now()

        snapshot = await self._build_snapshot()

        severity_order = {"info": 0, "warning": 1, "critical": 2}
        min_notify_severity = getattr(self._config, "KAIROS_NOTIFY_SEVERITY", "warning")
        min_level = severity_order.get(min_notify_severity, 1)

        for watcher in self._watchers:
            try:
                obs_list = await watcher.check(snapshot)
            except Exception as exc:
                logger.error(f"KAIROS watcher '{watcher.name}' raised an exception: {exc}")
                continue

            for obs in obs_list:
                # Always log to JSONL file
                self._log.append(obs)

                # Emit via WebSocket if manager is available
                if self._ws:
                    try:
                        await self._ws.broadcast(
                            {
                                "type": "kairos_observation",
                                "data": {
                                    "watcher": obs.watcher,
                                    "severity": obs.severity.value,
                                    "message": obs.message,
                                    "symbol": obs.symbol,
                                    "timestamp": obs.timestamp,
                                },
                            }
                        )
                    except Exception as ws_exc:
                        logger.debug(f"KAIROS WebSocket broadcast failed: {ws_exc}")

                # Send notification for qualifying observations
                obs_level = severity_order.get(obs.severity.value, 0)
                if obs.notify and obs_level >= min_level and self._notifier:
                    try:
                        await self._notifier.send_alert(
                            f"KAIROS [{obs.severity.value.upper()}] {obs.watcher}\n"
                            f"{obs.message}"
                        )
                    except Exception as notify_exc:
                        logger.debug(f"KAIROS notifier failed: {notify_exc}")

    # ── Snapshot builder ───────────────────────────────────────────────────

    async def _build_snapshot(self) -> dict:
        """
        Assemble the market snapshot dict passed to every watcher.

        Structure:
          snapshot["timestamp"]         — ISO string
          snapshot["risk_status"]       — dict from SafetyLayer.get_status()
          snapshot["vix"]               — float | None
          snapshot["symbols"][symbol]   — {"price", "volume", "stc", "regime", "spread"}
        """
        snapshot: dict = {
            "timestamp": datetime.now().isoformat(),
            "symbols": {},
            "risk_status": {},
            "vix": None,
        }

        # Risk status from SafetyLayer
        if self._safety is not None:
            try:
                if hasattr(self._safety, "get_status"):
                    snapshot["risk_status"] = self._safety.get_status()
            except Exception as exc:
                logger.debug(f"KAIROS snapshot: SafetyLayer.get_status() failed: {exc}")

        # Market data per symbol
        if self._data is not None:
            watchlist = getattr(self._config, "FUTURES_WATCHLIST", ["MES", "MNQ"])
            if isinstance(watchlist, str):
                watchlist = [s.strip() for s in watchlist.split(",") if s.strip()]

            for symbol in watchlist:
                try:
                    symbol_data: dict = {}

                    if hasattr(self._data, "get_bars"):
                        bars = await self._data.get_bars(symbol, interval="5m", limit=50)
                        if bars is not None and hasattr(bars, "iloc") and len(bars) > 0:
                            symbol_data["price"] = float(bars["close"].iloc[-1])
                            if "volume" in bars.columns:
                                symbol_data["volume"] = float(bars["volume"].iloc[-1])
                            if "regime" in bars.columns:
                                symbol_data["regime"] = str(bars["regime"].iloc[-1])
                            # STC is computed on-demand if signals available
                            symbol_data["stc"] = None

                    snapshot["symbols"][symbol] = symbol_data

                except Exception as exc:
                    logger.debug(f"KAIROS snapshot: data for {symbol} failed: {exc}")
                    snapshot["symbols"][symbol] = {}

        return snapshot

    # ── Status & inspection ────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a JSON-serialisable status dict for the /kairos/status endpoint."""
        uptime_seconds: Optional[float] = None
        if self._start_time:
            uptime_seconds = (datetime.now() - self._start_time).total_seconds()

        return {
            "running": self._running,
            "tick_count": self._tick_count,
            "watcher_count": len(self._watchers),
            "watchers": [w.name for w in self._watchers],
            "uptime_seconds": uptime_seconds,
            "last_tick": (self._last_tick_time.isoformat() if self._last_tick_time else None),
            "error_count": self._error_count,
            "today_observation_count": len(self._log.read_today()),
        }

    def get_today_observations(self) -> list[dict]:
        """Return all observations logged today."""
        return self._log.read_today()

    def get_recent_observations(self, minutes: int = 60) -> list[dict]:
        """Return observations from the last N minutes."""
        return self._log.get_recent(minutes=minutes)

```

### `engine/kairos/watchers.py`
```python
"""
KAIROS — Watchers
==================
Pure-Python rule-based market observation classes.
ZERO LLM calls. All watchers are tolerant of missing data.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Data Structures ────────────────────────────────────────────────────────


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Observation:
    timestamp: str
    watcher: str
    severity: Severity
    message: str
    data: dict = field(default_factory=dict)
    notify: bool = False  # Should trigger WhatsApp notification?
    symbol: Optional[str] = None


# ── Base Watcher ABC ───────────────────────────────────────────────────────


class BaseWatcher(ABC):
    name: str = "base"

    @abstractmethod
    async def check(self, market_snapshot: dict) -> list[Observation]:
        """Run check, return observations (may be empty list)."""

    def _obs(
        self,
        severity: Severity,
        message: str,
        data: dict = None,
        notify: bool = False,
        symbol: str = None,
    ) -> Observation:
        """Helper to create an observation."""
        return Observation(
            timestamp=datetime.now().isoformat(),
            watcher=self.name,
            severity=severity,
            message=message,
            data=data or {},
            notify=notify,
            symbol=symbol,
        )


# ── 1. RegimeChangeWatcher ─────────────────────────────────────────────────


class RegimeChangeWatcher(BaseWatcher):
    """
    Fires WARNING + notify=True when a symbol's market regime transitions.
    Reads market_snapshot["symbols"][symbol]["regime"].
    """

    name = "regime_change"

    def __init__(self) -> None:
        self._last_regimes: dict[str, str] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            current_regime = data.get("regime")
            if current_regime is None:
                continue

            last = self._last_regimes.get(symbol)
            if last is not None and last != current_regime:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(f"{symbol} regime changed: {last} → {current_regime}"),
                        data={"symbol": symbol, "from": last, "to": current_regime},
                        notify=True,
                        symbol=symbol,
                    )
                )
                logger.info(f"RegimeChangeWatcher: {symbol} {last} → {current_regime}")

            self._last_regimes[symbol] = current_regime

        return observations


# ── 2. STCCrossoverWatcher ─────────────────────────────────────────────────


class STCCrossoverWatcher(BaseWatcher):
    """
    Detects STC crossing the OS=15 (oversold) or OB=83 (overbought) thresholds.
    Reads market_snapshot["symbols"][symbol]["stc"].
    Per-instrument OB thresholds from signals.py INSTRUMENT_PARAMS.
    """

    name = "stc_crossover"

    # Per-symbol OB thresholds matching INSTRUMENT_PARAMS in signals.py
    _OB_THRESHOLDS: dict[str, float] = {
        "MNQ": 92.0,
        "MCL": 83.0,
        "MGC": 88.0,
        "SPY": 88.0,
        "MES": 83.0,
    }
    _DEFAULT_OB = 83.0
    _OS = 15.0

    def __init__(self) -> None:
        self._last_stc: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            current_stc = data.get("stc")
            if current_stc is None:
                continue

            try:
                current_stc = float(current_stc)
            except (TypeError, ValueError):
                continue

            ob_threshold = self._OB_THRESHOLDS.get(symbol, self._DEFAULT_OB)
            last = self._last_stc.get(symbol)

            if last is not None:
                # Crossed into oversold territory (above OS → below OS)
                if last >= self._OS and current_stc < self._OS:
                    observations.append(
                        self._obs(
                            severity=Severity.WARNING,
                            message=(
                                f"{symbol} STC crossed into oversold: "
                                f"{last:.1f} → {current_stc:.1f} (threshold={self._OS})"
                            ),
                            data={
                                "symbol": symbol,
                                "stc_prev": last,
                                "stc_current": current_stc,
                                "threshold": self._OS,
                                "direction": "oversold",
                            },
                            notify=True,
                            symbol=symbol,
                        )
                    )
                # Crossed into overbought territory (below OB → above OB)
                elif last <= ob_threshold and current_stc > ob_threshold:
                    observations.append(
                        self._obs(
                            severity=Severity.WARNING,
                            message=(
                                f"{symbol} STC crossed into overbought: "
                                f"{last:.1f} → {current_stc:.1f} (threshold={ob_threshold})"
                            ),
                            data={
                                "symbol": symbol,
                                "stc_prev": last,
                                "stc_current": current_stc,
                                "threshold": ob_threshold,
                                "direction": "overbought",
                            },
                            notify=True,
                            symbol=symbol,
                        )
                    )

            self._last_stc[symbol] = current_stc

        return observations


# ── 3. RiskLimitWatcher ────────────────────────────────────────────────────


class RiskLimitWatcher(BaseWatcher):
    """
    Monitors approaching risk limits from SafetyLayer.get_status().
    Reads market_snapshot["risk_status"].
    Fields expected: daily_pnl, daily_loss_limit, drawdown_pct, max_drawdown_pct.
    """

    name = "risk_limit"

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        risk = market_snapshot.get("risk_status", {})
        if not isinstance(risk, dict) or not risk:
            return observations

        daily_pnl = risk.get("daily_pnl")
        daily_loss_limit = risk.get("daily_loss_limit")
        drawdown_pct = risk.get("drawdown_pct")

        # Daily loss limit checks
        if daily_pnl is not None and daily_loss_limit is not None:
            try:
                pnl = float(daily_pnl)
                limit = float(daily_loss_limit)
                if limit < 0 and pnl < 0:
                    utilization = pnl / limit  # both negative → ratio 0..1+
                    if utilization >= 0.90:
                        observations.append(
                            self._obs(
                                severity=Severity.CRITICAL,
                                message=(
                                    f"Daily loss at {utilization*100:.1f}% of limit "
                                    f"(PnL={pnl:.2f}, limit={limit:.2f})"
                                ),
                                data={
                                    "daily_pnl": pnl,
                                    "daily_loss_limit": limit,
                                    "utilization_pct": round(utilization * 100, 1),
                                },
                                notify=True,
                            )
                        )
                    elif utilization >= 0.80:
                        observations.append(
                            self._obs(
                                severity=Severity.WARNING,
                                message=(
                                    f"Daily loss approaching limit: {utilization*100:.1f}% used "
                                    f"(PnL={pnl:.2f}, limit={limit:.2f})"
                                ),
                                data={
                                    "daily_pnl": pnl,
                                    "daily_loss_limit": limit,
                                    "utilization_pct": round(utilization * 100, 1),
                                },
                                notify=False,
                            )
                        )
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        # Drawdown check
        if drawdown_pct is not None:
            try:
                dd = float(drawdown_pct)
                if dd > 5.0:
                    observations.append(
                        self._obs(
                            severity=Severity.INFO,
                            message=(f"Portfolio drawdown exceeds 5%: current={dd:.1f}%"),
                            data={"drawdown_pct": dd},
                            notify=False,
                        )
                    )
            except (TypeError, ValueError):
                pass

        return observations


# ── 4. VIXSpikeWatcher ─────────────────────────────────────────────────────


class VIXSpikeWatcher(BaseWatcher):
    """
    Fires on rapid VIX movements within a rolling 15-minute window.
    Reads market_snapshot["vix"] (float or None).
    WARNING: >1.5 pt move in 15 min.
    CRITICAL: >3.0 pt move in 15 min.
    """

    name = "vix_spike"
    _WINDOW_MINUTES = 15
    _WARN_MOVE = 1.5
    _CRITICAL_MOVE = 3.0

    def __init__(self) -> None:
        # Deque of (datetime, float) pairs — rolling 15-min history
        self._vix_history: deque[tuple[datetime, float]] = deque()

    def _prune(self) -> None:
        """Remove entries older than 15 minutes."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(minutes=self._WINDOW_MINUTES)
        while self._vix_history and self._vix_history[0][0] < cutoff:
            self._vix_history.popleft()

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        vix_raw = market_snapshot.get("vix")
        if vix_raw is None:
            return observations

        try:
            vix = float(vix_raw)
        except (TypeError, ValueError):
            return observations

        now = datetime.now()
        self._prune()
        self._vix_history.append((now, vix))

        if len(self._vix_history) < 2:
            return observations

        oldest_vix = self._vix_history[0][1]
        move = abs(vix - oldest_vix)

        if move >= self._CRITICAL_MOVE:
            observations.append(
                self._obs(
                    severity=Severity.CRITICAL,
                    message=(
                        f"VIX spike CRITICAL: moved {move:.2f} pts in "
                        f"{self._WINDOW_MINUTES} min "
                        f"({oldest_vix:.2f} → {vix:.2f})"
                    ),
                    data={
                        "vix_current": vix,
                        "vix_15min_ago": oldest_vix,
                        "move": round(move, 2),
                        "window_minutes": self._WINDOW_MINUTES,
                    },
                    notify=True,
                )
            )
        elif move >= self._WARN_MOVE:
            observations.append(
                self._obs(
                    severity=Severity.WARNING,
                    message=(
                        f"VIX spike WARNING: moved {move:.2f} pts in "
                        f"{self._WINDOW_MINUTES} min "
                        f"({oldest_vix:.2f} → {vix:.2f})"
                    ),
                    data={
                        "vix_current": vix,
                        "vix_15min_ago": oldest_vix,
                        "move": round(move, 2),
                        "window_minutes": self._WINDOW_MINUTES,
                    },
                    notify=True,
                )
            )

        return observations


# ── 5. VolumeAnomalyWatcher ────────────────────────────────────────────────


class VolumeAnomalyWatcher(BaseWatcher):
    """
    Detects unusual volume relative to rolling average.
    Reads market_snapshot["symbols"][symbol]["volume"].
    INFO: >1.5x average. WARNING + notify: >2.5x average.
    """

    name = "volume_anomaly"
    _INFO_MULT = 1.5
    _WARN_MULT = 2.5
    _WINDOW = 20  # bars used for rolling average

    def __init__(self) -> None:
        # Rolling volume history per symbol
        self._vol_history: dict[str, deque[float]] = {}
        self._avg_volumes: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            vol_raw = data.get("volume")
            if vol_raw is None:
                continue
            try:
                volume = float(vol_raw)
            except (TypeError, ValueError):
                continue

            if symbol not in self._vol_history:
                self._vol_history[symbol] = deque(maxlen=self._WINDOW)

            self._vol_history[symbol].append(volume)

            if len(self._vol_history[symbol]) < 3:
                continue  # Need at least a few bars to compute average

            avg = sum(self._vol_history[symbol]) / len(self._vol_history[symbol])
            self._avg_volumes[symbol] = avg

            if avg <= 0:
                continue

            ratio = volume / avg

            if ratio >= self._WARN_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(
                            f"{symbol} volume anomaly: {ratio:.1f}x average "
                            f"(current={volume:,.0f}, avg={avg:,.0f})"
                        ),
                        data={
                            "symbol": symbol,
                            "volume": volume,
                            "avg_volume": round(avg, 2),
                            "ratio": round(ratio, 2),
                        },
                        notify=True,
                        symbol=symbol,
                    )
                )
            elif ratio >= self._INFO_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.INFO,
                        message=(
                            f"{symbol} elevated volume: {ratio:.1f}x average "
                            f"(current={volume:,.0f}, avg={avg:,.0f})"
                        ),
                        data={
                            "symbol": symbol,
                            "volume": volume,
                            "avg_volume": round(avg, 2),
                            "ratio": round(ratio, 2),
                        },
                        notify=False,
                        symbol=symbol,
                    )
                )

        return observations


# ── 6. SpreadWideningWatcher ───────────────────────────────────────────────


class SpreadWideningWatcher(BaseWatcher):
    """
    Fires WARNING when bid-ask spread widens beyond 2x the established baseline.
    Reads market_snapshot["symbols"][symbol]["spread"] (float).
    Baseline is established as rolling median of first N observations.
    """

    name = "spread_widening"
    _WARN_MULT = 2.0
    _BASELINE_WINDOW = 10  # number of bars to establish baseline

    def __init__(self) -> None:
        self._spread_history: dict[str, deque[float]] = {}
        self._normal_spreads: dict[str, float] = {}

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        for symbol, data in symbols.items():
            if not isinstance(data, dict):
                continue
            spread_raw = data.get("spread")
            if spread_raw is None:
                continue
            try:
                spread = float(spread_raw)
            except (TypeError, ValueError):
                continue
            if spread <= 0:
                continue

            if symbol not in self._spread_history:
                self._spread_history[symbol] = deque(maxlen=self._BASELINE_WINDOW)

            self._spread_history[symbol].append(spread)

            if len(self._spread_history[symbol]) < self._BASELINE_WINDOW:
                # Still calibrating baseline
                continue

            # Use median of history as normal spread
            sorted_history = sorted(self._spread_history[symbol])
            mid = len(sorted_history) // 2
            normal = sorted_history[mid]
            self._normal_spreads[symbol] = normal

            if normal <= 0:
                continue

            ratio = spread / normal

            if ratio >= self._WARN_MULT:
                observations.append(
                    self._obs(
                        severity=Severity.WARNING,
                        message=(
                            f"{symbol} spread widening: {ratio:.1f}x normal "
                            f"(spread={spread:.4f}, normal={normal:.4f})"
                        ),
                        data={
                            "symbol": symbol,
                            "spread": spread,
                            "normal_spread": round(normal, 6),
                            "ratio": round(ratio, 2),
                        },
                        notify=False,
                        symbol=symbol,
                    )
                )

        return observations


# ── 7. CorrelationBreakWatcher ─────────────────────────────────────────────


class CorrelationBreakWatcher(BaseWatcher):
    """
    Monitors MES/MNQ price correlation.
    Normally these move together (correlation > 0.8).
    Fires WARNING when 15-min returns diverge by >1.5%.
    """

    name = "correlation_break"
    _DIVERGE_THRESHOLD = 0.015  # 1.5% divergence in returns
    _SYMBOL_A = "MES"
    _SYMBOL_B = "MNQ"
    _WINDOW = 3  # bars in rolling window for return calculation

    def __init__(self) -> None:
        self._prices_a: deque[float] = deque(maxlen=self._WINDOW + 1)
        self._prices_b: deque[float] = deque(maxlen=self._WINDOW + 1)

    async def check(self, market_snapshot: dict) -> list[Observation]:
        observations: list[Observation] = []
        symbols = market_snapshot.get("symbols", {})

        data_a = symbols.get(self._SYMBOL_A, {})
        data_b = symbols.get(self._SYMBOL_B, {})

        if not isinstance(data_a, dict) or not isinstance(data_b, dict):
            return observations

        price_a_raw = data_a.get("price")
        price_b_raw = data_b.get("price")

        if price_a_raw is None or price_b_raw is None:
            return observations

        try:
            price_a = float(price_a_raw)
            price_b = float(price_b_raw)
        except (TypeError, ValueError):
            return observations

        self._prices_a.append(price_a)
        self._prices_b.append(price_b)

        if len(self._prices_a) < 2 or len(self._prices_b) < 2:
            return observations

        # Compute simple return from oldest to newest price in window
        prev_a = list(self._prices_a)[0]
        prev_b = list(self._prices_b)[0]

        if prev_a <= 0 or prev_b <= 0:
            return observations

        return_a = (price_a - prev_a) / prev_a
        return_b = (price_b - prev_b) / prev_b
        divergence = abs(return_a - return_b)

        if divergence >= self._DIVERGE_THRESHOLD:
            observations.append(
                self._obs(
                    severity=Severity.WARNING,
                    message=(
                        f"Correlation break: {self._SYMBOL_A}/{self._SYMBOL_B} "
                        f"returns diverged by {divergence*100:.2f}% "
                        f"({self._SYMBOL_A}={return_a*100:.2f}%, "
                        f"{self._SYMBOL_B}={return_b*100:.2f}%)"
                    ),
                    data={
                        "symbol_a": self._SYMBOL_A,
                        "symbol_b": self._SYMBOL_B,
                        "return_a": round(return_a, 6),
                        "return_b": round(return_b, 6),
                        "divergence": round(divergence, 6),
                        "price_a": price_a,
                        "price_b": price_b,
                    },
                    notify=False,
                )
            )

        return observations

```

### `engine/kairos/observation_log.py`
```python
"""
KAIROS — Observation Log
=========================
Append-only JSONL observation log. One file per day in data/kairos/.
Thread-safe for single-process asyncio usage.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .watchers import Observation

logger = logging.getLogger(__name__)


class ObservationLog:
    """
    Append-only JSONL observation log.
    One file per calendar day: data/kairos/YYYY-MM-DD.jsonl
    """

    def __init__(self, base_dir: str = "data/kairos") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _get_file(self, d: Optional[date] = None) -> Path:
        d = d or date.today()
        return self.base_dir / f"{d.isoformat()}.jsonl"

    # ── Write ──────────────────────────────────────────────────────────────

    def append(self, obs: Observation) -> None:
        """Append a single observation to today's JSONL log file."""
        line = json.dumps(
            {
                "timestamp": obs.timestamp,
                "watcher": obs.watcher,
                "severity": obs.severity.value,
                "message": obs.message,
                "data": obs.data,
                "notify": obs.notify,
                "symbol": obs.symbol,
            },
            ensure_ascii=False,
        )
        try:
            with open(self._get_file(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            logger.error(f"ObservationLog.append failed: {exc}")

    # ── Read ───────────────────────────────────────────────────────────────

    def read_today(self) -> list[dict]:
        """Return all observations logged today."""
        return self.read_date(date.today().isoformat())

    def read_date(self, date_str: str) -> list[dict]:
        """Return all observations for a given ISO date string."""
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            logger.warning(f"ObservationLog.read_date: invalid date '{date_str}'")
            return []

        path = self._get_file(d)
        if not path.exists():
            return []

        results: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        f"ObservationLog: skipping malformed JSON on line {line_no} "
                        f"of {path.name}: {exc}"
                    )
        return results

    def get_recent(self, minutes: int = 60) -> list[dict]:
        """Return observations from the last N minutes (today's log only)."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        all_obs = self.read_today()
        result: list[dict] = []
        for o in all_obs:
            try:
                ts = datetime.fromisoformat(o["timestamp"])
                if ts > cutoff:
                    result.append(o)
            except (KeyError, ValueError):
                continue
        return result

    def count_by_severity(self, date_str: str = None) -> dict:
        """Return observation counts grouped by severity for a given date (default today)."""
        obs = self.read_date(date_str) if date_str else self.read_today()
        counts: dict[str, int] = {"info": 0, "warning": 0, "critical": 0}
        for o in obs:
            sev = o.get("severity", "info")
            counts[sev] = counts.get(sev, 0) + 1
        return counts

```

### `engine/kairos/dreaming.py`
```python
"""
KAIROS — Dreaming (Nightly Consolidation)
==========================================
Summarises a day's observations into patterns and insights.
Optionally calls claude-haiku-4-5 for qualitative pattern analysis.
Works without an LLM client (returns statistical summary only).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


class KairosDreamer:
    """
    Nightly consolidation of KAIROS observations.

    Uses the FAST_MODEL (claude-haiku-4-5-20251001 by default) for qualitative
    pattern analysis when an LLM client is available.  Gracefully degrades to a
    pure-Python statistical summary when no client is provided.
    """

    def __init__(self, llm_client=None, observation_log=None) -> None:
        self._client = llm_client
        self._log = observation_log

    # ── Public API ─────────────────────────────────────────────────────────

    async def dream(self, target_date: str = None) -> dict:
        """
        Run nightly consolidation for a given ISO date (default: today).

        Returns a dict with:
          date, total_observations, severity_counts, watcher_hits,
          top_watchers, patterns, llm_insights
        """
        target_date = target_date or date.today().isoformat()

        if self._log is None:
            return {"error": "No observation log available"}

        observations = self._log.read_date(target_date)
        if not observations:
            return {
                "date": target_date,
                "summary": "No observations to consolidate.",
                "patterns": [],
                "severity_counts": {"info": 0, "warning": 0, "critical": 0},
                "watcher_hits": {},
                "top_watchers": [],
                "llm_insights": None,
            }

        counts = self._log.count_by_severity(target_date)

        watcher_hits: dict[str, int] = {}
        symbol_hits: dict[str, int] = {}
        critical_messages: list[str] = []

        for obs in observations:
            w = obs.get("watcher", "unknown")
            watcher_hits[w] = watcher_hits.get(w, 0) + 1

            sym = obs.get("symbol")
            if sym:
                symbol_hits[sym] = symbol_hits.get(sym, 0) + 1

            if obs.get("severity") == "critical":
                critical_messages.append(obs.get("message", ""))

        top_watchers = sorted(watcher_hits.items(), key=lambda x: x[1], reverse=True)[:5]

        # Rule-based pattern detection
        patterns: list[str] = self._detect_patterns(observations, counts, watcher_hits)

        summary: dict = {
            "date": target_date,
            "total_observations": len(observations),
            "severity_counts": counts,
            "watcher_hits": watcher_hits,
            "top_watchers": top_watchers,
            "symbol_hits": symbol_hits,
            "critical_messages": critical_messages[:10],
            "patterns": patterns,
            "llm_insights": None,
        }

        # Optional LLM insights via Haiku
        if self._client is not None and len(observations) > 0:
            summary["llm_insights"] = await self._call_llm(observations, target_date)

        return summary

    # ── Pattern detection (no LLM) ─────────────────────────────────────────

    def _detect_patterns(
        self,
        observations: list[dict],
        counts: dict,
        watcher_hits: dict[str, int],
    ) -> list[str]:
        """Simple rule-based pattern identification from observation statistics."""
        patterns: list[str] = []

        total = len(observations)
        critical_count = counts.get("critical", 0)
        warning_count = counts.get("warning", 0)

        if critical_count > 0:
            patterns.append(
                f"High-severity day: {critical_count} CRITICAL observation(s) recorded."
            )

        if total > 0 and warning_count / total > 0.5:
            patterns.append(
                f"Warning-heavy session: {warning_count}/{total} observations were WARNING level."
            )

        # Watcher dominance
        if watcher_hits:
            top_watcher, top_count = max(watcher_hits.items(), key=lambda x: x[1])
            if top_count > total * 0.4:
                patterns.append(
                    f"Watcher '{top_watcher}' dominated with {top_count} hits "
                    f"({top_count/total*100:.0f}% of observations)."
                )

        # VIX activity
        vix_hits = watcher_hits.get("vix_spike", 0)
        if vix_hits >= 3:
            patterns.append(
                f"Elevated VIX activity: {vix_hits} spike observations — high-volatility session."
            )

        # Regime instability
        regime_hits = watcher_hits.get("regime_change", 0)
        if regime_hits >= 3:
            patterns.append(
                f"Regime instability: {regime_hits} regime changes detected — choppy conditions."
            )

        # Spread widening
        spread_hits = watcher_hits.get("spread_widening", 0)
        if spread_hits >= 2:
            patterns.append(f"Liquidity concerns: {spread_hits} spread-widening events logged.")

        # Correlation breaks
        corr_hits = watcher_hits.get("correlation_break", 0)
        if corr_hits >= 2:
            patterns.append(f"MES/MNQ correlation breakdown observed {corr_hits} time(s).")

        if not patterns:
            patterns.append("Uneventful session — no dominant patterns detected.")

        return patterns

    # ── LLM call (Haiku) ──────────────────────────────────────────────────

    async def _call_llm(self, observations: list[dict], target_date: str) -> Optional[str]:
        """Call Haiku for qualitative pattern analysis. Returns None on failure."""
        obs_text = "\n".join(
            [
                f"[{o.get('severity', 'info').upper()}] "
                f"{o.get('watcher', '')}: {o.get('message', '')}"
                for o in observations[:50]
            ]
        )
        prompt = (
            f"Analyze these market observations from {target_date} and identify "
            f"3-5 key patterns or insights for a futures day-trader:\n\n{obs_text}"
        )
        try:
            # Support both direct Anthropic client and wrapped LLM clients
            if hasattr(self._client, "call"):
                result = await self._client.call(
                    model="claude-haiku-4-5-20251001",
                    system=(
                        "You are a trading pattern analyst. "
                        "Identify recurring patterns in market observations. "
                        "Be concise and actionable."
                    ),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                )
                content = result.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
                return str(result)

            elif hasattr(self._client, "messages"):
                # Direct anthropic.AsyncAnthropic client
                msg = await self._client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    system=(
                        "You are a trading pattern analyst. "
                        "Identify recurring patterns in market observations."
                    ),
                    messages=[{"role": "user", "content": prompt}],
                )
                return msg.content[0].text if msg.content else ""

        except Exception as exc:
            logger.error(f"KAIROS dreaming LLM call failed: {exc}")

        return None

```

### `engine/routers/kairos_router.py`
```python
"""KAIROS proactive monitoring daemon router."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from kairos import get_kairos

router = APIRouter(prefix="/kairos", tags=["kairos"])


@router.get("/status")
async def get_kairos_status():
    """Get KAIROS daemon status."""
    daemon = get_kairos()
    if not daemon:
        return {"running": False, "enabled": False, "message": "KAIROS not enabled"}
    return daemon.get_status()


@router.get("/observations")
async def get_observations(
    severity: Optional[str] = Query(None, description="Filter: info, warning, critical"),
    minutes: int = Query(60, description="Look back N minutes (0 = today's full log)"),
):
    """Get today's KAIROS observations."""
    daemon = get_kairos()
    if not daemon:
        return {"observations": [], "enabled": False}

    from kairos.observation_log import ObservationLog

    log = ObservationLog()

    if minutes > 0:
        obs = log.get_recent(minutes=minutes)
    else:
        obs = log.read_today()

    if severity:
        obs = [o for o in obs if o.get("severity") == severity]

    return {
        "observations": obs,
        "total": len(obs),
        "counts": log.count_by_severity(),
    }


@router.get("/observations/{date_str}")
async def get_observations_by_date(date_str: str):
    """Get observations for a specific date (YYYY-MM-DD)."""
    from kairos.observation_log import ObservationLog

    log = ObservationLog()
    obs = log.read_date(date_str)
    return {"date": date_str, "observations": obs, "total": len(obs)}


@router.get("/watchers")
async def get_watchers():
    """List registered watchers and their hit rates."""
    daemon = get_kairos()
    if not daemon:
        return {"watchers": [], "enabled": False}
    status = daemon.get_status()
    return {"watchers": status.get("watchers", []), "running": status.get("running", False)}


@router.post("/tick")
async def manual_tick():
    """Manually trigger one KAIROS tick (for testing)."""
    daemon = get_kairos()
    if not daemon:
        raise HTTPException(status_code=503, detail="KAIROS not enabled")
    await daemon.tick()
    return {"status": "tick_completed", "tick_count": daemon._tick_count}


@router.get("/dream/{date_str}")
async def get_dream_summary(date_str: str):
    """Get nightly consolidation summary for a specific date."""
    from kairos.dreaming import KairosDreamer
    from kairos.observation_log import ObservationLog

    dreamer = KairosDreamer(observation_log=ObservationLog())
    summary = await dreamer.dream(target_date=date_str)
    return summary


@router.post("/dream")
async def run_dream():
    """Manually trigger nightly consolidation for today."""
    from kairos.dreaming import KairosDreamer
    from kairos.observation_log import ObservationLog

    dreamer = KairosDreamer(observation_log=ObservationLog())
    summary = await dreamer.dream()
    return summary

```
