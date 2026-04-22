"""
Jarvis quick analysis endpoint.

Provides the canonical FastAPI `/jarvis/analyze` surface for the Gemini-backed
market snapshot flow.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from api.models import JarvisQuickAnalysisRequest, JarvisQuickAnalysisResponse
from services import jarvis_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jarvis", tags=["jarvis"])


def _build_request(symbol: str, period: str) -> JarvisQuickAnalysisRequest:
    try:
        return JarvisQuickAnalysisRequest(symbol=symbol, period=period)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc


async def _run_jarvis_analysis(request: JarvisQuickAnalysisRequest) -> JarvisQuickAnalysisResponse:
    symbol = request.symbol
    period = request.period

    try:
        analysis_text = await run_in_threadpool(jarvis_analysis.analyze_symbol, symbol, period)
    except ImportError as exc:
        logger.warning("[JARVIS] dependency unavailable for %s (%s): %s", symbol, period, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("[JARVIS] analysis rejected for %s (%s): %s", symbol, period, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[JARVIS] analysis failed for %s (%s)", symbol, period)
        raise HTTPException(status_code=500, detail=f"Jarvis analysis failed: {exc}") from exc

    analysis_text = (analysis_text or "").strip()
    if not analysis_text:
        raise HTTPException(status_code=502, detail="Jarvis analysis returned no text")

    return JarvisQuickAnalysisResponse(
        symbol=symbol,
        period=period,
        analysis=analysis_text,
        model=jarvis_analysis.MODEL_NAME,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/analyze", response_model=JarvisQuickAnalysisResponse)
async def analyze_jarvis(symbol: str = "SPY", period: str = "5d"):
    """Analyze a symbol with the quick Gemini-backed Jarvis snapshot."""
    request = _build_request(symbol=symbol, period=period)
    return await _run_jarvis_analysis(request)


@router.post("/analyze", response_model=JarvisQuickAnalysisResponse)
async def analyze_jarvis_body(request: JarvisQuickAnalysisRequest):
    """Analyze a symbol from a typed request body."""
    return await _run_jarvis_analysis(request)
