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
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd

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

# SKILL.md's clock discipline (both the AM and preclose skills) is CT — the
# trader's clock, not the DB's UTC storage or daily_morning_briefing.py's ET.
_CT = ZoneInfo("America/Chicago")

_ENGINE_PRICES_URL = "http://127.0.0.1:8010/prices/snapshot"
_HTTP_TIMEOUT_S = 5
# ~2 trading days of 1h bars — comfortably covers today's still-forming
# session with room to spare, without pulling get_engine_levels()'s much
# larger multi-week window.
_INTRADAY_LOOKBACK_BARS = 48


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
# Pre-close only — today's realized intraday session (new capability;
# get_engine_levels()/compute_key_levels() deliberately excludes today's
# still-forming session, so it cannot be reused for this). See
# .claude/skills/market-close-brief/SKILL.md Step 1.
# ---------------------------------------------------------------------------


def _fetch_price_snapshot(
    symbols: tuple[str, ...], timeout: int = _HTTP_TIMEOUT_S
) -> dict[str, Any]:
    """Live current price/prev-close/pct-change via the engine's own
    /prices/snapshot — mirrors daily_morning_briefing.fetch_engine_health()'s
    urlopen pattern, plus the X-API-Key header the SKILL.md curl examples use
    (unlike /health, this route sits behind the global API-key middleware even
    though its own handler declares no route-level auth dependency — confirmed
    live: an unauthenticated call 401s). Read fresh at call time, never cached,
    matching this repo's "rotates — read at use time" convention. Empty dict
    on any failure; callers fall back to the last DB bar's close."""
    import os
    from urllib.request import Request

    url = f"{_ENGINE_PRICES_URL}?symbols={','.join(symbols)}"
    api_key = os.getenv("API_KEY", "")
    req = Request(url, headers={"X-API-Key": api_key} if api_key else {})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except (URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Price snapshot unavailable: %s", exc)
        return {}


def get_intraday_snapshot(
    symbols: tuple[str, ...] = FRAMING_SYMBOLS,
    db_path: Optional[Path] = None,
) -> dict[str, Optional[dict]]:
    """Today's realized session range + value area, per symbol.

    Reuses analytics.regime.load_recent_bars (the same DB-native 1h source
    get_engine_levels() depends on transitively) filtered to today's CT
    calendar date, and analysis.morning_levels._value_area for VAH/VAL/POC —
    no new TPO implementation. last_price prefers the live /prices/snapshot
    tick, falling back to the last today-bar's close if the engine is
    unreachable. Returns {symbol: dict | None} — never raises.
    """
    from analysis.morning_levels import _value_area
    from analytics.regime import load_recent_bars

    today_ct = datetime.now(_CT).date()
    price_snapshot = _fetch_price_snapshot(symbols)

    out: dict[str, Optional[dict]] = {}
    for sym in symbols:
        try:
            df1h = load_recent_bars(sym, n_bars=_INTRADAY_LOOKBACK_BARS, db_path=db_path or _DB_PATH)
            if df1h is None or len(df1h) == 0 or "timestamp" not in df1h.columns:
                out[sym] = None
                continue

            ts_utc = pd.to_datetime(df1h["timestamp"], utc=True)
            today_mask = ts_utc.dt.tz_convert(_CT).dt.date == today_ct
            today_df = df1h.loc[today_mask]
            if today_df.empty:
                out[sym] = None
                continue

            session_open = float(today_df.iloc[0]["open"])
            session_high = float(today_df["high"].max())
            session_low = float(today_df["low"].min())
            last_bar_close = float(today_df.iloc[-1]["close"])

            indexed = today_df.set_index(pd.DatetimeIndex(ts_utc.loc[today_mask]))
            vah, val, poc, va_position = _value_area(indexed)

            last_price = last_bar_close
            snap = price_snapshot.get(sym)
            if isinstance(snap, dict) and snap.get("last_price") is not None:
                try:
                    last_price = float(snap["last_price"])
                except (TypeError, ValueError):
                    pass

            out[sym] = {
                "session_open": round(session_open, 4),
                "session_high": round(session_high, 4),
                "session_low": round(session_low, 4),
                "last_price": round(last_price, 4),
                "vah": vah,
                "val": val,
                "poc": poc,
                "va_position": va_position,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Intraday snapshot failed for %s: %s", sym, exc)
            out[sym] = None
    return out


def get_corey_preclose_commentary_for(
    target_date: date,
    *,
    db_path: Optional[Path] = None,
    cutoff_ct_hour: int = 12,
) -> Optional[dict[str, Any]]:
    """Today's raw Corey messages posted after `cutoff_ct_hour` CT — the
    deliberately lightweight companion to get_corey_bias_for(). Reads
    discord_corey_commentary directly (message timestamps already exist, no
    migration), rather than touching corey_session_bias's one-row-per-day
    schema, which blends the whole day's commentary together. Returns raw
    concatenated text, not an LLM-extracted bias — see market-close-brief/
    SKILL.md for why this is the intentional MVP scope. None if unavailable.
    """
    path = db_path or _DB_PATH
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(str(path))
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='discord_corey_commentary'"
        )
        if not cur.fetchone():
            con.close()
            return None
        rows = con.execute(
            "SELECT timestamp, content FROM discord_corey_commentary "
            "WHERE date(timestamp) = ? ORDER BY timestamp ASC",
            (target_date.isoformat(),),
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.debug("Corey pre-close commentary lookup failed: %s", exc)
        return None

    if not rows:
        return None

    afternoon: list[str] = []
    for ts_raw, content in rows:
        if not content:
            continue
        try:
            ts = pd.Timestamp(ts_raw)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            if ts.tz_convert(_CT).hour < cutoff_ct_hour:
                continue
        except Exception:
            pass  # unparseable timestamp — include rather than silently drop
        afternoon.append(str(content))

    if not afternoon:
        return None
    return {"raw_text": "\n\n".join(afternoon), "message_count": len(afternoon)}


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
    # Pre-close only (session="preclose"); always None on the premarket path —
    # an extra null key in the JSON context doesn't affect AM required-header
    # validation or behavior (see test_preclose_framing_brief.py's AM guard).
    intraday_snapshot: Optional[dict] = None
    corey_preclose_raw: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date,
            "confidence_tier": self.confidence_tier,
            "corey_today": self.corey_today,
            "corey_yesterday": self.corey_yesterday,
            "engine_levels": self.engine_levels,
            "system_overlay": self.system_overlay,
            "data_quality_notes": self.data_quality_notes,
            "intraday_snapshot": self.intraday_snapshot,
            "corey_preclose_raw": self.corey_preclose_raw,
        }


async def assemble_context(
    target_date: date,
    *,
    session: Literal["premarket", "preclose"] = "premarket",
    db_path: Optional[Path] = None,
    llm_client: Optional[object] = None,
) -> FramingContext:
    """Run the full Step 0.5 -> 1a -> (2c) gathering sequence and return the
    single context object the synthesis call consumes. Never raises — each
    sub-step degrades to None/empty on failure, matching daily_morning_briefing
    .py's per-section graceful-degradation discipline.

    `session` defaults to "premarket", preserving the exact call shape
    morning_framing_brief.py::_run() already uses (zero session awareness) —
    the two preclose-only gathering calls only happen when session=="preclose".
    """
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

    intraday_snapshot: Optional[dict] = None
    corey_preclose_raw: Optional[dict] = None
    if session == "preclose":
        try:
            intraday_snapshot = get_intraday_snapshot(db_path=db_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Intraday snapshot unavailable: %s", exc)
            notes.append("Intraday snapshot unavailable")
        if not intraday_snapshot or not any(v is not None for v in intraday_snapshot.values()):
            notes.append("Intraday snapshot unavailable — no today-dated bars")

        try:
            corey_preclose_raw = get_corey_preclose_commentary_for(target_date, db_path=db_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Corey pre-close commentary unavailable: %s", exc)
            notes.append("Corey pre-close commentary unavailable")

    return FramingContext(
        target_date=target_date.isoformat(),
        confidence_tier=tier,
        corey_today=corey_today.to_dict() if corey_today is not None else None,
        corey_yesterday=corey_yesterday.to_dict() if corey_yesterday is not None else None,
        engine_levels={k: (v.to_dict() if v is not None else None) for k, v in engine_levels.items()},
        system_overlay=system_overlay,
        data_quality_notes=notes,
        intraday_snapshot=intraday_snapshot,
        corey_preclose_raw=corey_preclose_raw,
    )
