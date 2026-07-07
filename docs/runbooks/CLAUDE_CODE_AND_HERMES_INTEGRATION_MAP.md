# Claude Code + Hermes Integration Map

**Purpose:** Single reference showing how every surface shipped on 2026-05-20 is consumed by Claude Code (direct tool / Bash caller in a dev session) and by Hermes (scheduled or voice-triggered HTTP caller via skills and crons). Mirrors the format of `HEALTH_API_CONTRACT.md`.

---

## 1. The Mental Model

Three layers — each with a distinct role and access pattern:

| Layer | Where | Source of truth for |
|---|---|---|
| **Engine (port 8010)** | FastAPI + SQLite | Pipeline state, bookmarks, tearsheets, broker positions |
| **MCP tools (stdio)** | Per Claude Code session | Discord live REST (bookmarks, personal channel) |
| **Vault (gbrain-ingested)** | Filesystem + semantic index | Durable research, wiki concepts, processed intel |

**Claude Code** is a direct tool caller. It reaches MCP servers via stdio, hits engine routes via Bash `Invoke-RestMethod`, reads the vault via `Read`/`Grep`/`Glob`, and can edit code. It runs interactively with full codebase context.

**Hermes** is a scheduled/voice/remote caller. It cannot load MCP tools — stdio is not available outside a Claude Code session. It reaches surfaces via HTTP (engine port 8010) using `aiohttp` from skill code, and reads the vault via its gbrain semantic-search MCP. Hermes runs headlessly in WSL2 on a systemd unit.

The practical consequence: **any surface that is MCP-only is invisible to Hermes** until an engine HTTP route exposes the same data.

---

## 2. Integration Matrix

| Surface | Claude Code consumption | Hermes consumption |
|---|---|---|
| **`get_recent_bookmarks` MCP** | `mcp__discord-jarvis__get_recent_bookmarks(hours=168)` | Cannot consume MCP. Call `GET /discord/bookmarks/recent?hours=N` via aiohttp from skill |
| **`search_bookmarks` MCP** | `mcp__discord-jarvis__search_bookmarks(query="...")` | Cannot consume MCP. Call `GET /discord/bookmarks/search?q=...` via aiohttp |
| **`get_bookmark_stats` MCP** | `mcp__discord-jarvis__get_bookmark_stats()` | No HTTP equivalent yet — stats are MCP-only [GAP] |
| **`list_recent_messages` MCP** (`discord-personal`)  | `mcp__discord-personal__list_recent_messages(channel_id=...)` — awaits token | Cannot consume MCP. No HTTP route exists — Hermes is blocked until an adapter is built [GAP] |
| **`get_message_by_id` MCP** | `mcp__discord-personal__get_message_by_id(id=...)` | Same gap — no HTTP adapter |
| **`search_personal_channel` MCP** | `mcp__discord-personal__search_personal_channel(query=...)` | Same gap — no HTTP adapter |
| **`post_to_personal_channel` MCP** | `mcp__discord-personal__post_to_personal_channel(content=...)` | Same gap — blocked |
| **`get_channel_info` MCP** | `mcp__discord-personal__get_channel_info()` | Same gap — blocked |
| **`GET /discord/bookmarks/recent`** | Bash: `Invoke-RestMethod http://127.0.0.1:8010/discord/bookmarks/recent -H "X-API-Key: $key"` | Native: `aiohttp.get("/discord/bookmarks/recent", headers={"X-API-Key": key})` from skill |
| **`GET /discord/bookmarks/search`** | Bash: `Invoke-RestMethod "http://127.0.0.1:8010/discord/bookmarks/search?q=..."` + `X-API-Key` | Native: `aiohttp.get("/discord/bookmarks/search", params={"q": query})` from skill |
| **`GET /reports/quantstats`** | Bash: `Invoke-RestMethod "http://127.0.0.1:8010/reports/quantstats?days=90"` + `X-API-Key` | Native: scheduled cron calls route and writes Markdown summary to gbrain memory |
| **`<QuantStatsPanel>` dashboard widget** | Browser at `http://127.0.0.1:3010/performance` — visual only | Not applicable — Hermes is headless; reads data via `/reports/quantstats` HTTP |
| **`<BookmarkFeedPanel>` dashboard widget** | Browser at `http://127.0.0.1:3010/` — visual only | Not applicable — Hermes reads bookmark data via HTTP route |
| **Kronos classifier (stub)** | Verify via `pytest engine/tests/test_kronos_classifier.py -v`; activate with `ENABLE_KRONOS=1` in `engine/.env` | Not directly consumable. Hermes cannot toggle the flag remotely — no engine endpoint exposes the env toggle [GAP] |
| **ResearchAgent (stub)** | Verify via `pytest engine/tests/test_research_agent.py -v`; activate with `ENABLE_RESEARCH_AGENT=1` in `engine/.env` | Same constraint as Kronos — remote toggle not available [GAP] |
| **Vault `_session-2026-05-20-amo/`** (4,581 files) | `Read` / `Grep` / `Glob` on `master-jarvis/second-brain/raw/_session-2026-05-20-amo/{wiki,discord-*}` | gbrain semantic search MCP: `gbrain.search("topic")` against the ingested vault index |
| **Vault peer session `wiki/`** (~3,374 files) | Same `Read`/`Glob` on `master-jarvis/second-brain/raw/wiki/` | Same gbrain semantic search — both session dirs land in the same index |

