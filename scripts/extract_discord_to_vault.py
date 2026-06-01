"""
extract_discord_to_vault.py
────────────────────────────────────────────────────────────────────────────
Extracts all Discord tables from jarvis_trader.db into the Obsidian vault at
second-brain/raw/.  Idempotent — skip files that already exist.

Usage:
    python scripts/extract_discord_to_vault.py [--dry-run] [--output-path PATH]

# Recommended invocation (writes directly to gbrain-ingested root):
#   engine/.venv/Scripts/python scripts/extract_discord_to_vault.py \
#     --output-path C:/Users/mattm/master-jarvis/second-brain/raw/_session-YYYY-MM-DD-amo

Tables handled:
    discord_bookmarks          → raw/discord-bookmarks/<author>-<id>.md
    discord_corey_commentary   → raw/discord-commentary/<YYYY-MM-DD>.md (daily agg)
    discord_corey_alerts       → raw/discord-corey-alerts/<id>.md
    discord_ib_reports         → raw/discord-ib-reports/<YYYY-MM-DD>-<symbol>.md
    discord_bot_signals        → raw/discord-bot-signals/<YYYY-MM>/<symbol>.md (monthly agg)
    discord_analyses           → raw/discord-analyses/<id>.md
    discord_daily_sentiment    → raw/discord-daily-sentiment/<YYYY-MM>.md (monthly agg)

Attachments: cdn.discordapp.com / media.discordapp.net URLs found in content
    → raw/discord-attachments/<message_id>/<filename>
    Time-boxed at 5 minutes total.

Canonical paths: see SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK for output-path conventions.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows (avoids cp1252 codec errors with special chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Configuration ────────────────────────────────────────────────────────────

DB_PATH = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\jarvis_trader.db")
DEFAULT_VAULT_RAW = Path(r"C:\Users\mattm\second-brain\raw")
CAPTURED_AT = "2026-05-20"
ATTACHMENT_TIMEOUT = 300  # 5 minutes
ATTACHMENT_UA = "jarvis-trader-vault/1.0"
PROGRESS_EVERY = 250

CDN_RE = re.compile(
    r"https://(?:cdn\.discordapp\.com|media\.discordapp\.net)/[^\s\)\]\">]+"
)


# ── Output-path resolver ──────────────────────────────────────────────────────


def resolve_output_path(raw_path: str) -> Path:
    """Resolve, validate, and return the output directory as a Path.

    Raises SystemExit with a clear message if the path does not exist,
    is not a directory, or is not writable.  This is called from argparse
    so errors surface before any DB work starts.
    """
    p = Path(raw_path).expanduser().resolve()
    if not p.exists():
        sys.exit(f"[ERROR] --output-path does not exist: {p}")
    if not p.is_dir():
        sys.exit(f"[ERROR] --output-path is not a directory: {p}")
    # Probe writability with a no-op temp file
    probe = p / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        sys.exit(f"[ERROR] --output-path is not writable ({exc}): {p}")
    return p


# ── Helpers ──────────────────────────────────────────────────────────────────


def sanitize_filename(s: str, max_len: int = 60) -> str:
    """Remove unsafe chars and truncate."""
    s = re.sub(r"[^\w\-]", "_", str(s or "unknown"))
    return s[:max_len].strip("_") or "unknown"


def iso_date(ts: str) -> str:
    """Extract YYYY-MM-DD from any ISO-ish timestamp string."""
    if not ts:
        return "0000-00-00"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
    return m.group(1) if m else "0000-00-00"


def iso_month(ts: str) -> str:
    """Extract YYYY-MM from any ISO-ish timestamp string."""
    d = iso_date(ts)
    return d[:7]


def yaml_str(v) -> str:
    """Minimal YAML-safe string quoting."""
    if v is None:
        return '""'
    s = str(v).replace('"', '\\"').replace("\n", " ").replace("\r", "")
    return f'"{s}"'


def write_file(path: Path, content: str, dry_run: bool) -> bool:
    """Write content to path; skip if exists.  Returns True if written."""
    if path.exists():
        return False  # already extracted
    if dry_run:
        return True  # would write
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def append_file(path: Path, content: str, dry_run: bool) -> None:
    """Append content (for daily/monthly aggregates).  Creates if missing."""
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


# ── Attachment downloader ─────────────────────────────────────────────────────


def download_attachments(
    urls: list, message_id: str, base_dir: Path, dry_run: bool, deadline: float
) -> dict:
    """Download CDN URLs into base_dir/<message_id>/<filename>.  Returns stats."""
    stats = {"downloaded": 0, "skipped": 0, "failed": 0, "bytes": 0}
    for url in urls:
        if time.time() > deadline:
            stats["failed"] += len(urls) - stats["downloaded"] - stats["skipped"]
            break
        try:
            fname = Path(url.split("?")[0].split("/")[-1]) or Path("attachment")
            dest = base_dir / str(message_id) / fname.name
            if dest.exists():
                stats["skipped"] += 1
                continue
            if dry_run:
                stats["downloaded"] += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": ATTACHMENT_UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            dest.write_bytes(data)
            stats["downloaded"] += 1
            stats["bytes"] += len(data)
        except Exception:
            stats["failed"] += 1
    return stats


# ── Table extractors ─────────────────────────────────────────────────────────


def extract_bookmarks(
    cur, vault: Path, dry_run: bool, attach_dir: Path, attach_deadline: float
) -> dict:
    outdir = vault / "discord-bookmarks"
    stats = {
        "written": 0,
        "skipped": 0,
        "failed": 0,
        "attach": {"downloaded": 0, "skipped": 0, "failed": 0, "bytes": 0},
    }
    index_rows = []  # for _INDEX.md

    cur.execute(
        """
        SELECT message_id, posted_at, url, domain, source_type,
               embed_title, embed_description, imported_at, content,
               author_id, author_name, analyzed_at, claimed_at, analysis_id,
               attachment_urls
        FROM discord_bookmarks
        ORDER BY posted_at
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    for i, row in enumerate(rows, 1):
        try:
            (
                message_id,
                posted_at,
                url,
                domain,
                source_type,
                embed_title,
                embed_description,
                imported_at,
                content,
                author_id,
                author_name,
                analyzed_at,
                claimed_at,
                analysis_id,
                attachment_urls,
            ) = row

            if not message_id:
                stats["failed"] += 1
                continue

            author_slug = sanitize_filename(author_name or author_id or "unknown")
            fname = f"{author_slug}-{message_id}.md"
            dest = outdir / fname

            # Determine jarvis_module routing
            jarvis_module = "signal-research"
            if domain in ("twitter.com", "x.com"):
                jarvis_module = "social-feed"
            elif domain == "github.com":
                jarvis_module = "dev-research"
            elif domain in ("youtube.com", "youtu.be"):
                jarvis_module = "media-feed"
            elif source_type == "article":
                jarvis_module = "article-feed"

            body = f"""---
source: "discord-bookmarks"
kind: "discord-bookmark"
url: {yaml_str(url)}
author: {yaml_str(author_name)}
author_id: {yaml_str(author_id)}
message_id: {yaml_str(message_id)}
captured_at: "{CAPTURED_AT}"
posted_at: {yaml_str(posted_at)}
domain: {yaml_str(domain)}
source_type: {yaml_str(source_type)}
analysis_id: {yaml_str(analysis_id)}
jarvis_module: "{jarvis_module}"
status: "extracted"
tags:
  - discord/bookmarks
  - domain/{sanitize_filename(domain or 'unknown')}
  - source/{sanitize_filename(source_type or 'unknown')}
---

# {embed_title or url or message_id}

**Author:** {author_name or author_id or 'unknown'}
**Posted:** {posted_at}
**URL:** {url or ''}
**Domain:** {domain or ''}
**Source type:** {source_type or ''}

## Description

{embed_description or ''}

## Content

{content or ''}
"""
            written = write_file(dest, body, dry_run)
            if written:
                stats["written"] += 1
            else:
                stats["skipped"] += 1

            # Attachments from content field
            cdn_urls = CDN_RE.findall(content or "")
            if cdn_urls and time.time() < attach_deadline:
                a = download_attachments(
                    cdn_urls, message_id, attach_dir, dry_run, attach_deadline
                )
                for k in ("downloaded", "skipped", "failed", "bytes"):
                    stats["attach"][k] += a[k]

            index_rows.append(
                {
                    "author": author_name or author_id,
                    "source_type": source_type or "unknown",
                    "month": iso_month(posted_at),
                }
            )

        except Exception as e:
            stats["failed"] += 1

        if i % PROGRESS_EVERY == 0:
            print(
                f"  [{i}/{total}] table=discord_bookmarks written={stats['written']} skipped={stats['skipped']}"
            )

    # Write _INDEX.md
    if not dry_run:
        _write_bookmark_index(outdir, index_rows)

    return stats


