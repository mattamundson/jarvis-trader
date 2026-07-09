"""
Data-gathering for the automated morning framing brief.

Python-native replacement for the market-framing-brief skill's Steps 0.5/1a/2c
(``.claude/skills/market-framing-brief/SKILL.md``) — the skill shells out to CLIs
and curl because it runs inside an LLM agent turn; a scheduled script can call
the same underlying functions in-process instead.

Source-of-truth priority (mirrors SKILL.md):
  1. Corey's actual commentary (``get_corey_bias_for`` — HIGHEST confidence)
  2. Engine/DB-derived structural levels (``get_engine_levels`` — HIGH confidence)
  3. Deterministic OHLC fallback (``compute_fallback_levels`` — defense-in-depth
     only; see its docstring for why it is rarely reachable in this path)

No web-search fallback (SKILL.md Step 1b) — a headless script has no WebSearch
equivalent; dropping straight to LOW confidence when Corey and the DB both come
up empty is intentional, not an oversight.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

_ANALYSIS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _ANALYSIS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"

# ES/NQ proxies (price-identical to the micros the engine actually carries bars
# for — same convention as daily_morning_briefing.py's Key Levels section).
FRAMING_SYMBOLS: tuple[str, ...] = ("MES", "MNQ")

ConfidenceTier = Literal["HIGHEST", "HIGH", "LOW"]


# ---------------------------------------------------------------------------
# Step 0.5 — Corey's actual commentary (highest-priority source)
# ---------------------------------------------------------------------------


async def get_corey_bias_for(
    target_date: date,
    *,
    db_path: Optional[Path] = None,
    llm_client: Optional[object] = None,
) -> Any:
    """In-process equivalent of ``corey_session_bias_report.py --date ... --json``.

    Calls the same ``CoreyCommentaryProcessor.get_session_bias()`` the CLI wraps
    (``engine/discord/commentary_processor.py``) directly — no subprocess, no
    JSON round-trip. Self-caches in ``corey_session_bias``, so calling this
    twice (today + yesterday) is at most one LLM call plus one cheap cache hit.
    """
    from discord.commentary_processor import CoreyCommentaryProcessor

    processor = CoreyCommentaryProcessor(
        db_path=str(db_path) if db_path else None,
        llm_client=llm_client,
    )
    return await processor.get_session_bias(target_date)


def is_bias_usable(bias: Any) -> bool:
    """``data_quality='none'`` means unavailable, NOT a bearish/neutral signal.

    This check must be applied to BOTH today's and yesterday's row — a poisoned
    or missing yesterday row is exactly as untrustworthy as a poisoned today row
    (SKILL.md Step 0.5 / Hard rules).
    """
    return bool(bias) and getattr(bias, "data_quality", "none") != "none"


# ---------------------------------------------------------------------------
# Step 1a — engine/DB-derived structural levels
# ---------------------------------------------------------------------------


def get_engine_levels(
    symbols: tuple[str, ...] = FRAMING_SYMBOLS,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Reuse ``daily_morning_briefing.compute_key_levels()`` — already DB-native,
    already production-proven, needs no HTTP call or API key. Returns
    ``{symbol: MorningLevels | None}``.
    """
    from scripts.daily_morning_briefing import compute_key_levels

    return compute_key_levels(symbols=symbols, db_path=db_path)


