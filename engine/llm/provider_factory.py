"""
Vertex-aware Anthropic client factory.
=====================================
Centralizes construction of the async Anthropic-family client so the rest of
the engine never has to care whether a Claude call goes to the direct Anthropic
API or to Claude-on-Vertex (Google Cloud). Provider is selected via the existing
``JARVIS_LLM_PROVIDER`` env var:

  - ``"vertex"``     -> ``anthropic.AsyncAnthropicVertex(project_id, region)``.
                        Auth is via Application Default Credentials /
                        ``GOOGLE_APPLICATION_CREDENTIALS`` — NO api_key is used.
  - ``"ollama"``     -> ``None`` (engine uses its local Ollama HTTP path; there
                        is no SDK client object on that route).
  - anything else    -> ``anthropic.AsyncAnthropic(api_key)`` (direct API).

Vertex serves Claude under version-pinned model ids that differ from the direct
API aliases this stack uses internally (e.g. ``claude-sonnet-4-6`` ->
``claude-sonnet-4-5@20250929``). :func:`to_vertex_model_id` translates; the map
is env-overridable so a catalog change is a config edit, not a code change.

Regions: Claude-on-Vertex is region-pinned and (per the Vertex integration plan)
served from ``us-east5`` — DISTINCT from the Gemini region (``us-central1`` in
``services/jarvis_analysis.py``). Keep the two separate.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Literal defaults (NOT os.getenv at import time) so behavior is deterministic
# regardless of when the process env was populated, and so unit tests can
# clear the env without inheriting an import-time snapshot.
DEFAULT_VERTEX_PROJECT = "jarvis-trading-493009"
DEFAULT_VERTEX_REGION = "us-east5"  # Claude on Vertex; Gemini uses us-central1.

# Direct Anthropic alias -> Vertex version-pinned model id.
# [UNVERIFIED] These are best-known mappings and MUST be confirmed against the
# live Vertex catalog (integration plan Task 1 smoke test) before flipping
# JARVIS_LLM_PROVIDER=vertex in production. Override/extend at runtime with
# JARVIS_VERTEX_MODEL_MAP ("alias=vertex-id,alias2=vertex-id2"). Any model not
# in the map passes through unchanged (see to_vertex_model_id).
DEFAULT_DIRECT_TO_VERTEX: dict[str, str] = {
    "claude-opus-4-7": "claude-opus-4-1@20250805",
    "claude-opus-4-6": "claude-opus-4-1@20250805",
    "claude-sonnet-4-6": "claude-sonnet-4-5@20250929",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5@20251001",
}


def _parse_env_model_map(raw: str) -> dict[str, str]:
    """Parse a 'alias=vertex-id,alias2=vertex-id2' env string into a dict.

    Mirrors the lenient parsing used for OLLAMA_MODEL_PER_AGENT in client.py:
    blank/malformed entries are skipped rather than raising.
    """
    out: dict[str, str] = {}
    for spec in raw.split(","):
        spec = spec.strip()
        if not spec or "=" not in spec:
            continue
        alias, vertex_id = spec.split("=", 1)
        alias = alias.strip()
        vertex_id = vertex_id.strip()
        if alias and vertex_id:
            out[alias] = vertex_id
    return out


def get_vertex_project() -> str:
    """Resolve the Vertex project id (env-first, literal default last)."""
    return (
        os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or DEFAULT_VERTEX_PROJECT
    ).strip()


def get_vertex_region() -> str:
    """Resolve the Claude-on-Vertex region (env-first, literal default last)."""
    return (os.getenv("ANTHROPIC_VERTEX_REGION") or DEFAULT_VERTEX_REGION).strip()


def to_vertex_model_id(model: str) -> str:
    """Translate a direct Anthropic model alias to its Vertex model id.

    Resolution order: ``JARVIS_VERTEX_MODEL_MAP`` env override -> built-in
    default map -> passthrough (return input unchanged). Passthrough is
    deliberate: a model we have no mapping for is sent to Vertex verbatim, which
    surfaces an explicit Vertex 404 instead of silently substituting the wrong
    model.
    """
    if not model:
        return model
    env_raw = os.getenv("JARVIS_VERTEX_MODEL_MAP", "").strip()
    if env_raw:
        env_map = _parse_env_model_map(env_raw)
        if model in env_map:
            return env_map[model]
    return DEFAULT_DIRECT_TO_VERTEX.get(model, model)


def resolve_provider(provider: Optional[str] = None) -> str:
    """Normalize the active provider string (explicit arg wins over env)."""
    if provider is not None:
        return provider.strip().lower()
    return os.getenv("JARVIS_LLM_PROVIDER", "ollama").strip().lower()


def is_vertex_enabled(provider: Optional[str] = None) -> bool:
    """True when the active provider routes Claude through Vertex AI."""
    return resolve_provider(provider) == "vertex"


def get_anthropic_client(api_key: str = "", provider: Optional[str] = None):
    """Construct the async Anthropic-family client for the active provider.

    Args:
        api_key: Anthropic API key — used ONLY on the direct path. Ignored for
            the vertex path (which authenticates via ADC) and the ollama path.
        provider: Optional explicit provider override; defaults to the
            ``JARVIS_LLM_PROVIDER`` env var.

    Returns:
        ``AsyncAnthropicVertex`` (vertex), ``AsyncAnthropic`` (direct), or
        ``None`` (ollama — the engine handles that route without an SDK client).
    """
    import anthropic

    prov = resolve_provider(provider)
    if prov == "ollama":
        return None
    if prov == "vertex":
        project = get_vertex_project()
        region = get_vertex_region()
        logger.info(
            "llm_provider_vertex_client_constructed",
            extra={"project": project, "region": region},
        )
        return anthropic.AsyncAnthropicVertex(project_id=project, region=region)
    return anthropic.AsyncAnthropic(api_key=api_key)
