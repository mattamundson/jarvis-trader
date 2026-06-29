# HANDOFF — Hermes Cron Recovery & Model-Routing Overhaul
**Date:** 2026-06-29 (continues work started 2026-06-26)
**Author session:** 58ea5745-dceb-460d-816d-f61344ac7087
**Scope:** Nous Research **Hermes** agent gateway (WSL/Ubuntu install at `~/.hermes`) — cron jobs were failing and flooding Telegram with ~400 failure alerts/day. Recovered the original failure, then uncovered and partially remediated a cascading billing/credit problem across all paid model providers.

> **READ FIRST — current one-line status:** Hermes gateway is **up** (PID 607900) and **connected** (Discord + Telegram), the *original* flood is **fixed**, but **both paid model providers (Anthropic + Google) are out of credits**. Config has been switched to a cheap/sustainable Haiku tier but is **NOT yet loaded** (needs a restart) and **Anthropic has $0 balance** (needs a top-up by Amo). Jobs currently fail to Anthropic-400 then time out on the local fallback.

---

## 1. SESSION SUMMARY (chronological)

### Part A — 2026-06-26 (original diagnosis + fix)
1. Investigated a Telegram flood of failed Hermes cron jobs (PLAN-ONLY diagnostic → `C:\Users\mattm\HERMES_FIX_PLAN.md`). Root cause: **gateway running stale in-memory config** pointed at an out-of-funds **Nous** account, plus `reasoning_effort: none` (broke a reasoning-mandatory endpoint), plus a **revoked Discord bot token** (401 on all delivery). Every agent cron job 401'd/400'd → failure alerts flooded Telegram.
2. **H3** — rotated `DISCORD_BOT_TOKEN` in `.env` to the valid token from 1Password (`Discord-Bot-Jarvis`).
3. **H2** — `agent.reasoning_effort` `none → medium`.
4. **H6** — fixed mis-cased `OpenROUTER_API_KEY → OPENROUTER_API_KEY`.
5. **H5** — paused a redundant/insecure backup cron job (`hermes-daily-backup`, id `5119907bb480`) — already covered by the Windows `Hermes-Nightly-Sync` task.
6. **H1** — main `model:` repointed off dead Nous → **Anthropic** (`claude-opus-4-7`); fallback chain set to Gemini.
7. **H4** — `nightly-vector-index` (id `5d6b754a31f9`) failing with SQLite **disk-I/O error**: root-caused to **vec0 (sqlite-vec) + WAL being incompatible with the `/mnt/c` drvfs/9p mount**. Rewrote `run-vec-index.py` to **build on ext4** and **publish a copy to `/mnt/c`**. Paused the cron job; ran the rebuild manually (~61k rows embedded via local Ollama, no disk-I/O error). Publish-swap to `/mnt/c` blocked by a Windows file lock (engine holds the db open) → completed index left staged as `vec_index.db.tmp`.
8. Restarted gateway (Amo ran `hermes-safe-restart.sh --force` via `!`). Verified: morning-brief job ran `ok` on `claude-opus-4-7/anthropic`, Discord + Telegram connected, zero Nous/reasoning/Discord errors.

