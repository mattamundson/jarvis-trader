#!/usr/bin/env python3
"""
JARVIS Ask-Log Daily Aggregator — self-improving loop analysis layer.

Reads engine/logs/jarvis_ask.log (JSONL), aggregates by day, and writes a
vault summary to ~/master-jarvis/second-brain/raw/wiki/jarvis-daily-log/<YYYY-MM-DD>.md
for gbrain ingestion.

Each JSONL record must contain:
  timestamp     ISO-8601 string (UTC)
  question_hash sha256 hex of the question
  intent        string intent label (e.g. "market_analysis", "position_query", "unknown", "refused")
  elapsed_ms    int — request wall-clock time in milliseconds
  sources_count int — number of context sources consulted
  actions_count int — number of downstream actions taken

Usage (from project root):
  engine/.venv/Scripts/python scripts/analyze_jarvis_log.py
  engine/.venv/Scripts/python scripts/analyze_jarvis_log.py --date 2026-05-19
  engine/.venv/Scripts/python scripts/analyze_jarvis_log.py --log-file path/to/custom.log
  engine/.venv/Scripts/python scripts/analyze_jarvis_log.py --output-dir /custom/wiki/dir
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Default paths relative to project root (cwd)
DEFAULT_LOG_PATH = Path("engine/logs/jarvis_ask.log")
DEFAULT_OUTPUT_BASE = Path(
    os.path.expanduser("~/master-jarvis/second-brain/raw/wiki/jarvis-daily-log")
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_records(log_path: Path, target_date: date) -> list[dict[str, Any]]:
    """Read JSONL log, return records whose timestamp falls on target_date (UTC)."""
    if not log_path.exists():
        return []

    records: list[dict[str, Any]] = []
    date_prefix = target_date.isoformat()  # "YYYY-MM-DD"

    with log_path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Line %d: JSON parse error — %s", lineno, exc)
                continue

            ts = rec.get("timestamp", "")
            # Fast prefix check before full parse
            if not str(ts).startswith(date_prefix):
                # Try full parse to handle offsets / fractional seconds
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.astimezone(timezone.utc).date() != target_date:
                        continue
                except (ValueError, TypeError):
                    continue

            records.append(rec)

    return records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> int:
    """Compute p-th percentile (0–100) of a sorted list. Returns 0 for empty."""
    if not values:
        return 0
    sv = sorted(values)
    idx = (p / 100.0) * (len(sv) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return int(sv[lo])
    return int(sv[lo] + (sv[hi] - sv[lo]) * (idx - lo))


def aggregate(records: list[dict[str, Any]], target_date: date) -> dict[str, Any]:
    """Compute daily aggregate statistics from a list of JSONL records."""
    n = len(records)
    if n == 0:
        return {
            "date": target_date.isoformat(),
            "request_count": 0,
            "intent_counts": {},
            "unknown_rate": 0.0,
            "refused_rate": 0.0,
            "p50_ms": 0,
            "p95_ms": 0,
            "avg_sources": 0.0,
            "avg_actions": 0.0,
        }

    intent_counts: Counter[str] = Counter()
    elapsed_list: list[float] = []
    sources_list: list[float] = []
    actions_list: list[float] = []

    for rec in records:
        intent = str(rec.get("intent", "unknown")).strip() or "unknown"
        intent_counts[intent] += 1

        try:
            elapsed_list.append(float(rec["elapsed_ms"]))
        except (KeyError, TypeError, ValueError):
            pass

        try:
            sources_list.append(float(rec["sources_count"]))
        except (KeyError, TypeError, ValueError):
            pass

        try:
            actions_list.append(float(rec["actions_count"]))
        except (KeyError, TypeError, ValueError):
            pass

    unknown_count = intent_counts.get("unknown", 0)
    refused_count = intent_counts.get("refused", 0)

    return {
        "date": target_date.isoformat(),
        "request_count": n,
        "intent_counts": dict(intent_counts.most_common()),
        "unknown_rate": round(unknown_count / n, 4),
        "refused_rate": round(refused_count / n, 4),
        "p50_ms": percentile(elapsed_list, 50),
        "p95_ms": percentile(elapsed_list, 95),
        "avg_sources": (
            round(sum(sources_list) / len(sources_list), 2) if sources_list else 0.0
        ),
        "avg_actions": (
            round(sum(actions_list) / len(actions_list), 2) if actions_list else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _intent_table(intent_counts: dict[str, int], total: int) -> str:
    if not intent_counts:
        return "_No intent data._"
    lines = [
        "| Intent | Count | Share |",
        "|--------|------:|------:|",
    ]
    for intent, count in sorted(intent_counts.items(), key=lambda kv: -kv[1]):
        share = f"{count / total * 100:.1f}%" if total else "—"
        lines.append(f"| `{intent}` | {count} | {share} |")
    return "\n".join(lines)


def _synthesis(agg: dict[str, Any]) -> str:
    """Three-paragraph narrative interpretation of the aggregate."""
    n = agg["request_count"]
    intent_counts: dict[str, int] = agg["intent_counts"]
    unknown_rate = agg["unknown_rate"]
    refused_rate = agg["refused_rate"]
    p50 = agg["p50_ms"]
    p95 = agg["p95_ms"]
    date_str = agg["date"]

    if n == 0:
        return "_No /jarvis/ask requests were recorded on this date._"

    # Paragraph 1 — most-asked intents
    top_intents = list(intent_counts.items())[:3]
    top_names = ", ".join(f"`{k}` ({v})" for k, v in top_intents)
    para1 = (
        f"On {date_str}, JARVIS received {n} /ask request{'s' if n != 1 else ''}. "
        f"The most-requested intents were {top_names}. "
        f"These patterns reflect the primary cognitive load being placed on the system today."
    )

    # Paragraph 2 — unknown rate gap analysis
    unknown_pct = unknown_rate * 100
    if unknown_pct >= 20:
        gap_tone = (
            f"The unknown-intent rate is elevated at {unknown_pct:.1f}%, indicating that more than "
            f"one in five requests fall outside the current intent taxonomy. "
            f"These represent the highest-ROI candidates for new intent definitions in the next "
            f"training cycle."
        )
    elif unknown_pct >= 5:
        gap_tone = (
            f"The unknown-intent rate is moderate at {unknown_pct:.1f}%. "
            f"A handful of query patterns are not yet mapped to known intents. "
            f"Reviewing the raw unknown-intent logs for recurring themes would surface the next "
            f"intent to add."
        )
    else:
        gap_tone = (
            f"The unknown-intent rate is low at {unknown_pct:.1f}%, suggesting strong intent "
            f"coverage for today's query volume. Intent taxonomy appears well-matched to current "
            f"usage patterns."
        )
    para2 = gap_tone

    # Paragraph 3 — latency + refused patterns
    refused_pct = refused_rate * 100
    latency_note = f"Median latency was {p50}ms with a p95 of {p95}ms. "
    if p95 > 5000:
        latency_note += (
            "The p95 tail is above 5 s, which warrants a latency investigation. "
        )
    elif p95 > 2000:
        latency_note += "The p95 tail is moderate — consider caching warm context between requests. "
    else:
        latency_note += "Latency is within acceptable bounds. "

    if refused_pct > 0:
        latency_note += (
            f"Refused queries accounted for {refused_pct:.1f}% of traffic. "
            f"Reviewing refusal logs may reveal safety-gate miscalibrations or adversarial probing."
        )
    else:
        latency_note += "No refused queries were recorded today."

    para3 = latency_note

    return f"{para1}\n\n{para2}\n\n{para3}"


def render_markdown(agg: dict[str, Any]) -> str:
    """Produce the full daily markdown file content with YAML frontmatter."""
    date_str = agg["date"]
    n = agg["request_count"]
    unknown_rate = agg["unknown_rate"]
    refused_rate = agg["refused_rate"]
    p50 = agg["p50_ms"]
    p95 = agg["p95_ms"]
    intent_counts = agg["intent_counts"]

    tags_block = (
        "tags:\n" "  - jarvis-ask\n" "  - self-improving-loop\n" "  - daily-log"
    )

    frontmatter = (
        "---\n"
        f'source: "jarvis-ask-log"\n'
        f'kind: "daily-aggregate"\n'
        f'date: "{date_str}"\n'
        f"request_count: {n}\n"
        f"unknown_rate: {unknown_rate}\n"
        f"refused_rate: {refused_rate}\n"
        f"p50_ms: {p50}\n"
        f"p95_ms: {p95}\n"
        f"{tags_block}\n"
        "---"
    )

    table = _intent_table(intent_counts, n)
    synthesis = _synthesis(agg)

    body = (
        f"# JARVIS Ask Log — {date_str}\n\n"
        f"## Intent Distribution\n\n"
        f"{table}\n\n"
        f"## Summary\n\n"
        f"{synthesis}\n"
    )

    return f"{frontmatter}\n\n{body}"


# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------


def write_daily_file(content: str, output_dir: Path, target_date: date) -> Path:
    """Write (or overwrite) the daily markdown file. Creates parent dirs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{target_date.isoformat()}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate JARVIS /jarvis/ask log for a given date and write a vault summary."
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Date to aggregate (defaults to yesterday UTC).",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=None,
        help=f"Path to jarvis_ask.log (default: {DEFAULT_LOG_PATH}).",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help=f"Base output directory for daily .md files (default: {DEFAULT_OUTPUT_BASE}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve target date
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date value %r; expected YYYY-MM-DD.", args.date)
            return 1
    else:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    # Resolve paths
    log_path = Path(args.log_file) if args.log_file else DEFAULT_LOG_PATH
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_BASE

    logger.info("Aggregating %s from %s", target_date.isoformat(), log_path)

    if not log_path.exists():
        logger.info("Log file not found (%s) — nothing to aggregate.", log_path)
        return 0

    records = load_records(log_path, target_date)

    if not records:
        logger.info("No records found for %s in %s.", target_date.isoformat(), log_path)
        return 0

    agg = aggregate(records, target_date)
    content = render_markdown(agg)
    out_path = write_daily_file(content, output_dir, target_date)

    logger.info(
        "Wrote %d-record aggregate to %s (unknown=%.1f%%, p50=%dms, p95=%dms)",
        agg["request_count"],
        out_path,
        agg["unknown_rate"] * 100,
        agg["p50_ms"],
        agg["p95_ms"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
