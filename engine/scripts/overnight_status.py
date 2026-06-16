"""Render overnight-automation status to a self-contained HTML file.

Zero dependencies beyond stdlib. Run directly; output path printed on stdout.

Checks covered:
  1. JarvisDiscordDailyExport scheduled task (Task Scheduler 05:30 CT fire)
  2. Wrapper log tail (discord_weekly_export.log)
  3. discord_bookmarks table (Phase B pipeline — new channel 1490851279180660819)
  4. discord_corey_commentary (existing pipeline regression check)
  5. pnl_snapshots freshness (engine's 1-min safety loop health)
  6. Engine /health endpoint (process is alive and serving)

Intent: double-click a .bat, get a pretty HTML, eyeball for green vs red.
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


def _ps_date_to_iso(val: Any) -> str:
    """Convert PowerShell's /Date(ms)/ or /Date(ms+tz)/ wrapper to ISO 8601."""
    if not isinstance(val, str):
        return str(val)
    m = re.match(r"/Date\((-?\d+)", val)
    if not m:
        return val
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).astimezone().isoformat(sep=" ", timespec="seconds")


def _parse_utc(s: str) -> datetime | None:
    """Parse ISO timestamp; naive values are assumed UTC (engine convention)."""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "engine"
DB_PATH = ENGINE_DIR / "data" / "jarvis_trader.db"
WRAPPER_LOG = ENGINE_DIR / "logs" / "discord_weekly_export.log"
OUTPUT = Path(os.environ["USERPROFILE"]) / "overnight_status.html" if os.name == "nt" else Path.home() / "overnight_status.html"

TASK_NAME = "JarvisDiscordDailyExport"
BOOKMARK_BASELINE = 371  # Row count at Phase B load time (2026-04-20 01:30 CT)
HEALTH_URL = "http://localhost:8010/health"


def _status_class(ok: bool, warn: bool = False) -> str:
    if ok:
        return "ok"
    if warn:
        return "warn"
    return "bad"


def _ts_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ──────────────────────────────────────────────────────────────────────────────
# Checks — each returns (title, status_class, html_body_str)
# ──────────────────────────────────────────────────────────────────────────────


def check_scheduled_task() -> tuple[str, str, str]:
    title = "Windows Task Scheduler — JarvisDiscordDailyExport (05:30 CT)"
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-ScheduledTaskInfo -TaskName {TASK_NAME} | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return title, "bad", f"<p>PowerShell error: <code>{html.escape(r.stderr.strip()[:300])}</code></p>"
        info = json.loads(r.stdout or "{}")
        last_run = _ps_date_to_iso(info.get("LastRunTime", "unknown"))
        last_result = info.get("LastTaskResult", "unknown")
        next_run = _ps_date_to_iso(info.get("NextRunTime", "unknown"))
        ok = last_result == 0
        return (
            title,
            _status_class(ok),
            f"<table><tr><td>LastRunTime</td><td><code>{html.escape(str(last_run))}</code></td></tr>"
            f"<tr><td>LastTaskResult</td><td><code>{last_result}</code> "
            f"{'✓' if ok else '✗'}</td></tr>"
            f"<tr><td>NextRunTime</td><td><code>{html.escape(str(next_run))}</code></td></tr></table>",
        )
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


def check_wrapper_log() -> tuple[str, str, str]:
    title = "Discord export wrapper log tail"
    try:
        if not WRAPPER_LOG.exists():
            return title, "warn", f"<p>Log not found at <code>{html.escape(str(WRAPPER_LOG))}</code> (expected after first auto-fire)</p>"
        lines = WRAPPER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-6:] if len(lines) >= 6 else lines
        last_line = tail[-1] if tail else ""
        ok = "export complete" in last_line.lower()
        bad = "[ERROR]" in last_line or "exit" in last_line.lower() and "code=0" not in last_line.lower()
        body = "<pre>" + html.escape("\n".join(tail)) + "</pre>"
        return title, _status_class(ok, warn=not (ok or bad)), body
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


def _db_query_one(sql: str) -> Any:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


