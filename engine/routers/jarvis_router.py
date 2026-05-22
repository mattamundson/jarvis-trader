"""
JARVIS Router — natural-language command bridge + quick-analysis surface.

Endpoints
---------
GET  /jarvis/analyze          — Gemini-backed market snapshot (quick analysis)
POST /jarvis/analyze          — same, body form
POST /jarvis/ask              — unified NL entrypoint: routes a free-text question
                                to the right subsystem and returns a coherent answer.

Safety contract for /jarvis/ask
--------------------------------
- Intent classification is RULE-BASED (regex/keyword). Never LLM-driven.
- Hardcoded refusal list blocks safety-layer override attempts.
- All questions that would route through LLM for classification are rejected if
  the intent classifier is uncertain (falls to "unknown" intent, not a guess).
- JSONL metadata log written per request; question/answer text is NOT logged.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from api.models import JarvisQuickAnalysisRequest, JarvisQuickAnalysisResponse
from services import jarvis_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jarvis", tags=["jarvis"])

# ── JSONL log path ──────────────────────────────────────────────────────────
# Resolved relative to this file so the path is correct regardless of cwd.
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_ASK_LOG_PATH = _LOG_DIR / "jarvis_ask.log"


def _write_ask_log(
    intent: str,
    elapsed_ms: int,
    sources_count: int,
    actions_count: int,
) -> None:
    """Append a metadata-only JSONL entry. No question/answer text."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intent": intent,
            "elapsed_ms": elapsed_ms,
            "sources_count": sources_count,
            "actions_count": actions_count,
        }
        with _ASK_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("[jarvis/ask] log write failed (non-fatal): %s", exc)


# ── Pydantic models ─────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """Natural-language question directed at the JARVIS command bridge."""

    model_config = ConfigDict(str_strip_whitespace=True, str_min_length=1)

    question: str = Field(..., description="Free-text question for JARVIS", max_length=2000)
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional caller context (e.g. symbol, account_id) — informational only",
    )


class AskResponse(BaseModel):
    """Unified response from POST /jarvis/ask."""

    model_config = ConfigDict(frozen=True)

    answer: str = Field(..., description="Natural-language answer paragraph")
    sources: list[str] = Field(default_factory=list, description="Vault paths or reference URLs")
    actions_taken: list[str] = Field(
        default_factory=list,
        description="Side-effect descriptions — empty for read-only handlers",
    )
    elapsed_ms: int = Field(..., description="Wall-clock latency in milliseconds")
    intent: str = Field(..., description="Detected intent label")


# ── Hardcoded refusal list ──────────────────────────────────────────────────
# Any question whose cleaned text matches one of these patterns is immediately
# refused.  Safety-layer decisions are NEVER routable through an LLM surface.

_REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"override.{0,20}kill.?switch",
        r"disable.{0,20}safety",
        r"set.{0,20}live.{0,20}trad",
        r"enable.{0,20}live",
        r"bypass.{0,20}risk",
        r"force.{0,20}trade",
        r"sell.{0,10}all",
        r"buy.{0,10}all",
        r"override.{0,20}stop",
        r"disable.{0,20}kill",
        r"turn.{0,10}off.{0,20}safety",
        r"remove.{0,20}risk.{0,20}limit",
    ]
]


def _is_refused(question: str) -> bool:
    """Return True if the question matches any hardcoded refusal pattern."""
    for pat in _REFUSAL_PATTERNS:
        if pat.search(question):
            return True
    return False


# ── Intent taxonomy ─────────────────────────────────────────────────────────
#
#  Each intent maps to a handler function with the signature:
#      handler(question: str, context: dict | None) -> tuple[str, list[str], list[str]]
#  returning (answer, sources, actions_taken).
#
#  Classification is keyword/regex — NOT an LLM call.

_SUPPORTED_INTENTS: list[str] = [
    "health",
    "bookmark_search",
    "bookmark_recent",
    "commentary",
    "briefing",
    "tearsheet",
    "regime",
    "pipeline_run",
    "position",
    "unknown",
]

