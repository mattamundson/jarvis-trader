"""
JARVIS's Read — a labeled, subjective morning opinion for the brief.

This is JARVIS's *own* discretionary lean for the session: a directional bias, a
conviction score, the levels it is committing to, and a short human-style
narrative ("here's my feel and why"). It is grounded in the deterministic levels
(Phase A) and the overnight regime, but it is an OPINION, not a fact and not a
trade signal.

HARD SAFETY BOUNDARY: nothing in this module is imported by engine/risk/ or used
to construct an OrderRequest. The hardcoded safety layer never consumes a read.
It is display/journal only and is graded against outcomes (Phase D) so the
opinion builds an honest track record over time.

Mirrors engine/discord/commentary_processor.py::_llm_extract: route through a
JarvisLLMClient when one is supplied (provider-fallback chain), else a direct
Anthropic POST; on ANY failure return an honest "no read" stub rather than
fabricating a call.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 700

_VALID_BIAS = {"bullish", "bearish", "neutral"}
# The Read is anchored/scored on the broad equity index (ES via the MES micro).
ANCHOR_SYMBOL = "MES"

_SYSTEM = (
    "You are JARVIS, a futures trading analyst writing your own honest "
    "discretionary read for the upcoming session. This is a labeled OPINION for "
    "a human operator — not financial advice, not a guaranteed forecast, and not "
    "an automated trade signal. Own your lean, be specific, and assign honest "
    "conviction (it is fine to be low-conviction). Ground every claim in the "
    "levels and regime data provided. Never invent price levels."
)

_PROMPT_TEMPLATE = """\
Date: {date}

Deterministic structural levels (computed from real bars) and overnight regime:
{context}

Give your discretionary read for the session. Respond with JSON in EXACTLY this format:
{{
  "bias": "bullish|bearish|neutral",
  "conviction": 0.0-1.0,
  "key_levels_committed": [list of price floats you are watching],
  "scenario_if_above": "what you expect if price accepts above the pivot/trigger",
  "scenario_if_below": "what you expect if price stays/breaks below",
  "narrative": "<=120 words: your honest feel for the day and why"
}}
Only output the JSON object."""


def _clamp(x: Any, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def _fallback_read(reason: str) -> dict[str, Any]:
    """Honest 'no read' stub. data_quality='none' means UNKNOWN, not neutral signal."""
    return {
        "bias": "neutral",
        "conviction": 0.0,
        "key_levels_committed": [],
        "scenario_if_above": "",
        "scenario_if_below": "",
        "narrative": f"No read available ({reason}).",
        "data_quality": "none",
    }


def _levels_summary(levels_map: dict[str, Any]) -> str:
    """Render a compact per-symbol context block for the prompt."""
    lines: list[str] = []
    for sym, lv in levels_map.items():
        if lv is None:
            continue
        d = lv.to_dict() if hasattr(lv, "to_dict") else dict(lv)
        up = ", ".join(f"{v:g}" for v in (d.get("targets_up") or []))
        dn = ", ".join(f"{v:g}" for v in (d.get("targets_down") or []))
        lines.append(
            f"- {sym}: prior_close={d.get('prior_close')} pivot={d.get('pivot')} "
            f"R1={d.get('r1')} S1={d.get('s1')} ATR={d.get('atr')} "
            f"targets_up=[{up}] targets_down=[{dn}]"
        )
    return "\n".join(lines) if lines else "(no levels available)"


def _regime_summary(regime_map: dict[str, dict] | None) -> str:
    if not regime_map:
        return ""
    lines = []
    for sym, r in regime_map.items():
        lines.append(
            f"- {sym}: regime={r.get('regime')} bias={r.get('bias')} "
            f"close={r.get('close')} sma_fast={r.get('sma_fast')} sma_slow={r.get('sma_slow')}"
        )
    return "\n".join(lines)


def build_prompt(
    date_str: str,
    levels_map: dict[str, Any],
    regime_map: dict[str, dict] | None,
    calibration_hint: str = "",
) -> str:
    """Pure: assemble the LLM prompt from levels + regime. Unit-testable.

    ``calibration_hint`` (from the Phase E calibrator) is folded in so the Read
    learns from its own graded track record.
    """
    context = _levels_summary(levels_map)
    regime = _regime_summary(regime_map)
    if regime:
        context = f"{context}\n\nRegime:\n{regime}"
    if calibration_hint:
        context = f"{context}\n\nCalibration feedback on your past reads:\n{calibration_hint}"
    return _PROMPT_TEMPLATE.format(date=date_str, context=context)


def parse_read(raw: str) -> dict[str, Any]:
    """Pure: parse + validate the LLM's JSON response. Raises on unrecoverable input.

    Strips markdown code fences (same handling as commentary_processor).
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    obj = json.loads(text)

    bias = str(obj.get("bias", "neutral")).lower()
    if bias not in _VALID_BIAS:
        bias = "neutral"
    levels = []
    for v in obj.get("key_levels_committed") or []:
        try:
            levels.append(round(float(v), 4))
        except (TypeError, ValueError):
            continue
    return {
        "bias": bias,
        "conviction": round(_clamp(obj.get("conviction", 0.0), 0.0, 1.0), 3),
        "key_levels_committed": levels,
        "scenario_if_above": str(obj.get("scenario_if_above", ""))[:500],
        "scenario_if_below": str(obj.get("scenario_if_below", ""))[:500],
        "narrative": str(obj.get("narrative", ""))[:1200],
        "data_quality": "fresh",
    }