def check_bookmarks() -> tuple[str, str, str]:
    title = "Phase B bookmark pipeline (discord_bookmarks)"
    try:
        count, latest = _db_query_one("SELECT COUNT(*), MAX(posted_at) FROM discord_bookmarks")
        delta = count - BOOKMARK_BASELINE
        # Also grab source_type breakdown
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            types = conn.execute(
                "SELECT source_type, COUNT(*) FROM discord_bookmarks GROUP BY source_type ORDER BY COUNT(*) DESC"
            ).fetchall()
        finally:
            conn.close()
        ok = delta > 0
        warn = delta == 0
        type_rows = "".join(
            f"<tr><td>&nbsp;&nbsp;{html.escape(t or 'unknown')}</td><td>{c}</td></tr>"
            for t, c in types
        )
        body = (
            f"<table>"
            f"<tr><td>Row count</td><td>{count} <span class='delta'>(baseline 2026-04-20 01:30 CT: {BOOKMARK_BASELINE}, Δ {'+' if delta >= 0 else ''}{delta})</span></td></tr>"
            f"<tr><td>Latest posted_at</td><td><code>{html.escape(str(latest))}</code></td></tr>"
            f"<tr><td colspan='2'><strong>source_type breakdown:</strong></td></tr>"
            f"{type_rows}"
            f"</table>"
        )
        return title, _status_class(ok, warn=warn), body
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


def check_corey() -> tuple[str, str, str]:
    title = "Corey commentary (discord_corey_commentary) — regression check"
    try:
        count, latest = _db_query_one(
            "SELECT COUNT(*), MAX(timestamp) FROM discord_corey_commentary"
        )
        # Fresh if latest is within 7 days
        ok = False
        age_days: Any = "unknown"
        lt = _parse_utc(latest)
        if lt is not None:
            age_days = (datetime.now(tz=timezone.utc) - lt).days
            ok = age_days <= 7
        body = (
            f"<table>"
            f"<tr><td>Row count</td><td>{count}</td></tr>"
            f"<tr><td>Latest timestamp</td><td><code>{html.escape(str(latest))}</code></td></tr>"
            f"<tr><td>Age</td><td>{age_days if age_days == 'unknown' else f'{age_days} day(s)'}</td></tr>"
            f"</table>"
        )
        return title, _status_class(ok, warn=not ok), body
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


def check_pnl_snapshots() -> tuple[str, str, str]:
    title = "pnl_snapshots (engine safety loop, 1-min cadence)"
    try:
        count, latest = _db_query_one("SELECT COUNT(*), MAX(updated_at) FROM pnl_snapshots")
        # Fresh if latest is within 5 minutes
        ok = False
        age_str = "unknown"
        lt = _parse_utc(latest)
        if lt is not None:
            age_sec = (datetime.now(tz=timezone.utc) - lt).total_seconds()
            age_str = f"{age_sec/60:.1f} minute(s) old"
            ok = age_sec < 300
        body = (
            f"<table>"
            f"<tr><td>Row count</td><td>{count} <span class='delta'>(upserts in place; 1 row/day is expected)</span></td></tr>"
            f"<tr><td>Latest updated_at (UTC)</td><td><code>{html.escape(str(latest))}</code></td></tr>"
            f"<tr><td>Freshness</td><td>{age_str}</td></tr>"
            f"</table>"
        )
        return title, _status_class(ok, warn=not ok), body
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


def check_engine_health() -> tuple[str, str, str]:
    title = "Engine /health (port 8010)"
    try:
        # API key from the environment (the API_KEY the engine validates); never
        # hardcode the credential in source.
        req = Request(HEALTH_URL, headers={"X-API-Key": os.environ.get("API_KEY", "")})
        with urlopen(req, timeout=5) as resp:
            body_bytes = resp.read()
        health = json.loads(body_bytes.decode("utf-8"))
        # Show only a subset of keys to keep it readable
        summary_keys = ["status", "ibkr_connected", "market_data_connected", "llm_path_healthy", "uptime_seconds"]
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td><code>{html.escape(str(health.get(k, 'N/A')))}</code></td></tr>"
            for k in summary_keys
        )
        ok = health.get("status") in ("healthy", "ok", True)
        return title, _status_class(ok, warn=not ok), f"<table>{rows}</table>"
    except URLError as e:
        return title, "bad", f"<p>Engine not reachable: <code>{html.escape(str(e.reason))}</code></p>"
    except Exception as e:
        return title, "bad", f"<p>Exception: <code>{html.escape(str(e))}</code></p>"


