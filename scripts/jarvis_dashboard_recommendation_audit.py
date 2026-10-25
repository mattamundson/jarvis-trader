#!/usr/bin/env python3
"""Read-only JARVIS dashboard readiness + recommendation performance audit.

This script intentionally does not mutate engine config, risk settings, kill-switch
state, broker state, or trading-symbol routing. It only reads local HTTP endpoints
and the SQLite paper ledger, then writes evidence reports under docs/reports/.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
UTC = dt.timezone.utc

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "engine" / "data" / "jarvis_trader.db"
DASHBOARD_ENV = ROOT / "dashboard" / ".env.local"
REPORT_DIR = ROOT / "docs" / "reports"

PORTS = {
    "dashboard_3010": 3010,
    "engine_8010": 8010,
    "ibkr_paper_4002": 4002,
    "tradingview_cdp_9222": 9222,
    "master_api_8030": 8030,
}

ROUTES = {
    "dashboard_root": "http://127.0.0.1:3010/",
    "dashboard_mission_control": "http://127.0.0.1:3010/mission-control",
    "engine_health_proxy": "http://127.0.0.1:3010/api/engine/health",
    "runtime_snapshot": "http://127.0.0.1:3010/api/runtime-snapshot",
    "paper_status": "http://127.0.0.1:3010/api/engine/backtest/paper-status",
    "pnl_truth": "http://127.0.0.1:3010/api/engine/pnl/truth",
    "safety_status": "http://127.0.0.1:3010/api/engine/safety/status",
    "portfolio": "http://127.0.0.1:3010/api/engine/portfolio",
    "pending_approvals": "http://127.0.0.1:3010/api/engine/pipeline/pending-approvals?limit=50",
    "actionable": "http://127.0.0.1:3010/api/engine/pipeline/actionable",
    "drawdown_stats": "http://127.0.0.1:3010/api/engine/portfolio/stats/drawdown",
    "broker_status": "http://127.0.0.1:3010/api/engine/brokers/status",
    "engine_health_direct": "http://127.0.0.1:8010/health",
}


def parse_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def basic_auth_header() -> dict[str, str]:
    env = parse_env(DASHBOARD_ENV)
    user = env.get("DASHBOARD_AUTH_USER") or env.get("BASIC_AUTH_USER")
    dash_pass = (
        env.get("DASHBOARD_AUTH_PASS")
        or env.get("BASIC_AUTH_PASSWORD")
        or env.get("DASHBOARD_AUTH_PASSWORD")
        or env.get("BASIC_AUTH_PASS")
    )
    if not user or not dash_pass:
        return {}
    auth_b64 = base64.b64encode(f"{user}:{dash_pass}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {auth_b64}"}


def probe_port(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def http_get_json_or_text(url: str, headers: dict[str, str], timeout: float = 20.0) -> dict[str, Any]:
    started = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "jarvis-readiness-audit/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2_000_000).decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "latency_ms": round((time.time() - started) * 1000, 1),
                "content_type": resp.headers.get("content-type"),
                "json": parsed,
                "text_head": None if parsed is not None else body[:240],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": exc.code,
            "latency_ms": round((time.time() - started) * 1000, 1),
            "error": "HTTPError",
            "text_head": body[:240],
        }
    except Exception as exc:  # noqa: BLE001 - report exact read failure
        return {
            "ok": False,
            "status": None,
            "latency_ms": round((time.time() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def query_all(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in cur.execute(sql, params)]


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(CENTRAL)


def is_regular_trading_hours(timestamp: str | None) -> bool:
    parsed = parse_timestamp(timestamp)
    if parsed is None or parsed.weekday() >= 5:
        return False
    return dt.time(8, 30) <= parsed.time() <= dt.time(15, 0)


def audit_database() -> dict[str, Any]:
    result: dict[str, Any] = {"db_path": str(DB_PATH), "exists": DB_PATH.exists()}
    if not DB_PATH.exists():
        result["error"] = "database_missing"
        return result

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        tables = [row["name"] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        result["tables"] = tables
        result["table_counts"] = {}
        for table in tables:
            if any(token in table.lower() for token in ["trade", "pipeline", "decision", "approval", "wfe"]):
                result["table_counts"][table] = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        if table_exists(cur, "paper_trades"):
            result["paper_total"] = query_all(
                cur,
                """
                SELECT COUNT(*) AS rows,
                       COUNT(DISTINCT trade_id) AS distinct_trade_ids,
                       SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) AS closed_rows,
                       SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_rows,
                       ROUND(SUM(CASE WHEN status='closed' THEN COALESCE(pnl,0) ELSE 0 END), 2) AS closed_pnl,
                       SUM(CASE WHEN status='closed' AND COALESCE(pnl,0)>0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status='closed' AND COALESCE(pnl,0)<0 THEN 1 ELSE 0 END) AS losses,
                       MIN(entry_time) AS first_entry,
                       MAX(entry_time) AS last_entry,
                       MAX(exit_time) AS last_exit
                FROM paper_trades
                """,
            )[0]
            result["paper_by_status"] = query_all(
                cur,
                "SELECT status, COUNT(*) AS rows, ROUND(SUM(COALESCE(pnl,0)), 2) AS pnl_sum FROM paper_trades GROUP BY status ORDER BY status",
            )
            result["paper_by_symbol"] = query_all(
                cur,
                """
                SELECT symbol,
                       COUNT(*) AS rows,
                       COUNT(DISTINCT trade_id) AS distinct_trades,
                       SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) AS closed,
                       SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open,
                       ROUND(SUM(CASE WHEN status='closed' THEN COALESCE(pnl,0) ELSE 0 END), 2) AS closed_pnl,
                       SUM(CASE WHEN status='closed' AND COALESCE(pnl,0)>0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status='closed' AND COALESCE(pnl,0)<0 THEN 1 ELSE 0 END) AS losses,
                       MIN(entry_time) AS first_entry,
                       MAX(entry_time) AS last_entry,
                       MAX(exit_time) AS last_exit
                FROM paper_trades
                GROUP BY symbol
                ORDER BY closed_pnl DESC
                """,
            )
            closed_pnls = [
                float(row["pnl"] or 0.0)
                for row in cur.execute("SELECT pnl FROM paper_trades WHERE status='closed'")
            ]
            wins = [value for value in closed_pnls if value > 0]
            losses = [value for value in closed_pnls if value < 0]
            result["paper_distribution"] = {
                "closed": len(closed_pnls),
                "wins": len(wins),
                "losses": len(losses),
                "breakeven": sum(1 for value in closed_pnls if value == 0),
                "win_rate": round(len(wins) / len(closed_pnls), 4) if closed_pnls else None,
                "gross_profit": round(sum(wins), 2),
                "gross_loss": round(sum(losses), 2),
                "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
                "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
                "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
                "best": round(max(closed_pnls), 2) if closed_pnls else None,
                "worst": round(min(closed_pnls), 2) if closed_pnls else None,
            }
            paper_rows = query_all(
                cur,
                "SELECT trade_id, symbol, entry_time, exit_time, pnl, status, strategy_id, quote_source FROM paper_trades ORDER BY entry_time",
            )
            rth_rows = []
            for row in paper_rows:
                parsed = parse_timestamp(row.get("entry_time"))
                if is_regular_trading_hours(row.get("entry_time")):
                    enriched = dict(row)
                    enriched["entry_ct"] = parsed.isoformat() if parsed else None
                    rth_rows.append(enriched)
            by_symbol: dict[str, dict[str, Any]] = {}
            for row in rth_rows:
                bucket = by_symbol.setdefault(
                    row["symbol"],
                    {"rows": 0, "closed": 0, "closed_pnl": 0.0, "first": row["entry_ct"], "last": row["entry_ct"]},
                )
                bucket["rows"] += 1
                bucket["last"] = row["entry_ct"]
                if row["status"] == "closed":
                    bucket["closed"] += 1
                    bucket["closed_pnl"] += float(row["pnl"] or 0.0)
            for bucket in by_symbol.values():
                bucket["closed_pnl"] = round(bucket["closed_pnl"], 2)
            result["intraday_paper_test"] = {
                "rth_entries": len(rth_rows),
                "non_rth_entries": len(paper_rows) - len(rth_rows),
                "first_rth": rth_rows[0] if rth_rows else None,
                "last_rth": rth_rows[-1] if rth_rows else None,
                "by_symbol": by_symbol,
                "recent_examples": rth_rows[-12:],
            }

        if table_exists(cur, "pipeline_runs"):
            result["pipeline_total"] = query_all(
                cur,
                """
                SELECT COUNT(*) AS rows,
                       MIN(created_at) AS first_run,
                       MAX(created_at) AS last_run,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status!='completed' THEN 1 ELSE 0 END) AS not_completed
                FROM pipeline_runs
                """,
            )[0]
            result["pipeline_actions"] = query_all(
                cur,
                "SELECT COALESCE(final_action,'NULL') AS final_action, COUNT(*) AS rows, MIN(created_at) AS first_run, MAX(created_at) AS last_run FROM pipeline_runs GROUP BY COALESCE(final_action,'NULL') ORDER BY rows DESC",
            )
            result["pipeline_recent_non_hold"] = query_all(
                cur,
                """
                SELECT id, created_at, run_id, symbol, source, final_action, final_quantity,
                       requires_human, status, confidence, summary, error_message
                FROM pipeline_runs
                WHERE COALESCE(final_action,'hold')!='hold'
                ORDER BY created_at DESC
                LIMIT 25
                """,
            )
            result["pipeline_since_2026_09_10"] = query_all(
                cur,
                """
                SELECT symbol, final_action, COUNT(*) AS rows, MIN(created_at) AS first_run, MAX(created_at) AS last_run
                FROM pipeline_runs
                WHERE created_at >= '2026-09-10'
                GROUP BY symbol, final_action
                ORDER BY symbol, final_action
                """,
            )

        if table_exists(cur, "pending_trade_approvals"):
            result["pending_trade_approvals_status"] = query_all(
                cur,
                "SELECT status, COUNT(*) AS rows, MIN(created_at) AS first_created, MAX(created_at) AS last_created FROM pending_trade_approvals GROUP BY status ORDER BY rows DESC",
            )
            result["pending_trade_approvals_by_symbol"] = query_all(
                cur,
                "SELECT symbol, status, COUNT(*) AS rows, MIN(created_at) AS first_created, MAX(created_at) AS last_created FROM pending_trade_approvals GROUP BY symbol,status ORDER BY symbol,status",
            )

        if table_exists(cur, "pipeline_approval_queue"):
            result["pipeline_approval_queue_status"] = query_all(
                cur,
                "SELECT status, COUNT(*) AS rows, MIN(created_at) AS first_created, MAX(created_at) AS last_created FROM pipeline_approval_queue GROUP BY status ORDER BY rows DESC",
            )
            result["pipeline_approval_queue_recent"] = query_all(
                cur,
                "SELECT id, created_at, symbol, direction, confidence, status, expires_at, reviewed_at, order_id FROM pipeline_approval_queue ORDER BY created_at DESC LIMIT 20",
            )
            result["pipeline_approved_order_match"] = query_all(
                cur,
                """
                SELECT q.symbol,
                       COUNT(*) AS approved_rows,
                       COUNT(DISTINCT q.order_id) AS queue_order_ids,
                       COUNT(DISTINCT p.trade_id) AS matched_paper_trade_ids,
                       ROUND(SUM(CASE WHEN p.status='closed' THEN COALESCE(p.pnl,0) ELSE 0 END), 2) AS matched_closed_pnl
                FROM pipeline_approval_queue q
                LEFT JOIN paper_trades p ON p.trade_id=q.order_id OR p.idempotency_key=q.order_id
                WHERE q.status='approved'
                GROUP BY q.symbol
                ORDER BY q.symbol
                """,
            )

        if table_exists(cur, "decisions"):
            result["decisions_actions"] = query_all(
                cur,
                "SELECT symbol, action, COUNT(*) AS rows, MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts, ROUND(AVG(confidence),4) AS avg_conf FROM decisions GROUP BY symbol,action ORDER BY symbol,rows DESC",
            )
            result["decisions_recent_non_hold"] = query_all(
                cur,
                "SELECT id,timestamp,symbol,action,confidence,regime,substr(reasoning,1,220) AS reasoning_head FROM decisions WHERE lower(action) NOT IN ('hold','wait') ORDER BY timestamp DESC LIMIT 25",
            )

        if table_exists(cur, "wfe_snapshots"):
            result["wfe_by_symbol"] = query_all(
                cur,
                "SELECT symbol, COUNT(*) AS rows, MAX(created_at) AS last_created, MAX(week_start) AS last_week, SUM(trades) AS sum_trades, ROUND(AVG(win_rate),4) AS avg_win_rate, ROUND(AVG(profit_factor),4) AS avg_profit_factor, ROUND(AVG(sharpe),4) AS avg_sharpe FROM wfe_snapshots GROUP BY symbol ORDER BY symbol",
            )

        return result
    finally:
        conn.close()


def audit_runtime() -> dict[str, Any]:
    headers = basic_auth_header()
    return {
        "ports": {name: {"port": port, "open": probe_port(port)} for name, port in PORTS.items()},
        "has_dashboard_auth": bool(headers),
        "endpoints": {name: http_get_json_or_text(url, headers) for name, url in ROUTES.items()},
    }


def derive_verdict(audit: dict[str, Any]) -> dict[str, Any]:
    runtime = audit.get("runtime", {})
    endpoints = runtime.get("endpoints", {})
    ports = runtime.get("ports", {})

    health = (endpoints.get("engine_health_proxy", {}).get("json") or {}) if isinstance(endpoints.get("engine_health_proxy", {}).get("json"), dict) else {}
    safety = (endpoints.get("safety_status", {}).get("json") or {}) if isinstance(endpoints.get("safety_status", {}).get("json"), dict) else {}
    actionable = (endpoints.get("actionable", {}).get("json") or {}) if isinstance(endpoints.get("actionable", {}).get("json"), dict) else {}
    pending = (endpoints.get("pending_approvals", {}).get("json") or {}) if isinstance(endpoints.get("pending_approvals", {}).get("json"), dict) else {}
    paper_status = (endpoints.get("paper_status", {}).get("json") or {}) if isinstance(endpoints.get("paper_status", {}).get("json"), dict) else {}

    dashboard_ok = bool(endpoints.get("dashboard_root", {}).get("ok") and endpoints.get("dashboard_mission_control", {}).get("ok"))
    engine_ok = bool(health.get("status") == "ok" or endpoints.get("engine_health_direct", {}).get("ok"))
    operator_analysis_ready = dashboard_ok and engine_ok
    monitoring_ready = operator_analysis_ready and bool(ports.get("ibkr_paper_4002", {}).get("open"))
    execution_ready = bool(
        monitoring_ready
        and health.get("paper_mode") is True
        and health.get("live_trading") is True
        and not (health.get("kill_switch_active") or safety.get("kill_switch_active"))
    )

    blockers: list[str] = []
    if not dashboard_ok:
        blockers.append("dashboard routes did not all return 200")
    if not engine_ok:
        blockers.append("engine health is not ok")
    if health.get("kill_switch_active") or safety.get("kill_switch_active"):
        blockers.append("kill_switch_active=true")
    if health.get("live_trading") is False:
        blockers.append("live_trading=false")
    if not ports.get("master_api_8030", {}).get("open"):
        blockers.append("master-api :8030 closed; master/trade-record widgets may be degraded")
    for symbol, row in paper_status.items() if isinstance(paper_status, dict) else []:
        if isinstance(row, dict) and row.get("status") == "ACTIVE" and row.get("verdict") not in {"PASS", "NONE"}:
            blockers.append(f"{symbol} active/auth mismatch: status={row.get('status')} verdict={row.get('verdict')}")

    db = audit.get("database", {})
    paper_total = db.get("paper_total", {}) if isinstance(db.get("paper_total"), dict) else {}
    distribution = db.get("paper_distribution", {}) if isinstance(db.get("paper_distribution"), dict) else {}
    pipeline_total = db.get("pipeline_total", {}) if isinstance(db.get("pipeline_total"), dict) else {}
    intraday = db.get("intraday_paper_test", {}) if isinstance(db.get("intraday_paper_test"), dict) else {}

    edge_notes: list[str] = []
    if distribution:
        pf = distribution.get("profit_factor")
        win_rate = distribution.get("win_rate")
        edge_notes.append(f"closed ledger PF={pf}, win_rate={win_rate}, pnl={paper_total.get('closed_pnl')}")
    matches = db.get("pipeline_approved_order_match", [])
    if matches and all((row.get("matched_paper_trade_ids") or 0) == 0 for row in matches):
        edge_notes.append("approved queue order_ids did not join to paper_trades; recommendation attribution is not proven")
    if actionable.get("count") == 0 and pending.get("count") == 0:
        edge_notes.append("current recommendation board is empty: actionable=0, pending=0")

    return {
        "monitoring_ready": monitoring_ready,
        "operator_analysis_ready": operator_analysis_ready,
        "execution_ready": execution_ready,
        "dashboard_ok": dashboard_ok,
        "engine_ok": engine_ok,
        "blockers": blockers,
        "current_recommendations": {
            "actionable_count": actionable.get("count"),
            "actionable_raw_count": actionable.get("raw_count"),
            "pending_count": pending.get("count"),
        },
        "historical_performance": {
            "pipeline_runs": pipeline_total.get("rows"),
            "closed_paper_trades": paper_total.get("closed_rows"),
            "closed_pnl": paper_total.get("closed_pnl"),
            "profit_factor": distribution.get("profit_factor"),
            "win_rate": distribution.get("win_rate"),
            "rth_paper_entries": intraday.get("rth_entries"),
            "last_paper_entry": paper_total.get("last_entry"),
        },
        "edge_notes": edge_notes,
    }


def md_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_No rows._\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join([header, sep, *body]) + "\n"


def render_markdown(audit: dict[str, Any]) -> str:
    verdict = audit["verdict"]
    runtime = audit["runtime"]
    db = audit["database"]
    generated_at = audit["generated_at"]

    endpoint_rows = []
    for name, payload in runtime.get("endpoints", {}).items():
        endpoint_rows.append(
            {
                "endpoint": name,
                "status": payload.get("status"),
                "ok": payload.get("ok"),
                "latency_ms": payload.get("latency_ms"),
                "error": payload.get("error", ""),
            }
        )

    port_rows = [
        {"surface": name, "port": payload["port"], "open": payload["open"]}
        for name, payload in runtime.get("ports", {}).items()
    ]

    lines = [
        "# JARVIS Dashboard + Recommendation Audit",
        "",
        f"Generated: `{generated_at}`",
        "",
        "> Scope: read-only evidence capture. No engine/risk/kill-switch/.env/symbol-routing changes.",
        "",
        "## Verdict",
        "",
        f"- Operator-analysis-ready: **{verdict.get('operator_analysis_ready')}**",
        f"- Monitoring-ready: **{verdict['monitoring_ready']}**",
        f"- Execution-ready: **{verdict['execution_ready']}**",
        f"- Dashboard OK: **{verdict['dashboard_ok']}**",
        f"- Engine OK: **{verdict['engine_ok']}**",
        "",
        "### Blockers / warnings",
        "",
        *(f"- {item}" for item in verdict.get("blockers", [])),
        "" if verdict.get("blockers") else "- None detected by this audit.",
        "",
        "## Current recommendations",
        "",
        f"- Actionable shown: `{verdict['current_recommendations'].get('actionable_count')}`",
        f"- Actionable raw count: `{verdict['current_recommendations'].get('actionable_raw_count')}`",
        f"- Pending approvals: `{verdict['current_recommendations'].get('pending_count')}`",
        "",
        "## Historical paper-performance summary",
        "",
        f"- Pipeline runs: `{verdict['historical_performance'].get('pipeline_runs')}`",
        f"- Closed paper trades: `{verdict['historical_performance'].get('closed_paper_trades')}`",
        f"- Closed paper P&L: `${verdict['historical_performance'].get('closed_pnl')}`",
        f"- Profit factor: `{verdict['historical_performance'].get('profit_factor')}`",
        f"- Win rate: `{verdict['historical_performance'].get('win_rate')}`",
        f"- Regular-trading-hours paper entries: `{verdict['historical_performance'].get('rth_paper_entries')}`",
        f"- Last paper entry: `{verdict['historical_performance'].get('last_paper_entry')}`",
        "",
        "### Edge caveats",
        "",
        *(f"- {item}" for item in verdict.get("edge_notes", [])),
        "",
        "## Port checks",
        "",
        md_table(port_rows, ["surface", "port", "open"]),
        "## Endpoint checks",
        "",
        md_table(endpoint_rows, ["endpoint", "status", "ok", "latency_ms", "error"]),
        "## Paper trades by symbol",
        "",
        md_table(db.get("paper_by_symbol", []), ["symbol", "rows", "closed", "open", "closed_pnl", "wins", "losses", "first_entry", "last_entry"]),
        "## Paper trade distribution",
        "",
        "```json",
        json.dumps(db.get("paper_distribution", {}), indent=2),
        "```",
        "",
        "## Intraday paper-test evidence",
        "",
        "```json",
        json.dumps(db.get("intraday_paper_test", {}), indent=2)[:12000],
        "```",
        "",
        "## Pipeline actions",
        "",
        md_table(db.get("pipeline_actions", []), ["final_action", "rows", "first_run", "last_run"]),
        "## Approved queue attribution join",
        "",
        md_table(db.get("pipeline_approved_order_match", []), ["symbol", "approved_rows", "queue_order_ids", "matched_paper_trade_ids", "matched_closed_pnl"]),
        "## Recommended enhancement queue",
        "",
        "1. Dashboard readiness card: split monitoring-ready vs execution-ready, backed by this audit payload.",
        "2. Recommendation attribution fix/report: durable join from decision/pipeline/approval to paper trade.",
        "3. Confidence calibration: hit rate and expectancy by confidence bucket, symbol, regime, and strategy_id.",
        "4. Master API dependency badge: visible degraded state on journal/performance pages when :8030 is closed.",
        "5. Intraday paper scoreboard: RTH vs non-RTH P&L, independent of all-time ledger headline.",
        "6. [safety-review] only: unify drawdown metric source and durable alert dedup.",
        "",
    ]
    return "\n".join(lines)


def write_reports(audit: dict[str, Any], report_dir: Path) -> tuple[Path, Path, Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    finished_at = dt.datetime.now(UTC)
    audit["generated_at"] = finished_at.isoformat()
    stamp = finished_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    json_path = report_dir / f"JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_{stamp}.json"
    md_path = report_dir / f"JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_{stamp}.md"
    latest_json = report_dir / "JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.json"
    latest_md = report_dir / "JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.md"
    serialized = json.dumps(audit, indent=2, default=str)
    markdown = render_markdown(audit)
    for path, content in [(json_path, serialized), (latest_json, serialized), (md_path, markdown), (latest_md, markdown)]:
        path.write_text(content, encoding="utf-8")
    return json_path, md_path, latest_json, latest_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary to stdout")
    parser.add_argument("--no-write", action="store_true", help="Do not write report artifacts")
    args = parser.parse_args(argv)

    audit: dict[str, Any] = {
        "generated_at": dt.datetime.now(UTC).isoformat(),
        "scope": "read_only_dashboard_engine_db_audit",
        "root": str(ROOT),
        "runtime": audit_runtime(),
        "database": audit_database(),
    }
    audit["verdict"] = derive_verdict(audit)

    written: tuple[Path, Path, Path, Path] | None = None
    if not args.no_write:
        written = write_reports(audit, REPORT_DIR)
        audit["written_reports"] = [str(path) for path in written]

    if args.json:
        print(json.dumps({"verdict": audit["verdict"], "written_reports": audit.get("written_reports", [])}, indent=2, default=str))
    elif written:
        print("Wrote reports:")
        for path in written:
            print(path)
        print(json.dumps(audit["verdict"], indent=2, default=str))
    else:
        print(json.dumps(audit["verdict"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
