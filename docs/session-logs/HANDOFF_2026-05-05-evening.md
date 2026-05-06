# JARVIS TRADER — Session Handoff
# Date: 2026-05-05 (evening session)
# Branch: feat/tradingview-mcp-gamma-kraken
# Written for: next AI session to continue without context loss

---

## 1. Session Summary — What Was Accomplished, In Order

This session began as a continuation of a compacted context (LLM C2+C3 Ollama hot-path validation was the final pre-compaction task). After compaction, the following work was executed in order:

**Phase A — Top-10 ROI task list created and authorized**
- User asked for a ranked top-10 ROI task list with subtasks. List was generated and user authorized full autonomous execution ("do not stop until all are complete").

**Phase B — Task 9: Boot-log fix (commit 8c75168)**
- `restart_engine.ps1` non-PM2 path was logging to nowhere. Fixed to redirect stdout/stderr to `engine/logs/engine-boot.log` and `engine/logs/engine-boot-error.log` using `Start-Process -RedirectStandardOutput/-RedirectStandardError`.

**Phase C — Task 1: GPU detection (closed, no-op)**
- Engine config checked for GPU/CUDA. Machine has Intel integrated graphics only — no NVIDIA, no CUDA. Ollama runs CPU-only. This is the root cause of 180s latency. No action taken (can't add a GPU via software).

**Phase D — Task 3: Per-agent model routing (commit d8d3822)**
- Added `OLLAMA_MODEL_PER_AGENT` environment variable to `engine/llm/client.py`.
- Uses `=` as agent/model separator (safe for Ollama `model:tag` colon notation), comma-separated.
- `social_analyst` and `news_analyst` routed to `llama3.2:3b`; all other agents stay on `hermes3:latest`.
- Wired `engine/.env` lines 353–357 with routing config.

**Phase E — Task 7: `/health/llm` observability endpoint (commits 6430e64 + 394c2a2)**
- New endpoint added to `engine/routers/health_router.py`.
- Reads `engine/data/llm_costs.db` (SQLite), computes p50/p95 latency per model over last 1h and 24h.
- Exposes `anthropic_fallback_active`, `latency_warning`, `cost_warning` flags.
- 30-second TTL cache to avoid hammering SQLite.
- **Bug found and fixed:** SQLite `datetime('now', '-1 hour')` produces space-separated timestamp (`2026-05-05 17:38:04`) while stored rows use ISO-T format (`2026-05-05T17:38:04`). String comparison was wrong (`T`=84 > space=32 in ASCII), causing all rows to match. Fixed with `strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour')`.
- **Auth bug found and fixed (commit 394c2a2):** `/health/llm` returned 401. `EXEMPT_PATHS` in `auth.py` only had bare `/health` and `/health/full`. Added all health sub-endpoints.

**Phase F — Task 10.1: pip-freeze snapshot**
- `engine/requirements-frozen-2026-05-05.txt` generated from current venv (262 packages). Committed with auth fix.

**Phase G — Task 2: pm2 persistence**
- Ran `pm2 save` → wrote `~/.pm2/dump.pm2` snapshot.
- Created `~/scripts/install-pm2-atlogon-task.ps1` and registered `Jarvis-PM2-AtLogon` scheduled task.
- Task fires `pm2 resurrect` at user logon, no admin elevation required.
- **PS1 em-dash bug hit:** `—` in error message caused PS 5.1 parse error. Fixed by replacing with `-`.

**Phase H — Task 8: Branch triage (partial)**
- Local `master` was fast-forward merged to feat tip (`394c2a2`) locally.
- `git push origin master` rejected — `origin/master` has 1 diverged commit (`4d99ef3`, Apr 22 2026, 2,194 files, a massive merge commit "JARVIS Strategy C+ v3 Phase 3+4"). This commit is NOT in the feat branch.
- Action: backed off, stayed on feat. Divergence requires Amo's decision. (See Blockers section.)

**Phase I — Task 5.1: Gate v2 snapshot (read-only)**
- Read all 4 verdict JSON files. Only MES_trend passes (via ALT routing). MCL, MNQ_breakout, MNQ_trend all FAIL. Details in section 6.

**Phase J — Task 10.4: DR Runbook**
- Created `~/scripts/RECOVERY_RUNBOOK.md` with 5 disaster scenarios (full rebuild, venv corruption, .env lost, Ollama evicted, pm2 died).

**Phase K — Task 10.3 + 10.6: DR backup**
- Created `~/scripts/dr-backup.ps1` (backs up `llm_costs.db`, regenerates requirements-frozen, auto-purges >90-day-old backups).
- Registered `Jarvis-DR-Weekly` scheduled task (Sundays 03:00, user-level, Status=Ready, NextRun=2026-05-10).

**Phase L — 1Password alternative**
- User raised friction with 1Password CLI in automated sessions.
- Created `~/scripts/manage-jarvis-secrets.ps1` — Windows Credential Manager wrapper with `-Set/-Get/-List/-Export` operations.
- Updated `RECOVERY_RUNBOOK.md` A2 step to show Credential Manager as Option A, 1Password as fallback.

---

## 2. Files Created or Modified — Full Paths, What Changed, Why

### Modified (committed to feat branch)

| File | Commit | Change | Why |
|---|---|---|---|
| `restart_engine.ps1` | `8c75168` | Added `-RedirectStandardOutput`/`-RedirectStandardError` to `Start-Process` in non-PM2 boot path | Boot logs were going nowhere; hard to debug silent failures |
| `engine/llm/client.py` | `d8d3822` | Added `ollama_model_per_agent` dict, per-agent routing in `call()`, model param threading into `_call_ollama` | Route cheap social/news agents to llama3.2:3b (faster on CPU) |
| `engine/.env` | `d8d3822` | Added lines 353-357: `OLLAMA_KEEP_ALIVE=24h`, `OLLAMA_MODEL_PER_AGENT=social_analyst=llama3.2:3b,news_analyst=llama3.2:3b` | Wire per-agent routing config |
| `engine/routers/health_router.py` | `6430e64` | New `/health/llm` endpoint with SQLite cost-DB query, p50/p95 latency, flags, 30s cache | Observability — need to see if Anthropic fallback is active or latency is spiking |
| `engine/middleware/auth.py` | `394c2a2` | Added `/health/llm`, `/health/watchdog`, `/health/pm2`, `/health/apis` to `EXEMPT_PATHS` | All health sub-endpoints were returning 401 |
| `engine/requirements-frozen-2026-05-05.txt` | `394c2a2` | New file — 262-package pip freeze snapshot | DR baseline; restore after venv corruption |

### Modified (uncommitted — working tree dirty)

| File | Change | Status |
|---|---|---|
| `engine/backtest/meanrev_signals.py` | +27 lines: new `rv_band` regime gate mode (realized volatility band filter), `rv_min/rv_max/rv_lookback` params added to `_build_regime_gate()` and `generate_bollinger_rsi_signals()` | Uncommitted — part of MCL Hypothesis C test (see below) |
| `engine/backtest/run_mcl_hypothesis_c.py` | New untracked file — script that ran the MCL Hypothesis C backtest (rv_band gate) | Uncommitted |

### Created (outside repo, not version controlled)

| File | Why |
|---|---|
| `~/scripts/install-pm2-atlogon-task.ps1` | Registers `Jarvis-PM2-AtLogon` scheduled task; idempotent |
| `~/scripts/RECOVERY_RUNBOOK.md` | DR playbook for 5 failure scenarios |
| `~/scripts/dr-backup.ps1` | Weekly backup: llm_costs.db + requirements-frozen regeneration |
| `~/scripts/manage-jarvis-secrets.ps1` | Windows Credential Manager wrapper (replaces 1Password CLI friction) |

---

## Ralph Loop Extension (2026-05-05 late evening)

All 6 user stories queued for the ralph loop were completed. Summary:

**US-001 — MCL Hypothesis C committed**
- Commit was already present (31ef7c6 with rv_band gate code)
- `gate_v2_verdicts/MCL_hyp_c_20260505T212306Z.json`: FAIL (pf=0.284, p_edge=0.0, DSR=0.0)
- MCL mean-reversion confirmed: no edge under any tested regime filter — hypothesis family closed

**US-002 — Branch divergence resolved**
- Merge commit `4077e46` merged `origin/master` (`4d99ef3` Strategy C+ v3, 2,194 files) into feat
- Zero merge conflicts — ort strategy merged cleanly
- Pushed to `origin/feat/tradingview-mcp-gamma-kraken` successfully
- Blocker 1 from this handoff is **resolved**

**US-003 — OLLAMA_NUM_CTX_PER_AGENT added**
- Commit `4a2b4bf` — `engine/llm/client.py` now parses `OLLAMA_NUM_CTX_PER_AGENT` env var
- `social_analyst` and `news_analyst` capped at 2048 ctx (vs 4096 global default)
- Prompt sizes verified: social ~430 tok, news ~1175 tok worst-case — 1.7× headroom at 2048
- `engine/.env` updated: `OLLAMA_NUM_CTX_PER_AGENT=social_analyst=2048,news_analyst=2048`
- Engine restarted; pm2 self-healed after port-race with `restart_engine.ps1`; health=ok
- Blocker 4 (Ollama CPU latency) partially mitigated for social/news agents

**US-004 — TV MCP health confirmed accurate**
- Port 9222 IS listening: TradingView/3.1.0 on Chrome/140.0.7339.133 (Electron 38.2.2)
- Health check is a real TCP probe to `127.0.0.1:9222/json/version` with 1s timeout + 30s cache
- `JARVIS-TV-CDP-AtLogon` last ran 2026-05-05 13:39 — TV Desktop is confirmed up
- Blocker 3 (TV Desktop anomaly) is **resolved** — `tradingview_mcp_healthy=true` is accurate

**US-005 — MNQ breakout rank2 committed (FAIL)**
- Parallel session ran rank2 sweep with `vol_ma_period=20` variation
- Result: degenerate — 0 OOS trades across all 18 windows (signal choked by param)
- Rank1 remains best result: `pf_ci_lower=1.0696` (gap 0.030 to core threshold)
- Alt path: `fixed_params_min_pf=1.186` (gap 0.014 to 1.20)
- MNQ remains in `DO_NOT_TRADE_SYMBOLS`

**US-006 — CredentialManager module installed**
- Version 2.0 installed at user scope
- Path: `C:\Users\mattm\OneDrive\Documents\WindowsPowerShell\Modules\CredentialManager\2.0\`
- `manage-jarvis-secrets.ps1 -List` runs clean (0 entries — no secrets loaded yet)
- Blocker 5 (module not installed) is **resolved**

---

## 3. Current State — What's Running, What's Stopped, What's Broken

### Running / Healthy

| Service | State | Details |
|---|---|---|
| `jarvis-engine` (pm2 id=0) | **Online** | PID 37944, uptime post-ralph-loop, 4 restarts (port-race churn during restart_engine.ps1 — not crashloop), CPU 0%, mem 24KB |
| Engine API (port 8010) | **Healthy** | `status=ok`, `llm_path_healthy=true`, `tradingview_mcp_healthy=true`, paper_mode=true, version=1.1.0 |
| Ollama (port 11434) | **Running** | CPU-only; hermes3:latest + llama3.2:3b loaded with KEEP_ALIVE=24h |
| `/health/llm` | **Live** | 141 hermes3 calls + 38 llama3.2:3b calls in last 24h, all $0.00 (Anthropic fallback dormant) |
| `Jarvis-PM2-AtLogon` | **Ready** | Registered, fires on next logon |
| `Jarvis-DR-Weekly` | **Ready** | Fires Sunday 2026-05-10 03:00 |

### Stopped / Disconnected (expected)

| Service | State | Why |
|---|---|---|
| IBKR paper (port 4002) | Disconnected | Market closed; `ibkr_execution_connected=false`, `ibkr_data_connected=false` — normal |
| IBKR live (port 4001) | Permanently blocked | Network policy, not a bug |
| Schwab | Disconnected | Not configured / not used currently |
| TV Desktop CDP (port 9222) | **Confirmed running** | TradingView/3.1.0 on Chrome/140.0.7339.133 (Electron 38.2.2); JARVIS-TV-CDP-AtLogon last ran 2026-05-05 13:39; `tradingview_mcp_healthy=true` is accurate |

### Known Issues / Degraded

| Issue | Severity | Detail |
|---|---|---|
| Ollama latency | High | Both hermes3:latest and llama3.2:3b hitting ~181s (p95). Root cause: CPU-only inference + OLLAMA_NUM_CTX=4096 + long prompts. `latency_warning=true` in /health/llm. |
| Branch divergence | ~~Medium~~ **Resolved** | Merge commit `4077e46` merged `origin/master` into feat; 0 conflicts; pushed successfully (US-002) |
| meanrev_signals.py dirty | ~~Low~~ **Resolved** | MCL Hypothesis C committed as 31ef7c6; working tree clean (US-001) |
| Secret rotation (Phase 0) | Medium | 6 known credential locations pending rotation — compliance debt accumulating |

---

## 4. In-Progress Work — Started But Not Finished

### 4a. MCL Hypothesis C — rv_band regime gate

**What:** A test of whether a realized volatility band filter can rescue MCL mean-reversion strategy. The hypothesis: MCL only has edge when annualized RV is in [rv_min, rv_max] — filtering out both ultra-low-vol (thin, directionless) and ultra-high-vol (trending shock) regimes.

**What was done:** 
- Added `rv_band` mode to `_build_regime_gate()` in `meanrev_signals.py`
- Created `run_mcl_hypothesis_c.py` as the WFO driver
- Ran the backtest → verdict written to `engine/data/gate_v2_verdicts/MCL_hyp_c_20260505T212306Z.json`

**Result: FAIL** — `pf_ci_lower=0.2841`, `p_edge=0.0`, mc_95th_dd=3.58%, DSR=0.0. The rv_band gate reduces drawdown but destroys trade count (many windows: 0-3 trades in OOS). Insufficient trades for statistical significance. **MCL mean-reversion does not have edge under any tested regime filter.**

**What's uncommitted:** The changes to `meanrev_signals.py` and `run_mcl_hypothesis_c.py` are still in the working tree. They should either be committed (as a documented failed hypothesis) or discarded. Recommend: commit with `docs(backtest): MCL hypothesis C rv_band — FAIL` so the verdict file and code stay in sync.

### 4b. Branch Merge Decision

Local master has been FF-merged to feat tip but NOT pushed. `origin/master` still points at the Apr 22 diverged commit. See Blockers.

### 4c. `manage-jarvis-secrets.ps1` — Credential Manager population

The script was written but NO secrets have actually been loaded into Windows Credential Manager yet. The `CredentialManager` PowerShell module may not be installed (script warns to run `Install-Module CredentialManager -Scope CurrentUser`). Until secrets are loaded, `-Export` produces an empty .env file. The 1Password path in the runbook remains the live DR path.

---

## 5. Blockers Discovered

### Blocker 1: Branch Divergence (needs Amo decision)

**Situation:** `origin/master` contains commit `4d99ef3` ("JARVIS Strategy C+ v3 — Phase 3+4 complete", Apr 22 2026) which is a massive merge (2,194 files changed, 1,406,032 insertions). This commit is NOT in `feat/tradingview-mcp-gamma-kraken`. The feat branch is 59 commits ahead of `origin/master` and `origin/master` is 1 commit ahead of the feat branch's merge-base.

**Options:**
- **(A) Cherry-pick `4d99ef3` into feat** — risky given 2,194 files; high conflict probability
- **(B) Merge `origin/master` into feat** — brings in the diverged commit, preserves all history, then FF master to feat
- **(C) Treat feat as de-facto master, force-push origin/master to feat tip** — destroys the `4d99ef3` commit on origin. Against git-hygiene rules; requires explicit authorization.
- **(D) Leave as-is** — feat is the active development trunk; let master drift. Acceptable temporarily.

**Recommendation:** Option B (merge `origin/master` into feat, resolve conflicts if any, then push). Run `git merge origin/master` from feat branch and inspect conflicts before committing.

### Blocker 2: Phase 0 Secret Rotation

15 services pending credential rotation (Anthropic, OpenAI, Google API ×2, Azure AD, Paradigm ERP, SMTP ×3, Render, Firecrawl, GitHub). Cannot be executed without issuer console access. All other Phase 0 work is gated on this completing first.

**Current exposure:** `D:\personal_agent - Copy\jarvis.env` is a 7th forbidden-path file (Dec 2025 mirror). Covered by existing glob but rotation has not happened yet.

### Blocker 3: TV Desktop Install

`tradingview_mcp_healthy=true` in /health but TV Desktop is not confirmed installed from Microsoft Store. The MCP health check may be probing the MCP server process only, not actual TV data availability. Until TV Desktop is installed and running with `--remote-debugging-port=9222`, TV bar data is unavailable and the engine falls back to other data sources.

### Blocker 4: Ollama CPU Latency (hardware constraint)

Both models (`hermes3:latest` and `llama3.2:3b`) hit ~181s per call (p95). Root cause: CPU-only inference. `OLLAMA_NUM_CTX=4096` and `OLLAMA_NUM_PREDICT=256` are already conservative. The only real fix is a GPU. 

**Potential software mitigation** (not yet attempted): reduce `OLLAMA_NUM_CTX` to 2048 for `llama3.2:3b` social/news agents specifically — their output is shorter JSON, may not need full 4K context. Risk: if agent prompts exceed 2K tokens, they'll be truncated silently. Would need to measure actual prompt lengths first.

### Blocker 5: `manage-jarvis-secrets.ps1` depends on `CredentialManager` module

`Install-Module CredentialManager -Scope CurrentUser` has not been run. Until installed, the script falls back to `cmdkey` which has limited programmatic read capability. The -Export function won't work reliably without the module.

---

## 6. Key Decisions Made

### 6a. `OLLAMA_MODEL_PER_AGENT` separator = `=` not `:`

**Decision:** Use `agent_name=model:tag` format (e.g. `social_analyst=llama3.2:3b`), comma-separated.

**Why:** Ollama model names use `:` as their tag separator (`model:tag`). If we used `:` as the agent/model delimiter, parsing `social_analyst:llama3.2:3b` is ambiguous. Using `=` is unambiguous.

**Implementation:** `spec.split("=", 1)` — maxsplit=1 ensures `model:tag` colons are preserved.

### 6b. SQLite timestamp comparison must use strftime, not datetime()

**Decision:** Use `strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour')` for the 1-hour lookback in the `/health/llm` query.

**Why:** SQLite's `datetime('now', '-1 hour')` returns `'2026-05-05 17:38:04'` (space separator). The `llm_costs.db` stores timestamps as `'2026-05-05T17:38:04.999+00:00'` (ISO-T format from Python's `datetime.isoformat()`). String comparison between these is wrong — `T` (ASCII 84) > ` ` (ASCII 32), so ISO-T timestamps always sort AFTER space-format timestamps of the same wall-clock time. Every row would match even if 6 hours old.

