# Discord message_id: TEXT → INTEGER Migration Spec

**Created:** 2026-05-22  
**Target migration number:** 033  
**Estimated implementation:** 2–3 hours  
**Risk:** Medium — requires table recreation for 5 tables; FTS5 rebuild required for 1  

---

## Problem

All 5 Discord tables store Discord snowflake IDs as `TEXT` in SQLite:

| Table | Current key | Rows (approx) |
|---|---|---|
| `discord_bot_signals` | `message_id TEXT UNIQUE NOT NULL` + `id INT PK` | ~5,000 |
| `discord_ib_reports` | `message_id TEXT UNIQUE NOT NULL` + `id INT PK` | ~1,000 |
| `discord_corey_alerts` | `message_id TEXT UNIQUE NOT NULL` + `id INT PK` | ~200 |
| `discord_corey_commentary` | `message_id TEXT UNIQUE NOT NULL` + `id INT PK` | ~66,000 |
| `discord_bookmarks` | `message_id TEXT PRIMARY KEY` (no surrogate) | ~1,200 |

Discord message IDs are 64-bit integers (snowflakes). The current `TEXT` storage:
- Wastes ~12 bytes per row vs `INTEGER` (8 bytes) on a 66K-row table = ~800 KB wasted
- Forces string comparison for any ID-based range query, which silently gives wrong ordering for IDs of different digit lengths (rare but possible under account migration)
- Blocks native snowflake timestamp extraction (`(id >> 22) + 1420070400000` ms epoch)
- The `discord_bookmarks` cursor pagination is timestamp-based (`posted_at TEXT`) instead of using monotonic snowflake ordering, which is fragile when two messages land in the same second

`discord_daily_sentiment` uses `date TEXT PRIMARY KEY` (a date string, not a snowflake) and is **out of scope** for this migration.

---

## Scope

### Tables to migrate

1. `discord_bot_signals` — `message_id TEXT UNIQUE` → `message_id INTEGER UNIQUE`
2. `discord_ib_reports` — same
3. `discord_corey_alerts` — same
4. `discord_corey_commentary` — same, **plus FTS5 virtual table + 3 triggers rebuild**
5. `discord_bookmarks` — `message_id TEXT PRIMARY KEY` → `message_id INTEGER PRIMARY KEY`

### Application code to update

| File | Change |
|---|---|
| `engine/discord/models.py` | `message_id: str` → `message_id: int` on all 5 models |
| `engine/discord/storage.py` | `CREATE_TABLES_SQL` DDL update; INSERT parameter types stay `?` (sqlite3 handles int natively) |
| `engine/discord/mcp_server.py` | Return types; cursor-pagination upgrade (see §Pagination below) |
| Ingest scripts that feed these tables | Any script casting Discord API string → must be `int(msg["id"])` not `str(msg["id"])` |

---

## Pre-flight check (run before migration_033)

```sql
-- For each table, verify all message_ids are valid 64-bit integers.
-- A failing row means a non-snowflake value slipped in — investigate before proceeding.
SELECT message_id FROM discord_bot_signals
  WHERE CAST(message_id AS INTEGER) IS NULL OR CAST(message_id AS INTEGER) = 0
  LIMIT 10;

SELECT message_id FROM discord_bookmarks
  WHERE CAST(message_id AS INTEGER) IS NULL OR CAST(message_id AS INTEGER) = 0
  LIMIT 10;
-- Repeat for ib_reports, corey_alerts, corey_commentary
```

If any rows fail: the value is non-snowflake. Decide per-row: drop, assign a synthetic negative ID, or move to a `_orphan` table.

---

## Migration SQL (migration_033)

The migration runs inside a single `conn` passed by `run_migrations`. Each table follows the SQLite "12-step ALTER COLUMN" pattern: new table → copy → drop → rename.

### 1. discord_bot_signals

```sql
CREATE TABLE discord_bot_signals_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER UNIQUE NOT NULL,
    timestamp       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT,
    direction       TEXT,
    signal_type     TEXT,
    entry_price     REAL,
    target1         REAL,
    target2         REAL,
    stop1           REAL,
    stop2           REAL,
    win_rate        REAL,
    wins            INTEGER,
    losses          INTEGER,
    mfe             REAL,
    mae             REAL,
    rr              REAL,
    gain            REAL,
    draw            REAL,
    net             REAL,
    last_price      REAL,
    raw_description TEXT,
    source_channel  TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO discord_bot_signals_v2
    SELECT id, CAST(message_id AS INTEGER), timestamp, symbol, timeframe, direction,
           signal_type, entry_price, target1, target2, stop1, stop2, win_rate, wins,
           losses, mfe, mae, rr, gain, draw, net, last_price, raw_description,
           source_channel, created_at
    FROM discord_bot_signals;
DROP TABLE discord_bot_signals;
ALTER TABLE discord_bot_signals_v2 RENAME TO discord_bot_signals;
CREATE INDEX IF NOT EXISTS idx_bot_signals_symbol_ts
    ON discord_bot_signals(symbol, timestamp DESC);
```

