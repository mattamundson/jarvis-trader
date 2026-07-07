"""LLM-classifies Candidates into ClassifiedUpgrade via JarvisLLMClient.

Single LLM turn per candidate. JSON-only output is parsed into the
ClassifiedUpgrade Pydantic v2 model. Classifier errors degrade to
`applicable=False, upgrade_type="none"` rather than raising — the
backlog should never break on a malformed model reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import certifi

# Anaconda leaves SSL_CERT_FILE pointing at a path that doesn't exist on this
# box. Force it to certifi's bundle so httpx can establish TLS connections for
# the Anthropic AsyncAnthropic client constructor. Matches the pattern in
# engine/discord/deep_analyzer/handlers/*.py. MUST run before importing
# JarvisLLMClient because the import path eagerly constructs httpx clients.
if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from llm.client import JarvisLLMClient  # noqa: E402

from .models import Candidate, ClassifiedUpgrade

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
AGENT_NAME = "hermes-upgrade-classifier"

SYSTEM_PROMPT = """You are triaging Discord bookmarks for Hermes Agent applicability.

Hermes Agent (Nous Research) is Amo's autonomous-agent infrastructure with:
- 4 profiles: default (hermes-gateway.service system unit) + programmer + researcher + designer (user services)
- WSL Ubuntu install at /home/mattm/.hermes/
- Skills hub (91 ship + 520+ community)
- GEPA self-evolution at /home/mattm/Code/hermes-agent-self-evolution/
- Telegram bots per profile
- Discord MCP bridge (jarvis-discord)
- Gemini fallback config

Your job: for ONE bookmark summary, decide if it describes a Hermes-applicable upgrade and classify it.

Output ONLY a JSON object with these fields (no markdown, no prose, no explanation):
{
  "applicable": true|false,
  "upgrade_type": "skill"|"mcp_server"|"cron_pattern"|"soul_template"|"library"|"config_improvement"|"gepa_target"|"none",
  "title": "<headline <= 70 chars>",
  "rationale": "<1-2 sentence why-worth-doing>",
  "implementation_steps": ["<concrete step 1>", "<step 2>", "..."],
  "leverage_rank": 1-5,
  "risk": "low"|"med"|"high",
  "dependencies": ["<prereq 1>", ...],
  "estimated_cost_usd": <number, 0 if free>,
  "extracted_content": "<key quote/snippet from the source>",
  "notes": "<caveats, amo-only steps, etc.>"
}

Guidelines:
- "applicable": true only if the bookmark concretely points to a Hermes-relevant artifact (a specific skill repo, MCP server, cron pattern, library, etc.). "Discusses LLMs in general" = false.
- "leverage_rank" 5 = transforms Amo's daily Hermes use; 1 = marginal nice-to-have.
- "risk": low=adds a skill or doc; med=touches config or needs an API key; high=changes safety surface, requires migration, or could break running services.
- "estimated_cost_usd": ongoing monthly or one-shot. 0 for free skills/scripts.
- "implementation_steps" must be CONCRETE (commands, file paths, env vars), not vague advice.

CONCRETENESS GATE — leverage_rank cap based on actionability:
A bookmark only qualifies for leverage_rank >= 4 if implementation_steps contain AT LEAST ONE of:
  (a) a github.com or gitlab.com URL pointing at a specific repo
  (b) a `hermes skills install <slug-or-url>` token
  (c) a `pip install <package>` or `uv pip install <package>` token
  (d) a fenced markdown block (```...```) for SOUL.md / skill template / persona content
  (e) a `hermes cron add ...` invocation
  (f) a specific config key + value (e.g., `model.provider: anthropic`)
  (g) a Hermes / Claude Code MCP server name + command + args spec

