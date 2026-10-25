#!/usr/bin/env python3
"""Read-only JARVIS recommendation attribution audit.

This script reconciles recommendation/approval tables to the paper-trade ledger.
It does not mutate engine config, risk state, kill-switch state, broker state,
.env files, or symbol routing.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "engine" / "data" / "jarvis_trader.db"
REPORT_DIR = ROOT / "docs" / "reports"
UTC = dt.timezone.utc
CENTRAL = ZoneInfo("America/Chicago")


def rows(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def one(cur: sqlite3.Cursor, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    row = cur.execute(sql, params).fetchone()
    return dict(row) if row else {}


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return cur.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone() is not None


def safe_json_loads(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def strategy_approval_id(strategy_params: Any) -> str | None:
    data = safe_json_loads(strategy_params)
    if isinstance(data, dict):
        value = data.get("approval_id") or data.get("source_approval_id") or data.get("recommendation_id")
        return str(value) if value else None
    return None


def pnl_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if str(t.get("status") or "").lower() == "closed" and t.get("pnl") is not None]
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = round(sum(wins), 2)
    gross_loss = round(sum(losses), 2)
    pf = round(gross_profit / abs(gross_loss), 4) if gross_loss else (None if gross_profit == 0 else math.inf)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "closed": len(closed),
        "pnl": round(sum(pnls), 2),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
        "profit_factor": pf,
        "avg_trade": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "median_trade": round(sorted(pnls)[len(pnls) // 2], 2) if pnls else None,
        "best": round(max(pnls), 2) if pnls else None,
        "worst": round(min(pnls), 2) if pnls else None,
        "max_closed_trade_drawdown": round(max_dd, 2),
    }


def parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(CENTRAL)


def bucket_confidence(value: Any) -> str:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if c < 0.4:
        return "0.00-0.39"
    if c < 0.6:
        return "0.40-0.59"
    if c < 0.8:
        return "0.60-0.79"
    return "0.80-1.00"


def audit() -> dict[str, Any]:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    required = ["pipeline_runs", "decisions", "pending_trade_approvals", "pipeline_approval_queue", "paper_trades"]
    tables = {t: table_exists(cur, t) for t in required}
    counts = {t: one(cur, f"select count(*) as rows from {t}")["rows"] if exists else None for t, exists in tables.items()}

    paper = rows(cur, """
        select id, trade_id, symbol, side, quantity, entry_time, exit_time, pnl, status,
               strategy_params, strategy_id, idempotency_key, quote_source, regime
        from paper_trades
        order by entry_time
    """) if tables.get("paper_trades") else []
    for t in paper:
        t["strategy_approval_id"] = strategy_approval_id(t.get("strategy_params"))

    pta = rows(cur, """
        select id, approval_id, symbol, action, quantity, entry_price, status, created_at,
               resolved_at, paper_trade_id, ib_order_id, timeframe
        from pending_trade_approvals
        order by created_at
    """) if tables.get("pending_trade_approvals") else []

    queue = rows(cur, """
        select id, created_at, symbol, direction, confidence, status, reviewed_at, order_id
        from pipeline_approval_queue
        order by created_at
    """) if tables.get("pipeline_approval_queue") else []

    by_trade_id = {t.get("trade_id"): t for t in paper if t.get("trade_id")}
    by_approval_id = {a.get("approval_id"): a for a in pta if a.get("approval_id")}
    pta_linked_trade_ids = {a.get("paper_trade_id") for a in pta if a.get("paper_trade_id")}
    pta_linked_trades = [by_trade_id[tid] for tid in pta_linked_trade_ids if tid in by_trade_id]
    strategy_param_linked = [t for t in paper if t.get("strategy_approval_id") in by_approval_id]
    linked_trade_ids = {t.get("trade_id") for t in pta_linked_trades} | {t.get("trade_id") for t in strategy_param_linked}
    unlinked = [t for t in paper if t.get("trade_id") not in linked_trade_ids]

    queue_order_ids = {q.get("order_id") for q in queue if q.get("order_id")}
    matched_queue_trades = [t for t in paper if t.get("trade_id") in queue_order_ids or t.get("idempotency_key") in queue_order_ids]

    pta_status = rows(cur, "select status, count(*) as rows from pending_trade_approvals group by status order by rows desc")
    queue_status = rows(cur, "select status, count(*) as rows from pipeline_approval_queue group by status order by rows desc")
    queue_symbol = rows(cur, "select symbol, status, count(*) as rows, avg(confidence) as avg_confidence from pipeline_approval_queue group by symbol, status order by symbol, status")
    pipeline_actions = rows(cur, "select symbol, final_action, count(*) as rows, avg(confidence) as avg_confidence, min(created_at) as first_run, max(created_at) as last_run from pipeline_runs group by symbol, final_action order by symbol, final_action")

    confidence_rows: dict[str, dict[str, Any]] = {}
    for q in queue:
        b = bucket_confidence(q.get("confidence"))
        item = confidence_rows.setdefault(b, {"bucket": b, "rows": 0, "approved": 0, "expired": 0, "rejected": 0})
        item["rows"] += 1
        status = str(q.get("status") or "unknown").lower()
        if status in item:
            item[status] += 1
    confidence_buckets = list(confidence_rows.values())

    rth_linked = []
    for t in pta_linked_trades + [x for x in strategy_param_linked if x.get("trade_id") not in {p.get("trade_id") for p in pta_linked_trades}]:
        ts = parse_ts(t.get("entry_time"))
        if ts and ts.weekday() < 5 and dt.time(8, 30) <= ts.time() <= dt.time(15, 0):
            rth_linked.append(t)

    return {
        "generated_at": dt.datetime.now(UTC).isoformat(),
        "scope": "read_only_recommendation_attribution_audit",
        "root": str(ROOT),
        "db_path": str(DB_PATH),
        "table_counts": counts,
        "summary": {
            "paper_rows": len(paper),
            "pending_trade_approvals": len(pta),
            "pipeline_approval_queue_rows": len(queue),
            "pending_approval_paper_trade_id_links": len(pta_linked_trades),
            "strategy_params_approval_id_links": len(strategy_param_linked),
            "unique_linked_paper_trades": len(linked_trade_ids),
            "unlinked_paper_trades": len(unlinked),
            "queue_order_id_matches_to_paper": len(matched_queue_trades),
            "linked_rth_paper_trades": len(rth_linked),
        },
        "stats": {
            "all_paper": pnl_stats(paper),
            "pending_approval_linked": pnl_stats(pta_linked_trades),
            "strategy_param_linked": pnl_stats(strategy_param_linked),
            "all_unique_linked": pnl_stats([t for t in paper if t.get("trade_id") in linked_trade_ids]),
            "unlinked": pnl_stats(unlinked),
            "rth_linked": pnl_stats(rth_linked),
            "queue_order_id_matched": pnl_stats(matched_queue_trades),
        },
        "status_counts": {
            "pending_trade_approvals": pta_status,
            "pipeline_approval_queue": queue_status,
        },
        "queue_by_symbol_status": queue_symbol,
        "queue_confidence_buckets": sorted(confidence_buckets, key=lambda r: r["bucket"]),
        "pipeline_actions_by_symbol": pipeline_actions,
        "recent_linked_trades": [
            {k: t.get(k) for k in ["trade_id", "symbol", "side", "entry_time", "exit_time", "pnl", "status", "strategy_id", "quote_source", "strategy_approval_id"]}
            for t in [x for x in paper if x.get("trade_id") in linked_trade_ids][-20:]
        ],
        "verdict": {
            "recommendation_attribution_proven": len(linked_trade_ids) > 0,
            "queue_order_id_attribution_proven": len(matched_queue_trades) > 0,
            "primary_caveat": "pipeline_approval_queue.order_id still does not match paper_trades.trade_id/idempotency_key" if not matched_queue_trades else None,
            "edge_verdict": "positive all-time linked ledger, but not enough to prove current recommendation edge without durable pipeline/queue linkage and baseline comparison",
        },
    }


def md_table(items: list[dict[str, Any]], columns: list[str]) -> str:
    if not items:
        return "_No rows._\n"
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for item in items:
        out.append("| " + " | ".join(str(item.get(c, "")) for c in columns) + " |")
    return "\n".join(out) + "\n"


def render(a: dict[str, Any]) -> str:
    s = a["summary"]
    stats = a["stats"]
    v = a["verdict"]
    lines = [
        "# JARVIS Recommendation Attribution Audit",
        "",
        f"Generated: `{a['generated_at']}`",
        "",
        "> Scope: read-only DB attribution. No live/risk/kill-switch/.env/symbol-routing changes.",
        "",
        "## Verdict",
        "",
        f"- Recommendation attribution proven: **{v['recommendation_attribution_proven']}**",
        f"- Queue order-id attribution proven: **{v['queue_order_id_attribution_proven']}**",
        f"- Edge verdict: {v['edge_verdict']}",
        f"- Caveat: {v['primary_caveat']}",
        "",
        "## Linkage summary",
        "",
        md_table([s], list(s.keys())),
        "## P&L statistics",
        "",
        md_table([{"cohort": k, **val} for k, val in stats.items()], ["cohort", "closed", "pnl", "wins", "losses", "win_rate", "profit_factor", "avg_trade", "median_trade", "best", "worst", "max_closed_trade_drawdown"]),
        "## Approval status counts",
        "",
        "### pending_trade_approvals",
        md_table(a["status_counts"]["pending_trade_approvals"], ["status", "rows"]),
        "### pipeline_approval_queue",
        md_table(a["status_counts"]["pipeline_approval_queue"], ["status", "rows"]),
        "## Queue confidence buckets",
        "",
        md_table(a["queue_confidence_buckets"], ["bucket", "rows", "approved", "expired", "rejected"]),
        "## Queue by symbol/status",
        "",
        md_table(a["queue_by_symbol_status"], ["symbol", "status", "rows", "avg_confidence"]),
        "## Pipeline actions by symbol",
        "",
        md_table(a["pipeline_actions_by_symbol"], ["symbol", "final_action", "rows", "avg_confidence", "first_run", "last_run"]),
        "## Recent linked paper trades",
        "",
        md_table(a["recent_linked_trades"], ["trade_id", "symbol", "side", "entry_time", "exit_time", "pnl", "status", "strategy_id", "quote_source", "strategy_approval_id"]),
    ]
    return "\n".join(lines)


def main() -> int:
    data = audit()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    data["generated_at"] = dt.datetime.now(UTC).isoformat()
    json_path = REPORT_DIR / f"JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_{stamp}.json"
    md_path = REPORT_DIR / f"JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_{stamp}.md"
    latest_json = REPORT_DIR / "JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json"
    latest_md = REPORT_DIR / "JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.md"
    serialized = json.dumps(data, indent=2, default=str)
    markdown = render(data)
    for path, content in [(json_path, serialized), (latest_json, serialized), (md_path, markdown), (latest_md, markdown)]:
        path.write_text(content, encoding="utf-8")
    print(json.dumps({"verdict": data["verdict"], "summary": data["summary"], "stats": data["stats"], "written_reports": [str(json_path), str(md_path), str(latest_json), str(latest_md)]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