### 2. discord_ib_reports

```sql
CREATE TABLE discord_ib_reports_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER UNIQUE NOT NULL,
    timestamp       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT,
    ib_open         REAL,
    ib_high         REAL,
    ib_low          REAL,
    ib_close        REAL,
    ib_range        REAL,
    ibu50           REAL,
    ibu100          REAL,
    ibd50           REAL,
    ibd100          REAL,
    auction_context TEXT,
    trade_plan      TEXT,
    raw_content     TEXT,
    source_channel  TEXT DEFAULT 'indicator-alerts',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO discord_ib_reports_v2
    SELECT id, CAST(message_id AS INTEGER), timestamp, symbol, timeframe,
           ib_open, ib_high, ib_low, ib_close, ib_range, ibu50, ibu100, ibd50, ibd100,
           auction_context, trade_plan, raw_content, source_channel, created_at
    FROM discord_ib_reports;
DROP TABLE discord_ib_reports;
ALTER TABLE discord_ib_reports_v2 RENAME TO discord_ib_reports;
```

### 3. discord_corey_alerts

```sql
CREATE TABLE discord_corey_alerts_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER UNIQUE NOT NULL,
    timestamp       TEXT NOT NULL,
    content         TEXT NOT NULL,
    symbol          TEXT,
    direction       TEXT,
    price           REAL,
    source_channel  TEXT DEFAULT 'trade-alerts',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO discord_corey_alerts_v2
    SELECT id, CAST(message_id AS INTEGER), timestamp, content,
           symbol, direction, price, source_channel, created_at
    FROM discord_corey_alerts;
DROP TABLE discord_corey_alerts;
ALTER TABLE discord_corey_alerts_v2 RENAME TO discord_corey_alerts;
```

### 4. discord_corey_commentary (FTS5 rebuild required)

FTS5 content tables and triggers reference the owning table by name. When the table is rebuilt, the FTS rowid linkage breaks. The safe approach: drop FTS + triggers first, recreate after table rename.

```sql
-- Step 1: drop FTS artifacts (FTS has no ALTER support)
DROP TRIGGER IF EXISTS discord_commentary_fts_ai;
DROP TRIGGER IF EXISTS discord_commentary_fts_ad;
DROP TRIGGER IF EXISTS discord_commentary_fts_au;
DROP TABLE IF EXISTS discord_commentary_fts;

-- Step 2: rebuild commentary table
CREATE TABLE discord_corey_commentary_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER UNIQUE NOT NULL,
    timestamp       TEXT NOT NULL,
    content         TEXT NOT NULL,
    channel         TEXT NOT NULL,
    author_id       TEXT DEFAULT '564449478174703646',
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO discord_corey_commentary_v2
    SELECT id, CAST(message_id AS INTEGER), timestamp, content,
           channel, author_id, created_at
    FROM discord_corey_commentary;
DROP TABLE discord_corey_commentary;
ALTER TABLE discord_corey_commentary_v2 RENAME TO discord_corey_commentary;

-- Step 3: restore FTS5 virtual table (rowid links to new table's id column)
CREATE VIRTUAL TABLE discord_commentary_fts USING fts5(content, timestamp, channel);

-- Backfill FTS from migrated data
INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
    SELECT id, content, timestamp, channel FROM discord_corey_commentary;

-- Step 4: restore triggers (identical to storage.py CREATE_TABLES_SQL)
CREATE TRIGGER discord_commentary_fts_ai
AFTER INSERT ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
    VALUES (new.id, new.content, new.timestamp, new.channel);
END;

CREATE TRIGGER discord_commentary_fts_ad
AFTER DELETE ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(discord_commentary_fts, rowid, content, timestamp, channel)
    VALUES ('delete', old.id, old.content, old.timestamp, old.channel);
END;

CREATE TRIGGER discord_commentary_fts_au
AFTER UPDATE ON discord_corey_commentary BEGIN
    INSERT INTO discord_commentary_fts(discord_commentary_fts, rowid, content, timestamp, channel)
    VALUES ('delete', old.id, old.content, old.timestamp, old.channel);
    INSERT INTO discord_commentary_fts(rowid, content, timestamp, channel)
    VALUES (new.id, new.content, new.timestamp, new.channel);
END;
```

### 5. discord_bookmarks (no surrogate integer — PRIMARY KEY changes type)

