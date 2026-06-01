# Hermes / OpenClaw Architecture

**Status:** ONLINE — system service, Gemini primary (verified 2026-05-21)
**Complements:** `~/scripts/HERMES_RUNBOOK.md` (cold-start ops), `~/scripts/HERMES_ARCHITECTURE.md` (WSL/install details)

---

## What Hermes Does for JARVIS TRADER

Hermes is the AI gateway that routes LLM inference calls from the jarvis-trader engine to external providers. The engine never calls Anthropic/Google/OpenAI directly — all calls go through Hermes, which handles provider selection, fallback, retry, and cost tracking.

Additionally, Hermes acts as the hub for second-brain ingestion: Discord data, X bookmarks, vault content, and market commentary all flow through Hermes skills into the gbrain knowledge base.

---

## Topology

```
jarvis-trader engine (Windows, port 8010)
     │
     │  HERMES_GATEWAY_URL (engine/.env)
     ▼
Hermes gateway (WSL2 Ubuntu — system service hermes-gateway.service)
     │
     │  LLM provider chain (in priority order):
     ├──▶ google/gemini-2.5-flash       [PRIMARY — fast, large context]
     ├──▶ custom:openai/gpt-5           [FALLBACK 1 — via custom_providers]
     └──▶ anthropic/claude-sonnet-4-6   [FALLBACK 2 — restored 2026-05-19]
     │
     │  Messaging integrations:
     ├──▶ Telegram (via Hermes built-in)
     └──▶ WhatsApp (via OpenClaw ← restored 2026-05-08)
     │
     │  Memory / knowledge:
     ├──▶ Mem0 (persistent memory across sessions)
     └──▶ gbrain trading brain (768-dim Ollama embeddings)
```

---

## LLM Provider Chain

### Current config (`/root/.hermes/config.yaml`)

```yaml
model:
  provider: google
  name: gemini-2.5-flash

fallback_chain:
  - provider: custom:openai
    name: gpt-5
  - provider: anthropic
    name: claude-sonnet-4-6
```

### Provider wiring notes

- **Gemini:** native Hermes provider; API key in auth pool
- **OpenAI:** no native Hermes `openai` provider — must use `custom_providers` with `key_env: OPENAI_API_KEY` + `provider: custom:openai`. Setting `provider: openai` silently routes to the wrong handler. (See `feedback_hermes_openai_provider_id.md`)
- **Anthropic:** restored as fallback 2026-05-19 after billing top-up; silently failed before top-up (returned HTTP 400 credit exhaustion; `session_id` still returned so the failure looked like success)

Verify chain end-to-end: `hermes -z` (inside WSL) — should show all 3 providers responding.

---

## Integration Points in Engine

| Engine Location | Hermes Role |
|-----------------|-------------|
| `agents/pipeline.py` | LLM inference for all 5 pipeline stages via `HERMES_GATEWAY_URL` |
| `notifications/openclaw_notifier.py` | Kill-switch and WhatsApp alerts via OpenClaw |
| `discord/briefing.py` | Hermes skills for morning briefing assembly |
| `risk/alert_manager.py` | Escalation alerts via Hermes → Telegram |

Engine health gate: `/health` response includes `llm_path_healthy: true` only when Hermes responds to a probe. If Hermes is down, `llm_path_healthy` goes false and the briefing falls back to empty stubs.

---

## System Service (WSL2)

Hermes runs as a **system service** in WSL2 Ubuntu since 2026-05-19 (previously a manual `nohup` process that died on WSL idle).

| Item | Value |
|------|-------|
| Service name | `hermes-gateway.service` |
| Unit file | `/etc/systemd/system/hermes-gateway.service` |
| Status check | `systemctl status hermes-gateway` (inside WSL) |
| WSL keep-alive | `Jarvis-Hermes-WSL-KeepAlive` scheduled task (Windows) pings WSL every 5 min |
| Linger | `loginctl enable-linger root` — keeps the service alive after WSL session exit |
| WSL idle | `vmIdleTimeout=-1` in `~/.wslconfig` — prevents 60s VM kill |

Safe restart (use instead of raw kill):
```bash
/root/.hermes/bin/hermes-safe-restart.sh
```
**Never** restart from a Claude diagnostic session — drops DMs for 10–73 seconds.

---

## OpenClaw (WhatsApp Bridge)

| Item | Status |
|------|--------|
| Binary | Restored 2026-05-08 — running via systemd in WSL |
| Install path | `~/.openclaw/` or PATH |
| Config | `~/.openclaw/config.yaml` |
| Role | WhatsApp-via-Twilio bridge consumed by Hermes |
| Self-bot concern | Uses DISCORD_TOKEN (mattamundson@gmail.com account) for auto-import cron |

