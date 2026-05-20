# Discord intelligence layer — runbook (2026-05-20)

**Purpose:** Operating reference for every surface in the Discord intelligence
stack — two MCP servers, seven HTTP routes, one ingest task, and six SQLite
tables. Use this when adding a Claude Code tool call, wiring a dashboard widget,
or diagnosing a stale or missing signal.

---

## Overview

The Discord intelligence layer ingests three Discord sources:

- **Corey #market-updates** — auction-theory commentary, structured into session
  bias, keyword sentiment, and FTS-indexed raw text
- **#general bookmark dump** — Matt's URL drops (channel `1490851279180660819`),
  classified into `x_post / github / video / other`
- **Bot channels** — automated entry/exit signals + IB open-interest reports

Data lands in `engine/data/jarvis_trader.db` (SQLite). Two MCP servers expose
it to Claude Code sessions. Seven HTTP routes (port 8010) serve dashboard widgets
and external integrations. One Windows Scheduled Task drives the 15-minute ingest
cycle.

---

## MCP server reference

Both servers are configured in `C:\Users\mattm\.claude.json` under `mcpServers`.
They start automatically when a Claude Code session opens.

### `discord-jarvis` — SQLite-backed read-only tools (7 tools)

**Launch path:**
`engine\.venv\Scripts\python.exe engine\discord\mcp_server.py`

All 7 tools query `engine/data/jarvis_trader.db` directly. Data lags the live
Discord feed by up to 15 minutes (ingest cycle).

| Tool | Key args | Returns |
|------|----------|---------|
| `get_session_bias` | `date` (YYYY-MM-DD, default today) | `session_type`, `directional_bias`, `key_levels`, `ib_bias`, `specific_triggers`, `conviction`, `corey_quote` |
| `get_recent_signals` | `symbol` (ES/CL/NQ/GC), `hours` (default 4) | list: `direction`, `signal_type`, `entry_price`, `target1`, `target2`, `stop1`, `win_rate` |
| `get_daily_sentiment` | `date` (default today) | `sentiment_score` (-1.0 to +1.0), `regime_multiplier`, `interpretation` |
| `search_commentary` | `query`, `days` (default 7) | list: `timestamp`, `content`, `channel`; uses FTS5 with LIKE fallback |
| `get_recent_bookmarks` | `hours` (default 168), `source_type`, `domain`, `before`, `limit` | `{bookmarks, next_before, has_more, page_size}` — paginated |
| `search_bookmarks` | `query`, `days` (default 30), `source_type` | list: `posted_at`, `url`, `domain`, `embed_title`, `embed_description`, `content` |
| `get_bookmark_stats` | `days` (default 30) | `total`, `by_source_type`, `top_domains` |

**When to use:** historical analysis, pre-session briefing, strategy research
across the full ingested corpus. Trades latency (up to 15 min lag) for
comprehensive search via FTS5.

### `discord-personal` — live Discord REST tools (5 tools)

**Launch path:**
`engine\.venv\Scripts\python.exe engine\discord\personal_mcp_server.py`

**Status:** Pending bot token. Place token at `~/Inbox/discord-personal-bot-token.txt`,
add as `DISCORD_PERSONAL_BOT_TOKEN` in `engine/.env`, then restart the MCP server.
Also requires `DISCORD_PERSONAL_CHANNEL_ID=1490851279180660819` and
`DISCORD_PERSONAL_GUILD_ID=1490851278601982165` (defaults already coded into
`personal_mcp_server.py` if env vars are absent).

| Tool | Key args | Notes |
|------|----------|-------|
| `list_recent_messages` | `limit` (1-100, default 20) | Newest first |
| `get_message_by_id` | `message_id` (snowflake string) | Single message |
| `search_personal_channel` | `query`, `limit`, `scan` | Client-side LIKE over last `scan` messages — max 100 per Discord REST cap |
| `post_to_personal_channel` | `content` (≤2000 chars) | Requires Send Messages permission |
| `get_channel_info` | — | Sanity check: confirms bot can see the channel |

**When to use:** real-time messages not yet ingested by the 15-min task; posting
alerts or confirmations back into the channel.

---

## HTTP route reference

All routes mount under the `discord-jarvis` router prefix `/discord` in
`engine/main.py`. All require the `X-API-Key` header (value from `engine/.env`).
Base URL: `http://127.0.0.1:8010`.

| Route | Method | Key params | Notes |
|-------|--------|-----------|-------|
| `/discord/signals` | GET | `symbol`, `direction`, `signal_type`, `limit`, `offset` | 221K+ rows in `discord_bot_signals` |
| `/discord/ib-reports` | GET | `symbol`, `limit`, `offset` | 1,000 rows in `discord_ib_reports` |
| `/discord/intelligence` | GET | `jarvis_bias` (LONG/SHORT/NEUTRAL) | Live-composed feed; uses `DiscordSignalContext` + optional live price from IBKR |
| `/discord/bookmarks/stats` | GET | `lookback_days` (1-90, default 7) | Count + source-type breakdown |
| `/discord/bookmarks/weekly-themes` | GET | `lookback_days`, `max_rows`, `refresh` | LLM-clustered themes; 6h in-memory cache; `?refresh=true` bypasses cache (~$0.02/call at Haiku) |
| `/discord/bookmarks/recent` | GET | `hours` (1-8760, default 168), `source_type`, `domain`, `limit` (1-500) | **NEW** — commit 9d01b06 |
| `/discord/bookmarks/search` | GET | `query` (required), `days` (1-365, default 30), `source_type`, `limit` (1-200, default 30) | **NEW** — commit 9d01b06; LIKE-based |

