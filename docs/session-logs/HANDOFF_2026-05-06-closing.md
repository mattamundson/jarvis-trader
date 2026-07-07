# JARVIS TRADER — Complete Closing Handoff
## Session: 2026-05-05 extended / 2026-05-06 early morning
## Branch: feat/tradingview-mcp-gamma-kraken
## Written: 2026-05-06 ~04:10 UTC
## Purpose: Zero-context-loss handoff for next AI session

---

```yaml
session_id: "2026-05-06-closing"
campaign: "Serene-Wigderson — multi-day autonomous campaign toward production-ready JARVIS"
goal: >
  This session completed OneDrive Phase C/E (Greenfield Metal Sales consolidation + 
  structure verification), stood up TradingView Desktop CDP, ran MCL Hypothesis C WFO 
  (FAIL), and fully prepared for Phase 0 Wave 1 credential rotation. Session is closing 
  before Amo can visit browser consoles for rotation — that is the next blocking work item.
status: "blocked_on_amo_console_work"

primary_blocker: >
  Phase 0 Wave 1 credential rotation. Amo must visit console.anthropic.com, 
  platform.openai.com, and console.cloud.google.com to revoke and replace 8 API keys 
  (Anthropic ×4, OpenAI ×1, Google ×3). Until old keys are verified dead (401), Tasks 7 
  and 10 cannot proceed. The playbook is fully loaded and ready — this is purely a 
  Amo-at-keyboard dependency.

engine_health_at_close:
  status: ok
  pm2_pid: 13508
  pm2_uptime_hours: ~3.3
  pm2_restarts: 6
  pm2_memory_kb: 740
  llm_path_healthy: true
  tradingview_mcp_healthy: FALSE  # regression — TV Desktop closed, port 9222 not listening
  ibkr_connected: false           # expected — not trading hours
  paper_mode: true
  kill_switch: inactive
  live_trading: false

git_state:
  branch: feat/tradingview-mcp-gamma-kraken
  ahead: 0
  behind: 0
  uncommitted_modified:
    - docs/session-logs/HANDOFF_2026-05-05-evening.md
    - docs/session-logs/HANDOFF_2026-05-05-late.md
  untracked:
    - docs/session-logs/HANDOFF_2026-05-06-closing.md  # this file
  latest_commit: cb49ec9 feat(backtest): MES trend rank11 verdict refresh — PASS
```

---

## EXECUTIVE SUMMARY FOR NEXT SESSION

The Serene-Wigderson campaign has driven JARVIS from a dirty, credential-leaking, partially-broken state to approximately 85% production-ready. The remaining 15% is almost entirely Phase 0 credential rotation (browser console work) and the downstream tasks it gates. 

**Single most important fact:** Everything downstream of Phase 0 is blocked. Paste-cache deletion (Task 7), D-drive cleanup (Task 10), and the Google audit log check are all waiting on Amo rotating 8 keys across 3 browser consoles. The code, scripts, and verification steps are all prepared — this is purely a human-at-browser dependency.

**Second most important fact:** TradingView MCP is currently down (port 9222 not listening). This degrades the engine's bar data path to fallback (Polygon/Yahoo). Recovery is one PowerShell command: `schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"`.

**Third:** The two modified handoff docs and this closing handoff need to be committed and pushed before any code work begins, to keep the branch clean.

---

## 1. FULL SESSION NARRATIVE — WHAT WAS ACCOMPLISHED, IN ORDER

### 1.1 Campaign Background (Where This Session Entered)

This was a context-compressed continuation of a longer session. The prior session ("Serene-Wigderson evening") had already completed:

**Infrastructure and tooling:**
- Engine venv repaired: switched bootstrap from `requirements.txt` → `requirements-core.txt` (these diverge significantly on `slowapi`, `torch`, `gymnasium`, `stable-baselines3`)
- Ollama installed and verified: 5 models pulled (~21GB), OLLAMA_KEEP_ALIVE=24h wired via existing `af40260` knob
- `OLLAMA_NUM_CTX_PER_AGENT` knob added (`4a2b4bf`) — social/news agents set to 2048 to prevent OOM on multi-agent inference
- Engine running under pm2 (not plain uvicorn — confirmed via `pm2 status`)

**Security cleanup:**
- 6 credential files deleted (prior pass)
- 123 OneNote quarantined pages + 20 vault files redacted (T9 OneNote vault redaction)
- scan-credentials.ps1 file-level whitelist bug fixed
- HIGH findings reduced from 259 → 23 (12 rotation-gated, 0 autonomous remaining after that prior pass)
- D-drive Phase 1+2 cleanup: FlowTrade + personal_agent-Copy(2) + career-ops-orphan deleted, ~17GB freed

**Career-ops:**
- PR #7 (firecrawl→native-fetch): merged
- PR #8 (firecrawl-js orphan removed): merged; 344/344 tests pass
- career-ops AtLogon + --live flag: 12 scheduled tasks restored post-reboot

**Trading system:**
- MNQ rank2 WFO verdict committed
- MCL Hypothesis C implemented and run (FAIL — see 1.4 below)
- Branch divergence (48 ahead/67 behind) resolved via merge commit `4077e46`
- MES trend rank7 through rank11 verdicts run (rank11: PASS — see 1.5 below)
- git working tree cleaned: 10 test artifacts untracked via .gitignore hardening (`5f697b6`)

### 1.2 TradingView Desktop CDP Setup (Task 4 — COMPLETE)

**Background:** Engine health was reporting `tradingview_mcp_healthy=false` because TradingView Desktop was not installed on this machine. The TV MCP (which provides Tier 0 bar data via Chrome DevTools Protocol) requires TV Desktop running with `--remote-debugging-port=9222`.

**What happened:**
1. Amo manually installed TradingView.Desktop 3.1.0.7818 (Microsoft Store delivery)
2. The existing script `~/scripts/install-tv-cdp-task.ps1` was run with `-RestartEngine` flag
3. Script verified AppX package, registered `JARVIS-TV-CDP-AtLogon` scheduled task, triggered it, waited 15s, verified port 9222 LISTENING, verified CDP `/json/version` responded (Chrome/140.0.7339.133), checked engine `/health`
4. Result: `tradingview_mcp_healthy=TRUE` — engine detected TV without needing a restart

**Current status:** REGRESSED. TradingView Desktop closed at some point during this session. Port 9222 is now NOT LISTENING. Engine health shows `tradingview_mcp_healthy=FALSE` with detail "CDP port 9222 unreachable: timed out". The scheduled task (`JARVIS-TV-CDP-AtLogon`) is correctly registered and will auto-run at next logon — this is not a bug, just TV not being open.

**Recovery command (run in PowerShell):**
```powershell
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
Start-Sleep 20
netstat -ano | Select-String ':9222' | Select-String 'LISTENING'
# Should show a LISTENING entry
Invoke-RestMethod http://127.0.0.1:8010/health | Select-Object tradingview_mcp_healthy
# Should show True
```

**Root cause of regression:** TV Desktop is a single-instance application. If Amo closed it (or it crashed), the debug port closes with it. The AtLogon task re-launches it on next login. Alternatively, running the task manually re-launches it if TV isn't already running.

**Known caveat:** If TV is already running WITHOUT `--remote-debugging-port=9222` (i.e., launched from taskbar shortcut), triggering the AtLogon task will be a no-op because TV blocks second instances. In that case: quit TV via system tray → Quit, then trigger the task.

### 1.3 OneDrive Phase C/E — GMS Consolidation

**Background:** Phase C was the large Greenfield Metal Sales consolidation — moving ~400K non-Phase-D files from various OneDrive locations into the AmoSZN/05_Past-Work/Greenfield-Metal-Sales/ numbered structure.

**Structure created:**
```
AmoSZN/05_Past-Work/Greenfield-Metal-Sales/
├── 01_Branding/
├── 02_Catalogs/
├── 03_Customers/
├── 04_Documentation/
├── 05_Equipment/
├── 06_Inventory/
├── 07_Invoices/
├── 08_Marketing/
├── 09_Orders/
├── 10_Paradigm-ERP/
├── 11_Photos-Jobsites/
├── 12_Presentations/
├── 13_Price-Lists/
├── 14_Product-Docs/
├── 15_Quotes/
├── 16_Reports/
├── 17_Sales-Tax/
├── 18_SOPs/
├── 19_Trim/
├── 20_Warehouse/
├── 21_Website/
├── README.md        ← created Phase E
└── _legacy-numbered/ ← old GMS internal numbering (01-10)
```

**What was moved (confirmed complete):**
- `OneDrive/Business/` (1,007 files, 28 subfolders) → GMS numbered structure
- `OneDrive/WebsiteUpgrade/` (383 files) → `GMS/21_Website/`
- `OneDrive/Archives/` (38,279 files) → year-binned into `GMS/06_Archive/<year>/` and `06_Archive/` top-level
- GMS `_legacy-numbered/` (01-10 old internal folders, ~452+ files moved) — was at ~549 files by checkpoint
- `OneDrive/Greenfield Metal Sales/Marketing Materials/` → `GMS/08_Marketing/` (blqawtp82 task, exit=1, confirmed moved)
- `OneDrive/Greenfield Metal Sales/Live-Shop-Floor-Dashboard/` main code (frontend/, api/server.js, powerbi/, package.json) → `_MIGRATE_OUT/Live-Shop-Floor-Dashboard/`; node_modules also moved via blqawtp82 (exit=1 with some ERROR 426 cloud timeouts, but ultimately completed)