def _load_compute_levels_module():
    """Dynamically load the skill's ``compute_levels.py`` (lives outside the
    ``engine/`` package, under ``.claude/skills/market-framing-brief/``) so the
    fallback floor-pivot math has exactly one implementation shared by the
    human-invoked skill and this script, rather than a second copy drifting
    out of sync. Returns ``None`` if the file can't be found/loaded.
    """
    repo_root = _ENGINE_DIR.parent
    skill_path = repo_root / ".claude" / "skills" / "market-framing-brief" / "compute_levels.py"
    if not skill_path.exists():
        logger.warning("compute_levels.py not found at %s", skill_path)
        return None
    try:
        spec = importlib.util.spec_from_file_location("_compute_levels_skill", skill_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("compute_levels.py load failed: %s", exc)
        return None


def compute_fallback_levels(
    prior_high: float, prior_low: float, prior_close: float
) -> Optional[dict[str, float]]:
    """Deterministic floor-pivot fallback, delegating to the skill's own
    ``floor_pivots()`` (same formula ``analysis/morning_levels.py`` already
    uses for the primary DB-native path — see that module's docstring).

    NOTE: in the automated path this is close to vestigial defense-in-depth,
    not a real second data source. If ``get_engine_levels()`` returns None for
    a symbol, it's because the DB has insufficient bars for that symbol — and
    this function needs prior-session OHLC, which comes from those same bars.
    There is no independent OHLC source (no WebSearch) to feed it from here.
    It exists for callers that DO have OHLC from elsewhere, and to keep the
    "never invent a level" discipline explicit rather than silently skipped.
    """
    module = _load_compute_levels_module()
    if module is None:
        return None
    return module.floor_pivots(prior_high, prior_low, prior_close)


# ---------------------------------------------------------------------------
# Confidence tier — single source of truth (script decision == prompt claim)
# ---------------------------------------------------------------------------


def resolve_confidence_tier(
    corey_bias: Any,
    engine_levels: dict[str, Any],
) -> ConfidenceTier:
    if is_bias_usable(corey_bias):
        return "HIGHEST"
    if any(v is not None for v in engine_levels.values()):
        return "HIGH"
    return "LOW"


# ---------------------------------------------------------------------------
# System overlay numbers (Step 3) — kill-switch state + ATR
# ---------------------------------------------------------------------------


def get_system_overlay(engine_levels: dict[str, Any]) -> dict[str, Any]:
    """Kill-switch/health state + the MES ATR for the 2.0xATR stop distance.
    Never blocks the brief — an unreachable engine yields an honest 'unknown'."""
    from scripts.daily_morning_briefing import fetch_engine_health

    health = fetch_engine_health()
    mes = engine_levels.get("MES")
    atr = float(mes.atr) if mes is not None and mes.atr == mes.atr else None  # NaN-safe
    return {
        "kill_switch_active": health.get("kill_switch_active"),
        "engine_status": health.get("status", "UNKNOWN"),
        "atr": atr,
    }


# ---------------------------------------------------------------------------
# Final assembly
# ---------------------------------------------------------------------------


@dataclass
class FramingContext:
    """The single JSON-serializable context object handed to the LLM synthesis
    call (``framing_synthesis.build_prompt``)."""

    target_date: str
    confidence_tier: ConfidenceTier
    corey_today: Optional[dict]
    corey_yesterday: Optional[dict]
    engine_levels: dict[str, Optional[dict]]
    system_overlay: dict[str, Any]
    data_quality_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "confidence_tier": self.confidence_tier,
            "corey_today": self.corey_today,
            "corey_yesterday": self.corey_yesterday,
            "engine_levels": self.engine_levels,
            "system_overlay": self.system_overlay,
            "data_quality_notes": self.data_quality_notes,
        }


async def assemble_context(
    target_date: date,
    *,
    db_path: Optional[Path] = None,
    llm_client: Optional[object] = None,
) -> FramingContext:
    """Run the full Step 0.5 -> 1a -> (2c) gathering sequence and return the
    single context object the synthesis call consumes. Never raises — each
    sub-step degrades to None/empty on failure, matching daily_morning_briefing
    .py's per-section graceful-degradation discipline."""
    notes: list[str] = []
    yesterday = target_date - timedelta(days=1)

    try:
        corey_today = await get_corey_bias_for(target_date, db_path=db_path, llm_client=llm_client)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Corey bias (today) unavailable: %s", exc)
        corey_today = None
        notes.append("Corey commentary lookup failed (today)")

    try:
        corey_yesterday = await get_corey_bias_for(
            yesterday, db_path=db_path, llm_client=llm_client
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Corey bias (yesterday) unavailable: %s", exc)
        corey_yesterday = None
        notes.append("Corey commentary lookup failed (yesterday)")

    if corey_today is not None and not is_bias_usable(corey_today):
        notes.append(f"Corey data_quality={corey_today.data_quality} (today) — not a market signal")
    elif corey_today is not None and corey_today.data_quality == "stale":
        notes.append("Corey commentary (today) is stale (>2 days old)")

    if corey_yesterday is not None and not is_bias_usable(corey_yesterday):
        notes.append(
            f"Corey data_quality={corey_yesterday.data_quality} (yesterday) — not a market signal"
        )

    try:
        engine_levels = get_engine_levels(db_path=db_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Engine/DB levels unavailable: %s", exc)
        engine_levels = dict.fromkeys(FRAMING_SYMBOLS)
        notes.append("Engine/DB levels lookup failed")

    if not any(v is not None for v in engine_levels.values()):
        notes.append("Engine/DB levels unavailable — no OHLC to compute a fallback from")

    try:
        system_overlay = get_system_overlay(engine_levels)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("System overlay unavailable: %s", exc)
        system_overlay = {"kill_switch_active": None, "engine_status": "UNKNOWN", "atr": None}
        notes.append("System overlay (kill-switch/ATR) unavailable")

    tier = resolve_confidence_tier(corey_today, engine_levels)

    return FramingContext(
        target_date=target_date.isoformat(),
        confidence_tier=tier,
        corey_today=corey_today.to_dict() if corey_today is not None else None,
        corey_yesterday=corey_yesterday.to_dict() if corey_yesterday is not None else None,
        engine_levels={k: (v.to_dict() if v is not None else None) for k, v in engine_levels.items()},
        system_overlay=system_overlay,
        data_quality_notes=notes,
    )