Source: `engine/routers/discord_router.py`

---

## Underlying ingest

**Task:** `Jarvis-DiscordAutoImport`
**Cadence:** every 15 minutes
**Healthy as of:** 2026-05-20

This task is the sole writer for all six Discord tables. There is no `dce_nightly.log`
(deleted). Check task health with:

```powershell
schtasks /Query /TN "Jarvis-DiscordAutoImport" /V /FO LIST
```

Expected: `Status: Ready`, `Next Run Time` populated.

---

## Data tables (`engine/data/jarvis_trader.db`)

| Table | Rows (approx) | Primary content |
|-------|---------------|-----------------|
| `discord_bookmarks` | 1,016+ | URL drops from channel `1490851279180660819`; columns: `posted_at`, `url`, `domain`, `source_type`, `embed_title`, `embed_description`, `content`, `author_name`, `attachment_urls` |
| `discord_corey_commentary` | 66K+ | Raw Corey messages; FTS5 index in `discord_commentary_fts` |
| `discord_bot_signals` | 221K+ | Automated entry/exit signals; columns: `symbol`, `direction`, `signal_type`, `entry_price`, `target1`, `target2`, `stop1`, `win_rate`, `timestamp` |
| `discord_ib_reports` | 1,000 | IB open-interest / level reports |
| `discord_corey_alerts` | varies | Corey's manual trade alerts |
| `discord_daily_sentiment` | varies | Pre-aggregated keyword sentiment scores |
| `discord_analyses` | varies | LLM analysis cache outputs |

**Known limitation:** `attachment_urls` column in `discord_bookmarks` is
currently unpopulated. This is expected behavior — not a bug.

---

## Recovery and troubleshooting

**MCP tool not appearing in Claude Code session**
Start a fresh session (tools register at startup). If still missing, delete
`engine/discord/__pycache__/` and restart the session.

**HTTP route returns 404**
Confirm the router is mounted in `engine/main.py` and restart the engine:
```powershell
.\restart_engine.ps1
```
Wait for `/health` to report `status=ok` before retesting (~229s startup).

**Ingest lag / stale data**
Check the scheduled task:
```powershell
schtasks /Query /TN "Jarvis-DiscordAutoImport" /V /FO LIST
```
If `Last Run Result` is non-zero, check Windows Event Viewer → Task Scheduler.

**`attachment_urls` always empty** — known limitation, not a bug.

**`discord-personal` tools fail with token error**
Add `DISCORD_PERSONAL_BOT_TOKEN` to `engine/.env` (source the token from
`~/Inbox/discord-personal-bot-token.txt`). Enable Message Content Intent in the
Discord developer portal for the bot application, then restart the MCP process.

---

## Smoke tests — HTTP routes

Replace `<YOUR_API_KEY>` with the value from `engine/.env`.

```powershell
$h = @{ "X-API-Key" = "<YOUR_API_KEY>" }

# Signals — last 5 ES entries
Invoke-RestMethod "http://127.0.0.1:8010/discord/signals?symbol=ES&limit=5" -Headers $h

# IB reports — last 3
Invoke-RestMethod "http://127.0.0.1:8010/discord/ib-reports?limit=3" -Headers $h

# Composed intelligence feed
Invoke-RestMethod "http://127.0.0.1:8010/discord/intelligence?jarvis_bias=NEUTRAL" -Headers $h

# Bookmark stats — last 7 days
Invoke-RestMethod "http://127.0.0.1:8010/discord/bookmarks/stats?lookback_days=7" -Headers $h

# Weekly themes (cached; use ?refresh=true to force LLM call)
Invoke-RestMethod "http://127.0.0.1:8010/discord/bookmarks/weekly-themes" -Headers $h

# Recent bookmarks — last 48h, GitHub only
Invoke-RestMethod "http://127.0.0.1:8010/discord/bookmarks/recent?hours=48&source_type=github" -Headers $h

# Bookmark search
Invoke-RestMethod "http://127.0.0.1:8010/discord/bookmarks/search?query=MES&days=14" -Headers $h
```

---

## Smoke tests — MCP tools

Example invocations inside a Claude Code session:

```
# Session bias for today
mcp__discord-jarvis__get_session_bias {}

# Last 4h ES signals
mcp__discord-jarvis__get_recent_signals {"symbol": "ES", "hours": 4}

# Sentiment for today
mcp__discord-jarvis__get_daily_sentiment {}

# Search Corey's commentary for "ES" in last 3 days
mcp__discord-jarvis__search_commentary {"query": "ES", "days": 3}

# Recent bookmarks — last 48h
mcp__discord-jarvis__get_recent_bookmarks {"hours": 48}

# Search bookmarks for "risk management"
mcp__discord-jarvis__search_bookmarks {"query": "risk management", "days": 14}

# Bookmark stats for last 30 days
mcp__discord-jarvis__get_bookmark_stats {"days": 30}

# Personal channel (requires bot token in engine/.env)
mcp__discord-personal__list_recent_messages {"limit": 10}
mcp__discord-personal__get_channel_info {}
```

---

## Related runbooks

- `[[DISCORD_BRIEFING_RUNBOOK]]` — composed `/discord/briefing` facade (Corey bias + IB levels + sentiment + recent signal, 5-min TTL cache); use for pre-session prep and Hermes morning calls
- `[[HEALTH_API_CONTRACT]]` — `/health` and `/safety/*` stable key contracts
- `[[SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK]]` — Obsidian vault + gbrain ingest pipeline
- `[[CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP]]` — Hermes gateway, MCP wiring, session coordination