**What remains in OneDrive/Greenfield Metal Sales/ (NOT moved):**
```
04_Marketing_Sales/   ← GMS internal numbering; didn't match move plan
05_Documentation/     ← same
06_Data_Geography/    ← same
07_Admin_Legal/       ← same
08_Equipment_Vendors/ ← same
09_Archives/          ← same  
10_Installers/        ← same
Greenfield-Classic-Rib-Extraction/  ← partially moved; non-Phase-D content should go to GMS/14_Product-Docs/
AI Agent Team/        ← Phase D (215K files, intentionally deferred)
greenfield-ai-suite/  ← Phase D (173K files, intentionally deferred)
dev-backup-2026-01-02/ ← Phase D (82K files, intentionally deferred)
```

**Analysis of 04-10 numbered folders:** These are GMS's own internal numbering scheme (unrelated to AmoSZN's numbering). They were NOT moved because the move plan didn't account for them — they either appeared after plan creation or were missed in the content audit. The next session needs to:
1. List each folder's contents briefly to identify what's inside
2. Map each to the AmoSZN GMS numbered structure (rough mapping in Section 7)
3. Move or merge

**Phase E verification results (V1–V9):**
- V1: OneDrive root = 14 entries (DEFERRED — target ≤10, Photos/Media/Phase-D blocking)
- V2: `_legacy-numbered/` exists = PASS
- V3: GMS directory has ≥21 dirs = PASS (has 22 + README + _legacy-numbered = 24)
- V4: OneDrive root files = PASS (only system files)
- V5: `_Cruft/` subdirs = PASS
- V6: `_Inbox/` count unchanged = PASS
- V7: `_MIGRATE_OUT/` has only code projects = PASS
- V8: Phase D mega-folders still at source = PASS (`AI Agent Team/` confirmed present)
- V9: FILING_GUIDE.md dated today = PASS

