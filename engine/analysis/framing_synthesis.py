"""
Narrative synthesis for the automated morning framing brief — the one genuinely
new LLM call in this feature. Everything else (data gathering, level math, Corey
extraction) already had a headless equivalent; the AMT Cues / Game Theory /
Scenario Map prose has only ever been produced by a live Claude Code turn
reading ``.claude/skills/market-framing-brief/SKILL.md``. This module is that
same synthesis step as one scripted API call.

Mirrors ``engine/analysis/jarvis_read.py``'s shape: pure ``build_prompt``/
``parse_brief`` (independently unit-testable, no network) plus an async
``generate_framing_brief`` that routes through a JarvisLLMClient when supplied,
else a direct Anthropic POST, and NEVER raises — any failure returns an honest
fallback stub rather than posting nothing or a garbled brief.

Template sourcing: the Output template / Bias rules / Hard rules text is parsed
directly out of SKILL.md at runtime (not forked into a separate file) so the
human-invoked skill and this script share exactly one authoritative copy. See
``_extract_skill_sections`` — the required-header guard test in
``engine/tests/test_morning_framing_brief.py`` fails loudly if SKILL.md is ever
reformatted in a way that breaks this extraction.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2500

_SKILL_MD_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".claude"
    / "skills"
    / "market-framing-brief"
    / "SKILL.md"
)

# Section headers as they literally appear in SKILL.md today. If a future edit
# renames these, `_extract_skill_sections` raises — caught by the guard test,
# not silently mis-parsed.
_SECTION_HEADERS = {
    "output_template": re.compile(r"^# Output template\b", re.MULTILINE),
    "bias_rules": re.compile(r"^# Bias rules\b", re.MULTILINE),
    "hard_rules": re.compile(r"^# Hard rules\b", re.MULTILINE),
}
_ANY_H1 = re.compile(r"^# ", re.MULTILINE)

# Headers the synthesized brief must contain to be considered well-formed.
# Matches the Output template in SKILL.md — a missing one means the model
# drifted from the required structure, and the brief should be rejected
# rather than posted.
_REQUIRED_OUTPUT_HEADERS = (
    "Level confidence:",
    "Structural Levels",
    "Scenario Map",
    "Caveats:",
)

_FRAMING_INSTRUCTION = (
    "You are generating a Corey-style Auction Market Theory morning framing "
    "brief for ES + NQ, for an automated/unattended run — no human is reviewing "
    "this before it posts. Follow the Output template below VERBATIM in "
    "structure (same section headers, same order). Every section's content is "
    "open-ended synthesis over the JSON context you're given, not a fill-in-the-"
    "blank exercise — but you must never invent a price level, session date, or "
    "fact that is not present in that context. If a data source was unavailable, "
    "say so plainly in the Caveats line rather than inventing a level to fill "
    "the gap. If `corey_yesterday` is present and usable (data_quality != "
    "'none'), open the AMT Cues or Overview section by noting whether today's "
    "data confirms, extends, or invalidates yesterday's stated bias."
)


def _extract_skill_sections(skill_md_text: str) -> dict[str, str]:
    """Pure: split SKILL.md into the three named sections by their `# ` header.
    Each section runs from its header to the next top-level `# ` header (or EOF).
    Raises ValueError if any required header is missing — this is the
    intentional "brittleness", closed by a guard unit test, not a silent
    fallback (a silently-empty rules section would let the model freelance).
    """
    all_headers = [(m.start(), m.group()) for m in _ANY_H1.finditer(skill_md_text)]
    if not all_headers:
        raise ValueError("SKILL.md has no top-level '# ' headers at all")

    sections: dict[str, str] = {}
    for key, pattern in _SECTION_HEADERS.items():
        match = pattern.search(skill_md_text)
        if not match:
            raise ValueError(f"SKILL.md missing expected section header for '{key}'")
        start = match.start()
        # Find the next top-level header strictly after this one.
        end = len(skill_md_text)
        for pos, _ in all_headers:
            if pos > start:
                end = pos
                break
        sections[key] = skill_md_text[start:end].strip()
    return sections


def _load_skill_sections(skill_md_path: Optional[Path] = None) -> dict[str, str]:
    path = skill_md_path or _SKILL_MD_PATH
    text = path.read_text(encoding="utf-8")
    return _extract_skill_sections(text)


def build_system_prompt(skill_md_path: Optional[Path] = None) -> str:
    """Pure/testable: assemble the system prompt from SKILL.md's authoritative
    template + rules text plus the automation-specific framing instruction."""
    sections = _load_skill_sections(skill_md_path)
    return "\n\n".join(
        [
            _FRAMING_INSTRUCTION,
            sections["output_template"],
            sections["bias_rules"],
            sections["hard_rules"],
        ]
    )


def build_prompt(context: dict[str, Any]) -> str:
    """Pure/testable: the user-message content — just the assembled JSON
    context, since all the instructions live in the system prompt."""
    return (
        "Context for today's brief (JSON):\n"
        f"{json.dumps(context, indent=2, default=str)}\n\n"
        "Write the brief now, following the Output template structure exactly."
    )


def parse_brief(raw: str) -> str:
    """Pure/testable: strip code fences, validate required section headers are
    present. Raises ValueError on malformed output — the caller must NOT post
    a brief that fails this check."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("markdown"):
            text = text[len("markdown") :]
        text = text.strip()

    if not text:
        raise ValueError("empty brief")

    missing = [h for h in _REQUIRED_OUTPUT_HEADERS if h not in text]
    if missing:
        raise ValueError(f"brief missing required section(s): {missing}")

    return text


