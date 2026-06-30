"""
JARVIS vs Corey comparison (Phase F) — built now, DORMANT until the feed returns.

When Corey's Discord commentary is flowing, this aligns his session bias and key
levels against JARVIS's Read and (post-close) scores both against the realized
session. While the feed is dry — discord-jarvis get_session_bias returns
data_quality="none" (the current state: the DiscordChatExporter token is expired,
fixed separately via scripts/REFRESH_DISCORD_TOKEN.md) — every entry point
no-ops cleanly: fetch returns None and the brief renders no section.

Reuses engine/discord/commentary_processor.py::CoreyCommentaryProcessor, the same
accessor behind the discord-jarvis MCP get_session_bias tool.

Display/journal only — nothing here is consumed by risk/ or order execution.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BIAS_SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}


def fetch_corey_bias(
    date_str: str,
    db_path: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return Corey's session bias dict for the date, or None when dormant.

    None whenever the feed is dry, the processor can't be built, or extraction
    yields data_quality="none". Never raises — Phase F must stay inert while the
    Corey feed is frozen.
    """
    try:
        import asyncio
        from datetime import date as _date

        from discord.commentary_processor import (
            CoreyCommentaryProcessor,
            build_default_llm_client,
        )
    except ImportError as exc:  # pragma: no cover - defensive
        logger.debug("corey_compare dormant — import failed: %s", exc)
        return None

    try:
        for_date = _date.fromisoformat(date_str)
        proc = CoreyCommentaryProcessor(
            db_path=db_path,
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            llm_client=build_default_llm_client(db_path),
        )
        bias = asyncio.run(proc.get_session_bias(for_date))
        d = bias.to_dict()
        if d.get("data_quality", "none") == "none":
            return None
        return d
    except Exception as exc:  # pragma: no cover - dormant-safe
        logger.debug("corey_compare dormant — fetch failed: %s", exc)
        return None


def _direction_correct(sign: int, actual: dict[str, float] | None) -> Optional[float]:
    if sign == 0 or not actual:
        return None
    move = actual["close"] - actual["open"]
    if move == 0:
        return 0.5
    return 1.0 if (move > 0) == (sign > 0) else 0.0


def _align_levels(
    jarvis_levels: list[float], corey_levels: list[float], tol: float = 5.0
) -> list[dict[str, Any]]:
    """Pair each Corey level with the nearest JARVIS level within ``tol``."""
    pairs: list[dict[str, Any]] = []
    for cl in corey_levels:
        if not jarvis_levels:
            pairs.append({"corey": cl, "jarvis": None, "delta": None})
            continue
        nearest = min(jarvis_levels, key=lambda jl: abs(jl - cl))
        delta = round(nearest - cl, 4)
        pairs.append({"corey": cl, "jarvis": nearest, "delta": delta, "agree": abs(delta) <= tol})
    return pairs


def compare(
    jarvis_read: dict[str, Any] | None,
    corey_bias: dict[str, Any] | None,
    jarvis_levels: list[float] | None = None,
    actual: dict[str, float] | None = None,
) -> Optional[dict[str, Any]]:
    """Compare JARVIS's Read with Corey's bias. Returns None when Corey is dormant. Pure."""
    if not corey_bias:
        return None

    j_bias = str((jarvis_read or {}).get("bias", "neutral")).lower()
    c_bias = str(corey_bias.get("directional_bias", "neutral")).lower()
    j_sign = _BIAS_SIGN.get(j_bias, 0)
    c_sign = _BIAS_SIGN.get(c_bias, 0)

    out: dict[str, Any] = {
        "jarvis_bias": j_bias,
        "corey_bias": c_bias,
        "agree": j_bias == c_bias,
        "corey_conviction": corey_bias.get("conviction"),
        "corey_quote": corey_bias.get("corey_quote", ""),
        "corey_data_quality": corey_bias.get("data_quality"),
        "level_alignment": _align_levels(
            list(jarvis_levels or []), [float(x) for x in (corey_bias.get("key_levels") or [])]
        ),
    }
    if actual:
        out["jarvis_correct"] = _direction_correct(j_sign, actual)
        out["corey_correct"] = _direction_correct(c_sign, actual)
    return out


def render_corey_compare(comparison: dict[str, Any] | None) -> list[str]:
    """Render the '## JARVIS vs Corey' section. Empty list when dormant (no section)."""
    if not comparison:
        return []  # feed dry -> no section at all

    lines: list[str] = []
    lines.append("## JARVIS vs Corey")
    agree = comparison.get("agree")
    flag = "AGREE" if agree else "DIVERGE"
    lines.append(
        f"**{flag}** — JARVIS: {comparison['jarvis_bias'].upper()} | "
        f"Corey: {comparison['corey_bias'].upper()}"
    )
    quote = (comparison.get("corey_quote") or "").strip()
    if quote:
        lines.append(f"> {quote}")
    align = comparison.get("level_alignment") or []
    if align:
        shown = []
        for p in align:
            if p.get("jarvis") is None:
                shown.append(f"{p['corey']:g} (no JARVIS match)")
            else:
                mark = "≈" if p.get("agree") else "vs"
                shown.append(f"{p['corey']:g} {mark} {p['jarvis']:g}")
        lines.append("- **Levels (Corey vs JARVIS):** " + "; ".join(shown))
    jc = comparison.get("jarvis_correct")
    cc = comparison.get("corey_correct")
    if jc is not None or cc is not None:

        def _v(x):
            return (
                "—" if x is None else ("CORRECT" if x >= 1.0 else ("FLAT" if x == 0.5 else "WRONG"))
            )

        lines.append(f"- **Outcome:** JARVIS {_v(jc)} | Corey {_v(cc)}")
    lines.append("")
    return lines
