"""
ThinkScript generation endpoints
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

try:
    from agents.thinkscript_generator import ThinkScriptGeneratorAgent
except ImportError:
    ThinkScriptGeneratorAgent = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["thinkscript"])

# Global references (injected from main.py)
technical_analyst = None


def inject_dependencies(ta=None):
    """Inject dependencies from main.py"""
    global technical_analyst
    if ta is not None:
        technical_analyst = ta


class ThinkScriptRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@router.post("/thinkscript/generate")
async def generate_thinkscript(req: ThinkScriptRequest):
    """Generate ThinkScript code for ThinkorSwim from JARVIS analysis"""
    if ThinkScriptGeneratorAgent is None:
        return {
            "error": "ThinkScript generator unavailable — agents.thinkscript_generator could not be imported"
        }
    gen = ThinkScriptGeneratorAgent(
        llm_client=technical_analyst.llm_client if technical_analyst else None
    )

    # Get technical analysis first
    tech_report = None
    if technical_analyst:
        try:
            tech_report = await technical_analyst.analyze(req.symbol, req.timeframe, req.is_futures)
        except Exception:
            pass

    result = await gen.generate(
        symbol=req.symbol,
        timeframe=req.timeframe,
        technical_report=tech_report,
        script_type="study",
    )

    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "title": result.title,
        "code": result.code,
        "description": result.description,
        "usage_instructions": result.usage_instructions,
        "signals_included": result.signals_included,
        "timestamp": result.timestamp.isoformat(),
    }


# ── Macro Data (FRED) ──────────────────────────────────────────────────────
