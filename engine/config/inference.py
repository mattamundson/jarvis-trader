"""
Inference provider configuration for Hermes/Ollama routing.
"""

from dataclasses import dataclass
from enum import Enum


class InferenceProvider(str, Enum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"


@dataclass
class OllamaConfig:
    host: str = "http://127.0.0.1:11434"
    model: str = "hermes3:latest"
    timeout_seconds: int = 120
    retry_attempts: int = 1
    num_ctx: int = 4096
    num_predict: int = 256
    temperature: float = 0.2


@dataclass
class AnthropicConfig:
    timeout_seconds: int = 5
    model: str = "claude-3-5-sonnet-20241022"


INFERENCE_CONFIG = {
    "primary_provider": InferenceProvider.OLLAMA,
    "ollama": OllamaConfig(),
    "anthropic": AnthropicConfig(),
    "anthropic_fallback_enabled": False,
}

# Task-specific routing: keep Hermes/Ollama as the sole inference backend.
TASK_ROUTING = {
    "morning_briefing": InferenceProvider.OLLAMA,
    "hourly_check": InferenceProvider.OLLAMA,
    "eod_analysis": InferenceProvider.OLLAMA,
    "trade_decision_logging": InferenceProvider.OLLAMA,
    "economic_calendar": InferenceProvider.OLLAMA,
    "signal_analysis": InferenceProvider.OLLAMA,
    "research": InferenceProvider.OLLAMA,
    "user_query": InferenceProvider.OLLAMA,
    "critical_alert": InferenceProvider.OLLAMA,
    "trading_decision": InferenceProvider.OLLAMA,
    "risk_assessment": InferenceProvider.OLLAMA,
    "default": InferenceProvider.OLLAMA,
}


def get_provider_for_task(task_name: str) -> InferenceProvider:
    """Get the configured provider for a task."""
    return TASK_ROUTING.get(task_name, TASK_ROUTING["default"])


