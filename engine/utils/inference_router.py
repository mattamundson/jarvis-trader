"""
Hybrid inference router: Local Ollama (primary) + Cloud Anthropic (fallback)
Routes tasks based on latency/cost requirements, with automatic failover.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Optional

import httpx

try:
    from engine.config.inference import (
        INFERENCE_CONFIG,
        TASK_ROUTING,
        InferenceProvider,
        get_provider_for_task,
    )
except ModuleNotFoundError:
    import importlib.util
    from pathlib import Path

    _config_path = Path(__file__).resolve().parents[1] / "config" / "inference.py"
    _spec = importlib.util.spec_from_file_location("jarvis_inference_config", _config_path)
    if _spec is None or _spec.loader is None:
        raise
    _inference_config = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_inference_config)

    INFERENCE_CONFIG = _inference_config.INFERENCE_CONFIG
    TASK_ROUTING = _inference_config.TASK_ROUTING
    InferenceProvider = _inference_config.InferenceProvider
    get_provider_for_task = _inference_config.get_provider_for_task

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(self):
        self.host = INFERENCE_CONFIG["ollama"].host
        self.model = INFERENCE_CONFIG["ollama"].model
        self.timeout = INFERENCE_CONFIG["ollama"].timeout_seconds
        self.retry_attempts = INFERENCE_CONFIG["ollama"].retry_attempts
        self.num_ctx = INFERENCE_CONFIG["ollama"].num_ctx
        self.num_predict = INFERENCE_CONFIG["ollama"].num_predict
        self.temperature = INFERENCE_CONFIG["ollama"].temperature

    async def health_check(self) -> bool:
        """Check if Ollama service is running."""
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.host}/api/tags")
                return bool(response.status_code == 200)
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    async def generate(self, prompt: str) -> Optional[str]:
        """Generate response using Ollama."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
                "temperature": self.temperature,
            },
        }

        for attempt in range(self.retry_attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.host}/api/generate",
                        json=payload,
                    )
                    response.raise_for_status()
                    result: str = response.json().get("response", "")
                    logger.debug(f"Ollama generated {len(result)} chars")
                    return result
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < self.retry_attempts - 1:
                    logger.debug(f"Ollama attempt {attempt+1} failed, retrying...")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"Ollama failed after {self.retry_attempts} attempts: {e}")
                    return None
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                return None
        return None


