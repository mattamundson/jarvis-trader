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
