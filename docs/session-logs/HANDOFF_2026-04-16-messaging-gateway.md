# Session Handoff — Always-Available Messaging Gateway
**Date:** 2026-04-16 (8:01 PM – 10:55 PM CDT)
**Branch:** `feat/tradingview-mcp-gamma-kraken`
**Session goal:** Build a zero-cost unified messaging gateway where OpenClaw and Hermes work together — reachable via Telegram, WhatsApp, and HTTP API when paid APIs (Claude/Codex/Gemini) are maxed out.

**Project vision:** OpenClaw and Hermes are complementary agents that should collaborate, not compete. OpenClaw owns WhatsApp + workspace context + cron jobs. Hermes owns the learning loop + skill generation + long-term memory. The messaging gateway unifies them under one ingress so the user can reach either or both from any channel. Future work should wire them into a collaborative pipeline where one agent's output feeds the other.

---

## 1. Session Summary — What Was Accomplished, In What Order

### Phase 1: Roadmap Design (18:00–18:30)
1. Explored codebase state with 2 parallel Explore agents — found existing notification plumbing, config surface, OpenClaw/Hermes runtime configs
2. Designed 10-task roadmap prioritized by ROI toward the project goal
3. Created design doc at `docs/plans/2026-04-16-always-available-messaging-roadmap.md`
4. Created all 10 tasks with dependency chains

### Phase 2: Core Implementation (18:30–19:30)
5. **T1: Fixed Hermes local inference** — discovered 3 config mismatches in WSL (.env had `LLM_MODEL=hermes3:latest` and `HERMES_INFERENCE_PROVIDER=auto`). Fixed, but Hermes CLI still hung because the 92-skill system prompt overwhelms the 7B model. **Pivoted:** switched Hermes adapter from CliAgentAdapter to OllamaAgentAdapter (direct HTTP to Ollama). Result: `"2 + 2 equals 4."` in 39 seconds. Zero cost.
6. **T2: Telegram connection** — implemented long-polling (TelegramPoller class) instead of webhooks. No ngrok/tunnel needed. Deletes any existing webhook on startup, polls getUpdates every 30s. Wired into engine lifespan hooks.
7. **T6: Auto-registration** — superseded by polling approach (no webhook to register).

### Phase 3: OpenClaw Fixes (19:30–20:00)
8. **T5: Fixed OpenClaw persona** — OpenClaw CLI returned career-ops alerts instead of answering prompts. Root cause: 35K-char system prompt with old session context. **Pivoted:** switched OpenClaw adapter to direct Ollama too (same approach as Hermes). Result: `"PERSONA_OK"` in 42 seconds. Both agents now bypass their CLIs for the messaging gateway path.
9. Fixed `OPENCLAW_LOCAL_MODEL` env var — had `ollama/` prefix that Ollama API doesn't understand. Added `.removeprefix("ollama/")` guard.
10. Fixed OpenClaw `--json` output parsing — 3 bugs: (a) output goes to stderr not stdout, (b) multi-line JSON needs `raw_decode` not `json.loads`, (c) warning lines before JSON block need rightmost-`{` scanning.

