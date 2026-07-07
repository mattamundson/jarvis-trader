"""
Daily Discord intelligence digest generator.

Queries corey_session_bias, top bot signals, and discord_daily_sentiment
for a given date, and writes a structured JSON file.

Usage:
    python -m engine.discord.digest_generator --date 2026-05-05 --output data/discord-digests/2026-05-05.json
    python -m engine.discord.digest_generator  # defaults: yesterday, auto-resolved DB path
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from datetime import date, timedelta, timezone
from pathlib import Path

try:  # dual-path import (engine.* package vs bare under engine/ cwd)
    from engine.analytics.outcome_hygiene import window_integrity
except ImportError:  # pragma: no cover
    from analytics.outcome_hygiene import window_integrity

logger = logging.getLogger(__name__)


def _default_db_path() -> str:
    # __file__ = engine/discord/digest_generator.py → up 2 levels → engine/
    # Canonical DB is engine/data/jarvis_trader.db (NOT the stale 733KB
    # repo-root data/jarvis_trader.db that was accidentally created).
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_root, "data", "jarvis_trader.db")


def _calibration_integrity(db_path: str, for_date: date, window_days: int = 30) -> dict:
    """Scan the sibling agent_feedback.db trade_outcomes table for corrupt /
    duplicate rows within the rolling window (analytics/outcome_hygiene).

    Standing detector for a repeat of the 2026-06-02 trade_outcomes pollution.
    Best-effort: returns a zeroed report (alert=False) when the DB or table is
    absent. Read-only (mode=ro), additive -- never mutates calibration state.
    """
    fb_path = Path(db_path).parent / "agent_feedback.db"
    report = {
        "total_outcomes": 0,
        "rows_excluded_corrupt": 0,
        "rows_excluded_duplicate": 0,
        "alert": False,
        "window_days": window_days,
    }
    if not fb_path.exists():
        return report
    cutoff = (for_date - timedelta(days=window_days)).isoformat()
    try:
        with sqlite3.connect(f"file:{fb_path}?mode=ro", uri=True) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM trade_outcomes WHERE timestamp >= ?", (cutoff,)
            ).fetchone()[0]
            corrupt, dup = window_integrity(conn, cutoff)
    except sqlite3.DatabaseError:
        return report
    report["total_outcomes"] = total
    report["rows_excluded_corrupt"] = corrupt
    report["rows_excluded_duplicate"] = dup
    report["alert"] = bool(corrupt or dup)
    return report


def _assess_llm_health(payload: dict) -> dict:
    """Pure assessment of /health llm fields -> digest block (I1, 2026-06-11).

    alert=True when the primary provider is unhealthy (single-leg operation:
    one fallback hiccup away from a dark LLM path). Kept pure for unit tests.
    """
    providers = payload.get("llm_providers") or {}
    primary_healthy = bool(providers.get("primary_healthy", True))
    report = {
        "engine_reachable": True,
        "active_provider": providers.get("active_provider"),
        "primary_provider": providers.get("primary_provider"),
        "primary_healthy": primary_healthy,
        "providers_available": providers.get("providers_available"),
        "google_fallback_count": payload.get("google_fallback_count", 0),
        "vertex_failover_count": payload.get("vertex_failover_count", 0),
        "llm_path_healthy": bool(payload.get("llm_path_healthy", False)),
        "alert": not primary_healthy,
    }
    return report


def _llm_provider_health(timeout_s: float = 5.0) -> dict:
    """Fetch /health and assess LLM provider state. Best-effort: when the
    engine is unreachable returns engine_reachable=False with alert=False
    (engine liveness is the watchdogs' job, not the digest's)."""
    import urllib.request

    fallback = {
        "engine_reachable": False,
        "active_provider": None,
        "primary_provider": None,
        "primary_healthy": None,
        "providers_available": None,
        "google_fallback_count": None,
        "vertex_failover_count": None,
        "llm_path_healthy": None,
        "alert": False,
    }
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/health", timeout=timeout_s
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _assess_llm_health(payload)
    except Exception:
        return fallback


def _assess_task_health(report_text: str, age_hours: float) -> dict:
    """Pure assessment of check-task-health.ps1 report text (I4, 2026-06-11).

    The Jarvis-TaskHealth-Daily monitor (~/scripts/check-task-health.ps1)
    already enumerates every Jarvis-*/JARVIS-*/Hermes-*/DP600-* task and
    writes task-health-latest.txt; this parser lifts its findings into the
    digest so failures reach the existing alert channel, not just a local
    toast. alert=True when enabled tasks are failing OR the report is stale
    (a dead monitor is itself silent degradation). Kept pure for unit tests.
    """
    import re

    report = {
        "present": True,
        "stale": age_hours > 26.0,
        "age_hours": round(age_hours, 1),
        "scanned": None,
        "failing_enabled": None,
        "failing_disabled": None,
        "failing_tasks": [],
        "alert": False,
    }
    m = re.search(r"Scanned (\d+) task", report_text)
    if m:
        report["scanned"] = int(m.group(1))
    m = re.search(
        r"Failing \(enabled\): (\d+)\s+Failing \(disabled, informational\): (\d+)",
        report_text,
    )
    if m:
        report["failing_enabled"] = int(m.group(1))
        report["failing_disabled"] = int(m.group(2))

    in_enabled_section = False
    for line in report_text.splitlines():
        if line.startswith("--- ENABLED tasks"):
            in_enabled_section = True
            continue
        if line.startswith("--- DISABLED tasks"):
            in_enabled_section = False
            continue
        if in_enabled_section:
            m = re.match(r"\s{2}(\S+)\s+(0x[0-9A-Fa-f]+)", line)
            if m:
                report["failing_tasks"].append(
                    {"name": m.group(1), "result": m.group(2)}
                )

    report["alert"] = bool(report["failing_enabled"]) or report["stale"]
    return report


def _task_health(report_path: "Path | None" = None) -> dict:
    """Read the latest task-health report and assess it. Best-effort: when the
    monitor has never written a report (file absent) returns present=False with
    alert=False so machines without the monitor (CI) stay quiet."""
    import time

    path = report_path or (
        Path.home() / ".claude" / "logs" / "task-health-latest.txt"
    )
    if not path.exists():
        return {
            "present": False,
            "stale": None,
            "age_hours": None,
            "scanned": None,
            "failing_enabled": None,
            "failing_disabled": None,
            "failing_tasks": [],
            "alert": False,
        }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return {
            "present": False,
            "stale": None,
            "age_hours": None,
            "scanned": None,
            "failing_enabled": None,
            "failing_disabled": None,
            "failing_tasks": [],
            "alert": False,
        }
    return _assess_task_health(text, age_hours)


def _assess_verdict_freshness(
    records: list,
    now,
    active_symbols,
    max_age_days: float = 7.0,
) -> dict:
    """Pure assessment of gate-v2 verdict freshness (I9, 2026-06-11).

    ``records`` are dicts with symbol/created_at(datetime)/verdict, one per
    verdict file. Per symbol, only the NEWEST verdict counts. alert=True when
    an ACTIVE symbol's newest verdict is older than ``max_age_days`` or has no
    verdict at all -- trading on a stale edge estimate is silent risk drift.
    Non-active symbols are reported informationally, never alerted.
    """
    active = [s.upper() for s in active_symbols]
    newest: dict = {}
    for rec in records:
        sym = str(rec.get("symbol", "")).upper()
        created = rec.get("created_at")
        if not sym or created is None:
            continue
        prev = newest.get(sym)
        if prev is None or created > prev["created_at"]:
            newest[sym] = {
                "created_at": created,
                "verdict": rec.get("verdict"),
                "files": 1 if prev is None else prev["files"] + 1,
            }
        else:
            prev["files"] += 1

    symbols = {}
    for sym, info in sorted(newest.items()):
        age_days = (now - info["created_at"]).total_seconds() / 86400.0
        symbols[sym] = {
            "age_days": round(age_days, 1),
            "newest": info["created_at"].isoformat(),
            "files": info["files"],
            "latest_verdict": info["verdict"],
            "active": sym in active,
        }

    stale_active = [
        s for s in active if s in symbols and symbols[s]["age_days"] > max_age_days
    ]
    missing_active = [s for s in active if s not in symbols]
    return {
        "active_symbols": active,
        "max_age_days": max_age_days,
        "symbols": symbols,
        "stale_active": stale_active,
        "missing_active": missing_active,
        "alert": bool(stale_active or missing_active),
    }


def _verdict_freshness(verdict_dir: "Path | None" = None, active_symbols=None) -> dict:
    """Read engine/data/gate_v2_verdicts/*.json (top level only -- archive/
    holds retired verdicts) and assess freshness. created_at comes from the
    JSON body, NOT file mtime: the verdict files are git-tracked, so a
    checkout refreshes every mtime and would fake freshness.

    Active symbols default to the approved paper traders; override with
    JARVIS_ACTIVE_PAPER_SYMBOLS (comma-separated) when promotions change.
    """
    from datetime import datetime as _dt

    if active_symbols is None:
        raw = os.getenv("JARVIS_ACTIVE_PAPER_SYMBOLS", "MES,MGC")
        active_symbols = [s.strip() for s in raw.split(",") if s.strip()]
    if verdict_dir is None:
        engine_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        verdict_dir = engine_root / "data" / "gate_v2_verdicts"

    records = []
    if verdict_dir.exists():
        for path in verdict_dir.glob("*.json"):
            try:
                body = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                created = _dt.fromisoformat(str(body.get("created_at")))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                records.append(
                    {
                        "symbol": body.get("symbol"),
                        "created_at": created,
                        "verdict": body.get("verdict"),
                    }
                )
            except (OSError, ValueError, TypeError):
                continue  # malformed verdict file -- skip, never crash the digest

    return _assess_verdict_freshness(
        records, now=_dt.now(timezone.utc), active_symbols=active_symbols
    )


def generate_digest(for_date: date, db_path: str) -> dict:
    """
    Build the daily digest dict for *for_date*.

    Returns a dict with: date, session_bias, sentiment_score, top_signals,
    corey_quote. Fields are None / [] when data is unavailable — callers must
    handle missing data gracefully.
    """
    date_str = for_date.isoformat()
    digest: dict = {
        "date": date_str,
        "session_bias": None,
        "sentiment_score": None,
        "sentiment_label": None,
        "top_signals": [],
        "corey_quote": None,
        "commentary_health": [],
        "calibration_integrity": None,
    }

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Session bias (LLM-extracted by CoreyCommentaryProcessor)
        row = conn.execute(
            "SELECT * FROM corey_session_bias WHERE date = ?", (date_str,)
        ).fetchone()
        if row:
            digest["session_bias"] = {
                "session_type": row["session_type"],
                "directional_bias": row["directional_bias"],
                "conviction": row["conviction"],
                "ib_bias": row["ib_bias"],
                "data_quality": row["data_quality"],
                "message_count": row["message_count"],
            }
            digest["corey_quote"] = row["corey_quote"]

        # Daily sentiment score — table may not exist on older DBs
        try:
            sent_row = conn.execute(
                "SELECT sentiment_score FROM discord_daily_sentiment WHERE date = ?",
                (date_str,),
            ).fetchone()
            if sent_row:
                score = sent_row["sentiment_score"]
                digest["sentiment_score"] = score
                if score > 0.2:
                    digest["sentiment_label"] = "bullish"
                elif score < -0.2:
                    digest["sentiment_label"] = "bearish"
                else:
                    digest["sentiment_label"] = "neutral"
        except sqlite3.OperationalError:
            pass

        # Last 7 days of corey_session_bias as a pipeline health indicator.
        # Use this to quickly detect if the commentary processor has been
        # running (data_quality='fresh'/'stale') vs silently failing ('none').
        try:
            health_rows = conn.execute(
                """
                SELECT date, data_quality, directional_bias, conviction, message_count
                FROM corey_session_bias
                WHERE date >= DATE(?, '-7 days')
                ORDER BY date DESC
                """,
                (date_str,),
            ).fetchall()
            digest["commentary_health"] = [dict(row) for row in health_rows]
        except sqlite3.OperationalError:
            pass

        # Top 5 bot signals by win_rate for the day
        signals = conn.execute(
            """
            SELECT symbol, direction, signal_type, entry_price,
                   target1, target2, stop1, win_rate, rr, timestamp
            FROM discord_bot_signals
            WHERE DATE(timestamp) = ?
              AND signal_type = 'ENTRY'
              AND win_rate IS NOT NULL
            ORDER BY win_rate DESC
            LIMIT 5
            """,
            (date_str,),
        ).fetchall()
        digest["top_signals"] = [dict(row) for row in signals]

    # Calibration integrity -- standing detector for a repeat of the 2026-06-02
    # trade_outcomes pollution. Reads the sibling agent_feedback.db (NOT the
    # signals db_path); additive + read-only. alert=True when corrupt/duplicate
    # rows are present so the daily digest surfaces it without a manual audit.
    digest["calibration_integrity"] = _calibration_integrity(db_path, for_date)

    # LLM provider health (I1, 2026-06-11): primary_healthy=false ran silent
    # for days while the system operated single-leg on the Gemini fallback.
    # Surface provider state in the daily digest so degradation reaches Amo.
    digest["llm_provider_health"] = _llm_provider_health()

    # Scheduled-task health (I4, 2026-06-11): FinanceSync failed silently for
    # 4 days because the local monitor only toasts. Lift its latest report
    # into the digest so failing Jarvis-* tasks reach the alert channel.
    digest["task_health"] = _task_health()

    # Gate-v2 verdict freshness (I9, 2026-06-11): a stale verdict means the
    # active symbols trade on outdated edge estimates. WARN when an active
    # symbol's newest verdict exceeds the freshness window.
    digest["gate_verdict_freshness"] = _verdict_freshness()

    return digest


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=None,
        help="YYYY-MM-DD (default: yesterday)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (default: engine/data/jarvis_trader.db)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path (default: data/discord-digests/YYYY-MM-DD.json relative to repo root)",
    )
    args = parser.parse_args()

    for_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    db_path = args.db or _default_db_path()

    if args.output:
        output_path = Path(args.output)
    else:
        engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo_root = os.path.dirname(engine_root)
        output_path = Path(repo_root) / "data" / "discord-digests" / f"{for_date.isoformat()}.json"

    try:
        digest = generate_digest(for_date, db_path)
    except Exception as exc:
        logger.error("Digest generation failed for %s: %s", for_date, exc, exc_info=True)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(digest, indent=2, default=str), encoding="utf-8")
    logger.info("Digest written to %s", output_path)

    # Log a one-line summary
    bias = digest.get("session_bias") or {}
    health_fresh = sum(
        1 for h in digest["commentary_health"] if h.get("data_quality") in ("fresh", "stale")
    )
    logger.info(
        "  %s | bias=%s conviction=%.2f | %d signals | sentiment=%s (%s) | health=%d/7d",
        for_date,
        bias.get("directional_bias", "n/a"),
        bias.get("conviction") or 0.0,
        len(digest["top_signals"]),
        f"{digest['sentiment_score']:.3f}" if digest["sentiment_score"] is not None else "n/a",
        digest["sentiment_label"] or "n/a",
        health_fresh,
    )
    ci = digest.get("calibration_integrity") or {}
    if ci.get("alert"):
        logger.warning(
            "  CALIBRATION INTEGRITY ALERT: %d corrupt + %d duplicate row(s) in "
            "trade_outcomes (last %dd) -- investigate agent_feedback.db",
            ci.get("rows_excluded_corrupt", 0),
            ci.get("rows_excluded_duplicate", 0),
            ci.get("window_days", 30),
        )
    else:
        logger.info(
            "  calibration integrity: clean (%d outcomes, last %dd)",
            ci.get("total_outcomes", 0),
            ci.get("window_days", 30),
        )
    lh = digest.get("llm_provider_health") or {}
    if lh.get("alert"):
        logger.warning(
            "  LLM SINGLE-LEG ALERT: primary provider %r unhealthy -- active=%r "
            "(gemini_fallbacks=%s, vertex_failovers=%s). One fallback hiccup from "
            "a dark LLM path; restore the primary.",
            lh.get("primary_provider"),
            lh.get("active_provider"),
            lh.get("google_fallback_count"),
            lh.get("vertex_failover_count"),
        )
    elif lh.get("engine_reachable"):
        logger.info(
            "  llm providers: primary=%r healthy, active=%r",
            lh.get("primary_provider"),
            lh.get("active_provider"),
        )
    th = digest.get("task_health") or {}
    if th.get("alert"):
        if th.get("stale"):
            logger.warning(
                "  TASK HEALTH ALERT: monitor report is STALE (%.1fh old) -- "
                "Jarvis-TaskHealth-Daily itself may have stopped running",
                th.get("age_hours") or -1.0,
            )
        if th.get("failing_enabled"):
            failing = "; ".join(
                f"{t['name']} {t['result']}" for t in th.get("failing_tasks", [])
            )
            logger.warning(
                "  TASK HEALTH ALERT: %d enabled scheduled task(s) failing: %s",
                th.get("failing_enabled"),
                failing or "(names unparsed -- see task-health-latest.txt)",
            )
    elif th.get("present"):
        logger.info(
            "  scheduled tasks: %s scanned, all enabled tasks healthy (report %.1fh old)",
            th.get("scanned"),
            th.get("age_hours") or -1.0,
        )
    vf = digest.get("gate_verdict_freshness") or {}
    if vf.get("alert"):
        details = []
        for sym in vf.get("stale_active", []):
            info = (vf.get("symbols") or {}).get(sym) or {}
            details.append(f"{sym} {info.get('age_days', '?')}d old")
        for sym in vf.get("missing_active", []):
            details.append(f"{sym} NO VERDICT")
        logger.warning(
            "  GATE VERDICT FRESHNESS ALERT: active symbol(s) on stale edge "
            "estimates (> %sd): %s -- rerun gate v2 validation",
            vf.get("max_age_days"),
            "; ".join(details),
        )
    else:
        ages = ", ".join(
            f"{s}={i['age_days']}d"
            for s, i in (vf.get("symbols") or {}).items()
            if i.get("active")
        )
        logger.info("  gate verdicts: active symbols fresh (%s)", ages or "none found")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
