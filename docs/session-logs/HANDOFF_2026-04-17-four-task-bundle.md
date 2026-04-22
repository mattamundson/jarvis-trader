# Session Handoff — Four-Task Bundle (Triage + /both + OpenClaw Timeout + Discord)
**Date:** 2026-04-16 23:12 CDT → 2026-04-17 00:00 CDT
**Branch:** `feat/tradingview-mcp-gamma-kraken` (pushed, synced)
**Plan file:** `C:\Users\mattm\.claude\plans\write-c-users-mattm-thinkorswim-jarvis-rustling-ullman.md`

---

## What shipped

### 1. Git triage — 13 commits, clean working tree

In commit order:

| SHA | Subject |
|---|---|
| `0d067f2` | `chore(gitignore): lock down secrets, legacy DB stub, and dev scratch` |
| `2eecb94` | `chore: remove stale paperclip agent/command scaffolding` (−490 lines) |
| `6eeda1b` | `feat(pipeline): wire tail-risk researcher + Brier calibration + LLM client updates` |
| `6fd0ad2` | `refactor(routers): extract approval flow from openclaw_router + scanner pause fix` |
| `dafc097` | `test: cover new feature wiring (config, LLM client, portfolio, route-wiring)` |
| `c6e1073` | `feat(rl): commission-aware reward (TensorTrade PBR, ML/AI Novel #3)` |
| `b01912b` | `feat(db): migrations 020 (supervisor_decisions) + 021 (paper_trades stop/tp)` |
| `d1bd31b` | `chore(deps): add google-genai 1.72.0 (Gemini / Vertex AI SDK)` |
| `d99fad4` | `docs + mcp: add chrome-devtools + markitdown MCP servers, refresh docs` |
| `8c21b13` | `chore: untrack .claude/task-manifest.json (per-session local state)` |
| `456e8a5` | `chore: untrack engine/data/paper_trades.json + session_memory.json` |
| `81a9249` | `feat(messaging): add /both command for parallel Hermes+OpenClaw dispatch` |
| `eb7b2b5` | `docs(troubleshooting): document OpenClaw LLM idle timeout fix (300s)` |

Additionally a parallel Claude process committed `1c97ccb` (Polygon T1.5 audit) and `0b0bd1a` (its own handoff) mid-session — both clean, no conflicts.

### 2. Unified multi-agent `/both` command
`engine/services/agent_gateway.py` — `SharedAgentGateway._dispatch_both` fans out one prompt to Hermes AND OpenClaw in parallel (`asyncio.gather` with `return_exceptions=True`), merges replies under `**OpenClaw:** … **Hermes:** …` headers, preserves the single-AdapterResponse contract so Telegram/WhatsApp paths need zero changes.

Live smoke tested:
```
POST /messaging/chat  {"message":"/both What is 2+2?..."}
→ "**Openclaw:** The sum of 2 and 2 is 4.\n\n**Hermes:** 2 + 2 equals 4."
   health_state=ok  backend=gateway-both
```

4 new tests in `engine/tests/test_agent_gateway.py` (9 total, all pass).

### 3. OpenClaw WhatsApp "Headers Timeout" — **ROOT-CAUSED AND FIXED**
Misdiagnosed in prior handoff as a network issue. Real cause: `agents.defaults.llm.idleTimeoutSeconds` defaulted to **120s**, but qwen2.5:7b on CPU with OpenClaw's ~35K-char system prompt often takes longer than 120s to emit its first token — watchdog aborts, falls through to `surface_error`.

Fix applied in WSL (change NOT in git — lives in `/root/.openclaw/openclaw.json`):
```bash
wsl -d Ubuntu -e openclaw config set agents.defaults.llm.idleTimeoutSeconds 300
wsl -d Ubuntu -e systemctl --user restart openclaw-gateway
```
Backup saved to `/root/.openclaw/openclaw.json.bak-<timestamp>`. Documented in `docs/troubleshooting.md`.

### 4. Discord refresh — pipeline verified healthy
- `python -m discord.cli` ran clean, all files processed, **0 new rows** (idempotent — DB already covers the April 2 export)
- `python -m scripts.nightly_discord --etl-only` finished in 57.5s, 997/997 sentiment dates stored
- `GET /discord/corey-alerts` returns data

**Finding:** Corey stopped posting alerts after 2024-12-31. The "stale Discord data" isn't a pipeline bug — it's an upstream source that went quiet 15 months ago. The `created_at: 2026-04-06` is when rows were last imported, not when Corey posted.

---

## Files created

- `docs/session-logs/HANDOFF_2026-04-17-four-task-bundle.md` (this file)
- `docs/troubleshooting.md` — new section "OpenClaw 'Headers Timeout Error' / no-reply on WhatsApp"

## Files modified

- `.gitignore` — added secrets patterns, legacy DB paths, dev scratch, dashboard buildinfo
- `engine/services/agent_gateway.py` — `/both` command + `asyncio` import
- `engine/tests/test_agent_gateway.py` — 4 new tests (+ RaisingAdapter helper)
- `/root/.openclaw/openclaw.json` (WSL, not in git) — `llm.idleTimeoutSeconds: 120 → 300`

---

## Current state (2026-04-17 00:00 CDT)

| Service | Port | Status |
|---|---|---|
| JARVIS Engine | 8010 | ok, paper mode, kill_switch inactive |
| Dashboard | 3010 | ok |
| Ollama | 11434 | 6 models including qwen2.5:7b |
| OpenClaw Gateway | 18789 | active (WSL systemd), restarted with 300s idle timeout |
| Telegram Poller | — | background task |

