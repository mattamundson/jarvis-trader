# JARVIS TRADER — Stark Mode README

> **Note:** Some sub-deliverables (Hermes skills, parallel-agent tasks) may complete after
> this doc is written. The structure described here is stable; skill names and file paths
> are as-designed.

---

## TL;DR

- **JARVIS TRADER** is an AI-powered futures & options trading engine for MES/MGC/MCL on
  Interactive Brokers paper account DUP662235 (port 4002); live trading is Phase 3 and
  not yet active.
- **2026-05-20 shipped:** 86 commits across Discord deep-analyzer, QuantStats tearsheet
  endpoint, Kronos + ResearchAgent experimental stubs, `/admin/feature-flags` toggle,
  Hermes-upgrade agent framework, 7 new runbooks, and LLM Gemini fallback.
- **Start here:** `docs/runbooks/STARK_MODE_OPERATING_PHILOSOPHY.md` — three surfaces,
  five axioms, one source of truth.
- **7 runbooks** (see table in §5) cover every operational domain.
- **Claude Code** = deep work / code; **Hermes** = on-the-go / Telegram; **Dashboard** =
  ambient awareness at `http://127.0.0.1:3010`.
- **Kronos** (foundation-model regime classifier) and **ResearchAgent** are code-complete
  stubs wired into the pipeline, default off via `ENABLE_KRONOS=0` / `ENABLE_RESEARCH_AGENT=0`.
  Toggle live at `/admin/feature-flags`. Kronos threshold calibration is documented in
  `docs/runbooks/KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md`.
- **Branch:** `feat/tradingview-mcp-gamma-kraken` (HEAD `50f6a12`). Not yet pushed to
  `origin` — push requires explicit authorization.

---

## 1. What Shipped 2026-05-20

86 commits on `feat/tradingview-mcp-gamma-kraken`. Representative set by category:

### Discord Intelligence

| Commit | Description |
|---|---|
| `855fb0a` | Add bookmark weekly-delta synthesizer scaffold |
| `579c432` | Add P0 FAILED tier for broken-extract bookmarks |
| `d977ee8` | Add Discord-to-vault extraction script |
| `df3e470` | Add force-drain script for channel re-ingest with attachment backfill |
| `d7c3909` | Add Discord bookmark cross-link enrichment |
| `dcc494d` | Ingest attachment-only messages + persist attachment_urls |
| `de5e43b` | Path B — capture Discord attachments on ingest |
| `b2cffad` | Implementation plan for autonomous deep analyzer |
| `e8ed881` | Deep-analyzer runner (Phase 1 text-only end-to-end) |
| `05e9b1c` | Deep-analyzer image handler (vision LLM) |
| `d572897` | Deep-analyzer audio handler (faster-whisper local) |
| `ddd5421` | Deep-analyzer document handler (PDF extract + LLM) |
| `aa1c8a6` | Deep-analyzer URL handler (readability + X-post fallback) |
| `5009a95` | Add XPostHandler using fxtwitter for JS-free X.com fetch |
| `437d1f0` | Add personal-channel MCP server with live REST tools |
| `44f8260` | Add MCP tools for bookmark channel queries |
| `9d01b06` | Add HTTP routes for bookmark feed |
| `9b3d02f` | Deep-analyzer scheduled-task wrappers + installer |
| `1d0c7c0` | Deep-analyzer daily digest writer + Hermes DM |

### QuantStats & Reports

| Commit | Description |
|---|---|
| `c80a9ca` | Add `/reports/quantstats` endpoint with metrics blob |
| `df6600b` | Pin quantstats in requirements-core.txt |
| `250b25a` | Wire reports_router into main.py |

### Kronos + ResearchAgent (Experimental Analysts)

| Commit | Description |
|---|---|
| `bbf3b4c` | Add Kronos foundation-model classifier stub |
| `b0cc58c` | Add QuantAgent research-agent stub |
| `6395081` | Add experimental analyst env flags |
| `7d3964b` | Wire Kronos classifier into pipeline `_run_analysts()` |
| `518eb26` | Wire ResearchAgent into `StrategyTuner.generate_hypothesis` |
| `5bc6e1e` | Align Kronos stub interface with paper schema; lazy-init in pipeline |
| `693eb4f` | Add `/admin/feature-flags` route for runtime toggle |
| `e72ae23` | Lock Kronos input schema verified from paper |

### Dashboard

| Commit | Description |
|---|---|
| `051ffe1` | Add QuantStatsPanel with portfolio tearsheet |
| `ea07d90` | Add QuantStatsMetrics + fetchQuantStats to api.ts |
| `b229e02` | Add BookmarkFeedPanel for #general bookmark feed |
| `6fcc57a` | Add BookmarkRow + recent/search helpers to api.ts |
| `43673fe` | Null-safe action/side lowercasing in 3 widgets |

### Hermes Upgrade Framework

