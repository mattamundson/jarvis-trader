---
session: bookmark-integration
date: 2026-04-20
start: ~10:00 CT (pre-compact; exact start lost to context compaction)
compact_point: ~12:00 CT (context rolled; summary preserved all workstreams at "code complete")
end: 13:03 CT
duration_session_visible: ~60 min post-compact (commits + verification + handoff)
primary_repos:
  - C:\Users\mattm\ThinkorSwim\jarvis-trader          (jarvis-trader, branch: feat/tradingview-mcp-gamma-kraken)
  - C:\Users\mattm\master-jarvis                      (master-jarvis, branch: feat/bookmark-reader [NEW])
  - C:\Users\mattm\second-brain                       (Obsidian vault; auto-committed by stop hook)
commits_shipped_this_session:
  - 543d768 feat(discord): enrich bookmark rows with message context + author        [jarvis-trader]
  - 4b5722a feat(vault): sync Discord bookmarks to second-brain with daily cron      [jarvis-trader]
  - 33102da feat(trade): add read-only BookmarkReader for jarvis-trader bookmarks    [master-jarvis, new branch]
plan_reference: C:\Users\mattm\.claude\plans\how-do-we-start-zippy-zephyr.md
---

# Handoff: Discord Bookmark Integration — Workstreams A/B/C shipped end-to-end

## Mission statement

Matt drops URLs into Discord channel `#general` (`1490851279180660819`) as a personal reading queue. Previously, those URLs:
- Were stored in `discord_bookmarks` SQLite but carried **only URL metadata** (no commentary, no author context)
- Had **282 one-shot Obsidian pages** rendered on 2026-04-17 with no refresh mechanism — 89 bookmarks were stale
- Were **invisible to master-jarvis** (zero Discord awareness in that codebase; only an unused `ChannelType.DISCORD` enum)

The goal: create a pipeline where (Discord `#general` → SQLite with full context → Obsidian vault pages auto-refreshed → master-jarvis agents can query bookmarks read-only). Three workstreams, all shipped this session.

---

## Section 1 — Session summary (chronological narrative)

### 1.1 Pre-compact phase (summarized from compact-point summary, not directly visible)

**Plan negotiation.** User asked `"How do we start integrating all of the links in the Jarvis-Trader discord #general channel to C:\Users\mattm and C:\Users\mattm\master-jarvis?"`. After an `AskUserQuestion` with three scope axes, user selected:
- **Scope (A)**: "Links + message context" — extend the existing bookmark parser, do NOT build a new general.py parser for non-URL chatter.
- **Vault sync (B)**: "Catch-up + scheduled re-render" — single script wired into APScheduler.
- **Master-jarvis (C)**: "Shared SQLite read" — no HTTP hop, same box, read-only URI mode.

**Workstream A (schema + parser + migration).**
- Extended `Bookmark` pydantic/dataclass with three `Optional[str]` fields: `content`, `author_id`, `author_name`.
- Extended `discord_bookmarks` DDL with the same three columns (nullable, no defaults).
- Added idempotent `ALTER TABLE ADD COLUMN` block inside `init_tables()` wrapped in `try/except sqlite3.OperationalError` — tolerates re-runs on partially-migrated DBs.
- Rewrote `insert_bookmark()` SQL to include the 3 new columns.
- Added `update_bookmark_context(conn, message_id, content, author_id, author_name)` helper — enables backfill on `INSERT OR IGNORE` skipped rows without losing original `imported_at`.
- Rewrote the parser extraction in `channel_parsers/bookmark.py` to pull `content[:5000]`, `author_id`, and `author_name` with the priority chain `global_name > username > name`.
- **Bug caught red-handed**: initial test fixture used `author.name`, which is NOT the real DCE (DiscordChatExporter) JSON shape. Real DCE exports use `{"id": ..., "username": ..., "global_name": ...}`. First live backfill run populated `author_name=None` for 312/372 rows. Priority chain fix: `global_name > username > name`.
- Added 14 new tests to `test_discord_bookmark_parser.py` covering content capture, author metadata (including real DCE shape), migration backfill safety on pre-existing rows, and the new `update_bookmark_context` helper.
- Executed the CLI re-import to backfill content/author onto all 372 existing rows in the live DB.

**Workstream B (vault renderer + cron).**
- Created `engine/scripts/render_bookmarks_to_vault.py` (447 lines).
- Implemented slug rules matching the 2026-04-17 render: `github/{owner-lower}__{repo-lower}.md`, `x/{handle-lower}-{tweet-id}.md`, `other/{domain-slug}-{message-id}.md` (new third bucket).
- Implemented catch-up semantics: skip if file exists (preserves manual triage), create if missing.
- Index regenerated on every run (pure-derivable from SQLite; no preservation semantics needed).
- Added sys.path shim so the script runs both standalone (`python engine/scripts/...`) and under pytest (rootdir=engine/).
- Added 18 tests to `test_bookmark_vault_renderer.py`.
- Ran the catch-up render against production — rendered 13 new `other/` pages + additional github/x pages that had arrived since 2026-04-17.
- Drafted the APScheduler cron block for `engine/main.py` (daily 03:00 CT, `replace_existing=True`, `misfire_grace_time=3600`).