### Part B — 2026-06-29 (verification + cascading-credit remediation) — THIS SESSION
9. **Verification (3 days post-restart):** original flood **dead** — 0 occurrences of Nous-401 / reasoning-400 / max-iterations / Discord-401 in 3 days; **34/38 jobs ok, 0 delivery failures**; gateway stable (no crashes). Discord delivery confirmed end-to-end.
10. **NEW issue #1 — Google Gemini out of prepay credits (429 RESOURCE_EXHAUSTED)**, started 06-29. Broke the cheap-tier jobs (`engine-watchdog` `*/5 * * * *`, `AI Triage on Capture`, `event-monitor`, `Research Scout - web+X`). Traced routing: unprofiled/skill jobs ride the **`delegation:` block** (was Gemini) and **`fallback_model`** (was Gemini); profiles live as dirs in `~/.hermes/profiles/<name>/`.
11. Amo chose "free local (ollama)" for the cheap tier. Edited `delegation`, `fallback_model`, `fallback_providers[0]` → `ollama-local/qwen2.5:7b`.
12. Amo then said "fix it the way you'd suggest" → re-pointed `delegation` + `fallback_model` → **`anthropic/claude-haiku-4-5`** (reliable + cheap for load-bearing automation), keeping `fallback_providers[0]=ollama-local` as the free cross-provider net. Verified Haiku available (`claude-haiku-4-5-20251001`) and `qwen2.5:7b` serves.
13. Restarted (Amo via `!`) → PID 607900.
14. **NEW issue #2 (bigger) — Anthropic ALSO out of credits.** Triggering `engine-watchdog` revealed **673× `HTTP 400: Your credit balance is too low`** today on `claude-opus-4-7`. The Opus-4-7 default **drained the Anthropic account (~$900 est.) in 3 days** (1,452 calls × ~42k-token contexts). Jobs fall back to local `qwen2.5:7b` but it **times out** (`RuntimeError: Request timed out`) — the 7B is too slow to drive the skills.
15. Decision (Amo): **top up Anthropic + switch default Opus→Haiku**; **leave jobs running** (no pause) during the wait.
16. Changed main `model.default` **`claude-opus-4-7 → claude-haiku-4-5-20251001`**. Validated YAML. **NOT YET RESTARTED** — staged on disk only.

---

## 2. FILES CREATED OR MODIFIED

| Path | Change | Why |
|---|---|---|
| `/home/mattm/.hermes/config.yaml` | `model.default`+`name` → `claude-haiku-4-5-20251001`; `delegation` → anthropic/haiku; `fallback_model` → anthropic/haiku; `fallback_providers[0]` → ollama-local/qwen2.5:7b; `agent.reasoning_effort` = medium (06-26) | Sustainable cheap/reliable routing; kill dead Nous/Gemini; stop Opus cost drain |
| `/home/mattm/.hermes/.env` | (06-26) `DISCORD_BOT_TOKEN` rotated to valid; `OpenROUTER_API_KEY` case-fixed | Restore Discord delivery; enable OpenRouter |
| `/home/mattm/.hermes/scripts/run-vec-index.py` | `INDEX_DB`→ext4 path; added `PUBLISH_DB`=`/mnt/c/.../engine/data/vec_index.db`; checkpoint + atomic publish (temp+os.replace) + stale-sidecar cleanup | Fix vec0/WAL disk-I/O on drvfs; build local, publish to engine |
| `/home/mattm/.hermes/cron/jobs.json` | (06-26) paused `hermes-daily-backup` (`5119907bb480`) + `nightly-vector-index` (`5d6b754a31f9`) | Redundant/insecure; vec-index now manual on ext4 |
| `C:\Users\mattm\HERMES_FIX_PLAN.md` | 06-26 diagnostic plan + execution log | Mission deliverable |
| `/mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/engine/data/vec_index.db.tmp` | 249 MB completed H4 index, staged | Awaiting publish-swap (engine holds target open) |

**Config/.env backups (rollback points):**
- `config.yaml.bak-preHAIKU-20260629T160816Z` (before Opus→Haiku main switch)
- `config.yaml.bak-preLOCAL-20260629T130556Z` (before Gemini→local)
- `config.yaml.bak-preRESTART-20260626T122204Z` (06-26 pre-restart)
- `config.yaml.bak-preH2-20260626T111246Z`
- `.env.bak-preH3-20260626T104615Z`, `.env.bak-preH6-20260626T111246Z`
- `run-vec-index.py.bak-preH4-*`, `jobs.json.bak-preH5-*`

**Disposable verification helpers (in `/tmp`, safe to delete):** `hermes_creds_check.py`, `hermes_verify.sh`, `hermes_routing.py`, `hermes_jobdump.py`, `check_haiku.py`, `h4_publish_retry.py`.