OpenClaw history: binary was missing 2026-05-05 through 2026-05-08. Restored as part of Phase 0 cleanup.

---

## Discord Integration

| Component | Path | Notes |
|-----------|------|-------|
| Jarvis Discord MCP | `engine/discord/jarvis_mcp_server.py` | Bookmarks, signals, commentary — 6 MCP tools |
| Personal Discord MCP | `engine/discord/personal_mcp_server.py` | Direct channel access — 5 MCP tools + UA fix |
| Auto-import cron | `Jarvis-DiscordAutoImport` (Windows task) | Runs every 15 min; uses `DISCORD_TOKEN` self-bot |
| Bot token gap | `jarvis-personal-bot` 403s on channel 1490 | Per-channel grant needed via Discord UI; see `project_bot_channel_access_gap_2026_05_21.md` |
| Data store | Supabase `discord_corey_commentary` (66,275 rows) | Corey #market-updates sentiment source |

**DISCORD_TOKEN security note:** `DISCORD_TOKEN` is a self-bot (ToS violation). MFA enabled 2026-05-21. Deleting the token breaks `Jarvis-DiscordAutoImport` cron immediately. Path 2 (throwaway account) and Path 3 (non-Discord feed) are the viable replacements.

---

## Memory System

### Mem0 (persistent cross-session memory)
- Stores conversation context, trading decisions, signal patterns
- Accessible via `hermes -m` recall commands
- Integrated with the 9 Hermes skills from Stark Mode

### gbrain trading brain
- 768-dim embeddings via local Ollama
- Populated from: Obsidian vault, Discord commentary, X bookmarks, Corey signals
- Status: 1248 pages / 2251 chunks (as of 2026-05-09)
- Repair: `gbrain init --path <trading-brain-path>` after restart

### RAG pipeline (4-source)
- Source 1: gbrain embeddings
- Source 2: Supabase discord commentary
- Source 3: Corey signals DB
- Source 4: vault wiki (second-brain)
- Status: 28% indexed as of 2026-05-22 Hermes top-10 sprint

---

## Hermes Skills (9 active, Stark Mode)

Registered skills callable via `hermes <skill-name>`:

| Skill | Purpose |
|-------|---------|
| `jarvis-trader` | Quick JARVIS status + pipeline signals |
| `goal` | Goal tracking and planning |
| `eod` | End-of-day summary |
| `standup` | Morning standup brief |
| `handoff` | Session handoff writer |
| `hygiene` | Memory + vault hygiene check |
| `routines` | Daily/weekly routine management |
| `alert` | Alert triage and routing |
| `hermes-nightly-sync` | Nightly vault sync and ingest |

---

## Control Room & Dashboard

| Surface | Location | Access |
|---------|----------|--------|
| Hermes TUI dashboard | `hermes dashboard --tui` (WSL) | Port 9119 |
| Vault dashboard | `master-jarvis/reports/vault-dashboard.html` | Local file |
| Control room | `~/.hermes/control-room/` | Plan docs + runbooks |
| T7 WSL dashboard | `http://127.0.0.1:10272` | Note: `127.0.0.1` not `localhost` — IPv6 quirk |

---

## Health Checks

```bash
# From engine
curl http://127.0.0.1:8010/health | python -m json.tool | grep llm_path_healthy

# From WSL — verify provider chain end-to-end
hermes -z

# Check service
wsl systemctl status hermes-gateway

# Check gateway logs
wsl journalctl -u hermes-gateway -n 50
```

Engine `llm_path_healthy: false` after a Hermes restart is normal for ~5–10 seconds while the gateway reconnects.

---

## Key Files

| File | Purpose |
|------|---------|
| `/root/.hermes/config.yaml` | Provider chain, fallback config |
| `~/.hermes/auth.json` | Provider auth pool (chmod 600) |
| `~/.hermes/.env` | Secrets (Telegram token, API keys) |
| `~/scripts/HERMES_RUNBOOK.md` | Cold-start ops (6 sections A–F) |
| `~/scripts/HERMES_ARCHITECTURE.md` | WSL install details + failure modes |
| `/root/.hermes/bin/hermes-safe-restart.sh` | Peer-session-aware restart helper |

---

## Cross-References

- `~/scripts/HERMES_RUNBOOK.md` — full cold-start revival procedures (24.8 KB, 594 lines)
- `~/scripts/HERMES_ARCHITECTURE.md` — WSL paths, install details, failure mode table
- `~/.claude/projects/.../memory/project_hermes_system_service_2026_05_19.md` — system service migration
- `~/.claude/projects/.../memory/project_hermes_top10_sprint_2026_05_22.md` — Mem0, RAG, vault dashboard
- `engine/CLAUDE.md` — active instruments table; Hermes LLM path health gate
