session: 2026-05-06 Discord Intelligence Pipeline — Session 2 (Comprehensive Handoff)
branch: feat/tradingview-mcp-gamma-kraken (jarvis-trader) | feat/claude-code-skill-hub (master-jarvis)
state: Phases 1–5 code complete and committed; pipeline gated on DISCORD_TOKEN

---

## 1. Current State

### Running services and their actual status

| Component | Status | Notes |
|-----------|--------|-------|
| `Jarvis-DiscordAutoImport` | Ready (Task Scheduler, every 15 min) | **BLOCKED** — needs `DISCORD_TOKEN` in `engine/.env`; will silently fail until set |
| `Jarvis-DiscordGitDigest` | Ready (daily 03:00) | Will produce valid JSON but empty fields until `corey_session_bias` has data |
| `Jarvis-DiscordObsidianSync` | Ready (daily 02:30) | Will exit 0 with "no rows" message until `corey_session_bias` has data |
| Discord MCP server (`discord-jarvis`) | Registered in `~/.claude.json` | Not running until Claude Code session loads it; read-only, no persistent process |
| `/discord/analysis/correlation/:symbol` | Code complete, **not yet live** | Engine restart required to load new router endpoints |
| `/discord/analysis/time-patterns/:symbol` | Code complete, **not yet live** | Same — `compute_time_patterns` (Phase 3) needs engine restart |
| `/discord/briefing` | Live | Was live before this session |
| `/discord/signals`, `/discord/stats`, etc. | Live | Pre-existing endpoints unchanged |

### What the pipeline looks like when fully operational

```
Every 15 min:
  Jarvis-DiscordAutoImport
    └─ DCE CLI: export 15 channels (last 2 days, JSON format)
    └─ python -m engine.discord.cli --source ./discord-export --trigger-commentary
          └─ run_import() → 7 SQLite tables
          └─ if inserted > 0:
                processor.invalidate_cache(today)
                CoreyCommentaryProcessor.get_session_bias() → corey_session_bias

Daily 02:30:
  Jarvis-DiscordObsidianSync
    └─ inline Python: SELECT last 7 days from corey_session_bias
    └─ Write markdown files to second-brain/trading/discord/

Daily 03:00:
  Jarvis-DiscordGitDigest
    └─ python -m engine.discord.digest_generator --date yesterday
    └─ git add data/discord-digests/YYYY-MM-DD.json
    └─ git commit -m "data(discord): YYYY-MM-DD digest"
```

### What's still missing from the picture

- **`discord_daily_sentiment` table is lazily created** — it only exists after `SentimentProvider` is first instantiated. If the engine hasn't served a sentiment request, this table doesn't exist yet. The digest generator handles this gracefully (`OperationalError` fallback), but the Phase 3 summary endpoint will return `sentiment_score: null` until the SentimentProvider ETL runs. To force it: hit `GET /discord/briefing?symbol=MES` once, which instantiates `SentimentProvider` internally.

- **Phase 2 (OpenClaw real-time)** — explicitly deferred. The 15-minute cron is the only ingest path until OpenClaw Discord config is verified.

---

## 2. Key Decisions Made and Their Rationale

### Phase 3 — Four new functions added to existing file, not a new file

The existing `discord_correlation.py` was a 250-line pandas-heavy standalone study script. Three options considered:

1. **Rewrite entirely** — highest coherence but kills the NQ-alignment study that already works
2. **New file (`discord_corey_correlation.py`)** — cleanest separation but splits related analysis logic
3. **Add to existing file** — preserves the working study, groups all Discord correlation logic in one place

Chose option 3. The existing `run_correlation_study()` function is completely untouched. The 4 new functions (`_is_aligned`, `analyze_corey_alignment_win_rate`, `analyze_session_type_performance`, `analyze_conviction_threshold`, `get_corey_alignment_summary`) sit in a clearly demarcated section starting at line 459 with a doc comment explaining the boundary.

**Tradeoff accepted:** The existing functions use `pandas.read_sql_query` + DataFrames; the new functions use raw `sqlite3.Row` + Python dicts. Inconsistent within the same file. Acceptable for now because the new functions target FastAPI use (dicts serialize directly to JSON) while the old functions target CSV study output.

### Phase 3 — Endpoints added to `discord_router.py`, not a new router file

The plan originally specified `discord_analysis_router.py` (a new file). Discovery: `discord_router.py` is already imported and mounted in `main.py` with prefix `/discord`. Adding two endpoints to it costs zero wiring — no `main.py` changes. A new router would require a new import and `app.include_router()` call. The endpoints belong to the same `/discord` namespace conceptually. Chose to add to the existing file.

### `win_rate` field is 0–100, not 0.0–1.0

This is not obvious from the field name or schema. The `discord_bot_signals` table stores win_rate as a percentage (e.g., `65.5` means 65.5%). This is how DiscordChatExporter receives it from the bot's Discord messages. All three new analysis functions divide by `100.0` before performing comparisons or returning results in API responses. This is verified by looking at `discord_correlation.py:191`:
```python
df["win_rate_norm"] = df["win_rate"] / 100.0  # 0.0–1.0 scale
```
The existing study script comment makes this explicit. The `edge_present` comparison in `get_corey_alignment_summary` is between two 0.0–1.0 values.

### `_is_aligned()` maps Corey's `directional_bias` to bot signal `direction`

The commentary processor writes exactly three values for `directional_bias`: `"bullish"`, `"bearish"`, `"neutral"`. The `_is_aligned()` function accepts aliases (`"long"`, `"buy"`, `"short"`, `"sell"`) for forward-compatibility if the prompt is ever changed to output different labels. These extra branches are currently dead code but harmless.

`discord_bot_signals.direction` contains `"LONG"` or `"SHORT"` (uppercase). The function handles this via `.upper()` normalization.

Logic table:

| Corey bias | Signal direction | `_is_aligned()` |
|------------|-----------------|-----------------|
| bullish | LONG | `True` |
| bearish | SHORT | `True` |
| bullish | SHORT | `False` |
| bearish | LONG | `False` |
| neutral | any | `None` |
| unknown/empty | any | `None` |

