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
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_health_snapshots_ts ON health_snapshots(ts_utc)"
    )
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

        brokers = payload.get("brokers", {}) or {}
        data_ib = payload.get("data_ib_connected")
        exec_ib = payload.get("execution_ib_connected")
        if data_ib is None:
            data_ib = brokers.get("data_ib_connected")
        if exec_ib is None:
            exec_ib = brokers.get("execution_ib_connected")

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
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
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
    payload = json.dumps({"content": f":rotating_light: **JARVIS WATCHDOG** — {message}", "username": "JARVIS"})
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

    if not force and not _within_trading_hours(now_et):
        logger.debug("Outside trading hours (%s ET) — exiting.", now_et.strftime("%H:%M"))
        return {"skipped": True, "reason": "outside_trading_hours"}

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

    alerts = detect_transitions(rows)
    for alert in alerts:
        _send_discord_alert(alert, no_discord=no_discord)

    return {
        "ts_utc": ts_utc,
        "reachable": reachable,
        "alerts": alerts,
        "status": payload.get("status") if payload else None,
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