### 6c. Windows Credential Manager over 1Password CLI for local automation

**Decision:** For local machine automation, use Windows Credential Manager (`manage-jarvis-secrets.ps1`) rather than 1Password CLI (`op`).

**Why:** `op` CLI requires biometric unlock or session token that expires after 30 minutes, making it unusable in headless/automated contexts. Windows Credential Manager is always available, persists across reboots, doesn't require CLI authentication, and is covered by OS-level security (per `rules/secret-hygiene.md` — WCM is an approved storage location).

**Caveat:** 1Password remains the authoritative DR source (the canonical copy of `engine/.env` is in 1Password vault). WCM is the local-machine operational copy.

### 6d. Per-agent model routing: only social/news agents to llama3.2:3b

**Decision:** Route `social_analyst` and `news_analyst` to `llama3.2:3b`. All other agents stay on `hermes3:latest`.

**Why:** Social/news agents produce short structured JSON (sentiment scores, ticker mentions). They don't need the broader world-knowledge of hermes3. llama3.2:3b is ~2B params vs ~7B for hermes3 — theoretically 2-3× faster on CPU for short outputs. (In practice both still hit 180s due to context overhead, but the routing is correct for when a GPU is available.)

**What was validated:** `/health/llm` confirmed 38 llama3.2:3b calls and 141 hermes3 calls in 24h. Routing is working.

