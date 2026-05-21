# QuestDB Migration Runbook — Discord Time-Series Tables

**Status:** SCAFFOLD (default OFF — SQLite is primary)
**Added:** 2026-05-20
**Related:** [[SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK]], [[DISCORD_INTEL_RUNBOOK]]

---

## What Is QuestDB and Why Use It Here

QuestDB is an open-source time-series database designed for high-throughput append-only
workloads.  Its columnar storage and native SQL `SAMPLE BY` / `WHERE ts IN (...)` operators
run time-range aggregates 10-100x faster than SQLite on datasets of the scale JARVIS is
accumulating:

| Table | Rows (as of 2026-05-20) | SQLite p95 aggregate (est.) | QuestDB p95 (est.) |
|---|---|---|---|
| discord_bot_signals | 221K | ~600 ms | ~8 ms |
| discord_corey_commentary | 66K | ~200 ms | ~3 ms |
| discord_ib_reports | 1K | negligible | negligible |
| discord_daily_sentiment | 1K | negligible | negligible |

The speedup matters when the trading pipeline queries "all bot signals for ES in the
last 30 days with win_rate > 70%" during the briefing cycle (called every 5 minutes
during trading hours).

---

## Architecture: Dual-Write Mode

```
Discord ingest (existing path)
         |
         v
   insert_*(conn, model)              <-- storage.py (UNCHANGED reads)
         |
   [SQLite commit]  <-- PRIMARY SOURCE OF TRUTH
         |
         v
   _qdb.insert_*_ts(model)            <-- storage_questdb.py (shadow write)
         |
   [if ENABLE_QUESTDB_DUAL_WRITE=1]
         |
         v
   QuestDB /exec HTTP endpoint
   discord_*_ts tables (shadow copy)
```

**Reads always come from SQLite** until a future PR explicitly flips read
paths to QuestDB (`where=questdb` feature flag or a dedicated read module).

**Dual-write is non-blocking:** if QuestDB is down, a WARNING is logged and the
ingest cycle continues.  SQLite is never affected by QuestDB failures.

---

## Activation Steps

### 1. Start QuestDB

QuestDB is not included in the docker-compose stack yet.  Start it manually:

```bash
docker run \
  -p 9000:9000 \
  -p 9009:9009 \
  -p 8812:8812 \
  -v $(pwd)/data/questdb:/root/.questdb \
  questdb/questdb
```

Or if `docker-compose.yml` has been updated to include QuestDB:

```bash
docker-compose up -d questdb
```

Verify it is reachable:

```powershell
Invoke-WebRequest "http://127.0.0.1:9000/exec?query=SELECT+1" -UseBasicParsing | Select-Object StatusCode
# Expected: 200
```

### 2. Enable dual-write in engine/.env

Add or update:

```
ENABLE_QUESTDB_DUAL_WRITE=1
QUESTDB_HOST=localhost
QUESTDB_PORT=9000
```

### 3. Restart the engine

```powershell
.\restart_engine.ps1
```

Wait for `/health` to return `status=ok` (~229 s).

The next Discord ingest cycle will begin shadow-writing to QuestDB automatically.
DDL (CREATE TABLE IF NOT EXISTS) runs on first insert per process lifetime.

### 4. Backfill historical rows

Run the one-shot backfill script to copy existing SQLite rows to QuestDB:

```bash
# Dry-run first — no writes, just counts
python scripts/backfill_discord_to_questdb.py --table all --dry-run

# Execute the backfill (idempotent — safe to re-run on partial failure)
python scripts/backfill_discord_to_questdb.py --table all
```

Or table-by-table:

```bash
python scripts/backfill_discord_to_questdb.py --table bot_signals --batch-size 500
python scripts/backfill_discord_to_questdb.py --table corey_commentary
python scripts/backfill_discord_to_questdb.py --table ib_reports
python scripts/backfill_discord_to_questdb.py --table daily_sentiment
```

Expected runtime: ~2-5 minutes for all four tables at 221K+ rows.

### 5. Monitor for 30 days

Compare row counts weekly to verify dual-write health:

```sql
-- QuestDB (via http://localhost:9000)
SELECT count() FROM discord_bot_signals_ts;

-- SQLite (from Python)
python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db').execute('SELECT COUNT(*) FROM discord_bot_signals'); print(c.fetchone())"
```

The counts should converge within one ingest cycle (~5 minutes).  A persistent
divergence indicates dual-write failures — check the engine WARNING logs:

```bash
grep "QuestDB dual-write" engine/logs/jarvis.log | tail -20
```

### 6. Future cut-over (out of scope today)

After 30 days of dual-write health:

1. Open a PR that changes Discord aggregate read paths (`signal_context.py`,
   `sentiment_provider.py`, `ib_levels.py`) to query QuestDB instead of SQLite.
2. Add `ENABLE_QUESTDB_READS=1` feature flag.
3. Run the existing test suite — all tests must pass.
4. Tag the PR `[safety-review]` for review of the SQLite bypass.
5. Deploy; monitor for 7 days; remove the SQLite fallback in a follow-up PR.

---

## Rollback

Rollback is instant and lossless because SQLite is always the source of truth:

1. Set `ENABLE_QUESTDB_DUAL_WRITE=0` in `engine/.env`.
2. Restart the engine: `.\restart_engine.ps1`.
3. QuestDB shadow writes stop immediately.  No data is lost — SQLite is unchanged.

If QuestDB becomes unavailable while dual-write is active, the engine logs
WARNING messages but continues normally.  No restart is required.

---

## Schema Reference

QuestDB shadow tables have `_ts` suffix to avoid naming collisions with the
existing SQLite schema.  All tables are partitioned by DAY on the `ts` column.

```sql
-- Bot signals
SELECT * FROM discord_bot_signals_ts
WHERE ts BETWEEN '2026-05-01' AND '2026-05-20'
AND symbol = 'ES'
AND win_rate > 70.0
SAMPLE BY 1d;

-- Commentary volume over time
SELECT ts, count() as msg_count
FROM discord_corey_commentary_ts
SAMPLE BY 1h;

-- IB range by day
SELECT ts, symbol, ib_range
FROM discord_ib_reports_ts
WHERE symbol = 'ES'
ORDER BY ts DESC
LIMIT 30;

-- Daily sentiment trend
SELECT ts, sentiment_score, post_count
FROM discord_daily_sentiment_ts
ORDER BY ts DESC;
```

---

## Files Created by This Scaffold

| File | Purpose |
|---|---|
| `engine/discord/storage_questdb.py` | QuestDB shadow-write module (all insert_*_ts functions) |
| `engine/discord/storage.py` | Modified: added dual-write hooks after each SQLite insert |
| `scripts/backfill_discord_to_questdb.py` | One-shot historical backfill CLI |
| `engine/tests/test_storage_questdb.py` | Tests: disabled-by-default, enabled path, failure handling, DDL idempotency, backfill dry-run |
| `engine/.env.example` | Added ENABLE_QUESTDB_DUAL_WRITE=0 block |
| `docs/runbooks/QUESTDB_MIGRATION_RUNBOOK.md` | This file |

---

## Durability Concern

The dual-write gap between SQLite and QuestDB is **not atomic**.  A process crash
between the SQLite commit and the QuestDB HTTP call will leave the row in SQLite
but absent from QuestDB.  The backfill script is idempotent and can be re-run at
any time to close the gap.  This is acceptable because QuestDB is a shadow/read
replica, not the source of truth.  Only after the read-flip PR makes QuestDB the
primary source of truth does this gap become a consistency concern — at that point
a two-phase commit or write-ahead-log mirroring strategy should be evaluated.