---

## 3. Recipes — Concrete Patterns

### Recipe A: "Show me what got bookmarked this week"

| | Pattern |
|---|---|
| **Claude Code** | `mcp__discord-jarvis__get_recent_bookmarks(hours=168)` |
| **Hermes** | Skill calls `GET /discord/bookmarks/recent?hours=168` with `X-API-Key`; formats top-10 as Telegram message |

### Recipe B: "Search bookmark feed for a topic"

| | Pattern |
|---|---|
| **Claude Code** | `mcp__discord-jarvis__search_bookmarks(query="kronos")` |
| **Hermes** | `aiohttp.get("/discord/bookmarks/search", params={"q": "kronos"})` inside `jarvis-discord-bookmarks` skill; post result to Telegram |

### Recipe C: "Generate today's portfolio tearsheet"

| | Pattern |
|---|---|
| **Claude Code** | `Invoke-RestMethod "http://127.0.0.1:8010/reports/quantstats?days=90" -H "X-API-Key: $key"` |
| **Hermes** | Scheduled cron (8 pm CT daily) — `jarvis-quantstats-tearsheet` skill calls the route, writes Markdown to `_hermes-cron-<date>/tearsheet.md` in gbrain vault |

### Recipe D: "Check pipeline output for a symbol"

| | Pattern |
|---|---|
| **Claude Code** | `Invoke-RestMethod -Method POST "http://127.0.0.1:8010/pipeline/run" -Body '{"symbol":"MES"}' -ContentType "application/json" -H "X-API-Key: $key"` |
| **Hermes** | `jarvis-pipeline-run` skill triggered by Telegram message "pipeline mes" — POSTs to `/pipeline/run` and replies with verdict |

### Recipe E: "Audit the unactioned bookmark backlog"

| | Pattern |
|---|---|
| **Claude Code** | `Read master-jarvis/second-brain/raw/_session-2026-05-20-amo/wiki/trading/discord-top-50-unactioned-bookmarks.md` |
| **Hermes** | Weekly cron: gbrain semantic search for `"action item priority>=4"` → post top 5 to Telegram |

---

## 4. When to Use Which

```
Is this deep work in a dev session?
  YES → Claude Code
    → full MCP access, codebase edits, multi-file context
  NO → Hermes
    ↓
    Am I away from my desk?
      YES → Hermes via Telegram (text or voice)
    Is this a scheduled recurring task?
      YES → Hermes cron (skill + aiohttp)
    Is this a status check / alert / summary?
      YES → Hermes
    Does this require code edits across multiple files?
      YES → Claude Code
    Is this a one-off vault ingest?
      YES → Claude Code (faster for one-offs)
    Is this a recurring vault sync (e.g. daily discord digest)?
      YES → Hermes cron writing to _hermes-cron-<date>/ subdir
```

---

## 5. Auth + Secrets Summary

| Secret | Where it lives | Who reads it |
|---|---|---|
| Engine `API_KEY` | `engine/.env` (gitignored) | Claude Code reads at runtime via Bash; Hermes reads from `hermes config set ENGINE_API_KEY=...` (per-container env) |
| `DISCORD_PERSONAL_BOT_TOKEN` | `engine/.env` — awaits user creation | MCP server `discord-personal` only; Hermes cannot use it until an HTTP adapter is built |
| gbrain / vault credentials | `~/.gbrain/config.yaml` | Claude Code has no direct gbrain creds — accesses vault as plain filesystem; Hermes uses gbrain MCP natively |

**Rule:** no key values in chat or commits. See `feedback_api_key_handling` memory entry. Read keys from `engine/.env` at call time.

---

## 6. Ready-Made Hermes Skills

### Skill filesystem path (authoritative)