### 6e. MCL mean-reversion = no edge, abandon for now

**Decision:** MCL mean-reversion family has no statistical edge under any tested regime filter (BBwidth, Keltner, rv_band). Three independent hypotheses tested, all FAIL gate v2. MCL remains in `DO_NOT_TRADE_SYMBOLS`.

**Gate v2 verdicts summary:**

| Symbol | Family | Verdict | Key metric failures |
|---|---|---|---|
| MES | trend (rank 7) | **PASS (ALT)** | Core fails PF/p_edge; ALT passes DSR=0.667, WFO=STRONG |
| MCL | meanrev (rank 1) | FAIL | mc_95th_dd=16.79%, DSR=0.0 (original); Hypothesis C rv_band: pf=0.2841, p_edge=0.0 |
| MNQ | breakout (rank 1-5) | FAIL | Rank2-5 all FAIL. Root cause: mid-2025 non-stationarity (windows 7-15 persistent losing streak). fixed_params_min_pf cleared at rank4 (1.2621) but WFO_CONSISTENCY=WEAK, pf_ci_lower=0.73, p_edge=0.36. Breakout family exhausted. Next: regime filter targeting 2025 volatility regime, or different MNQ strategy family. |
| MNQ | trend (rank 1) | FAIL | pf=0.6752, mc_dd=13.46% |