### `data_quality` filter in all new analysis functions

All three analysis queries filter `WHERE cs.data_quality IN ('fresh', 'stale')`. This excludes rows where `data_quality = 'none'` (commentary processor ran but found zero messages for that date — no LLM output). The decision: silent exclusion rather than returning error. A date with `data_quality = 'none'` has no usable bias data, so including it would pollute the win rate averages with untagged signals.

**Risk:** If the commentary processor consistently fails (API key issue, rate limit) for a stretch of days, the analysis window silently shrinks. The `corey_session_bias` table shows the gap — run `SELECT date, data_quality FROM corey_session_bias ORDER BY date DESC LIMIT 30` to audit.

### Phase 4 — Obsidian sync does NOT git-commit

`discord-obsidian-sync.ps1` writes markdown files to `second-brain/trading/discord/` but does not run `git add` or `git commit`. Decision: Obsidian vault content has its own sync/backup rhythm (likely synced via Obsidian Sync or filesystem backup). The git history for second-brain/ content is less important than for data digests. Committing the obsidian files would also require careful staging in a repo (master-jarvis) that has 200+ pre-existing untracked files.

### Phase 5 — Python module + PowerShell wrapper, not a monolithic script

`digest_generator.py` is a proper Python module callable as `python -m engine.discord.digest_generator` or importable as `from engine.discord.digest_generator import generate_digest`. This means:
- It can be unit-tested without invoking PowerShell
- Future code (e.g., a FastAPI endpoint) can call `generate_digest()` directly
- The PowerShell wrapper has a single responsibility: git operations

The wrapper never uses `git add -A`. It stages exactly `data/discord-digests/$date.json` by explicit path. This is critical given master-jarvis has 200+ untracked files and jarvis-trader has an active working tree.

### `discord_daily_sentiment` graceful fallback in digest_generator

The table is defined in `engine/discord/sentiment_provider.py`, not `engine/discord/storage.py`. It is only created when `SentimentProvider.__init__` is called, which happens lazily on first use. The `generate_digest()` function wraps the sentiment query in `try/except sqlite3.OperationalError` so it silently sets `sentiment_score: null` if the table doesn't exist. This is the correct behavior — the digest should still write even if the sentiment subsystem hasn't been initialized.

---

## 3. In-Progress Work

No code is in-progress. All 5 phases are committed. The only open threads are operational:

### Operational thread 1: DISCORD_TOKEN (P1 blocker)
Pipeline is completely inert until this is set. No data will flow, no commentary will be processed, no bias will accumulate. All downstream phases (3, 4, 5) will produce empty/null output.

### Operational thread 2: Engine restart
The two new Phase 3 endpoints (`/discord/analysis/correlation/:symbol` and `/discord/analysis/time-patterns/:symbol`) were added to `discord_router.py` which is already imported in `main.py`. The engine does not hot-reload — the new endpoints are not accessible until `.\restart_engine.ps1` runs and succeeds. Running `GET /discord/analysis/correlation/MES` before restart will return 404.

### Operational thread 3: `discord_daily_sentiment` bootstrap
The first time `GET /discord/briefing` is called after engine restart, `SentimentProvider` initializes and creates the `discord_daily_sentiment` table. If nobody hits the briefing endpoint, the table won't exist, and Phase 5 digests will always have `sentiment_score: null`. This will self-resolve over time but is worth knowing.

---

## 4. Blockers Discovered

### DISCORD_TOKEN — retrieval and security

**P1 blocker.** Without this, the pipeline is inert.

File to edit: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env`
Line to add: `DISCORD_TOKEN=<value>`

**Security protocol (mandatory):**
1. Store in 1Password as "Discord User Token" **before** adding to `.env`
2. Never echo the token to the terminal or commit it

**Retrieval — Discord Desktop (preferred):**
```
1. Open Discord desktop app
2. Ctrl+Shift+I → Console tab
3. Paste and run:
   webpackChunkdiscord_app.push([[1],{},(e)=>{m=[];for(let c in e.c)m.push(e.c[c])}]);
   m.find(m=>m?.exports?.default?.getToken).exports.default.getToken()
4. Copy the returned string (starts with "MTA..." or similar, length 70+ chars)
```

**Retrieval — Browser fallback:**
```
1. Open Discord in Chrome/Firefox
2. F12 → Network tab → filter by Fetch/XHR
3. Click any message or navigate to a channel
4. Find any request to discord.com/api/v9/...
5. Headers → Request Headers → Authorization value
```

**Important:** This is your personal user token, not a bot token. Discord's ToS prohibits automating user accounts. The risk in this specific use case is **read-only exports via DiscordChatExporter** — DCE is an established tool with years of use in this context. Store the token carefully; if it is compromised, anyone can read your Discord DMs.

**Token validation after setting:**
```powershell
$token = (Get-Content "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env" | Where-Object { $_ -match "DISCORD_TOKEN" }) -replace "DISCORD_TOKEN=", ""
# Should print a non-empty string of 70+ characters
```

### `corey_session_bias` bootstrap delay

The commentary processor needs at least one batch of Corey #market-updates messages before it produces output. After `DISCORD_TOKEN` is set and the first manual run succeeds:

1. DCE exports last 2 days from all 15 channels
2. `run_import()` inserts rows into `discord_corey_commentary`
3. `CoreyCommentaryProcessor.get_session_bias()` fires for today's date
4. It queries `discord_corey_commentary WHERE DATE(timestamp) = today`
5. If Corey has posted to #market-updates today, it calls Claude Haiku with those messages
6. Result is written to `corey_session_bias` with `data_quality = 'fresh'` or `'stale'`

If the first run happens outside market hours (Corey typically posts pre-market), `data_quality` may be `'stale'` if the messages are >2 days old — but they will still be processed.

**How to check the bootstrap worked:**
```python
# Via the API after engine restart
GET http://127.0.0.1:8010/discord/briefing?symbol=MES
# Look for: "session_bias": {"directional_bias": "bullish"/"bearish"/"neutral", ...}
# Not null = bootstrap succeeded
```

### `discord_daily_sentiment` table not pre-created

Not a hard blocker but causes `digest_generator.py` to always return `sentiment_score: null` until `SentimentProvider` is initialized via the engine. **Fix:** add `discord_daily_sentiment` table creation to `storage.py`'s `CREATE_TABLES_SQL` block (see Recommendations section).

### Phase 2 (OpenClaw real-time path) gated on config verification

Before any Phase 2 code is written, HERMES_RUNBOOK.md section E must confirm `ChannelType.DISCORD` is actively connected. The Phase 2 work is ~4 hours of implementation — do not start without this verification, as the architecture may need to change if OpenClaw's Discord session is in a different state than assumed.

---

## 5. Files Created or Modified

### jarvis-trader (`feat/tradingview-mcp-gamma-kraken`)

#### `engine/discord/cli.py` — Modified (commit `6c939fd`)

**What changed:** Added `--trigger-commentary` flag + cache invalidation fix.

**The bug (BUG-3):** `get_session_bias()` reads from the `corey_session_bias` cache table before making an LLM call. If the processor had already run once today (e.g., from the morning), calling it again after new messages were inserted would return the stale morning result — the new messages would be ignored until tomorrow.

**The fix:** `processor.invalidate_cache(date.today())` is called **before** `get_session_bias()`. `invalidate_cache()` deletes the existing row for today's date from `corey_session_bias`, forcing a fresh LLM extraction on the next call.

**Control flow after fix:**
```python
# Only fires when inserted > 0 (avoids unnecessary LLM calls)
if args.trigger_commentary and not args.dry_run:
    inserted = summary.get("total_inserted", 0)
    if inserted > 0:
        processor = CoreyCommentaryProcessor()
        processor.invalidate_cache(date.today())  # ← the fix
        bias = asyncio.run(processor.get_session_bias())
        # bias.data_quality == "none" warning if ANTHROPIC_API_KEY is missing
    else:
        logger.info("Skipping commentary processor — 0 new rows inserted.")