Hermes runs as WSL user `mattm` and reads skills from:
```
/home/mattm/.hermes/skills/<skill-name>/
```
**The Windows path `C:\Users\mattm\.hermes\skills\` is NOT read by Hermes.** When authoring or installing new skills, write directly to the WSL path (or copy via `wsl -u mattm -- cp -r /mnt/c/... /home/mattm/.hermes/skills/...`). The Windows path is kept as a backup only.

### Live skills (9 migrated 2026-05-20)

| Skill | What it does |
|---|---|
| `jarvis-discord-bookmarks` | Calls `GET /discord/bookmarks/recent` or `/search`, formats as Telegram message, optionally writes to vault |
| `jarvis-quantstats-tearsheet` | Calls `GET /reports/quantstats?days=90`, renders Markdown tearsheet, posts summary to Telegram, writes file to `_hermes-cron-<date>/` |
| `jarvis-morning-brief` | Aggregates session bias, overnight signals, gate verdicts, P&L snapshot into a Telegram morning brief |
| `jarvis-pipeline-status` | Polls `/pipeline/status` for all instruments; posts gate v2 verdicts to Telegram |
| `jarvis-regime-check` | Calls regime endpoint; posts current market regime label and confidence to Telegram |
| `jarvis-kill-switch-status` | Checks `/health` and kill-switch state; alerts if thresholds are within 50% of trigger |
| `jarvis-positions` | Calls `/brokers/positions`; formats current open positions as a Telegram card |
| `jarvis-paper-roi` | Pulls paper-account P&L metrics; posts ROI summary and drawdown stats to Telegram |
| `jarvis-self-review` | Runs a self-diagnostic on engine health, pipeline recency, and data freshness; posts findings to Telegram |

### Suggested next skills (not built)

| Skill | What it would do |
|---|---|
| `jarvis-pipeline-run` | Trigger `/pipeline/run` for a named symbol via Telegram command and reply with gate v2 verdict |
| `jarvis-health-alert` | Poll `/health` every 5 minutes; page on degraded state (replaces manual polling) |
| `jarvis-weekly-bookmark-audit` | Weekly cron: semantic search vault for high-priority unactioned bookmarks; post top 5 to Telegram |
| `jarvis-pnl-summary` | Pull `/brokers/positions` + daily P&L and post end-of-session Markdown card to Telegram |
| `jarvis-kronos-report` | Once Kronos is activated, call a future `GET /pipeline/kronos/last` endpoint and post regime label |
| `jarvis-vault-ingest-trigger` | Trigger the gbrain ingest pipeline on demand from Telegram so new vault files are indexed without opening a Claude Code session |

---

## 7. Limitations + Known Gaps

| Gap | Detail | Mitigation |
|---|---|---|
| Hermes cannot consume MCP tools | stdio protocol is session-bound to Claude Code; no cross-process MCP bridge exists | Each MCP surface needs a parallel HTTP route for Hermes access |
| `get_bookmark_stats` is MCP-only | No `/discord/bookmarks/stats` HTTP route exists | Add route to `engine/routers/discord_bookmarks.py` |
| `discord-personal` MCP has no HTTP adapter | All 5 personal-channel tools are stdio-only; Hermes cannot post/read personal channel messages | Build a thin FastAPI adapter or expose routes under `/discord/personal/` |
| Kronos + ResearchAgent flags are env-only | `ENABLE_KRONOS` and `ENABLE_RESEARCH_AGENT` live in `engine/.env`; Hermes cannot toggle them remotely | Add `POST /admin/feature-flags` endpoint (auth-gated) to expose runtime toggles |
| `discord-personal` token not yet created | Bot token missing; MCP server will fail to connect until token is provisioned and added to `engine/.env` | User action required: create bot in Discord Developer Portal |
| Vault write namespace collision | Hermes crons and Claude Code sessions both write to `master-jarvis/second-brain/raw/` | Convention: Hermes always writes to `_hermes-cron-<date>/`; Claude Code session dirs use `_session-<date>-amo/` |

---

## 8. Related Runbooks

- `[[DISCORD_INTEL_RUNBOOK]]` — Discord bookmark pipeline, MCP wiring, channel config
- `[[KRONOS_AND_RESEARCH_AGENT_RUNBOOK]]` — Activation flags, test gate, pipeline position
- `[[QUANTSTATS_TEARSHEET_RUNBOOK]]` — Route params, output format, scheduled tearsheet pattern
- `[[SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK]]` — gbrain ingest, namespace conventions, stale-alert
- External: `~/scripts/HERMES_RUNBOOK.md` — Hermes topology, LLM backends, safe-restart procedure

---

*Written 2026-05-20. Update when a new surface is added or a gap is closed.*
