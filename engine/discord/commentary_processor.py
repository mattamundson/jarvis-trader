"""
CoreyCommentaryProcessor — LLM-powered session bias extraction from discord_corey_commentary.

Converts Corey's raw market commentary (TPO/Auction Theory professional) into structured
session bias data: session type, directional bias, key price levels, IB context, and
specific trade triggers.

Results are cached daily in the corey_session_bias table to avoid repeated LLM calls.
Falls back to keyword-based sentiment when the LLM is unavailable or data is missing.

Usage:
    from discord.commentary_processor import CoreyCommentaryProcessor
    processor = CoreyCommentaryProcessor()
    bias = await processor.get_session_bias()   # today
    bias = await processor.get_session_bias(date(2026, 4, 10))
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB path helper (mirrors signal_context.py convention)
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    # DB lives at engine/data/jarvis_trader.db. Anchor at engine/ root, not
    # workspace root — the previous 3-levels-up walked past engine/ and
    # caused a split-brain DB on 2026-04-10.
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_root, "data", "jarvis_trader.db")


def build_default_llm_client(db_path: Optional[str] = None) -> Optional[object]:
    """Construct a JarvisLLMClient for the *standalone* Corey extraction surfaces.

    The MCP server, ``discord.cli --trigger-commentary``, and corey_compare build
    CoreyCommentaryProcessor without an engine-supplied llm_client, so they fell
    through to a raw httpx POST against api.anthropic.com. When that account's
    credit is exhausted, every standalone extraction silently degrades to
    data_quality='none' (2026-06-29 incident), while the live engine — which
    routes through JarvisLLMClient's Vertex->Gemini->OpenAI failover chain — stays
    healthy. Passing this client gives the standalone surfaces the same failover.

    The cost ledger is anchored next to the commentary DB (engine/data/
    llm_costs.db) so it isn't scattered by the caller's cwd. Returns None — never
    raises — if the client can't be built, so callers transparently fall back to
    the existing direct-POST path.
    """
    try:
        # Local import: avoid a heavy import at module load and any import cycle.
        from llm.client import JarvisLLMClient  # noqa: PLC0415

        anchor = db_path or _default_db_path()
        cost_db = os.path.join(os.path.dirname(anchor), "llm_costs.db")
        return JarvisLLMClient(api_key=os.getenv("ANTHROPIC_API_KEY", ""), db_path=cost_db)
    except Exception as e:  # pragma: no cover - defensive; degrade to direct POST
        logger.warning("[CoreyProcessor] build_default_llm_client unavailable: %s", e)
        return None


# ---------------------------------------------------------------------------
# Cache table DDL
# ---------------------------------------------------------------------------

_CREATE_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS corey_session_bias (
    date TEXT PRIMARY KEY,
    session_type TEXT NOT NULL,
    directional_bias TEXT NOT NULL,
    key_levels_json TEXT NOT NULL DEFAULT '[]',
    ib_bias TEXT NOT NULL DEFAULT 'not_mentioned',
    triggers_json TEXT NOT NULL DEFAULT '[]',
    conviction REAL NOT NULL DEFAULT 0.0,
    corey_quote TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    data_quality TEXT NOT NULL DEFAULT 'none',
    computed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class CoreySessionBias:
    """Structured session bias extracted from Corey's commentary."""

    date: date
    session_type: str  # "range_day" | "trend_day" | "outside_bar" | "inside_bar" | "uncertain"
    directional_bias: str  # "bullish" | "bearish" | "neutral"
    key_levels: list[float]  # price levels mentioned in commentary
    ib_bias: str  # "above_ib" | "below_ib" | "inside_ib" | "not_mentioned"
    specific_triggers: list[str]  # max 5 actionable statements
    conviction: float  # 0.0-1.0
    corey_quote: str  # single most actionable sentence
    message_count: int  # number of commentary messages used
    data_quality: str  # "fresh" | "stale" | "none"

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "session_type": self.session_type,
            "directional_bias": self.directional_bias,
            "key_levels": self.key_levels,
            "ib_bias": self.ib_bias,
            "specific_triggers": self.specific_triggers,
            "conviction": self.conviction,
            "corey_quote": self.corey_quote,
            "message_count": self.message_count,
            "data_quality": self.data_quality,
        }