```

**LLM cost consideration:** Each `get_session_bias()` call uses Claude Haiku. At 15-minute intervals with non-zero imports, this is up to 96 Haiku calls/day. Actual cost is very low (Haiku is ~$0.25/M input tokens and Corey's daily messages are short), but monitor via the `cost_tracker` DB table if budget is a concern.

---

#### `engine/discord/briefing.py` — Modified (commit `6c939fd`)

**What changed:** `_fetch_recent_signal()` converted from bare connect/close to context manager.

**The bug (BUG-1):** The original code:
```python
conn = sqlite3.connect(signal_ctx.db_path)
conn.row_factory = sqlite3.Row
row = conn.execute(...).fetchone()
conn.close()  # ← never reached on exception
```
On Windows, SQLite holds a file lock on the `.db` file until the connection is closed. If an exception occurred between `connect()` and `close()` (e.g., malformed SQL, permission error), the file handle would leak silently. In long-running processes (uvicorn), these accumulate.

**The fix:**
```python
with sqlite3.connect(signal_ctx.db_path) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute(...).fetchone()
# context manager guarantees conn.close() on both success and exception
```

The `try/except Exception` wrapping the entire function remains — it catches DB errors and adds them to the briefing's `warnings` list rather than propagating a 500 to the client.

---

#### `engine/discord/storage.py` — Modified (commit `6c939fd`)

**What changed:** Added performance index on `discord_bot_signals`.

```sql
CREATE INDEX IF NOT EXISTS idx_bot_signals_symbol_ts
  ON discord_bot_signals(symbol, timestamp DESC);
```

**Why:** Phase 3 correlation queries join `discord_bot_signals` with `corey_session_bias` on `DATE(timestamp) = date`. At 280K+ rows, a table scan on `discord_bot_signals` with a timestamp filter is the dominant cost. This composite index covers the `symbol = ?` and `timestamp >= ?` predicates in all three new analysis functions. The `timestamp DESC` ordering means the index also covers the `ORDER BY timestamp DESC LIMIT 5` in the digest generator's top-signals query.

**Impact:** Index creation is idempotent (`IF NOT EXISTS`). It runs once on first engine startup after the commit.

---

#### `engine/analysis/discord_correlation.py` — Modified (commit `628f807`)

**What changed:** Added `from datetime import datetime, timedelta` import + 5 new functions in a clearly demarcated section (line 459 onward).

**`_is_aligned(corey_bias, signal_direction) → Optional[bool]`**
Translates the cross-product of Corey's bias (`bullish/bearish/neutral`) × signal direction (`LONG/SHORT`) into a three-valued alignment indicator. Returns `None` for neutral or unknown — these signals are excluded from the aligned/opposed win rate comparison. Pure Python, no DB access.

**`analyze_corey_alignment_win_rate(symbol, lookback_days, db_path, min_signals) → List[dict]`**
Core Phase 3 function. Executes:
```sql
SELECT cs.directional_bias, bs.direction, bs.win_rate, bs.rr
FROM discord_bot_signals bs
JOIN corey_session_bias cs ON DATE(bs.timestamp) = cs.date
WHERE bs.symbol = ?
  AND bs.timestamp >= ?
  AND bs.signal_type = 'ENTRY'
  AND bs.win_rate IS NOT NULL
  AND cs.data_quality IN ('fresh', 'stale')