**MNQ_breakout is the closest to passing** — misses `pf_ci_lower` by 0.0304 and `fixed_params_min_pf` by 0.014. Worth a targeted parameter sweep before declaring it dead.

### 6f. pm2 restart count = 2 is acceptable

**Decision:** pm2 shows `↺ 2` for jarvis-engine — this is expected and not a crashloop. The 2 restarts occurred during this session's engine restarts for code changes. Current uptime is 62 minutes with no new restarts.

---

## 7. TODO Items — Planned But Not Started

These were in the Top-10 ROI list but not reached or blocked. US-001 through US-006 from the ralph loop are now complete (see Ralph Loop Extension section above).

| # | Item | Status |
|---|---|---|
| Task 4 | Phase 0 secret rotation (15 services) | Still pending — requires issuer console access |
| Task 5b | MNQ_breakout parameter sweep (close 0.0304 PF gap) | Still open — rank2 sweep (US-005) was a FAIL; need new approach. Rank1 pf_ci_lower=1.0696, alt fixed_params_min_pf=1.186 |
| Task 6 | TV Desktop install from Microsoft Store | **Resolved** — TV Desktop confirmed running (US-004); port 9222 active |
| Task 2 final | Reboot test to confirm pm2 AtLogon resurrection | Still pending — requires reboot |
| WCM population | Load all engine/.env secrets into Windows Credential Manager | Module now installed (US-006); secrets not yet loaded — requires interactive input |
| MCL Hypothesis C commit | Commit rv_band code and verdict | **Done** — committed as 31ef7c6 (US-001) |
| Branch divergence | Merge origin/master into feat | **Done** — merge commit 4077e46, pushed (US-002) |
| OLLAMA_NUM_CTX per agent | Cap social/news agents at 2048 ctx | **Done** — commit 4a2b4bf (US-003) |
| CredentialManager module | Install-Module CredentialManager | **Done** — version 2.0 installed (US-006) |