# Pattern sets for each non-unknown intent.  Evaluated in listed order; first match wins.
_INTENT_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "health",
        [
            re.compile(
                r"\b(health|healthy|status|kill.?switch|engine.?up|broker.?connect|is.+up|is.+running|system.+ok)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "bookmark_search",
        [
            re.compile(r"\b(search|find|look.?up|query).{0,30}bookmark", re.IGNORECASE),
            re.compile(r"\bbookmark.{0,30}(search|find|about|for|contain|match)\b", re.IGNORECASE),
        ],
    ),
    (
        "bookmark_recent",
        [
            re.compile(r"\b(recent|latest|last|new).{0,20}bookmark", re.IGNORECASE),
            re.compile(
                r"\bbookmark.{0,20}(recent|latest|last|new|today|this week)\b", re.IGNORECASE
            ),
        ],
    ),
    (
        "commentary",
        [
            re.compile(
                r"\b(corey|commentary|market.?update|auction.?theory|discord.?comment)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "briefing",
        [
            re.compile(
                r"\b(briefing|pre.?market|morning.?brief|session.?brief|brief.+(?:MES|MNQ|MCL|MGC|SPY|QQQ))\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(brief|snapshot|summary).{0,30}(MES|MNQ|MCL|MGC|SPY|QQQ)\b", re.IGNORECASE
            ),
            re.compile(
                r"\b(MES|MNQ|MCL|MGC|SPY|QQQ).{0,30}(brief|snapshot|summary)\b", re.IGNORECASE
            ),
        ],
    ),
    (
        "tearsheet",
        [
            re.compile(
                r"\b(tearsheet|tear.?sheet|quantstats|performance.?report|stats.?report|backtest.?report)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "regime",
        [
            re.compile(
                r"\b(regime|market.?regime|trending|choppy|mean.?rev|volatil.{0,10}regime)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "pipeline_run",
        [
            re.compile(
                r"\b(run.{0,20}pipeline|trigger.{0,20}pipeline|pipeline.{0,20}run|analyze.{0,20}(MES|MNQ|MCL|MGC|SPY))\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(run.{0,10}signal|fire.{0,10}pipeline|kick.{0,10}off.{0,10}pipeline)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "position",
        [
            re.compile(
                r"\b(position|open.?trade|paper.?trade|current.?trade|portfolio|holding|exposure)\b",
                re.IGNORECASE,
            ),
        ],
    ),
]


def _classify_intent(question: str) -> str:
    """Rule-based intent classifier.  Returns one of _SUPPORTED_INTENTS."""
    for intent, patterns in _INTENT_PATTERNS:
        for pat in patterns:
            if pat.search(question):
                return intent
    return "unknown"


# ── Handlers ────────────────────────────────────────────────────────────────


def _handle_health(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Query /health endpoint and summarise the result."""
    import urllib.error
    import urllib.request

    url = "http://127.0.0.1:8010/health"
    try:
        from config import settings as _cfg

        req = urllib.request.Request(url, headers={"X-API-Key": _cfg.API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        status = data.get("status", "unknown")
        tv = data.get("tradingview_mcp_healthy", False)
        llm = data.get("llm_path_healthy", False)
        # /health emits flat ibkr_*_connected booleans (not nested dicts).
        # Fall back to legacy execution_ib/data_ib dict shape just in case.
        ib_exec_ok = data.get("ibkr_execution_connected")
        if ib_exec_ok is None:
            ib_exec = data.get("execution_ib", {})
            ib_exec_ok = (
                ib_exec.get("connected", False) if isinstance(ib_exec, dict) else bool(ib_exec)
            )
        ib_data_ok = data.get("ibkr_data_connected")
        if ib_data_ok is None:
            ib_data = data.get("data_ib", {})
            ib_data_ok = (
                ib_data.get("connected", False) if isinstance(ib_data, dict) else bool(ib_data)
            )
        ks = data.get("kill_switch_active", False)

        summary = (
            f"Engine status: {status.upper()}. "
            f"TradingView MCP: {'healthy' if tv else 'down'}. "
            f"LLM path: {'healthy' if llm else 'down'}. "
            f"IB execution: {'connected' if ib_exec_ok else 'disconnected'}. "
            f"IB data: {'connected' if ib_data_ok else 'disconnected'}. "
            f"Kill switch: {'ACTIVE' if ks else 'inactive'}."
        )
        return summary, [url], []

    except urllib.error.URLError as exc:
        return (
            f"Could not reach the engine health endpoint ({url}): {exc}. "
            "The engine may be starting up or port 8010 is not bound.",
            [url],
            [],
        )
    except Exception as exc:
        return f"Health check failed: {exc}", [url], []


def _handle_bookmark_search(
    question: str, context: dict | None
) -> tuple[str, list[str], list[str]]:
    """Full-text search across the discord_bookmarks SQLite table."""
    import os
    import sqlite3

    # Extract a search term: everything after 'bookmarks' or 'bookmark' + optional 'for/about'
    term_match = re.search(
        r"\bbookmark(?:s)?\b.{0,20}?(?:for|about|containing|with|on)?\s+(.+)$",
        question,
        re.IGNORECASE,
    )
    if not term_match:
        # fall back: take the last word(s) that aren't stop-words
        words = [
            w
            for w in question.split()
            if len(w) > 3
            and w.lower()
            not in {"search", "find", "about", "look", "bookmark", "bookmarks", "query", "show"}
        ]
        search_term = " ".join(words[-3:]) if words else question
    else:
        search_term = term_match.group(1).strip()

    db_path = os.environ.get("DB_PATH", "data/jarvis_trader.db")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT embed_title AS title, url, embed_description AS summary,
                       source_type AS channel_name, posted_at AS bookmarked_at
                FROM discord_bookmarks
                WHERE embed_title LIKE ? OR embed_description LIKE ?
                   OR content LIKE ? OR url LIKE ?
                ORDER BY posted_at DESC
                LIMIT 5
                """,
                (
                    f"%{search_term}%",
                    f"%{search_term}%",
                    f"%{search_term}%",
                    f"%{search_term}%",
                ),
            ).fetchall()

        if not rows:
            return (
                f"No bookmarks matched '{search_term}'. "
                "Try a broader search term or use 'recent bookmarks' to see the latest.",
                [f"sqlite://{db_path}#discord_bookmarks"],
                [],
            )

        lines = [f"Found {len(rows)} bookmark(s) matching '{search_term}':"]
        sources: list[str] = []
        for row in rows:
            title = row["title"] or row["url"] or "(no title)"
            lines.append(f"- {title} ({row['channel_name'] or 'unknown channel'})")
            if row["url"]:
                sources.append(row["url"])

        return "\n".join(lines), sources, []

    except Exception as exc:
        return (
            f"Bookmark search failed: {exc}. The discord_bookmarks table may not exist yet.",
            [],
            [],
        )


def _handle_bookmark_recent(
    question: str, context: dict | None
) -> tuple[str, list[str], list[str]]:
    """Return the most recent N bookmarks."""
    import os
    import sqlite3

    # Look for a number in the question ("last 10 bookmarks", "5 recent")
    n_match = re.search(r"\b(\d{1,3})\b", question)
    limit = int(n_match.group(1)) if n_match else 10
    limit = min(limit, 50)  # cap at 50

    db_path = os.environ.get("DB_PATH", "data/jarvis_trader.db")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT embed_title AS title, url,
                       source_type AS channel_name, posted_at AS bookmarked_at
                FROM discord_bookmarks
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        if not rows:
            return (
                "No bookmarks found in the database yet. "
                "The Discord bookmark ingestion pipeline may not have run.",
                [],
                [],
            )

        lines = [f"Most recent {len(rows)} bookmark(s):"]
        sources: list[str] = []
        for row in rows:
            title = row["title"] or row["url"] or "(no title)"
            ts = (row["bookmarked_at"] or "")[:10]
            lines.append(f"- [{ts}] {title} ({row['channel_name'] or 'unknown'})")
            if row["url"]:
                sources.append(row["url"])

        return "\n".join(lines), sources, []

    except Exception as exc:
        return (
            f"Could not retrieve recent bookmarks: {exc}.",
            [],
            [],
        )


def _handle_commentary(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Search Corey auction-theory commentary via the discord MCP data."""
    import os
    import sqlite3

    # Extract search term from the question
    term_match = re.search(
        r"(?:commentary|corey|market.?update).{0,20}?(?:about|for|on|regarding)?\s+(.+)$",
        question,
        re.IGNORECASE,
    )
    if term_match:
        search_term = term_match.group(1).strip()
    else:
        # Pull last meaningful words
        words = [
            w
            for w in question.split()
            if len(w) > 4
            and w.lower()
            not in {
                "corey",
                "commentary",
                "market",
                "update",
                "search",
                "find",
                "show",
                "latest",
                "recent",
            }
        ]
        search_term = " ".join(words[-3:]) if words else ""

    db_path = os.environ.get("DB_PATH", "data/jarvis_trader.db")

    # Try discord_bot_signals / discord_commentary tables (whichever exists)
    tables_tried: list[str] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Check what tables are available
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            # Prefer discord_commentary; fall back to discord_bot_signals
            if "discord_commentary" in tables:
                tables_tried.append("discord_commentary")
                where = "WHERE text LIKE ?" if search_term else ""
                params = (f"%{search_term}%",) if search_term else ()
                rows = conn.execute(
                    f"SELECT author, text, posted_at FROM discord_commentary {where} "
                    "ORDER BY posted_at DESC LIMIT 5",
                    params,
                ).fetchall()
            elif "discord_bot_signals" in tables:
                tables_tried.append("discord_bot_signals")
                where = "WHERE notes LIKE ?" if search_term else ""
                params = (f"%{search_term}%",) if search_term else ()
                rows = conn.execute(
                    f"SELECT symbol, direction, notes, timestamp FROM discord_bot_signals {where} "
                    "ORDER BY timestamp DESC LIMIT 5",
                    params,
                ).fetchall()
            else:
                return (
                    "No commentary tables found in the database. "
                    "The Discord intelligence pipeline may not have ingested data yet.",
                    [],
                    [],
                )

        if not rows:
            label = f" matching '{search_term}'" if search_term else ""
            return (
                f"No Corey commentary{label} found. "
                "Try a broader search or check recent commentary without a filter.",
                [f"sqlite://{db_path}#{tables_tried[0]}"],
                [],
            )

        lines = [f"Corey commentary ({len(rows)} result(s)):"]
        for row in rows:
            d = dict(row)
            if "text" in d:
                snippet = (d["text"] or "")[:120]
                ts = (d.get("posted_at") or "")[:10]
                lines.append(f"- [{ts}] {snippet}...")
            else:
                lines.append(
                    f"- [{d.get('symbol','')}] {d.get('direction','')} — {d.get('notes','')[:80]}"
                )

        return (
            "\n".join(lines),
            [f"sqlite://{db_path}#{tables_tried[0]}"],
            [],
        )

    except Exception as exc:
        return f"Commentary lookup failed: {exc}", [], []


def _handle_briefing(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Composed pre-session briefing for a symbol."""
    import urllib.error
    import urllib.request

    from config import settings as _cfg

    # Extract symbol from question or context
    sym_match = re.search(r"\b(MES|MNQ|MCL|MGC|MYM|SPY|QQQ|AAPL|TSLA)\b", question, re.IGNORECASE)
    symbol = (
        sym_match.group(1).upper() if sym_match else ((context or {}).get("symbol", "MES").upper())
    )

    url = f"http://127.0.0.1:8010/discord/briefing/{symbol}"
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": _cfg.API_KEY})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        text = data.get("briefing") or data.get("summary") or json.dumps(data)[:500]
        return (
            f"Pre-session briefing for {symbol}:\n{text}",
            [url],
            [],
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return (
                f"No briefing available for {symbol}. "
                "The /discord/briefing endpoint may not have data for this symbol yet.",
                [url],
                [],
            )
        return f"Briefing request failed (HTTP {exc.code}): {exc}", [url], []
    except Exception as exc:
        return (
            f"Could not retrieve briefing for {symbol}: {exc}",
            [url],
            [],
        )


def _handle_tearsheet(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Return a link to the quantstats tearsheet."""
    import urllib.error
    import urllib.request

    from config import settings as _cfg

    sym_match = re.search(r"\b(MES|MNQ|MCL|MGC|MYM|SPY|QQQ)\b", question, re.IGNORECASE)
    symbol = (
        sym_match.group(1).upper() if sym_match else ((context or {}).get("symbol", "MES").upper())
    )

    url = f"http://127.0.0.1:8010/reports/quantstats?symbol={symbol}"
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": _cfg.API_KEY})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        sharpe = data.get("sharpe", "N/A")
        pf = data.get("profit_factor", "N/A")
        total_return = data.get("total_return", "N/A")
        summary = (
            f"Tearsheet for {symbol}: "
            f"Sharpe={sharpe}, Profit Factor={pf}, Total Return={total_return}. "
            f"Full report available at {url}."
        )
        return summary, [url], []
    except urllib.error.HTTPError as exc:
        return (
            f"Tearsheet for {symbol} not available (HTTP {exc.code}). "
            "Run a backtest first to generate tearsheet data.",
            [url],
            [],
        )
    except Exception as exc:
        return f"Could not retrieve tearsheet for {symbol}: {exc}", [url], []


def _handle_regime(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Return current market regime per symbol."""
    import urllib.error
    import urllib.request

    from config import settings as _cfg

    sym_match = re.search(r"\b(MES|MNQ|MCL|MGC|MYM|SPY|QQQ)\b", question, re.IGNORECASE)
    symbol = (
        sym_match.group(1).upper() if sym_match else ((context or {}).get("symbol", "MES").upper())
    )

    # Try the wfe_router regime endpoint first; fall back to signals endpoint
    url = f"http://127.0.0.1:8010/wfe/regime?symbol={symbol}"
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": _cfg.API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        regime = data.get("regime") or data.get("regime_type") or data.get("status", "unknown")
        bias = data.get("bias", "")
        extra = f" (bias: {bias})" if bias else ""
        return (
            f"Current market regime for {symbol}: {regime}{extra}.",
            [url],
            [],
        )
    except Exception as exc:
        return (
            f"Regime data for {symbol} unavailable: {exc}. "
            "The WFE regime endpoint may not have data for this instrument.",
            [url],
            [],
        )


def _fetch_health_for_preflight() -> dict:
    """Fetch /health and return a parsed dict.  Raises on network/parse error."""
    import urllib.request

    from config import settings as _cfg

    health_url = "http://127.0.0.1:8010/health"
    req = urllib.request.Request(health_url, headers={"X-API-Key": _cfg.API_KEY})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _handle_pipeline_run(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Trigger POST /pipeline/run for a symbol in paper mode.

    Safety pre-flight (evaluated before the POST):
      - kill_switch_active=True  → refused
      - status != "ok"           → refused
      - live_trading=True        → refused (paranoid guard; should always be False)

    If the /health fetch itself fails, the pre-flight is skipped and the pipeline
    run proceeds (fail-open) with a warning logged.
    """
    import urllib.error
    import urllib.request

    from config import settings as _cfg

    sym_match = re.search(r"\b(MES|MNQ|MCL|MGC|MYM|SPY|QQQ)\b", question, re.IGNORECASE)
    symbol = (
        sym_match.group(1).upper() if sym_match else ((context or {}).get("symbol", "MES").upper())
    )

    health_url = "http://127.0.0.1:8010/health"

    # ── Safety pre-flight ────────────────────────────────────────────────────
    try:
        health_data = _fetch_health_for_preflight()
        status = health_data.get("status", "unknown")
        ks = bool(health_data.get("kill_switch_active", False))
        lt = bool(health_data.get("live_trading", False))

        if ks or status != "ok" or lt:
            reason = (
                f"status={status}, kill_switch_active={ks}, live_trading={lt}. "
                "Resolve via engine/risk/safety_layer.py and engine restart."
            )
            logger.warning("[jarvis/ask] pipeline_run refused by safety pre-flight: %s", reason)
            return (
                f"Refused: pipeline_run blocked by safety pre-flight. {reason}",
                [health_url],
                [],
            )
    except Exception as _pf_exc:
        logger.warning(
            "[jarvis/ask] pipeline_run safety pre-flight could not reach /health "
            "(proceeding fail-open): %s",
            _pf_exc,
        )

    # ── Execute pipeline run ─────────────────────────────────────────────────
    url = "http://127.0.0.1:8010/pipeline/run"
    payload = json.dumps({"symbol": symbol, "is_futures": True, "interval": "1h"}).encode()
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"X-API-Key": _cfg.API_KEY, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        action = data.get("final_action") or data.get("action") or "unknown"
        confidence = data.get("confidence") or data.get("fund_conviction") or 0
        summary = data.get("summary", "")
        answer = (
            f"Pipeline run for {symbol} complete. "
            f"Decision: {action.upper()} (confidence {confidence:.0%}). "
            f"{summary}"
        ).strip()
        return answer, [url], [f"pipeline_run:{symbol}:{action}"]
    except urllib.error.HTTPError as exc:
        return (
            f"Pipeline run for {symbol} failed (HTTP {exc.code}). "
            "Check engine logs for details.",
            [url],
            [],
        )
    except Exception as exc:
        return (
            f"Could not trigger pipeline for {symbol}: {exc}",
            [url],
            [],
        )


def _handle_position(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Return current paper positions."""
    import urllib.error
    import urllib.request

    from config import settings as _cfg

    url = "http://127.0.0.1:8010/portfolio/paper/positions"
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": _cfg.API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        positions = data.get("positions") or data.get("open_positions") or []
        if not positions:
            return "No open paper positions at this time.", [url], []

        lines = [f"Open paper positions ({len(positions)}):"]
        for pos in positions[:10]:
            sym = pos.get("symbol", "?")
            side = pos.get("side", "?")
            qty = pos.get("quantity") or pos.get("qty") or 0
            pnl = pos.get("unrealized_pnl") or pos.get("pnl") or 0
            lines.append(f"- {sym} {side.upper()} qty={qty} unrealized_pnl=${pnl:.2f}")

        return "\n".join(lines), [url], []
    except urllib.error.HTTPError as exc:
        return (
            f"Could not retrieve positions (HTTP {exc.code}).",
            [url],
            [],
        )
    except Exception as exc:
        return f"Position lookup failed: {exc}", [url], []


def _handle_unknown(question: str, context: dict | None) -> tuple[str, list[str], list[str]]:
    """Fallback handler — lists supported intents."""
    intent_descriptions = {
        "health": "engine/health, broker status, kill switch state",
        "bookmark_search": "search the Discord bookmark feed by keyword",
        "bookmark_recent": "list recent bookmarks from the Discord feed",
        "commentary": "search or summarise Corey auction-theory commentary",
        "briefing": "get a composed pre-session briefing for a symbol",
        "tearsheet": "fetch the quantstats tearsheet/performance report",
        "regime": "current market regime for a symbol (trending, choppy, etc.)",
        "pipeline_run": "trigger a paper-mode pipeline run for a symbol",
        "position": "current open paper positions and unrealized P&L",
    }
    lines = [
        "I can answer about the following topics — try rephrasing your question to match one of these:\n"
    ]
    for intent, desc in intent_descriptions.items():
        lines.append(f"  - {intent}: {desc}")
    return "\n".join(lines), [], []


# Intent → handler dispatch table
_HANDLERS: dict[str, Any] = {
    "health": _handle_health,
    "bookmark_search": _handle_bookmark_search,
    "bookmark_recent": _handle_bookmark_recent,
    "commentary": _handle_commentary,
    "briefing": _handle_briefing,
    "tearsheet": _handle_tearsheet,
    "regime": _handle_regime,
    "pipeline_run": _handle_pipeline_run,
    "position": _handle_position,
    "unknown": _handle_unknown,
}


# ── /jarvis/ask endpoint ────────────────────────────────────────────────────


@router.post("/ask", response_model=AskResponse, summary="Natural-language JARVIS command bridge")
async def ask_jarvis(request: AskRequest) -> AskResponse:
    """
    Route a free-text question to the appropriate JARVIS subsystem.

    Classification is rule-based (regex/keyword) — never LLM-driven.
    Safety-layer override attempts are immediately refused (intent='refused').
    """
    t0 = time.monotonic()
    question = request.question.strip()

    # Safety refusal gate — hardcoded, evaluated before any other logic
    if _is_refused(question):
        elapsed = int((time.monotonic() - t0) * 1000)
        _write_ask_log("refused", elapsed, 0, 0)
        return AskResponse(
            answer=(
                "Refused: safety-layer decisions are not routable through this surface. "
                "See engine/risk/safety_layer.py for the hardcoded safety logic."
            ),
            sources=[],
            actions_taken=[],
            elapsed_ms=elapsed,
            intent="refused",
        )

    intent = _classify_intent(question)
    handler = _HANDLERS.get(intent, _handle_unknown)

    try:
        answer, sources, actions_taken = await run_in_threadpool(handler, question, request.context)
    except Exception as exc:
        logger.exception("[jarvis/ask] handler %s raised unexpectedly", intent)
        answer = f"Handler for intent '{intent}' encountered an error: {exc}"
        sources = []
        actions_taken = []

    elapsed = int((time.monotonic() - t0) * 1000)
    _write_ask_log(intent, elapsed, len(sources), len(actions_taken))
    logger.info("[jarvis/ask] intent=%s elapsed_ms=%d sources=%d", intent, elapsed, len(sources))

    return AskResponse(
        answer=answer,
        sources=sources,
        actions_taken=actions_taken,
        elapsed_ms=elapsed,
        intent=intent,
    )


# ── /jarvis/analyze (existing) ──────────────────────────────────────────────


def _build_request(symbol: str, period: str) -> JarvisQuickAnalysisRequest:
    try:
        return JarvisQuickAnalysisRequest(symbol=symbol, period=period)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc


async def _run_jarvis_analysis(request: JarvisQuickAnalysisRequest) -> JarvisQuickAnalysisResponse:
    symbol = request.symbol
    period = request.period

    try:
        analysis_text = await run_in_threadpool(jarvis_analysis.analyze_symbol, symbol, period)
    except ImportError as exc:
        logger.warning("[JARVIS] dependency unavailable for %s (%s): %s", symbol, period, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("[JARVIS] analysis rejected for %s (%s): %s", symbol, period, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[JARVIS] analysis failed for %s (%s)", symbol, period)
        raise HTTPException(status_code=500, detail=f"Jarvis analysis failed: {exc}") from exc

    analysis_text = (analysis_text or "").strip()
    if not analysis_text:
        raise HTTPException(status_code=502, detail="Jarvis analysis returned no text")

    return JarvisQuickAnalysisResponse(
        symbol=symbol,
        period=period,
        analysis=analysis_text,
        model=jarvis_analysis.MODEL_NAME,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/analyze", response_model=JarvisQuickAnalysisResponse)
async def analyze_jarvis(symbol: str = "SPY", period: str = "5d"):
    """Analyze a symbol with the quick Gemini-backed Jarvis snapshot."""
    request = _build_request(symbol=symbol, period=period)
    return await _run_jarvis_analysis(request)


@router.post("/analyze", response_model=JarvisQuickAnalysisResponse)
async def analyze_jarvis_body(request: JarvisQuickAnalysisRequest):
    """Analyze a symbol from a typed request body."""
    return await _run_jarvis_analysis(request)