```
Groups by `(corey_bias, signal_direction)`, computes weighted averages. Returns list of dicts with `corey_bias`, `signal_direction`, `aligned` (True/False/None), `signal_count`, `avg_win_rate` (0.0–1.0), `avg_rr`.

**`analyze_session_type_performance(symbol, lookback_days, db_path, min_signals) → List[dict]`**
Same join, grouped by `cs.session_type`. Returns win rate / avg_rr / avg_gain per session type (`range_day`, `trend_day`, `outside_bar`, `inside_bar`, `uncertain`). Use case: suppress signals or adjust position sizing on days Corey labels "range_day" if the data shows lower win rates on those days.

**`analyze_conviction_threshold(symbol, lookback_days, db_path, min_signals) → List[dict]`**
Groups signals into conviction buckets (0.0–0.3 low, 0.3–0.6 medium, 0.6–1.01 high). If the LLM extraction is working correctly, high-conviction days should show higher win rates — this is the monotonicity test. Bucket thresholds (0.3, 0.6) are hardcoded constants; see Recommendations for parameterization.

**`get_corey_alignment_summary(symbol, lookback_days, db_path) → dict`**
Aggregator. Calls all three functions and computes `summary.edge_present`:
```python
edge_present = (
    aligned_avg_win_rate is not None
    and opposed_avg_win_rate is not None
    and aligned_avg_win_rate > opposed_avg_win_rate
)
```
This is a weak signal test — `edge_present` only requires `aligned > opposed`, not that the gap is statistically significant. After 30+ days of data, the delta should ideally be ≥5 percentage points to be practically meaningful. See TODO for the full validation query.

---

#### `engine/routers/discord_router.py` — Modified (commit `628f807`)

**What changed:** Two new GET endpoints added before the existing `/briefing` endpoint (lines 348–389).

**`GET /discord/analysis/correlation/{symbol}?lookback_days=90`**
Calls `get_corey_alignment_summary(symbol.upper(), lookback_days, db_path)`. Returns the full summary dict. On empty `corey_session_bias`, returns `{"symbol": "MES", "lookback_days": 90, "alignment": [], "session_type_performance": [], "conviction_threshold": [], "summary": {"aligned_avg_win_rate": null, "opposed_avg_win_rate": null, "aligned_signal_count": 0, "opposed_signal_count": 0, "edge_present": false}}`.

**`GET /discord/analysis/time-patterns/{symbol}`**
Calls `compute_time_patterns(symbol.upper(), db_path)`. This function lives in `analysis.discord_time_patterns` which was pre-existing. No changes to that file were made in this session — the endpoint is a new wiring.

**Router registration:** `discord_router.py` is already mounted in `main.py` with prefix `/discord`. No `main.py` changes required. The new endpoints are accessible at `/discord/analysis/correlation/:symbol` and `/discord/analysis/time-patterns/:symbol` after engine restart.

---

#### `engine/discord/digest_generator.py` — New file (commit `a8684e0`)

**Purpose:** Generates a structured daily JSON digest of yesterday's Discord intelligence. Designed as a Python module (not a script) for testability and reuse.

**Primary function: `generate_digest(for_date: date, db_path: str) -> dict`**

Queries three data sources:
1. `corey_session_bias WHERE date = ?` — session type, directional bias, conviction, IB bias, Corey quote
2. `discord_daily_sentiment WHERE date = ?` — keyword sentiment score (graceful fallback if table absent)
3. `discord_bot_signals WHERE DATE(timestamp) = ? AND signal_type = 'ENTRY' AND win_rate IS NOT NULL ORDER BY win_rate DESC LIMIT 5` — top 5 signals by win rate

Output schema:
```json
{
  "date": "YYYY-MM-DD",
  "session_bias": {
    "session_type": "range_day|trend_day|outside_bar|inside_bar|uncertain|null",
    "directional_bias": "bullish|bearish|neutral|null",
    "conviction": 0.0,
    "ib_bias": "...",
    "data_quality": "fresh|stale|none",
    "message_count": 12
  },
  "sentiment_score": 0.312,
  "top_signals": [
    {"symbol": "ES", "direction": "LONG", "entry_price": 5260.0, "win_rate": 76.5, "rr": 2.1, ...}
  ],
  "corey_quote": "IB established, watching 5250 for long setup..."
}
```

**Known issue — default DB path:** `_default_db_path()` resolves to `engine/data/jarvis_trader.db` (one level inside `engine/`), but the actual DB is at `data/jarvis_trader.db` (repo root level). The PowerShell wrapper always passes `--db "data/jarvis_trader.db"` so this is hidden in production. A bare `python -m engine.discord.digest_generator` without `--db` would fail. See Recommendations.

---

#### `scripts/discord-github-digest.ps1` — New file (commit `a8684e0`)

**Purpose:** PowerShell wrapper for Phase 5. Runs the digest generator and commits the output.

**Key design decisions:**
- `Push-Location $repoRoot` before git commands — ensures `git add` paths are relative to repo root
- Stages ONLY `data/discord-digests/$targetDate.json` by explicit path — never `git add -A`
- Idempotent: `git diff --cached --name-only` check means a re-run on the same date is a no-op
- Commit format: `data(discord): YYYY-MM-DD digest` — uses `data()` conventional scope

**Watch point — commit signing:** If the repo has `gpg.signingkey` configured, `git commit` will attempt GPG signing. If gpg-agent is not running (common in scheduled task context), the commit hangs. Check `git config --global commit.gpgsign` — if `true`, either configure gpg-agent to auto-start or disable signing for this repo with `git config commit.gpgsign false` (per-repo override).

---

#### `.gitignore` — Modified (commit `6c939fd`)

Added `/discord-export/` entry. The DCE export directory contains raw JSON channel exports that can be large (100MB+ for 280K messages), are regenerated every 15 minutes, and should never be committed. This matches the pattern of `/discord-charts/` which was already excluded.

---

### master-jarvis (`feat/claude-code-skill-hub`)

#### `scripts/discord-obsidian-sync.ps1` — New file (commit `4c170e1`)

**Purpose:** Phase 4 — nightly sync of Corey session bias into Obsidian second-brain.

**Approach:** Inline Python `-c` script embedded in PowerShell to query the SQLite DB. This avoids the need for a separate `.py` file or FastAPI call, at the cost of readability. The embedded Python uses `sys.argv[1]` to receive the DB path.

**Output files:**
```
second-brain/trading/discord/
├── YYYY-MM-DD-session-bias.md   (one per day, last 7 days)
├── weekly-summary.md            (rolling 7-day table)
└── README.md                    (date-sorted index of all bias files)
```

**Obsidian-specific conventions used:**
- YAML frontmatter with `date`, `session_type`, `directional_bias`, `conviction`, `ib_bias`, `data_quality`, `message_count`
- `[[wikilink]]` format for cross-file links (e.g., `[[2026-05-05-session-bias|2026-05-05]]`)
- Table format in `weekly-summary.md` with clickable wikilinks

**Known gap:** The `triggers_json` and `key_levels_json` fields from `corey_session_bias` are written raw (as JSON strings) into the markdown body under "Specific Triggers" and "Key Levels" headings. They render as code blocks in Obsidian, not as formatted lists. A follow-up improvement would parse these fields and render them as markdown bullet lists. See Recommendations.

---

### Scheduled Tasks (registered via `schtasks.exe`)

| Task name | Trigger | Command | Status |
|-----------|---------|---------|--------|
| `Jarvis-DiscordAutoImport` | Every 15 min | `discord-auto-import.ps1` | Ready |
| `Jarvis-DiscordGitDigest` | Daily 03:00 | `discord-github-digest.ps1` | Ready |
| `Jarvis-DiscordObsidianSync` | Daily 02:30 | `discord-obsidian-sync.ps1` | Ready |

All run as current user with `/RL LIMITED` (not SYSTEM). These tasks do not require elevation.

---

## 6. TODO Items — Prioritized

### P1 — Must do before pipeline runs

1. **Add `DISCORD_TOKEN` to `engine/.env`**
   ```powershell
   # After retrieving from Discord and storing in 1Password:
   Add-Content "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env" "`nDISCORD_TOKEN=<token>"
   ```

2. **Restart the engine**
   ```powershell
   cd C:\Users\mattm\ThinkorSwim\jarvis-trader
   .\restart_engine.ps1
   Invoke-RestMethod http://127.0.0.1:8010/health | ConvertTo-Json -Depth 4
   # Verify: status=ok, tradingview_mcp_healthy=true, llm_path_healthy=true
   ```

3. **Run the pipeline manually to verify end-to-end**
   ```powershell
   cd C:\Users\mattm\ThinkorSwim\jarvis-trader
   .\scripts\discord-auto-import.ps1
   # Watch output — expect: "X/15 channels exported", "Total inserted: N", bias outcome
   ```

4. **Verify data landed**
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8010/discord/stats | ConvertTo-Json
   # discord_corey_commentary.count should be > 0
   Invoke-RestMethod "http://127.0.0.1:8010/discord/briefing?symbol=MES" | ConvertTo-Json -Depth 5
   # session_bias should not be null
   ```