If implementation_steps are NARRATIVE only ("Review the X article and identify
patterns", "Audit Y", "Consider integrating Z") with no concrete (a)-(g) token,
CAP leverage_rank at 3 MAX, even if the underlying idea is brilliant. The applier
can't execute narratives — those become tier_3 / human-curation items rather than
falsely-tier_1 batch-apply candidates.

Set upgrade_type="none" if the bookmark is purely informational with no upgrade
intent (commentary, news, opinion). Don't stretch to fit a type.
"""


def _strip_code_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrappers around a JSON blob."""
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    # Remove leading triple-backticks (possibly with language tag) and trailing triple-backticks
    text = text.lstrip("`")
    # Optional language identifier on first line
    if text.lower().startswith("json"):
        text = text[4:]
    text = text.lstrip("\r\n")
    if text.endswith("```"):
        text = text[:-3]
    return text.strip("`").strip()


def _build_user_prompt(candidate: Candidate) -> str:
    return (
        f"Bookmark URL: {candidate.url}\n"
        f"Source kind: {candidate.source_kind}\n"
        f"Topics: {', '.join(candidate.topics)}\n"
        f"Has action item: {candidate.has_action_item}\n\n"
        f"Summary:\n{candidate.summary}\n\n"
        f"Existing structured JSON (for additional context):\n"
        f"{candidate.structured_json[:1500]}\n\n"
        "Classify per the system instructions. Output ONLY the JSON object."
    )


def _coerce_payload(data: Any, candidate: Candidate) -> ClassifiedUpgrade:
    """Build a ClassifiedUpgrade from a parsed dict, defending against bad keys."""
    if not isinstance(data, dict):
        raise ValueError(f"classifier reply not a dict: {type(data).__name__}")
    # Drop unknown keys before instantiating to keep Pydantic happy + defensive
    allowed = set(ClassifiedUpgrade.model_fields.keys())
    kept = {k: v for k, v in data.items() if k in allowed and k != "bookmark_id"}
    return ClassifiedUpgrade(bookmark_id=candidate.bookmark_id, **kept)


def _build_default_client() -> JarvisLLMClient:
    """Construct a JarvisLLMClient forced to the anthropic provider.

    The engine-wide default is `ollama` (cost). The classifier needs cloud
    routing so we temporarily override the env var, mirroring the pattern in
    deep_analyzer/llm.py.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    db_path = os.getenv("JARVIS_LLM_COST_DB", "data/llm_costs.db")
    prev = os.environ.get("JARVIS_LLM_PROVIDER")
    os.environ["JARVIS_LLM_PROVIDER"] = "anthropic"
    try:
        return JarvisLLMClient(api_key=api_key, db_path=db_path)
    finally:
        if prev is None:
            os.environ.pop("JARVIS_LLM_PROVIDER", None)
        else:
            os.environ["JARVIS_LLM_PROVIDER"] = prev


async def classify_one(client: JarvisLLMClient, candidate: Candidate) -> ClassifiedUpgrade:
    """Run one LLM classification.

    Returns a ClassifiedUpgrade. On any error (network, JSON parse, etc.)
    returns ClassifiedUpgrade(applicable=False, upgrade_type="none", ...)
    so the batch pipeline never raises on a single failure.
    """
    user_prompt = _build_user_prompt(candidate)
    try:
        result = await client.call(
            model=DEFAULT_MODEL,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=800,
            agent_name=AGENT_NAME,
            temperature=0.1,
            tier="fast",
            compact=False,
        )
        if not getattr(result, "success", True):
            raise RuntimeError(f"LLM call unsuccessful: {getattr(result, 'error', 'unknown')}")
        text = _strip_code_fences(getattr(result, "content", "") or "")
        if not text:
            raise ValueError("empty classifier reply")
        data = json.loads(text)
        return _coerce_payload(data, candidate)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(
            "hermes_upgrade.classifier: classify_one failed for %s: %s",
            candidate.bookmark_id,
            e,
        )
        return ClassifiedUpgrade(
            bookmark_id=candidate.bookmark_id,
            applicable=False,
            upgrade_type="none",
            title="<classifier error>",
            rationale=f"classifier failed: {e}",
        )


async def classify_batch(
    candidates: list[Candidate],
    *,
    concurrency: int = 5,
    client: JarvisLLMClient | None = None,
) -> list[ClassifiedUpgrade]:
    """Classify many candidates with bounded concurrency.

    Order of returned list matches the input list.
    """
    if not candidates:
        return []
    own_client = client or _build_default_client()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(c: Candidate) -> ClassifiedUpgrade:
        async with sem:
            return await classify_one(own_client, c)

    return await asyncio.gather(*(_one(c) for c in candidates))