| Commit | Description |
|---|---|
| `084043f` | Add backlog generator + CLI (Phase 2) |
| `59410a7` | Add applier orchestrator + audit log (Phase 3 core) |
| `5592200` | Add skill_installer + mcp_adder appliers |
| `f7145c1` | Add library_integrator + config_patcher appliers |
| `4012cf0` | Export all 6 appliers from package `__init__` |
| `7108bec` | Apply certifi SSL_CERT_FILE fallback before LLM import |
| `1985d5e` | Load engine/.env in CLI so ANTHROPIC_API_KEY is set |
| `50f6a12` | Add nightly Hermes upgrade scanner wrapper + task |

### LLM Routing & Health

| Commit | Description |
|---|---|
| `184e612` | Add Gemini fallback for Anthropic credit-exhaustion |
| `4deb1a9` | Phase 3.1 — route 3 direct-Anthropic sites via JarvisLLMClient |
| `6785670` | Add `/fast` `/deep` `/code` model-profile commands to agent-gateway |
| `b00beaa` | Surface `brier_30d_rolling` in `/health` payload |
| `581024d` | Add pm2 restart-rate instability alerting to health-watchdog |

### Safety & Tests

| Commit | Description |
|---|---|
| `9903a9a` | `[safety-review]` fix(risk): regime_guard DataFrame-aware + NaN/schema guards |
| `608585d` | `[safety-review]` test(risk): cover regime_guard + protections invariants |
| `80c043c` | test(messaging): cover STATUS / PNL / POSITIONS / CONFIRM CLEAR commands |
| `123e00e` | fix(tests): repair test_inference_router async hang blocking full suite |
| `a68df9b` | Refresh MES R11 + MGC R4 gate v2 verdicts to 2026-05-20 |

### Runbooks (7 new docs)

| Commit | Description |
|---|---|
| `f7e89ec` | Add second-brain vault operations runbook |
| `c9f4be0` | Add Kronos + ResearchAgent operations runbook |
| `4558388` | Add QuantStats tearsheet operations runbook |
| `93d03e6` | Add Discord intelligence runbook |
| `a4c9fc0` | Add `/discord/briefing` composed-endpoint runbook |
| `299028e` | Add Claude Code + Hermes integration map |
| `1926a8a` | Cross-link DISCORD_INTEL_RUNBOOK to new briefing runbook |

---

## 2. The Three Control Surfaces

```
                          ┌─────────────────────────┐
                          │     JARVIS TRADER        │
                          │  engine:8010             │
                          │  SQLite jarvis_trader.db │
                          │  vault: second-brain/raw │
                          └──────────┬───────────────┘
                                     │
       ┌─────────────────────────────┼────────────────────────────┐
       │                             │                            │
  Claude Code                    Hermes                      Dashboard
  (desk, deep work)         (phone, on-the-go)           (couch, ambient)
       │                             │                            │
  mcp__discord-jarvis__*    aiohttp → /discord/...       SWR → /reports/...
  mcp__discord-personal__*  aiohttp → /reports/...       page /jarvis
  Bash → engine routes      ~/.hermes/skills/jarvis-*    page /performance
  direct vault read/write   scheduled Hermes crons       page /
  subagents: pipeline-      /jarvis/ask (Telegram)
    debugger, backtest-     Hermes-upgrade agent
    runner, safety-reviewer
```

**gbrain** is the unifying memory layer — not a fourth surface. Every surface writes
signals, verdicts, and intel into `master-jarvis/second-brain/raw/`; gbrain embeds and
indexes them. The dashboard reads `/reports/`; Hermes reads the same. The vault is what
persists across restarts.

---

## 3. Day 1 After a Reboot — Five Steps

**Step 1 — Orient (Claude Code session)**

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
git status
```

Read `~/.claude/handoffs/MASTER_HANDOFF_<latest>.md`, then the most recent
`docs/session-logs/HANDOFF_*.md`.

**Step 2 — Confirm engine is up**

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health | ConvertTo-Json -Depth 4
```

Pass criteria: `status=ok`, `tradingview_mcp_healthy=true`, `llm_path_healthy=true`.
If not up: `.\restart_engine.ps1` (steady-state startup ≈ 229s).

**Step 3 — Open the dashboard**

Navigate to `http://127.0.0.1:3010/jarvis` (Stark page). Confirm QuantStatsPanel
and BookmarkFeedPanel are loading. If the dashboard process is not running:

```powershell
~/scripts/start-dashboard.ps1
```

**Step 4 — Confirm scheduled tasks are active**

```powershell
schtasks /Query /TN "Jarvis-DiscordAutoImport" /V /FO LIST | Select-String "Status|Next Run"
schtasks /Query /TN "Jarvis-VaultGbrainSync" /V /FO LIST | Select-String "Status|Next Run"
```

Both should show `Status: Ready` and a plausible next run time.

**Step 5 — Morning brief (if Hermes is reachable)**

Send `jarvis brief` via Telegram → Hermes dispatches `jarvis-morning-brief` skill →
engine `/discord/briefing` → summary DM back.

If anything is unclear about surface roles or workflow, read
`docs/runbooks/STARK_MODE_OPERATING_PHILOSOPHY.md` first.

---

## 4. The 7 Runbooks — Navigation Hub