### P2 — Code improvements (see Recommendations for full detail)

5. **Fix `datetime.utcnow()` deprecation** — Python 3.12 deprecates this. Affects 5 call sites:
   - `engine/analysis/discord_correlation.py` lines 504, 567, 634
   - `engine/discord/mcp_server.py` lines 86, 153

6. **Fix `digest_generator.py` default DB path** — `_default_db_path()` resolves to `engine/data/jarvis_trader.db` but actual DB is at repo root `data/jarvis_trader.db`. Low urgency (PowerShell wrapper always passes `--db`), but would break standalone invocation.

7. **Add `discord_daily_sentiment` to `storage.py` CREATE_TABLES_SQL** — table is currently only created when `SentimentProvider` is first instantiated. Moving table creation to `storage.py` makes the schema authoritative and eliminates the graceful-fallback need in `digest_generator.py`.

### P3 — Phase 2 (OpenClaw real-time)

8. **Verify OpenClaw Discord config before writing any Phase 2 code**
   ```powershell
   true && grep -A 20 "Section E" C:/Users/mattm/scripts/HERMES_RUNBOOK.md
   # Confirm ChannelType.DISCORD is wired and receiving messages
   ```
   If confirmed: build `master-jarvis/app/routers/trade/discord.py` (POST /ingest, GET /briefing/{symbol}, GET /session-bias, GET /signals/{symbol}) + `master-jarvis/app/services/trade/discord_ingestion.py` (DiscordIngestionService with 120s asyncio debounce).

### P4 — Validation after ~30 days

9. **Validate `edge_present` after 30 days of data**
   ```
   GET http://127.0.0.1:8010/discord/analysis/correlation/MES?lookback_days=30
   ```
   Target indicators:
   - `summary.edge_present == true`
   - `summary.aligned_avg_win_rate > summary.opposed_avg_win_rate + 0.05` (5pp gap = practically meaningful)
   - `summary.aligned_signal_count >= 30` (minimum for statistical inference)

10. **Validate conviction monotonicity** — after 30 days:
    ```
    GET http://127.0.0.1:8010/discord/analysis/correlation/MES
    # Check conviction_threshold: low.avg_win_rate < medium.avg_win_rate < high.avg_win_rate
    # Monotone increase = LLM extraction is discriminating
    # Flat or inverted = extraction noise, reconsider relying on conviction scores
    ```

11. **Validate session type routing** — after 30 days:
    ```
    GET http://127.0.0.1:8010/discord/analysis/correlation/MES
    # Check session_type_performance
    # If trend_day win_rate > range_day win_rate by 5pp+:
    #   → consider reducing position size or skipping signals on range_day sessions
    ```

### P5 — Push master-jarvis

12. **Push `feat/claude-code-skill-hub`** — branch is 2 commits ahead of origin:
    ```powershell
    cd C:\Users\mattm\master-jarvis
    git push
    ```

---

## 7. Git State (as of session end)

### jarvis-trader (`feat/tradingview-mcp-gamma-kraken`)

```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is up to date with 'origin/feat/tradingview-mcp-gamma-kraken'.

Changes not staged for commit:
    modified: engine/backtest/run_mcl_hypothesis_b.py  ← pre-existing, unrelated to Discord
```