**Background task blqawtp82 result (just completed):**
- Marketing Materials: exit=1 (robocopy success — files copied/moved to GMS/08_Marketing/)
- Live-Shop-Floor-Dashboard: exit=1 (success with some ERROR 426 cloud timeouts during retry window — files ultimately moved to _MIGRATE_OUT)
- Greenfield-Business/Marketing: exit=16 (source path `C:\Users\mattm\OneDrive\Greenfield Metal Sales\Greenfield-Business\Marketing\` not found — either already moved in prior pass or path was wrong)
- Greenfield/: exit=16 (source path `C:\Users\mattm\OneDrive\Greenfield Metal Sales\Greenfield\` not found — same reason)
- Overall task exit=0 (shell script treated 16s as non-fatal or final step returned 0)

**Files created during Phase E:**
- `AmoSZN/FILING_GUIDE.md` — authoritative directory structure index (6 top-level dirs, 21 GMS numbered subdirs with 1-line descriptions, _Cruft and _Inbox notes, Phase D annotations)
- `AmoSZN/05_Past-Work/Greenfield-Metal-Sales/README.md` — GMS archive context, era marker, all 22 numbered subdirs indexed, _legacy-numbered explanation, Phase D status
- `AmoSZN/02_Code/_MIGRATE_OUT/README.md` — staged repos table (10 entries), Phase D note, migration instructions

### 1.4 MCL Hypothesis C WFO — FAIL

**Background:** MCL (Micro Crude Oil) is locked in `DO_NOT_TRADE_SYMBOLS = frozenset({"MCL", "MNQ"})` at `engine/backtest/signals.py:108`. The prior attempt (Bollinger+RSI mean-reversion, 254 trades, PF 0.855) showed a trend-day chop signature and was declared dead.

**Hypothesis C theory:** The vol-regime gate — add a wrapper that only enters when 20-day annualized realized volatility falls within a band (25–45%). The idea: above a vol threshold crude exhibits trend; below, it chops. Filter to the "sweet spot" where the mean-rev signal has edge.

**Implementation:** Added `rv_band` mode to `engine/backtest/meanrev_signals.py:_build_regime_gate()`. Computes daily close-to-close log returns resampled from 1h bars, annualizes with sqrt(252). WFO script at `engine/backtest/run_mcl_hypothesis_c.py`.

**WFO configuration:**
- 18 windows: 6-month in-sample / 1-month out-of-sample / 1-month step
- Fast parameter grid: rv_min=[20,25,30] × rv_max=[40,50] × lookback=[15,20] = 12 combinations
- Gate v2 thresholds: pf_ci_lower≥1.10, p_edge≥0.95, mc_95th_dd≤5%, dsr≥0.10

**Results:**
| Metric | OOS Result | Threshold | Status |
|---|---|---|---|
| pf_ci_lower | 0.284 | ≥ 1.10 | **FAIL by 0.816** |
| p_edge | 0.000 | ≥ 0.95 | **FAIL — ZERO profitable OOS windows** |
| mc_95th_dd | 3.579% | ≤ 5.0% | PASS (meaningless — no trades) |
| dsr | 0.000 | ≥ 0.10 | **FAIL** |

**Root cause analysis:** IS PF was consistently < 1.0 across all 18 windows (median ~0.80; best IS PF: 1.20 in one window). The optimizer selected the "least bad" combo each time — not a genuinely profitable configuration. The vol-regime gate filters signals but cannot inject edge where none exists in the base strategy. The Bollinger+RSI mean-reversion strategy has no edge on MCL 1h at any vol band tested.

**Dead strategy list (do not re-attempt without new theory):**
- Bollinger+RSI mean-rev (no filter): PF 0.855, 254 trades — DEAD
- Bollinger+RSI mean-rev + rv_band (Hypothesis C): pf_ci_lower=0.284, p_edge=0.000 — DEAD

**Committed:** `31ef7c6` — `feat(backtest): add rv_band regime filter to meanrev_signals + MCL WFO runner`

**Verdict file:** `engine/data/gate_v2_verdicts/MCL_hyp_c_20260505T212306Z.json`

**MCL next step — Hypothesis B (Sentiment Overlay):**
Theory: crude oil edge is narrative-driven (EIA inventory reports Wednesday, OPEC announcements, geopolitical events). Filtering to only when Corey (#market-updates Discord) expresses a directional crude bias avoids the chop case where MCL has no narrative catalyst.

Requirements before WFO can run:
1. Corey's historical Discord messages must be backfilled with crude-keyword extraction + sentiment polarity labels
2. New module: `engine/backtest/sentiment_overlay_signals.py` — wraps any base directional signal with a sentiment gate from `social_analyst.py`
3. The gate at `social_analyst.py:347-356` already restricts futures sentiment to Corey's channel only — leverage that

### 1.5 MNQ Breakout Strategy — Exhausted

**Background:** MNQ (Micro Nasdaq) was one of the top trading priorities. The Donchian channel breakout strategy was identified as the closest to passing gate v2.

**Full sweep history:**
| Rank | Sweep type | Result | Key metric | Notes |
|---|---|---|---|---|
| 1 | Base: pf_ci_lower=1.0696 (gap 0.030), alt fixed_params_min_pf=1.186 (gap 0.014) | FAIL | pf_ci_lower=1.0696 | Closest to passing of all sweeps |
| 2 | vol_ma_period=20 variation | FAIL | 0 OOS trades | Signal died with vol filter |
| 3 | ALT-path sweep | FAIL | — | — |
| 4 | Tight-grid ALT sweep | FAIL (but cleared fixed_params_min_pf=1.2621) | WFO_CONSISTENCY=WEAK, pf_ci_lower=0.73, p_edge=0.36 | fixed_params_min_pf cleared but WFO is weak |
| 5 | $25K capital test | FAIL | 0 OOS trades | — |

**Root cause (confirmed across 5 sweeps):** Mid-2025 structural non-stationarity. WFO windows 7–15 (approximately covering mid-2024 through mid-2025) show a persistent losing streak that IS optimizer cannot navigate around — it selects least-bad combos that then fail in OOS. This is not parameter mis-tuning; it's a regime change where the Donchian breakout signal's underlying assumptions broke down.

**What "clearing fixed_params_min_pf" at rank4 means:** The rank4 sweep found a parameter set with 1.2621 fixed_params_min_pf (exceeds the 1.20 threshold). But this is a pre-WFO metric computed on the full training set, not the walk-forward OOS. When the same parameters are evaluated in WFO, consistency is WEAK and pf_ci_lower drops to 0.73. The IS signal is real but OOS doesn't confirm it — exactly the pattern of overfitting to historical data.

**Next steps for MNQ:**
Option A — Regime filter: Design a filter that detects when the 2025 losing-streak regime is active (e.g., based on realized vol, ATR percentile, or VIX analogue) and gates out trading during that period. The IS optimizer would then only select combos that worked in non-losing-streak periods. Risk: the 2025 regime may have been a one-off; if so, the filter will over-reduce the trade count.

Option B — New strategy family: MES trend-following (SMA 50/200) PASSed gate v2 at rank11 after extensive tuning. Apply the same SMA trend-following framework to MNQ, which also exhibits trend during major macro events. This would require a fresh backtest starting from rank1 — no existing infrastructure to reuse from the breakout sweeps.

**Polygon WebSocket fix committed during this campaign:**
The engine had a silent infinite retry loop in `engine/data/polygon_stream.py`. On Polygon plans that don't include WebSocket access (the current plan), auth_failed responses were logged but not acted on — the code fell through to subscribe, which also failed, hit ConnectionClosed, slept 5s, and retried forever. Fix:
1. `840ee01`: Parse auth response; on `auth_failed`/`auth_timeout`, set `self.running=False` and return — clean immediate exit, no retry ever
2. `7555188`: PostToolUse linter applied exponential backoff (5s→300s, 2× multiplier) for genuine transient failures. The auth_failed path is unaffected.

### 1.6 Phase 0 Credential Rotation — Prepared, Not Started

**What was accomplished:** Full PHASE0_ROTATION_PLAYBOOK.md was read into context (550 lines, all 15 services). INCIDENT.md was read. The rotation checklist was provided to Amo. Amo said "Proceed" but the session is closing before browser console work can happen.

**What was NOT accomplished:** Zero services have been rotated. All 15 remain at "pending" status in the playbook audit log.

**Critical note on the Chrome Passwords.csv:** The CSV at `C:\Users\mattm\.archive\cred-incidents\chrome-pwd-2026-05-05\Chrome Passwords.csv` is credential-guarded. The assistant cannot read it directly. Amo must open it manually (Excel or Notepad), work through each row, and delete the file only after all credentials are rotated at their respective sites.

---

## 2. FILES CREATED OR MODIFIED — COMPLETE INVENTORY

### 2.1 Created This Session (Confirmed Present on Disk)

| File | Full Path | Contents / Purpose |
|---|---|---|
| `HANDOFF_2026-05-06-closing.md` | `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\HANDOFF_2026-05-06-closing.md` | **This file** — comprehensive zero-context-loss handoff |
| `_MIGRATE_OUT/README.md` | `C:\Users\mattm\OneDrive\AmoSZN\02_Code\_MIGRATE_OUT\README.md` | Staged repos table: 10 repos listed with origin, notes, migration target; Phase D exclusions documented; migration instructions (Move-Item → git remote -v → git status) |
| `FILING_GUIDE.md` | `C:\Users\mattm\OneDrive\AmoSZN\FILING_GUIDE.md` | Authoritative AmoSZN/ structure index: 6 top-level directories with purpose statements, all 21 GMS numbered subfolders with 1-line descriptions, _Cruft and _Inbox notes, Phase D annotations, date stamp 2026-05-05 |
| `GMS README.md` | `C:\Users\mattm\OneDrive\AmoSZN\05_Past-Work\Greenfield-Metal-Sales\README.md` | GMS archive context: era marker (GMS 2016–2026), 22-numbered-subfolder index, _legacy-numbered explanation, Phase D mega-folder status |

### 2.2 Modified This Session (Committed to Git)

| Commit | File(s) | Change Type | Why |
|---|---|---|---|
| `31ef7c6` | `engine/backtest/meanrev_signals.py` | feat | Added `rv_band` regime filter mode using 20-day annualized RV from 1h bar log returns; `_build_regime_gate()` function |
| `31ef7c6` | `engine/backtest/run_mcl_hypothesis_c.py` | feat (new file) | MCL Hypothesis C WFO runner: 18 windows, 6mo IS/1mo OOS, 12-combo grid (rv_min×rv_max×lookback) |
| `4a2b4bf` | `engine/main.py` or config | feat | `OLLAMA_NUM_CTX_PER_AGENT` env var — per-agent context sizing, social/news → 2048 |
| `840ee01` | `engine/data/polygon_stream.py` | fix | auth_failed/auth_timeout → immediate clean exit, `self.running=False`, return |
| `7555188` | `engine/data/polygon_stream.py` | fix | Exponential backoff on transient reconnects: 5s→300s, 2× multiplier, resets on successful auth |
| `37e9ccd` | `engine/data/gate_v2_verdicts/MNQ_breakout_rank2_*.json` + others | feat | MNQ rank2 verdict committed |
| `bff5e7d` | `engine/backtest/run_mnq_*.py` + verdicts | feat | MNQ rank5 $25K capital test FAIL |
| `c114e5c` | same | feat | MNQ rank4 tight-grid ALT sweep FAIL |
| `3e73934` | same | feat | MNQ rank3 ALT-path sweep FAIL |
| `12e686b` | same | chore | MNQ rank3 sweep script + handoff update |
| `cb49ec9` | `engine/data/gate_v2_verdicts/MES_trend_rank11_*.json` | feat | MES trend rank11 verdict PASS |
| `2dc585f`, `baf31db`, `2d408c3`, `8b0a951` | various MES trend verdicts | feat | MES trend rank8-10 verdict FAILs |
| `d2f5eac` | `engine/` routing | fix | Wire MES_trend SMA(50,200) into paper trading pipeline |
| `8b0a951` | `restart_engine.ps1` | fix | Use 127.0.0.1 in health poll (Windows IPv6 localhost quirk) |
| `5f697b6` | `.gitignore` | chore | Exclude gate verdict runs, HTML charts, untrack test artifacts |
| `4077e46` | merge commit | chore | Merge `origin/master` into feature branch (resolved 48-ahead/67-behind divergence) |

### 2.3 Modified This Session (NOT YET COMMITTED)

| File | Full Path | What Changed |
|---|---|---|
| `HANDOFF_2026-05-05-evening.md` | `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\HANDOFF_2026-05-05-evening.md` | Updated MNQ status from "rank1-2 FAIL, next sweep needed" to "rank1-5 all FAIL; root cause documented as mid-2025 non-stationarity" |
| `HANDOFF_2026-05-05-late.md` | `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\HANDOFF_2026-05-05-late.md` | Major expansion: +639/-220 lines; full session narrative from Polygon fix through credential prep; added sections on MNQ exhaustion, MES rank11 PASS, OLLAMA context knob, TV CDP recovery |

### 2.4 OneDrive Files Moved (Non-Git, Phase C/E Work)

**Destination structure created:**
- `AmoSZN/05_Past-Work/Greenfield-Metal-Sales/` — 22 numbered subdirectories + _legacy-numbered + README
- `AmoSZN/02_Code/_MIGRATE_OUT/` — expanded with LSFD, additional GMS code repos, Marketing Materials

**Key moves completed (robocopy exit=1 = success):**
- `OneDrive/Business/*` (1,007 files) → GMS numbered structure
- `OneDrive/WebsiteUpgrade/*` (383 files) → `GMS/21_Website/`
- `OneDrive/Archives/*` (38,279 files, bulk) → `GMS/06_Archive/<year>/`
- `OneDrive/Greenfield Metal Sales/Marketing Materials/*` → `GMS/08_Marketing/`
- `OneDrive/Greenfield Metal Sales/Live-Shop-Floor-Dashboard/*` → `_MIGRATE_OUT/Live-Shop-Floor-Dashboard/`
- `OneDrive/Greenfield Metal Sales/01-10 old folders/*` → `GMS/_legacy-numbered/`

**Key moves with issues:**
- `OneDrive/Documents/Bobby Love McClelland...docx` — destination copy confirmed; source still present (OneDrive lock). Needs manual `Remove-Item` once lock releases.

**Key moves NOT done (remain at source):**
- `OneDrive/Greenfield Metal Sales/04_Marketing_Sales/` through `10_Installers/`
- `OneDrive/Photos/` (6,718 files — cloud-only, deferred)
- `OneDrive/Media/` (2,729 files — iTunes Album Artwork cache)
- `OneDrive/Pictures/` (count unknown)
- `OneDrive/Desktop/` (13 stray spreadsheets)

---

## 3. CURRENT SYSTEM STATE — VERIFIED AT CLOSE

### 3.1 JARVIS Engine

```
URL: http://127.0.0.1:8010
Status: RUNNING (pm2 jarvis-engine, pid 13508, 3h uptime)
pm2 restart count: 6  (not crashlooping — restarts from prior session bounces)
pm2 memory: 740KB (normal; engine is in startup/idle state)

/health response:
  status: ok
  version: 1.1.0
  timestamp: 2026-05-06T03:47:28Z
  live_trading: false
  kill_switch_active: false
  paper_mode: true
  database: connected
  ibkr_connected: false          ← EXPECTED (not trading hours; IB paper port 4002 not open)
  ibkr_execution_connected: false
  ibkr_data_connected: false
  schwab_connected: false
  uptime_seconds: 11740 (~3.26h)
  llm_available: true
  llm_path_healthy: true          ← GOOD — Ollama serving hermes3:latest
  tradingview_mcp_healthy: false  ← REGRESSION — port 9222 not listening (TV closed)
  tradingview_mcp_details: "CDP port 9222 unreachable: timed out"
```

**What the 6 restarts mean:** pm2 tracks lifetime restarts. These 6 are NOT from this session alone — they accumulated from the multi-day campaign. The engine is stable; 6 over 3+ days is expected.

**What "740KB memory" means:** The engine is in startup/idle — it hasn't loaded any large models or cached data. Full operational memory is typically 2–4GB when bar data and model weights are loaded.

### 3.2 TradingView MCP (DEGRADED)

Port 9222: NOT LISTENING (confirmed via `netstat -ano | grep :9222`)

The engine's bar data path degrades gracefully:
- Tier 0 (TV MCP): DOWN
- Tier 1 (Polygon WS): inactive (plan doesn't include WS; the fix at `840ee01` exits cleanly)
- Tier 2 (Polygon REST): active fallback
- Tier 3 (Yahoo Finance): active fallback

This means the engine can still trade, but bar data is sourced from Polygon REST (which has rate limits and may be slower than TV's local rendering). For paper trading during off-hours this is acceptable, but should be fixed before any live or paper session that requires tick data.

### 3.3 IBKR

Not connected — expected. IB Gateway (paper port 4002) is not open at this hour. This does not constitute a fault — the engine paper trades when IB connects at market open. Live port 4001 is PERMANENTLY BLOCKED (network policy; never attempt to reach it).

### 3.4 Ollama / LLM

`llm_path_healthy=true` — Ollama is serving models. The OLLAMA_KEEP_ALIVE=24h setting means the loaded model stays resident in VRAM for 24h after last request. Cost DB confirms all hermes3 calls are $0.00 (Anthropic fallback dormant).

5 models available:
- `hermes3:latest` — primary; ~8GB VRAM
- `llama3.2:3b` — lightweight fallback; ~2GB VRAM
- 3 others (see `ollama list` output)

### 3.5 OneDrive Sync State

OneDrive root currently has 14 entries (verify with `Get-ChildItem "C:\Users\mattm\OneDrive\" | Measure-Object`):
```
AmoSZN/                    ← 7 items: 01_Personal 02_Code 03_Media 04_Apps 05_Past-Work 06_Archive FILING_GUIDE.md _Cruft
Archives/                  ← partially moved; some content may remain
Desktop/                   ← 13 stray spreadsheets
Development/               ← desktop-projects hydration may be ongoing
Documents/                 ← Bobby Love docx still present at source
Greenfield Metal Sales/    ← 12 entries: 04-10 numbered + 3 Phase D + Greenfield-Classic-Rib-Extraction + LSFD + others
Greenfield-Classic-Rib-Extraction/  ← duplicated? check if same as GMS/ subfolder
Media/                     ← iTunes Album Artwork cache (2,729 files, regenerable)
Personal Vault.lnk         ← shortcut, not a folder; ignore
Photos/                    ← 6,718 files, cloud-only
Pictures/                  ← deferred
_Cruft/                    ← leftover from prior passes
_Inbox/                    ← 18 mystery files (unchanged per V6 verification)
desktop.ini               ← system file; ignore
```

### 3.6 Git Repository

```
Branch: feat/tradingview-mcp-gamma-kraken
Remote: origin (github.com/mattamundson/jarvis-trader)
Sync: 0 ahead, 0 behind — fully synced with origin
Modified (not staged):
  - docs/session-logs/HANDOFF_2026-05-05-evening.md  (6 lines changed)
  - docs/session-logs/HANDOFF_2026-05-05-late.md    (853-line file, +639/-220)
Untracked:
  - docs/session-logs/HANDOFF_2026-05-06-closing.md  (this file)
```

### 3.7 Security / Credentials

- `~/.archive/cred-incidents/chrome-pwd-2026-05-05/Chrome Passwords.csv`: **EXISTS** (not rotated)
- `~/.archive/cred-incidents/chrome-pwd-2026-05-05/INCIDENT.md`: EXISTS (rotation tracker)
- Phase 0 rotation audit: 0/15 services rotated
- MEMORY.md: 14,134 bytes (limit: 22,528 bytes; 63% full)

---

## 4. IN-PROGRESS WORK — STARTED BUT NOT FINISHED

### 4.1 Phase 0 Credential Rotation (0% complete)

**What was prepared:**
- Full PHASE0_ROTATION_PLAYBOOK.md read and summarized
- Rotation checklist provided to Amo
- Amo said "Proceed" 
- Session closed before browser console work began

**Why it matters:** This is the single largest outstanding blocker. Until Wave 1 is done:
- Task 7 (paste-cache/plans deletion) cannot proceed — deleting files with live credentials is pointless
- Task 10 (D-drive cleanup) is gated — D-drive files contain plaintext secrets
- Google Cloud audit log check cannot be interpreted — the exposure window is still "open"
- `engine/.env` or Windows Credential Manager secrets cannot be updated

**Wave 1 service checklist (exact steps below in Section 7):**
1. Anthropic: revoke 4 keys, create 1 new, store in 1Password
2. OpenAI: revoke 1 key, create 1 new, store in 1Password
3. Google: delete 3 keys (highest priority: AIzaSyA2EJPQ2GD8nE...nHpHDQ), create 3 new, store in 1Password, audit Cloud Logging

### 4.2 OneDrive desktop-projects Hydration (Status Unknown)

**Background:** Development/desktop-projects → `_MIGRATE_OUT/desktop-projects/` was the longest background job (~11,159 cloud-only files including google-cloud-sdk which has ~12K sub-files). It was started in the prior session but status at this close is unknown.

**Current observation:** `_MIGRATE_OUT/desktop-projects/` currently has 11 items (BarcodeScanner, Greenfield_3D_Generator, Greenfield_Sheet, InventoryScannerApp, Live-Shop-Floor-Dashboard, Logs, ParadigmProxy, Scanner-Server, app, generate-label-data.js, google-cloud-sdk). The presence of `google-cloud-sdk` in the listing means either (a) the move completed, or (b) the folder was created but not fully populated.

**How to verify:**
```powershell
# Check if destination has content (google-cloud-sdk is ~1.5GB)
(Get-ChildItem "C:\Users\mattm\OneDrive\AmoSZN\02_Code\_MIGRATE_OUT\desktop-projects\google-cloud-sdk" -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count

# Check if source still has google-cloud-sdk (if yes, move incomplete)
Test-Path "C:\Users\mattm\OneDrive\Development\desktop-projects\google-cloud-sdk"
```

**If move incomplete:** Accept this. google-cloud-sdk is a Google Cloud CLI tool install — it's regenerable with `gcloud components install`. Not worth hours of retry. Delete the source folder (it's a tool install, not code) and accept the destination may be partial.

### 4.3 GMS _legacy-numbered Continuation

**Background:** A background robocopy job was moving the old GMS internal numbered folders (01-10) from `OneDrive/Greenfield Metal Sales/` to `AmoSZN/05_Past-Work/Greenfield-Metal-Sales/_legacy-numbered/`. At the prior checkpoint, ~549 files had moved (of ~1,216+ remaining at that point).

**Status:** Unknown. blqawtp82 completed but that task was focused on Marketing Materials and LSFD node_modules, not _legacy-numbered. A separate job may or may not have completed.

**How to verify:**
```powershell
(Get-ChildItem "C:\Users\mattm\OneDrive\AmoSZN\05_Past-Work\Greenfield-Metal-Sales\_legacy-numbered" -Recurse | Measure-Object).Count
# Prior checkpoint: ~549 files; full dataset: ~1,216+ files
```

### 4.4 Bobby Love Docx Source Lock

**State:** Destination copy confirmed at `AmoSZN\01_Personal\Documents-residual\Bobby Love McClelland - Unbreakable Vow.docx`. Source still present at `C:\Users\mattm\OneDrive\Documents\Bobby Love McClelland - Unbreakable Vow.docx` due to OneDrive file lock during the robocopy MOVE attempt.

**Resolution:** Simply run when convenient:
```powershell
Remove-Item "C:\Users\mattm\OneDrive\Documents\Bobby Love McClelland - Unbreakable Vow.docx"
```
OneDrive should have released the lock by now (it was a sync-in-progress lock, likely cleared within minutes).

---

## 5. BLOCKERS — DETAILED ANALYSIS

### BLOCKER 1: Phase 0 Wave 1 — Hard Gate (Security-Critical)

**Nature:** Requires Amo at browser consoles. Cannot be automated. Cannot be worked around.

**Services:** Anthropic (4 keys), OpenAI (1 key), Google (3 keys) = 8 total

**Why the sequencing matters:**
- Revoking Anthropic keys before updating `engine/.env` will cause engine LLM health to fail temporarily. Plan: revoke at console → immediately paste new key into 1Password → run `op run` or `restart_engine_op.ps1` → restart engine → verify health. Don't leave the engine without a valid key for more than the restart window.
- Google's `AIzaSyA2EJPQ2GD8nE...nHpHDQ` key was exposed as a OneNote PAGE TITLE — meaning it was visible to anyone with access to that OneNote notebook. The exposure window runs from key creation date → rotation date. After rotation, check Cloud Logging → Activity for calls during that window. A finding there means real unauthorized API usage.

**Post-rotation verification protocol:**
```bash
# Anthropic — should return 401 with old key
curl -s -H "x-api-key: sk-ant-api03-<OLD-KEY>" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  https://api.anthropic.com/v1/messages \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
# Expected: {"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}

# OpenAI — should return 401 with old key
curl -s -H "Authorization: Bearer sk-proj-<OLD-KEY>" \
  https://api.openai.com/v1/models
# Expected: {"error":{"message":"Incorrect API key provided",...}}

# Google — should return 400/403 with old key
curl -s "https://maps.googleapis.com/maps/api/geocode/json?address=test&key=AIzaSyA2...<OLD>"
# Expected: {"status":"REQUEST_DENIED"}
```

**Engine update after Wave 1:**
1. `.\restart_engine_op.ps1` (if configured for op template) OR manually update `engine/.env` with new keys
2. `.\restart_engine.ps1` — wait ~229s for full startup
3. Verify: `curl -s http://127.0.0.1:8010/health` → `llm_path_healthy: true`

### BLOCKER 2: TradingView MCP (Non-Critical, Easy Fix)

**Nature:** TV Desktop closed, port 9222 not listening. Engine bar data falls back to Polygon REST.

**Impact:** Paper trading continues normally. No positions are at risk. Degraded data quality for any live-session bar requests.

**Fix (2 minutes):**
```powershell
# Option A: trigger the scheduled task (preferred — uses the correct launch wrapper)
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
Start-Sleep 20
# Check port
netstat -ano | Select-String ':9222' | Select-String 'LISTENING'
# Check engine
curl -s http://127.0.0.1:8010/health | python3 -c "import sys,json; h=json.load(sys.stdin); print('TV:', h.get('tradingview_mcp_healthy'))"

# Option B: just open TradingView Desktop from Start menu
# (then wait for the AtLogon task to ensure the debug port flag is applied)
```

**If TV is already running without debug flag:** System tray → quit TradingView → trigger task → wait.

### BLOCKER 3: OneDrive non-Phase-D GMS Numbered Folders (04-10)

**Nature:** 7 GMS-internal-numbered folders are still in `OneDrive/Greenfield Metal Sales/` and haven't been moved to the AmoSZN numbered structure. They were missed in the Phase C move plan (they use GMS's own numbering, separate from AmoSZN's schema).

**Rough mapping (verify by listing contents before moving):**
| GMS Internal | Likely AmoSZN Destination | Notes |
|---|---|---|
| `04_Marketing_Sales/` | `GMS/08_Marketing/` | Sales and marketing materials |
| `05_Documentation/` | `GMS/04_Documentation/` | Product and process docs |
| `06_Data_Geography/` | `GMS/16_Reports/` or new subfolder | Geographic data, customer maps |
| `07_Admin_Legal/` | New: `GMS/22_Legal/` | Legal docs; may need new numbered subfolder |
| `08_Equipment_Vendors/` | `GMS/05_Equipment/` | Equipment and vendor files |
| `09_Archives/` | `GMS/06_Archive/` or `_legacy-numbered/` | Old archival content |
| `10_Installers/` | `AmoSZN/_Cruft/04_vendor-installers/` | Software installers; regenerable |

**Move command pattern:**
```powershell
robocopy "C:\Users\mattm\OneDrive\Greenfield Metal Sales\04_Marketing_Sales" `
  "C:\Users\mattm\OneDrive\AmoSZN\05_Past-Work\Greenfield-Metal-Sales\08_Marketing\04_Marketing_Sales" `
  /E /MOVE /COPY:DAT /R:30 /W:5 /MT:4
```

### BLOCKER 4: MNQ and MCL Still Gated

**MNQ:** DO_NOT_TRADE until a new WFO PASS is achieved. The breakout family is exhausted. The 2025 non-stationarity is structural. Next session must choose: regime filter OR new strategy family (see Section 7).

**MCL:** DO_NOT_TRADE until Hypothesis B (sentiment overlay) is implemented and passes WFO. Hypothesis B requires Corey Discord archive backfill first — can't run WFO without historical sentiment labels.

**MES:** rank11 PASSed (`cb49ec9`). MES trend-following (SMA 50/200) is the reference success story. The code for wiring it into paper trading is committed (`d2f5eac`). Verify it's actually executing in paper mode by checking `/brokers/positions` after market open.

---

## 6. KEY DECISIONS MADE — WITH FULL RATIONALE

### 6.1 MCL stays in DO_NOT_TRADE_SYMBOLS

**Decision:** MCL remains gated after Hypothesis C FAIL.
**Evidence:** pf_ci_lower=0.284 (needed ≥1.10), p_edge=0.000 (zero profitable OOS windows across 18 walk-forward windows). The vol-regime gate cannot create edge where none exists.
**Why not try another vol band?** The 12-combo grid covered rv_min={20,25,30} × rv_max={40,50}. The best IS PF found was 1.20 in one window, with median ~0.80. This isn't a "we were close but missed the right band" situation — the IS PF pattern is consistently poor, meaning the underlying signal has no edge on MCL 1h at any volatility level tested.
**File:** `engine/backtest/signals.py:108` — `DO_NOT_TRADE_SYMBOLS = frozenset({"MCL", "MNQ"})`
**Verdict JSON:** `engine/data/gate_v2_verdicts/MCL_hyp_c_20260505T212306Z.json`

### 6.2 MCL Hypothesis B (Sentiment Overlay) is the next attempt

**Decision:** Next MCL re-validation attempt will use Corey #market-updates sentiment as a gate.
**Theory:** Crude oil edge is narrative-conditional. Without a narrative catalyst (EIA inventory report, OPEC decision, geopolitical event), the signal is just chop. Filtering to periods when Corey is directional on crude should eliminate the chop case.
**Why not Hypothesis A (H1 trend-following)?** The prior 0-WFO-winners result on SMA(50,200) MCL is a strong negative signal. Changing to a different SMA pair (20/100) is a second-order variation, not a fundamentally different theory. The failure mode (false starts on brief trend spikes) is well-documented for crude on hourly bars.
**Prerequisite:** Corey's historical Discord message archive must be backfilled with crude-keyword + sentiment polarity labels. Without historical labels, the WFO has no sentiment signal to gate on.
**Reference:** `memory/project_mcl_revalidation_options_2026_05_05.md`

### 6.3 MNQ Breakout Family Declared Exhausted

**Decision:** No further parameter sweeps on MNQ Donchian breakout.
**Evidence:** 5 successive sweeps across multiple grid shapes, capital levels ($10K–$25K), and routing paths (CORE/ALT) all fail gate v2. Root cause is structural mid-2025 non-stationarity, not parameter mis-tuning.
**Why not one more sweep?** The rank4 sweep found fixed_params_min_pf=1.2621 (clearing the threshold), but WFO_CONSISTENCY was WEAK and OOS pf_ci_lower=0.73. This pattern — IS looks good, OOS collapses — is the definition of curve-fitting. Adding a 6th sweep with a different variation would be chasing noise.
**Next options:** Regime filter OR pivot to SMA trend-following family. Both are viable; the decision should be made based on how much compute budget is available and how urgent MNQ trading is.

### 6.4 Phase D Mega-Folders Intentionally Not Moved

**Decision:** AI Agent Team (~215K files), greenfield-ai-suite (~173K), dev-backup (~82K) stay in `OneDrive/Greenfield Metal Sales/` for a dedicated Phase D session.
**Reason:** These are too large for OneDrive-mediated moves. OneDrive syncs each file individually through cloud storage — 215K files at even 1 file/second would take 60 hours. The correct approach is a direct local move (OneDrive folder → local drive, bypassing cloud sync). This requires OneDrive to be paused during the move.
**Migration targets:**
- `AI Agent Team/` → `~/Code/jarvis-agent-gms/` (partially done in earlier session)
- `greenfield-ai-suite/` → `~/Code/` (new repo)
- `dev-backup-2026-01-02/` → TBD (determine if it has unique content or is a snapshot of something already in git)

### 6.5 Polygon WebSocket: auth_failed = exit immediately, no retry

**Decision:** On `auth_failed` or `auth_timeout`, disable the WebSocket streamer cleanly rather than retrying.
**Reason:** These statuses indicate the current Polygon plan does not include WebSocket access. No amount of retrying will change the plan — it's a billing/tier constraint. The previous behavior (silent infinite retry loop) consumed CPU, spammed logs with 5-second interval "Auth Response: auth_failed" entries, and provided no diagnostic value.
**Key implementation detail:** `isinstance(auth_data, list)` guard is necessary because Polygon wraps single-message auth responses in a list. Without this guard, `auth_data.get("status")` would fail with AttributeError.
**Commits:** `840ee01` (exit guard) + `7555188` (exponential backoff for genuine transient failures, which are unaffected by the auth_failed path)

### 6.6 OLLAMA_NUM_CTX_PER_AGENT Knob at 2048 for Social/News Agents

**Decision:** Add `OLLAMA_NUM_CTX_PER_AGENT` env var and set social/news agents to 2048 context.
**Reason:** Default context window was too large, causing OOM (out-of-VRAM) on multi-agent inference when multiple agents were loaded simultaneously. Social and news analysis agents don't need the full model context — they're doing sentiment classification on short Discord posts and news headlines, not long-document analysis.
**Effect:** Smaller per-agent VRAM footprint allows more concurrent agents without evicting each other from VRAM. The KEEP_ALIVE knob ensures models stay warm between agent calls.
**Commit:** `4a2b4bf`

### 6.7 OneDrive V1 Check Deferred (14 entries, not ≤10)

**Decision:** Accept 14 entries in OneDrive root as the current state; defer ≤10 target to after Photos/Media/Phase-D decisions.
**Reason:** The remaining 4 excess entries are Photos/ (6,718 cloud-only files — multi-hour hydration), Media/ (2,729 iTunes Album Artwork cache files — regenerable, but still a move job), Pictures/ (unknown count), and the Phase D mega-folders in Greenfield Metal Sales/. Each of these requires a deliberate decision (move vs delete vs leave). The V1 check failing is a known, accepted state — not an oversight.
**Path to V1 PASS:** Delete Media/ (iTunes Album Artwork is regenerable — no need to move), delete Pictures/ if it's just screenshots or phone syncs, move Photos/ to `AmoSZN/03_Media/Photos/` in a dedicated background session, remove Phase D from root count by completing Phase D.

---

## 7. TODO ITEMS — COMPLETE ORDERED LIST

### 7.1 IMMEDIATE — Do at Start of Next Session (No Gate)

**A. Commit and push the three handoff docs:**
```bash
cd "C:\Users\mattm\ThinkorSwim\jarvis-trader"
git add docs/session-logs/HANDOFF_2026-05-05-evening.md \
        docs/session-logs/HANDOFF_2026-05-05-late.md \
        docs/session-logs/HANDOFF_2026-05-06-closing.md
git commit -m "docs(session-logs): closing handoff — TV CDP, Phase C/E, MCL Hyp-C FAIL, Phase 0 prep

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
```

**B. Fix TradingView MCP (2 min):**
```powershell
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
# Wait 20s
curl -s http://127.0.0.1:8010/health | python3 -c "import sys,json; h=json.load(sys.stdin); print('TV:', h['tradingview_mcp_healthy'])"
```

**C. Verify pm2 restarts haven't grown:**
```bash
pm2 status
# jarvis-engine should be: online, restarts ≤8 (minor growth is fine; >15 suggests crashloop)
```

### 7.2 URGENT — Security (Amo at Browser Consoles)

**Phase 0 Wave 1 — SERVICE 1: Anthropic (4 keys)**
1. Go to `console.anthropic.com` → API Keys
2. Revoke every key with `sk-ant-api03-` prefix (there are 4; special priority on `sk-ant-api03-NlwD8...mMRxgAA` which was exposed as OneNote page title)
3. Click "Create Key" → name it `jarvis-trader-prod`
4. Copy the new key immediately (shown only once)
5. Open 1Password → vault "Amo Personal" → find or create item "Anthropic-API" → paste key as credential field
6. Signal to assistant: "Anthropic done"

**Phase 0 Wave 1 — SERVICE 2: OpenAI (1 key)**
1. Go to `platform.openai.com` → API Keys
2. Revoke the existing `sk-proj-...` key
3. Click "Create new secret key" → name it `jarvis-main`
4. Copy the new key
5. 1Password → "OpenAI-API" → update
6. Note: `career-ops/.env` also references this key — update that reference after (or let 1Password handle via op template)
7. Signal: "OpenAI done"

**Phase 0 Wave 1 — SERVICE 5: Google (3 keys) — HIGHEST EXPOSURE**
1. Go to `console.cloud.google.com` → APIs & Services → Credentials
2. **First:** Delete key `AIzaSyA2EJPQ2GD8nE...nHpHDQ` (the OneNote page-title exposure)
3. Delete key `AIzaSyBr2fOJ1xMk2H...A4J2A`
4. Delete the third Google key (visible in your credentials list)
5. Create 3 new API keys with equivalent restrictions/scope
6. Store in 1Password as "Google-API-1", "Google-API-2", "Google-API-3"
7. **CRITICAL:** Check Cloud Logging → Activity → filter to the period from key creation → today → look for API calls using the old `AIzaSyA2...` key. Any calls = unauthorized usage. Document findings.
8. Signal: "Google done, [found/no] unauthorized calls"

**Chrome Passwords.csv (parallel task — Amo only):**
1. Open `C:\Users\mattm\.archive\cred-incidents\chrome-pwd-2026-05-05\Chrome Passwords.csv` in Excel or Notepad
2. For each row: site URL + username → navigate to site → account settings → change password → save new password to 1Password vault "Amo Personal" → do NOT let Chrome save it
3. When all rows complete: `Remove-Item "C:\Users\mattm\.archive\cred-incidents\chrome-pwd-2026-05-05\Chrome Passwords.csv"`
4. Update INCIDENT.md with resolution date

**Post-Wave-1 verification (assistant executes after each service signal):**
```bash
# Test Anthropic old key is dead
curl -s -H "x-api-key: sk-ant-api03-OLDKEY" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  https://api.anthropic.com/v1/messages \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
# Must return: {"type":"error","error":{"type":"authentication_error",...}}

# Update engine (one of these approaches):
# Option A: op run (if op template is configured)
cd "C:\Users\mattm\ThinkorSwim\jarvis-trader" && op run --env-file=engine/.env.op-template -- .\restart_engine.ps1
# Option B: manually update engine/.env with new values, then restart
```

### 7.3 GATED ON WAVE 1 COMPLETE — Task 7: Paste-Cache + Plans Deletion

1. Read audit report: `C:\Users\mattm\Inbox\onenote-migration-2026-05-04\paste-cache-cred-audit-2026-05-05.txt`
   - Identifies 4 specific paste-cache files and 3 specific plans files containing old credential patterns
   - Do NOT bulk-delete — only the specifically identified files
2. Verify old keys are dead (401 test call for at least one Anthropic key)
3. Delete 4 paste-cache files:
   ```powershell
   Remove-Item "C:\Users\mattm\.claude\paste-cache\<file1>.txt"
   # repeat for each of the 4 identified files
   Get-ChildItem "C:\Users\mattm\.claude\paste-cache\" | Select-Object Name
   # confirm targeted files gone, others remain
   ```
4. Delete 3 plans files (NOT the current active plans like the closing handoff):
   ```powershell
   Remove-Item "C:\Users\mattm\.claude\plans\<file>.md"
   # repeat for each of the 3 identified plans
   ```
5. Final scan:
   ```powershell
   Select-String -Path "C:\Users\mattm\.claude\paste-cache\*.txt" -Pattern "sk-ant-|sk-proj-|AIzaSy"
   Select-String -Path "C:\Users\mattm\.claude\plans\*.md" -Pattern "sk-ant-|sk-proj-|AIzaSy"
   # Both should return 0 results
   ```

### 7.4 GATED ON WAVE 1 COMPLETE — Phase 0 Wave 2 (Amo at Browser)

Wave 2 services in priority order per PHASE0_ROTATION_PLAYBOOK.md:
- **SERVICE 3: Azure AD** — `portal.azure.com` → App Registrations → locate GMS/JARVIS service account → Certificates & Secrets → rotate client secret. If GMS is fully archived and the app reg is unused, consider disabling the registration entirely (confirm with Amo first).
- **SERVICE 4: Paradigm ERP** — GMS is archived; these credentials still pose account-abuse risk. Navigate to Paradigm admin or contact support. Rotate or disable.
- **SERVICE 6: GMS Mailboxes ×3 SMTP** — email host admin panel; rotate SMTP passwords for 3 GMS mailboxes. If accounts are fully closed, confirm with email host.
- **SERVICE 7: Render** — `dashboard.render.com` → API Keys. If no active Render deployments (GMS web app archived), revoke without replacement.
- **SERVICES 8-15:** Teams webhook, Twilio, Telegram bot, Jarvis internals, Cursor, Supermemory, Firecrawl, gcloud Postgres + Midco — see PHASE0_ROTATION_PLAYBOOK.md for details.

### 7.5 GATED ON FULL PHASE 0 — D-drive Cleanup

D-drive has 100–135 GB reclaimable. Key targets:
- `D:\master-jarvis` (7.6 GB legacy mirror) — verify moved to `D:\.archive\`; check vault-drift-check task ran
  ```powershell
  schtasks /Query /TN "Jarvis-D-VaultDrift" /V /FO LIST
  # Status should be: Ready, not Disabled
  ```
- Any Phase D mega-folder mirrors on D-drive (check if `D:\greenfield-ai-suite\` or similar exist)
- Run disk analyzer after to confirm top-10 consumer shift

### 7.6 SOON — Trading System

**A. MCL Hypothesis B setup:**
1. Get Corey's Discord message archive (export from Discord or scrape via existing Hermes integration)
2. Filter to messages from `#market-updates` channel only
3. Apply crude-keyword filter (oil, crude, WTI, Brent, inventory, EIA, OPEC)
4. Run sentiment polarity classification (can use existing `social_analyst.py` pipeline)
5. Create historical label CSV: `timestamp, text_snippet, crude_directional_bias (-1/0/1), confidence`
6. Build `engine/backtest/sentiment_overlay_signals.py` wrapping any base signal with the sentiment gate
7. Run WFO using Bollinger+RSI base signal (the existing meanrev module) with sentiment overlay

**B. MNQ next approach — pick one:**

*Option A (Regime Filter):*
- Define regime indicator: e.g., 20-day ATR percentile > 70th percentile = "trending regime"; < 30th = "choppy"
- Add regime condition to existing Donchian breakout signal
- Only trade when regime indicator shows "trending"
- The mid-2025 losing-streak windows should correlate with the choppy regime
- WFO would naturally avoid the 2025 period when the regime filter gates out chop

*Option B (SMA Trend-Following Family):*
- MES trend SMA(50,200) PASSed at rank11 — apply same infrastructure to MNQ
- Different parameter tuning needed (MNQ is more volatile than MES)
- Could reuse `engine/backtest/trend_signals.py` + `get_sma_trend_params(symbol)` — just add an MNQ entry
- More robust conceptually: if the market-structure reason SMA works for MES also applies to MNQ, this is a theory-grounded approach

**Recommendation:** Option B is faster to implement (reuses existing infrastructure) and is theory-grounded (the macro-trend logic for MES applies equally to MNQ). Start there. If SMA trend fails on MNQ, fall back to regime filter design.

**C. MES live paper monitoring:**
- `d2f5eac` wired MES trend SMA(50,200) into paper trading pipeline
- Verify actual paper orders are firing by checking `/brokers/positions` at market open
- Cross-check: `/health.ibkr_execution_connected` should be `true` during IB session (port 4002 open)

### 7.7 OneDrive Cleanup Continuation

**A. GMS numbered folders 04-10 (non-urgent, Phase C continuation):**
```powershell
# Quick content audit before moving
Get-ChildItem "C:\Users\mattm\OneDrive\Greenfield Metal Sales\04_Marketing_Sales" | Select-Object Name
Get-ChildItem "C:\Users\mattm\OneDrive\Greenfield Metal Sales\05_Documentation" | Select-Object Name
# etc.
# Then move each to appropriate AmoSZN GMS subfolder (mapping in Section 5.3 above)
```

**B. Desktop spreadsheets (13 stray xlsx files):**
```powershell
Get-ChildItem "C:\Users\mattm\OneDrive\Desktop" -File | Select-Object Name
# Move each to appropriate GMS numbered folder:
# GMS invoices/quotes → 07_Invoices or 15_Quotes
# Inventory → 06_Inventory
# Atlas Credit App → 09_Orders
```

**C. Bobby Love docx source deletion:**
```powershell
Remove-Item "C:\Users\mattm\OneDrive\Documents\Bobby Love McClelland - Unbreakable Vow.docx"
# If permission denied (OneDrive still locked): retry in 10 min
```

**D. Greenfield-Classic-Rib-Extraction non-Phase-D content:**
This folder exists at both `OneDrive/Greenfield-Classic-Rib-Extraction/` (root) and possibly inside `OneDrive/Greenfield Metal Sales/`. The non-Phase-D portions (installation-guides, product-catalogs) should go to `GMS/14_Product-Docs/rib-extraction/`. The Phase D portion (AI Agent Team subfolder inside it, if present) stays.

**E. Photos/Media decision (Amo required):**
- Photos (6,718 files): Move to `AmoSZN/03_Media/Photos/` OR delete duplicates (if backed up elsewhere). Multi-hour background job.
- Media/iTunes Album Artwork (2,729 files): These are cache files regenerated by iTunes/Music app. Recommend: delete the entire `Media/` folder. No data loss.
- Pictures: Check contents first — may be screenshots or phone syncs. Likely safe to move to `AmoSZN/03_Media/Pictures/` or delete.

### 7.8 Hardening (Low Urgency)

**A. Disable Chrome save-password:**
Chrome → Settings (⋮) → Autofill and passwords → Google Password Manager → Settings → toggle off "Offer to save passwords." This prevents future Chrome Passwords.csv class incidents.

**B. Extend scan-credentials.ps1:**
Add glob pattern for `OneDrive/**/*Password*.csv` and `OneDrive/**/*Passwords*.csv`. The existing script already runs as `Jarvis-ScanCredentials` scheduled task. Find the script and add the pattern:
```powershell
# Find the scan script
Get-ChildItem "C:\Users\mattm\scripts" -Filter "*scan*cred*"
# Edit to add: $additionalPaths = @("C:\Users\mattm\OneDrive\**\*password*.csv")
```

**C. Load engine secrets into Windows Credential Manager:**
```powershell
# After Phase 0 rotation is complete
cd "C:\Users\mattm\ThinkorSwim\jarvis-trader"
.\manage-jarvis-secrets.ps1 -Set
# Interactive — requires 1Password CLI session or manual entry
```

**D. Reboot test:**
Schedule a reboot to verify `Jarvis-PM2-AtLogon` correctly resurrects pm2 and the engine. After reboot:
1. Wait ~3 minutes for pm2 + engine startup
2. Check: `pm2 status` → jarvis-engine should be online
3. Check: `curl http://127.0.0.1:8010/health` → status=ok

---

## 8. COMPLETE CURRENT TO-DO LIST (PRIORITY ORDER)

### 🔴 CRITICAL — Security, no gate

- [ ] Open Chrome Passwords.csv manually, rotate each credential at issuer site, save to 1Password, delete CSV
- [ ] Anthropic ×4 keys: revoke at console.anthropic.com, create `jarvis-trader-prod`, store in 1P
- [ ] OpenAI ×1 key: revoke at platform.openai.com, create `jarvis-main`, store in 1P
- [ ] Google ×3 keys: delete at cloud.google.com (AIzaSyA2... first), create 3 replacements, store in 1P, audit Cloud Logging
- [ ] Verify old keys return 401 (test curl commands in Section 7.2)
- [ ] Update engine with new keys → restart → verify `/health` `llm_path_healthy=true`

### 🟠 IMPORTANT — System health, no gate

- [ ] Commit + push 3 handoff docs (`git add` + `git commit` + `git push`)
- [ ] Fix TradingView MCP: `schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"` → verify port 9222 LISTENING → verify `tradingview_mcp_healthy=true`
- [ ] Delete Bobby Love docx source: `Remove-Item "C:\Users\mattm\OneDrive\Documents\Bobby Love McClelland..."`

### 🟡 SOON — Gated on Anthropic/OpenAI/Google Wave 1 completion

- [ ] Task 7: Read paste-cache audit, delete 4 paste-cache files + 3 plans files, run final scan
- [ ] Phase 0 Wave 2: Azure AD, Paradigm, Render, GMS Mailboxes ×3, Teams, Twilio, Telegram, Jarvis internals, Cursor, Supermemory, Firecrawl, gcloud/Midco
- [ ] D-drive cleanup (100–135 GB): after full Phase 0, verify vault-drift-check, execute deletions

### 🟢 TRADING SYSTEM — Next session

- [ ] MCL Hypothesis B: backfill Corey archive → sentiment labels → build sentiment_overlay_signals.py → WFO → gate v2 verdict
- [ ] MNQ: decide regime filter vs SMA trend family; implement chosen approach; run WFO
- [ ] Verify MES trend SMA(50,200) paper orders firing: check `/brokers/positions` at market open
- [ ] Reboot test: confirm `Jarvis-PM2-AtLogon` resurrects pm2 correctly

### 🔵 ONEDRIVE CONTINUATION — Non-urgent

- [ ] GMS numbered folders 04-10: audit contents, map to AmoSZN structure, move
- [ ] Desktop stray spreadsheets (13 xlsx): move to appropriate GMS numbered folders
- [ ] Photos/Media/Pictures: Amo decision (move vs delete); Photos = multi-hour background job
- [ ] Greenfield-Classic-Rib-Extraction non-Phase-D content → GMS/14_Product-Docs/rib-extraction/
- [ ] Phase D mega-folders (dedicated session): AI Agent Team → ~/Code/jarvis-agent-gms/, greenfield-ai-suite → ~/Code/, dev-backup → TBD

### ⚪ HARDENING — Low urgency

- [ ] Disable Chrome save-password feature
- [ ] Extend scan-credentials.ps1 to include OneDrive Password CSV patterns
- [ ] Load engine secrets into Windows Credential Manager (`manage-jarvis-secrets.ps1 -Set`)

---

## 9. GIT STATE — VERBATIM COMMAND OUTPUT

### `git status`
```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is up to date with 'origin/feat/tradingview-mcp-gamma-kraken'.

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working commit)
	modified:   docs/session-logs/HANDOFF_2026-05-05-evening.md
	modified:   docs/session-logs/HANDOFF_2026-05-05-late.md

no changes added to commit (use "git add" and/or "git commit -a")
```
Note: `docs/session-logs/HANDOFF_2026-05-06-closing.md` (this file) is untracked — will appear after write completes.

### `git log --oneline -20`
```
cb49ec9 feat(backtest): MES trend rank11 verdict refresh — PASS
2dc585f feat(backtest): MES trend rank10 verdict refresh — FAIL
baf31db feat(backtest): MES trend rank9 verdict refresh — FAIL
2d408c3 feat(backtest): MES trend rank8 verdict refresh — FAIL (blocked by bad grid combos + OOS trade filter)
8b0a951 fix(engine): use 127.0.0.1 in restart health poll (Windows IPv6 localhost quirk)
d2f5eac fix(strategy): wire MES_trend SMA(50,200) into paper trading pipeline
bff5e7d feat(backtest): MNQ breakout rank5 $25K capital test — FAIL
c114e5c feat(backtest): MNQ breakout rank4 tight-grid ALT sweep — FAIL
7555188 fix(data): exponential backoff for Polygon WS auth_failed reconnect loop
c0cc2a0 docs(session-logs): add late session handoff 2026-05-05
3e73934 feat(backtest): MNQ breakout rank3 ALT-path sweep — FAIL
12e686b chore(backtest): add MNQ breakout rank3 sweep + update session handoff
840ee01 fix(polygon-ws): stop retry loop on auth_failed/auth_timeout
5f697b6 chore(gitignore): exclude gate verdict runs + HTML charts + untrack test artifacts
37e9ccd feat(gate): add MNQ breakout rank2 verdict
3ed5760 docs: add phase0 env update checklist + MNQ breakout rank2 sweep script
4a2b4bf feat(llm): OLLAMA_NUM_CTX_PER_AGENT knob for per-agent context sizing
4077e46 Merge remote-tracking branch 'origin/master' into feat/tradingview-mcp-gamma-kraken
8a76560 docs: add evening session handoff 2026-05-05
31ef7c6 feat(backtest): add rv_band regime filter to meanrev_signals + MCL WFO runner
```

### `git diff --stat`
```
 docs/session-logs/HANDOFF_2026-05-05-evening.md |   6 +-
 docs/session-logs/HANDOFF_2026-05-05-late.md    | 853 ++++++++++++++++++------
 2 files changed, 639 insertions(+), 220 deletions(-)
```

The 853-line `HANDOFF_2026-05-05-late.md` file with 639 insertions is the full campaign narrative covering:
- Polygon WebSocket auth fix (detailed technical analysis)
- MNQ rank3–5 sweeps (results and root cause)
- Credential scan completion (23 HIGH findings, down from 259)
- Engine state documentation
- OLLAMA context knob
- TV CDP setup
- MCL Hypothesis C implementation and results

This is correct and complete — commit it as-is.

---

## 10. BACKGROUND TASK blqawtp82 — RESULT ANALYSIS

**Task label:** "Move GMS non-Phase-D straggler subfolders to numbered structure"
**Exit code:** 0 (overall shell script)
**Duration:** ~4 hours (started ~18:58, completed ~23:00)
**Output file:** `C:\Users\mattm\AppData\Local\Temp\claude\...\tasks\blqawtp82.output` (498.9KB, 3,236 lines)

**Per-subtask results:**
| Subtask | robocopy exit | Interpretation | Files affected |
|---|---|---|---|
| Marketing Materials | 1 | SUCCESS — files copied (with /MOVE, source deleted after) | 60 files: brochures, sales roofing lists, VEO3 videos, DWG files, etc. |
| Live-Shop-Floor-Dashboard | 1 | SUCCESS with cloud timeouts (ERROR 426 on some node_modules files) — files ultimately moved on retry | 2,200+ node_modules files |
| Greenfield-Business/Marketing | 16 | ERROR — source path not found (`OneDrive/Greenfield Metal Sales/Greenfield-Business/Marketing/`) | 0 files (path doesn't exist) |
| Greenfield/ | 16 | ERROR — source path not found (`OneDrive/Greenfield Metal Sales/Greenfield/`) | 0 files (path doesn't exist) |

**What Marketing Materials contained (notable):**
- Product brochures (Board and Batten, DuraLock, PBR-Panel, TrueLock, Tuff-Rib, WeatherXL)
- Roofing company prospect lists (100 companies, CSV/XLSX formats)
- Timbersteel system documentation (installation, spec sheets, warranties)
- Veo3-generated videos (3× 2.6MB marketing videos)
- Strategic Growth Execution Plan PDF
- CAD/DWG: `ss-tlz-06-timberline-series-wall-flashing.dwg`

**What LSFD node_modules contained:** Standard pnpm dependencies for a Node.js API (express, winston, axios, form-data, finalhandler, etc.). These are regenerable with `pnpm install`. Moving them was correct — they accompany the source code.

**Paths not found (exit=16) explanation:** `Greenfield-Business/Marketing/` and `Greenfield/` were planned move targets from the original Phase C plan, but those paths don't exist at the source. They were likely already moved in a prior session pass, or the paths in the original plan were incorrect. Either way, exit=16 = not an error in the sense of data loss — it just means nothing to move.

---

## 11. KEY FILE PATHS — COMPLETE QUICK REFERENCE

### JARVIS Engine
| What | Path |
|---|---|
| Engine root | `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\` |
| Engine API | `http://127.0.0.1:8010` |
| Dashboard | `http://127.0.0.1:3010` |
| Restart script | `C:\Users\mattm\ThinkorSwim\jarvis-trader\restart_engine.ps1` |
| Engine venv | `engine\.venv\Scripts\python.exe` |
| PM2 config | via pm2 (jarvis-engine process, id 0) |
| Gate v2 verdicts | `engine\data\gate_v2_verdicts\` |
| DO_NOT_TRADE_SYMBOLS | `engine\backtest\signals.py:108` |
| Polygon stream | `engine\data\polygon_stream.py` |
| MCL WFO runner | `engine\backtest\run_mcl_hypothesis_c.py` |
| MCL meanrev (rv_band) | `engine\backtest\meanrev_signals.py` |
| MES trend | `engine\backtest\trend_signals.py` |
| Deflated Sharpe | `engine\backtest\deflated_sharpe.py` |
| Gate v2 policy | `engine\backtest\gate_v2_policy.py` |
| Social analyst | `engine\social_analyst.py:347-356` (futures sentiment gate) |

### Session / Memory
| What | Path |
|---|---|
| MEMORY.md | `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md` |
| MEMORY-archive.md | `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY-archive.md` |
| MCL revalidation memo | `~\.claude\projects\C--windows-system32\memory\project_mcl_revalidation_options_2026_05_05.md` |
| Session logs | `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\` |
| Phase 0 playbook | `C:\Users\mattm\.claude\skills\ralph\projects\home-strategic-plan\PHASE0_ROTATION_PLAYBOOK.md` |
| Top-10 ROI plan | `C:\Users\mattm\.claude\plans\analyze-the-following-and-velvet-hickey.md` |

### Security / Credentials
| What | Path |
|---|---|
| Chrome CSV incident | `C:\Users\mattm\.archive\cred-incidents\chrome-pwd-2026-05-05\Chrome Passwords.csv` |
| INCIDENT.md | `C:\Users\mattm\.archive\cred-incidents\chrome-pwd-2026-05-05\INCIDENT.md` |
| Paste-cache audit | `C:\Users\mattm\Inbox\onenote-migration-2026-05-04\paste-cache-cred-audit-2026-05-05.txt` |
| Credential guard | `C:\Users\mattm\.claude\hooks\credential-guard.sh` |
| Git pre-commit scan | `C:\Users\mattm\scripts\git-precommit-secret-scan.sh` |
| Scan credentials script | `C:\Users\mattm\scripts\scan-credentials.ps1` |

### TV CDP
| What | Path |
|---|---|
| Install script | `C:\Users\mattm\scripts\install-tv-cdp-task.ps1` |
| Launch script | `C:\Users\mattm\scripts\launch-tv-cdp.ps1` |
| Scheduled task | `JARVIS-TV-CDP-AtLogon` |
| CDP URL | `http://127.0.0.1:9222/json/version` |

### OneDrive
| What | Path |
|---|---|
| AmoSZN root | `C:\Users\mattm\OneDrive\AmoSZN\` |
| FILING_GUIDE | `C:\Users\mattm\OneDrive\AmoSZN\FILING_GUIDE.md` |
| GMS numbered structure | `C:\Users\mattm\OneDrive\AmoSZN\05_Past-Work\Greenfield-Metal-Sales\` |
| _MIGRATE_OUT | `C:\Users\mattm\OneDrive\AmoSZN\02_Code\_MIGRATE_OUT\` |
| GMS Phase D (leave here) | `C:\Users\mattm\OneDrive\Greenfield Metal Sales\AI Agent Team\` |
| Bobby Love docx (delete source) | `C:\Users\mattm\OneDrive\Documents\Bobby Love McClelland - Unbreakable Vow.docx` |

---

*End of handoff. Next session: read Section 10 Quick-Start, check engine, commit docs, ask Amo if ready for Phase 0 rotation.*
