"""
JARVIS TRADER — Admin Feature-Flags Router
==========================================
Runtime toggle for analyst-stub feature flags (ENABLE_KRONOS, ENABLE_RESEARCH_AGENT).

SAFETY NOTICE
-------------
This endpoint controls flags that gate trading decisions. The two flags managed
here are *analyst stub* gates only — they enable/disable stub classifiers that
emit neutral/zero-confidence signals. They do NOT expose risk parameters,
position-sizing limits, kill-switch state, or any live-trading toggle.

The following are explicitly OUT OF SCOPE for this endpoint and must never be
added here:
  - LIVE_TRADING_ENABLED
  - REQUIRE_HUMAN_APPROVAL
  - MAX_DAILY_LOSS_PCT / MAX_DRAWDOWN_PCT
  - Any field in engine/config.py or engine/risk/

Auth
----
All /admin/* paths are protected by the global APIKeyMiddleware
(engine/middleware/api_key_middleware.py). The middleware runs before any route
handler and returns 401 for missing/invalid X-API-Key headers. No additional
per-route Depends() is needed here.

Runtime-flag mechanics
----------------------
``is_kronos_enabled()`` and ``is_research_agent_enabled()`` both call
``os.environ.get(...)`` on every invocation — they do NOT cache the value at
import time. Setting os.environ via this endpoint therefore takes effect
immediately for any subsequent helper call.

HOWEVER: ``engine/agents/pipeline.py`` initialises ``self._kronos`` once at
``TradingPipeline.__init__`` time (line ~482). Toggling ENABLE_KRONOS via this
endpoint will NOT retro-actively attach or detach the KronosClassifier from a
running pipeline instance. A full engine restart is required to change the
active pipeline's Kronos wiring. The flag change IS reflected immediately in:
  - future ``is_kronos_enabled()`` calls
  - new TradingPipeline instances (e.g. created by a background task)
  - ``GET /admin/feature-flags`` reads
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from agents.kronos_classifier import is_kronos_enabled
from agents.research_agent import is_research_agent_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Env-var names (single source of truth in this router)
# ---------------------------------------------------------------------------

_KRONOS_FLAG = "ENABLE_KRONOS"
_RESEARCH_FLAG = "ENABLE_RESEARCH_AGENT"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FeatureFlagsResponse(BaseModel):
    """Current state of the two analyst-stub feature flags."""

    enable_kronos: bool
    enable_research_agent: bool


class FeatureFlagsUpdateRequest(BaseModel):
    """
    Partial-update payload for POST /admin/feature-flags.

    Both fields are optional — omit a field to leave its flag unchanged.
    Send ``true`` to enable, ``false`` to disable.
    """

    enable_kronos: Optional[bool] = None
    enable_research_agent: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_flags() -> FeatureFlagsResponse:
    """Read current flag state directly from os.environ (never cached)."""
    return FeatureFlagsResponse(
        enable_kronos=is_kronos_enabled(),
        enable_research_agent=is_research_agent_enabled(),
    )


def _apply_flag(env_var: str, value: bool) -> None:
    """Write flag to os.environ as the canonical '1' / '0' string."""
    os.environ[env_var] = "1" if value else "0"
    logger.info(
        "Feature flag %s set to %r (os.environ[%r]='%s')",
        env_var,
        value,
        env_var,
        os.environ[env_var],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="Read current analyst-stub feature flag state",
)
async def get_feature_flags() -> FeatureFlagsResponse:
    """
    Return the current runtime state of the two analyst-stub feature flags.

    Values are read fresh from os.environ on every call — no caching.
    This endpoint is safe to poll (it makes no state changes).

    Returns
    -------
    enable_kronos
        True when ``ENABLE_KRONOS=1`` is set in the process environment.
    enable_research_agent
        True when ``ENABLE_RESEARCH_AGENT=1`` is set in the process environment.
    """
    return _read_flags()


@router.post(
    "/feature-flags",
    response_model=FeatureFlagsResponse,
    summary="Toggle analyst-stub feature flags at runtime",
)
async def post_feature_flags(body: FeatureFlagsUpdateRequest) -> FeatureFlagsResponse:
    """
    Enable or disable ENABLE_KRONOS and/or ENABLE_RESEARCH_AGENT at runtime,
    without requiring an engine restart or .env edit.

    Both fields are optional — a request that omits a field leaves that flag
    unchanged. Sending ``{"enable_kronos": true}`` only modifies Kronos.

    SAFETY CONTRACT
    ---------------
    This endpoint controls analyst *stub* flags only. It does NOT expose
    risk parameters, kill-switch state, or live-trading settings. Those
    invariants are enforced in engine/config.py and engine/risk/ and are
    not reachable from here.

    Side-effect on running pipelines
    ---------------------------------
    ``TradingPipeline.__init__`` reads the flag once at instantiation time.
    Toggling ENABLE_KRONOS will NOT retro-actively change whether the current
    live pipeline instance uses KronosClassifier. The flag change takes effect
    for all future ``is_kronos_enabled()`` calls and any newly-created pipeline
    instance. A full engine restart is required to rewire the active pipeline.

    Parameters
    ----------
    body
        JSON object with optional ``enable_kronos`` and/or
        ``enable_research_agent`` boolean fields.

    Returns
    -------
    FeatureFlagsResponse
        The new state of both flags after the update.
    """
    if body.enable_kronos is not None:
        _apply_flag(_KRONOS_FLAG, body.enable_kronos)

    if body.enable_research_agent is not None:
        _apply_flag(_RESEARCH_FLAG, body.enable_research_agent)

    new_state = _read_flags()
    logger.info(
        "Feature flags after update: kronos=%s research_agent=%s",
        new_state.enable_kronos,
        new_state.enable_research_agent,
    )
    return new_state