### Phase 4: Feature Additions (20:00–20:45)
11. **T7: /model switch command** — added `/model list` (queries Ollama `/api/tags`), `/model set <name>` (validates model exists, changes adapter's active model). Verified: lists 6 models with sizes, switches work.
12. **T8: Updated OpenClaw** — from 2026.4.2 to 2026.4.15 via `openclaw update`. Gateway probe: ok (310ms).
13. **T9: Health monitoring** — created `messaging_health.py` with periodic Ollama health check (60s via APScheduler), auto-restart attempt on failure, Telegram alert when backend goes down. Added `/messaging/health` endpoint.

### Phase 5: Telegram Debugging & Channel Architecture (19:10–20:30)
14. **T3: Telegram E2E** — discovered OpenClaw gateway (WSL systemd) was consuming Telegram `getUpdates` for the same bot token. Later verified OpenClaw only loads WhatsApp plugin. The actual thief was the Hermes gateway (separate process).
15. **T4 + T10: Unified channel architecture** — OpenClaw gateway handles WhatsApp natively. Engine handles Telegram + API. Both use local Ollama. This is a temporary split, not the end state — the goal is for both agents to be reachable from ALL channels through a unified gateway. See "TODO: Unified Multi-Agent Routing" below.

### Phase 6: Commit + Polish (22:15–22:55)
16. **Committed messaging gateway** — `b5028dc`, 11 files, 1828 insertions
17. **Fixed Polygon 429** — wired sync PriceCache + token-bucket rate limiter (4 calls/min) into PolygonDataConnector. Committed: `f7a7305`
18. **Dashboard online** — built Next.js, added to PM2 ecosystem, verified HTTP 200. Committed: `d5a116a`

---

## 2. Files Created or Modified — Full Paths

### NEW FILES (created this session)
| File | Purpose |
|------|---------|
| `engine/services/agent_gateway.py` | SharedAgentGateway, OllamaAgentAdapter, CliAgentAdapter, GatewaySessionStore, JSON parser with `raw_decode`, `/model list`+`set` commands |
| `engine/services/telegram_poller.py` | Telegram long-polling service. Deletes webhooks, polls getUpdates every 30s, routes through gateway, sends replies. Allowlist checks both chat_id and username. |
| `engine/services/messaging_health.py` | Periodic health monitor (60s interval). Checks Ollama, attempts auto-restart, sends Telegram alert on failure. |
| `engine/routers/messaging_router.py` | HTTP routes: POST /messaging/chat, GET /messaging/status, GET /messaging/health, POST /messaging/inbound/telegram, POST /messaging/inbound/whatsapp. Builds both adapters as OllamaAgentAdapter. Startup/shutdown hooks for TelegramPoller. |
| `engine/tests/test_agent_gateway.py` | 5 unit tests: default routing, explicit prefix override, allowlist blocking, session isolation, reset behavior |
| `docs/plans/2026-04-16-always-available-messaging-roadmap.md` | Full roadmap doc with architecture diagram, task details, and success criteria |

### MODIFIED FILES (changed this session)
| File | What Changed | Why |
|------|-------------|-----|
| `engine/main.py` | Added lifespan hooks: `start_messaging_services()` before yield, `stop_messaging_services()` after yield. Added APScheduler job for `messaging_health.run_health_check` (60s). | Wire Telegram poller and health monitor into engine lifecycle |
| `engine/notifications/telegram.py` | Added `send()` method to TelegramNotifier for bidirectional replies | Poller needs to send replies back to Telegram chat |
| `engine/notifications/whatsapp.py` | Added `send_whatsapp_message()` convenience function | Reply path for WhatsApp inbound messages |
| `engine/notifications/openclaw_notifier.py` | Added `send_whatsapp_message()` backward-compat alias | Messaging router imports it for WhatsApp reply fallback chain |
| `engine/config.py` | Added Settings fields: MESSAGING_*, TELEGRAM_*, HERMES_*, OPENCLAW_*, OLLAMA_BASE_URL | Configuration surface for the messaging gateway |
| `engine/.env.example` | Added all messaging env vars with documentation | Template for new installs |
| `engine/.env` | Added messaging env vars. Fixed OPENCLAW_LOCAL_MODEL (removed `ollama/` prefix). Set HERMES_LOCAL_MODEL=qwen2.5:7b. | Runtime config |
| `engine/data/market_data.py` | Added rate limiter (4 calls/min) + sync cache (60s TTL) to PolygonDataConnector. 429 returns expired cache. | Fix Polygon 429 rate limiting |
| `engine/ecosystem.config.js` | Added `jarvis-dashboard` PM2 app block (pnpm start, port 3010, production mode) | Dashboard persistence |

### WSL CONFIG CHANGES (not in git)
| File | What Changed |
|------|-------------|
| `/root/.hermes/config.yaml` | `provider: custom`, `default: qwen2.5:7b`, `base_url: http://localhost:11434/v1` |
| `/root/.hermes/.env` | `LLM_MODEL=qwen2.5:7b`, `HERMES_INFERENCE_PROVIDER=custom`, `OPENAI_BASE_URL=http://localhost:11434/v1` |
| `/root/.openclaw/openclaw.json` | Updated to 2026.4.15. Local Ollama provider, WhatsApp enabled |

---

## 3. Current State — What's Running, Stopped, Broken

### Running
| Service | Port | Details |
|---------|------|---------|
| **JARVIS Engine** | 8010 | PM2 managed, health=ok, paper mode, kill_switch=inactive |
| **Dashboard** | 3010 | PM2 `jarvis-dashboard`, Next.js 15.3.0 production, HTTP 200 |
| **Ollama** | 11434 | 6 models: qwen2.5:7b (active), hermes3, gpt-oss:20b, qwen2.5-coder:32b, llama3.3, nomic-embed-text |
| **OpenClaw Gateway** | 18789 | v2026.4.15, probe=ok, WhatsApp connected (+16128771189) |
| **Telegram Poller** | — | Engine background task, polling @HermesAmoBot every 30s |
| **Health Monitor** | — | APScheduler job checking Ollama every 60s |

### Stopped (intentionally)
| Service | Why |
|---------|-----|
| **Hermes Gateway (WSL)** | Was stealing Telegram updates (same bot token). Must stay stopped until we create a second bot or unify the architecture. |

### Known Issues
| Issue | Severity | Details |
|-------|----------|---------|
| Telegram not tested E2E from phone | Low | Poller works, API verified. User needs to press Start on @HermesAmoBot |
| OpenClaw WSL→Ollama timeouts | Medium | `Headers Timeout Error` for WhatsApp responses via OpenClaw gateway |
| 55 uncommitted files from prior sessions | Debt | Needs triage into logical commits |
| Both agents use direct Ollama (no agent features) | Design debt | See TODO #1 below |

---

## 4. In-Progress Work

### Telegram E2E Verification
- Poller running, bot verified via getMe. Zero messages received.
- **Next:** User opens Telegram → @HermesAmoBot → Start → send message

### Uncommitted Prior Work (55 files, 3218 insertions)
- debate.py, pipeline.py, llm/client.py, ic_ensemble.py, openclaw_router.py, portfolio_router.py, stop_loss tests, etc.
- **Next:** Triage into logical commits (safety fixes, feature wiring, test additions)

---

## 5. Blockers Discovered

### Blocker 1: Agent CLI System Prompts Overwhelm 7B Model
Both Hermes (92 skills, 31 tools) and OpenClaw (35K-char workspace) inject massive system prompts that cause qwen2.5:7b to hang or produce irrelevant output (240s+ timeout).
- **Current workaround:** Direct Ollama HTTP, bypassing CLIs entirely
- **To restore agent features:** Use a larger model (gpt-oss:20b needs ~13GB RAM) or reduce system prompt size

### Blocker 2: Telegram Bot Token Shared
@HermesAmoBot token is used by engine poller AND Hermes/OpenClaw gateways. Only one consumer can poll `getUpdates`.
- **Current:** Engine has exclusive Telegram, OpenClaw has WhatsApp
- **To fix:** Create second Telegram bot, or build a shared message broker

### Blocker 3: ngrok Not Configured
Blocks webhook-based integrations. Not needed for current polling+native approach.

---

## 6. Key Decisions Made

| Decision | Choice | Tradeoff | Reversible? |
|----------|--------|----------|-------------|
| Direct Ollama over CLIs | Both adapters call Ollama HTTP | No agent skills/memory/tools | Yes — change adapter type in messaging_router.py |
| Long-polling over webhooks | TelegramPoller uses getUpdates | Up to 30s latency vs instant | Yes — add webhook endpoint + tunnel |
| Channel separation | OpenClaw=WhatsApp, Engine=Telegram+API | Not unified yet | Yes — build message broker |
| Sync cache for Polygon | Module-level dict with TTL | Not shared across processes | Could upgrade to Redis later |
| 4 calls/min rate limit | Token bucket, not Polygon's 5 | 1 call/min headroom | Configurable via class attr |

---

## 7. TODO Items — The Full List

### TODO 1: Unified Multi-Agent Routing (HIGH PRIORITY)
**Goal:** OpenClaw and Hermes should work together, not just as separate routing targets.
- Add a `/both <message>` command that sends to BOTH agents and returns both responses
- Consider an "orchestrator" mode where OpenClaw handles planning/workspace and Hermes handles execution/learning
- Wire OpenClaw's WhatsApp messages through the engine gateway so all channels are unified
- Share session context between agents (e.g., OpenClaw's AGENTS.md knowledge available to Hermes)

### TODO 2: Restore Agent Features for Gateway
- Add a lightweight system prompt to the OllamaAgentAdapter (trading context, Matt's preferences)
- Experiment with gpt-oss:20b (13GB) — may handle full agent system prompts
- Consider streaming responses to reduce perceived latency

### TODO 3: Triage + Commit 55 Uncommitted Files
Group into logical commits:
- Safety: trade_invariants.py, _mixins_trades.py, portfolio_router.py, test_stop_loss_invariants.py
- Features: debate.py (advisor+IC wiring), pipeline.py (hidden pivots), llm/client.py (token proxy)
- Tests: test_routes_wired.py, test_llm_client.py, test_portfolio_paper_trade_post.py
- Data: paper_trades.json (maybe .gitignore this)
- Cleanup: delete .claude/agents/paperclip-*.md, .claude/commands/paperclip-*.md

### TODO 4: Telegram First Contact
- User presses Start on @HermesAmoBot
- Capture numeric chat_id from first message
- Update MESSAGING_ALLOWED_TELEGRAM_CHAT_IDS and TELEGRAM_CHAT_ID in .env

### TODO 5: Fix OpenClaw WhatsApp Timeout
- OpenClaw gateway gets `Headers Timeout Error` reaching Ollama from WSL
- May need to change Ollama URL in openclaw.json from localhost to Windows host IP (172.x.x.x)

### TODO 6: Operational
- Refresh Discord data (16 months stale)
- Smoke-test Bayesian optimizer after engine restart
- Consider adding lightweight system prompt to direct Ollama adapters

---

## 8. Git State

### Branch
```
feat/tradingview-mcp-gamma-kraken
```

### Recent Commits (this session's 3 at top)
```
d5a116a feat(infra): add jarvis-dashboard to PM2 ecosystem (port 3010)
f7a7305 fix(data): add rate limiter + cache to PolygonDataConnector
b5028dc feat(messaging): add always-available Telegram/WhatsApp gateway with Ollama backends
121d887 fix(tests): resolve 7 pre-existing test failures
659fd32 docs(session-log): handoff for tradingview-mcp + gamma + kraken session
126501f test(data): update waterfall test for Polygon futures blocklist
568bf47 docs(patches): stage CryptoMarketModule startup-wiring patch for later
4d83b47 fix(config): add missing CRYPTO_ENABLED + ENABLED_MARKETS + get_enabled_markets
115a0b6 feat(crypto): add KrakenAdapter + CRYPTO_BACKEND selector (paper-first)
030bd6f feat(tv): parse MY FREE GAMMA LEVELS overlay + gamma regime hints
21e0b86 docs(tradingview): add MCP setup guide + register kraken MCP server
fd02ccc fix(wfe): correct BacktestDataLoader constructor call in rolling scheduler
01e9345 feat(trader): wire ToolInspectionManager + Advisor gating
94c4793 fix(data): disable Polygon for futures + add port-conflict guardrail
05b939d chore(gitignore): ignore aider workspace files
7f1f0e0 refactor(approval): extract shared approval flow and enforce paper gate
1928322 docs(ops): add paper IB verification and market-data runbooks
1597130 fix(dashboard): prefer internal engine routing for local proxy health
3f94558 fix(health): report IB connectivity from execution connector path
30dee80 fix(dashboard): update pending approvals offline hint for proxy routing
```

### Uncommitted (55 files, 3218 insertions, 785 deletions)
```
 D .claude/agents/paperclip-*.md (8 files)
 D .claude/commands/paperclip-*.md (9 files)
 M .claude/task-manifest.json, .mcp.json, CLAUDE.md
 M engine/agents/{advisor_client,debate,pipeline,risk_manager}.py
 M engine/analytics/ic_ensemble.py (+158)
 M engine/api/{__init__,models}.py
 M engine/data/paper_trades.json (+2162)
 M engine/database/{_mixins_alerts,_mixins_trades,migrations}.py
 M engine/llm/{client,context_manager,cost_tracker,README}.py
 M engine/routers/{observability,openclaw,portfolio}_router.py
 M engine/scanner/signal_scanner.py
 M engine/tests/{test_config_validation,test_llm_client,test_portfolio_paper_trade_post,test_routes_wired,test_stop_loss_invariants}.py
 M engine/{dependencies,requirements-core,requirements}.{py,txt}
 M data/jarvis_trader.db (binary — NEVER commit)
?? .claude-backup-*/, .claude-stale/, .claude/agents/memory-curator.md
```

---

## Quick-Start for Next Session

```bash
# Verify all services
curl -s http://localhost:8010/health | python -m json.tool
curl -s -o /dev/null -w "Dashboard: %{http_code}\n" http://localhost:3010
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" \
  http://localhost:8010/messaging/health

# Test both agents via gateway
curl -s --max-time 60 -X POST \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"channel":"api","user_id":"matt","message":"/hermes What is 2+2?"}' \
  http://localhost:8010/messaging/chat

curl -s --max-time 60 -X POST \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"channel":"api","user_id":"matt","message":"/openclaw What is the MCL regime?"}' \
  http://localhost:8010/messaging/chat

# List available models
curl -s --max-time 15 -X POST \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"channel":"api","user_id":"matt","message":"/model list"}' \
  http://localhost:8010/messaging/chat
```

### Critical Constraints
- **Never `git add -A`** — 1,450+ GMS changes and 55 uncommitted files need triage
- **Hermes gateway MUST stay stopped** — it steals Telegram updates from the engine poller
- **`OPENCLAW_LOCAL_MODEL`** must NOT have `ollama/` prefix
- **Both adapters use direct Ollama** — not their CLIs (temporary workaround for 7B model limitations)
- **OpenClaw gateway handles WhatsApp only** — no Telegram plugin loaded
- **Polygon free tier = 5 calls/min** — rate limiter set to 4/min
- **`data/jarvis_trader.db`** is a 104MB binary — never commit it
- **OpenClaw and Hermes should work together** — current channel split is temporary, not the end state