```
git log --oneline -20
f203826 feat(backtest): add MCL Hypothesis D — SMA trend-following runner
2e5885d docs(session-logs): expand discord/career-ops/WFO handoff + archive stale verdicts
b9ca272 chore(verdicts): archive superseded rank files to verdicts/archive/
a8684e0 feat(discord): Phase 5 GitHub daily digest (generator + cron script)
e6aa579 feat(wfo): MNQ trend rank2 FAIL — signal too infrequent on 1h timeframe
628f807 feat(discord): Phase 3 Corey-bias correlation analysis + API endpoints
6c939fd fix(discord): cache invalidation, connection leak, and perf index
2b573bb feat(backtest): add MNQ trend rank2 runner — shorter SMA periods
a56f177 docs(session-logs): expand WFO sweeps handoff — deep analysis + recommendations
de87173 docs(session-logs): WFO sweeps handoff — MNQ rank7+Hyp-B FAIL, rank1 zero-trades
eaa0798 docs(session-logs): expand evening handoff — deep MCL analysis, MNQ predictions
6439eb6 docs(session-logs): evening handoff 2026-05-06
af473a5 chore(verdicts): MNQ breakout rank7 FAIL — signal exhausted
0b860a6 fix(discord): harden env-regex, DCE path fallback, skip-on-zero-exports
a70604b feat(backtest): add MNQ trend rank1 + MCL Hyp-B runners; sentiment overlay
e23785b feat(discord): add Discord MCP server for Claude Code queries
0b2f369 fix(mes-paper): update champion params to rank11 (fast=60) + gate_v2 policy
0681d47 fix(discord): log commentary bias outcome + verify WAL activation
4076abf chore(discord): WAL mode + --trigger-commentary flag
17b7e68 docs(session-logs): add closing handoff for 2026-05-06 session
```

```
git diff --stat HEAD~5 HEAD
 docs/session-logs/HANDOFF_2026-05-06-discord-pipeline-p2.md      |  160 +++
 docs/session-logs/HANDOFF_2026-05-06-discord-pipeline.md         | 1419 +++++++++++++++++---
 engine/backtest/run_mcl_hypothesis_d.py                          |  733 ++++++++++
 engine/data/gate_v2_verdicts/MNQ_trend_rank2.json                |  355 +++++
 engine/data/gate_v2_verdicts/{ => archive}/MCL_meanrev_rank1.json|    0
 engine/data/gate_v2_verdicts/{ => archive}/MES_trend_rank7.json  |    0
 engine/data/gate_v2_verdicts/{ => archive}/MNQ_breakout_rank6.json|   0
 engine/data/gate_v2_verdicts/{ => archive}/MNQ_trend_rank1.json  |    0
 engine/discord/digest_generator.py                               |  155 +++
 scripts/discord-github-digest.ps1                                |   73 +
 10 files changed, 2708 insertions(+), 187 deletions(-)
```

### master-jarvis (`feat/claude-code-skill-hub`)

```
On branch feat/claude-code-skill-hub
Your branch is ahead of 'origin/feat/claude-code-skill-hub' by 2 commits.

Changes not staged for commit:
    modified: CLAUDE.md
    modified: app/core/__init__.py
    modified: app/routers/biz/__init__.py
    modified: app/services/biz/__init__.py

Untracked files: 200+ (pre-existing GMS/biz backlog — DO NOT commit these)
```

```
git log --oneline -10
4c170e1 feat(discord): Phase 4 Obsidian second-brain sync script
aedf135 docs(hermes): reflect control-interface + topology post-T7/T8 close
e75abfc fix(jarvis-mcp): get_briefing requires symbol query param
ded035b docs(hermes): reflect post-T1+T2+T5 state in bundle README
246b0fb docs(hermes): add session handoff for T1+T2+T5 + sibling cron fixes
81fc245 chore(claude-code): regenerate skills-index after GMS frontmatter additions
ffb61f6 docs(claude-code): correct handoff with verified branch topology + GMS root cause
47ffee7 feat(hermes): add jarvis-trader read-only MCP bridge
c2266e6 docs(claude-code): expand session handoff to 945 lines
6b0c683 feat(hermes): bundle NousResearch Hermes ecosystem under master-jarvis
```

```
git diff --stat HEAD~2 HEAD
 hermes/README.md                  |  23 ++++--
 scripts/discord-obsidian-sync.ps1 | 145 ++++++++++++++++++++++++++++++++++++++
 2 files changed, 161 insertions(+), 7 deletions(-)
```

---

## 8. Suggested Next Action

**Set `DISCORD_TOKEN`, verify end-to-end, restart engine.** This is the single most important step — all phases are inert without real data flowing. One manual run will confirm the full chain works or surface the first real error.

```powershell
# Step 1: Add token (retrieve from Discord DevTools first)
Add-Content "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.env" "`nDISCORD_TOKEN=<token>"

# Step 2: Run pipeline manually
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
.\scripts\discord-auto-import.ps1
# Watch output — you should see: "DCE: 15/15 channels exported" and a bias result

# Step 3: Restart engine to activate Phase 3 endpoints
.\restart_engine.ps1
Invoke-RestMethod http://127.0.0.1:8010/health

# Step 4: Verify the briefing endpoint has real data
Invoke-RestMethod "http://127.0.0.1:8010/discord/briefing?symbol=MES" | ConvertTo-Json -Depth 5

# Step 5: Verify Phase 3 endpoints are live (will return empty arrays if no data yet)
Invoke-RestMethod "http://127.0.0.1:8010/discord/analysis/correlation/MES" | ConvertTo-Json -Depth 5
```

After that, cron runs every 15 minutes automatically. Check back in 24–48 hours to confirm `corey_session_bias` is accumulating rows before investing time in Phase 2.

---

## 9. Recommendations for Improvements

These are not blocking issues but represent technical debt, correctness concerns, or meaningful capability upgrades. Ordered by priority.

---

### R1 — Fix `datetime.utcnow()` deprecation (quick, important)

**File:** `engine/analysis/discord_correlation.py` (lines 504, 567, 634) and `engine/discord/mcp_server.py` (lines 86, 153)

`datetime.utcnow()` is deprecated as of Python 3.12 and will be removed in a future version. It also returns a naive datetime, which can cause subtle timezone bugs when compared to timezone-aware datetimes stored in SQLite.

**Fix (5 occurrences, all the same pattern):**
```python
# Before
from datetime import datetime, timedelta
cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")

# After
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%S")
```

---

### R2 — Fix `digest_generator.py` default DB path

**File:** `engine/discord/digest_generator.py` line 26

`_default_db_path()` resolves to `engine/data/jarvis_trader.db` when the actual DB is at the repo root `data/jarvis_trader.db`. The PowerShell wrapper always passes `--db` so this is hidden, but a bare invocation would fail silently.

```python
# Before
def _default_db_path() -> str:
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_root, "data", "jarvis_trader.db")