def _fallback_brief(reason: str) -> dict[str, Any]:
    return {
        "markdown": (
            f"**Morning framing brief generation failed — see logs.**\n\n"
            f"Reason: {reason}\n\n"
            "No brief was posted this session. This is an honest gap, not a "
            "silently-stale or fabricated read."
        ),
        "data_quality": "degraded",
        "model_used": "none",
    }


async def generate_framing_brief(
    context: dict[str, Any],
    *,
    llm_client: Optional[object] = None,
    api_key: Optional[str] = None,
    skill_md_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Generate the framing brief. Always returns a dict; NEVER raises.

    Mirrors ``jarvis_read.generate_read``'s has_client / direct-POST fallback,
    with Sonnet instead of Haiku — this is open-ended multi-section narrative
    synthesis (AMT judgment, scenario ranking), a materially bigger task than
    the closed-schema JSON extraction Haiku handles in
    ``corey_session_bias_report.py``.
    """
    import os

    key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
    has_client = llm_client is not None and hasattr(llm_client, "call")
    if not key and not has_client:
        return _fallback_brief("LLM unavailable (no API key, no client)")

    try:
        system = build_system_prompt(skill_md_path)
    except Exception as exc:
        logger.error("SKILL.md template extraction failed: %s", exc)
        return _fallback_brief(f"template extraction failed: {exc}")

    prompt = build_prompt(context)

    try:
        if has_client:
            result = await llm_client.call(
                model=MODEL,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                agent_name="morning_framing_brief",
            )
            if not getattr(result, "success", False):
                raise RuntimeError(f"framing brief LLM call failed: {getattr(result, 'error', '?')}")
            raw = (result.content or "").strip()
            model_used = getattr(result, "model", MODEL)
        else:
            import httpx  # type: ignore[import-untyped]

            try:
                import certifi  # type: ignore[import-untyped]

                verify: Any = certifi.where()
            except Exception:  # pragma: no cover - defensive
                verify = True

            async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "max_tokens": MAX_TOKENS,
                        "system": system,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["content"][0]["text"].strip()
                model_used = MODEL

        markdown = parse_brief(raw)
        return {"markdown": markdown, "data_quality": "ok", "model_used": model_used}
    except Exception as exc:
        logger.warning("Framing brief generation degraded to fallback: %s", exc)
        return _fallback_brief(str(exc))
