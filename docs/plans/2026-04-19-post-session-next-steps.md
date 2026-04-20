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

2. **Pydantic model** (NOT dataclass; plan originally wrong) — add `Bookmark(BaseModel)` to `engine/discord/models.py` alongside existing `BotSignal`/`IBReport`/`CoreyAlert`/`CoreyCommentary` (all four are `BaseModel`, see `models.py:6,34,56,68`). Fields match columns above.

3. **Insert function** — add `insert_bookmark` to `engine/discord/storage.py`, mirror `insert_corey_commentary` at `storage.py:196-216` (uses `INSERT OR IGNORE` + `SELECT changes()` idempotency check). Add `from .models import ... Bookmark` to import list at `storage.py:4`. Extend `CREATE_TABLES_SQL` at `storage.py:8-80` with the new table.

4. **Channel parser module** — create `engine/discord/channel_parsers/bookmark.py` mirroring the sibling modules (`bot_alerts.py`, `general.py`, `market_updates.py`, etc. — each exposes `parse_channel(messages, channel_name) -> List[dict]`). Extract first URL from `m["content"]` via regex, derive `domain` with `urllib.parse.urlparse`, classify `source_type` via dict lookup, pull `embed_title` + `embed_description` from `m["embeds"][0]` if non-empty.

5. **Wire into dispatch** — `engine/discord/parser.py` needs three edits:
   - Import: add `bookmark` to the `from .channel_parsers import ...` line at `parser.py:9`
   - Model import: add `Bookmark` to `from .models import ...` at `parser.py:10`
   - Storage import: add `insert_bookmark` to `from .storage import ...` block at `parser.py:11-17`
   - `CHANNEL_MAP` at `parser.py:22-47`: add `"1490851279180660819": {"parser": "bookmark", "type": "bookmark"}`
   - Dispatch branch at `parser.py:102-114`: add `elif parser_name == "bookmark": parsed_list = bookmark.parse_channel(messages, "jarvis-trader-general")`
   - Insert branch at `parser.py:125-136`: add `elif data_type == "bookmark": bookmark_obj = Bookmark(**item); inserted = insert_bookmark(conn, bookmark_obj)`

6. **Test fixture** — real data confirmed via this scouting pass: `C:\Users\mattm\discord-export\Jarvis-Trader - Text Channels - general [1490851279180660819] (after 2026-04-16).json` has **63 messages** (4-day window → ~15/day density, ~450/month). Use as golden fixture. First message shape verified:
   ```
   content: "https://x.com/noisyb0y1/status/2044692412061425748?s=12"
   embeds[0].title: ""                  # often empty for x.com
   embeds[0].description: "Anthropic hackathon winner automated his entire Workflow..."  # TWEET BODY — signal text
   embeds[0].url: "https://twitter.com/noisyb0y1/..."  # canonical redirect
   author.name: "amoszn"                # Matt's handle; only poster in this channel
   ```
   Note: `embed_description` contains actual tweet text — more signal-rich than just URLs. Agent consumers can cluster on description semantics. Domain normalization: treat `x.com` and `twitter.com` as the same `source_type='x_post'` (Discord's embed scraper converts x.com URLs to twitter.com in the embed.url field).

7. **Agent consumer** (optional, follow-up) — a research agent that queries `SELECT url, embed_description FROM discord_bookmarks WHERE posted_at > date('now', '-7 days') AND source_type='x_post'` and summarizes thematic clusters for the morning brief. Out of scope for this plan; data + embed_description existing is sufficient value.

### Files to touch (corrected from scouting 2026-04-20 00:15 CT)
- `engine/discord/models.py` — add `Bookmark(BaseModel)` class (not storage.py — original plan had the wrong file)
- `engine/discord/storage.py` — extend `CREATE_TABLES_SQL`, add `insert_bookmark` function, update `.models` import
- `engine/discord/channel_parsers/bookmark.py` — **NEW FILE** implementing `parse_channel(messages, channel_name)`
- `engine/discord/channel_parsers/__init__.py` — (check whether it exports anything; may or may not need update)
- `engine/discord/parser.py` — update 3 import lines + CHANNEL_MAP + 2 dispatch elifs (see step 5 above)
- Test file — check existing test conventions in `engine/tests/test_discord_*.py` first; if there's a per-channel pattern, mirror it. Fixture: copy or reference the real `(after 2026-04-16).json` into `engine/tests/fixtures/` if that dir exists.

### Verification
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.\.venv\Scripts\python.exe -m scripts.nightly_discord --import-only
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db'); print(c.execute('SELECT COUNT(*), MAX(posted_at) FROM discord_bookmarks').fetchone())"
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