---

## 8. Full Current To-Do List

### Immediate (can execute next session without user input)

- [x] **Commit or discard MCL Hypothesis C code** — committed as 31ef7c6; working tree clean (US-001)
- [x] **Install CredentialManager PS module** — version 2.0 installed at user scope (US-006)
- [ ] **Load engine secrets into WCM** — Run `manage-jarvis-secrets.ps1 -Set` for each key in engine/.env (requires user to provide values or read from 1Password)
- [x] **Verify tradingview_mcp_healthy=true is accurate** — Confirmed: port 9222 active, TradingView/3.1.0 (Electron 38.2.2), JARVIS-TV-CDP-AtLogon last ran 13:39 (US-004)
- [x] **Add OLLAMA_NUM_CTX_PER_AGENT** — commit 4a2b4bf; social/news agents capped at 2048 ctx (US-003)

### Requires Amo Decision

- [x] **Branch divergence resolution** — resolved via merge commit 4077e46; pushed to origin (US-002)
- [ ] **MNQ_breakout family exhausted (rank1-5)** — All 5 sweeps FAIL. Root cause: mid-2025 non-stationarity (windows 7-15 losing streak). fixed_params_min_pf cleared at rank4 (1.2621) but WFO_CONSISTENCY=WEAK. Next: design regime filter for mid-2025 losing streak, OR pivot to MNQ trend-following family (not yet backtested).
- [x] **TV Desktop install / verify** — TV Desktop confirmed running on port 9222 (US-004)
- [ ] **Reboot test** — verify `Jarvis-PM2-AtLogon` actually resurrects pm2 on logon. Schedule a reboot when convenient.