class InferenceRouter:
    """
    Routes inference tasks to local Ollama or cloud Anthropic.
    Ollama for background tasks (cheap, 3-5s latency okay)
    Anthropic for interactive tasks (fast, <1s required)
    """

    def __init__(self, anthropic_client=None):
        self.ollama = OllamaClient()
        self.provider = os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()
        self.anthropic_client = None if self.provider == "ollama" else anthropic_client
        self.metrics: Dict[str, list] = {}
        self._instance_id = id(self)

    async def test_connection(self) -> dict:
        """Test both providers and return status."""
        ollama_available = await self.ollama.health_check()
        return {
            "ollama": {
                "available": ollama_available,
                "host": self.ollama.host,
                "model": self.ollama.model,
            },
            "anthropic": {
                "available": self.provider != "ollama" and self.anthropic_client is not None,
                "model": None if self.provider == "ollama" else INFERENCE_CONFIG["anthropic"].model,
            },
            "router_id": self._instance_id,
        }

    async def route_task(
        self,
        task_name: str,
        prompt: str,
        force_provider: Optional[InferenceProvider] = None,
    ) -> str:
        """
        Route task to primary provider, fallback on failure.

        Args:
            task_name: Name of the task (e.g., "morning_briefing")
            prompt: The prompt to send
            force_provider: Override routing config for this call

        Returns:
            Generated response text
        """
        start_time = time.time()
        provider = force_provider or get_provider_for_task(task_name)
        if self.provider == "ollama":
            provider = InferenceProvider.OLLAMA
        elif provider != InferenceProvider.OLLAMA and not INFERENCE_CONFIG.get(
            "anthropic_fallback_enabled", False
        ):
            logger.warning(f"[{task_name}] Anthropic requested but disabled; routing to Ollama")
            provider = InferenceProvider.OLLAMA

        logger.info(f"[{task_name}] Routing to {provider.value}")

        if provider == InferenceProvider.OLLAMA:
            result = await self._call_ollama(prompt)
            latency = time.time() - start_time

            if result is not None:
                self._record_metric(task_name, "ollama", latency)
                logger.info(f"[{task_name}] Ollama OK ({latency:.2f}s)")
                return result
            else:
                if self.provider != "ollama" and INFERENCE_CONFIG.get(
                    "anthropic_fallback_enabled", False
                ):
                    logger.warning(f"[{task_name}] Ollama failed, falling back to Anthropic")
                    result = await self._call_anthropic(prompt)
                    latency = time.time() - start_time
                    self._record_metric(task_name, "anthropic_fallback", latency)
                    logger.info(f"[{task_name}] Anthropic fallback ({latency:.2f}s)")
                    return result or ""

                self._record_metric(task_name, "ollama_failed", latency)
                logger.error(f"[{task_name}] Ollama failed; Anthropic fallback disabled")
                return "Ollama/Hermes is unavailable. Check that Ollama is running and hermes3:latest is installed."
        else:
            # Direct to Anthropic for interactive tasks
            result = await self._call_anthropic(prompt)
            latency = time.time() - start_time
            self._record_metric(task_name, "anthropic", latency)
            logger.info(f"[{task_name}] Anthropic OK ({latency:.2f}s)")
            return result or ""

    async def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama API."""
        return await self.ollama.generate(prompt)

    async def _call_anthropic(self, prompt: str) -> Optional[str]:
        """Call Anthropic API (requires client to be set)."""
        if self.provider == "ollama" or self.anthropic_client is None:
            logger.error("Anthropic client not configured")
            return None

        try:
            # Assumes anthropic_client has a generate() or similar method
            response: str | None = await self.anthropic_client.generate(prompt)
            return response
        except Exception as e:
            logger.error(f"Anthropic error: {e}")
            return None

    def _record_metric(self, task_name: str, provider: str, latency_seconds: float):
        """Record latency metric for monitoring."""
        if task_name not in self.metrics:
            self.metrics[task_name] = []

        self.metrics[task_name].append(
            {
                "provider": provider,
                "latency_ms": latency_seconds * 1000,
                "timestamp": time.time(),
            }
        )

        # Keep only last 100 metrics per task to avoid memory bloat
        if len(self.metrics[task_name]) > 100:
            self.metrics[task_name] = self.metrics[task_name][-100:]

    def get_metrics(self) -> Dict:
        """Get performance metrics summary."""
        summary = {}
        for task_name, records in self.metrics.items():
            if records:
                latencies = [r["latency_ms"] for r in records]
                providers_used = [r["provider"] for r in records]
                summary[task_name] = {
                    "count": len(records),
                    "avg_latency_ms": sum(latencies) / len(latencies),
                    "min_latency_ms": min(latencies),
                    "max_latency_ms": max(latencies),
                    "providers": list(set(providers_used)),
                    "fallback_count": sum(1 for p in providers_used if "fallback" in p),
                }
        return summary


# Global router instance
_router_instance: Optional[InferenceRouter] = None


def get_inference_router(anthropic_client=None) -> InferenceRouter:
    """Get or create the global inference router."""
    global _router_instance
    if _router_instance is None:
        _router_instance = InferenceRouter(anthropic_client=anthropic_client)
    return _router_instance


async def route_task(
    task_name: str,
    prompt: str,
    force_provider: Optional[InferenceProvider] = None,
) -> str:
    """Convenience function to route a task."""
    router = get_inference_router()
    return await router.route_task(task_name, prompt, force_provider)
