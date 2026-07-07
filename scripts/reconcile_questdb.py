#!/usr/bin/env python
"""QuestDB ↔ SQLite reconciliation runner.

Detects dual-write divergence between the SQLite primary and QuestDB shadow
tables BEFORE reads cut over.  Read-only by default — reports divergence but
never auto-heals.  Manual heal mode requires ENABLE_QUESTDB_RECONCILE_HEAL=1.

Usage
-----
    # Read-only reconcile (all tables)
    python scripts/reconcile_questdb.py

    # Dry-run — prints what would be checked without touching anything
    python scripts/reconcile_questdb.py --dry-run

    # Heal missing rows in one table (requires ENABLE_QUESTDB_RECONCILE_HEAL=1)
    python scripts/reconcile_questdb.py --heal bot_signals

Status thresholds
-----------------
    "ok"        diff_pct <= 0.1%
    "divergent" 0.1% < diff_pct <= 5.0%
    "critical"  diff_pct > 5.0%
    "unreachable" QuestDB did not respond

Output
------
    engine/data/reconcile_snapshots/<YYYY-MM-DD>.json
    master-jarvis/second-brain/raw/_session-reconcile/reconcile-<YYYY-MM-DD>.md
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _REPO_ROOT / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_ENGINE_DIR / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reconcile_questdb")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_THRESHOLD = 10_000  # rows; full diff below this, sample above
SAMPLE_SIZE = 1_000  # random message_ids to draw for large tables
DIVERGENT_PCT = 0.001  # 0.1%
CRITICAL_PCT = 0.05  # 5.0%

QUESTDB_HOST = os.environ.get("QUESTDB_HOST", "localhost")
QUESTDB_PORT = os.environ.get("QUESTDB_PORT", "9000")
QUESTDB_BASE_URL = f"http://{QUESTDB_HOST}:{QUESTDB_PORT}"

DB_PATH = os.environ.get("DB_PATH", str(_ENGINE_DIR / "data" / "jarvis_trader.db"))

SNAPSHOT_DIR = _ENGINE_DIR / "data" / "reconcile_snapshots"
VAULT_RAW_DIR = (
    _REPO_ROOT.parent.parent
    / "master-jarvis"
    / "second-brain"
    / "raw"
    / "_session-reconcile"
)

HEAL_LOG = _ENGINE_DIR / "logs" / "questdb_heal.log"

# Table configuration — mirrors backfill_discord_to_questdb.py
TABLES: dict[str, dict[str, Any]] = {
    "bot_signals": {
        "sqlite_table": "discord_bot_signals",
        "questdb_table": "discord_bot_signals_ts",
        "id_col": "message_id",
        "ts_col": "timestamp",
        "sqlite_cols": [
            "message_id",
            "timestamp",
            "symbol",
            "timeframe",
            "direction",
            "signal_type",
            "entry_price",
            "target1",
            "target2",
            "stop1",
            "stop2",
            "win_rate",
            "wins",
            "losses",
            "mfe",
            "mae",
            "rr",
            "gain",
            "draw",
            "net",
            "last_price",
            "source_channel",
        ],
    },
    "corey_commentary": {
        "sqlite_table": "discord_corey_commentary",
        "questdb_table": "discord_corey_commentary_ts",
        "id_col": "message_id",
        "ts_col": "timestamp",
        "sqlite_cols": ["message_id", "timestamp", "content", "channel", "author_id"],
    },
    "ib_reports": {
        "sqlite_table": "discord_ib_reports",
        "questdb_table": "discord_ib_reports_ts",
        "id_col": "message_id",
        "ts_col": "timestamp",
        "sqlite_cols": [
            "message_id",
            "timestamp",
            "symbol",
            "timeframe",
            "ib_open",
            "ib_high",
            "ib_low",
            "ib_close",
            "ib_range",
            "ibu50",
            "ibu100",
            "ibd50",
            "ibd100",
            "auction_context",
            "source_channel",
        ],
    },
    "daily_sentiment": {
        "sqlite_table": "discord_daily_sentiment",
        "questdb_table": "discord_daily_sentiment_ts",
        "id_col": "date",
        "ts_col": "date",
        "sqlite_cols": [
            "date",
            "sentiment_score",
            "post_count",
            "source",
            "computed_at",
        ],
    },
}


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------


def is_reconcile_enabled() -> bool:
    """True when ENABLE_QUESTDB_RECONCILE=1."""
    return os.environ.get("ENABLE_QUESTDB_RECONCILE", "0").strip() == "1"


def is_heal_enabled() -> bool:
    """True when ENABLE_QUESTDB_RECONCILE_HEAL=1."""
    return os.environ.get("ENABLE_QUESTDB_RECONCILE_HEAL", "0").strip() == "1"


# ---------------------------------------------------------------------------
# QuestDB helpers
# ---------------------------------------------------------------------------


def _qdb_exec(client, sql: str, timeout: float = 30.0) -> dict:
    """Run a SQL query via QuestDB /exec endpoint. Returns parsed JSON dict."""
    resp = client.get("/exec", params={"query": sql}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _qdb_count(client, table: str) -> int:
    """Return row count for a QuestDB table. Raises on network/table error."""
    data = _qdb_exec(client, f"SELECT count() FROM {table}")
    return int(data["dataset"][0][0])


def _qdb_fetch_ids(client, table: str, id_col: str) -> set[str]:
    """Fetch all id values from a QuestDB table. Returns empty set on error."""
    try:
        data = _qdb_exec(client, f"SELECT {id_col} FROM {table}", timeout=60.0)
        if "dataset" not in data:
            return set()
        return {str(row[0]) for row in data["dataset"] if row[0] is not None}
    except Exception:
        return set()


def _qdb_id_presence(client, table: str, id_col: str, ids: list[str]) -> set[str]:
    """Check which of `ids` exist in QuestDB table. Returns the present subset."""
    if not ids:
        return set()
    # QuestDB supports IN with up to a few thousand literals safely
    id_list = ", ".join(f"'{i.replace(chr(39), chr(39)*2)}'" for i in ids)
    sql = f"SELECT {id_col} FROM {table} WHERE {id_col} IN ({id_list})"
    try:
        data = _qdb_exec(client, sql, timeout=30.0)
        if "dataset" not in data:
            return set()
        return {str(row[0]) for row in data["dataset"] if row[0] is not None}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def _sqlite_count(db_path: str, table: str) -> int:
    """Return row count for a SQLite table."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _sqlite_all_ids(db_path: str, table: str, id_col: str) -> list[str]:
    """Return all id values from a SQLite table."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(f"SELECT {id_col} FROM {table}")
        return [str(row[0]) for row in cursor if row[0] is not None]
    finally:
        conn.close()


def _sqlite_sample_ids(db_path: str, table: str, id_col: str, k: int) -> list[str]:
    """Return a random sample of up to k id values from a SQLite table."""
    all_ids = _sqlite_all_ids(db_path, table, id_col)
    if len(all_ids) <= k:
        return all_ids
    return random.sample(all_ids, k)


# ---------------------------------------------------------------------------
# Core reconciliation logic
# ---------------------------------------------------------------------------


def _classify_status(diff_pct: float) -> str:
    """Map a divergence percentage to a status string."""
    if diff_pct > CRITICAL_PCT:
        return "critical"
    if diff_pct > DIVERGENT_PCT:
        return "divergent"
    return "ok"


def reconcile_table(
    table_name: str,
    sqlite_db: str,
    questdb_url: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Reconcile one table between SQLite and QuestDB.

    Parameters
    ----------
    table_name:
        Key in the TABLES config dict (e.g. "bot_signals").
    sqlite_db:
        Path to the SQLite database file.
    questdb_url:
        Base URL for the QuestDB HTTP endpoint (e.g. "http://localhost:9000").
    dry_run:
        If True, performs count checks but skips the expensive full/sample diff.

    Returns
    -------
    dict with keys:
        table, sqlite_count, questdb_count, diff_pct, diff_mode,
        missing_from_questdb_sample, extra_in_questdb_sample, status,
        sample_size, confidence_interval_95pct (for sampled tables), note
    """
    import httpx  # lazy — not always installed when this module is imported

    cfg = TABLES[table_name]
    sqlite_table = cfg["sqlite_table"]
    questdb_table = cfg["questdb_table"]
    id_col = cfg["id_col"]

    result: dict[str, Any] = {
        "table": table_name,
        "sqlite_table": sqlite_table,
        "questdb_table": questdb_table,
        "sqlite_count": 0,
        "questdb_count": 0,
        "diff_pct": 0.0,
        "diff_mode": "none",
        "missing_from_questdb_sample": [],
        "extra_in_questdb_sample": [],
        "status": "ok",
        "sample_size": None,
        "confidence_interval_95pct": None,
        "note": "",
    }

    # ---- SQLite count (read-only) ----------------------------------------
    try:
        sqlite_count = _sqlite_count(sqlite_db, sqlite_table)
    except Exception as exc:
        result["status"] = "error"
        result["note"] = f"SQLite count failed: {exc}"
        logger.error("SQLite count failed for %s: %s", sqlite_table, exc)
        return result

    result["sqlite_count"] = sqlite_count

    # ---- QuestDB count ---------------------------------------------------
    try:
        with httpx.Client(base_url=questdb_url, timeout=10.0) as client:
            try:
                questdb_count = _qdb_count(client, questdb_table)
                result["questdb_count"] = questdb_count
            except Exception as exc:
                result["status"] = "unreachable"
                result["note"] = f"QuestDB unreachable or table missing: {exc}"
                logger.warning("QuestDB unreachable for %s: %s", questdb_table, exc)
                return result

            # ---- Diff computation ----------------------------------------
            if sqlite_count == 0:
                result["diff_pct"] = 0.0
                result["status"] = "ok"
                result["note"] = "SQLite table empty — no divergence to measure"
                return result

            count_diff_pct = abs(sqlite_count - questdb_count) / sqlite_count

            if dry_run:
                result["diff_pct"] = count_diff_pct
                result["diff_mode"] = "count-only"
                result["status"] = _classify_status(count_diff_pct)
                result["note"] = "dry-run: count comparison only"
                return result

            # ---- Full diff vs. sample ------------------------------------
            if sqlite_count <= SAMPLE_THRESHOLD:
                # Full diff via id sets
                result["diff_mode"] = "full"
                result["sample_size"] = sqlite_count

                sqlite_ids = set(_sqlite_all_ids(sqlite_db, sqlite_table, id_col))
                questdb_ids = _qdb_fetch_ids(client, questdb_table, id_col)

                missing = list(sqlite_ids - questdb_ids)
                extra = list(questdb_ids - sqlite_ids)

                # Report up to 50 examples
                result["missing_from_questdb_sample"] = missing[:50]
                result["extra_in_questdb_sample"] = extra[:50]

                # Divergence rate based on SQLite as ground truth
                diff_pct = len(missing) / sqlite_count if sqlite_count else 0.0
                result["diff_pct"] = diff_pct
                result["status"] = _classify_status(diff_pct)

                logger.info(
                    "%s full diff: sqlite=%d questdb=%d missing=%d extra=%d status=%s",
                    table_name,
                    sqlite_count,
                    questdb_count,
                    len(missing),
                    len(extra),
                    result["status"],
                )

            else:
                # Statistical sample — 1000 random message_ids from SQLite
                result["diff_mode"] = "sample"
                result["sample_size"] = SAMPLE_SIZE

                sampled = _sqlite_sample_ids(
                    sqlite_db, sqlite_table, id_col, SAMPLE_SIZE
                )
                present_in_qdb = _qdb_id_presence(
                    client, questdb_table, id_col, sampled
                )
                missing_in_sample = [i for i in sampled if i not in present_in_qdb]

                result["missing_from_questdb_sample"] = missing_in_sample[:50]
                result["extra_in_questdb_sample"] = []  # not computed in sample mode

                # Estimated divergence = fraction missing in sample
                sample_n = len(sampled)
                observed_missing = len(missing_in_sample)
                diff_pct = observed_missing / sample_n if sample_n else 0.0
                result["diff_pct"] = diff_pct

                # 95% Wilson score confidence interval on the proportion
                ci_lower, ci_upper = _wilson_ci(observed_missing, sample_n, z=1.96)
                result["confidence_interval_95pct"] = {
                    "lower": round(ci_lower, 6),
                    "upper": round(ci_upper, 6),
                    "note": (
                        f"{observed_missing}/{sample_n} sampled rows missing; "
                        f"CI [{ci_lower:.2%}, {ci_upper:.2%}] at 95% confidence"
                    ),
                }

                result["status"] = _classify_status(diff_pct)
                logger.info(
                    "%s sample diff: sqlite=%d sample=%d missing=%d (%.2f%%) status=%s",
                    table_name,
                    sqlite_count,
                    sample_n,
                    observed_missing,
                    diff_pct * 100,
                    result["status"],
                )

    except Exception as exc:
        result["status"] = "error"
        result["note"] = f"Unexpected error: {exc}"
        logger.error(
            "reconcile_table failed for %s: %s", table_name, exc, exc_info=True
        )

    return result


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n at confidence level z."""
    if n == 0:
        return 0.0, 0.0
    p_hat = k / n
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denominator
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def reconcile_all(
    sqlite_db: str | None = None,
    questdb_url: str | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Run reconciliation for all 4 tables. Returns aggregated report dict.

    Parameters
    ----------
    sqlite_db:
        Path to SQLite database (defaults to DB_PATH env / engine/data/jarvis_trader.db).
    questdb_url:
        QuestDB base URL (defaults to QUESTDB_BASE_URL constructed from env vars).
    dry_run:
        Passed through to each reconcile_table call.
    """
    db = sqlite_db or DB_PATH
    url = questdb_url or QUESTDB_BASE_URL
    today = date.today().isoformat()
    ran_at = datetime.now(timezone.utc).isoformat()

    table_results = []
    for table_name in TABLES:
        logger.info("Reconciling table: %s ...", table_name)
        r = reconcile_table(table_name, db, url, dry_run=dry_run)
        table_results.append(r)

    # Aggregate status: worst individual status wins
    STATUS_RANK = {"unreachable": 4, "error": 3, "critical": 2, "divergent": 1, "ok": 0}
    overall_status = max(
        (r["status"] for r in table_results),
        key=lambda s: STATUS_RANK.get(s, 0),
        default="ok",
    )

    report = {
        "date": today,
        "ran_at": ran_at,
        "overall_status": overall_status,
        "sqlite_db": db,
        "questdb_url": url,
        "tables": table_results,
    }

    _write_snapshot(report)
    _write_vault_markdown(report)

    return report


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_snapshot(report: dict) -> None:
    """Write JSON snapshot to engine/data/reconcile_snapshots/<date>.json."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAPSHOT_DIR / f"{report['date']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Snapshot written: %s", out)


def _write_vault_markdown(report: dict) -> None:
    """Write vault-ingestible markdown to master-jarvis second-brain raw dir."""
    try:
        VAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create vault dir %s: %s", VAULT_RAW_DIR, exc)
        return

    overall = report["overall_status"]
    today = report["date"]

    lines = [
        "---",
        'source: "questdb-reconcile"',
        'kind: "daily-aggregate"',
        f'date: "{today}"',
        f'overall_status: "{overall}"',
        "tags:",
        "  - questdb",
        "  - reconciliation",
        "  - daily-log",
        "---",
        "",
        f"# QuestDB Reconciliation Report — {today}",
        "",
        f"**Overall status:** `{overall}`  ",
        f"**Ran at:** {report['ran_at']}  ",
        f"**SQLite:** `{report['sqlite_db']}`  ",
        f"**QuestDB:** `{report['questdb_url']}`",
        "",
        "## Table Results",
        "",
        "| Table | SQLite | QuestDB | Diff% | Mode | Status |",
        "|---|---|---|---|---|---|",
    ]

    for r in report["tables"]:
        diff_pct_str = f"{r['diff_pct']:.3%}" if r["diff_pct"] is not None else "N/A"
        lines.append(
            f"| {r['table']} "
            f"| {r['sqlite_count']:,} "
            f"| {r['questdb_count']:,} "
            f"| {diff_pct_str} "
            f"| {r.get('diff_mode', 'N/A')} "
            f"| **{r['status']}** |"
        )

    lines.append("")
    lines.append("## Detail")
    lines.append("")

    for r in report["tables"]:
        lines.append(f"### {r['table']}")
        if r.get("note"):
            lines.append(f"- Note: {r['note']}")
        if r.get("confidence_interval_95pct"):
            ci = r["confidence_interval_95pct"]
            lines.append(f"- {ci['note']}")
        if r.get("missing_from_questdb_sample"):
            sample = r["missing_from_questdb_sample"]
            lines.append(f"- Missing from QuestDB ({len(sample)} shown): {sample[:10]}")
        if r.get("extra_in_questdb_sample"):
            sample = r["extra_in_questdb_sample"]
            lines.append(f"- Extra in QuestDB ({len(sample)} shown): {sample[:10]}")
        lines.append("")

    if overall in ("divergent", "critical"):
        lines += [
            "## Recommended Action",
            "",
            "Run the backfill script to close the gap:",
            "",
            "```bash",
            "python scripts/backfill_discord_to_questdb.py --table all",
            "```",
            "",
            "Or heal via this script (requires `ENABLE_QUESTDB_RECONCILE_HEAL=1`):",
            "",
            "```bash",
            "python scripts/reconcile_questdb.py --heal <table>",
            "```",
            "",
        ]

    md = "\n".join(lines)
    out = VAULT_RAW_DIR / f"reconcile-{today}.md"
    out.write_text(md, encoding="utf-8")
    logger.info("Vault markdown written: %s", out)


# ---------------------------------------------------------------------------
# Heal mode
# ---------------------------------------------------------------------------


def heal_table(table_name: str, sqlite_db: str, questdb_url: str) -> None:
    """Heal missing rows in one table by delegating to the backfill script.

    Requires ENABLE_QUESTDB_RECONCILE_HEAL=1. Errors out clearly if not set.
    Logs each heal invocation to engine/logs/questdb_heal.log.
    """
    if not is_heal_enabled():
        logger.error(
            "Heal mode requires ENABLE_QUESTDB_RECONCILE_HEAL=1. "
            "Set this flag explicitly in engine/.env or the environment."
        )
        sys.exit(1)

    HEAL_LOG.parent.mkdir(parents=True, exist_ok=True)

    # First reconcile to find what's missing
    logger.info("Pre-heal reconcile for %s ...", table_name)
    pre = reconcile_table(table_name, sqlite_db, questdb_url)
    missing = pre.get("missing_from_questdb_sample", [])

    if pre["status"] == "ok":
        logger.info("%s is already in sync — nothing to heal.", table_name)
        return

    ran_at = datetime.now(timezone.utc).isoformat()
    heal_entry = {
        "ran_at": ran_at,
        "table": table_name,
        "pre_status": pre["status"],
        "pre_diff_pct": pre["diff_pct"],
        "pre_sqlite_count": pre["sqlite_count"],
        "pre_questdb_count": pre["questdb_count"],
        "action": "backfill_script",
        "missing_sample_shown": missing[:10],
    }

    # Delegate to the backfill script — it is idempotent and handles batching
    backfill_script = _REPO_ROOT / "scripts" / "backfill_discord_to_questdb.py"
    cmd = [
        str(_ENGINE_DIR / ".venv" / "Scripts" / "python"),
        str(backfill_script),
        "--table",
        table_name,
        "--db-path",
        sqlite_db,
    ]
    logger.info("Invoking backfill for %s: %s", table_name, " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        heal_entry["returncode"] = result.returncode
        heal_entry["stdout_tail"] = result.stdout[-2000:] if result.stdout else ""
        heal_entry["stderr_tail"] = result.stderr[-500:] if result.stderr else ""
        if result.returncode != 0:
            logger.error(
                "Backfill exited %d:\n%s", result.returncode, result.stderr[-500:]
            )
        else:
            logger.info("Backfill complete. stdout tail:\n%s", result.stdout[-1000:])
    except subprocess.TimeoutExpired:
        heal_entry["error"] = "timeout after 300s"
        logger.error("Backfill timed out after 300s for %s", table_name)

    with open(HEAL_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(heal_entry) + "\n")
    logger.info("Heal log appended: %s", HEAL_LOG)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QuestDB ↔ SQLite reconciliation runner (read-only by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--table",
        choices=list(TABLES.keys()) + ["all"],
        default="all",
        help="Table to reconcile (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count comparison only — no full/sample diff query",
    )
    parser.add_argument(
        "--heal",
        metavar="TABLE",
        choices=list(TABLES.keys()),
        help=(
            "Run heal mode for TABLE — delegates to backfill script. "
            "Requires ENABLE_QUESTDB_RECONCILE_HEAL=1."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"Path to SQLite database (default: {DB_PATH})",
    )
    parser.add_argument(
        "--questdb-url",
        default=QUESTDB_BASE_URL,
        help=f"QuestDB base URL (default: {QUESTDB_BASE_URL})",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    db_path = args.db_path
    questdb_url = args.questdb_url

    if not Path(db_path).exists():
        logger.error("SQLite database not found at %s", db_path)
        sys.exit(1)

    # ---- Heal mode -------------------------------------------------------
    if args.heal:
        heal_table(args.heal, db_path, questdb_url)
        return

    # ---- Reconcile -------------------------------------------------------
    if args.table == "all":
        report = reconcile_all(db_path, questdb_url, dry_run=args.dry_run)
    else:
        today = date.today().isoformat()
        ran_at = datetime.now(timezone.utc).isoformat()
        r = reconcile_table(args.table, db_path, questdb_url, dry_run=args.dry_run)
        report = {
            "date": today,
            "ran_at": ran_at,
            "overall_status": r["status"],
            "sqlite_db": db_path,
            "questdb_url": questdb_url,
            "tables": [r],
        }
        _write_snapshot(report)
        _write_vault_markdown(report)

    # ---- Print summary ---------------------------------------------------
    print(f"\nOverall status : {report['overall_status'].upper()}")
    print(f"Ran at         : {report['ran_at']}")
    print()
    print(
        f"{'Table':<20} {'SQLite':>10} {'QuestDB':>10} {'Diff%':>8} {'Mode':<12} Status"
    )
    print("-" * 75)
    for r in report["tables"]:
        diff_str = f"{r['diff_pct']:.3%}" if r["diff_pct"] is not None else "N/A"
        print(
            f"{r['table']:<20} {r['sqlite_count']:>10,} {r['questdb_count']:>10,} "
            f"{diff_str:>8} {r.get('diff_mode', 'N/A'):<12} {r['status']}"
        )

    if report["overall_status"] == "critical":
        print("\nCRITICAL: divergence > 5% — halt cut-over plan and investigate.")
        sys.exit(2)
    elif report["overall_status"] in ("divergent", "error", "unreachable"):
        sys.exit(1)


if __name__ == "__main__":
    main()
