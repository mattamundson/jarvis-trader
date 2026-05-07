"""Observability router — Tracks F/G/H runtime state.

Registration snippet for engine/main.py:
    from routers.observability_router import router as observability_router
    app.include_router(observability_router)
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/obs", tags=["observability"])

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_key(key: str = Depends(_api_key_header)):
    expected = os.getenv("JARVIS_API_KEY") or os.getenv("API_KEY")
    if expected and key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


@router.get("/advisor/status")
def advisor_status(_=Depends(_require_key)):  # noqa: B008 — FastAPI dependency-injection idiom
    try:
        from agents.advisor_client import AdvisorClient
        client = AdvisorClient()
        return {
            "available": getattr(client, "llm", None) is not None,
            "llm_constructed": getattr(client, "llm", None) is not None,
            "api_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
            "model": "claude-opus-4-7",
            "tiebreak_tolerance": 0.05,
            "low_confidence_threshold": 0.5,
        }
    except Exception as e:
        logger.warning("advisor_status error: %s", e)
        return {"available": False, "error": str(e)}


@router.get("/ic-ensemble/describe")
def ic_ensemble_describe(_=Depends(_require_key)):  # noqa: B008 — FastAPI dependency-injection idiom
    try:
        from analytics.ic_ensemble import ICWeightedEnsemble
        ensemble = ICWeightedEnsemble()
        if hasattr(ensemble, "describe"):
            return ensemble.describe()
        return {"agents": getattr(ensemble, "agents", []), "warning": "describe() not implemented"}
    except Exception as e:
        logger.warning("ic_ensemble_describe error: %s", e)
        return {"available": False, "error": str(e)}


@router.get("/token-proxy/metrics")
def token_proxy_metrics(_=Depends(_require_key)):  # noqa: B008 — FastAPI dependency-injection idiom
    try:
        from utils.token_proxy import get_token_proxy
        proxy = get_token_proxy()
        m = proxy.metrics
        if is_dataclass(m):
            return asdict(m)
        if hasattr(m, "as_dict"):
            return m.as_dict()
        return {k: getattr(m, k) for k in dir(m) if not k.startswith("_") and not callable(getattr(m, k))}
    except Exception as e:
        logger.warning("token_proxy_metrics error: %s", e)
        return {"available": False, "error": str(e)}