async def generate_read(
    date_str: str,
    levels_map: dict[str, Any],
    regime_map: dict[str, dict] | None = None,
    *,
    llm_client: Optional[object] = None,
    api_key: Optional[str] = None,
    calibration_hint: str = "",
    conviction_shrink: float = 1.0,
) -> dict[str, Any]:
    """Generate JARVIS's discretionary read. Always returns a dict (fallback on failure).

    ``calibration_hint`` / ``conviction_shrink`` come from the Phase E calibrator:
    the hint is folded into the prompt, and the shrink factor scales the parsed
    conviction down when the Read has been historically overconfident.
    """
    key = api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
    has_client = llm_client is not None and hasattr(llm_client, "call")
    if not key and not has_client:
        return _fallback_read("LLM unavailable")

    prompt = build_prompt(date_str, levels_map, regime_map, calibration_hint)
    try:
        if has_client:
            result = await llm_client.call(
                model=MODEL,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                agent_name="jarvis_read",
            )
            if not getattr(result, "success", False):
                raise RuntimeError(f"jarvis_read LLM call failed: {getattr(result, 'error', '?')}")
            raw = (result.content or "").strip()
        else:
            import httpx  # type: ignore[import-untyped]

            # Pin the trust store to certifi's bundle. The ambient SSL_CERT_FILE
            # may point at a stale path (e.g. a removed anaconda cacert.pem),
            # which httpx would otherwise honor and fail on. certifi is always a
            # transitive dependency; fall back to httpx's default if unavailable.
            try:
                import certifi  # type: ignore[import-untyped]

                verify: Any = certifi.where()
            except Exception:  # pragma: no cover - defensive
                verify = True

            async with httpx.AsyncClient(timeout=30.0, verify=verify) as client:
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
                        "system": _SYSTEM,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["content"][0]["text"].strip()

        read = parse_read(raw)
        # Apply the calibrator's conviction-shrink (no-op at 1.0).
        try:
            shrink = float(conviction_shrink)
            if 0.0 < shrink < 1.0:
                read["conviction"] = round(read["conviction"] * shrink, 3)
                read["conviction_shrunk"] = True
        except (TypeError, ValueError):
            pass
        return read
    except Exception as exc:
        logger.warning("JARVIS's Read degraded to fallback: %s", exc)
        return _fallback_read("LLM error")