# ──────────────────────────────────────────────────────────────────────────────
# HTML rendering
# ──────────────────────────────────────────────────────────────────────────────

CSS = """
:root { color-scheme: dark; }
body { font-family: -apple-system, "Segoe UI", sans-serif; background: #0f1419; color: #e6e6e6;
       margin: 0; padding: 2rem; max-width: 1000px; margin: 0 auto; }
h1 { margin-top: 0; font-weight: 500; letter-spacing: -0.02em; }
.generated { color: #8b949e; font-size: 0.85rem; margin-bottom: 2rem; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
        padding: 1rem 1.25rem; margin-bottom: 1rem; }
.card.ok   { border-left: 4px solid #3fb950; }
.card.warn { border-left: 4px solid #d29922; }
.card.bad  { border-left: 4px solid #f85149; }
.card h2 { margin: 0 0 0.5rem 0; font-size: 1.05rem; font-weight: 500; display: flex; align-items: center; gap: 0.5rem; }
.badge { font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 10px; font-weight: 500; }
.badge.ok   { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
.badge.warn { background: rgba(210, 153, 34, 0.15); color: #d29922; }
.badge.bad  { background: rgba(248, 81, 73, 0.15); color: #f85149; }
table { border-collapse: collapse; font-size: 0.9rem; }
table td { padding: 0.25rem 0.75rem 0.25rem 0; vertical-align: top; }
table td:first-child { color: #8b949e; white-space: nowrap; }
code { font-family: "Cascadia Code", Consolas, monospace; font-size: 0.85rem;
       background: #1c2128; padding: 0.1rem 0.4rem; border-radius: 3px; }
pre { background: #1c2128; border-radius: 4px; padding: 0.75rem; font-size: 0.8rem;
      overflow-x: auto; margin: 0.25rem 0 0 0; white-space: pre-wrap; word-break: break-word; }
.delta { color: #8b949e; font-size: 0.85rem; }
.summary { display: flex; gap: 1rem; margin-bottom: 1.5rem; padding: 1rem;
           background: #161b22; border-radius: 8px; border: 1px solid #30363d; }
.summary .count { font-size: 1.5rem; font-weight: 500; }
.summary .count.ok   { color: #3fb950; }
.summary .count.warn { color: #d29922; }
.summary .count.bad  { color: #f85149; }
"""


def render(results: list[tuple[str, str, str]]) -> str:
    ok_n = sum(1 for _, s, _ in results if s == "ok")
    warn_n = sum(1 for _, s, _ in results if s == "warn")
    bad_n = sum(1 for _, s, _ in results if s == "bad")

    cards_html = []
    for title, status, body in results:
        badge_text = {"ok": "✓ OK", "warn": "⚠ CHECK", "bad": "✗ FAIL"}[status]
        cards_html.append(
            f"""<div class="card {status}">
              <h2>{html.escape(title)} <span class="badge {status}">{badge_text}</span></h2>
              {body}
            </div>"""
        )

    overall = "ok" if bad_n == 0 and warn_n == 0 else ("warn" if bad_n == 0 else "bad")
    summary = (
        f"""<div class="summary">
          <div><span class="count ok">{ok_n}</span> <div style="color:#8b949e">OK</div></div>
          <div><span class="count warn">{warn_n}</span> <div style="color:#8b949e">Warn</div></div>
          <div><span class="count bad">{bad_n}</span> <div style="color:#8b949e">Fail</div></div>
          <div style="flex-grow:1"></div>
          <div><span class="count {overall}">{overall.upper()}</span> <div style="color:#8b949e">Overall</div></div>
        </div>"""
    )

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Overnight Automation Status — {_ts_now()}</title>
<style>{CSS}</style>
</head><body>
<h1>Overnight automation status</h1>
<div class="generated">Generated {_ts_now()} — refresh by re-running <code>check-overnight.bat</code></div>
{summary}
{''.join(cards_html)}
</body></html>"""


def main() -> int:
    checks = [
        check_scheduled_task,
        check_wrapper_log,
        check_bookmarks,
        check_corey,
        check_pnl_snapshots,
        check_engine_health,
    ]
    results = [c() for c in checks]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(results), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
