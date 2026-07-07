# Sprint 17 Storage Unification — US-1703

**Status**: MIGRATION SCRIPT READY (not yet run — awaiting US-1702 commit)
**Date**: 2026-04-03
**Author**: JARVIS / US-1703 agent

---

## 1. JSON File Location(s) Found

| File | Format | Records |
|------|--------|---------|
| `engine/portfolio/trades.jsonl` | JSONL (one JSON object per line, append-only) | 13 raw lines → 11 unique trade_ids |
| `engine/data/paper_validation.json` | JSON dict keyed by symbol | 0 live trades (reset 2026-04-03, contains validation metadata only) |

**No other paper trade files found.** The task brief mentioned 416 trades; investigation
revealed the actual live paper trade count is 11 unique records (9 open, 2 closed).
Backtest result files in `engine/backtest/results/` contain historical simulation trades
(entry_date/exit_date schema) — these are **not** paper trades and are **excluded** from
this migration. Migrating backtest results into `paper_trades` would misrepresent them as
live executed trades.

---

## 2. Record Count in JSON

### trades.jsonl breakdown (after deduplication — last record per trade_id wins)

| Status | Count | Symbols |
|--------|-------|---------|
| Closed | 2 | MES (2) |
| Open | 9 | MES (1), MCL (8) |
| **Total unique** | **11** | |

### Existing SQLite paper_trades (pre-migration)

| trade_id prefix | Symbol | Side | pnl | Status |
|----------------|--------|------|-----|--------|
| MES_2026-04-02_long | MES | long | NULL | closed |
| MES_2026-04-03_short | MES | short | NULL | closed |
| MES_2026-04-01_long | MES | long | NULL | closed |
| MES_2026-04-02_long_5810 | MES | long | NULL | closed |
| d85d810b | MCL | buy | NULL | open |
| b6f20a35 | MCL | buy | NULL | open |

**Net new records migration would insert: 9** (2 JSONL records already in SQLite)

---

## 3. Schema Mapping (JSON field → SQLite column)

| JSONL Field | SQLite Column | Notes |
|------------|---------------|-------|
| `trade_id` | `trade_id` | Direct map; used as dedup key (ON CONFLICT IGNORE) |
| `symbol` | `symbol` | Uppercased |
| `action` | `side` | "buy"/"buy_to_open" → "buy"; "sell"/"short" → "sell" |
| `quantity` | `quantity` | Cast to REAL |
| `entry_price` | `entry_price` | Cast to REAL |
| `exit_price` | `exit_price` | NULL for open trades |
| `entry_time` | `entry_time` | ISO-8601 string, direct map |
| `exit_time` | `exit_time` | NULL for open trades |
| `pnl` | `pnl` | Recomputed if NULL on closed trades (see below) |
| `is_open` | `status` | `True` → `'open'`, `False` → `'closed'` |
| `notes` | `notes` | Direct map |
| *(absent)* | `regime` | NULL — not in JSONL schema |
| *(absent)* | `strategy_params` | NULL — not in JSONL schema |
| *(absent)* | `structure_position` | NULL — not in JSONL schema |
| *(absent)* | `bias` | NULL — not in JSONL schema |
| *(absent)* | `composite_score` | NULL — not in JSONL schema |
| *(absent)* | `stc_contrib` | NULL — not in JSONL schema |
| *(absent)* | `orb_contrib` | NULL — not in JSONL schema |
| *(absent)* | `vwap_contrib` | NULL — not in JSONL schema |
| *(absent)* | `risk_pct_used` | NULL — not in JSONL schema |

### PnL Recomputation Formula

For closed trades with `pnl = NULL`:

```
multiplier = INSTRUMENT_MULTIPLIERS[symbol]  # MCL=100, MNQ=2, MES=5, MGC=10
LONG  pnl = (exit_price - entry_price) * quantity * multiplier
SHORT pnl = (entry_price - exit_price) * quantity * multiplier
```

Both closed JSONL trades already have pnl populated (MES: $20.00 and $10.00),
so no recomputation will be needed for the current 11 records.

---

## 4. Schema Gaps

### Fields in JSONL not in SQLite paper_trades
| JSONL Field | Disposition |
|-------------|-------------|
| `is_open` | Mapped to `status` text column; not stored separately |
| `stop_loss` | Present on PaperTrade dataclass but not written to JSONL by open_trade() |
| `take_profit` | Same — not in JSONL |
| `atr_value` | Same — not in JSONL |

### Fields in SQLite not in JSONL
These columns will be NULL for all migrated records:
`regime`, `structure_position`, `bias`, `composite_score`, `stc_contrib`,
`orb_contrib`, `vwap_contrib`, `risk_pct_used`, `strategy_params`

These richer fields are only populated by the full pipeline path
(`add_paper_trade()` with strategy_params dict), not by the simpler
`open_trade()` path that writes to JSONL.

---

## 5. Migration Script Location

```
engine/scripts/migrate_json_to_sqlite.py
```

### Usage

```bash
# Dry-run (shows what would be inserted, touches nothing)
cd engine
.venv/Scripts/python scripts/migrate_json_to_sqlite.py --dry-run

# Live run (after US-1702 merges)
.venv/Scripts/python scripts/migrate_json_to_sqlite.py
```

### Dry-run output (verified 2026-04-03)

```
JSONL: 13 raw lines → 11 unique trade_ids
SQLite: 6 existing trade_ids in paper_trades
[DRY-RUN] would insert 62753104  MES  buy  pnl=20.00  status=closed
[DRY-RUN] would insert d67b1e39  MES  buy  pnl=10.00  status=closed
[DRY-RUN] would insert 4c1ed80d  MES  buy  pnl=NULL  status=open
... (6 more MCL open trades)

Records read  : 11
Records inserted : 9
Records skipped (duplicate) : 2
Records skipped (invalid)   : 0
```

---

## 6. JSONL Write Path — Marked for Removal

The canonical JSON write path in `engine/portfolio/tracker.py` is method `_append_record()`.
It has been marked with a TODO comment:

```python
# TODO Sprint 17 US-1703: Remove this JSON write path after migration completes.
# JSON write path marked for removal — SQLite will be canonical after migration.
```

**Do not remove this method yet.** It serves as the audit fallback until the migration
runs successfully and SQLite is verified as the sole source of truth.

---

## 7. Dependency Chain

```
US-1701 (add SQLITE_DB_PATH to config, delete ghost DB)
    ↓
US-1702 (fix NULL pnl in close_trade())
    ↓
US-1703 (run migration) ← THIS TICKET
```

Migration must run AFTER US-1702 commits to ensure any newly closed trades written during
the migration window have correct pnl values in SQLite.

---

## 8. Post-Migration Verification Checklist

Run after `migrate_json_to_sqlite.py` succeeds:

- [ ] `SELECT COUNT(*) FROM paper_trades` shows 15 records (6 existing + 9 new)
- [ ] All 2 closed MES trades from JSONL have non-NULL pnl in SQLite
- [ ] All 9 open trades appear with `status='open'` and `exit_price IS NULL`
- [ ] `GET /api/v1/portfolio/trades` returns all 15 records
- [ ] `GET /api/v1/portfolio/performance` reflects correct trade count
- [ ] JSONL file still exists as audit log (do not delete yet)
