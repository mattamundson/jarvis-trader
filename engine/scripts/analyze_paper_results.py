"""Paper-trading empirical analyzer.

**Multi-DB aware** (2026-04-19 v2): walks all `.db` files in `engine/data/`:
  - `jarvis_trader.db`    (main DB, 30 tables)
  - `agent_feedback.db`   (AgentFeedbackTracker — `trade_outcomes` for Track H IC)
  - `llm_costs.db`        (LLM call/cost tracking — `llm_calls`, not pipeline_llm_costs)
  - `cot_cache.db`        (Commitments of Traders data cache)

Emits a JSON report covering:
  - schema + analysis window
  - paper_trades breakdown (organic vs sync vs test vs contaminated)
  - pipeline_runs + decisions distribution per symbol
  - data-availability matrix for analytics tables across ALL DB files
  - contamination detection (futures-symbol records priced in equity range)
  - daily_pnl sanity (flags identical-every-day patterns)
  - full_pipeline_json structural extraction for non-HOLD decisions
  - trade_outcomes (Track H input) from agent_feedback.db
  - llm_calls cost + token tracking from llm_costs.db

Usage:
    python -m engine.scripts.analyze_paper_results \\
        --db engine/data/jarvis_trader.db \\
        --start 2026-04-10 \\
        --end   2026-04-19

The `--db` arg only points at the main DB; the other DBs are resolved
relative to the main DB's parent directory (i.e. always the engine/data dir).

Outputs JSON to stdout. Pipe to `python -m json.tool` for pretty print,
or to a file for downstream diffing.

No writes to any DB. Safe to run while engine is live.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

# Symbols we paper-trade (MEMORY.md: MCL, MNQ approved; MES bypass-testing).
PAPER_APPROVED = {"MCL", "MNQ", "MES"}

# Known equity-price ranges for futures contamination detection.
# If a "futures" symbol shows an entry_price in the equity range, flag it.
FUTURES_EQUITY_CONTAMINATION_RANGES = {
    "MES": (50.0, 120.0),  # real MES is ~5000-6000; stock prices in this range = bogus
    "MNQ": (50.0, 200.0),
    "MCL": (None, None),   # MCL ~60-100, no clean separator from stock range — skip
    "MGC": (None, None),
}


def _count(con: sqlite3.Connection, sql: str, args: tuple = ()) -> int:
    return con.execute(sql, args).fetchone()[0]


def _classify_paper_trade(row: sqlite3.Row) -> str:
    """Tag each paper_trade as one of: sync, test, contaminated, guard, unknown, organic."""
    sp = row["strategy_params"] or ""
    try:
        parsed = json.loads(sp)
        note = (parsed.get("notes") or "").lower()
    except Exception:
        return "malformed_json"
    if "paper_runner_sync" in note:
        return "sync"
    if "test trade" in note or "e2e verification" in note:
        return "test"
    if "smoke-test" in note or "guard" in note:
        return "guard"
    if row["entry_price"] is not None and row["symbol"] in FUTURES_EQUITY_CONTAMINATION_RANGES:
        lo, hi = FUTURES_EQUITY_CONTAMINATION_RANGES[row["symbol"]]
        if lo is not None and lo <= row["entry_price"] <= hi:
            return "contaminated"
    if not note:
        return "unknown"
    return "organic"


def _sharpe_proxy(pnls: list[float]) -> float | None:
    """Annualized Sharpe proxy from daily trade P&Ls. sqrt(252) scaling."""
    if len(pnls) < 2:
        return None
    m = mean(pnls)
    s = pstdev(pnls)
    if s == 0:
        return None
    return (m / s) * (252 ** 0.5)


def _max_drawdown(pnls_chron: list[float]) -> float:
    """Max drawdown in % of peak, given chronologically ordered P&L list."""
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls_chron:
        eq += p
        peak = max(peak, eq)
        dd = peak - eq
        if peak > 0 and dd / peak > max_dd:
            max_dd = dd / peak
    return max_dd


def _analyze_agent_feedback_db(db_path: str, start: str, end: str) -> dict[str, Any]:
    """trade_outcomes rows + test-vs-real classification."""
    import os
    if not os.path.exists(db_path):
        return {"exists": False}
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        n_total = con.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]
        rows = [dict(r) for r in con.execute(
            "SELECT trade_id, timestamp, symbol, direction, pnl_usd, outcome "
            "FROM trade_outcomes WHERE timestamp >= ? AND timestamp < ? "
            "ORDER BY timestamp",
            (start, end + "T23:59:59Z"),
        )]
        test_rows = [r for r in rows if r["trade_id"].startswith("test-")]
        real_rows = [r for r in rows if not r["trade_id"].startswith("test-")]
        return {
            "exists": True,
            "n_total": n_total,
            "n_in_window": len(rows),
            "n_real_in_window": len(real_rows),
            "n_test_in_window": len(test_rows),
            "real_rows": real_rows,
        }
    except sqlite3.OperationalError as e:
        return {"exists": True, "error": str(e)}


def _analyze_llm_costs_db(db_path: str, start: str, end: str) -> dict[str, Any]:
    """llm_calls: per-day/model cost + token aggregate, plus broken-tracker detection."""
    import os
    if not os.path.exists(db_path):
        return {"exists": False}
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        n_total = con.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        by_day_model = [dict(r) for r in con.execute(
            """
            SELECT DATE(timestamp) d, model, COUNT(*) n,
                   SUM(input_tokens) in_tok, SUM(output_tokens) out_tok,
                   SUM(COALESCE(cost_usd, 0)) cost
            FROM llm_calls WHERE timestamp >= ? AND timestamp < ?
            GROUP BY d, model ORDER BY d DESC, n DESC
            """,
            (start, end + "T23:59:59Z"),
        )]
        # Detect broken tracker: rows where input_tokens=0 despite the call happening
        n_zero_tok = con.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE timestamp >= ? AND timestamp < ? AND input_tokens = 0",
            (start, end + "T23:59:59Z"),
        ).fetchone()[0]
        n_in_window = con.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE timestamp >= ? AND timestamp < ?",
            (start, end + "T23:59:59Z"),
        ).fetchone()[0]
        total_cost = con.execute(
            "SELECT SUM(COALESCE(cost_usd,0)) FROM llm_calls WHERE timestamp >= ? AND timestamp < ?",
            (start, end + "T23:59:59Z"),
        ).fetchone()[0] or 0.0
        return {
            "exists": True,
            "n_total": n_total,
            "n_in_window": n_in_window,
            "zero_token_rows_in_window": n_zero_tok,
            "tracker_healthy": n_in_window > 0 and n_zero_tok < n_in_window * 0.5,
            "total_cost_usd_in_window": round(total_cost, 4),
            "by_day_model": by_day_model,
        }
    except sqlite3.OperationalError as e:
        return {"exists": True, "error": str(e)}


def analyze(db_path: str, start: str, end: str) -> dict[str, Any]:
    import os
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # Sibling DB paths (always resolve to the same engine/data directory).
    data_dir = os.path.dirname(os.path.abspath(db_path))
    agent_feedback_db = os.path.join(data_dir, "agent_feedback.db")
    llm_costs_db = os.path.join(data_dir, "llm_costs.db")

    out: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": db_path,
        "sibling_dbs": {
            "agent_feedback_db": agent_feedback_db,
            "llm_costs_db": llm_costs_db,
        },
        "window": {"start": start, "end": end},
    }

    # Multi-DB sections — added in v2 (2026-04-19) after Task 2.5 discovered
    # the multi-DB architecture was missed by v1.
    out["agent_feedback"] = _analyze_agent_feedback_db(agent_feedback_db, start, end)
    out["llm_costs"] = _analyze_llm_costs_db(llm_costs_db, start, end)

    # Schema version
    sv = con.execute(
        "SELECT version, applied_at, description FROM schema_version "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()
    out["schema_version"] = dict(sv) if sv else None

    # Data availability — which analytics tables have rows?
    availability = {}
    for tbl in [
        "paper_trades",
        "pipeline_runs",
        "decisions",
        "pipeline_llm_costs",
        "learning_events",
        "supervisor_decisions",
        "trading_patterns",
        "trade_journal",
        "journal_notes",
        "pnl_snapshots",
        "capital_allocation",
        "positions",
        "daily_pnl",
        "pending_trade_approvals",
        "alert_log",
        "discord_bot_signals",
    ]:
        try:
            availability[tbl] = _count(con, f"SELECT COUNT(*) FROM {tbl}")
        except sqlite3.OperationalError:
            availability[tbl] = None
    out["table_row_counts"] = availability
    out["empty_analytics_tables"] = [
        t for t, n in availability.items()
        if n == 0 and t in {
            "pipeline_llm_costs", "learning_events", "supervisor_decisions",
            "trading_patterns", "trade_journal", "journal_notes",
            "pnl_snapshots", "capital_allocation",
        }
    ]

    # paper_trades: classify each trade in window
    paper_classified: Counter = Counter()
    organic_pnls: list[float] = []
    per_symbol_organic: dict[str, list[float]] = {}
    all_in_window: list[dict] = []
    for r in con.execute(
        "SELECT id, trade_id, symbol, side, entry_price, exit_price, "
        "       entry_time, exit_time, pnl, status, strategy_params "
        "FROM paper_trades WHERE entry_time >= ? AND entry_time < ? "
        "ORDER BY entry_time",
        (start, end + "T23:59:59Z"),
    ):
        cls = _classify_paper_trade(r)
        paper_classified[cls] += 1
        all_in_window.append({
            "id": r["id"], "trade_id": r["trade_id"], "symbol": r["symbol"],
            "side": r["side"], "entry_price": r["entry_price"],
            "exit_price": r["exit_price"], "pnl": r["pnl"],
            "classification": cls,
        })
        if cls == "organic" and r["pnl"] is not None:
            organic_pnls.append(r["pnl"])
            per_symbol_organic.setdefault(r["symbol"], []).append(r["pnl"])

    out["paper_trades_in_window"] = {
        "total": sum(paper_classified.values()),
        "classification": dict(paper_classified),
        "raw": all_in_window,
    }

    # Organic-only metrics (if any)
    organic_metrics: dict[str, Any] = {
        "n_trades": len(organic_pnls),
        "note": "Only trades classified 'organic' count for alpha analysis.",
    }
    if organic_pnls:
        organic_metrics["sum_pnl"] = sum(organic_pnls)
        organic_metrics["mean_pnl"] = mean(organic_pnls)
        organic_metrics["win_rate"] = sum(1 for p in organic_pnls if p > 0) / len(organic_pnls)
        organic_metrics["sharpe_proxy"] = _sharpe_proxy(organic_pnls)
        organic_metrics["max_drawdown_pct"] = _max_drawdown(organic_pnls)
        organic_metrics["per_symbol"] = {
            s: {"n": len(ps), "sum": sum(ps), "win_rate": sum(1 for p in ps if p > 0) / len(ps)}
            for s, ps in per_symbol_organic.items()
        }
    out["organic_paper_metrics"] = organic_metrics

    # pipeline_runs distribution per symbol in window
    pipeline_by_sym: list[dict] = []
    for r in con.execute(
        """
        SELECT symbol, final_action, status, COUNT(*) n,
               SUM(CASE WHEN requires_human = 1 THEN 1 ELSE 0 END) req_human,
               AVG(duration_ms) avg_ms
        FROM pipeline_runs
        WHERE created_at >= ? AND created_at < ?
        GROUP BY symbol, final_action, status
        ORDER BY symbol, final_action
        """,
        (start, end + "T23:59:59"),
    ):
        pipeline_by_sym.append(dict(r))
    out["pipeline_runs_by_symbol"] = pipeline_by_sym

    # decisions with non-hold action — the organic signals
    non_hold_decisions: list[dict] = []
    for r in con.execute(
        """
        SELECT id, symbol, timestamp, action, confidence, regime
        FROM decisions
        WHERE timestamp >= ? AND timestamp < ?
          AND action IN ('buy','sell','exit_long','exit_short')
        ORDER BY timestamp
        """,
        (start, end + "T23:59:59"),
    ):
        non_hold_decisions.append(dict(r))
    out["non_hold_decisions"] = non_hold_decisions
    out["non_hold_count_by_symbol"] = dict(Counter(d["symbol"] for d in non_hold_decisions))

    # pipeline_runs dead-column audit
    dead_col_audit = {}
    for col in ["confidence", "final_decision", "error_message"]:
        dead_col_audit[col] = {
            "non_null": _count(con, f"SELECT COUNT(*) FROM pipeline_runs WHERE {col} IS NOT NULL"),
            "total": _count(con, "SELECT COUNT(*) FROM pipeline_runs"),
        }
    out["pipeline_runs_column_coverage"] = dead_col_audit

    # pending_trade_approvals
    approvals = {
        "total": _count(con, "SELECT COUNT(*) FROM pending_trade_approvals"),
        "approved": _count(con, "SELECT COUNT(*) FROM pending_trade_approvals WHERE status='approved'"),
        "rejected": _count(con, "SELECT COUNT(*) FROM pending_trade_approvals WHERE status='rejected'"),
        "pending": _count(con, "SELECT COUNT(*) FROM pending_trade_approvals WHERE status='pending'"),
        "linked_to_paper_trade": _count(
            con, "SELECT COUNT(*) FROM pending_trade_approvals WHERE paper_trade_id IS NOT NULL"
        ),
    }
    out["approvals"] = approvals

    # daily_pnl sanity — flag identical-every-day patterns
    daily_pnl_rows: list[dict] = [
        dict(r) for r in con.execute(
            "SELECT date, realized_pnl, total_trades, winning_trades, losing_trades "
            "FROM daily_pnl ORDER BY date"
        )
    ]
    distinct_pnls = len({r["realized_pnl"] for r in daily_pnl_rows})
    distinct_trade_counts = len({r["total_trades"] for r in daily_pnl_rows})
    out["daily_pnl"] = {
        "rows": daily_pnl_rows,
        "distinct_realized_pnl_values": distinct_pnls,
        "distinct_total_trades_values": distinct_trade_counts,
        "suspicion": (
            "Repeated identical values across days suggests synthetic/demo data, "
            "NOT real daily rollups." if distinct_pnls <= 3 and len(daily_pnl_rows) >= 5 else "ok"
        ),
    }

    # Contamination detection on paper_trades + pending_approvals
    contamination = []
    for r in con.execute("SELECT symbol, entry_price, id FROM pending_trade_approvals"):
        lo_hi = FUTURES_EQUITY_CONTAMINATION_RANGES.get(r["symbol"], (None, None))
        if lo_hi[0] is not None and r["entry_price"] is not None and lo_hi[0] <= r["entry_price"] <= lo_hi[1]:
            contamination.append({
                "source": "pending_trade_approvals", "id": r["id"],
                "symbol": r["symbol"], "entry_price": r["entry_price"],
            })
    out["contamination_detected"] = contamination

    # Rich full_pipeline_json summary: are tracks wired?
    tracks_evidence = {
        "rows_with_full_pipeline_json": _count(
            con, "SELECT COUNT(*) FROM decisions WHERE full_pipeline_json IS NOT NULL"
        ),
        "has_hp_fields": 0,
        "has_boosted_confidence": 0,
        "has_advisor_invocation": 0,
    }
    for r in con.execute(
        "SELECT full_pipeline_json FROM decisions "
        "WHERE full_pipeline_json IS NOT NULL AND timestamp >= ? AND timestamp < ? LIMIT 500",
        (start, end + "T23:59:59"),
    ):
        try:
            fp = json.loads(r[0])
        except Exception:
            continue
        if "hp_conflict" in fp or "hp_confirms" in fp or "hp_bias" in fp:
            tracks_evidence["has_hp_fields"] += 1
        if "boosted_confidence" in fp:
            tracks_evidence["has_boosted_confidence"] += 1
        if "advisor" in str(fp).lower():
            tracks_evidence["has_advisor_invocation"] += 1
    out["tracks_evidence"] = tracks_evidence

    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="engine/data/jarvis_trader.db")
    p.add_argument("--start", required=True, help="ISO date e.g. 2026-04-10")
    p.add_argument("--end", required=True, help="ISO date e.g. 2026-04-19")
    args = p.parse_args()
    result = analyze(args.db, args.start, args.end)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