| Runbook | When to read |
|---|---|
| [`STARK_MODE_OPERATING_PHILOSOPHY.md`](runbooks/STARK_MODE_OPERATING_PHILOSOPHY.md) | Always — read first on any new session |
| [`CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP.md`](runbooks/CLAUDE_CODE_AND_HERMES_INTEGRATION_MAP.md) | When deciding which surface to use for a task |
| [`DISCORD_INTEL_RUNBOOK.md`](runbooks/DISCORD_INTEL_RUNBOOK.md) | Any Discord-related work: signals, bookmarks, deep-analyzer |
| [`DISCORD_BRIEFING_RUNBOOK.md`](runbooks/DISCORD_BRIEFING_RUNBOOK.md) | Pre-session prep workflow, `/discord/briefing` endpoint |
| [`KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md`](runbooks/KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md) | Before toggling experimental analyst flags or calibrating thresholds |
| [`QUANTSTATS_TEARSHEET_RUNBOOK.md`](runbooks/QUANTSTATS_TEARSHEET_RUNBOOK.md) | Portfolio analytics, tearsheet refresh, Sortino/Sharpe interpretation |
| [`SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK.md`](runbooks/SECOND_BRAIN_VAULT_OPERATIONS_RUNBOOK.md) | Vault ops, gbrain sync, force-drain, peer-session coordination |

---

## 5. The 9 Hermes Skills

Skills live at `~/.hermes/skills/`. Deployment via Hermes-upgrade agent (shipped today);
individual skill files may still be deploying when this doc was written.

| Skill | Trigger | What it does |
|---|---|---|
| `jarvis-morning-brief` | 5:30am CT cron | Daily situation report: regime, pipeline, positions, P&L |
| `jarvis-discord-bookmarks` | On-demand | Query bookmark feed from Discord #general |
| `jarvis-quantstats-tearsheet` | 4:15pm CT weekday | Refresh portfolio tearsheet from `/reports/quantstats` |
| `jarvis-pipeline-status` | On-demand | Latest pipeline verdict for all active instruments |
| `jarvis-regime-check` | On-demand | Current market regime + Kronos confidence (if enabled) |
| `jarvis-kill-switch-status` | On-demand | Safety layer state: daily P&L, drawdown, halt flags |
| `jarvis-positions` | On-demand | IBKR paper positions + paper account summary |
| `jarvis-paper-roi` | On-demand | 30-day win rate, Sortino, open drawdown |
| `jarvis-self-review` | 11pm CT | Aggregate `/jarvis/ask` log; surface patterns, flag anomalies |

---

## 6. What Is Not Done Yet

| Item | Status | Gate |
|---|---|---|
| Kronos `from_pretrained` wire-up | Stub only — returns `{"regime":"neutral","confidence":0.0}` | Threshold calibration result from `KRONOS_AND_RESEARCH_AGENT_RUNBOOK.md` |
| ResearchAgent real LLM call | Stub only — returns placeholder hypothesis | Cost-budget gates must be live first |
| `/admin/feature-flags` Kronos lazy-init verified in prod | Implemented, not smoke-tested under load | Engine restart + flag toggle test |
| HF Inference / GPU path for Kronos | Not scoped | Decision: GPU host vs API inference |
| Hermes skills deployed to `~/.hermes/skills/` | Hermes-upgrade agent scheduled; may not have run yet | `ls ~/.hermes/skills/jarvis-*` to verify |
| Live trading transition (Phase 3) | Separate roadmap; `LIVE_TRADING_ENABLED = False` hardcoded | Gate v2 pass on all instruments + capital allocation decision |

---

## 7. Cross-Links

Vault wiki entries (open in Obsidian or search gbrain):

- `[[discord-jarvis-mcp]]` — MCP tool reference for `mcp__discord-jarvis__*`
- `[[discord-personal-mcp]]` — personal-channel MCP tools shipped today
- `[[hermes-agent-army-cheatsheet]]` — Hermes skill invocation reference
- `[[discord-extraction-master-index]]` — all Discord → vault extraction runs
- `[[gbrain-trading-brain]]` — current embedding stats, chunk count, sync schedule
- `[[stark-mode-philosophy]]` — mirror of STARK_MODE_OPERATING_PHILOSOPHY.md for vault

Engine API quick-reference:

- `GET /health` — system health gate (see `docs/runbooks/HEALTH_API_CONTRACT.md`)
- `GET /reports/quantstats` — portfolio metrics blob (new today)
- `GET /discord/bookmarks/recent` — bookmark feed (new today)
- `GET /discord/briefing` — composed pre-session report (new today)
- `POST /admin/feature-flags` — toggle Kronos / ResearchAgent at runtime (new today)
- `GET /brokers/positions` — live position state (diverges from `/health` — check both)

Project-level canonical docs:

- `docs/JARVIS_TRADER_UNIFIED_CANON.md` — architecture source of truth
- `docs/CURRENT_STATE.md` — latest P0/P1/P2 status
- `CLAUDE.md` (project root) — non-negotiable rules, port map, dev quick-start

---

*Written 2026-05-20. Branch `feat/tradingview-mcp-gamma-kraken` HEAD `50f6a12`. Not pushed.*