def _write_bookmark_index(outdir: Path, rows: list) -> None:
    by_author = defaultdict(int)
    by_source = defaultdict(int)
    by_month = defaultdict(int)
    for r in rows:
        by_author[r["author"]] += 1
        by_source[r["source_type"]] += 1
        by_month[r["month"]] += 1

    lines = [
        f"# Discord Bookmarks Index\n\nGenerated: {CAPTURED_AT}  Total: {len(rows)}\n"
    ]
    lines.append("\n## By Author\n")
    for k, v in sorted(by_author.items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines.append("\n## By Source Type\n")
    for k, v in sorted(by_source.items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines.append("\n## By Month\n")
    for k, v in sorted(by_month.items()):
        lines.append(f"- {k}: {v}")

    idx = outdir / "_INDEX.md"
    outdir.mkdir(parents=True, exist_ok=True)
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_commentary(
    cur, vault: Path, dry_run: bool, attach_dir: Path, attach_deadline: float
) -> dict:
    outdir = vault / "discord-commentary"
    stats = {
        "written": 0,
        "skipped": 0,
        "failed": 0,
        "attach": {"downloaded": 0, "skipped": 0, "failed": 0, "bytes": 0},
    }

    cur.execute(
        """
        SELECT message_id, timestamp, content, channel, author_id
        FROM discord_corey_commentary
        ORDER BY timestamp
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    # Group by date
    by_date = defaultdict(list)
    for row in rows:
        message_id, timestamp, content, channel, author_id = row
        d = iso_date(timestamp or "")
        by_date[d].append((message_id, timestamp, content, channel, author_id))

    dates = sorted(by_date.keys())
    written_days = 0
    total_msgs = 0

    for day_i, date in enumerate(dates):
        dest = outdir / f"{date}.md"
        msgs = by_date[date]

        if not dest.exists():
            # Build daily aggregate file
            header = f"""---
source: "discord-corey-commentary"
kind: "discord-daily-commentary"
date: "{date}"
captured_at: "{CAPTURED_AT}"
message_count: {len(msgs)}
jarvis_module: "market-commentary"
status: "extracted"
tags:
  - discord/commentary
  - corey-sures
  - date/{date}
---

# Corey Commentary — {date}

**Messages:** {len(msgs)}

---

"""
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(header, encoding="utf-8")

            # Append each message
            for message_id, timestamp, content, channel, author_id in msgs:
                entry = f"### {timestamp} — #{channel or 'general'}\n\n{content or ''}\n\n---\n\n"
                if not dry_run:
                    with dest.open("a", encoding="utf-8") as f:
                        f.write(entry)

                # Check for CDN URLs
                cdn_urls = CDN_RE.findall(content or "")
                if cdn_urls and time.time() < attach_deadline:
                    a = download_attachments(
                        cdn_urls, message_id, attach_dir, dry_run, attach_deadline
                    )
                    for k in ("downloaded", "skipped", "failed", "bytes"):
                        stats["attach"][k] += a[k]

            stats["written"] += 1
            written_days += 1
        else:
            stats["skipped"] += 1

        total_msgs += len(msgs)
        if (total_msgs // PROGRESS_EVERY) != (
            (total_msgs - len(msgs)) // PROGRESS_EVERY
        ):
            print(
                f"  [{total_msgs}/{total}] table=discord_corey_commentary days_written={written_days}"
            )

    return stats


def extract_corey_alerts(
    cur, vault: Path, dry_run: bool, attach_dir: Path, attach_deadline: float
) -> dict:
    outdir = vault / "discord-corey-alerts"
    stats = {"written": 0, "skipped": 0, "failed": 0}

    cur.execute(
        """
        SELECT id, message_id, timestamp, content, symbol, direction, price, source_channel, created_at
        FROM discord_corey_alerts
        ORDER BY timestamp
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    for i, row in enumerate(rows, 1):
        try:
            (
                row_id,
                message_id,
                timestamp,
                content,
                symbol,
                direction,
                price,
                source_channel,
                created_at,
            ) = row
            mid = message_id or str(row_id)
            dest = outdir / f"{sanitize_filename(symbol or 'unknown')}-{mid}.md"

            jarvis_module = "trade-alerts"
            if symbol in ("MES", "ES"):
                jarvis_module = "mes-alerts"
            elif symbol in ("MNQ", "NQ"):
                jarvis_module = "mnq-alerts"
            elif symbol in ("MCL", "CL"):
                jarvis_module = "mcl-alerts"
            elif symbol in ("MGC", "GC"):
                jarvis_module = "mgc-alerts"

            body = f"""---
source: "discord-corey-alerts"
kind: "discord-trade-alert"
message_id: {yaml_str(mid)}
captured_at: "{CAPTURED_AT}"
posted_at: {yaml_str(timestamp)}
symbol: {yaml_str(symbol)}
direction: {yaml_str(direction)}
price: {yaml_str(price)}
source_channel: {yaml_str(source_channel)}
jarvis_module: "{jarvis_module}"
status: "extracted"
tags:
  - discord/corey-alerts
  - symbol/{sanitize_filename(symbol or 'unknown')}
  - direction/{sanitize_filename(direction or 'unknown')}
---

# Alert: {direction or ''} {symbol or ''} @ {price or ''}

**Timestamp:** {timestamp}
**Symbol:** {symbol}
**Direction:** {direction}
**Price:** {price}
**Channel:** {source_channel}

## Content

{content or ''}
"""
            written = write_file(dest, body, dry_run)
            if written:
                stats["written"] += 1
            else:
                stats["skipped"] += 1

        except Exception:
            stats["failed"] += 1

        if i % PROGRESS_EVERY == 0:
            print(f"  [{i}/{total}] table=discord_corey_alerts")

    return stats


def extract_ib_reports(cur, vault: Path, dry_run: bool) -> dict:
    outdir = vault / "discord-ib-reports"
    stats = {"written": 0, "skipped": 0, "failed": 0}

    cur.execute(
        """
        SELECT id, message_id, timestamp, symbol, timeframe, ib_open, ib_high, ib_low, ib_close,
               ib_range, ibu50, ibu100, ibd50, ibd100, auction_context, trade_plan,
               raw_content, source_channel, created_at
        FROM discord_ib_reports
        ORDER BY timestamp
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    # Group by date+symbol (some may have multiple per day/symbol)
    seen = set()

    for i, row in enumerate(rows, 1):
        try:
            (
                row_id,
                message_id,
                timestamp,
                symbol,
                timeframe,
                ib_open,
                ib_high,
                ib_low,
                ib_close,
                ib_range,
                ibu50,
                ibu100,
                ibd50,
                ibd100,
                auction_context,
                trade_plan,
                raw_content,
                source_channel,
                created_at,
            ) = row

            mid = message_id or str(row_id)
            date = iso_date(timestamp or "")
            sym_slug = sanitize_filename(symbol or "unknown")
            # Unique per message_id
            fname = f"{date}-{sym_slug}-{mid}.md"
            dest = outdir / fname

            body = f"""---
source: "discord-ib-reports"
kind: "discord-ib-report"
message_id: {yaml_str(mid)}
captured_at: "{CAPTURED_AT}"
posted_at: {yaml_str(timestamp)}
symbol: {yaml_str(symbol)}
timeframe: {yaml_str(timeframe)}
ib_open: {yaml_str(ib_open)}
ib_high: {yaml_str(ib_high)}
ib_low: {yaml_str(ib_low)}
ib_close: {yaml_str(ib_close)}
ib_range: {yaml_str(ib_range)}
ibu50: {yaml_str(ibu50)}
ibu100: {yaml_str(ibu100)}
ibd50: {yaml_str(ibd50)}
ibd100: {yaml_str(ibd100)}
source_channel: {yaml_str(source_channel)}
jarvis_module: "ib-analysis"
status: "extracted"
tags:
  - discord/ib-reports
  - symbol/{sym_slug}
  - date/{date}
---

# IB Report: {symbol} — {date}

**Timestamp:** {timestamp}
**Symbol:** {symbol} | **Timeframe:** {timeframe}

## IB Levels

| Field | Value |
|---|---|
| IB Open | {ib_open} |
| IB High | {ib_high} |
| IB Low | {ib_low} |
| IB Close | {ib_close} |
| IB Range | {ib_range} |
| IBU 50% | {ibu50} |
| IBU 100% | {ibu100} |
| IBD 50% | {ibd50} |
| IBD 100% | {ibd100} |

## Auction Context

{auction_context or ''}

## Trade Plan

{trade_plan or ''}

## Raw Content

{raw_content or ''}
"""
            written = write_file(dest, body, dry_run)
            if written:
                stats["written"] += 1
            else:
                stats["skipped"] += 1

        except Exception:
            stats["failed"] += 1

        if i % PROGRESS_EVERY == 0:
            print(
                f"  [{i}/{total}] table=discord_ib_reports written={stats['written']}"
            )

    return stats


def extract_bot_signals(cur, vault: Path, dry_run: bool) -> dict:
    """Monthly per-symbol aggregates to avoid 221K individual files."""
    outdir = vault / "discord-bot-signals"
    stats = {"written": 0, "skipped": 0, "failed": 0}

    cur.execute(
        """
        SELECT id, message_id, timestamp, symbol, timeframe, direction, signal_type,
               entry_price, target1, target2, stop1, stop2, win_rate, wins, losses,
               mfe, mae, rr, gain, draw, net, last_price, raw_description, source_channel
        FROM discord_bot_signals
        ORDER BY symbol, timestamp
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    # Group by (YYYY-MM, symbol)
    groups = defaultdict(list)
    for row in rows:
        (
            row_id,
            message_id,
            timestamp,
            symbol,
            timeframe,
            direction,
            signal_type,
            entry_price,
            target1,
            target2,
            stop1,
            stop2,
            win_rate,
            wins,
            losses,
            mfe,
            mae,
            rr,
            gain,
            draw,
            net,
            last_price,
            raw_description,
            source_channel,
        ) = row
        month = iso_month(timestamp or "")
        sym = sanitize_filename(symbol or "unknown")
        groups[(month, sym)].append(row)

    group_list = sorted(groups.keys())
    written = 0

    for gi, (month, sym) in enumerate(group_list):
        dest = outdir / month / f"{sym}.md"
        rows_in_group = groups[(month, sym)]

        if not dest.exists():
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                header = f"""---
source: "discord-bot-signals"
kind: "discord-bot-signals-monthly"
symbol: "{sym}"
month: "{month}"
captured_at: "{CAPTURED_AT}"
signal_count: {len(rows_in_group)}
jarvis_module: "bot-signals"
status: "extracted"
tags:
  - discord/bot-signals
  - symbol/{sym}
  - month/{month}
---

# Bot Signals: {sym} — {month}

**Signal count:** {len(rows_in_group)}

| Timestamp | Direction | Type | Entry | T1 | T2 | Stop | Win% | W | L | RR | Net |
|---|---|---|---|---|---|---|---|---|---|---|---|
"""
                dest.write_text(header, encoding="utf-8")

                with dest.open("a", encoding="utf-8") as f:
                    for row in rows_in_group:
                        (
                            row_id,
                            message_id,
                            timestamp,
                            symbol,
                            timeframe,
                            direction,
                            signal_type,
                            entry_price,
                            target1,
                            target2,
                            stop1,
                            stop2,
                            win_rate,
                            wins,
                            losses,
                            mfe,
                            mae,
                            rr,
                            gain,
                            draw,
                            net,
                            last_price,
                            raw_description,
                            source_channel,
                        ) = row
                        f.write(
                            f"| {timestamp} | {direction or ''} | {signal_type or ''} | "
                            f"{entry_price or ''} | {target1 or ''} | {target2 or ''} | "
                            f"{stop1 or ''} | {win_rate or ''} | {wins or ''} | {losses or ''} | "
                            f"{rr or ''} | {net or ''} |\n"
                        )
            stats["written"] += 1
            written += 1
        else:
            stats["skipped"] += 1

        processed = sum(len(groups[k]) for k in group_list[: gi + 1])
        if (processed // PROGRESS_EVERY) != (
            (processed - len(rows_in_group)) // PROGRESS_EVERY
        ):
            print(
                f"  [{processed}/{total}] table=discord_bot_signals groups_written={written}"
            )

    return stats


def extract_analyses(cur, vault: Path, dry_run: bool) -> dict:
    outdir = vault / "discord-analyses"
    stats = {"written": 0, "skipped": 0, "failed": 0}

    cur.execute(
        """
        SELECT id, bookmark_id, artifact_type, summary, structured_json, vault_path,
               gbrain_chunk_ids, model_used, cost_usd, error_text, retries, created_at
        FROM discord_analyses
        ORDER BY created_at
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    for i, row in enumerate(rows, 1):
        try:
            (
                row_id,
                bookmark_id,
                artifact_type,
                summary,
                structured_json,
                vault_path,
                gbrain_chunk_ids,
                model_used,
                cost_usd,
                error_text,
                retries,
                created_at,
            ) = row

            dest = outdir / f"{row_id}-{bookmark_id or 'unknown'}.md"

            # Parse structured_json safely
            parsed_json = ""
            if structured_json:
                try:
                    parsed = json.loads(structured_json)
                    parsed_json = json.dumps(parsed, indent=2)
                except Exception:
                    parsed_json = str(structured_json)[:2000]

            body = f"""---
source: "discord-analyses"
kind: "discord-analysis"
analysis_id: {yaml_str(row_id)}
bookmark_id: {yaml_str(bookmark_id)}
artifact_type: {yaml_str(artifact_type)}
model_used: {yaml_str(model_used)}
cost_usd: {yaml_str(cost_usd)}
vault_path: {yaml_str(vault_path)}
captured_at: "{CAPTURED_AT}"
created_at: {yaml_str(created_at)}
jarvis_module: "analysis-results"
status: "extracted"
tags:
  - discord/analyses
  - artifact/{sanitize_filename(artifact_type or 'unknown')}
---

# Analysis #{row_id} — {artifact_type or 'unknown'}

**Bookmark ID:** {bookmark_id}
**Model:** {model_used}
**Cost:** ${cost_usd or 0:.4f}
**Created:** {created_at}

## Summary

{summary or ''}

## Structured Output

```json
{parsed_json}
```

## Error

{error_text or 'None'}
"""
            written = write_file(dest, body, dry_run)
            if written:
                stats["written"] += 1
            else:
                stats["skipped"] += 1

        except Exception:
            stats["failed"] += 1

        if i % PROGRESS_EVERY == 0:
            print(f"  [{i}/{total}] table=discord_analyses written={stats['written']}")

    return stats


def extract_daily_sentiment(cur, vault: Path, dry_run: bool) -> dict:
    """Monthly aggregate files for daily sentiment."""
    outdir = vault / "discord-daily-sentiment"
    stats = {"written": 0, "skipped": 0, "failed": 0}

    cur.execute(
        """
        SELECT date, sentiment_score, post_count, source, computed_at
        FROM discord_daily_sentiment
        ORDER BY date
    """
    )
    rows = cur.fetchall()
    total = len(rows)

    # Group by YYYY-MM
    by_month = defaultdict(list)
    for row in rows:
        date, sentiment_score, post_count, source, computed_at = row
        month = (date or "0000-00")[:7]
        by_month[month].append(row)

    for month, month_rows in sorted(by_month.items()):
        dest = outdir / f"{month}.md"
        if not dest.exists():
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                header = f"""---
source: "discord-daily-sentiment"
kind: "discord-sentiment-monthly"
month: "{month}"
captured_at: "{CAPTURED_AT}"
entry_count: {len(month_rows)}
jarvis_module: "sentiment-analysis"
status: "extracted"
tags:
  - discord/daily-sentiment
  - month/{month}
---

# Daily Sentiment — {month}

**Entries:** {len(month_rows)}

| Date | Score | Post Count | Source |
|---|---|---|---|
"""
                dest.write_text(header, encoding="utf-8")

                with dest.open("a", encoding="utf-8") as f:
                    for (
                        date,
                        sentiment_score,
                        post_count,
                        source,
                        computed_at,
                    ) in month_rows:
                        score_str = (
                            f"{sentiment_score:.4f}"
                            if sentiment_score is not None
                            else ""
                        )
                        f.write(
                            f"| {date} | {score_str} | {post_count or ''} | {source or ''} |\n"
                        )

            stats["written"] += 1
        else:
            stats["skipped"] += 1

    print(
        f"  [{total}/{total}] table=discord_daily_sentiment months_written={stats['written']}"
    )
    return stats


# ── Last-extract counter ──────────────────────────────────────────────────────


def write_last_extract(vault: Path, summary: dict, dry_run: bool) -> None:
    # _LAST_EXTRACT.json lives at the output root so the idempotency check
    # is scoped to whichever --output-path was supplied, not a hardcoded subdir.
    # Prior to --output-path support it lived in discord-bookmarks/; it now
    # lives at vault/_LAST_EXTRACT.json so each target directory tracks its
    # own extraction state independently.
    dest = vault / "_LAST_EXTRACT.json"
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "output_path": str(vault),
        "tables": summary,
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract Discord tables from jarvis_trader.db into the Obsidian vault. "
            "Idempotent — skips files that already exist in the target directory. "
            "Each output directory maintains its own _LAST_EXTRACT.json so multiple "
            "target directories track their extraction state independently. "
            "See SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK for canonical --output-path conventions."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing any files.",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        metavar="PATH",
        help=(
            "Absolute path to the output root directory. "
            "Must exist, be a directory, and be writable. "
            "Default: C:\\Users\\mattm\\second-brain\\raw "
            "(preserves prior run behavior). "
            "Example: --output-path "
            "C:\\Users\\mattm\\master-jarvis\\second-brain\\raw\\_session-2026-05-20-amo"
        ),
    )
    args = parser.parse_args()
    dry_run = args.dry_run

    # Resolve the output path: caller-supplied or the historical default.
    if args.output_path is not None:
        vault_raw = resolve_output_path(args.output_path)
        print(f"Output path: {vault_raw}")
    else:
        vault_raw = DEFAULT_VAULT_RAW
        print(f"Output path (default): {vault_raw}")

    if dry_run:
        print("=== DRY RUN MODE - no files will be written ===")

    t0 = time.time()
    attach_deadline = t0 + ATTACHMENT_TIMEOUT
    attach_dir = vault_raw / "discord-attachments"

    # Create output dirs
    for d in [
        "discord-bookmarks",
        "discord-commentary",
        "discord-corey-alerts",
        "discord-ib-reports",
        "discord-bot-signals",
        "discord-daily-sentiment",
        "discord-analyses",
        "discord-attachments",
    ]:
        if not dry_run:
            (vault_raw / d).mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    cur = conn.cursor()

    summary = {}

    print("\n[1/7] Extracting discord_bookmarks ...")
    s = extract_bookmarks(cur, vault_raw, dry_run, attach_dir, attach_deadline)
    summary["discord_bookmarks"] = s
    print(
        f"  done: written={s['written']} skipped={s['skipped']} failed={s['failed']} | attach_dl={s['attach']['downloaded']} attach_bytes={s['attach']['bytes']}"
    )

    print("\n[2/7] Extracting discord_corey_commentary ...")
    s = extract_commentary(cur, vault_raw, dry_run, attach_dir, attach_deadline)
    summary["discord_corey_commentary"] = s
    print(
        f"  done: written(days)={s['written']} skipped={s['skipped']} failed={s['failed']}"
    )

    print("\n[3/7] Extracting discord_corey_alerts ...")
    s = extract_corey_alerts(cur, vault_raw, dry_run, attach_dir, attach_deadline)
    summary["discord_corey_alerts"] = s
    print(f"  done: written={s['written']} skipped={s['skipped']} failed={s['failed']}")

    print("\n[4/7] Extracting discord_ib_reports ...")
    s = extract_ib_reports(cur, vault_raw, dry_run)
    summary["discord_ib_reports"] = s
    print(f"  done: written={s['written']} skipped={s['skipped']} failed={s['failed']}")

    print("\n[5/7] Extracting discord_bot_signals ...")
    s = extract_bot_signals(cur, vault_raw, dry_run)
    summary["discord_bot_signals"] = s
    print(
        f"  done: written(group-files)={s['written']} skipped={s['skipped']} failed={s['failed']}"
    )

    print("\n[6/7] Extracting discord_analyses ...")
    s = extract_analyses(cur, vault_raw, dry_run)
    summary["discord_analyses"] = s
    print(f"  done: written={s['written']} skipped={s['skipped']} failed={s['failed']}")

    print("\n[7/7] Extracting discord_daily_sentiment ...")
    s = extract_daily_sentiment(cur, vault_raw, dry_run)
    summary["discord_daily_sentiment"] = s
    print(
        f"  done: written(months)={s['written']} skipped={s['skipped']} failed={s['failed']}"
    )

    conn.close()

    # Write counter file (lives at vault_raw root, scoped to this output path)
    write_last_extract(vault_raw, summary, dry_run)

    elapsed = time.time() - t0
    print(
        f"\n{'=== DRY RUN COMPLETE ===' if dry_run else '=== EXTRACTION COMPLETE ==='}"
    )
    print(f"Elapsed: {elapsed:.1f}s")
    total_written = sum(v.get("written", 0) for v in summary.values())
    print(f"Total file operations (written): {total_written}")
    for tbl, s in summary.items():
        print(
            f"  {tbl}: written={s.get('written',0)} skipped={s.get('skipped',0)} failed={s.get('failed',0)}"
        )


if __name__ == "__main__":
    main()
