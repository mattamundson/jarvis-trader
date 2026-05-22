"""
JARVIS TRADER — Engine Health Watchdog
=======================================
Single-shot poll of http://127.0.0.1:8010/health.  Writes one row to
health_snapshots, then fires Discord alerts on state transitions.

Run every 5 minutes during trading hours via Windows Task Scheduler
(Jarvis-HealthWatchdog).  The script itself guards the trading-hours window
so an always-on 5-minute trigger works safely outside market hours.

Usage (from jarvis-trader root):
    engine/.venv/Scripts/python -m engine.scripts.health_watchdog
    engine/.venv/Scripts/python -m engine.scripts.health_watchdog --no-discord
    engine/.venv/Scripts/python -m engine.scripts.health_watchdog --url http://127.0.0.1:9999
    engine/.venv/Scripts/python -m engine.scripts.health_watchdog --force

Flags:
    --no-discord   Log alerts to stdout only; do not POST to Discord.
    --url URL      Override engine base URL (default http://127.0.0.1:8010).
    --force        Run even outside trading hours (useful for smoke testing).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("health_watchdog")

_ET = ZoneInfo("America/New_York")
_DB_PATH = _ENGINE_DIR / "data" / "jarvis_trader.db"
_HEALTH_TIMEOUT = 5

_MARKET_OPEN_H = 9
_MARKET_OPEN_M = 25
_MARKET_CLOSE_H = 16
_MARKET_CLOSE_M = 5

_SUSTAINED_ALERT_POLLS = 3

# pm2 restart-rate alerting.
# Phase 6.2 (2026-05-20): alert when the engine has restarted too many times
# inside a rolling window — distinguishes operator-driven restarts (1-2/hr is
# normal during dev) from actual instability (>=4 inside 60 min).
# History is a JSON list of {"ts_utc": ISO, "restart_count": int} entries,
# capped at _PM2_HISTORY_MAX_ENTRIES and self-trimming on each write.
_PM2_HISTORY_FILE = _ENGINE_DIR / "data" / "pm2_restart_history.json"
_PM2_WINDOW_MINUTES = 60
_PM2_RESTART_THRESHOLD = 4
_PM2_HISTORY_MAX_ENTRIES = 36  # 3h at 5-min poll cadence

_DISCORD_WEBHOOK = (
    os.getenv("JARVIS_DISCORD_APPROVAL_WEBHOOK") or os.getenv("DISCORD_WEBHOOK_URL") or ""
).strip()


# ---------------------------------------------------------------------------
# Trading-hours guard
# ---------------------------------------------------------------------------


def _within_trading_hours(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    open_mins = _MARKET_OPEN_H * 60 + _MARKET_OPEN_M
    close_mins = _MARKET_CLOSE_H * 60 + _MARKET_CLOSE_M
    now_mins = now_et.hour * 60 + now_et.minute
    return open_mins <= now_mins <= close_mins


# ---------------------------------------------------------------------------
# pm2 restart-rate tracking
# ---------------------------------------------------------------------------


def _resolve_pm2_cmd() -> str | None:
    """Locate the pm2 CLI. Returns None if unavailable.

    Tries PATH first, then the known pnpm-installed Windows path.
    """
    found = shutil.which("pm2") or shutil.which("pm2.cmd")
    if found:
        return found
    win_pnpm_path = Path(os.path.expandvars(r"%LOCALAPPDATA%\pnpm\pm2.CMD"))
    if win_pnpm_path.exists():
        return str(win_pnpm_path)
    return None


def _get_pm2_restart_count(app_name: str = "jarvis-engine") -> int | None:
    """Return restart count for `app_name` per `pm2 jlist`, or None if unknown.

    None is treated as "unknown" (skip alerting) rather than 0 to avoid
    false-positive deltas when pm2 is unreachable or the daemon is mid-cycle.

    Windows note: pm2 ships as a `.CMD` shim that hangs when invoked via
    Python's subprocess with a plain list-arg form. Routing through `cmd.exe`
    (or `shell=True` on win32) lets the shim execute cleanly.
    """
    pm2 = _resolve_pm2_cmd()
    if not pm2:
        return None

    if sys.platform == "win32":
        cmd: list[str] | str = f'"{pm2}" jlist'
        kwargs: dict = {"shell": True}
    else:
        cmd = [pm2, "jlist"]
        kwargs = {}

    try:
        out = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=15,
            **kwargs,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    try:
        apps = json.loads(out)
    except json.JSONDecodeError:
        return None
    for app in apps:
        if not isinstance(app, dict):
            continue
        if app.get("name") == app_name:
            # pm2 stores restart count in pm2_env.restart_time
            env = app.get("pm2_env") or {}
            count = env.get("restart_time")
            if isinstance(count, int):
                return count
    return None


def _load_pm2_history() -> list[dict]:
    if not _PM2_HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(_PM2_HISTORY_FILE.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_pm2_history(history: list[dict]) -> None:
    _PM2_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _PM2_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    except OSError as exc:
        logger.warning("pm2 history write failed: %s", exc)


def detect_pm2_instability(
    now_utc: datetime,
    current_count: int | None,
    history: list[dict],
    window_minutes: int = _PM2_WINDOW_MINUTES,
    threshold: int = _PM2_RESTART_THRESHOLD,
) -> tuple[list[str], list[dict]]:
    """Return (alerts, updated_history).

    Alert fires when restart_count delta inside `window_minutes` is >= `threshold`.
    The delta is computed against the oldest history entry still inside the window.
    A single alert fires per crossing — the alert message includes the delta.
    """
    if current_count is None:
        return ([], history)

    entry = {"ts_utc": now_utc.isoformat(), "restart_count": current_count}
    new_history = history + [entry]
    cutoff = now_utc - timedelta(minutes=window_minutes + 60)  # keep a bit beyond window
    new_history = [
        e
        for e in new_history
        if datetime.fromisoformat(e["ts_utc"].replace("Z", "+00:00")) >= cutoff
    ][-_PM2_HISTORY_MAX_ENTRIES:]

    window_start = now_utc - timedelta(minutes=window_minutes)
    in_window = [
        e
        for e in new_history
        if datetime.fromisoformat(e["ts_utc"].replace("Z", "+00:00")) >= window_start
    ]
    if len(in_window) < 2:
        return ([], new_history)

    delta = current_count - in_window[0]["restart_count"]
    if delta < threshold:
        return ([], new_history)

    # Suppress repeated alerts for the same incident: only alert if the
    # previous poll's delta was below threshold (edge-triggered on crossing).
    if len(in_window) >= 3:
        prev_delta = in_window[-2]["restart_count"] - in_window[0]["restart_count"]
        if prev_delta >= threshold:
            return ([], new_history)

    msg = (
        f"ENGINE INSTABILITY — pm2 restart_count rose by {delta} "
        f"in last {window_minutes}m (threshold: {threshold}). "
        f"Current count: {current_count}. Likely cause: cascading "
        f"crash/auto-restart cycle. Check pm2 logs jarvis-engine and "
        f"engine-out.log for the trigger."
    )
    return ([msg], new_history)


# ---------------------------------------------------------------------------
# Engine poll
# ---------------------------------------------------------------------------


def _poll_health(base_url: str) -> tuple[bool, dict | None]:
    """
    GET <base_url>/health with _HEALTH_TIMEOUT.

    Returns (reachable, payload_or_None).
    """
    url = f"{base_url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=_HEALTH_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"_raw": body}
            return True, data
    except Exception as exc:
        logger.warning("Engine unreachable: %s", exc)
        return False, None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_table(conn)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS health_snapshots (
            ts_utc           TEXT NOT NULL PRIMARY KEY,
            status           TEXT NOT NULL,
            reachable        INTEGER NOT NULL,
            llm_healthy      INTEGER,
            tv_mcp_healthy   INTEGER,
            ibkr_data        INTEGER,
            ibkr_exec        INTEGER,
            kill_switch      INTEGER,
            uptime_seconds   REAL,
            raw_json         TEXT,
            fetched_at       TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_snapshots_ts ON health_snapshots(ts_utc)")
    conn.commit()


def _insert_snapshot(
    conn: sqlite3.Connection,
    ts_utc: str,
    reachable: bool,
    payload: dict | None,
    fetched_at: str,
) -> None:
    if reachable and payload:
        status = payload.get("status", "unknown")
        llm = _bool_col(payload.get("llm_path_healthy"))
        tv = _bool_col(payload.get("tradingview_mcp_healthy"))

        data_ib = payload.get("ibkr_data_connected")
        exec_ib = payload.get("ibkr_execution_connected")

        ks = _bool_col(payload.get("kill_switch_active"))
        uptime = payload.get("uptime_seconds")
        raw = json.dumps(payload)
    else:
        status = "unreachable"
        llm = tv = data_ib = exec_ib = ks = None
        uptime = None
        raw = None

    conn.execute(
        """
        INSERT OR IGNORE INTO health_snapshots
            (ts_utc, status, reachable, llm_healthy, tv_mcp_healthy,
             ibkr_data, ibkr_exec, kill_switch, uptime_seconds, raw_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts_utc,
            status,
            1 if reachable else 0,
            llm,
            tv,
            _bool_col(data_ib),
            _bool_col(exec_ib),
            ks,
            uptime,
            raw,
            fetched_at,
        ),
    )
    conn.commit()