```sql
CREATE TABLE discord_bookmarks_v2 (
    message_id      INTEGER PRIMARY KEY,
    channel_id      TEXT    NOT NULL,
    posted_at       TEXT    NOT NULL,
    url             TEXT    NOT NULL,
    domain          TEXT,
    source_type     TEXT,
    embed_title     TEXT,
    embed_description TEXT,
    content         TEXT,
    author_id       TEXT,
    author_name     TEXT,
    imported_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attachment_urls TEXT
);
INSERT INTO discord_bookmarks_v2
    SELECT CAST(message_id AS INTEGER), channel_id, posted_at, url, domain,
           source_type, embed_title, embed_description, content, author_id,
           author_name, imported_at, attachment_urls
    FROM discord_bookmarks;
DROP TABLE discord_bookmarks;
ALTER TABLE discord_bookmarks_v2 RENAME TO discord_bookmarks;
CREATE INDEX IF NOT EXISTS idx_bookmarks_posted ON discord_bookmarks(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_bookmarks_domain ON discord_bookmarks(domain);
CREATE INDEX IF NOT EXISTS idx_bookmarks_source_type ON discord_bookmarks(source_type);
```

---

## Application code changes

### models.py — 5 models

```python
# Before
class BotSignal(BaseModel):
    message_id: str
    ...

# After
class BotSignal(BaseModel):
    message_id: int
    ...
```

Apply to: `BotSignal`, `IBReport`, `CoreyAlert`, `CoreyCommentary`, `Bookmark`.

### storage.py — CREATE_TABLES_SQL

Update DDL to match migration_033 target schema (INTEGER message_id). The INSERT statements use positional `?` parameters; no SQL string changes needed — sqlite3 handles Python `int` natively.

### mcp_server.py — cursor pagination upgrade (optional but recommended)

Current cursor: `posted_at TEXT ISO timestamp` — fragile if two messages share the same second.

After migration, use snowflake ID cursor instead:

```python
# Get bookmarks with snowflake cursor
def get_recent_bookmarks(before: int | None = None, page_size: int = 50):
    if before:
        rows = db.execute(
            "SELECT * FROM discord_bookmarks WHERE message_id < ? ORDER BY message_id DESC LIMIT ?",
            (before, page_size + 1)
        )
    else:
        rows = db.execute(
            "SELECT * FROM discord_bookmarks ORDER BY message_id DESC LIMIT ?",
            (page_size + 1,)
        )
    has_more = len(rows) > page_size
    page = rows[:page_size]
    return {
        "bookmarks": page,
        "next_before": page[-1]["message_id"] if has_more else None,
        "has_more": has_more,
    }
```

Rename `next_before` → `next_before_id` in the MCP tool schema to signal the type change to callers.

---

## Rollback

The migration runs inside the `migration_033(conn)` function. If any step raises, the transaction rolls back automatically (migration system uses implicit transaction). The `discord_bot_signals_v2` / `*_v2` temp tables will be left on disk — a failed run should be cleaned with:

```sql
DROP TABLE IF EXISTS discord_bot_signals_v2;
-- ... etc for each _v2 table
```

Add an explicit cleanup block at the top of migration_033 to handle partial runs:

```python
for suffix_table in ["discord_bot_signals_v2", "discord_ib_reports_v2",
                     "discord_corey_alerts_v2", "discord_corey_commentary_v2",
                     "discord_bookmarks_v2"]:
    conn.execute(f"DROP TABLE IF EXISTS {suffix_table}")
```

---

## Implementation sequence

1. **Pre-flight** (5 min): run the pre-flight SQL above; verify 0 non-castable rows.  
2. **migration_033** (1 hour): write the migration function, add to `MIGRATIONS` list.  
3. **models.py** (15 min): `str` → `int` on 5 models; run `mypy` / `ruff`.  
4. **storage.py DDL** (15 min): update `CREATE_TABLES_SQL` to match.  
5. **MCP pagination** (30 min): replace timestamp cursor with snowflake cursor; update callers.  
6. **Tests** (30 min): update test fixtures that pass `message_id` as string; run full suite.  
7. **Engine restart**: apply migration on startup; verify row counts match pre-migration snapshot.  

---

## Notes

- The migration must run with `PRAGMA foreign_keys = OFF` if any FK constraints reference these tables — currently none do (trade_journal uses a soft FK to paper_trades, not Discord tables). Safe to proceed without disabling FKs.
- `discord_daily_sentiment` (`date TEXT PRIMARY KEY`) is intentionally excluded — dates are not snowflakes.
- The `_BOOKMARK_MIGRATION_COLUMNS` list in storage.py (for ALTER TABLE ADD COLUMN idempotency) is superseded by migration_033; it can be removed once migration runs.
- QuestDB dual-write in `storage.py` passes `message_id` as a tag string — update those call sites to `str(signal.message_id)` after changing the model field to `int`.