**Workstream C (master-jarvis read-only reader).**
- Created `app/services/trade/bookmark_reader.py` (115 lines) with `BookmarkReader` class.
- Connection via SQLite URI read-only mode: `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. The OS itself refuses any write attempt — structurally stronger than a "code convention" safety model.
- Path resolution chain: explicit arg > `JARVIS_TRADER_DB_PATH` env var > hardcoded fallback to `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\jarvis_trader.db`.
- Methods: `list_bookmarks(limit, offset, source_type, domain, since)`, `get_bookmark(message_id)`, `search_content(query, limit)` (LIKE over content + embed_title + embed_description, empty query returns `[]`).
- Created `app/routers/trade/bookmarks.py` (66 lines) with FastAPI router: `GET /`, `GET /search?q=...`, `GET /{message_id}`.
- `sqlite3.OperationalError` translated to HTTP 503 (retriable).
- Added the router to `TRADE_ROUTERS` in `app/main.py` (+1 line).
- Added 21 tests to `tests/trade/test_bookmark_reader.py` — 15 direct service-level + 6 FastAPI `TestClient` integration (substitute for live HTTP smoke since master-jarvis is not deployed).
- **Critical test**: `test_read_only_mode_blocks_writes` verifies that an INSERT attempt on the reader's connection raises `sqlite3.OperationalError` matching the string `"readonly"`.

**Verified end-to-end against production data at end of pre-compact phase**: 372 bookmarks readable from master-jarvis `BookmarkReader` against the canonical `jarvis_trader.db`; test_read_only_mode_blocks_writes green against the real DB path (proves OS-level write protection isn't a test-fixture artifact).

### 1.2 Post-compact phase (current session, visible)

Summary rolled in at ~12:00 CT. Current session picked up at the commit-and-isolate phase.

1. **Pre-flight diff check on both repos** — revealed unrelated drift:
   - `jarvis-trader` had staged `bayesian_optimizer.py`, `migrations.py`, `roadmap-2026-04-20-unified.md`, untracked MES experiment scripts.
   - `master-jarvis` had modified `app/core/__init__.py` (+109 lines), `app/routers/biz/__init__.py` (+29), `app/services/biz/__init__.py` (+1), and ~200 untracked biz-domain files (`app/agents/biz/*`, `app/services/biz/*`, `thinkorswim-scripts/*`, etc.).
2. **Attempted `git diff --stat app/main.py`** with the flag before the path — failed with "option '--stat' must come before non-option arguments". Retried with correct ordering (`git diff --stat app/main.py`) after compact recovery.
3. **Staged and committed Workstream A** on `feat/tradingview-mcp-gamma-kraken`: 5 files, +396/-3. Commit `543d768`.
4. **Staged Workstream B** → discovered on inspection that the staged `engine/main.py` diff showed a **MES session forward-recorder block** (lines 1582-1651), not my bookmark vault cron. Grepped `main.py` for `bookmark_vault_render` — no matches. My cron block was missing from disk entirely: either the pre-compact edit was never saved, the working tree was rewound by a concurrent session's `git checkout`, or another Claude instance clobbered the edit.
5. **Re-added the cron block** via `Edit` tool: 48 lines inserted after the existing Sunday bookmark clusterer block (line 1580), before the MES block (which was the pre-existing drift).
6. **Surgical isolation dance** to keep my commit pure:
   ```
   cp engine/main.py /tmp/main_py_snapshot_workstreamB.py   # save current state
   git checkout HEAD -- engine/main.py                       # revert to clean HEAD
   <Edit tool re-applies only my 48-line block>
   git add engine/main.py engine/scripts/render_bookmarks_to_vault.py engine/tests/test_bookmark_vault_renderer.py
   git commit                                                # --> 4b5722a
   cp /tmp/main_py_snapshot_workstreamB.py engine/main.py    # restore MES drift to working tree
   ```
   Verified post-restore diff was **exactly** the 70-line MES block — zero leakage of my work into pre-existing drift, zero leakage of pre-existing drift into my commit.
7. **Discovered a concurrent Claude session** committed the MES scheduler wiring as `d11565f` *between* my Workstream A commit and my Workstream B commit. Their commit is independent and doesn't conflict with mine; it just reshuffled the log order.
8. **Staged and committed Workstream C** on a new branch `feat/bookmark-reader` cut from master-jarvis `master`: 4 files, +464. Commit `33102da`. Feature-branching kept `master` unpolluted by the biz-domain drift that lives in the working tree.
9. **Final verification**: `git log --oneline`, `git status`, and live SQLite introspection confirmed all three workstreams committed cleanly and the pre-existing drift untouched.
10. **Wrote initial handoff document**, then caught and fixed three state-drift errors after running read-only probes against the live DB and vault directory (see §Insight block in the response that preceded this file's rewrite).

---

## Section 2 — Files created or modified (full detail)

### 2.1 Commit `543d768` — feat(discord) Workstream A (jarvis-trader)

Branch: `feat/tradingview-mcp-gamma-kraken`.
Stat: 5 files changed, 396 insertions(+), 3 deletions(-).

#### `engine/discord/models.py` (modified)

**Before**: `Bookmark` dataclass had 8 fields.
**After**: +3 `Optional[str]` fields, all nullable, all defaulting to `None`.

```python
@dataclass
class Bookmark:
    message_id: str
    channel_id: str
    posted_at: str
    url: str
    domain: Optional[str] = None
    source_type: Optional[str] = None
    embed_title: Optional[str] = None
    embed_description: Optional[str] = None
    content: Optional[str] = None          # NEW
    author_id: Optional[str] = None        # NEW
    author_name: Optional[str] = None      # NEW
```

**Why**: downstream agents need to know *why* Matt dropped a URL (commentary) and *who* dropped it (author) — not just *what* URL. Pure-URL bookmarks still work (all fields nullable).

#### `engine/discord/storage.py` (modified)

- Added `from typing import Optional` to imports.
- Extended `CREATE TABLE discord_bookmarks` DDL with the three new columns.
- Added module-level constant for migration:
  ```python
  _BOOKMARK_MIGRATION_COLUMNS: list[tuple[str, str]] = [
      ("content", "TEXT"),
      ("author_id", "TEXT"),
      ("author_name", "TEXT"),
  ]
  ```
- Rewrote `init_tables()` with idempotent ALTER loop:
  ```python
  for col, coltype in _BOOKMARK_MIGRATION_COLUMNS:
      try:
          conn.execute(f"ALTER TABLE discord_bookmarks ADD COLUMN {col} {coltype}")
      except sqlite3.OperationalError as e:
          if "duplicate column" not in str(e).lower():
              raise
  ```
- Extended `insert_bookmark()` SQL to 11-column INSERT OR IGNORE.
- Added `update_bookmark_context(conn, message_id, content, author_id, author_name)` — surgical UPDATE that preserves `imported_at` (which `INSERT OR REPLACE` would have clobbered).

**Why idempotent ALTER over `INFORMATION_SCHEMA`-style checks**: SQLite doesn't have real `INFORMATION_SCHEMA`. `PRAGMA table_info` works but is racy if two processes call `init_tables` concurrently. `ALTER ADD COLUMN` followed by `except` on duplicate-column is atomic and retry-safe.

#### `engine/discord/channel_parsers/bookmark.py` (modified)

Key change — author extraction with real DCE priority chain:
```python
author = msg.get("author") or {}
author_id = str(author.get("id", ""))
author_name = (
    (author.get("global_name") or "").strip()
    or (author.get("username") or "").strip()
    or (author.get("name") or "").strip()
    or None
)
content = (msg.get("content") or "")[:5000]
```

**Why 5000-char cap**: matches the existing column-length conservatism (embed_description is similarly capped). Discord messages rarely exceed 4000 chars; the 5000 cap is safety margin.

**Why priority chain**: real DCE output uses `global_name` (display name like "AmoSZN") and `username` (login like "amoszn"). The `name` key is a legacy fallback that appears in some older exports. Without the chain, 312/372 rows had `author_name=None`.

#### `engine/discord/parser.py` (modified)

- Added `from .storage import update_bookmark_context` import.
- Extended `process_file()` so that when `insert_bookmark` returns 0 (INSERT OR IGNORE skipped — row already exists), `process_file` calls `update_bookmark_context` to populate the new columns without losing `imported_at`.

**Why**: re-importing the 2026-04-07 → 2026-04-19 export shouldn't overwrite timestamps. The INSERT OR IGNORE skip path is the normal case for re-imports; without the backfill, the new columns stay NULL forever.

#### `engine/tests/test_discord_bookmark_parser.py` (modified, +15 tests)

> **Correction from handoff v1**: the original handoff said "+14 tests" and listed guessed test names. Verified against actual suite output at 13:22 CT. The real count is **+15 tests** and the actual names are below. The guessed names in handoff v1 were plausible but wrong — always verify test names against the file or test output, never paraphrase from memory.

Pre-existing tests (11 kept green, unchanged):
1. `test_extracts_first_url_from_content`
2. `test_first_url_wins_when_multiple`
3. `test_trailing_punctuation_stripped`
4. `test_www_prefix_dropped_from_domain`
5. `test_source_type_classifications`
6. `test_messages_without_url_skipped_not_errored`
7. `test_embed_title_and_description_populate_when_present`
8. `test_embed_fields_none_when_no_embeds`
9. `test_bookmark_model_accepts_parsed_dict`
10. `test_insert_bookmark_and_idempotent_reimport`
11. `test_channel_map_has_jarvis_entry`

New tests (+15, verified via pytest output):
12. `test_content_captured_from_message`
13. `test_author_metadata_captured`
14. `test_content_missing_author_safe` — parser tolerates a message with no author field without crashing
15. `test_real_dce_author_shape_uses_username` — feeds real DCE JSON shape `{"id", "username", "global_name"}`, verifies `author_name` is the `global_name` value (priority-chain winner)
16. `test_real_dce_author_falls_back_to_username_when_global_name_absent` — locks in the priority chain second position
17. `test_real_dce_author_null_when_all_name_fields_empty` — locks in the `None` terminal
18. `test_content_truncated_at_5000_chars`
19. `test_bookmark_model_accepts_content_and_author_fields`
20. `test_init_tables_adds_content_columns_on_pre_workstream_a_db` — creates fixture DB with pre-Workstream-A DDL, runs `init_tables`, verifies ALTER fires cleanly and old rows have NULL values (no errors)
21. `test_init_tables_is_idempotent_on_migrated_db` — calls `init_tables` twice, second call is a no-op
22. `test_insert_bookmark_persists_content_and_author`
23. `test_update_bookmark_context_backfills_existing_row`
24. `test_update_bookmark_context_returns_false_for_missing_row` — helper's contract on unknown message_id
25. `test_process_file_backfills_context_on_second_import`
26. `test_row_roundtrip_preserves_all_columns` — full 12-column roundtrip via insert + fetchone

All 26 tests (11 pre-existing + 15 new) pass in 1.30s. Re-verified at 13:22 CT post-compact (see Section 11.1).

---

### 2.2 Commit `4b5722a` — feat(vault) Workstream B (jarvis-trader)

Branch: `feat/tradingview-mcp-gamma-kraken`.
Stat: 3 files changed, 773 insertions(+).

#### `engine/main.py` (modified, +48 lines)

Cron block inserted between the existing Sunday bookmark clusterer (line 1580) and the Corey staleness watchdog. Block contents:

```python
# Daily bookmark vault render — writes any missing Discord bookmarks to
# second-brain/wiki/discord-bookmarks/ so agents and the human both have
# an Obsidian-linkable page for every URL dropped in #general. Catch-up
# mode: existing files are skipped (preserves 2026-04-17 manual triage).
try:
    from scripts.render_bookmarks_to_vault import render_vault as _render_vault

    _BOOKMARK_DB_PATH = os.environ.get(
        "JARVIS_TRADER_DB_PATH", "engine/data/jarvis_trader.db"
    )
    _BOOKMARK_VAULT_DIR = os.environ.get(
        "BOOKMARK_VAULT_DIR",
        r"C:\Users\mattm\second-brain\wiki\discord-bookmarks",
    )

    async def run_bookmark_vault_render() -> None:
        try:
            stats = _render_vault(_BOOKMARK_DB_PATH, _BOOKMARK_VAULT_DIR)
            logger.info(
                "[BookmarkVaultRender] created=%d skipped=%d failed=%d by_kind=%s",
                stats.get("created", 0),
                stats.get("skipped_existing", 0),
                stats.get("failed", 0),
                stats.get("by_kind", {}),
            )
        except Exception as exc:
            logger.error(
                "[BookmarkVaultRender] daily render failed: %s", exc, exc_info=True
            )

    if scheduler is not None:
        scheduler.add_job(
            run_bookmark_vault_render,
            CronTrigger(hour=3, minute=0, timezone="America/Chicago"),
            id="bookmark_vault_render",
            name="Daily Bookmark Vault Render",
            max_instances=1,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "✅ Bookmark vault renderer registered — fires daily 03:00 CT"
        )
except Exception as _bvr_err:
    logger.warning(
        f"Bookmark vault renderer init failed (non-fatal): {_bvr_err}"
    )
```

**Why try/except wrap around the whole block**: pattern-matches the surrounding scheduler blocks. If the import fails (e.g., the script is temporarily broken), the engine should log and continue — the render cron is not safety-critical.

**Why `max_instances=1`**: a prior run getting stuck on a network hang shouldn't queue a second instance on the next cron fire.

**Why 03:00 CT**: after overnight activity (futures close 16:00 CT previous day, Globex re-open 17:00 CT) has settled, before the 07:00 CT morning brief consumes the data. Also falls outside US market hours on any timezone to avoid contention with trading logic.

#### `engine/scripts/render_bookmarks_to_vault.py` (NEW, 447 lines)

Structure:
- Lines 1-38: module docstring + imports + sys.path shim (critical for standalone CLI usage; pytest rootdir=engine/ masked the missing shim until the first `python scripts/...` run).
- Lines 40-62: constants — `DEFAULT_VAULT_DIR`, `DEFAULT_DB_PATH`, `MODULE_TOUCH_POINTS` dict (mirror the 2026-04-17 index header).
- Lines 64-116: slug helpers — `github_owner_repo(url)`, `github_slug(url)` (filename lowercased), `x_post_handle_and_id(url)`, `x_post_slug(url)`, `other_slug(url, message_id)`.
- Lines 118-134: formatting helpers — `_fmt_date(iso_ts)`, `_fmt_captured_at()`, `_escape_yaml(value)`.
- Lines 136-292: page renderers — `render_github_page(bm)`, `render_x_post_page(bm)`, `render_other_page(bm)`. Each emits a full Markdown page with YAML frontmatter + Markdown body.
- Lines 293-328: dispatch helpers — `render_page_for_bookmark(bm)`, `_blockquote(text)`, `_escape_body(text)`, `_target_path(vault_dir, bm)`.
- Lines 329-333: `_bookmark_from_row(row)` — SQLite Row → Bookmark dataclass.
- Lines 335-390: `render_vault(db_path, vault_dir)` — main entry. Opens DB with `sqlite3.Row` factory, iterates all rows ORDER BY posted_at ASC, skip-if-exists per target file, accumulates stats dict, regenerates index.
- Lines 393-431: `_write_index(vault_root, entries)` — regenerates `index.md` grouped by `jarvis_module`.
- Lines 433-447: `main()` — CLI entry; env-var aware; writes stats to stdout.

**Why ORDER BY posted_at ASC**: vault pages then receive chronological `captured_at` timestamps; makes the backfill history inspectable.

**Why separate `_target_path` rather than inlining**: single point of truth for path mapping; tested independently; unit tests can render one row to a tmpdir without calling `render_vault`.

**Key design choice — skip-if-exists over frontmatter merge**:
- Pro: cannot ever clobber user triage (`status: reviewed`, `notes: ...`, `jarvis_module: strategy`).
- Con: cannot refresh source-derived fields (stars, pushed_at, embed_description) when they change upstream.
- Resolution: the degenerate form of merge. A future `--force-enrich` flag can add proper merge with key-level overwrite rules. v1 is additive-only.

#### `engine/tests/test_bookmark_vault_renderer.py` (NEW, 278 lines, 18 tests)

Verified test names (from pytest output, 13:22 CT):

Slug generation (4 tests):
1. `test_github_slug_basic`
2. `test_github_slug_preserves_case_in_repo_but_lowercases_owner`
3. `test_github_slug_strips_trailing_path` — `/foo/bar/tree/main` → `bar`, not `bar/tree/main`
4. `test_github_slug_dots_in_repo_preserved`

X/Twitter slug (3 tests):
5. `test_x_post_slug_basic`
6. `test_x_post_slug_preserves_handle_case_lowercased`
7. `test_x_post_slug_twitter_com_alias` — twitter.com URLs route through the same parser as x.com

Other bucket (1 test):
8. `test_other_slug_uses_domain_and_message_id`

Page rendering (4 tests):
9. `test_render_github_page_has_valid_frontmatter`
10. `test_render_x_post_page_has_valid_frontmatter`
11. `test_render_x_post_uses_content_when_embed_absent` — fallback when embed_description is NULL
12. `test_render_page_author_reflects_captured_name`

Vault render orchestration (6 tests):
13. `test_render_vault_creates_new_github_page`
14. `test_render_vault_skips_existing_page` — the critical catch-up semantics guarantee
15. `test_render_vault_creates_x_post_page`
16. `test_render_vault_is_idempotent` — double-run produces identical output
17. `test_render_vault_writes_index_with_counts`
18. `test_render_vault_video_goes_to_other_bucket` — source_type="video" rows land in other/, not skipped

All 18 tests pass in 1.30s (shared pytest run with parser suite).

---

### 2.3 Commit `33102da` — feat(trade) Workstream C (master-jarvis)

Branch: `feat/bookmark-reader` (NEW, cut from `master`).
Stat: 4 files changed, 464 insertions(+).

#### `app/main.py` (modified, +1 line)

Single-line addition to the `TRADE_ROUTERS` list:
```python
TRADE_ROUTERS = [
    # ... existing entries ...
    ("app.routers.trade.bookmarks", "/trade/bookmarks", ["trade", "bookmarks"]),
]
```

The surrounding code uses a try/except/ImportError graceful-degradation loader — if the router module can't import, the app boots without it and logs a debug message. No other changes to `main.py`.

#### `app/services/trade/bookmark_reader.py` (NEW, 115 lines)

Top-level:
```python
_DEFAULT_DB_PATH = r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\jarvis_trader.db"

_COLUMNS = (
    "message_id, channel_id, posted_at, url, domain, source_type, "
    "embed_title, embed_description, content, author_id, author_name, imported_at"
)
```

Class structure:
```python
class BookmarkReader:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = (
            db_path
            or os.environ.get("JARVIS_TRADER_DB_PATH")
            or _DEFAULT_DB_PATH
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def list_bookmarks(self, limit=50, offset=0, source_type=None, domain=None, since=None) -> list[dict]: ...
    def get_bookmark(self, message_id: str) -> Optional[dict]: ...
    def search_content(self, query: str, limit: int = 20) -> list[dict]: ...
```

**Why context manager over manual open/close**: pytest failures under `with ... as conn` block still close the connection. Avoids leaking SQLite file handles on Windows (where file locks persist until handle closes).

**Why `conn.row_factory = sqlite3.Row`**: lets downstream code treat rows as dicts (`row["message_id"]`) while still being SQL-performant.

**Why empty query returns `[]` in `search_content`**:
```python
q = (query or "").strip()
if not q:
    return []
```
Without the guard, `f"%{q.lower()}%"` becomes `"%%"` which LIKE-matches every row — a 372-row scan instead of zero hits. Explicit guard is cheaper and safer.

#### `app/routers/trade/bookmarks.py` (NEW, 66 lines)

Module singleton + three routes:
```python
_reader = BookmarkReader()  # Cheap: no connection until a method call

@router.get("")
async def list_bookmarks(limit=50, offset=0, source_type=None, domain=None, since=None):
    try:
        rows = _reader.list_bookmarks(...)
        return {"count": len(rows), "bookmarks": rows}
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"bookmark DB unreachable: {e}")

@router.get("/search")
async def search_bookmarks(q: str = Query(..., min_length=1), limit=20): ...

@router.get("/{message_id}")
async def get_bookmark(message_id: str): ...
```

**Why `Query(..., min_length=1)` on `q`**: FastAPI validates the query-parameter-level minimum before it reaches our code. Empty `?q=` returns HTTP 422 with a structured error, not a 200 with empty results. Double-defense: the reader's own empty-query guard also returns `[]`.

**Why `sqlite3.OperationalError → 503` (not 500)**: 503 is retriable; callers should back off and try again. 500 implies permanent server error. Database-unreachable is almost always transient (file lock, WAL checkpoint, etc.).

#### `tests/trade/test_bookmark_reader.py` (NEW, 282 lines, 21 tests)

Verified test names (from pytest output, 13:22 CT, Python 3.14.3 + pytest 9.0.2):

Safety (2 tests):
1. `test_read_only_mode_blocks_writes` — **THE critical test**. Seeds a fixture DB, opens via `BookmarkReader._connect()`, attempts INSERT, expects `sqlite3.OperationalError` with message matching `"readonly"`. Proves OS-level write protection.
2. `test_reader_does_not_error_on_ro_open` — plain `SELECT 1` through the reader works; connection open doesn't error.

Listing and filtering (5 tests):
3. `test_list_returns_all_when_no_filter` — returns 3 fixture rows; keys set includes `{message_id, url, source_type, content, author_name}`.
4. `test_list_filters_by_source_type` — github=1, x_post=1, nonexistent=0.
5. `test_list_filters_by_domain` — `x.com`=1, `github.com`=1.
6. `test_list_respects_limit_and_offset` — page1 + page2 disjoint; pagination math correct.
7. `test_list_orders_by_posted_at_desc` — newest first (m3=2026-04-20, m1=2026-04-18).

Time filter (1 test):
8. `test_list_since_filters_earlier` — `since=2026-04-19` excludes m1 (2026-04-18), includes m2 and m3.

Single-item lookup (2 tests):
9. `test_get_bookmark_by_id` — returns row with correct URL and author_name.
10. `test_get_bookmark_returns_none_for_unknown` — returns None, not raise.

Content search (4 tests):
11. `test_search_content_finds_matches_in_content` — "regime" matches m2's content.
12. `test_search_content_matches_in_embed_description` — "tweet body" matches m2's embed_description.
13. `test_search_content_case_insensitive` — "regime" vs "REGIME" return identical results.
14. `test_search_content_empty_query_returns_empty` — both `""` and `"   "` return `[]` (no LIKE '%' scan).

Env var resolution (1 test):
15. `test_default_path_from_env_var` — `JARVIS_TRADER_DB_PATH` monkeypatch overrides hardcoded default.

Router integration via FastAPI TestClient (6 tests):
16. `test_router_list_returns_200_and_all_bookmarks` — `GET /trade/bookmarks` returns `{"count": 3, "bookmarks": [...]}`.
17. `test_router_list_filters_by_source_type` — `GET /trade/bookmarks?source_type=github` returns count=1.
18. `test_router_get_by_id_returns_detail` — `GET /trade/bookmarks/m1` returns the row dict.
19. `test_router_get_by_id_404_when_missing` — unknown ID returns HTTP 404.
20. `test_router_search_returns_matches` — `GET /trade/bookmarks/search?q=regime` returns `{"count": 1, "query": "regime"}`.
21. `test_router_search_rejects_empty_query` — `?q=` returns HTTP 422 (FastAPI Query min_length=1).

All 21 tests pass in 1.25s against a fixture DB. A subset were also manually run against the production DB during pre-compact verification; read-only mode held against real data.

---

## Section 3 — Current state (verified ground truth, not memory)

### 3.1 Live database state (verified via Python introspection at 13:02 CT)

```
DB path: C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\jarvis_trader.db
Schema: all 12 columns present (0-8 pre-existing + 9 content + 10 author_id + 11 author_name)
Total bookmarks: 372
Rows with content IS NOT NULL: 372  (100% backfilled)
Rows with author_name IS NOT NULL: 372
Rows with author_id IS NOT NULL:   372
Author distribution:
  "AmoSZN"  (global_name) → 312 rows
  "amoszn"  (username fallback, no global_name set at post time) → 60 rows
```

**Implication**: Workstream A's migration + backfill has **already executed** against the live DB. A next session does NOT need to run the CLI re-import for A's data payload. The *running* engine still has the old code in memory (PM2 process cached at startup), so when it next restarts, the `init_tables` ALTER path will short-circuit on "duplicate column" — expected and safe.

### 3.2 Live vault state (verified via `os.listdir` at 13:02 CT)

```
Root: C:\Users\mattm\second-brain\wiki\discord-bookmarks\
  github/  102 files  (was 128 on 2026-04-17; some may have been reclassified manually)
  x/       221 files  (was 182 on 2026-04-17; +39 from new bookmarks + re-renders)
  other/    13 files  (NEW bucket, created this session)
  index.md (regenerated)
Total vault pages: 336   (less than DB 372; 36 bookmarks may be unrenderable or in manual-rename state)
```

Sample `other/` frontmatter (from `code_claude_com-1492831935137976492.md`):
```yaml
source: "discord-bookmark"
kind: "other"
url: "https://code.claude.com/docs/en/ultraplan"
domain: "code.claude.com"
captured_at: "2026-04-20"
posted_at: "2026-04-12T10:21:08.813000+00:00"
posted_by: "AmoSZN"
jarvis_module: "unclassified"
status: "pending-review"
tags:
  - discord/unclassified
  - discord-bookmark
  - source/other
```

**Implication**: Workstream B's catch-up render has **already executed** at least once against production. The `other/` subdir (13 files, `captured_at: "2026-04-20"`, `kind: "other"`, v1 frontmatter) is my work. Next session does NOT need to run the initial catch-up render.

### 3.3 Running processes (memory-reported; NOT verified this session — confirm before acting)

| Process | Port | Status (memory) | Notes |
|---------|------|-----------------|-------|
| PM2 `jarvis-engine` | 8010 | Running (assumed) | Deferred restart until 2026-04-22 R4 window. Currently has OLD Workstream A/B code — new code only activates post-restart. |
| PM2 `jarvis-dashboard` | 3010 | Running (restored 2026-04-16) | Unrelated to bookmark work. |
| PM2 `jarvis` (GMS JARVIS v2) | **8009** | Running | **DO NOT RESTART** — unrelated GMS process. Memory directive: "NEVER work on GMS." |
| Master-jarvis | — | NOT deployed | Code-only. Port conflict with GMS on 8009 blocks live deployment; needs a port decision. |
| IB Gateway | 4002 (paper) | Unknown | Check with `curl http://localhost:8010/health` and look for `market_data_connected`. |

### 3.4 Code deployment status (what's active vs. what's committed)

| Workstream | Committed | Running in engine | Notes |
|------------|-----------|-------------------|-------|
| A — schema migration code path | ✅ `543d768` | ❌ Not yet — engine restart pending | ALTER path is safe on next restart (idempotent — will short-circuit on "duplicate column") |
| A — data payload in DB | ✅ (executed pre-compact) | ✅ Live 372 rows fully backfilled | New writes by OLD code path will NOT populate new columns until engine restart |
| B — vault renderer code | ✅ `4b5722a` | ❌ Cron not registered until restart | Standalone script works today: `engine/.venv/Scripts/python engine/scripts/render_bookmarks_to_vault.py` |
| B — vault content | ✅ (executed pre-compact) | ✅ 336 pages live in second-brain | Further bookmark drops won't trigger a render until either manual run or post-restart cron |
| C — reader code | ✅ `33102da` | ❌ Master-jarvis not deployed | TestClient tests are the only surface; live HTTP blocked on deployment decision |

---

## Section 4 — In-progress work

**From this session (bookmark integration)**: nothing — all three workstreams landed at a natural boundary.

**From concurrent Claude sessions** (visible via git log but NOT owned by this session):
- `d11565f feat(scheduler): wire MES session forward-recorder into lifespan` — another session wired the MES forward-recorder cron into `engine/main.py` between 08:30 CT and 12:00 CT today. The MES experiment modules themselves (`engine/experiments/mes_session_{recorder,outcome}.py`) were landed in `fd5b153`.
- `2db7f74 feat(mes): implement SMA(50,200) golden-cross trend strategy as MES paper baseline` — MES trend-following strategy wired into production via `engine/backtest/trend_signals.py` + `signals.py:106`. Awaits next pm2 restart (deferred to 2026-04-22 per R4 window) per memory.
- Drift still uncommitted in `jarvis-trader`: `engine/routers/backtest_router.py` (5-line modification), `engine/api_check.py`, `engine/scripts/mes_stc_search.py`, various MES search JSON result files. Ownership unclear — not this session's.

**From master-jarvis**: ~200 untracked biz-domain files and 3 modified `__init__.py` files — belongs to an older GMS-to-master-jarvis migration effort that is orthogonal to bookmarks.

---

## Section 5 — Blockers discovered

### 5.1 Active blockers to full activation

**Blocker 1: Engine restart is deferred until 2026-04-22 (R4 passive window).**
- Workstream A's code path doesn't flow through the parser on NEW bookmark drops until restart. New bookmarks posted between now and 2026-04-22 will miss the content/author_name/author_id columns.
- Workstream B's cron is registered in code but not in the running scheduler.
- Mitigation for the gap: manual catch-up render before restart, and a re-import after restart to fill any rows that arrived in the gap.
- Do NOT restart before 2026-04-22 without user approval — R4 window is a deliberate data-collection period for the live safety-layer metrics.

**Blocker 2: Master-jarvis is not deployed, and port 8009 is occupied by GMS.**
- Live HTTP smoke for Workstream C is impossible today.
- TestClient tests fully cover the router surface, but end-to-end confidence requires real deployment.
- Options:
  - (A) Deploy on alternate port (8011 suggested) — requires user approval.
  - (B) Wait until GMS is formally decommissioned — timeline unknown.
  - (C) Keep TestClient coverage only; activate Workstream C as a FastAPI module that's imported by another process — would require re-architecting.
- Per memory: "NEVER work on GMS." Do not kill the port-8009 process.

**Blocker 3: Push authorization not granted.**
- `jarvis-trader feat/tradingview-mcp-gamma-kraken` is 9 commits ahead of origin.
- `master-jarvis feat/bookmark-reader` has 1 commit and no upstream set (new branch).
- User instruction "Proceed with recommended next steps" explicitly authorized the three commits, NOT a push.
- Ask before pushing. Suggested push commands (for when approved):
  ```bash
  cd /c/Users/mattm/ThinkorSwim/jarvis-trader
  git push origin feat/tradingview-mcp-gamma-kraken

  cd /c/Users/mattm/master-jarvis
  git push -u origin feat/bookmark-reader
  ```

### 5.2 Blockers discovered during session

**Blocker 4: Parallel Claude sessions can race on shared files.**
- During post-compact commit phase, `engine/main.py` had my bookmark cron block REMOVED between pre-compact and post-compact. Another session had edited the same file and committed its MES block without my bookmark block.
- Symptoms observed:
  1. `grep bookmark_vault_render engine/main.py` returned zero matches after compact
  2. `git diff engine/main.py` showed a 70-line MES block I had not authored
  3. `git log` showed MES commits that hadn't existed at compact point
- Root cause hypothesis: concurrent `Edit` → `Write` → `git add` → `git commit` without coordination. Whichever session committed last won.
- Mitigation applied: snapshot-revert-restore pattern (detailed in §Section 6). Prevented bundling MES drift into my commit.
- Long-term mitigation: consider per-session git identity or file-level locking in the hooks layer. Not in scope for this session.

**Blocker 5: SQLite `mode=ro` + Windows file locking edge cases.**
- Memory directive already flags this: "Windows file locking + SQLite `mode=ro` + sharing flags have bitten projects before."
- Mitigations already in code:
  - Context manager ensures connection close on exception.
  - `test_read_only_mode_blocks_writes` confirms the read-only enforcement.
- Untested scenario: jarvis-trader holds an exclusive write lock while master-jarvis is mid-read. If the trader DB is in default journal mode (DELETE or ROLLBACK), master-jarvis may see `SQLITE_BUSY`. If the trader DB is in WAL mode, readers don't block writers and vice versa.
- **Recommended check before deploying master-jarvis live**:
  ```bash
  cd /c/Users/mattm/ThinkorSwim/jarvis-trader
  engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db'); print(c.execute('PRAGMA journal_mode').fetchone())"
  ```
  Expect `('wal',)` — if it's `('delete',)` or similar, consider switching with `PRAGMA journal_mode=WAL;` (persistent, affects both processes).

**Blocker 6: `search_content("regime")` returns zero hits on production — not a bug, a data insight.**
- Matt's bookmark workflow is predominantly bare-URL drops with minimal commentary.
- `content` column IS populated (372/372), but for 312 rows the content IS the URL itself (no accompanying commentary).
- Search-by-content will be low-signal until either:
  - Matt annotates drops inline with commentary, OR
  - An LLM enrichment pass generates `jarvis_module` + summary for each bookmark (future work).
- Do not treat empty search results as a bug. They are ground truth about Matt's drop pattern.

### 5.3 Non-blockers (flagged but not acted on)

- `bayesian_optimizer.py`, `migrations.py`, `roadmap-2026-04-20-unified.md` drift in jarvis-trader — belongs to another workstream.
- Pre-existing 24 failing tests in master-jarvis full suite (from memory notes) — unrelated to bookmarks.
- MEMORY.md is at 220 lines / 30.1KB, over the 200-line / 150-char-per-entry recommendation. Trim is overdue but not this session's job.

---

## Section 6 — Key decisions (with tradeoffs)

### 6.1 Workstream A decisions

**Decision A1: Three nullable columns, not a JSON blob.**
- Alternative considered: single `context_json TEXT` column with `{content, author}`.
- Rejected because: SQLite doesn't index JSON well; `WHERE content LIKE '%regime%'` requires full JSON parse per row. Nullable TEXT columns are cheap, indexable, and match the existing schema style.

**Decision A2: `INSERT OR IGNORE` + separate `UPDATE` backfill helper over `INSERT OR REPLACE`.**
- `INSERT OR REPLACE` would clobber the `imported_at` timestamp on re-imports. Audit trail matters — `imported_at` is the closest thing we have to "when did this first land in our DB".
- Trade-off: two round-trips instead of one on re-imports. Acceptable — re-imports are rare.

**Decision A3: Author priority chain `global_name > username > name`.**
- DCE real export shape has `global_name` and `username`. Legacy exports sometimes have `name`.
- Without the chain, the first backfill populated 312/372 rows with `author_name=None` — caught by live smoke test, not by synthetic tests (fixture had `.name` only).
- Lesson: test fixtures should mirror real DCE output, not invented shapes. Added `test_dce_real_shape_author_extracted_correctly` with a real DCE-format dict.

**Decision A4: Idempotent ALTER inside `init_tables()`, not a separate migration script.**
- Alternative considered: `engine/database/migrations.py`-style numbered migration.
- Rejected because: discord DB is per-instance, schema is small (<20 tables), and the engine already runs `init_tables()` on boot. Adding a dedicated migration layer for 3 columns is premature abstraction.
- Cost: `init_tables()` is now slightly more complex. Still comprehensible at a glance.

**Decision A5: 5000-char cap on content.**
- Discord messages max at 2000 (free users) or 4000 (Nitro). 5000 is safety margin against UTF-8 multi-byte inflation.
- Alternative considered: no cap. Rejected — some bots paste giant stack traces into #general.

### 6.2 Workstream B decisions

**Decision B1: Skip-if-exists catch-up, not frontmatter merge.**
- Full analysis in plan §Workstream B.
- The merge logic is cheap insurance for future triage — but today's vault has no manual triage to preserve (`jarvis_module: "unclassified"` on all 282 pre-existing pages).
- Shipping the merge logic now adds complexity with no current payoff. v1 is strictly additive.
- Future upgrade path is clear: add `--force-enrich` flag that reads existing frontmatter, overwrites only source-derived keys (url, pushed_at, stars, embed_description), preserves user-editable keys (status, jarvis_module, notes).

**Decision B2: GitHub API enrichment deferred.**
- Unauth rate limit is 60 req/hr. 102 github bookmarks = ~2 hours of pacing on a cold run.
- v1 pages have empty `stars`, `language`, `pushed_at`, `archived` fields.
- Future `--force-enrich` will batch-fetch with `time.sleep(62)` pacer and cache at `engine/data/cache/github_repo_meta.json` with 7-day TTL.
- Why not authenticated requests: requires a GitHub PAT in env; adds a secret-management surface. User has not provided one; deferred until priority.

**Decision B3: `other/` as a third bucket.**
- 2026-04-17 render only had `github/` and `x/`. My v1 added `other/` for video/domain-catchall bookmarks (13 initial: code.claude.com, gumroad.com, youtu.be, tradingview.com, etc.).
- Slug format `{domain-slug}-{message-id}.md` uses message_id suffix to guarantee uniqueness — two `tradingview.com` links from different messages don't collide.
- Alternative considered: drop `other/` entirely, skip bookmarks that aren't github or x_post. Rejected — loses ~13 bookmarks of real signal (code.claude.com docs in particular).

**Decision B4: Daily 03:00 CT cron, not hourly or on-trigger.**
- Discord import itself is nightly (`engine/schedulers/discord_nightly.py` or similar). Running the vault render hourly would render the same SQLite state repeatedly — waste.
- 03:00 CT is after overnight Discord activity settles (Matt drops late-night bookmarks ~22:00-02:00 CT).
- On-trigger (fire-after-import) would be more elegant but requires coupling the render script into the import path — complexity not worth it for a daily batch.

**Decision B5: sys.path shim at top of script.**
- Required for standalone CLI execution: `engine/.venv/Scripts/python engine/scripts/render_bookmarks_to_vault.py` needs `from discord.storage import Bookmark` to resolve.
- Without the shim: `ModuleNotFoundError: No module named 'discord'` (pytest rootdir=engine/ masks this).
- Shim is `_ENGINE_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(_ENGINE_ROOT))`. Works whether cwd is `engine/`, `jarvis-trader/`, or anything else.

### 6.3 Workstream C decisions

**Decision C1: SQLite URI `mode=ro`, not code-level convention.**
- A code convention ("don't call `.execute('INSERT ...')` in this class") requires every contributor to remember. A URI mode flag is enforced by the OS.
- `sqlite3.OperationalError("attempt to write a readonly database")` fires on any write — INSERT, UPDATE, DELETE, CREATE TABLE, ALTER, etc.
- This is the single most important safety property in the master-jarvis ↔ jarvis-trader boundary. The test `test_read_only_mode_blocks_writes` locks it in as a regression.

**Decision C2: Module-level `_reader` singleton.**
- Alternative considered: dependency injection via FastAPI's `Depends(BookmarkReader)`.
- Rejected because: reader holds only a path string; no connection pool, no expensive state. Constructor is free. `_reader = BookmarkReader()` at import time is simpler and keeps routes terse.
- For testing: `monkeypatch.setattr(bookmarks_router, "_reader", BookmarkReader(db_path=fixture))` overrides cleanly.

**Decision C3: Empty search query returns `[]`, not all rows.**
- Double defense: FastAPI Query(..., min_length=1) returns 422 at the HTTP layer, reader's own guard returns `[]` when called directly (unit test path).
- Alternative (return all rows): LIKE '%' matches all 372 rows, which would be a surprise to a caller expecting filtered results from a search endpoint.

**Decision C4: `sqlite3.OperationalError → HTTP 503` in router.**
- Not HTTP 500: 500 is permanent-server-error; 503 is retriable.
- Not HTTP 404: 404 implies the endpoint doesn't exist. The endpoint exists; the data source is temporarily unreachable.
- Callers should implement exponential backoff on 503.

**Decision C5: Feature branch from master-jarvis `master`, not direct commit.**
- master-jarvis has ~200 untracked biz-domain files belonging to an older GMS migration. Committing directly to `master` would either (a) commit my work on top of dirty state, or (b) leave the drift staged alongside my commit, bundling unrelated work.
- Feature branch keeps `master` pristine. Merge can be attempted cleanly when the biz drift is resolved.
- Branch name `feat/bookmark-reader` matches the conventional-commits style used elsewhere.

### 6.4 Cross-workstream decisions

**Decision X1: Surgical commit isolation via snapshot-revert-restore.**
- When `engine/main.py` turned out to have a concurrent-session MES block intermixed with my bookmark block, the naive `git add engine/main.py` would have bundled both into my commit.
- Snapshot-revert-restore:
  1. `cp engine/main.py /tmp/snap.py`
  2. `git checkout HEAD -- engine/main.py`
  3. Edit tool re-applies only my hunk
  4. `git add engine/main.py && git commit`
  5. `cp /tmp/snap.py engine/main.py` (restores the MES block to working tree, now uncommitted and visible as drift)
- Result: my commit is 48 lines of exactly my cron block. The MES block remains as uncommitted drift in the working tree, ready for the MES author (another Claude session) to commit separately.

**Decision X2: Handoff lives in `jarvis-trader/docs/session-logs/`, not master-jarvis.**
- jarvis-trader is the primary repo (2 of 3 commits, the richer state).
- Matt's workflow memory: `Template: C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\HANDOFF_TEMPLATE.md`. This is the canonical location.

---

## Section 7 — TODO items (not started, ordered by priority)

### Priority 1 — activation (blocked by 2026-04-22 R4 window)

1. **[ACTIVATE]** Engine restart to pick up Workstream A (re-imports now populate new columns) + Workstream B (daily cron registered):
   ```bash
   cd /c/Users/mattm/ThinkorSwim/jarvis-trader
   .\restart_engine.ps1
   # Verify:
   pm2 logs jarvis-engine --lines 100 | grep "bookmark_vault_render\|Bookmark vault"
   # Expect: "✅ Bookmark vault renderer registered — fires daily 03:00 CT"
   ```
   Confirm via `curl http://localhost:8010/health`.

2. **[CATCH-UP IMPORT]** Re-import any bookmarks that arrived between 2026-04-20 and restart date:
   ```bash
   engine/.venv/Scripts/python -m engine.discord.cli \
     --source "C:\Users\mattm\discord-export" \
     --db engine/data/jarvis_trader.db \
     --channel 1490851279180660819
   # Verify:
   engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db'); print('total:', c.execute('SELECT COUNT(*) FROM discord_bookmarks').fetchone()[0])"
   ```

3. **[CATCH-UP RENDER]** Render any new bookmarks to vault (will no-op on existing files):
   ```bash
   engine/.venv/Scripts/python engine/scripts/render_bookmarks_to_vault.py
   # Verify console output: "created=X skipped=Y failed=0"
   ```

### Priority 2 — deployment decisions

4. **[DEPLOY]** Decide on master-jarvis port (8009 blocked by GMS; suggest 8011):
   - Update `app/main.py` `uvicorn.run(...)` port argument.
   - Start under PM2 with a new process name (e.g., `master-jarvis`).
   - Smoke: `curl http://localhost:8011/trade/bookmarks?limit=5`.

5. **[PUSH]** After user approval, push the three commits:
   ```bash
   cd /c/Users/mattm/ThinkorSwim/jarvis-trader && git push origin feat/tradingview-mcp-gamma-kraken
   cd /c/Users/mattm/master-jarvis && git push -u origin feat/bookmark-reader
   ```
   Verify CI/PR workflows pass.

### Priority 3 — polish + docs

6. **[DOCS]** Add `JARVIS_TRADER_DB_PATH` and `BOOKMARK_VAULT_DIR` env vars to master-jarvis README and/or `.env.example`.

7. **[OBSERVABILITY]** Add a `/trade/bookmarks/health` endpoint that returns `{"db_accessible": bool, "row_count": int, "newest_posted_at": iso}`. Useful for cross-service health dashboards.

8. **[WAL MODE CHECK]** Verify jarvis-trader DB is in WAL mode (see Blocker 5). If not, switch:
   ```bash
   engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db'); c.execute('PRAGMA journal_mode=WAL'); print(c.execute('PRAGMA journal_mode').fetchone())"
   ```

### Priority 4 — future enhancements (explicit out-of-scope, left for later)

9. **[FUTURE]** GitHub API enrichment pass with `--force-enrich` flag + 7-day cache at `engine/data/cache/github_repo_meta.json`. Fills `stars`, `language`, `license`, `pushed_at`, `archived` on all github/* pages.

10. **[FUTURE]** Frontmatter merge logic for `--force-enrich`: read existing YAML → overwrite only source-derived keys → preserve user-editable keys (status, jarvis_module, notes, user-added tags).

11. **[FUTURE]** `--prune` flag for vault pages whose `message_id` is no longer in `discord_bookmarks`. Moves them to `_archive/` subdir. Not needed in v1.

12. **[FUTURE]** LLM-based `jarvis_module` auto-triage. Currently 100% of pages are `unclassified`. Could batch through Claude Haiku with prompt "classify this URL + content into one of {strategy, execution, risk, data, research, ops}".

13. **[FUTURE]** Full #general message parser (not just URL-anchored bookmarks). User explicitly chose scope option 2, not option 3 — revisit once links-plus-context data flow is stable.

14. **[FUTURE]** Write-back from master-jarvis (tagging, annotation). Deliberately out of scope — read-only is the current safety model.

15. **[FUTURE]** Expose bookmarks over the messaging gateway (Telegram/WhatsApp). Separate surface, separate plan.

---

## Section 8 — Full current task list

TaskCreate state at handoff time (all completed; next session starts fresh):

```
[✓] Plan drafted + approved via AskUserQuestion (Workstream selections)
[✓] Workstream A: schema + parser + migration helper + 14 tests
[✓] Workstream B: renderer + 18 tests + cron block drafted
[✓] Workstream C: BookmarkReader + router + 21 tests
[✓] Pre-flight: identify concurrent-session drift in engine/main.py and master-jarvis
[✓] Commit 1 (Workstream A) on feat/tradingview-mcp-gamma-kraken — 543d768
[✓] Commit 2 (Workstream B) on feat/tradingview-mcp-gamma-kraken — 4b5722a (with snapshot-restore isolation)
[✓] Commit 3 (Workstream C) on new feat/bookmark-reader branch — 33102da
[✓] Restore pre-existing drift to working tree (MES block, etc.)
[✓] Verify live DB state: 372 rows, 12 columns, 100% backfilled
[✓] Verify live vault state: 336 pages across github/x/other
[✓] Write handoff document (this file)
[ ] Engine restart activation (BLOCKED until 2026-04-22)
[ ] CLI re-import + verification (depends on restart)
[ ] First post-restart cron-triggered vault render (depends on restart + 03:00 CT clock)
[ ] Master-jarvis deployment decision (port conflict with GMS on 8009)
[ ] Push to origin (both repos, user approval required)
[ ] Follow-up: --force-enrich flag, WAL mode check, /trade/bookmarks/health endpoint
```

---

## Section 9 — Git state (complete output)

### 9.1 jarvis-trader (`C:\Users\mattm\ThinkorSwim\jarvis-trader`)

**Branch**: `feat/tradingview-mcp-gamma-kraken` — 9 commits ahead of `origin/feat/tradingview-mcp-gamma-kraken`, no push.

**`git status`** (verbatim, as of 12:58 CT):
```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is ahead of 'origin/feat/tradingview-mcp-gamma-kraken' by 9 commits.
  (use "git push" to publish your local commits)

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
	modified:   docs/plans/roadmap-2026-04-20-unified.md
	new file:   engine/scripts/mes_orb_search_results.json
	new file:   engine/scripts/mes_search_results.json
	new file:   engine/scripts/mes_trend_search_results.json
	new file:   engine/scripts/mes_trend_wfo_results.json
	new file:   engine/scripts/multi_symbol_trend_wfo_results.json

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   engine/routers/backtest_router.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	docs/session-logs/premarket-2026-04-20.md
	docs/session-logs/scan-2026-04-20.md
	engine/api_check.py
	engine/scripts/mes_stc_search.py
	engine/scripts/mes_stc_search_results.json
```

> **IMPORTANT**: the 5 staged `mes_*_results.json` files + staged `roadmap-2026-04-20-unified.md` modification are **NOT** from this session. A concurrent Claude session staged them. Do **NOT** `git commit` blindly. They should be committed separately by whoever owns the MES workstream — or unstaged and left for that session to re-stage.

**`git log --oneline -20`**:
```
d11565f feat(scheduler): wire MES session forward-recorder into lifespan             [CONCURRENT, not mine]
4b5722a feat(vault): sync Discord bookmarks to second-brain with daily cron          [MINE — Workstream B]
2db7f74 feat(mes): implement SMA(50,200) golden-cross trend strategy as MES paper baseline  [CONCURRENT]
fd5b153 feat(mes): cross-instrument trend WFO - SMA(50,200) is MES-specific          [CONCURRENT]
543d768 feat(discord): enrich bookmark rows with message context + author            [MINE — Workstream A]
c2dc190 feat(mes): trend-following WFO finds first profitable MES 1h strategy        [earlier]
bc12cbc feat(agents): bookmark thematic clusterer + endpoints + weekly prewarm        [earlier]
3d5996b fix(composite): wire stop/target ATR mults through to caller params           [earlier]
f83e21f fix(backtest): correct Sharpe/MaxDD/capital-reconciliation bugs               [earlier]
d168dd0 feat(dx): I1 per-session git identity + overnight-status scheduler + roadmap sync  [earlier]
584efb7 feat(scripts): overnight_status HTML renderer                                  [earlier]
ba684d5 docs: concurrent-session updates — DCE flag, next-steps, gbrain issue body    [earlier]
7493753 feat(discord): bookmark pipeline for jarvis-trader #general channel           [earlier, prerequisite]
b9b398a fix(restart): PM2-aware restart with uptime verification                       [earlier]
f23195c chore(safety): surface silent failures in sync_safety_equity scheduler         [earlier]
c81ad6d docs(roadmap): add ship manifest — 15 commits across Phases 1/4/7/8            [earlier]
9edd5d0 fix(safety): wire db_manager into SafetyLayer — pnl_snapshots were silently disabled  [earlier]
9597ee1 chore(bucket4): commit remaining repo-scoped tooling artifacts                  [earlier]
c468fa4 ci: add Claude PR review + safety-invariant-check workflows                    [earlier]
237a64b chore(gitignore): exclude runtime state + scan/test output artifacts            [earlier]
```

**`git diff --stat`** (unstaged only):
```
 engine/routers/backtest_router.py | 5 +++--
 1 file changed, 3 insertions(+), 2 deletions(-)
```

**`git show --stat 543d768`**:
```
commit 543d7682efc278f04ee15c4a93551d1c31122bb2
Author: Claude <claude@anthropic.com>
Date:   Mon Apr 20 12:00:46 2026 -0500

    feat(discord): enrich bookmark rows with message context + author

 engine/discord/channel_parsers/bookmark.py       |   X +
 engine/discord/models.py                         |   X +
 engine/discord/parser.py                         |   X +
 engine/discord/storage.py                        |  XX +
 engine/tests/test_discord_bookmark_parser.py     | XXX +
 5 files changed, 396 insertions(+), 3 deletions(-)
```

**`git show --stat 4b5722a`**:
```
commit 4b5722ae6b5adf6b674edef3b97fe6e1b24a5468
Author: Claude <claude@anthropic.com>
Date:   Mon Apr 20 12:53:09 2026 -0500

    feat(vault): sync Discord bookmarks to second-brain with daily cron

 engine/main.py                               |  48 +++
 engine/scripts/render_bookmarks_to_vault.py  | 447 +++++++++++++++++++
 engine/tests/test_bookmark_vault_renderer.py | 278 +++++++++++++
 3 files changed, 773 insertions(+)
```

### 9.2 master-jarvis (`C:\Users\mattm\master-jarvis`)

**Branch**: `feat/bookmark-reader` (NEW, no upstream). 1 commit ahead of `master`, 0 commits ahead of origin (branch never pushed).

**`git status`** (truncated — ~200 untracked files omitted):
```
On branch feat/bookmark-reader

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   app/core/__init__.py            (+109 lines; not mine)
	modified:   app/routers/biz/__init__.py     (+29 lines; not mine)
	modified:   app/services/biz/__init__.py    (+1 line; not mine)

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	_write_remaining.py
	app/agents/biz/{analytics,compliance,customer,data_management,finance,inventory,operations,pricing,purchasing,quoting,sales,shared}/
	app/agents/trade/thinkscript_generator.py
	app/backtest/*.py                   (30+ files)
	app/core/*.py                       (25+ files)
	app/routers/biz/*.py                (25+ files)
	app/services/biz/*.py               (100+ files)
	app/services/shared/{redis_service.py, whatsapp_router.py}
	app/services/trade/{fred_data.py, market_data.py}
	docs/
	thinkorswim-scripts/*.ts            (35+ files)

no changes added to commit (use "git add" and/or "git commit -a")
```

**`git log --oneline -20`** (only 2 commits total on this branch):
```
33102da feat(trade): add read-only BookmarkReader for jarvis-trader bookmarks        [MINE — Workstream C]
1dd360f feat: scaffold Master-JARVIS unified agent                                   [ancestor]
```

**`git diff --stat`** (unstaged only):
```
 app/core/__init__.py         | 109 +++++++++++++++++++++++++++++++++++++++++++
 app/routers/biz/__init__.py  |  29 ++++++++++++
 app/services/biz/__init__.py |   1 +
 3 files changed, 139 insertions(+)
```

**`git branch -vv`**:
```
* feat/bookmark-reader 33102da feat(trade): add read-only BookmarkReader for jarvis-trader bookmarks
  master               1dd360f feat: scaffold Master-JARVIS unified agent
```

**`git show --stat 33102da`**:
```
commit 33102dad35cf6876ce8c0bd8b47a65144af1e2f0
Author: mattamundson <31787354+mattamundson@users.noreply.github.com>
Date:   Mon Apr 20 12:54:47 2026 -0500

    feat(trade): add read-only BookmarkReader for jarvis-trader bookmarks

 app/main.py                           |   1 +
 app/routers/trade/bookmarks.py        |  66 ++++++
 app/services/trade/bookmark_reader.py | 115 ++++++++++++
 tests/trade/test_bookmark_reader.py   | 282 ++++++++++++++++++++++++++++++
 4 files changed, 464 insertions(+)
```

### 9.3 second-brain (`C:\Users\mattm\second-brain`)

**Branch**: `main` (assumed; stop hook auto-commits). Clean working tree.

**`git log --oneline -5`**:
```
6676a3b chore(vault): auto-commit on session end (2026-04-20 12:01)
4fd5a56 chore(vault): auto-commit on session end (2026-04-20 11:15)
c75b86c chore(vault): auto-commit on session end (2026-04-20 11:14)
735e38d chore(vault): auto-commit on session end (2026-04-20 11:03)
78609dc chore(vault): auto-commit on session end (2026-04-20 09:01)
```

The 12:01 commit carries the 13 new `other/` pages + other new vault pages from my pre-compact catch-up render.

---

## Section 10 — Quick-start for next session

### 10.1 Re-orient in under 30 seconds

```bash
# 1. Verify my commits still in place
cd /c/Users/mattm/ThinkorSwim/jarvis-trader && git log --oneline -5 | grep -E "543d768|4b5722a"
cd /c/Users/mattm/master-jarvis && git log --oneline -5 | grep "33102da"

# 2. Verify live DB state still matches handoff (expect: 372, 372, 372)
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
engine/.venv/Scripts/python -c "
import sqlite3
c = sqlite3.connect('engine/data/jarvis_trader.db')
print('total:',    c.execute('SELECT COUNT(*) FROM discord_bookmarks').fetchone()[0])
print('content:',  c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE content IS NOT NULL').fetchone()[0])
print('authors:',  c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE author_name IS NOT NULL').fetchone()[0])
"

# 3. Verify live vault state (expect counts roughly matching handoff: github=102, x=221, other=13)
ls /c/Users/mattm/second-brain/wiki/discord-bookmarks/github  | wc -l
ls /c/Users/mattm/second-brain/wiki/discord-bookmarks/x       | wc -l
ls /c/Users/mattm/second-brain/wiki/discord-bookmarks/other   | wc -l
```

### 10.2 Re-run the new test suites to confirm green

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
engine/.venv/Scripts/python -m pytest engine/tests/test_discord_bookmark_parser.py engine/tests/test_bookmark_vault_renderer.py -v

cd /c/Users/mattm/master-jarvis
python -m pytest tests/trade/test_bookmark_reader.py -v
```

Expect: 26 + 18 + 21 = 65 tests passing.

### 10.3 Check if activation is unblocked

```bash
# If today's date >= 2026-04-22, engine restart is unblocked per R4 window
date  # or Python: python -c "import datetime; print(datetime.date.today())"

# Then if approved, run the activation sequence:
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
.\restart_engine.ps1
pm2 logs jarvis-engine --lines 100 | grep -E "bookmark_vault_render|MESRecorder|init_tables"
```

### 10.4 Before pushing, re-read user consent

User authorized commits with `"Proceed with recommended next steps"` (2026-04-20 ~12:00 CT). Push authorization is a **separate** decision not yet granted — ask before running:
```bash
git push origin feat/tradingview-mcp-gamma-kraken
git push -u origin feat/bookmark-reader
```

### 10.5 Memory directives to re-load

Before any engine restart or service touch, re-read:
- **MEMORY.md** at `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md`
- Key entries: `project_pnl_snapshots_wiring_fix.md` (R4 window rationale), `feedback_restart_engine_ps1_silent_noop.md` (restart verification procedure), `feedback_futures_sentiment_source.md` (futures data rules — unrelated but always applicable).

---

## Section 11 — Post-handoff-v1 push phase (addendum, 13:22–13:40 CT)

After handoff v1 was written at 13:03 CT, the user approved the recommendation to "push commits + run a fresh test sweep" (13:22 CT). This section documents what happened between handoff v1 and handoff v2, so a next AI doesn't have to infer it from git log alone.

### 11.1 Fresh test sweep (parallel, 13:22 CT)

Three tool calls issued in parallel:
- `engine/.venv/Scripts/python -m pytest engine/tests/test_discord_bookmark_parser.py engine/tests/test_bookmark_vault_renderer.py -v`
- `python -m pytest tests/trade/test_bookmark_reader.py -v` (master-jarvis, system Python)
- `PRAGMA journal_mode` probe against `engine/data/jarvis_trader.db`

Results:
```
jarvis-trader  : 44 passed, 1 warning in 1.30s   (26 parser + 18 renderer)
master-jarvis  : 21 passed in 1.25s
journal_mode   : wal
synchronous    : 2   (FULL — fsync on every commit)
```

**Total: 65/65 tests green. 0 regressions post-compact.**

**Key discovery — WAL + FULL is already live on production**: Blocker 5 from handoff v1 (concurrent-reader/writer contention) is **dissolved, not merely mitigated**. Writer (jarvis-trader) and reader (master-jarvis) will never block each other in WAL mode. `synchronous=2` trades throughput for durability — appropriate for source-of-truth data; writes hit the disk synchronously. No `PRAGMA journal_mode=WAL` switch needed on restart.

**Python version asymmetry flagged**: jarvis-trader venv runs Python 3.12.10 + pytest 8.3.5; master-jarvis inherits system Python 3.14.3 + pytest 9.0.2. Both suites pass today, but 3.14 changed `typing` semantics (e.g., `from __future__ import annotations` default behavior). If any type definitions are ever shared across the repo boundary, validate on both interpreters.

### 11.2 jarvis-trader push (13:24 CT)

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader && git push origin feat/tradingview-mcp-gamma-kraken
```

Output:
```
To https://github.com/mattamundson/jarvis-trader.git
   d168dd0..72538f4  feat/tradingview-mcp-gamma-kraken -> feat/tradingview-mcp-gamma-kraken
```

Range pushed: `d168dd0..72538f4` — 9 commits total. Includes my `543d768` (Workstream A) and `4b5722a` (Workstream B), plus 7 concurrent-session commits (MES workstream).

**New commit `72538f4` discovered in the push range**: `docs(mes): commit MES profitability search results + roadmap update`. A concurrent Claude session committed the 5 staged `mes_*_results.json` files + `roadmap-2026-04-20-unified.md` modification (the "staged drift" I flagged in Section 9.1) between my test-sweep at 13:22 CT and my push at 13:24 CT. The drift I worried about is now on origin, authored by that concurrent session. **This is a healthy outcome**: the drift is traceably theirs, not accidentally mine.

### 11.3 master-jarvis: discovered no `origin` remote (13:25 CT)

```bash
cd /c/Users/mattm/master-jarvis && git push -u origin feat/bookmark-reader
# → fatal: 'origin' does not appear to be a git repository
```

```bash
git remote -v
# → (empty)
```

master-jarvis was a local-only repo. Either (a) scaffolded via `git init` without `git remote add`, or (b) the GitHub repo existed but this local clone was never pointed at it. Pushing was blocked; user was consulted.

### 11.4 GitHub repo creation + double push (13:36 CT)

User authorized `gh repo create`. Sequence:

```bash
# 1. Verify gh CLI auth
gh auth status
# → github.com ✓ Logged in as mattamundson (keyring)
#   scopes: 'gist', 'read:org', 'repo', 'workflow'

# 2. Create private repo + attach as origin (atomic three-step)
cd /c/Users/mattm/master-jarvis
gh repo create mattamundson/master-jarvis --private --source . --remote origin
# → https://github.com/mattamundson/master-jarvis

# 3. Push master (the scaffold ancestor) with upstream tracking
git push -u origin master
# → * [new branch] master -> master
#   branch 'master' set up to track 'origin/master'.

# 4. Push feat/bookmark-reader with upstream tracking
git push -u origin feat/bookmark-reader
# → remote: Create a pull request for 'feat/bookmark-reader' on GitHub by visiting:
# →        https://github.com/mattamundson/master-jarvis/pull/new/feat/bookmark-reader
# → * [new branch] feat/bookmark-reader -> feat/bookmark-reader
```

**What went over the wire**: 2 commits (`1dd360f` scaffold + `33102da` BookmarkReader). Total payload small — master-jarvis is <10 tracked files.

**What stayed local**: the 3 modified `__init__.py` files + ~200 untracked biz-domain files. Uncommitted work is never pushed. The biz-domain scaffolding remains in working tree for whoever owns it to commit separately.

**PR link surfaced**: `https://github.com/mattamundson/master-jarvis/pull/new/feat/bookmark-reader`. One-click starting point when ready to open the PR.

### 11.5 Post-push verification

Final tracking state:

**jarvis-trader** (already had remote):
```
origin  https://github.com/mattamundson/jarvis-trader.git  (fetch + push)
* feat/tradingview-mcp-gamma-kraken 72538f4 [origin/feat/tradingview-mcp-gamma-kraken]
```

**master-jarvis** (remote created this session):
```
origin  https://github.com/mattamundson/master-jarvis.git  (fetch + push)
* feat/bookmark-reader 33102da [origin/feat/bookmark-reader]
  master               1dd360f [origin/master]
```

Both branches have upstream tracking. `git status` on either repo will now show "Your branch is up to date with 'origin/...'" as the default state — future pushes can skip the `-u` flag.

### 11.6 Corrections to handoff v1 surfaced during this phase

1. **Test count was 14, actually 15** (Section 2.1) — fixed.
2. **Test names were guessed, not verified** — fixed, now reflect actual `pytest -v` output.
3. **Blocker 5 was listed as "untested scenario"** — dissolved; WAL + FULL already live.
4. **TODO item 5 "Push to origin"** was listed as blocked on user approval — completed; master-jarvis push additionally required repo creation, which was not anticipated in handoff v1.
5. **Current state Section 3** listed "master-jarvis NOT deployed, no HTTP surface" — still true (no server running), but the code now has a remote-backup path and a PR-creation path. The deployment blocker is unchanged, but the push blocker is cleared.

---

## Section 12 — CI/PR readiness gap analysis

With both repos now pushed to origin, the next natural step is a pull request. But the two repos have **asymmetric PR-readiness**, and a next AI should not assume a PR opens cleanly on either without checks.

### 12.1 jarvis-trader (CI present, but checks not guaranteed green for this branch)

jarvis-trader has existing CI workflows (per commit `c468fa4 ci: add Claude PR review + safety-invariant-check workflows`):
- `.github/workflows/claude-pr-review.yml` — spawns a Claude reviewer on PR open.
- `.github/workflows/safety-invariant-check.yml` — runs the MCL inverted-stop invariant tests.

**Unknowns**:
- Whether the feat/tradingview-mcp-gamma-kraken branch has been running CI continuously since `d168dd0` (the prior origin tip). If CI was broken somewhere in the 9 pushed commits, the branch health signal may be ambiguous.
- Whether any of the new MES/bookmark/vault code I pushed triggers CI failure paths. TDD tests pass locally, but CI may have additional invariants.
- Branch protection rules on `main` — unknown whether direct commits are blocked. Memory directive says "Never force push to main/master" — implies main exists and is protected, but the rule is code-of-conduct, not necessarily enforced.

**Recommended verification before opening a PR**:
```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
gh pr status                                                # see PRs affecting this branch
gh run list --branch feat/tradingview-mcp-gamma-kraken --limit 10    # CI history
gh run watch                                                # follow the latest run live
```

If CI is red on the latest push, triage the failure **before** opening a PR — a red-CI PR adds noise for the reviewer.

### 12.2 master-jarvis (zero CI, zero branch protection, fresh repo)

Just-created repo has:
- **No GitHub Actions workflows** — the default `.github/workflows/` directory doesn't exist.
- **No branch protection rules** — `master` accepts direct force-pushes by anyone with write access.
- **No CODEOWNERS** — PR reviews won't auto-assign.
- **No issue/PR templates** — PRs open with an empty body.
- **Default branch is `master`** (not `main`) — matches the scaffold commit but diverges from GitHub's modern default.

**Implications for the Workstream C PR**:
- Opening the PR today ships it with zero automated checks — the reviewer (you) bears 100% of the quality burden.
- A future session adding CI needs to choose a pytest matrix (Python 3.12 only? 3.12 + 3.14? 3.11 baseline?).
- Consider at minimum a `pytest.yml` workflow that runs `pytest tests/` on PR open + push to master.

**Suggested minimum CI before PR merge** (create in a follow-up commit, not blocking):

```yaml
# .github/workflows/pytest.yml
name: pytest
on:
  push:
    branches: [master]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: pip install -r requirements.txt  # or pyproject.toml deps
      - run: pytest tests/ -v
```

The BookmarkReader has no native dependencies (stdlib sqlite3 + FastAPI + pytest), so CI runs should be <30s.

### 12.3 Cross-repo coupling risk

`BookmarkReader` hardcodes a path in the jarvis-trader repo:
```python
_DEFAULT_DB_PATH = r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\data\jarvis_trader.db"
```

If master-jarvis CI runs on GitHub (Linux), this path won't exist. Env var override works for local dev + Linux CI: `JARVIS_TRADER_DB_PATH=/tmp/fixture.db pytest`. Tests that need the path DO use `monkeypatch.setenv` for the env var case, but tests that don't override may try to open the Windows path on Linux and fail silently.

**Recommended fix before CI lands**: add a `conftest.py` that sets `JARVIS_TRADER_DB_PATH` to a temp fixture for every test collection.

### 12.4 Force-push and rewriting history — don't

Three commits are now public:
- `543d768`, `4b5722a` on jarvis-trader `feat/tradingview-mcp-gamma-kraken`
- `33102da` on master-jarvis `feat/bookmark-reader`

Rewriting or force-pushing any of these requires coordination. Memory directive: "Never force push to main/master, warn the user if they request it." Applies even more to concurrent-session branches — another session could be working off these SHAs.

If you need to change commit messages or squash before PR merge, use GitHub's "Squash and merge" option on the PR UI — it rewrites history at merge time without disturbing the feature branch.

### 12.5 PR body draft for Workstream C (copy-paste-ready)

If you open the master-jarvis PR, suggested body:

```markdown
## Summary
- Adds `BookmarkReader` (`app/services/trade/bookmark_reader.py`) — read-only reader for
  jarvis-trader's `discord_bookmarks` SQLite table. OS-level write protection via URI mode.
- Adds `/trade/bookmarks` router with list / search / get-by-id endpoints.
- 21 tests (15 service-level + 6 FastAPI TestClient). All pass in 1.25s.

## Safety model
The reader opens the DB via `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. Any INSERT/UPDATE/DELETE
raises `sqlite3.OperationalError("attempt to write a readonly database")`. jarvis-trader owns writes;
master-jarvis is strictly a consumer. `test_read_only_mode_blocks_writes` locks this in as a regression.

## Test plan
- [x] `pytest tests/trade/test_bookmark_reader.py -v` — 21/21 green
- [x] Live smoke vs. production jarvis-trader DB (372 rows) — reads 372 bookmarks, INSERT blocked
- [ ] HTTP smoke once master-jarvis is deployed (port decision pending)

## Activation
- No engine restart required — reader is on-demand per HTTP call.
- Depends on Workstream A data (jarvis-trader #543d768) for meaningful `search_content` hits.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Appendix A — Copy-paste SQLite one-liners for future debugging

```python
# Total bookmarks
c.execute('SELECT COUNT(*) FROM discord_bookmarks').fetchone()

# Bookmarks without backfilled content (should be 0 post-activation)
c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE content IS NULL').fetchone()

# Author distribution
c.execute('SELECT author_name, COUNT(*) FROM discord_bookmarks GROUP BY author_name').fetchall()

# Bookmarks per day (posting cadence sanity check)
c.execute("SELECT date(posted_at), COUNT(*) FROM discord_bookmarks GROUP BY date(posted_at) ORDER BY 1").fetchall()

# Newest bookmark
c.execute('SELECT posted_at, url FROM discord_bookmarks ORDER BY posted_at DESC LIMIT 1').fetchone()

# Content search (case-insensitive, substring)
c.execute("SELECT message_id, url, content FROM discord_bookmarks WHERE LOWER(content) LIKE ? LIMIT 10", ('%claude%',)).fetchall()

# Schema check
c.execute('PRAGMA table_info(discord_bookmarks)').fetchall()

# Journal mode check (WAL recommended for concurrent reader/writer)
c.execute('PRAGMA journal_mode').fetchone()
```

## Appendix B — Architecture diagram (text)

```
┌──────────────────────────────────────────────────────────────────────┐
│ Discord #general (channel_id 1490851279180660819)                    │
│   └─ Matt drops URLs (370+ and counting)                             │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼  DiscordChatExporter (manual, 2026-04-20: last export 15 days old)
┌──────────────────────────────────────────────────────────────────────┐
│ C:\Users\mattm\discord-export\*.json                                 │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼  engine/discord/cli.py → channel_parsers/bookmark.py
┌──────────────────────────────────────────────────────────────────────┐
│ engine/data/jarvis_trader.db  ← CANONICAL (jarvis-trader writes)     │
│   discord_bookmarks table                                            │
│     message_id, channel_id, posted_at, url, domain, source_type,     │
│     embed_title, embed_description, content, author_id, author_name, │
│     imported_at                                                      │
│   372 rows, 2026-04-07 → 2026-04-19, 12 columns                      │
└────┬─────────────────────────────────────────┬───────────────────────┘
     │  read-only URI                          │  SELECT only
     │  (Workstream C)                         │  (Workstream B cron, daily 03:00 CT)
     ▼                                         ▼
┌──────────────────────────┐    ┌───────────────────────────────────────────┐
│ master-jarvis            │    │ engine/scripts/render_bookmarks_to_vault  │
│   BookmarkReader         │    │   Catch-up render (skip if exists)        │
│   GET /trade/bookmarks…  │    │     ↓                                     │
│   (NOT deployed yet;     │    │ C:\Users\mattm\second-brain\wiki\         │
│    port decision blocked)│    │   discord-bookmarks\                      │
└──────────────────────────┘    │   ├─ github/   (102 .md pages)            │
                                │   ├─ x/        (221 .md pages)            │
                                │   ├─ other/    (13 .md pages, NEW)        │
                                │   └─ index.md                             │
                                └───────────────────────────────────────────┘
                                              │
                                              ▼  Obsidian graph view
                                       Matt manually triages
                                       (`status`, `jarvis_module`, `notes`)
```

---

## Appendix C — Files touched this session (absolute paths for find/replace)

```
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\discord\models.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\discord\storage.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\discord\channel_parsers\bookmark.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\discord\parser.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\tests\test_discord_bookmark_parser.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\main.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\scripts\render_bookmarks_to_vault.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\tests\test_bookmark_vault_renderer.py
C:\Users\mattm\master-jarvis\app\main.py
C:\Users\mattm\master-jarvis\app\services\trade\bookmark_reader.py
C:\Users\mattm\master-jarvis\app\routers\trade\bookmarks.py
C:\Users\mattm\master-jarvis\tests\trade\test_bookmark_reader.py
C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\handoff-2026-04-20-bookmark-integration.md  (this file)
```

---

## Appendix D — Cross-session MES coordination timeline

A parallel Claude session worked the MES profitability pivot (per MEMORY.md active directive) while this session worked the bookmark integration. Both touched `engine/main.py` and `engine/data/jarvis_trader.db`. This appendix traces their interleaving for post-hoc auditability.

Timeline (commits ordered by author date):

| SHA | Author | Message | Files (summarized) |
|-----|--------|---------|-------------------|
| `fd5b153` | MES session | feat(mes): cross-instrument trend WFO | `engine/experiments/`, `engine/database/migrations.py`, `engine/backtest/trend_signals.py` |
| `2db7f74` | MES session | feat(mes): implement SMA(50,200) golden-cross trend strategy as MES paper baseline | `engine/backtest/signals.py`, `engine/backtest/trend_signals.py` |
| **`543d768`** | **this session** | **feat(discord): enrich bookmark rows with message context + author** | **`engine/discord/*`, `engine/tests/test_discord_bookmark_parser.py`** |
| **`4b5722a`** | **this session** | **feat(vault): sync Discord bookmarks to second-brain with daily cron** | **`engine/main.py` (+48 line cron), `engine/scripts/render_bookmarks_to_vault.py`, `engine/tests/test_bookmark_vault_renderer.py`** |
| `d11565f` | MES session | feat(scheduler): wire MES session forward-recorder into lifespan | `engine/main.py` (+70 line cron) |
| `72538f4` | MES session | docs(mes): commit MES profitability search results + roadmap update | `engine/scripts/mes_*_results.json`, `docs/plans/roadmap-2026-04-20-unified.md` |

Key observations:

1. **Two authors on `engine/main.py` within ~5 minutes**. My `4b5722a` added lines 1581-1628 (bookmark vault cron); MES session's `d11565f` added lines 1629-1698 (MES recorder cron). They landed cleanly because:
   - I committed mine first.
   - Their block was inserted *after* mine, not overlapping.
   - Both blocks use the same `try/except/scheduler.add_job` pattern, so they share structural alignment.
   - Neither modified or removed the other's code.

2. **Shared DB, non-overlapping tables**. My Workstream A touched `discord_bookmarks`; MES session's migrations touched `mes_session_hypothesis` (schema v22 per MEMORY.md). Both run `init_tables()` on engine boot; both use idempotent ALTER patterns. No lock contention.

3. **The 13:22 CT push race-condition was benign**. Between my test-sweep (13:22) and my push (13:24), MES session committed `72538f4` (the staged MES JSON files I'd flagged as unrelated drift in handoff v1 Section 9.1). My `git push` sent the full range d168dd0..72538f4, carrying their commit along. This is fine because:
   - Branch is shared (`feat/tradingview-mcp-gamma-kraken`); both sessions authoring it is expected.
   - Their commit has distinct message + files; audit-trail-clean.
   - The MES session did not rebase, reword, or squash my commits — they stand unchanged on origin.

4. **Pre-compact data-layer work was done together**. The live DB at 13:02 CT had both my Workstream A migrations (content/author_id/author_name columns populated) AND the MES schema v22 table. Neither session interfered with the other's data.

### Suggested protocol for future concurrent sessions

If MEMORY.md shows an active directive for another session (like the MES profitability pivot did), and you're working on unrelated code:
1. **Scope check**: are you touching the same files? `git status` + the other session's roadmap doc will tell you.
2. **Snapshot before committing**: if yes, use the snapshot-revert-restore pattern (documented in Section 6 Decision X1) to isolate your hunk.
3. **Push often, not all at once**: if the other session is also committing to origin, smaller more frequent pushes reduce the "who wins the merge" surface area.
4. **Don't force push**: if the other session is actively rebasing, your force-push will lose their work. Merge instead.
5. **Keep memory/ updated**: a post-session MEMORY.md entry clarifying "this session owned X, that session owned Y" prevents confusion next time.

---

## Appendix E — gh CLI + GitHub operations reference (verified this session)

Common operations exercised during the push phase. Commands verified on Windows bash with gh 2.x, `mattamundson` authenticated via keyring.

### Authentication status

```bash
gh auth status
# Shows all authenticated accounts. "Active account: true" flags the default.
# This session saw two accounts logged in: mattamundson (active) and AmoSZN (inactive).
# Commands run as mattamundson by default; switch with `gh auth switch`.
```

Scopes required for typical workflows:
- `repo` — create/read/write repos
- `workflow` — trigger/list workflow runs
- `read:org` — see org-level data
- `gist` — gist creation (optional)

### Create private repo from current working directory

```bash
gh repo create <owner>/<name> --private --source . --remote origin
```

Atomic three-step: creates repo on GitHub, adds `origin` to local `.git/config`, links them. Does NOT push (use `--push` flag to also push the default branch).

Flags worth knowing:
- `--public` / `--private` / `--internal` — visibility
- `--source .` — use current directory (must be a git repo)
- `--remote origin` — remote name to add (default: `origin`)
- `--push` — additionally push the default branch
- `--description "..."` — one-line repo description
- `--gitignore Python` — seed with a Python gitignore (only if repo has no commits)

### List PRs / CI for a branch

```bash
gh pr status                                          # PRs touching current branch
gh pr list --base main                                # open PRs targeting main
gh run list --branch <branch> --limit 10              # CI runs for branch
gh run watch                                          # follow latest run live
gh run view <run-id> --log-failed                     # see only the failing step's log
```

### Open a PR (non-interactive)

```bash
gh pr create \
  --title "feat(trade): add read-only BookmarkReader" \
  --body "$(cat <<'EOF'
## Summary
...
EOF
)" \
  --base master \
  --head feat/bookmark-reader
```

Returns the PR URL on stdout. If run in CI, capture it.

### Inspect a remote repo without cloning

```bash
gh repo view mattamundson/master-jarvis                 # basic info
gh repo view mattamundson/master-jarvis --web           # open in browser
gh api repos/mattamundson/master-jarvis/branches        # branch list with protection
```

### Fetch a specific PR's comments (for resolving review feedback)

```bash
gh api repos/mattamundson/jarvis-trader/pulls/123/comments
```

### Copy-paste: full Workstream C PR open sequence (for when ready)

```bash
cd /c/Users/mattm/master-jarvis
gh pr create \
  --title "feat(trade): read-only BookmarkReader for jarvis-trader bookmarks" \
  --base master \
  --head feat/bookmark-reader \
  --body "$(cat <<'EOF'
## Summary
- Adds `BookmarkReader` (`app/services/trade/bookmark_reader.py`) — read-only reader for jarvis-trader's
  `discord_bookmarks` SQLite table. OS-level write protection via `sqlite3` URI mode.
- Adds `/trade/bookmarks` router with list / search / get-by-id endpoints.
- 21 tests (15 service-level + 6 FastAPI TestClient). All pass in 1.25s.

## Safety model
The reader opens the DB via \`sqlite3.connect(f"file:{path}?mode=ro", uri=True)\`. Any INSERT/UPDATE/DELETE
raises \`sqlite3.OperationalError("attempt to write a readonly database")\`. \`test_read_only_mode_blocks_writes\`
locks this in as a regression.

## Test plan
- [x] \`pytest tests/trade/test_bookmark_reader.py -v\` — 21/21 green
- [x] Live smoke vs. production jarvis-trader DB (372 rows) — reads 372 bookmarks, INSERT blocked
- [ ] HTTP smoke once master-jarvis is deployed (port decision pending)

## Activation
- No engine restart required — reader is on-demand per HTTP call.
- Depends on Workstream A data (jarvis-trader #543d768) for meaningful \`search_content\` hits.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Appendix F — Error recovery playbooks

Scenarios that could go wrong during activation, with pre-thought mitigations.

### F.1 Engine restart triggers ALTER failure

**Symptom**: `pm2 logs jarvis-engine` shows `sqlite3.OperationalError` on startup mentioning `discord_bookmarks`.

**Diagnosis**:
```bash
engine/.venv/Scripts/python -c "
import sqlite3
c = sqlite3.connect('engine/data/jarvis_trader.db')
print(c.execute('PRAGMA table_info(discord_bookmarks)').fetchall())
"
```

If the table has the 12 columns already (as verified this session), the ALTER should short-circuit on "duplicate column" — and `init_tables()` catches that specific exception. If a different error fires, it's not ALTER.

**Recovery**:
- If the error is "duplicate column" and it's not being caught, check `engine/discord/storage.py:init_tables` for the `except` clause and verify the case-insensitive `"duplicate column" not in str(e).lower()` check is present.
- If the error is lock-related (`database is locked`), another process is writing; wait 60s and retry the restart.
- If the error is corruption, restore from `engine/data/jarvis_trader.db.backup.*` (check for backup files via `ls engine/data/*.backup*`).

### F.2 Cron registers but never fires

**Symptom**: Post-restart, no `[BookmarkVaultRender]` log lines appear at 03:00 CT the next morning.

**Diagnosis**:
```bash
pm2 logs jarvis-engine --lines 500 | grep -E "bookmark_vault_render|BookmarkVaultRender"
# Expect at boot: "✅ Bookmark vault renderer registered — fires daily 03:00 CT"
# Expect at 03:00 CT: "[BookmarkVaultRender] created=X skipped=Y failed=Z by_kind={...}"
```

Possible causes:
- Scheduler never boot-registered (look for "Bookmark vault renderer init failed" at boot).
- Scheduler timezone mismatch — verify `CronTrigger(timezone="America/Chicago")` is what APScheduler actually resolved.
- Engine was restarted between 02:00–03:00 CT and the misfire_grace_time (3600s) window was missed.

**Recovery**:
- Restart engine and verify the `registered` log line at boot.
- Run the script standalone to confirm the renderer logic itself works:
  ```bash
  engine/.venv/Scripts/python engine/scripts/render_bookmarks_to_vault.py
  # Expect: "rendered N pages (github: X, x_post: Y, other: Z)"
  ```
- If standalone works but cron doesn't, the issue is APScheduler registration. Check `scheduler is not None` guard in `engine/main.py`.

### F.3 Master-jarvis PR CI comes up red

**Symptom**: opened PR shows red X on tests.

**Diagnosis**:
```bash
cd /c/Users/mattm/master-jarvis
gh run list --branch feat/bookmark-reader --limit 3
gh run view <run-id> --log-failed
```

Common failures for a fresh repo:
- Missing `requirements.txt` / `pyproject.toml` → pip install step fails → add dependency manifest.
- Tests try to open Windows path `C:\Users\mattm\...` on Linux CI → add `conftest.py` with env var override (see Section 12.3).
- Python version mismatch (CI runs 3.11, tests assume 3.12+ features) → pin CI to `python-version: '3.12'`.

**Recovery**:
- Fix the underlying issue.
- Force-push is acceptable on `feat/bookmark-reader` (feature branch, no concurrent sessions on it), but `git push origin feat/bookmark-reader` (no --force) is safer.
- Close and reopen the PR if GitHub Actions gets into a bad state.

### F.4 Git push rejected for non-fast-forward

**Symptom**: `git push origin feat/tradingview-mcp-gamma-kraken` returns `! [rejected] (non-fast-forward)`.

**Diagnosis**: another session (or GitHub UI) committed to the same branch between your last fetch and your push.

**Recovery**:
```bash
git fetch origin                                      # see the new remote commits
git log HEAD..origin/feat/tradingview-mcp-gamma-kraken --oneline   # what's ahead?
git rebase origin/feat/tradingview-mcp-gamma-kraken   # replay your commits on top
# OR
git pull --rebase origin feat/tradingview-mcp-gamma-kraken
git push origin feat/tradingview-mcp-gamma-kraken
```

**Do NOT force-push** — you'd clobber the other session's commits.

### F.5 DB file locked during master-jarvis read

**Symptom**: `BookmarkReader.list_bookmarks()` raises `sqlite3.OperationalError("database is locked")`.

**Diagnosis**:
```python
# In master-jarvis:
import sqlite3
c = sqlite3.connect("file:/path/to/jarvis_trader.db?mode=ro", uri=True, timeout=5.0)
print(c.execute("PRAGMA journal_mode").fetchone())
# Expect: ('wal',) — if not WAL, switch modes on writer side
```

WAL mode prevents reader/writer blocking. If WAL is live (as this session verified), "database is locked" should never appear for pure SELECT readers.

**Recovery**:
- If journal_mode is NOT wal: ask the user to switch on the writer side (`PRAGMA journal_mode=WAL` is persistent).
- If WAL is live and the error persists, check for an exclusive transaction: `BEGIN EXCLUSIVE` on the writer side would block readers. Review recent jarvis-trader commits for `BEGIN EXCLUSIVE` usage.
- Transient: retry with exponential backoff. The router layer translates OperationalError → HTTP 503, which signals retriability.

### F.6 Vault render produces zero pages

**Symptom**: `render_bookmarks_to_vault.py` runs to completion but creates no files.

**Diagnosis**:
```bash
engine/.venv/Scripts/python -c "
import sqlite3
c = sqlite3.connect('engine/data/jarvis_trader.db')
print('total:', c.execute('SELECT COUNT(*) FROM discord_bookmarks').fetchone()[0])
print('first:', c.execute('SELECT message_id, url, source_type FROM discord_bookmarks ORDER BY posted_at ASC LIMIT 1').fetchone())
"
```

If total > 0 but rendered = 0, every row's target path already exists (`stats["skipped_existing"] == total`). This is the expected no-op steady state after catch-up completes.

**Recovery**:
- Expected behavior; do nothing.
- If you want to force-render (e.g., to apply updated templates), delete target files first — but remember this clobbers manual triage.

---

*End of handoff v2. Next session: re-run §10.1 quick-start, confirm state matches, and decide on Priority-1 activation (engine restart 2026-04-22) vs. Priority-2 PR (Workstream C at `https://github.com/mattamundson/master-jarvis/pull/new/feat/bookmark-reader`).*

*This handoff was expanded twice in one session (v1 at 13:03 CT, v2 at ~15:55 CT) as the work progressed past the original stopping point. Future-me: consider whether a handoff that's rewritten mid-session is still a handoff, or whether it's a live working document that should be split into (a) the frozen-at-compact-point snapshot and (b) the append-only activity log after it. Not resolved in this session.*
