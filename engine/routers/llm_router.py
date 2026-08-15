from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging
import json
from datetime import datetime

# API Key validation function
def validate_api_key(api_key: str = Header(None)):
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    # In production, you would validate against a stored key
    return api_key

"""
JARVIS TRADER — LLM Router (Phase 3.1)
======================================

HTTP API endpoints for LLM functionality.
Replaces the missing llm_router.py with direct client integration.

Endpoints:
- /llm/test (POST) - Test LLM connectivity
- /llm/status (GET) - Get LLM provider status  
- /llm/chat (POST) - Chat completion endpoint
- /llm/stats (GET) - Get usage statistics
"""

from typing import List, Dict, Any, Optional
import logging
import json
from datetime import datetime

# Import the LLM client
from llm.client import JarvisLLMClient, _LLM_PATH_STATE, is_billing_error_active

router = APIRouter()
logger = logging.getLogger("jarvis_trader.llm_router")

# Request/Response models
class TestRequest(BaseModel):
    message: str = "Hello, this is a test message"

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4000

class ChatResponse(BaseModel):
    response: str
    model: str
    tokens_used: int
    timestamp: str

class StatusResponse(BaseModel):
    healthy: bool
    primary_provider: str
    providers_configured: List[str]
    providers_available: int
    primary_healthy: bool
    single_leg_warning: bool
    vertex_failover_count: int
    google_fallback_count: int
    timestamp: str

class StatsResponse(BaseModel):
    total_calls: int
    total_tokens: int
    total_cost: float
    daily_breakdown: List[Dict[str, Any]]
    timestamp: str

# Global client instance (same pattern as other routers)
_llm_client: Optional[JarvisLLMClient] = None

def get_llm_client() -> JarvisLLMClient:
    """Get or create the LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = JarvisLLMClient()
    return _llm_client

@router.post("/llm/test")
async def test_llm_connection(request: TestRequest):
    """
    Test LLM connectivity.
    
    Returns a simple response to verify the LLM is working.
    """
    try:
        client = get_llm_client()

        # Live connectivity probe through the real client API (JarvisLLMClient.call).
        result = await client.call(
            model=client.fast_model,
            system="You are a connectivity test. Reply with a short acknowledgement.",
            messages=[{"role": "user", "content": request.message}],
            max_tokens=64,
            agent_name="llm_router_test",
            temperature=0.1,
        )

        if not result.success:
            raise HTTPException(
                status_code=502,
                detail=f"LLM call failed: {result.error}",
            )

        return {
            "status": "ok",
            "response": result.content,
            "model": result.model,
            "timestamp": datetime.now().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LLMRouter] Test failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"LLM test failed: {str(e)}"
        )

@router.get("/llm/status")
async def get_llm_status():
    """
    Get LLM provider status.
    
    Returns the current status of all configured LLM providers.
    """
    try:
        client = get_llm_client()
        
        # Get current state from the client
        status = {
            "healthy": _LLM_PATH_STATE.get("healthy", False),
            "primary_provider": _LLM_PATH_STATE.get("primary_provider", "unknown"),
            "providers_configured": _LLM_PATH_STATE.get("providers_configured", []),
            "providers_available": len(_LLM_PATH_STATE.get("providers_configured", [])),
            "primary_healthy": _LLM_PATH_STATE.get("primary_healthy", False),
            "single_leg_warning": _LLM_PATH_STATE.get("single_leg_warning", False),
            "vertex_failover_count": _LLM_PATH_STATE.get("vertex_failover_count", 0),
            "google_fallback_count": _LLM_PATH_STATE.get("google_fallback_count", 0),
            "timestamp": datetime.now().isoformat()
        }
        
        return StatusResponse(**status)
        
    except Exception as e:
        logger.error(f"[LLMRouter] Status check failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Status check failed: {str(e)}"
        )

@router.post("/llm/chat")
async def chat_completion(request: ChatRequest):
    """
    Chat completion endpoint.
    
    Standard OpenAI-compatible chat completion endpoint.
    """
    try:
        client = get_llm_client()

        # JarvisLLMClient.call takes the system prompt separately from the
        # conversation, so split any OpenAI-style system messages out of the list.
        system_parts = [
            m.get("content", "") for m in request.messages if m.get("role") == "system"
        ]
        conversation = [m for m in request.messages if m.get("role") != "system"]
        system = (
            "\n".join(p for p in system_parts if p)
            or "You are JARVIS, a helpful trading assistant."
        )

        model = request.model or client.default_model

        result = await client.call(
            model=model,
            system=system,
            messages=conversation,
            max_tokens=request.max_tokens or 1024,
            agent_name="llm_router_chat",
            temperature=request.temperature if request.temperature is not None else 0.7,
        )

        if not result.success:
            raise HTTPException(
                status_code=502,
                detail=f"Chat completion failed: {result.error}",
            )

        return ChatResponse(
            response=result.content,
            model=result.model,
            tokens_used=(result.input_tokens or 0) + (result.output_tokens or 0),
            timestamp=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LLMRouter] Chat completion failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat completion failed: {str(e)}"
        )

@router.get("/llm/stats")
async def get_llm_stats():
    """
    Get LLM usage statistics.
    
    Returns token usage and cost tracking data.
    """
    try:
        client = get_llm_client()

        # Real cost-tracker summary (JarvisLLMClient.get_daily_stats). Top-level
        # keys are total_calls / total_cost_usd / per_model{...}; token totals are
        # derived by summing input+output across per_model.
        stats = await client.get_daily_stats()
        per_model = stats.get("per_model", {}) or {}

        total_tokens = sum(
            (m.get("input_tokens", 0) or 0) + (m.get("output_tokens", 0) or 0)
            for m in per_model.values()
        )
        daily_breakdown = [{"model": name, **metrics} for name, metrics in per_model.items()]

        return StatsResponse(
            total_calls=stats.get("total_calls", 0),
            total_tokens=total_tokens,
            total_cost=stats.get("total_cost_usd", 0.0),
            daily_breakdown=daily_breakdown,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        logger.error(f"[LLMRouter] Stats retrieval failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Stats retrieval failed: {str(e)}"
        )

# Health check endpoint for integration with main health endpoint
@router.get("/llm/health")
async def get_llm_health():
    """
    Health check endpoint for LLM service.
    """
    # Cheap health signal derived from the shared LLM path state — no live API
    # call, so hitting this endpoint on a monitor loop never spends tokens or
    # trips billing limits. The live connectivity probe lives in /llm/test.
    try:
        billing_error = is_billing_error_active()
        healthy = bool(_LLM_PATH_STATE.get("healthy", False)) and not billing_error

        return {
            "status": "healthy" if healthy else "unhealthy",
            "primary_provider": _LLM_PATH_STATE.get("primary_provider", "unknown"),
            "primary_healthy": _LLM_PATH_STATE.get("primary_healthy", False),
            "billing_error": billing_error,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"[LLMRouter] Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.now().isoformat()}


# Simple test endpoint without authentication
@router.get("/llm/test-simple")
async def test_simple():
    return {"status": "ok", "message": "LLM router working without auth"}