### Requires Issuer Console Access

- [ ] **Phase 0 rotation** — 15 services. See `~/.claude/projects/C--windows-system32/memory/project_phase0_playbook_updates_2026_05_04.md` for full list. Gating item for D-drive cleanup and gbrain-staging cleanup.

### Long-Term / Lower Priority

- [ ] **Ollama latency** — investigate reducing `OLLAMA_NUM_CTX` to 2048 for llama3.2:3b agents only. Would need to measure actual prompt token lengths to ensure no truncation.
- [ ] **MES_trend ALT→Core promotion** — MES passes via ALT routing (DSR=0.667, WFO=STRONG) but fails core PF/p_edge thresholds. If account size reaches $50K+ threshold, ALT routing is already authorized. Below that, trading is not active.
- [ ] **MCL alternative hypothesis** — rv_band failed. If MCL is to be revisited, need a fundamentally different approach (trend-following? correlation with crude oil ETF?). No timeline.

---

## 9. Git State

### Branch
```
feat/tradingview-mcp-gamma-kraken
Up to date with origin/feat/tradingview-mcp-gamma-kraken
```

### git status
```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is up to date with 'origin/feat/tradingview-mcp-gamma-kraken'.

Changes not staged for commit:
  modified:   engine/backtest/meanrev_signals.py

Untracked files:
  engine/backtest/run_mcl_hypothesis_c.py
```

