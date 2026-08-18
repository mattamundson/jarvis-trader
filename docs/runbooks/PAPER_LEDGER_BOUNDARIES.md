# Paper ledger — writers and readers (B-first for the dashboard)

Companion to [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md). This doc names **who may write** vs **who reads** so validation metrics and the UI stay consistent.

## Mode B (engine API — dashboard default)

- **Writer:** `PortfolioTracker` persistence (SQLite / configured store) when legs are opened or closed via **`POST /portfolio/paper/trade`** and related portfolio routes.
- **Readers:** `GET /portfolio/paper/*`, `GET /portfolio/history/trades`, validation surfaces that query the same store.

Treat **B** as the **canonical book** for anything the Next.js dashboard shows through `fetchEngine`.

## Mode A (file-backed runner)

- **Writer:** `paper_runner` → `paper_positions.json`, `paper_trades_live.json` (and siblings under `engine/backtest/results/` per runner config).
- **Readers:** Headless jobs, ad-hoc scripts, or future dashboard features that explicitly read those files.

**A** is not merged into **B** unless **A→B sync** is enabled (`JARVIS_ENGINE_URL` + `JARVIS_API_KEY` on the runner host).

## `PaperTradeLogger` (`data/paper_trades.json`)

- **Always** appends fills to `data/paper_trades.json` (audit / IB connector paper simulation).
- When constructed with a **`PortfolioTracker`** and **`mirror_to_tracker=True`** (default), it also mirrors **full** net-position cycles per symbol: flat → non-zero → flat. **Partial** adds/reduces (net stays non-zero) are logged to JSON only until richer mapping exists.

`IBGatewayConnector` accepts optional **`portfolio_tracker`** and passes it through to `PaperTradeLogger` when you wire the engine book into the connector.

## Consolidation direction (engineering)

**B** remains canonical for the dashboard. JSON is a secondary audit; mirroring keeps connector fills aligned with **`PortfolioTracker`** for full round-trips. **A** (runner files) is unchanged — use **A→B sync** per [PAPER_DATA_SOURCES.md](PAPER_DATA_SOURCES.md) when ops needs one view.

## Update 2026-07-28 (MR-0.3): PortfolioTracker's JSONL/SQLite duality is resolved

The rest of this doc (above) predates US-1703 and describes the broader
multi-mode landscape. This section closes the loop on the specific
`PortfolioTracker` JSONL-vs-SQLite duality it references in Mode B.

**`engine/data/jarvis_trader.db` (`paper_trades` table) is the sole canonical
paper-trade ledger for `PortfolioTracker`.** US-1703 (commit `10c4f1b`,
2026-06-17) retired the parallel JSONL write: `PortfolioTracker._append_record()`
and `_load_history()` are both gated on `self._db is None` — when a
`db_manager` is active (true in every real deployment), the JSONL write and
replay are skipped entirely. The JSONL write only survives in no-DB fallback
modes (some tests, or a degraded startup with no database configured).

`engine/portfolio/trades.jsonl` itself is **frozen** as of the cutover
(mtime `2026-06-16T19:17:33Z`) and kept on disk, not deleted, per this
project's archive-never-delete norm — it's a historical audit artifact of
the pre-SQLite era, not a live ledger. Root cause it replaced: the JSONL
ledger carried no `status` field, so it never reflected DB-layer curation
(duplicate cancellation, contaminated-row voiding, phantom voids) and
accreted an unbounded, uncurated superset — directly implicated in the
phantom MES "+$30,918 / 43 open" forward-test book incident (2026-06-16).

### Known gap: the one-time migration was never completed against the final JSONL state

`scripts/migrate_json_to_sqlite.py` (written 2026-04-03, US-1703) is the
one-time backfill tool that copies JSONL trade records into `paper_trades`
(dedup by trade_id, `INSERT OR IGNORE` so it can never clobber an existing
SQLite row, recomputes NULL pnl). It ran once early (dry-run showed 11
unique trade_ids, 9 inserted) against an early, much smaller snapshot of the
JSONL file. The JSONL file kept growing under dual-write mode for another
~2.5 months before the 2026-06-17 cutover froze it at its final, larger
state — the migration was never re-run against that final state.

**Verified 2026-07-28** via `scripts/reconcile_paper_sources.py` (new, see
below):

- JSONL (frozen): 100 unique trade_ids
- SQLite (`paper_trades`): 96 rows
- **60 JSONL trade_ids are absent from SQLite**, of which:
  - 4 are synthetic backtest/simulation placeholders, not real paper trades
    (bare-date `entry_time` like `"2026-04-01"`, `action: "long"` instead of
    `buy`/`sell`, `entry_price == exit_price` with `pnl: 0.0` — matches the
    migration script's own "task brief count referred to backtest simulation
    results which are excluded" note). Correctly excluded, no action needed.
  - **56 are real UUID4-format historical paper trades that exist only in
    the frozen JSONL file and were never migrated to SQLite.** These predate
    the SQLite-only era; they do not affect any currently-running code path
    (which reads `paper_trades` exclusively), but any all-time historical
    count/P&L total computed from `paper_trades` alone undercounts actual
    historical paper-trading activity by these 56 trades.

**Remedy (not run — needs Amo's call):**

```
cd engine
.venv/Scripts/python scripts/migrate_json_to_sqlite.py --dry-run   # preview
.venv/Scripts/python scripts/migrate_json_to_sqlite.py              # backfill for real
```

Additive-only (`INSERT OR IGNORE`, cannot alter or delete an existing
`paper_trades` row), reusing an already-tested, already-reviewed script.
Deliberately not run automatically here: inserting 56 historical rows
retroactively shifts all-time aggregate numbers (total trade count,
cumulative historical P&L) that Amo may already have looked at and
internalized — the same "re-baselining is a consequential moment, not a
loop's call" reasoning already applied to MR-0.5b elsewhere in the
roadmap-drain queue. Once run, `scripts/reconcile_paper_sources.py` should
report `divergent_count: 4` (only the legitimately-excluded synthetic IDs)
rather than 0.

### Ongoing verification

```
cd engine
.venv/Scripts/python scripts/reconcile_paper_sources.py
```

Read-only. Reports the divergent trade_id count (JSONL-only rows not present
in SQLite) and confirms the JSONL file's mtime hasn't advanced past the
cutover. Exit 0 = clean, exit 1 = drift found. Never mutates either ledger.