def _bool_col(val) -> int | None:
    if val is None:
        return None
    return 1 if val else 0


def _last_n_rows(conn: sqlite3.Connection, n: int) -> list[dict]:
    cur = conn.execute(
        """
        SELECT ts_utc, reachable, llm_healthy, tv_mcp_healthy, kill_switch
        FROM health_snapshots
        ORDER BY ts_utc DESC
        LIMIT ?
        """,
        (n,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
    rows.reverse()
    return rows


# ---------------------------------------------------------------------------
# Transition detection
# ---------------------------------------------------------------------------


def detect_transitions(rows: list[dict]) -> list[str]:
    """
    Given the last N rows (oldest first, ending with the row just written),
    return a list of alert message strings that should be sent.

    Transition rules:
      1. reachable 1→0 on latest row: ENGINE DOWN
      2. reachable 0→1 on latest row: ENGINE BACK UP (downtime: Xm)
      3. tv_mcp_healthy 1→0 sustained >= _SUSTAINED_ALERT_POLLS consecutive: TV MCP unhealthy
      4. kill_switch changed 0→1 on latest row: KILL SWITCH ACTIVATED
      5. llm_healthy 1→0 sustained >= _SUSTAINED_ALERT_POLLS consecutive: LLM path unhealthy
    """
    if len(rows) < 2:
        return []

    alerts: list[str] = []
    current = rows[-1]
    prev = rows[-2]

    cur_reach = current["reachable"]
    prev_reach = prev["reachable"]

    if prev_reach == 1 and cur_reach == 0:
        alerts.append("ENGINE DOWN — /health unreachable")
        return alerts

    if prev_reach == 0 and cur_reach == 1:
        down_rows = 0
        for r in reversed(rows[:-1]):
            if r["reachable"] == 0:
                down_rows += 1
            else:
                break
        downtime_min = down_rows * 5
        alerts.append(f"ENGINE BACK UP (downtime: {downtime_min}m)")
        return alerts

    if cur_reach != 1:
        return alerts

    if current.get("kill_switch") == 1 and prev.get("kill_switch") != 1:
        alerts.append("KILL SWITCH ACTIVATED")

    if len(rows) >= _SUSTAINED_ALERT_POLLS:
        tail = rows[-_SUSTAINED_ALERT_POLLS:]
        if all(r.get("tv_mcp_healthy") == 0 and r["reachable"] == 1 for r in tail):
            prior_tail = rows[-(_SUSTAINED_ALERT_POLLS + 1) : -_SUSTAINED_ALERT_POLLS]
            if not prior_tail or prior_tail[-1].get("tv_mcp_healthy") != 0:
                alerts.append(
                    f"TV MCP unhealthy {_SUSTAINED_ALERT_POLLS * 5}m+ (tradingview_mcp_healthy=false)"
                )

        if all(r.get("llm_healthy") == 0 and r["reachable"] == 1 for r in tail):
            prior_tail = rows[-(_SUSTAINED_ALERT_POLLS + 1) : -_SUSTAINED_ALERT_POLLS]
            if not prior_tail or prior_tail[-1].get("llm_healthy") != 0:
                alerts.append(
                    f"LLM path unhealthy {_SUSTAINED_ALERT_POLLS * 5}m+ (llm_path_healthy=false)"
                )

    return alerts


# ---------------------------------------------------------------------------
# Discord alert
# ---------------------------------------------------------------------------


def _send_discord_alert(message: str, no_discord: bool) -> None:
    logger.info("ALERT: %s", message)
    if no_discord:
        return
    if not _DISCORD_WEBHOOK:
        logger.debug("JARVIS_DISCORD_APPROVAL_WEBHOOK not set — Discord alert skipped")
        return
    payload = json.dumps(
        {"content": f":rotating_light: **JARVIS WATCHDOG** — {message}", "username": "JARVIS"}
    )
    try:
        req = urllib.request.Request(
            _DISCORD_WEBHOOK,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                logger.warning("Discord webhook returned %s", resp.status)
    except Exception as exc:
        logger.warning("Discord webhook POST failed: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    db_path: Path = _DB_PATH,
    base_url: str = "http://127.0.0.1:8010",
    no_discord: bool = False,
    force: bool = False,
) -> dict:
    """
    Single poll cycle.  Returns a summary dict (used by tests).
    """
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(_ET)

    # pm2 restart-rate alerting — runs unconditionally (engine instability
    # outside trading hours still affects next-session readiness)
    pm2_count = _get_pm2_restart_count()
    pm2_history = _load_pm2_history()
    pm2_alerts, pm2_history = detect_pm2_instability(now_utc, pm2_count, pm2_history)
    _save_pm2_history(pm2_history)
    for alert in pm2_alerts:
        _send_discord_alert(alert, no_discord=no_discord)

    if not force and not _within_trading_hours(now_et):
        logger.debug("Outside trading hours (%s ET) — exiting.", now_et.strftime("%H:%M"))
        return {
            "skipped": True,
            "reason": "outside_trading_hours",
            "pm2_alerts": pm2_alerts,
            "pm2_restart_count": pm2_count,
        }

    ts_utc = now_utc.strftime("%Y-%m-%dT%H:%M:00Z")
    fetched_at = now_utc.isoformat()

    reachable, payload = _poll_health(base_url)
    logger.info(
        "Poll: reachable=%s status=%s",
        reachable,
        payload.get("status", "N/A") if payload else "N/A",
    )

    conn = _open_db(db_path)
    try:
        _insert_snapshot(conn, ts_utc, reachable, payload, fetched_at)
        rows = _last_n_rows(conn, _SUSTAINED_ALERT_POLLS + 2)
    finally:
        conn.close()

    rth_alerts = detect_transitions(rows)
    for alert in rth_alerts:
        _send_discord_alert(alert, no_discord=no_discord)

    return {
        "ts_utc": ts_utc,
        "reachable": reachable,
        "alerts": rth_alerts + pm2_alerts,
        "status": payload.get("status") if payload else None,
        "pm2_restart_count": pm2_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS engine health watchdog — single poll")
    parser.add_argument("--no-discord", action="store_true", help="Suppress Discord POSTs")
    parser.add_argument("--url", default="http://127.0.0.1:8010", help="Engine base URL")
    parser.add_argument("--force", action="store_true", help="Run outside trading hours")
    parser.add_argument("--db", default=str(_DB_PATH), help="Path to jarvis_trader.db")
    args = parser.parse_args()

    result = run(
        db_path=Path(args.db),
        base_url=args.url,
        no_discord=args.no_discord,
        force=args.force,
    )

    if result.get("skipped"):
        return 0

    logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