**Tests:** 1720 passed / 15 failed (ALL pre-existing — 5 middleware + 5 prices_router + 4 prices_router_offline + 1 exception_handler; unchanged from session start) / 65 skipped / 1 xfailed

**Git:** clean working tree. Branch `feat/tradingview-mcp-gamma-kraken` pushed and synced with origin.

---

## Blockers found and unblocked

| Blocker | Status | Notes |
|---|---|---|
| "DB is 0 bytes" (handoff said restore from backup) | **Dismissed** | Canonical DB is `engine/data/jarvis_trader.db` (131 MB, healthy). Repo-root `data/jarvis_trader.db` was a legacy stub — the split-brain the 2026-04-10 `_resolve_sqlite_db_path` validator was written to prevent. Stub deleted + gitignored. |
| "OpenClaw Headers Timeout" (network) | **Root-caused** | Network fine; LLM idle watchdog at 120s. Bumped to 300s. |
| "Discord data 16 months stale" | **Explained** | Corey stopped posting 2024-12-31; pipeline is healthy. Need external Discord re-export to get any NEW content, but there may not be any to get. |

---

## Open TODOs (carry-forward)

### High-priority
1. **Larger untracked tree cleanup** — still sitting: `.claude/commands/jarvis-*.md` (9 files), `.claude/skills/{agent-debate-explain,backtest-report,pm2-doctor}/`, `.claude/hooks/`, `.github/workflows/{claude-pr-review,safety-invariant-check}.yml`, `.devcontainer/`, `docs/digest/`, `docs/runbooks/*.md`, 5 `Jarvis-Trader-SessionHighlights*.md` scratch files. **These are NEW assets from Matt's Claude sessions** — need his triage to decide commit vs ignore.
2. **Supervisor integration** — migration 020 ships the `supervisor_decisions` table, but the runtime supervisor gating code isn't merged yet. Follow-up session should wire `supervisor_router.py` if that's the pattern direction.
3. **PRAW Reddit swap** — still the outstanding 4-6hr task per MEMORY.md (dependency pre-installed, social_analyst.py needs refactor).

### Medium-priority
4. **Tail-risk researcher live test** — shipped behind `TAIL_RISK_RESEARCHER_ENABLED` env flag (default off). No in-production signal yet. Flip flag on a single paper-only pipeline run to validate.
5. **Brier calibration wiring** — `BrierCalibrationTracker` class added to `ic_ensemble.py` but not wired into `debate.py`. Needs a second commit to call it alongside `ICWeightedEnsemble`.
6. **Migration 021 deployment** — `paper_trades.stop_loss` and `take_profit` columns will auto-add on next engine startup via the MIGRATIONS registry. No action needed unless a fresh DB is being spun up.

### Security note
**`/root/.openclaw/agents/main/agent/models.json` contains a live OpenAI project key in plaintext.** Matt should rotate this key and move to a ref/provider pattern (`openclaw config set ... --ref-source env --ref-id OPENAI_API_KEY`). Not touched this session (out of scope).

---

## Decisions made

| Decision | Why | Reversible? |
|---|---|---|
| `/both` returns merged single-string reply, not union type | Preserves `AdapterResponse` contract; Telegram/WhatsApp code paths need zero changes | Yes — swap to new type in future commit |
| Bucket Phase 2 commits per domain (safety / feature-wiring / routers / tests / deps / docs / RL / DB) | Easier to `git revert` a single domain without churning the others | N/A |
| Untrack `engine/data/paper_trades.json` + `engine/learning/data/session_memory.json` instead of committing | Both in .gitignore since 2026-04-10 as "session-specific, never commit" | `git add -f <path>` to re-track |
| Keep `/root/.openclaw/openclaw.json.bak-*` backups in WSL | Cheap rollback safety | Manual `rm` when stale |
| OpenClaw `maxConcurrent` left at 2 | `idleTimeoutSeconds` bump is the narrower fix; drop to 1 only if 300s still insufficient | Yes — one config change |

---

## Quick-start for next session

```bash
# Health sweep
curl -s http://localhost:8010/health | python -m json.tool
curl -s -o /dev/null -w "Dashboard: %{http_code}\n" http://localhost:3010
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" \
  http://localhost:8010/messaging/health

# Test /both live
curl -s --max-time 180 -X POST \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"channel":"api","user_id":"matt","message":"/both What is the MCL regime?"}' \
  http://localhost:8010/messaging/chat | python -m json.tool

# OpenClaw idle timeout check (fix applied 2026-04-17)
wsl -d Ubuntu -e openclaw config get agents.defaults.llm.idleTimeoutSeconds  # expect 300
wsl -d Ubuntu -e systemctl --user is-active openclaw-gateway                 # expect active

# Verify Discord pipeline
engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db').cursor(); c.execute('SELECT MAX(created_at) FROM discord_corey_alerts'); print(c.fetchone())"
```

### Critical constraints (unchanged)
- **Never `git add -A`** — still 40+ untracked files from Matt's prior sessions
- **Canonical DB is `engine/data/jarvis_trader.db`** — not repo-root `data/jarvis_trader.db` (deleted this session)
- **Hermes gateway MUST stay stopped** — would steal Telegram updates from engine poller
- **Both messaging adapters still use direct Ollama** (not CLIs) — temporary workaround for 7B model + massive system prompts