---

## 3. CURRENT STATE

**Running:**
- `hermes-gateway.service` (systemd, **system-level** not `--user`) — **active**, PID **607900**, since 2026-06-29 15:50 CDT.
- Discord (connected as **Jarvis-Trader#4564**) + Telegram (polling) both connected.
- Local infra: ollama `:11434` (serves `qwen2.5:7b`, `deepseek-coder-v2:16b`, `nomic-embed-text`, etc.), litellm `:4000`, dashboard `:9119`, prometheus `:9090`.
- Separate unrelated `openclaw` node gateway on `:18789` (NOT Hermes — left untouched).

**⚠️ CRITICAL NUANCE:** the running gateway (started 15:50) loaded the **haiku-delegation/fallback + Gemini-removed** config, but its **main model is still `claude-opus-4-7`** — the Opus→Haiku main switch (made 16:08) is **on disk but NOT loaded**. A restart is required to load it.

**Broken / degraded:**
- **Anthropic API: $0 balance** — `claude-opus-4-7` (and Haiku) return `400 credit balance too low`. 673 such errors today.
- **Google Gemini: out of prepay credits** — `429`. (Now fully removed from config, so dormant.)
- **Local `qwen2.5:7b` fallback: times out** on heavy/skill jobs (`Request timed out`) — not a reliable standalone tier.
- Jobs: **23 ok / 15 error** right now (errors = Anthropic-400 → local-timeout). Failing: `engine-watchdog`, `AI Triage on Capture`, `event-monitor`, `signal-context`.
- **H4 publish:** `vec_index.db.tmp` (249 MB, complete) staged on `/mnt/c`; swap blocked — the Windows jarvis engine holds `vec_index.db` open (`os.replace` → EACCES).

---

## 4. IN-PROGRESS WORK
- **Haiku main-model switch** — staged in `config.yaml`, **awaiting gateway restart** to load.
- **Anthropic top-up** — pending (Amo, billing-only).
- **H4 vec-index publish-swap** — `.tmp` staged, awaiting engine to release the open file handle.

---

## 5. BLOCKERS DISCOVERED
1. **Anthropic $0 balance** — nothing on Anthropic (incl. Haiku) works until topped up. **Amo-only** (console.anthropic.com → Plans & Billing). Root cause: Opus-4-7 default on 38 jobs burned ~$900 in 3 days.
2. **Google Gemini $0** — dead; now removed from active config (moot unless re-added).
3. **Auto-mode classifier blocks the assistant from restarting the gateway** (both raw `gateway run --replace` and `hermes-safe-restart.sh --force` were denied). The restart **must be run by Amo** via: `! wsl -d Ubuntu bash -lc "bash ~/.hermes/bin/hermes-safe-restart.sh --force"` — OR add a `~/.claude/settings.local.json` allow rule for that command.
4. **`hermes-safe-restart.sh` requires `--force`** because 7 sessions show as "live peers" in the manifest (several likely stale System32 scheduled-task sessions that never deregistered). `--force` is the script's sanctioned override.
5. **Local 7B too slow** for skill/delegation jobs → timeouts. Free-local is only viable as a last-resort fallback, not the primary cheap tier (hence the Haiku decision).
6. **H4 `/mnt/c` publish** — target db held open by the Windows engine; needs the engine to release it (next `restart_engine.ps1`).

---

## 6. KEY DECISIONS MADE
- **Repoint main Nous→Anthropic** (06-26): Nous out of funds; the real bug was the gateway running stale in-memory config (fix was on disk, never loaded → a restart was the whole fix).
- **`reasoning_effort` none→medium**: the routed model rejected reasoning-off.
- **Discord token rotation**: old token revoked (401); valid token in 1Password `Discord-Bot-Jarvis`. `model.default` wins over `model.name` (`status.py:67`), so the dotted `name` never mattered.
- **Cheap-tier routing: Gemini → (briefly local) → Haiku.** The watchdog/triage/delegation tier is load-bearing automation (the watchdog guards the trading engine), so reliability > marginal cost. Haiku is ~15× cheaper than Opus, fast, reliable. Local `ollama` retained only as the **cross-provider fallback** (`fallback_providers[0]`).
- **Main default Opus-4-7 → Haiku-4-5**: Opus drained the account in 3 days; Haiku makes a modest top-up last weeks (~$50–60/mo for the same workload).
- **Leave high-frequency jobs RUNNING** (not paused) during the top-up wait — Amo accepts interim alerts to keep monitoring live.
- **Restart mechanism**: it IS a **system-level** systemd service (`hermes-gateway.service`); use `hermes-safe-restart.sh --force` (sudoers NOPASSWD covers `systemctl restart/stop/start/status hermes-gateway.service`). NOT `--user`. Raw `gateway run --replace` is classifier-blocked.

---

## 7. TODO (planned, not started)
1. **[AMO]** Top up Anthropic credits (console.anthropic.com → Plans & Billing).
2. **[AMO or settings-rule]** Restart gateway to load the Haiku-main config: `! wsl -d Ubuntu bash -lc "bash ~/.hermes/bin/hermes-safe-restart.sh --force"`.
3. **[VERIFY after 1+2]** Trigger `engine-watchdog` (`hermes cron run 387bc0382e7a`) + a heavy job; confirm they complete on `claude-haiku-4-5/anthropic`, **no 400**, **no timeout**, clean Discord delivery. Re-check `hermes cron list` → error count → 0.
4. **[H4]** Complete the vec-index publish: after the jarvis engine next restarts (releases the file), run `python /tmp/h4_publish_retry.py` (or `os.replace` `vec_index.db.tmp` → `vec_index.db` + remove stale `-wal`/`-shm`). Then re-enable the `nightly-vector-index` cron job (id `5d6b754a31f9`) — verify it now points at the ext4-build/`/mnt/c`-publish logic.
5. **[QUALITY watch]** Haiku is the blanket default for all 38 jobs; if heavy research/synthesis jobs (morning brief, weekly synthesis) underperform, add a per-job **Sonnet** override. NOTE: `hermes cron edit` has **no `--model` flag** — per-job model must be set by editing `jobs.json` directly (fields `model`/`provider`, currently `null`) then restarting, OR via a profile config.
6. **[LATENT]** Per-profile configs (`~/.hermes/profiles/{briefer,analyst,...}/config.yaml`) still point at **dead Nous** — currently masked by the global Anthropic override; clean up to avoid future confusion.
7. **[LATENT]** `image_gen` aux provider still registered as `nous` (openrouter plugin) — fails only if a job requests image generation.
8. **[MINOR]** Gateway logs "Installed service definition is outdated — run `sudo hermes gateway restart --system`" to refresh the systemd unit.
9. **[DONE]** Gemini fully removed from active config — no Google dependency remains.

---

## 8. FULL CURRENT TO-DO LIST
**Honest note:** I did not maintain a formal task-tracker (TaskCreate/TaskList) list this session — work was driven conversationally. The complete working to-do list **is Section 7 above**. There is no separate/hidden task list. The two immediate, blocking items are: **(1) Amo tops up Anthropic**, **(2) restart gateway to load Haiku config** — everything else (verification, H4 swap, latent cleanups) follows from those.

---

## 9. GIT STATE

**`~/.hermes` (the Hermes install where ALL this session's changes live): NOT a git repo.**
Config is tracked via a **nightly mirror** to the private repo `mattamundson/hermes-state` (`Hermes-Nightly-Sync` Windows task, worker `~/scripts/hermes-state-sync.ps1`, 00:00 CT, age-encrypts secrets). This session's edits exist as working files + timestamped `.bak-*` backups; they will propagate to `hermes-state` at the next nightly sync. **There is no per-change git history for the Hermes config** — rely on the `.bak-*` files (Section 2) for rollback.

**`C:\Users\mattm\ThinkorSwim\jarvis-trader` (jarvis-trader repo — touched only via the gitignored `engine/data/vec_index.db.tmp`; NO tracked code changed this session):**
```
branch: fix/corey-cache-stale-nodata
git status -s  → 22 entries (ALL pre-existing, unrelated to this Hermes session):
 M .gitignore
 M dashboard/dashboard.code-workspace
 M docs/reports/METRICS_SNAPSHOT.json
 M engine/data/forecast_reports/2026-06-25.md
 m tradingview-mcp
 ?? dashboard/AGENTS.md
 ?? docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md
 ?? docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html
 ... (22 total)

git log --oneline -20:
36c2b7c data(discord): 2026-06-27 digest
8bd65d3 data(discord): 2026-06-26 digest
c590ef1 docs(deploy): add credential-rotation section to Vercel runbook
d701868 docs(deploy): rewrite Vercel runbook to as-built ngrok + 3-layer auth
54ada57 feat(autonomous): opt-in paper-only auto-approve (default OFF) (#173)
e82fe8e data(discord): 2026-06-25 digest
c820bbe fix(market_data): map MHG (COMEX) and MYM (CBOT) futures exchanges
a91670a feat(dashboard): proxy injects tunnel basic-auth server-side
40e9f96 fix(market_data): map ZB/ZN (CBOT) futures exchange — unfreeze bond bars
f359240 test(corey,harmonic): cover guardrail branches + prove harmonic detector fires
5960aca feat(dashboard): live Price column on Hidden Pivots page
1386713 feat(corey): signal-propagation guardrail for trade_outcomes
2898aa1 feat(corey): on-demand session-bias extract viewer
aa3f9bb feat(backtest): H1/H2 chronological stationarity gate (library + wrapper)
97b53a6 fix(dashboard): bypass ngrok browser-warning interstitial in proxy
1f14843 chore(dashboard): .vercelignore + Cloudflare deploy runbook
a438098 fix(paper-config): disable MGC — enabled on a now-FAIL rank4 verdict
1905852 docs(env): point DISCORD_TOKEN at 1Password canonical store
d0f7d91 fix(corey): re-extract stale no-data bias cache on backfilled commentary
767c7b7 chore(dashboard): Vercel deploy config + runbook
```
`git diff --stat` returned no summary line (changes are the working-tree files listed above; none committed this session). **This session committed nothing to git** — all Hermes work is in non-git config.

---

## CURRENT CONFIG ROUTING (authoritative, on disk in `config.yaml`)
| Slot | provider / model | Status |
|---|---|---|
| `model` (main, all cron) | `anthropic / claude-haiku-4-5-20251001` | staged, **needs restart to load** (running gateway still on opus-4-7) |
| `delegation` | `anthropic / claude-haiku-4-5-20251001` | loaded (15:50 restart) |
| `fallback_model` | `anthropic / claude-haiku-4-5-20251001` | loaded |
| `fallback_providers[0]` | `ollama-local / qwen2.5:7b` | loaded (free cross-provider net) |
| `agent.reasoning_effort` | `medium` | loaded |
| Gemini / Nous references | **0 in active paths** | removed |

## SUGGESTED NEXT ACTION
**Amo tops up Anthropic, then runs the restart command** (`! wsl -d Ubuntu bash -lc "bash ~/.hermes/bin/hermes-safe-restart.sh --force"`). The continuing session should then run the Section-7 #3 verification and report whether the error count clears to 0.

## OPEN COORDINATION NOTE
The assistant held the `hermes` Tier-2.5 resource lock during edits (owner `58ea5745`, 30-min TTL — may be expired by handoff time). Re-claim before any further Hermes mutation: `~/scripts/claude-resource-lock.ps1 -Claim hermes`. The restart-guard hook + auto-mode classifier will block assistant-initiated gateway restarts regardless — route restarts through Amo's `!` shell or a settings allow-rule.
