#!/usr/bin/env python
"""
Vault Attribution Writer — cron-runnable script that writes daily and weekly
risk attribution Markdown files to the gbrain vault ingest directory.

Usage:
    python scripts/write_attribution_to_vault.py              # today only
    python scripts/write_attribution_to_vault.py --date 2026-05-20
    python scripts/write_attribution_to_vault.py --weekly     # ISO week rollup
    python scripts/write_attribution_to_vault.py --days 7     # last 7 days

Writes to:
    master-jarvis/second-brain/raw/_session-attribution/daily-<YYYY-MM-DD>.md
    master-jarvis/second-brain/raw/_session-attribution/weekly-<YYYY-WW>.md

Controlled by ENABLE_RISK_ATTRIBUTION in engine/.env (must be "1" or "true").
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Resolve paths ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
_VAULT_DIR = (
    _REPO_ROOT / "master-jarvis" / "second-brain" / "raw" / "_session-attribution"
)

# Allow importing engine modules when running from repo root
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))


def _load_env() -> None:
    """Load engine/.env into os.environ (simple KV parser, no python-dotenv required)."""
    env_file = _ENGINE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _attribution_enabled() -> bool:
    flag = os.environ.get("ENABLE_RISK_ATTRIBUTION", "0").lower()
    return flag in ("1", "true", "yes")


def _db_path() -> str:
    env = os.environ.get("DB_PATH", "")
    if env:
        return env
    return str(_ENGINE_DIR / "data" / "jarvis_trader.db")


# ── Frontmatter builder ───────────────────────────────────────────────────────


def _daily_frontmatter(d: date, total_pnl: float, top: str | None) -> str:
    return (
        "---\n"
        'source: "risk-attribution"\n'
        'kind: "daily-attribution"\n'
        f'date: "{d.isoformat()}"\n'
        f"total_pnl_usd: {round(total_pnl, 2)}\n"
        f'top_contributor: "{top or "none"}"\n'
        "tags:\n"
        "  - risk-attribution\n"
        "  - daily\n"
        "  - jarvis-trader/audit\n"
        "---\n\n"
    )


def _weekly_frontmatter(iso_week: str, total_pnl: float, top: str) -> str:
    return (
        "---\n"
        'source: "risk-attribution"\n'
        'kind: "weekly-attribution"\n'
        f'week: "{iso_week}"\n'
        f"total_pnl_usd: {round(total_pnl, 2)}\n"
        f'top_contributor: "{top}"\n'
        "tags:\n"
        "  - risk-attribution\n"
        "  - weekly\n"
        "  - jarvis-trader/audit\n"
        "---\n\n"
    )


# ── Write functions ───────────────────────────────────────────────────────────


def write_daily(target: date) -> Path:
    from analytics.risk_attribution import (
        attribute_daily_pnl,
        format_markdown,
        attribute_window,
    )

    result = attribute_daily_pnl(target, db_path=_db_path())
    # Wrap in a 1-day window for format_markdown
    window = attribute_window(target, target, db_path=_db_path())
    from analytics.risk_attribution import format_markdown

    body = format_markdown(window)
    frontmatter = _daily_frontmatter(target, result.total_pnl, result.top_contributor)

    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    out = _VAULT_DIR / f"daily-{target.isoformat()}.md"
    out.write_text(frontmatter + body, encoding="utf-8")
    print(f"[attribution] wrote {out}")
    return out


def write_weekly(week_start: date) -> Path:
    """Write a weekly rollup for the ISO week containing week_start."""
    from analytics.risk_attribution import attribute_window, format_markdown

    week_end = min(week_start + timedelta(days=6), date.today())
    iso_year, iso_week, _ = week_start.isocalendar()
    iso_week_str = f"{iso_year}-W{iso_week:02d}"

    window = attribute_window(week_start, week_end, db_path=_db_path())
    body = format_markdown(window)
    frontmatter = _weekly_frontmatter(
        iso_week_str, window.total_pnl, window.top_contributor_by_abs
    )

    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    out = _VAULT_DIR / f"weekly-{iso_week_str}.md"
    out.write_text(frontmatter + body, encoding="utf-8")
    print(f"[attribution] wrote {out}")
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> int:
    _load_env()

    parser = argparse.ArgumentParser(description="Write risk attribution to vault")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument(
        "--days", type=int, default=None, help="Write last N daily files"
    )
    parser.add_argument(
        "--weekly", action="store_true", help="Also write current ISO week rollup"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if ENABLE_RISK_ATTRIBUTION=0",
    )
    args = parser.parse_args()

    if not args.force and not _attribution_enabled():
        print(
            "[attribution] ENABLE_RISK_ATTRIBUTION=0 — skipping. "
            "Pass --force to override or set ENABLE_RISK_ATTRIBUTION=1 in engine/.env."
        )
        return 0

    today = datetime.now(tz=timezone.utc).date()

    if args.days is not None:
        for offset in range(args.days - 1, -1, -1):
            write_daily(today - timedelta(days=offset))
    else:
        target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else today
        write_daily(target)

    if args.weekly:
        # ISO week start = Monday
        week_start = today - timedelta(days=today.weekday())
        write_weekly(week_start)

    return 0


if __name__ == "__main__":
    sys.exit(main())