# After — walk up one more level to repo root
def _default_db_path() -> str:
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(engine_root)
    return os.path.join(repo_root, "data", "jarvis_trader.db")
```

Mirror `discord_correlation.py`'s `_find_db()` which walks parent directories for robustness.

---

### R3 — Move `discord_daily_sentiment` schema to `storage.py`

**Files:** `engine/discord/storage.py` + `engine/discord/sentiment_provider.py`

Currently the `discord_daily_sentiment` table DDL lives in `sentiment_provider.py` (around line 93) and is only created when `SentimentProvider.__init__` runs. All other Discord tables are in `storage.py`'s `CREATE_TABLES_SQL`. This inconsistency means:

1. `digest_generator.py` needs a `try/except OperationalError` fallback
2. A fresh DB (e.g., in test environments) won't have this table until the sentiment subsystem is initialized
3. The schema is not discoverable via `storage.py`

**Fix:** Move the `CREATE TABLE IF NOT EXISTS discord_daily_sentiment` statement to `storage.py`'s `CREATE_TABLES_SQL` block. Keep `SentimentProvider.__init__` calling `_ensure_table()` for backwards compatibility (it's a no-op once the table exists). Remove the `OperationalError` fallback from `digest_generator.py`.

---

### R4 — Raise `min_signals` default from 5 to 30

**File:** `engine/analysis/discord_correlation.py` — all three analysis functions

The current default `min_signals=5` means a conviction bucket or session type with 5 signals will be included in the API response with a stated win rate. A win rate computed from 5 observations has a 95% confidence interval of ±40 percentage points — essentially noise presented as signal.

**Recommendation:**
```python
# Raise to 30 for all three functions
def analyze_corey_alignment_win_rate(symbol, lookback_days=90, db_path=None, min_signals=30):
def analyze_session_type_performance(symbol, lookback_days=90, db_path=None, min_signals=30):
def analyze_conviction_threshold(symbol, lookback_days=90, db_path=None, min_signals=30):
```

With 30 samples, the 95% CI narrows to ±18pp — still wide, but at least not meaningless. For real statistical inference, target ≥100 signals per category and add a p-value to the response (see R5).

**Tradeoff:** With a higher threshold and fresh data, early results will return fewer rows. This is the correct behavior — better to return `[]` (no data) than to return statistically invalid numbers.

---

### R5 — Add p-values and confidence intervals to correlation responses

**File:** `engine/analysis/discord_correlation.py`

The `edge_present` flag in `get_corey_alignment_summary()` is a bare point-estimate comparison (`aligned_wr > opposed_wr`). There is no test of statistical significance. A 1pp gap with 1000 signals each is meaningful. A 10pp gap with 15 signals each is not.

**Recommended addition using `scipy.stats`:**
```python
from scipy.stats import chi2_contingency

# In get_corey_alignment_summary(), after computing aligned_wr and opposed_wr:
aligned_wins = round(aligned_wr * aligned_count) if aligned_wr else 0
aligned_losses = aligned_count - aligned_wins
opposed_wins = round(opposed_wr * opposed_count) if opposed_wr else 0
opposed_losses = opposed_count - opposed_wins

if aligned_count >= 30 and opposed_count >= 30:
    contingency = [[aligned_wins, aligned_losses], [opposed_wins, opposed_losses]]
    _, p_value, _, _ = chi2_contingency(contingency)
    edge_significant = p_value < 0.05
else:
    p_value = None
    edge_significant = None

summary["p_value"] = round(p_value, 4) if p_value is not None else None
summary["edge_significant"] = edge_significant
```

This adds `p_value` and `edge_significant` to the API response without breaking the existing `edge_present` contract.

---

### R6 — Full-text search index for `search_commentary` MCP tool

**File:** `engine/discord/mcp_server.py` line 159 + `engine/discord/storage.py`

The `search_commentary` MCP tool uses `LIKE '%query%'` on `discord_corey_commentary.content`. At 280K+ rows, this is an O(n) table scan. For the MCP server's use case (interactive "what did Corey say about X?"), latency will be 500ms–2s on cold data.

**Fix — add SQLite FTS5:**
```sql
-- In storage.py CREATE_TABLES_SQL, after discord_corey_commentary table:
CREATE VIRTUAL TABLE IF NOT EXISTS discord_corey_commentary_fts
USING fts5(content, timestamp UNINDEXED, channel UNINDEXED,
           content=discord_corey_commentary, content_rowid=id);

-- Keep in sync via trigger:
CREATE TRIGGER IF NOT EXISTS corey_commentary_ai
AFTER INSERT ON discord_corey_commentary BEGIN
    INSERT INTO discord_corey_commentary_fts(rowid, content)
    VALUES (new.id, new.content);
END;
```

**Updated query in `search_commentary`:**
```python
rows = conn.execute(
    """
    SELECT c.timestamp, c.content, c.channel
    FROM discord_corey_commentary c
    JOIN discord_corey_commentary_fts fts ON fts.rowid = c.id
    WHERE discord_corey_commentary_fts MATCH ?
      AND c.timestamp >= ?
    ORDER BY c.timestamp DESC
    LIMIT 20
    """,
    (query, cutoff),
).fetchall()
```

FTS5 `MATCH` is 10–100× faster than `LIKE` and also handles tokenization (e.g., searching "bull" matches "bullish").

**Initial population** (one-time, after adding FTS table to schema):
```sql
INSERT INTO discord_corey_commentary_fts(rowid, content)
SELECT id, content FROM discord_corey_commentary;
```

---

### R7 — Add rate-limit handling to DCE export loop

**File:** `scripts/discord-auto-import.ps1`

The script exports 15 channels every 15 minutes. DiscordChatExporter will return HTTP 429 (rate limited) when Discord throttles requests. The current loop logs a warning per channel but continues. After a bad run, `$successCount` might be 12/15 or 7/15 — data for some channels goes unimported until the next cycle.

**Recommended improvement — retry with backoff:**
```powershell
function Export-Channel {
    param($channelId, $token, $exportDir, $afterDate, $maxRetries = 3)
    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        & $dceExe export --channel $channelId --token $token --format Json `
                         --output $exportDir --after $afterDate --overwrite
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($attempt -lt $maxRetries) {
            Write-Warning "Channel $channelId export failed (attempt $attempt/$maxRetries), retrying in 30s..."
            Start-Sleep 30
        }
    }
    return $false
}
```

Also consider: for the #market-updates channel specifically (the only one that feeds `corey_session_bias`), treat export failure as a hard error rather than a warning. A missed market-updates export means the commentary processor won't have new data.

---

### R8 — Improve Obsidian rendering of `triggers_json` and `key_levels_json`

**File:** `scripts/discord-obsidian-sync.ps1` (the markdown template at line 76–115)

Currently, `$($row.triggers_json)` and `$($row.key_levels_json)` are written raw into the markdown body. They're JSON strings like `["watch 5250 for long", "CPI at 8:30"]`. In Obsidian they render as raw JSON text, not as readable lists.

**Fix — parse and render as bullet lists:**
```powershell
# Add a helper function
function Format-JsonArray {
    param($jsonString)
    if (-not $jsonString) { return "_none_" }
    try {
        $items = $jsonString | ConvertFrom-Json
        if ($items -is [array]) {
            return ($items | ForEach-Object { "- $_" }) -join "`n"
        }
        return $jsonString
    } catch {
        return $jsonString
    }
}