### git log --oneline -20
```
394c2a2 fix(auth): exempt /health/* sub-endpoints from API key requirement
6430e64 feat(health): add /health/llm endpoint for cost-DB observability
d8d3822 feat(llm): add OLLAMA_MODEL_PER_AGENT knob for per-agent model routing
8c75168 fix(engine): capture uvicorn boot stdout/stderr in non-pm2 path
2dd3e7f refactor(verify-p0): prefer ibkr_execution_connected over legacy ibkr_connected
ab0a8f9 feat(secrets): add 1Password op-aware engine launch artifacts (Phase 0 Wave 1 prep)
af566d3 docs(session-logs): branch divergence analysis 2026-05-05
af40260 feat(llm): plumb OLLAMA_KEEP_ALIVE through to /api/generate requests
4780afe fix(engine): import CircuitBreakerStatus model used by /safety/circuit-breakers
db46dc4 chore(mcp): drop unused chrome-devtools and markitdown MCPs
546d079 chore(gitignore): expand venv exclusion to catch empty/failed rebuilds
68c2d9d docs: backfill plans + weekly review (Apr 22-26) + 2026-05-05 triage report
cd6a98d build(deps): pin xgboost==3.2.0 and document pandas-ta Windows patch
360ee1d feat(brokers): surface blind-state on /brokers/positions reconciliation
3642459 feat(health): split ibkr_execution_connected vs ibkr_data_connected
983e467 chore(gitignore): exclude broken venv backups and runtime morning_briefs
6ef27d7 feat(safety): /smoke/bracket endpoint + orders_router improvements for HB-1 verification
08e4a27 fix(brief): extract price from dict returned by get_current_price — was calling float(dict)
704ea81 fix(gate): drawdown = today's intra-session, pm2 prefers jarvis-engine
e8cca9e fix(gate): bracket counter via sidecar, decoupled from paper_trades.notes
```

