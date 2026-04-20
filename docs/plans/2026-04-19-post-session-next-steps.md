# Next Steps — Post 2026-04-19 Tools Install Session

**Context**: The 2026-04-18 → 2026-04-19 session closed DCE install + T2.1 Discord scheduler (daily 05:30 CT, 3 channels: Corey #general, Corey indicator-alerts, Jarvis-Trader #general). Three items remain open, in priority order. See session handoff at `docs/session-logs/handoff-2026-04-19-tools-install-and-t21.md`.

---

## Phase A — Tomorrow (2026-04-20, ~15 min)

**Goal**: confirm the first auto-fired daily run worked end-to-end.

Run the verification block from the handoff appendix. Success criteria:
- `Get-ScheduledTaskInfo -TaskName JarvisDiscordDailyExport` → `LastRunTime` ~05:30, `LastTaskResult=0`
- Three new `(after 2026-04-17).json` files in `C:\Users\mattm\discord-export\`
- `MAX(timestamp)` on `discord_corey_commentary` advances past 2026-04-01 after engine's Mon 06:00 import
- Wrapper log ends with `=== weekly export complete (import deferred...) ===`

If any step fails: tail the wrapper log, diagnose, patch `discord_weekly_export.ps1`, re-trigger with `Start-ScheduledTask`.

---

## Phase B — Bookmark ingestion pipeline (highest leverage, 1 focused session)

**Why this is the next move**: the new daily scheduler drops ~50 KB/day of Matt's curated X.com + GitHub links into `Jarvis-Trader - Text Channels - general [1490851279180660819] (after *).json`, but **no engine consumer reads it**. Every day it sits there is a day of trading-relevant research that agents can't see.

### Scope
1. **Schema** (`engine/discord/schema.sql` or via alembic/direct migration matching existing table creation pattern):
   ```sql
   CREATE TABLE IF NOT EXISTS discord_bookmarks (
       message_id TEXT PRIMARY KEY,
       channel_id TEXT NOT NULL,
       posted_at TEXT NOT NULL,
       url TEXT NOT NULL,
       domain TEXT,                -- twitter.com, github.com, etc.
       source_type TEXT,           -- 'x_post', 'github_repo', 'news', 'other'
       embed_title TEXT,
       embed_description TEXT,
       imported_at TEXT NOT NULL DEFAULT (datetime('now'))
   );
   CREATE INDEX IF NOT EXISTS idx_bookmarks_posted ON discord_bookmarks(posted_at DESC);
   CREATE INDEX IF NOT EXISTS idx_bookmarks_domain ON discord_bookmarks(domain);
   ```

2. **Dataclass** — mirror the pattern at `engine/discord/storage.py:171` (`CoreyAlert`) / `:196` (`CoreyCommentary`). Add `Bookmark` with fields matching columns.

3. **Insert function** — mirror `insert_corey_commentary` (`storage.py:196-215`). Use `INSERT OR IGNORE` for idempotent reimport (already the pattern).

4. **Parser branch** — at `engine/discord/parser.py:172` (`source_path.glob("*.json")` loop), branch on channel_id extracted from filename (regex at `parser.py:55`). If channel_id == `1490851279180660819`, dispatch to new `parse_bookmark_messages` that extracts first URL from `m["content"]`, derives `domain` from `urllib.parse.urlparse`, classifies `source_type` via a small dict lookup (no ML), pulls `embed_title`/`description` if `m["embeds"]` non-empty.

5. **Test fixture** — use the actual `(after 2026-04-16).json` that just landed at 148 KB as the golden fixture. Check it has 3 messages = 3 bookmarks inserted, correct domains.

6. **Agent consumer** (optional, follow-up) — a research agent that queries `SELECT url FROM discord_bookmarks WHERE posted_at > date('now', '-7 days') AND source_type='x_post'` and summarizes thematic clusters for the morning brief. Out of scope for this plan; the data existing is sufficient value.

### Files to touch
- `engine/discord/schema.sql` (or equivalent) — new table
- `engine/discord/storage.py` — add `Bookmark` class + `insert_bookmark`
- `engine/discord/parser.py` — add channel-ID branch + `parse_bookmark_messages`
- `engine/tests/test_discord_parser.py` (or similar) — add fixture-based test

### Verification
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.\.venv\Scripts\python.exe -m scripts.nightly_discord --import-only
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/jarvis_trader.db'); print(c.execute('SELECT COUNT(*), MAX(posted_at) FROM discord_bookmarks').fetchone())"
```
Expected: count matches number of Matt-authored messages in the newest Jarvis-Trader JSON; `MAX(posted_at)` is within the last 3 days.

### Estimated effort
90-120 minutes. Most of it is writing tests; the parser branch itself is ~30 lines.

---

## Phase C — Loose ends (low priority, batch when convenient)

### C1 — Fix T2.1 incident doc's wrong DCE command (5 min)
`docs/incident-notes/2026-04-17-t2.1-discord-staleness.md` lines showing `exportchannel -c` should be `export -c`. Single find/replace. Matters only if someone re-reads that doc and trusts its example shell block.

### C2 — File gbrain v0.13.0 upstream issue (10 min)
Title: `v0.13.0: fresh init fails with "column \"link_source\" does not exist"; config set silently no-ops`
URL: `https://github.com/garrytan/gbrain/issues/new`
Body: include exact `gbrain --version` + `gbrain init` stderr + `gbrain config set` reproduction + `cat config.json` showing no change.

### C3 — Windows Terminal default profile (30 sec, Matt-only)
`Ctrl+,` → Startup → Default profile → **PowerShell** (GUID `{574e775e-4f2a-5b96-ac1e-a2962a402336}`). Blocked from CLI by permission policy; must be clicked.

### C4 — (Optional, defensive) Pin gbrain to v0.12 tag
Only if Matt ever decides to revive the trading-brain idea despite D6 dropping it. Requires `cd C:\Users\mattm\tools\gbrain && git log --tags --simplify-by-decoration --pretty='%D' | grep 0.12` then checkout + `bun install && bun link`.

### C5 — (Optional) Expand Discord channel set
If `discord_bot_signals` freshness becomes a decision-input concern, add the 9 bot_alerts instrument channels (MCL/MNQ/MES/ES/NQ/CL/GC/YM/SPY) to `$Channels` in `discord_weekly_export.ps1:30-42`. Adds ~3-5 MB/day bandwidth.

---

## Explicitly NOT doing (decisions recorded)

- **gbrain trading brain** — dropped per session D6. Obsidian + claude-mem + OpenClaw cover the semantic-memory need; v0.13 upstream init bug makes it non-trivial anyway.
- **Full #general re-export** — dropped per session D2. 12+hr wall, bandwidth waste; daily `--after 3d` + `INSERT OR IGNORE` dedup is strictly better.
- **PS7 as scheduled task runtime** — dropped per session D4. Store-install path is Task-Scheduler-hostile; PS 5.1 at `System32\WindowsPowerShell\v1.0\powershell.exe` is the stable choice.

---

## Recommended execution order

1. **Tomorrow AM**: Phase A (15 min)
2. **This week**: Phase B (90-120 min) — biggest trading-signal leverage left on the table
3. **Whenever**: Phase C items 1-3 (~15 min batched). C4/C5 only if triggered by new requirements.
