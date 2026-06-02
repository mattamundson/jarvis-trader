"""ThinkScript generation and registry router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.thinkscript_generator import ThinkScriptGeneratorAgent
from schemas.thinkscript_registry import ScriptRegistry, ScriptWithDocs
from utils.thinkscript_registry_loader import load_registry, read_doc

router = APIRouter(prefix="", tags=["thinkscript"])

technical_analyst = None


def inject_dependencies(ta=None):
    """Inject global dependencies from main.py"""
    global technical_analyst
    technical_analyst = ta


class ThinkScriptRequest(BaseModel):
    symbol: str
    timeframe: str = "15m"
    is_futures: bool = False


@router.post("/thinkscript/generate")
async def generate_thinkscript(req: ThinkScriptRequest):
    """Generate ThinkScript code for ThinkorSwim from JARVIS analysis"""
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


@router.get("/thinkscript/registry", response_model=ScriptRegistry)
async def get_thinkscript_registry():
    """Return the full catalog of ThinkScript studies wired into JARVIS."""
    try:
        return load_registry()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/thinkscript/registry/{script_id}", response_model=ScriptWithDocs)
async def get_thinkscript_registry_entry(script_id: str):
    """Return a single registry entry plus its full markdown documentation body."""
    try:
        registry = load_registry()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    entry = next((s for s in registry.scripts if s.id == script_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"script_id '{script_id}' not found")
    return ScriptWithDocs(entry=entry, doc_markdown=read_doc(entry.docs))

@router.post("/thinkscript/generate")
async def generate_thinkscript(req: ThinkScriptRequest):
    """Generate ThinkScript code for ThinkorSwim from JARVIS analysis"""
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



@router.get("/thinkscript/registry", response_model=ScriptRegistry)
async def get_thinkscript_registry():
    """Return the full catalog of ThinkScript studies wired into JARVIS."""
    try:
        return load_registry()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))



@router.get("/thinkscript/registry/{script_id}", response_model=ScriptWithDocs)
async def get_thinkscript_registry_entry(script_id: str):
    """Return a single registry entry plus its full markdown documentation body."""
    try:
        registry = load_registry()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    entry = next((s for s in registry.scripts if s.id == script_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"script_id '{script_id}' not found")
    return ScriptWithDocs(entry=entry, doc_markdown=read_doc(entry.docs))


# ── Macro Data (FRED) ──────────────────────────────────────────────────────


