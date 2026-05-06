session: 2026-05-06 Discord Pipeline Session 2
state: Phase 1-5 code complete; Phase 1 gated on DISCORD_TOKEN

---

## Current State

### What's running
- `Jarvis-DiscordAutoImport` — Ready, every 15 min (BLOCKED: needs DISCORD_TOKEN in engine/.env)
- `Jarvis-DiscordGitDigest` — Ready, daily 03:00 (will no-op until corey_session_bias has data)
- `Jarvis-DiscordObsidianSync` — Ready, daily 02:30 (same)
- Discord MCP server registered as `discord-jarvis` in ~/.claude.json

### What's stopped
- The cron pipeline cannot fetch new Discord data until DISCORD_TOKEN is set
- Corey session bias table is empty until the first successful CLI run with --trigger-commentary

### What's complete (code)
All 5 pipeline phases are code-complete on branch `feat/tradingview-mcp-gamma-kraken`:

| Phase | Description | Commits |
|-------|-------------|---------|
| 1 | Cron ingestion (discord-auto-import.ps1) + MCP server | prior session |
| 1 polish | BUG-3 cache fix + BUG-1 connection leak fix + perf index + .gitignore | `6c939fd` |
| 3 | Corey-bias correlation analysis + /discord/analysis/* endpoints | `628f807` |
| 5 | GitHub daily digest (digest_generator.py + discord-github-digest.ps1) | `a8684e0` |
| 4 | Obsidian second-brain sync (discord-obsidian-sync.ps1 in master-jarvis) | `4c170e1` (master-jarvis) |

---

## Key Decisions Made

### Phase 3 approach
The existing `engine/analysis/discord_correlation.py` was a standalone study script (no Corey bias integration). Rather than rewrite it, we added 4 new functions that accept optional `db_path` (FastAPI-compatible):
- `analyze_corey_alignment_win_rate(symbol, lookback_days, db_path)` — joins on date
- `analyze_session_type_performance()` — win rate by session_type
- `analyze_conviction_threshold()` — win rate by conviction bucket (low/medium/high)
- `get_corey_alignment_summary()` — aggregates all three + `edge_present` flag

The `edge_present` flag is the validation signal: `aligned_wr > opposed_wr` proves Corey's LLM extraction has genuine discriminative power.

### Phase 4 vault path
Obsidian vault is at `~/my-vault` but second-brain content lives at `~/master-jarvis/second-brain/`. The sync script targets `master-jarvis/second-brain/trading/discord/` — consistent with how other second-brain content is organized. The `trading/` subdir existed but was empty.

### Phase 5 design
`digest_generator.py` is a Python module (not a script) so it can be unit tested and called from other code. The PowerShell wrapper handles git exclusively. `discord_daily_sentiment` is queried with graceful fallback (`try/except OperationalError`) in case the table doesn't exist on older DBs.

---

## In-Progress Work

None — all code complete and committed. The only open work is operational:

1. **DISCORD_TOKEN** — must be added to `engine/.env` before any data flows
2. **First manual run** — `.\scripts\discord-auto-import.ps1` to verify end-to-end before trusting cron

---

## Blockers Discovered

### DISCORD_TOKEN missing (P1 blocker)
- Add to `engine/.env`: `DISCORD_TOKEN=<value>`
- Retrieve from Discord web client: F12 → Network → any `api/v9` request → `Authorization` header
- Or desktop: Ctrl+Shift+I → Console → paste the JS token extractor
- Store in 1Password as "Discord User Token" per secret-hygiene rules

### corey_session_bias will be empty initially
The commentary processor needs to run at least once with Corey commentary in the DB before Phases 3-5 produce meaningful output. Phases 3, 4, 5 all gracefully return empty/null when the table has no rows.

---

## Files Created or Modified

### jarvis-trader repo (branch feat/tradingview-mcp-gamma-kraken)
```
engine/discord/cli.py           — BUG-3: added processor.invalidate_cache(date.today()) before get_session_bias()
engine/discord/briefing.py      — BUG-1: _fetch_recent_signal converted to context manager (connection leak fix)
engine/discord/storage.py       — added idx_bot_signals_symbol_ts (symbol, timestamp DESC)
engine/discord/digest_generator.py  — NEW: daily digest JSON generator (Phase 5)
engine/analysis/discord_correlation.py — added 4 Corey-bias correlation functions + datetime import
engine/routers/discord_router.py — added GET /discord/analysis/correlation/{symbol} and /time-patterns/{symbol}
scripts/discord-github-digest.ps1  — NEW: PowerShell wrapper for daily digest + git commit (Phase 5)
.gitignore                      — added /discord-export/
```

### master-jarvis repo (branch feat/claude-code-skill-hub)
```
scripts/discord-obsidian-sync.ps1  — NEW: Phase 4 Obsidian second-brain sync
```

### Scheduled tasks registered
```
Jarvis-DiscordGitDigest    — daily 03:00, runs discord-github-digest.ps1
Jarvis-DiscordObsidianSync — daily 02:30, runs discord-obsidian-sync.ps1
```

---

## TODO Items

### Phase 2 (OpenClaw real-time, deferred)
Before implementing, verify OpenClaw Discord config is active:
```bash
# Check HERMES_RUNBOOK.md section E — confirm ChannelType.DISCORD is wired
cat C:\Users\mattm\scripts\HERMES_RUNBOOK.md | grep -A 20 "Section E"
```
If confirmed: build `master-jarvis/app/routers/trade/discord.py` (POST /ingest, GET /briefing) + `DiscordIngestionService` with 120s debounce.

### data/discord-digests gitignore review
Currently the `/discord-export/` dir is excluded. Verify `data/discord-digests/` is NOT excluded (it should be committed). The current .gitignore has `data/*.json` excluded — need to add a negation for the digests dir:
```
# in .gitignore — add this:
!data/discord-digests/
```
**This is a bug introduced by the existing `data/*.json` exclusion rule.** Fix before first digest run.

### .gitignore negation for discord-digests
File: `C:\Users\mattm\ThinkorSwim\jarvis-trader\.gitignore`
Around line 209: `engine/data/*.json` excludes engine/data, not data/ root.
But check if `data/*.json` exists and would exclude `data/discord-digests/*.json`.

### Verify edge_present after first 30 days of data
Query after ~30 days of commentary processor runs:
```
GET http://127.0.0.1:8010/discord/analysis/correlation/MES?lookback_days=30
```
Check: `summary.edge_present == true` and `aligned_avg_win_rate > opposed_avg_win_rate + 0.05`

---

## Git State

### jarvis-trader (feat/tradingview-mcp-gamma-kraken)
Recent commits this session:
```
a8684e0 feat(discord): Phase 5 GitHub daily digest
628f807 feat(discord): Phase 3 Corey-bias correlation analysis + API endpoints
6c939fd fix(discord): cache invalidation, connection leak, and perf index
```

### master-jarvis (feat/claude-code-skill-hub)
```
4c170e1 feat(discord): Phase 4 Obsidian second-brain sync script
```

---

## Suggested Next Action

**Fix the .gitignore negation for data/discord-digests/ before the first cron run:**

In `.gitignore`, around the `data/*.json` area, add:
```
!data/discord-digests/
!data/discord-digests/*.json
```

Without this, the Phase 5 digest files will be generated but `git add` will silently no-op and the commit will be empty.

Then do the DISCORD_TOKEN setup and run `.\scripts\discord-auto-import.ps1` manually to verify the full pipeline end-to-end.