# Neutral fallback for when no data is available
def _neutral_bias(for_date: date, message_count: int = 0) -> CoreySessionBias:
    return CoreySessionBias(
        date=for_date,
        session_type="uncertain",
        directional_bias="neutral",
        key_levels=[],
        ib_bias="not_mentioned",
        specific_triggers=[],
        conviction=0.0,
        corey_quote="",
        message_count=message_count,
        data_quality="none",
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

TATHEDOG_AUTHOR_ID = "564449478174703646"

_LLM_SYSTEM = (
    "You are analyzing Corey's market commentary (TPO/Auction Theory professional). "
    "Extract structured session analysis. Respond with valid JSON only. "
    "Do not include any text outside the JSON object."
)

_LLM_PROMPT_TEMPLATE = """Analyze Corey's commentary for {date} ({n_messages} messages, market-updates + general/tathedog channels).
Messages (oldest first):

{messages}

Identify the session structure and directional bias from this auction theory commentary.

Respond with JSON in exactly this format:
{{
  "session_type": "range_day|trend_day|outside_bar|inside_bar|uncertain",
  "directional_bias": "bullish|bearish|neutral",
  "key_levels": [list of price numbers as floats, empty list if none],
  "ib_bias": "above_ib|below_ib|inside_ib|not_mentioned",
  "specific_triggers": ["max 5 actionable trade trigger statements, empty list if none"],
  "conviction": 0.0,
  "corey_quote": "single most actionable sentence, empty string if none"
}}

Rules:
- conviction: 0.0 if very uncertain, 0.5 if moderate clarity, 1.0 if very clear directional bias
- key_levels: only include specific price numbers Corey mentioned (e.g. 5823.50, 84.20)
- specific_triggers: exact action-oriented statements ("if X holds, expect Y")
- session_type: use "uncertain" if unclear or insufficient data"""


class CoreyCommentaryProcessor:
    """
    Extracts structured session bias from discord_corey_commentary via Haiku LLM.

    Caches results daily in corey_session_bias table. On cache hit, returns
    immediately without calling the LLM. On cache miss, fetches commentary rows,
    calls Haiku, writes cache, returns result.

    Falls back to neutral bias if:
    - No commentary rows exist for the requested date
    - LLM call fails
    - DB is not accessible
    """

    MODEL = "claude-haiku-4-5-20251001"
    MAX_TOKENS = 600
    STALE_DAYS = 2  # data older than this gets data_quality="stale"

    def __init__(
        self,
        db_path: Optional[str] = None,
        api_key: Optional[str] = None,
        llm_client: Optional[object] = None,
    ):
        self.db_path = db_path or _default_db_path()
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        # Optional JarvisLLMClient: when provided, _llm_extract routes through
        # its provider-fallback chain instead of a direct Anthropic POST (B4).
        self._llm = llm_client
        self._ensure_cache_table()

    def _ensure_cache_table(self) -> None:
        """Create the cache table if it doesn't exist.

        R-I-5: Logs include the resolved db_path so a wrong-path failure
        (e.g., split-brain DB pointing at the stale repo-root copy) is
        diagnosable from the warning text alone, instead of surfacing
        later as an obscure 'no such table: corey_session_bias' from
        downstream code.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(_CREATE_CACHE_TABLE)
                conn.commit()
        except Exception as e:
            logger.warning(
                "[CoreyProcessor] Could not create cache table at %s: %s",
                self.db_path,
                e,
            )

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_session_bias(self, for_date: Optional[date] = None) -> CoreySessionBias:
        """
        Return structured session bias for the given date (defaults to today).

        Checks cache first. On cache miss, fetches commentary rows and calls LLM.
        Returns neutral bias if no data is available.
        """
        if for_date is None:
            for_date = date.today()

        # Cache check
        cached = self._load_from_cache(for_date)
        if cached is not None:
            logger.debug("[CoreyProcessor] Cache hit for %s", for_date)
            return cached

        # Fetch commentary rows
        rows = self._fetch_commentary(for_date)
        if not rows:
            # Check nearby dates for stale data
            rows, actual_date = self._fetch_recent_commentary(for_date)
            if not rows:
                logger.info("[CoreyProcessor] No commentary found for %s or nearby dates", for_date)
                result = _neutral_bias(for_date, message_count=0)
                self._save_to_cache(result)
                return result
            days_old = (for_date - actual_date).days
            if days_old > self.STALE_DAYS:
                logger.info(
                    "[CoreyProcessor] Commentary is %d days old (from %s) — will be marked stale",
                    days_old,
                    actual_date,
                )

        # Call LLM
        result = await self._llm_extract(for_date, rows)
        # Don't pin LLM failures to the day-level cache: if Anthropic returns 4xx
        # (credit balance, transient bad-request) the cached "none" would persist
        # until midnight even after billing/connectivity is restored mid-session.
        # Successful extractions and the "no rows exist" branch above still cache.
        if result.data_quality == "none" and len(rows) > 0:
            logger.info(
                "[CoreyProcessor] Skipping cache for %s — LLM failed with rows present; will retry next call",
                for_date,
            )
            return result
        self._save_to_cache(result)
        return result

    # ── Commentary Fetch ───────────────────────────────────────────────────

    def _fetch_commentary(self, for_date: date) -> list[dict]:
        """Fetch all commentary rows for the given date (market-updates + tathedog/general)."""
        date_str = for_date.isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT content, timestamp, channel
                    FROM discord_corey_commentary
                    WHERE DATE(timestamp) = ?
                      AND (
                          channel = 'market-updates'
                          OR (channel = 'general' AND author_id = ?)
                      )
                    ORDER BY timestamp ASC
                    """,
                    (date_str, TATHEDOG_AUTHOR_ID),
                )
                rows = [dict(r) for r in cur.fetchall()]
            return rows
        except Exception as e:
            logger.warning("[CoreyProcessor] DB fetch failed for %s: %s", date_str, e)
            return []

    def _count_commentary(self, for_date: date) -> int:
        """Cheap COUNT of commentary rows for a date — same filter as
        _fetch_commentary. Used by _load_from_cache to detect when a cached
        none/msgs=0 row has been invalidated by late-arriving / backfilled
        #market-updates ingestion. Degrades to 0 (treat as still-empty) if the
        commentary table is absent or the query fails, so a fresh/standalone DB
        never raises through the cache-load path.
        """
        date_str = for_date.isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM discord_corey_commentary
                    WHERE DATE(timestamp) = ?
                      AND (
                          channel = 'market-updates'
                          OR (channel = 'general' AND author_id = ?)
                      )
                    """,
                    (date_str, TATHEDOG_AUTHOR_ID),
                )
                return int(cur.fetchone()[0] or 0)
        except Exception as e:
            logger.warning("[CoreyProcessor] Commentary count failed for %s: %s", date_str, e)
            return 0

    def _fetch_recent_commentary(self, for_date: date) -> tuple[list[dict], date]:
        """
        Look back up to 7 days to find the most recent commentary.
        Returns (rows, actual_date) — rows may be empty if nothing found.
        """
        for days_back in range(1, 8):
            check_date = for_date - timedelta(days=days_back)
            rows = self._fetch_commentary(check_date)
            if rows:
                return rows, check_date
        return [], for_date

    # ── LLM Extraction ─────────────────────────────────────────────────────

    async def _llm_extract(self, for_date: date, rows: list[dict]) -> CoreySessionBias:
        """Call Claude Haiku to extract structured bias from commentary rows."""
        if not self._api_key and not (self._llm is not None and hasattr(self._llm, "call")):
            logger.warning("[CoreyProcessor] No API key — returning neutral bias")
            return _neutral_bias(for_date, message_count=len(rows))

        # Determine data quality
        most_recent_date = _parse_date(rows[-1]["timestamp"]) if rows else for_date
        days_old = (for_date - most_recent_date).days if most_recent_date else 0
        data_quality = "fresh" if days_old <= self.STALE_DAYS else "stale"

        # Build message block (cap at 6000 chars to stay within Haiku token budget)
        messages_text = _build_message_block(rows, max_chars=60000)
        prompt = _LLM_PROMPT_TEMPLATE.format(
            date=for_date.isoformat(),
            n_messages=len(rows),
            messages=messages_text,
        )

        try:
            if self._llm is not None and hasattr(self._llm, "call"):
                # Live engine path (B4, 2026-06-11): JarvisLLMClient owns the
                # Vertex->Gemini->OpenAI fallback chain, so credit exhaustion on
                # the primary no longer kills daily Corey bias extraction. The
                # direct POST below remains ONLY for standalone contexts (CLI,
                # MCP server, briefing) constructed without an engine client.
                llm_result = await self._llm.call(
                    model=self.MODEL,
                    system=_LLM_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.MAX_TOKENS,
                    agent_name="corey_commentary",
                )
                if not getattr(llm_result, "success", False):
                    raise RuntimeError(
                        f"corey_commentary LLM call failed: "
                        f"{getattr(llm_result, 'error', 'unknown')}"
                    )
                raw = (llm_result.content or "").strip()
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": self.MODEL,
                            "max_tokens": self.MAX_TOKENS,
                            "system": _LLM_SYSTEM,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()

                raw = payload["content"][0]["text"].strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result_dict = json.loads(raw)

            return CoreySessionBias(
                date=for_date,
                session_type=_valid_session_type(result_dict.get("session_type")),
                directional_bias=_valid_bias(result_dict.get("directional_bias")),
                key_levels=_parse_levels(result_dict.get("key_levels")),
                ib_bias=_valid_ib_bias(result_dict.get("ib_bias")),
                specific_triggers=_parse_triggers(result_dict.get("specific_triggers")),
                conviction=float(_clamp(result_dict.get("conviction", 0.0), 0.0, 1.0)),
                corey_quote=str(result_dict.get("corey_quote", ""))[:300],
                message_count=len(rows),
                data_quality=data_quality,
            )

        except Exception as e:
            # Surface the actual Anthropic response body when available — a bare
            # "400 Bad Request" hides "credit balance is too low" vs other 400s.
            body_excerpt = ""
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    body_excerpt = (resp.text or "")[:400]
                except Exception:
                    body_excerpt = ""
            logger.error(
                "[CoreyProcessor] LLM extraction failed: %s%s",
                e,
                f" | body={body_excerpt!r}" if body_excerpt else "",
            )
            # WARNING — visible sentinel so silent degradation is always logged.
            # data_quality='none' means the bias is unknown, NOT that it is neutral.
            # Downstream consumers must not treat 'none' as a directional signal.
            logger.warning(
                "[CoreyProcessor] DEGRADED TO NEUTRAL for %s — "
                "data_quality='none' because LLM extraction failed (%d messages present). "
                "This date will NOT be cached; next call will retry the LLM.",
                for_date.isoformat(),
                len(rows),
            )
            # data_quality must be 'none' on any LLM exception — the rows-present
            # branch previously wrote 'fresh'/'stale' here, which downstream
            # correlation queries (discord_correlation.py filters on data_quality
            # IN ('fresh','stale')) would silently include as content-empty
            # neutral noise. 'none' is the explicit "no LLM-extracted bias" sentinel.
            return CoreySessionBias(
                date=for_date,
                session_type="uncertain",
                directional_bias="neutral",
                key_levels=[],
                ib_bias="not_mentioned",
                specific_triggers=[],
                conviction=0.0,
                corey_quote="",
                message_count=len(rows),
                data_quality="none",
            )

    # ── Cache ───────────────────────────────────────────────────────────────

    def _load_from_cache(self, for_date: date) -> Optional[CoreySessionBias]:
        """Return cached result for the date, or None if not cached.

        Poisoned rows — data_quality='none' with message_count > 0 — are
        treated as a cache miss and evicted. They represent a prior LLM
        failure (e.g. billing outage) on a date that had real commentary.
        Returning them would permanently suppress extraction for that date
        even after the outage is resolved (2026-05-11 regression root cause).

        Stale no-data rows (data_quality='none' AND message_count=0) are
        rechecked against live commentary: if #market-updates has since been
        ingested for that date (late arrival or post-ingestion-gap backfill),
        the row is evicted and re-extracted. Only a date that is *still* empty
        is returned as-is — that answer is stable.
        """
        date_str = for_date.isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT * FROM corey_session_bias WHERE date = ?", (date_str,))
                row = cur.fetchone()
            if row is None:
                return None

            # Evict poisoned rows: failed LLM extraction on a date with real messages.
            if row["data_quality"] == "none" and int(row["message_count"]) > 0:
                logger.warning(
                    "[CoreyProcessor] Evicting poisoned cache for %s "
                    "(data_quality='none' but message_count=%d — prior LLM failure). "
                    "Will re-extract.",
                    date_str,
                    int(row["message_count"]),
                )
                self._evict_cache(for_date)
                return None

            # Evict stale no-data rows: msgs=0 was cached before #market-updates
            # ingestion caught up for this date. Trusting it permanently pinned a
            # neutral bias (corey_signal=0.0) even after commentary backfilled,
            # starving the IC calibration. Recheck live commentary; re-extract
            # when messages now exist. A genuinely-empty day still returns as-is.
            if row["data_quality"] == "none" and int(row["message_count"]) == 0:
                if self._count_commentary(for_date) > 0:
                    logger.warning(
                        "[CoreyProcessor] Evicting stale no-data cache for %s "
                        "(cached msgs=0 but commentary has since been ingested). "
                        "Will re-extract.",
                        date_str,
                    )
                    self._evict_cache(for_date)
                    return None

            return CoreySessionBias(
                date=for_date,
                session_type=row["session_type"],
                directional_bias=row["directional_bias"],
                key_levels=json.loads(row["key_levels_json"] or "[]"),
                ib_bias=row["ib_bias"],
                specific_triggers=json.loads(row["triggers_json"] or "[]"),
                conviction=float(row["conviction"]),
                corey_quote=row["corey_quote"] or "",
                message_count=int(row["message_count"]),
                data_quality=row["data_quality"],
            )
        except Exception as e:
            logger.warning("[CoreyProcessor] Cache load failed: %s", e)
            return None

    def _save_to_cache(self, bias: CoreySessionBias) -> None:
        """Write (or replace) cache row for the given date."""
        date_str = bias.date.isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO corey_session_bias
                    (date, session_type, directional_bias, key_levels_json,
                     ib_bias, triggers_json, conviction, corey_quote,
                     message_count, data_quality, computed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date_str,
                        bias.session_type,
                        bias.directional_bias,
                        json.dumps(bias.key_levels),
                        bias.ib_bias,
                        json.dumps(bias.specific_triggers),
                        bias.conviction,
                        bias.corey_quote,
                        bias.message_count,
                        bias.data_quality,
                        datetime.utcnow().isoformat(),
                    ),
                )
                conn.commit()
            logger.debug(
                "[CoreyProcessor] Cached session bias for %s (quality=%s)",
                date_str,
                bias.data_quality,
            )
        except Exception as e:
            logger.warning("[CoreyProcessor] Cache save failed: %s", e)

    def invalidate_cache(self, for_date: Optional[date] = None) -> None:
        """Delete cache row for a date (or today) to force re-extraction on next call."""
        date_str = (for_date or date.today()).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM corey_session_bias WHERE date = ?", (date_str,))
                conn.commit()
            logger.info("[CoreyProcessor] Cache invalidated for %s", date_str)
        except Exception as e:
            logger.warning("[CoreyProcessor] Cache invalidation failed: %s", e)

    def purge_stale_no_data_cache(self) -> list[str]:
        """Evict every cached none/msgs=0 row whose date now has ingested
        commentary, so the next get_session_bias re-extracts the real bias.
        Returns the list of evicted date strings (ascending).

        Complements the per-call recheck in _load_from_cache: that heals a date
        only when it is next requested, whereas this proactively clears the
        backlog left by an ingestion gap (or a slow first-call-of-the-day) so
        the IC calibration isn't starved waiting for each stale date to happen
        to be re-requested. Idempotent — a date that is still empty is left
        untouched, and an already-re-extracted date no longer matches the filter.
        """
        evicted: list[str] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT date FROM corey_session_bias "
                    "WHERE data_quality = 'none' AND message_count = 0 "
                    "ORDER BY date ASC"
                ).fetchall()
            for r in rows:
                date_str = r["date"]
                try:
                    d = date.fromisoformat(date_str)
                except (TypeError, ValueError):
                    continue
                if self._count_commentary(d) > 0:
                    self._evict_cache(d)
                    evicted.append(date_str)
        except Exception as e:
            logger.warning("[CoreyProcessor] purge_stale_no_data_cache failed: %s", e)
        if evicted:
            logger.info(
                "[CoreyProcessor] Purged %d stale no-data cache row(s) "
                "(commentary backfilled): %s",
                len(evicted),
                ", ".join(evicted),
            )
        return evicted

    def _evict_cache(self, for_date: date) -> None:
        """Delete a poisoned cache row so the next call triggers fresh LLM extraction."""
        date_str = for_date.isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM corey_session_bias WHERE date = ?", (date_str,))
                conn.commit()
        except Exception as e:
            logger.warning("[CoreyProcessor] Cache eviction failed for %s: %s", date_str, e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_message_block(rows: list[dict], max_chars: int = 60000) -> str:
    """Build a single text block from commentary rows for the LLM extractor.

    Walks newest-first to fill the budget so end-of-session updates
    (e.g., a Power Hour revision that pivots the bias) anchor the synthesis
    rather than getting dropped when an earlier morning post exhausts the
    budget. The output is then re-sorted chronologically (oldest→newest)
    so the LLM still reads the day's narrative in sequence.

    Input rows are expected ASC (oldest first) — see _fetch_commentary.
    """
    selected: list[tuple[str, str]] = []
    total = 0
    for row in reversed(rows):
        content = (row.get("content") or "").strip()
        if not content:
            continue
        ts_full = row.get("timestamp", "")
        ts = ts_full[:16]
        line = f"[{ts}] {content}"
        if total + len(line) > max_chars:
            break
        selected.append((ts_full, line))
        total += len(line)
    if not selected:
        return "(no messages)"
    selected.sort(key=lambda x: x[0])
    return "\n".join(line for _, line in selected)


def _parse_date(ts_str: str) -> Optional[date]:
    """Parse a timestamp string to a date, returning None on failure."""
    try:
        return datetime.fromisoformat(ts_str[:10]).date()
    except Exception:
        return None


def get_futures_sentiment_staleness(db_path: Optional[str] = None) -> dict:
    """Freshness of the Corey #market-updates futures-sentiment feed.

    Corey's Discord commentary is the SOLE sanctioned futures-sentiment source
    (social_analyst gates Reddit/Twitter off for futures). Its DCE import has
    silently frozen before — the user token was revoked and nothing flagged it,
    so every MES/MNQ/MCL/MGC decision ran on stale sentiment undetected. This
    reads MAX(timestamp) from discord_corey_commentary and reports age + quality
    against ``CoreyCommentaryProcessor.STALE_DAYS`` so a frozen feed is
    observable in /health and to the analyst.

    Read-only + resilient: returns quality="unknown" (never raises) if the table
    is absent or empty.
    """
    path = db_path or _default_db_path()
    threshold = CoreyCommentaryProcessor.STALE_DAYS
    result = {
        "latest_timestamp": None,
        "age_days": None,
        "quality": "unknown",
        "threshold_days": threshold,
    }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM discord_corey_commentary "
                "WHERE channel = 'market-updates'"
            ).fetchone()
    except Exception as exc:  # missing table / unreadable DB
        logger.debug("get_futures_sentiment_staleness: %s", exc)
        return result

    latest = row[0] if row else None
    if not latest:
        return result
    latest_date = _parse_date(latest)
    if latest_date is None:
        return result

    age_days = (date.today() - latest_date).days
    result["latest_timestamp"] = latest
    result["age_days"] = age_days
    result["quality"] = "fresh" if age_days <= threshold else "stale"
    return result


def get_bias_extraction_health(db_path: Optional[str] = None) -> dict:
    """Detect when Corey *structured-bias* LLM extraction has stalled while raw
    commentary keeps flowing.

    ``get_futures_sentiment_staleness`` covers INGESTION freshness; it cannot see
    an LLM-extraction outage. On 2026-06-29 the direct-Anthropic account's credit
    was exhausted: commentary ingested fine, but every structured session_bias
    degraded to data_quality='none' for two days, undetected by /health. This
    compares the latest market-updates commentary date against the latest date
    with a fresh/stale cached bias; if extraction has fallen ``lag_threshold``+
    days behind ingestion (or never produced bias for existing commentary), it is
    'degraded'.

    Cache-only — makes NO LLM call (safe for a hot health endpoint). Read-only +
    resilient: returns quality='unknown' (never raises) if a table is absent/empty.
    """
    path = db_path or _default_db_path()
    lag_threshold = 2
    result = {
        "extraction_quality": "unknown",
        "latest_commentary_date": None,
        "latest_bias_date": None,
        "lag_days": None,
        "lag_threshold_days": lag_threshold,
    }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            crow = conn.execute(
                "SELECT MAX(DATE(timestamp)) FROM discord_corey_commentary "
                "WHERE channel = 'market-updates'"
            ).fetchone()
            brow = conn.execute(
                "SELECT MAX(date) FROM corey_session_bias "
                "WHERE data_quality IN ('fresh','stale')"
            ).fetchone()
    except Exception as exc:  # missing table / unreadable DB
        logger.debug("get_bias_extraction_health: %s", exc)
        return result

    latest_commentary = crow[0] if crow else None
    latest_bias = brow[0] if brow else None
    if not latest_commentary:
        return result  # no commentary at all -> unknown

    result["latest_commentary_date"] = latest_commentary
    result["latest_bias_date"] = latest_bias

    cdate = _parse_date(latest_commentary)
    if cdate is None:
        return result
    if not latest_bias:
        # Commentary exists but no structured bias has ever been cached.
        result["extraction_quality"] = "degraded"
        return result
    bdate = _parse_date(latest_bias)
    if bdate is None:
        return result

    lag = (cdate - bdate).days
    result["lag_days"] = lag
    result["extraction_quality"] = "degraded" if lag >= lag_threshold else "ok"
    return result


def _clamp(val, lo, hi):
    try:
        return max(lo, min(hi, float(val)))
    except (TypeError, ValueError):
        return lo


def _valid_session_type(val: Optional[str]) -> str:
    valid = {"range_day", "trend_day", "outside_bar", "inside_bar", "uncertain"}
    if val and str(val).lower() in valid:
        return str(val).lower()
    return "uncertain"


def _valid_bias(val: Optional[str]) -> str:
    valid = {"bullish", "bearish", "neutral"}
    if val and str(val).lower() in valid:
        return str(val).lower()
    return "neutral"


def _valid_ib_bias(val: Optional[str]) -> str:
    valid = {"above_ib", "below_ib", "inside_ib", "not_mentioned"}
    if val and str(val).lower() in valid:
        return str(val).lower()
    return "not_mentioned"


def _parse_levels(val) -> list[float]:
    if not isinstance(val, list):
        return []
    result = []
    for item in val:
        try:
            f = float(item)
            if f > 0:
                result.append(round(f, 4))
        except (TypeError, ValueError):
            pass
    return result[:20]  # cap at 20 levels


def _parse_triggers(val) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(t)[:200] for t in val if t][:5]