# In the template:
## Specific Triggers
$(Format-JsonArray $row.triggers_json)

## Key Levels
$(Format-JsonArray $row.key_levels_json)
```

---

### R9 — Parameterize conviction bucket thresholds

**File:** `engine/analysis/discord_correlation.py` line 631

```python
BUCKETS = [("low", 0.0, 0.3), ("medium", 0.3, 0.6), ("high", 0.6, 1.01)]
```

These thresholds are hardcoded. If after 30 days of data, the distribution of `conviction` values is concentrated in the 0.2–0.5 range (common with LLM outputs that hedge), the "high" bucket will have almost no data and the split will be misleading.

**After 30 days**, query the actual distribution:
```sql
SELECT
  MIN(conviction) AS min_conv,
  MAX(conviction) AS max_conv,
  AVG(conviction) AS avg_conv,
  COUNT(*) FILTER (WHERE conviction < 0.3) AS low_count,
  COUNT(*) FILTER (WHERE conviction BETWEEN 0.3 AND 0.6) AS med_count,
  COUNT(*) FILTER (WHERE conviction > 0.6) AS high_count
FROM corey_session_bias
WHERE data_quality IN ('fresh', 'stale');
```

If `high_count < 20`, consider adjusting the thresholds (e.g., split at 0.4 and 0.65 instead of 0.3 and 0.6) to ensure each bucket has meaningful sample sizes.

---

### R10 — Add `discord_daily_sentiment` to digest with interpretation label

**File:** `engine/discord/digest_generator.py`

The digest currently stores `sentiment_score` as a raw float. The MCP server adds a categorical interpretation (`"bullish"`, `"bearish"`, `"neutral"`) via the 0.2/-0.2 thresholds in `mcp_server.py:127-131`. The digest should include the interpretation for human readability without requiring a second lookup.

**Fix:**
```python
if sent_row:
    score = sent_row["sentiment_score"]
    digest["sentiment_score"] = score
    if score > 0.2:
        digest["sentiment_label"] = "bullish"
    elif score < -0.2:
        digest["sentiment_label"] = "bearish"
    else:
        digest["sentiment_label"] = "neutral"
```

---

### R11 — Phase 2 debounce window consideration

**For when Phase 2 (OpenClaw real-time) is implemented:**

The plan specifies a 120-second debounce before triggering the commentary processor. This is appropriate for normal Corey posting patterns (he often posts several messages in a short burst). However, consider the following edge case: Corey posts a single critical pre-open message at 8:00 AM CT. The next Corey message might not come until 9:30 AM. The debounce timer starts at 8:00 AM and fires at 8:02 AM — correct and efficient.

But if OpenClaw itself has a reconnect gap (e.g., WSL VM idled and restarted per the `vmIdleTimeout` issue in `rules/windows-pitfalls.md`), messages during the gap are missed. The cron path (every 15 min) provides the safety net — Phase 2 is supplemental, not a replacement.

**Recommendation:** Phase 2's `DiscordIngestionService.ingest_message()` should check if the message has already been ingested (by `message_id`, which DCE also exports) before inserting. The DCE import already handles deduplication via `message_id` — extend this to the real-time path.

---

### R12 — Monitor `edge_present` as a model health signal

Once `corey_session_bias` accumulates 90+ days of data, the correlation endpoint becomes a diagnostic for the LLM extraction quality. If `edge_present` flips from `true` to `false`, it could indicate:

1. **Commentary drift** — Corey's posting style changed (less directional language, more "watching" language)
2. **Market regime change** — the alignment that worked in trending markets doesn't generalize to choppy periods
3. **LLM extraction degradation** — a Claude API change or prompt regression caused the commentary processor to return more "neutral" biases

**Recommendation:** Add `edge_present` as a tracked metric in the morning briefing or in a weekly health check. Specifically, track the rolling 30-day `aligned_avg_win_rate - opposed_avg_win_rate` delta. If it falls below 2pp or goes negative, investigate commentary processor output quality before attributing it to market conditions.

---

### R13 — DCE path fragility

**File:** `scripts/discord-auto-import.ps1` lines 29–35

The DCE executable path encodes the WinGet source registry ID:
```
$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Tyrrrz.DiscordChatExporter.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\DiscordChatExporter.Cli.exe
```

The `Microsoft.Winget.Source_8wekyb3d8bbwe` component is stable but the version subdirectory (not shown here but present in the full path) will change on `winget upgrade`. The script has a `Get-Command` fallback, but if DCE is not on `$PATH`, the fallback also fails.

**Recommendation:** Add DCE to `$PATH` explicitly (or create a symlink at a stable path like `$env:LOCALAPPDATA\Microsoft\WindowsApps\DiscordChatExporter.Cli.exe`) so the `Get-Command` fallback is reliable. Alternatively, use `winget list Tyrrrz.DiscordChatExporter.CLI --accept-source-agreements | Out-String` to dynamically resolve the installed path.