### git diff --stat (working tree)
```
 engine/backtest/meanrev_signals.py | 27 +++++++++++++++++++++++++++
 1 file changed, 27 insertions(+)
```

### Branch divergence from origin/master
```
feat is 59 commits AHEAD of origin/master
origin/master is 1 commit AHEAD of feat's merge-base:
  4d99ef3 feat: JARVIS Strategy C+ v3 — Phase 3+4 complete (Apr 22, 2026)
  [2,194 files changed, 1,406,032 insertions, massive merge commit]
```

---

## Live State at Handoff

```
Engine: http://127.0.0.1:8010/health
  status=ok | version=1.1.0 | paper_mode=true
  llm_path_healthy=true | tradingview_mcp_healthy=true
  ibkr_execution_connected=false | ibkr_data_connected=false (market closed)
  uptime_seconds=3737

/health/llm:
  anthropic_fallback_active=false (all calls going to Ollama)
  latency_warning=true (hermes3 p95=181.5s, llama3.2 p95=181.1s)
  cost_24h_total_usd=0.0
  hermes3:latest — 24h: 141 calls | 1h: 7 calls
  llama3.2:3b   — 24h: 38 calls  | 1h: 10 calls

pm2:
  jarvis-engine | online | PID 37944 | uptime post-ralph-loop | restarts 4 (port-race churn, not crashloop)

Scheduled tasks:
  Jarvis-PM2-AtLogon — Ready (fires at next logon)
  Jarvis-DR-Weekly   — Ready (next: 2026-05-10 03:00)
```

---

## Suggested First Action for Next Session

Working tree is clean, branch is merged and pushed (all ralph loop items done). Next priorities:

1. **Load engine secrets into Windows Credential Manager** — `manage-jarvis-secrets.ps1 -Set` for each key in `engine/.env`. Interactive — needs Amo's input or 1Password CLI session.
2. **MNQ breakout family exhausted (rank1-5)** — Next: design regime filter for mid-2025 losing streak, OR pivot to MNQ trend-following family (not yet backtested). Polygon WS reconnect backoff also fixed (commit 7555188).
3. **Phase 0 secret rotation** — 15 services pending; unblocks D-drive cleanup and gbrain-staging scrub. Requires issuer console access.
4. **Reboot test** — schedule when convenient to confirm `Jarvis-PM2-AtLogon` resurrects pm2 correctly.
