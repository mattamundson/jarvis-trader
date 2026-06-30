# HANDOFF — 2026-06-30 — Price-Freshness Gate Shipped & Deployed; Calibration Volume Blocked on LLM Billing

> **Companion documents (same `docs/session-logs/` folder):**
> - `SESSION_SUMMARY_2026-06-30_price-freshness-gate.md` — narrative summary (the "story")
> - `CONVERSATION_2026-06-30_price-freshness-gate.md` — full secret-redacted transcript (1,616 turns)
> - A mirror of this handoff lives at `~/.claude/handoffs/HANDOFF_2026-06-30_price-freshness-gate-and-llm-blocker.md`

**Author:** Claude Opus 4.8 (1M context)
**Repo:** `C:\Users\mattm\ThinkorSwim\jarvis-trader`
**Working branch:** `fix/corey-cache-stale-nodata` (2 ahead / 172 behind `origin`)
**Engine:** UP, pm2-managed (`jarvis-engine` pid 111544, 2 restarts), `/health = degraded` (LLM leg only)
**Platform:** Windows 11 (26200) · PowerShell 5.1 + Git Bash · engine venv Python 3.12.10
**Date the work happened:** 2026-06-29 (build/deploy) → 2026-06-30 (diagnosis, docs)

---

## TL;DR (read this first)

A paper-trade contamination on **2026-06-29** booked fills against a **frozen/stale MES price (~5300)** while the live market was **~7497**. Root cause: the IB **paper** account has **no futures market-data subscription**, so the data leg errored (IB 10168/354) and the engine silently fell back to a **months-old CSV cache** whose values were internally consistent and *tagged live* — defeating all three existing price-sanity anchors.

**What got built & shipped (PR #194, CI-green, deployed to the running engine):**
1. A **4th price-sanity anchor — bar-timestamp freshness** — that rejects any entry validated against a bar older than a configurable ceiling (default 2 h). Fail-safe → `NO_TRADE`.
2. An **IB delayed-data stopgap** (`reqMarketDataType(3)`) so a missing live subscription yields *delayed* real data instead of a stale cache.

**What is now the single blocker to the actual goal (calibration volume):** the **LLM path is down**. Anthropic (primary) is out of credit; the OpenAI fallback key is globally dead; local ollama is non-viable on this box. **This is Amo-only** — a billing/key action, not a code action.

**Everything else in this doc is depth behind those three facts.**

---

## 1. Session summary — what was accomplished, in order

| # | Step | Outcome |
|---|------|---------|
| 1 | Reproduced & root-caused the 2026-06-29 stale-price contamination | Subscription-gap → IB data error → stale CSV cache fallback; the three existing anchors are all *relative* and a self-consistent stale cache passes them |
| 2 | Designed the orthogonal fix: an **absolute bar-age** anchor | Only a timestamp catches a self-consistent stale frame; chose a 2 h ceiling, fail-safe, opt-out |
| 3 | Implemented `entry_price_sanity.py` freshness anchor (TDD, 20 tests) | Fires only when a timestamp is determinable; skips timestamp-less synthetic frames so legacy tests stay green |
| 4 | Implemented IB delayed-data stopgap in `market_data.py` (TDD, 4 tests) | `reqMarketDataType(3)` default, env-overridable, non-fatal |
| 5 | Ran full suite | 86 tests green |
| 6 | Opened **PR #194**; CI failed the **Safety Invariant Check** | `engine/risk/` changes require `[safety-review]` in PR body |
| 7 | Added `[safety-review]` with per-invariant notes (Amo-authorized) | Gate re-ran **green**; no hooks bypassed |
| 8 | Deployed: landed the two commits onto the running branch | Verified live: `IBKR market-data type set to 3`, `IBKR connected`, real MES `marketPrice ~7487/7495` |
| 9 | Investigated `jarvis-engine` 144-restart kill-loop | Root cause = orphan accumulation from mixing `restart_engine.ps1` standalone path with pm2; fixed via `pm2 delete` + clean re-register + `pm2 save` |
| 10 | Diagnosed the LLM outage | Anthropic = no credit; OpenAI fallback key = globally dead (HTTP 401); gemini unverified |
| 11 | Tried local ollama (`hermes3`) as a stopgap (Amo-authorized) | Non-viable: 29 s cold inference + RAM exhaustion crashlooped the engine; **reverted** to anthropic, unloaded model, engine recovered |
| 12 | (2026-06-30) Attempted OpenAI-key swap from clipboard | Clipboard held no key (prose) → **no `.env` mutation, no restart**; then produced this documentation set |

---

## 2. The incident, in full (anatomy of the 2026-06-29 contamination)

**Symptom.** Autonomous paper fills were booked for MES at ~5300 while the real continuous-future price was ~7497 — a ~2,200-point (~30%) divergence. The fills looked legitimate (correct symbol, plausible size, "live" source tag).

**Causal chain.**
1. The engine's data leg calls IB for MES bars/ticks.
2. The **IB paper account has no futures market-data subscription** → IB returns **Error 10168** ("requested market data is not subscribed") / **354** family, and never streams live futures.
3. The engine's `MarketDataManager` fell through its source ladder to the **CSV cache** (`engine/data/...` historical export).
4. That cache was **months old** but **internally consistent** (OHLC all ~5300, no NaNs) and was surfaced **tagged as a normal/live source**, not flagged stale.
5. `entry_price_sanity.check_entry_price_sanity()` ran its three anchors:
   - **ATR-delta** — entry vs recent bars: passes (entry ~5300 *matches* the stale ~5300 bars).
   - **provenance-source** — rejects `unavailable`/`error`, but the cache reported a benign source: passes.
   - **era-deviation** — entry vs robust median of the *same stale window*: passes (median is also ~5300).
6. All three are **relative** comparisons against the very frame that is stale → **no anchor could see the problem**. The order passed sanity and filled.

**Why this is a class of bug, not a one-off.** Any time a stale-but-self-consistent frame is mistakenly tagged live, *every relative anchor is blind*. The only signal that survives is the **absolute wall-clock age of the latest bar**. That is precisely the gap the new anchor closes.

---

## 3. The fix — design, rationale, and exact behavior

### 3a. Bar-timestamp freshness anchor (`engine/risk/entry_price_sanity.py`)

**New environment knobs**
| Env var | Default | Meaning |
|---|---|---|
| `ENABLE_ENTRY_PRICE_FRESHNESS` | on (any value ≠ `0/false/no`) | Opt-out switch for the whole anchor |
| `ENTRY_PRICE_MAX_BAR_AGE_SECONDS` | `7200` (2 h) | Max tolerated age of the latest bar; floored at 60 s |

**New helpers**
- `is_bar_freshness_check_enabled() -> bool` — opt-out (default True).
- `_get_max_bar_age_seconds() -> int` — parses the env, floors at 60.
- `latest_bar_age_seconds(df, now=None) -> Optional[float]` — determines the timestamp of the most recent bar by trying, in order: (1) a `DatetimeIndex`, (2) a `timestamp`/`time`/`date`/`datetime` column. Naive timestamps are **assumed UTC**. Returns `None` when no timestamp can be determined.

**Integration in `check_entry_price_sanity()`**
- After the existing `get_bars` fetch (and only if freshness is enabled, `bars` is non-empty):
  - `age = latest_bar_age_seconds(bars)`
  - `age is None` → **warn and skip** the freshness anchor; the three relative anchors still apply. (Don't hard-block on missing metadata.)
  - `age > ceiling` → **`return False`** with a `STALE bar` reason string → fail-safe **NO_TRADE**.

**Why this exact shape (the load-bearing design choices)**
- **Absolute, not relative** — the whole point is to escape the relative-anchor blind spot.
- **2 h ceiling** — wide enough never to false-positive on a normal slow tape or a brief gap; tight enough that a months-old cache is caught instantly. Floor of 60 s prevents a foot-gun env value of `0`.
- **Fail-safe** — uncertainty resolves to "don't trade," consistent with gate-v2's `NO_TRADE` philosophy.
- **Opt-out, determinable-only** — fires *only* when a timestamp exists. Real IB/CSV bars always carry one; the synthetic, timestamp-less frames used in legacy unit tests are skipped, so the change is non-breaking. (This is why the 20 new tests pass *and* the prior suite stayed green.)
- **Protects both paths** — manual approval and the `AUTONOMOUS_AUTO_APPROVE_PAPER=1` auto-approve path both route through `check_entry_price_sanity`, so one fix covers both.

### 3b. IB delayed-data stopgap (`engine/data/market_data.py`)

- Added `import os`. In `IBKRDataConnector.connect()`, immediately after `self._connected = True`:
  - Parse `IB_MARKET_DATA_TYPE` (default `"3"`). Valid values `1=live 2=frozen 3=delayed 4=delayed-frozen`.
  - For a valid value, call `self._ib.reqMarketDataType(n)` and log it.
  - Out-of-range/garbage → skip the call (connection still succeeds).
  - Whole block wrapped in try/except → **non-fatal**: a failure here must never abort `connect()`.
- **Semantics that matter:** `reqMarketDataType(3)` requests delayed data *only where there is no live subscription*. Where a live sub exists, IB keeps streaming **live** — it never downgrades a subscribed feed. So this is strictly additive: a subscription gap now yields **delayed real prices** instead of a **stale cache**.

### 3c. Defense-in-depth: the two fixes are complementary
- The **stopgap** attacks the *cause* (no live sub → real delayed data instead of cache fallback).
- The **freshness anchor** attacks the *blast radius* (even if a stale frame ever reaches sanity, it is rejected). Either alone would have prevented 2026-06-29; together they are belt-and-suspenders.

---

## 4. Test matrix

| File | Cases | Coverage |
|---|---|---|
| `engine/tests/test_entry_price_freshness.py` | **20** | flag on/off; env parse + floor; `latest_bar_age_seconds` for DatetimeIndex / each column name / naive-UTC / undeterminable→None; integration via `check_entry_price_sanity`: stale-but-plausible **rejected**, fresh **passes**, disabled **does not block**, untimestamped frame **skips anchor**. Helper `_mock_dm(bars, last_price=7400.0, source="ibkr")`. |
| `engine/tests/test_ib_market_data_type.py` | **4** | default→`[3]`; env override→`[1]`; out-of-range `9`→`[]` but connect still True; `reqMarketDataType` raising→connect still True (non-fatal). Patches `ib_async.IB` with `_FakeIB` (records calls; async no-op `connectAsync`). |
| **Full suite** | **86 green** | no regressions |

---

## 5. Deploy & verification (exactly what was done, and how to re-verify)

**Deploy method.** Rather than wait on the PR merge, the two commits were landed onto the **running** branch `fix/corey-cache-stale-nodata` (HEAD = `a326d75`/`a81cf29`), and the engine was restarted under pm2. PR #194 remains the clean-merge record.

**Live verification observed (post-deploy):**
- Engine log: `IBKR market-data type set to 3 (1=live 2=frozen 3=delayed 4=delayed-frozen)`
- Engine log: `IBKR connected`
- MES `marketPrice` ~**7487 / 7495** (real market) — no longer frozen ~5300.

**Re-verify commands (read-only):**
```bash
# engine health
curl.exe -s http://127.0.0.1:8010/health | python -m json.tool
# broker truth (health can short-circuit; positions is the real broker state)
curl.exe -s http://127.0.0.1:8010/brokers/positions
# pm2 supervision
pm2 status
pm2 logs --lines 80 jarvis-engine
# confirm the freshness anchor + stopgap are present in the running tree
git -C /c/Users/mattm/ThinkorSwim/jarvis-trader log --oneline -3
```
**Pass criteria** (per `rules/verification.md`): `status=ok` *and* `tradingview_mcp_healthy=true` *and* `llm_path_healthy=true`. **Today only the first two hold** — `llm_path_healthy=false` (see §7).

---

## 6. pm2 supervision incident & resolution

**Symptom.** `jarvis-engine` showed a chronic **144-restart** count and was kill-looping on the first pm2-path restart.

**Root cause.** Orphan accumulation from **mixing two launch paths**: `restart_engine.ps1` starts the engine via a standalone `Start-Process` (its own uvicorn), while pm2 launches `engine/scripts/port_guardian.py`. When both paths touch port 8010, `port_guardian` finds the port held, kills an orphan, and the supervisor churns.

**`port_guardian.py` is sound** (read, not modified): `main()` runs once, kills a *single* orphan uvicorn if 8010 is held, then `uvicorn.run("main:app", host="0.0.0.0", port=8010)` **in-process** for one stable PID. `_check_venv_python()` hard-exits(4) if not run under `.venv`.

**Fix.** `pm2 delete jarvis-engine` → clean `pm2 start engine/scripts/port_guardian.py --name jarvis-engine --interpreter <venv-python> --cwd engine` (fork mode) → `pm2 save`. Restart counter reset; engine now stable (restarts: 2).

**Standing rule reinforced:** pm2 is the **single** supervisor. Never start the engine via `restart_engine.ps1`'s standalone path while pm2 owns it — that re-creates the kill-loop. To restart the pm2-managed engine, use `pm2 restart jarvis-engine` (never `--reload`).

**Config identity note.** `config.py:29` does `load_dotenv(override=True)`, so standalone and pm2 launches are **config-identical** — both read `engine/.env`. This is why an `.env` change + `pm2 restart` is sufficient to pick up a new key.

---

## 7. The binding blocker — LLM path (Amo-only)

`/health` is `degraded` solely because `llm_path_healthy=false`. The LLM chain is **claude (primary) → gemini → openai**. Current state of each leg:

| Provider | Configured | Working | Evidence |
|---|---|---|---|
| **anthropic** (primary) | yes | **no** | `invalid_request_error: "Your credit balance is too low…"` (last failure agent `discovery_loop`) |
| **gemini** (fallback 1) | yes | **unverified** | never exercised/validated this session — *possible zero-cost restore if its key/billing is live* |
| **openai** (fallback 2) | yes | **no** | key in `engine/.env:453` is globally dead → OpenAI returns `invalid_api_key` / **HTTP 401**; identical to the 1Password copy |

**Local ollama — ruled out on this hardware.** Flipping `JARVIS_LLM_PROVIDER=ollama` (model `hermes3:latest`) crashlooped the engine: **29 s cold inference** stalled boot, and **RAM exhaustion** (31.5 GB total, ~3 GB free, hermes3 resident **9.26 GB**) drove it to `status=stopped`. Reverted `JARVIS_LLM_PROVIDER` ollama→anthropic, unloaded the model (`keep_alive:0`); engine recovered to the stable degraded baseline. The ollama env block remains in `.env` (`OLLAMA_HOST=http://127.0.0.1:11434`, `OLLAMA_MODEL=hermes3:latest`) but is **unused**.

**Why this is *the* blocker.** No working LLM ⇒ the autonomous pipeline (`pipeline_autonomous.py`, `ENABLE_AUTONOMOUS_PIPELINE=1`) cannot run its analyst agents ⇒ **no signals generated** ⇒ **zero calibration volume**. The whole point of the recent work (auto-approve, freshness gate, IC/Brier calibration framework) is to *generate calibrated paper volume*; that is gated here.

**The three independent ways to clear it (any one suffices):**
1. **Anthropic top-up** — console.anthropic.com → Plans & Billing. Keeps Claude primary; zero `.env` change needed.
2. **Fresh OpenAI key** — generate, store in 1Password `op://Amo Personal/OpenAI-API/credential`, run `! op signin`, then the next session syncs `engine/.env:453` and restarts. Restores the gpt-4o-mini fallback.
3. **Validate gemini** — if its key/billing is live, it may already satisfy the fallback with no spend; worth a probe before paying.

---

## 8. Secret-handling protocol (followed this session; reuse next session)

- **No secret value ever transits chat or a file at rest.** Keys are read into a `$key` PowerShell variable; only a **redacted fingerprint** (prefix + last-4 + length) is printed.
- **Rejected** the "save the key in a notepad file" idea — plaintext secret at rest is forbidden (`rules/secret-hygiene.md`). Canonical store is **1Password vault `Amo Personal`** (`OpenAI-API/credential`; Anthropic lives at `jarvis-engine/password`).
- **`.env` writes use a `$key` variable, never the literal** — so the `credential-guard` PreToolUse hook (which scans command *text* for `sk-` patterns) doesn't trip, and the value never appears in tool-call arguments. `engine/.env` is gitignored.
- **The OpenAI-key swap runbook** (when a real key + `op signin` exist): read key (redacted) → test against OpenAI `/v1/models` (expect HTTP 200) → write `engine/.env:453` via `$key` → update 1Password → claim the `jarvis-engine` **resource lock in a separate prior call** → restart under the `PROPOSING_DESTRUCTIVE_OP` marker → verify `llm_path_healthy:true` + `status:ok` → clear clipboard. **Do nothing until the key is real and `op signin` is confirmed** (the op CLI session was timing out / locked this session).

---

## 9. Current state — running / stopped / broken

### pm2 (as of 2026-06-30 ~06:11 UTC)
| Process | Status | PID | Restarts | Uptime | Notes |
|---|---|---|---|---|---|
| `jarvis-engine` | **online** | 111544 | 2 | ~25 min | Stable; pm2-supervised; degraded on LLM only |
| `master-api` | online | 98216 | 0 | ~9.4 h | — |
| `jarvis-bridge-api` | online | 108444 | 0 | ~9.4 h | — |
| `jarvis-dashboard` | **stopped** | — | **8761** | — | Chronic crashloop; **pre-existing, NOT triaged this session** |
| `jarvis-weekly-tearsheet` | stopped | — | 0 | — | Scheduled one-shot; idle is expected |

### Engine `/health` snapshot
- `status:degraded`, `paper_mode:true`, `live_trading:false`, `kill_switch_active:false`
- Healthy: `database:connected`, `ibkr_connected/execution/data:true`, `ibgateway_port:4002`, `tradingview_mcp_healthy:true`
- **Broken:** `llm_path_healthy:false`, `primary_healthy:false`, `active_provider:null`, last failure = Anthropic credit-low
- `brier_30d_rolling:0.346`

### Ports (reference)
| Service | Port | Notes |
|---|---|---|
| Engine API | 8010 | use `127.0.0.1` (IPv6 quirk) |
| Dashboard | 3010 | (crashlooping under pm2) |
| IB Gateway paper | 4002 | connected |
| IB Gateway live | 4001 | **permanently blocked** |
| Redis | 6379 | — |

---

## 10. In-progress work (started, not finished)

1. **OpenAI key swap** — staged, waiting on Amo to supply a key + `op signin`. Runbook in §8. (Today's attempt found no key on the clipboard → nothing mutated.)
2. **PR #194** — OPEN, CI green, `[safety-review]` present, `mergeable:UNKNOWN` (refresh merge-base before merging). Substance already deployed; PR is the clean-merge vehicle. **Amo merges** — sessions never merge/push the shared branch.

---

## 11. Blockers discovered

1. **LLM billing/keys — Amo-only, HARD blocker** (see §7). Any one of: Anthropic top-up / fresh OpenAI key / validated gemini.
2. **1Password CLI session locked** — `op read` returned `authorization timeout`; needs interactive `! op signin`.
3. **Execution-path overlap → latent double-fill risk.** The **untracked** `engine/systematic/live_signal_executor.py` (this is PR #177's content) submits paper orders **directly**, bypassing the approval queue, while `AUTONOMOUS_AUTO_APPROVE_PAPER=1` routes through `approve_candidate`. Both terminate in `submit_paper_order` but use **separate idempotency** → if both are ever enabled, **double-fill**. Both are default-OFF today. **Reconcile to one canonical path + a shared dedup guard before activating either.** See memories `project_systematic_exec_path_reconciliation_2026_06_29` and `project_cross_path_dedup_2026_06_29` (shared first-wins JSONL ledger keyed `(symbol,action,trading_date)`; PRs #177/#183/#186 await Amo merge in order **#186 → #177 → #183**; #186 also fixes a master lint-red that was blocking *all* PRs).
4. **`jarvis-dashboard` crashloop** (8761 restarts) — needs its own triage.
5. **Branch divergence** — `fix/corey-cache-stale-nodata` is **2 ahead / 172 behind** `origin`. Do **not** reflexively rebase/merge; surface and ask which is source of truth (`rules/git-hygiene.md`).

---

## 12. Key decisions made (with rationale)

| Decision | Rationale / tradeoff |
|---|---|
| Bar-age as the 4th anchor | Only an absolute timestamp escapes the relative-anchor blind spot |
| 2 h ceiling, 60 s floor | No false-positive on a slow tape; instant catch of a stale cache; floor blocks a `0` foot-gun |
| Fail-safe → NO_TRADE on stale | Matches gate-v2 philosophy; uncertainty must not trade |
| Opt-out + determinable-only | Non-breaking (legacy timestamp-less frames skip); real bars always carry a timestamp |
| `reqMarketDataType(3)` default; non-fatal | Adds delayed data only where unsubscribed; never downgrades a live feed; never aborts connect |
| Deploy by landing commits on the running branch | Contamination fix live immediately; PR #194 kept as clean-merge record |
| pm2 = single supervisor; never mix with `restart_engine.ps1` standalone | That mix was the kill-loop |
| ollama rejected | Latency (29 s cold) + RAM (9.26 GB) on a ~3 GB-free box; not principle |
| No plaintext secret at rest; `$key`-variable writes | Secret-hygiene; avoids credential-guard trip; value never in chat/argv |
| Never disable MES | Standing directive ("10000% never") — any gate change that would side-effect-block MES must EXEMPT MES |

---

## 13. TODO (planned, not started) — priority order

- [ ] **Restore the LLM path** (Anthropic top-up *or* fresh OpenAI key *or* validated gemini) — *Amo-gated, #1; unblocks calibration volume.*
- [ ] After a key exists: sync `engine/.env:453` + 1Password, restart (lock-claimed, `PROPOSING_DESTRUCTIVE_OP`), verify `llm_path_healthy:true`.
- [ ] **Merge PR #194** (Amo) — refresh mergeability first.
- [ ] **Reconcile the two execution paths** + land the shared dedup guard before enabling either (merge order **#186 → #177 → #183**).
- [ ] **Triage `jarvis-dashboard`** crashloop (8761 restarts).
- [ ] **Resolve branch divergence** (2 ahead / 172 behind) — decide source of truth.
- [ ] **Decide disposition of untracked working-tree files** — `engine/systematic/` (PR #177 content), `engine/backtest/run_mes_vwap_rank1.py`, `vwap_paper_track.py`: commit / branch / archive.
- [ ] **Probe gemini** as a possibly-free LLM restore before paying for anything.
- [ ] (Stretch) Wire calendar-discovery H1/H2 once free-daily→master lands (per recent memories).

---

## 14. Full current to-do list

**This session held no active `TaskCreate` todo list** — work was driven turn-by-turn from Amo's directives (AskUserQuestion selections + explicit asks), not a tracked queue. The effective live list is exactly **§13**. The single highest-priority, Amo-gated item is **restore the LLM path**; everything else is downstream of it or independent maintenance.

AskUserQuestion decisions taken this session (for audit): "Add `[safety-review]`"; "Deploy now (cherry-pick + restart)"; "1 and 2" (investigate kill-loop **then** re-register under pm2); "Flip to local ollama now" (later reverted as non-viable).

---

## 15. Files created / modified — full paths

### Committed (on `fix/corey-cache-stale-nodata`; substance of PR #194)
- `engine/risk/entry_price_sanity.py` — **MODIFIED** — freshness anchor (constants, helpers, integration). *Triggers the Safety Invariant Check (matches `^engine/risk/`).*
- `engine/tests/test_entry_price_freshness.py` — **NEW** (20 cases).
- `engine/data/market_data.py` — **MODIFIED** — `import os` + `reqMarketDataType` stopgap in `IBKRDataConnector.connect()`.
- `engine/tests/test_ib_market_data_type.py` — **NEW** (4 cases).
- `docs/session-logs/…2026-06-29 deploy-consolidation handoff…` — committed in `1f5e6d4`.
- *(This session adds:)* `docs/session-logs/HANDOFF_2026-06-30_…md`, `SESSION_SUMMARY_2026-06-30_…md`, `CONVERSATION_2026-06-30_…md` (written to the tree; **not auto-committed** — see §17).

### Read, not modified
- `engine/scripts/port_guardian.py` — pm2 launch target; confirmed sound.
- `.github/workflows/safety-invariant-check.yml` — the safety gate; PATTERNS include `^engine/risk/`.

### Working-tree (uncommitted) — see §18 for the verbatim status
- **Modified (incidental drift, NOT this work):** `.gitignore`, `dashboard/dashboard.code-workspace`, `docs/reports/METRICS_SNAPSHOT.json`, `engine/data/forecast_reports/2026-06-25.md`.
- **Untracked — `engine/systematic/`** (PR #177 content; overlaps auto-approve — see §11.3): `__init__.py`, `live_signal_executor.py`, `test_live_signal_executor.py`.
- **Untracked — incidental/data:** `dashboard/AGENTS.md`, `docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md`, `docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html`, `engine/backtest/run_mes_vwap_rank1.py`, `engine/backtest/vwap_paper_track.py`, forecast/morning-forecast JSON+MD 06-26…06-29, `engine/data/vec_index.db.tmp`.

### Config (NOT committed — `.env` gitignored, intentional)
- `engine/.env:453` `OPENAI_API_KEY=` — still the **dead** `sk-proj-…dKoA` (len 164); untouched this session.
- `engine/.env` ~L380–398 ollama block — `JARVIS_LLM_PROVIDER` flipped ollama→anthropic and **reverted to `anthropic`** (current correct value).

---

## 16. Environment & operational reference (for the next session)

- **OS / shells:** Windows 11 (26200); PowerShell 5.1 (`powershell.exe`) + pwsh 7 + Git Bash. Keep `.ps1` run by PS 5.1 **pure ASCII**.
- **Engine venv:** `engine/.venv/Scripts/python.exe`, Python **3.12.10**. Bootstrap from `requirements-core.txt` (NOT `requirements.txt`). Repair via `repair-engine-venv.ps1`.
- **Restart:** pm2-managed → `pm2 restart jarvis-engine`. **Never** `--reload` (duplicate IB connections). Steady-state startup ≈ 229 s; `/health` is the gate, not log-absence.
- **Resource lock (mandatory before any engine restart/.env mutation):** `~/scripts/claude-resource-lock.ps1 -Claim jarvis-engine` in a **separate prior call**, `-Release` after. The restart guard blocks mutation if the lock isn't claimed by *this* session and a peer is live.
- **`localhost` → IPv6:** always hit `127.0.0.1` for local services.
- **Gate v2 thresholds** (don't call a strategy "good" without): `pf_ci_lower≥1.10`, `p_edge≥0.95`, `mc_95th_dd≤5%` (≤4% ALT on $50k+), `dsr≥0.10`. `NO_TRADE` is the answer when it fails.
- **Futures sentiment:** Corey `#market-updates` Discord only.

---

## 17. How the doc set was produced (provenance)

- **Handoff** (this file) + **session summary** — authored from the in-context summary, live git/health/pm2 queries, and the transcript.
- **Conversation transcript** — rendered by `scratchpad/render_convo.py` from the raw Claude Code JSONL (`~/.claude/projects/C--windows-system32/daea2db5-…853.jsonl`, 4,867 records → 1,616 turns, ~940 KB). **All secret patterns are redacted** to `[REDACTED-…]` fingerprints (verified by a post-render leak scan: clean); long tool outputs and command bodies are truncated inline; thinking blocks included (truncated).
- **Not auto-committed.** All three are written into `docs/session-logs/`. Committing is a separate, Amo-authorized step — and note `engine/data/vec_index.db.tmp` and other untracked drift should **not** be swept in (per-file staging only; never `git add -A`). The transcript is large (~940 KB) and contains full session prose; confirm you want it in git history before committing/pushing.

---

## 18. Git state (verbatim)

**Branch:** `fix/corey-cache-stale-nodata` — diverged **2 ahead / 172 behind** `origin/fix/corey-cache-stale-nodata`.

### `git status` (porcelain)
```
 M .gitignore
 M dashboard/dashboard.code-workspace
 M docs/reports/METRICS_SNAPSHOT.json
 M engine/data/forecast_reports/2026-06-25.md
?? dashboard/AGENTS.md
?? docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md
?? docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html
?? engine/backtest/run_mes_vwap_rank1.py
?? engine/backtest/vwap_paper_track.py
?? engine/data/forecast_reports/2026-06-26.md
?? engine/data/forecast_reports/2026-06-27.md
?? engine/data/forecast_reports/2026-06-28.md
?? engine/data/forecast_reports/calibration_2026-06-28.md
?? engine/data/morning_forecasts/2026-06-26.json
?? engine/data/morning_forecasts/2026-06-27.json
?? engine/data/morning_forecasts/2026-06-28.json
?? engine/data/morning_forecasts/2026-06-29.json
?? engine/data/vec_index.db.tmp
?? engine/systematic/__init__.py
?? engine/systematic/live_signal_executor.py
?? engine/systematic/test_live_signal_executor.py
```

### `git log --oneline -20`
```
a326d75 feat(data): request IB delayed market data as subscription-gap stopgap
a81cf29 feat(risk): add bar-timestamp freshness anchor to entry-price sanity
1f5e6d4 docs(session-logs): add 2026-06-29 deploy-consolidation handoff + conversation
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
```

### `git diff --stat` (unstaged)
```
 .gitignore                                 |  3 +++
 dashboard/dashboard.code-workspace         | 16 +++++++++++-
 docs/reports/METRICS_SNAPSHOT.json         | 40 +++++++++++++++---------------
 engine/data/forecast_reports/2026-06-25.md |  6 ++---
 4 files changed, 41 insertions(+), 24 deletions(-)
```
(CRLF→LF warnings on `.gitignore`, `METRICS_SNAPSHOT.json`, `2026-06-25.md`.)

### PR
- **#194** `feat: bar-freshness anchor + IB delayed-data stopgap (2026-06-29 stale-price contamination)` — branch `feat/autonomous-price-freshness-gate`, **OPEN**, CI green, `[safety-review]` present, `mergeable:UNKNOWN`. https://github.com/mattamundson/jarvis-trader/pull/194

---

## 19. Suggested next action (one thing)

**Restore the LLM path.** Cheapest-first: (a) **probe gemini** — if its key/billing is live it may already satisfy the fallback at zero spend; else (b) **top up Anthropic** (keeps Claude primary, no `.env` change) or (c) **drop a fresh OpenAI key** into 1Password `OpenAI-API/credential` + `! op signin`, and the next session syncs `engine/.env:453`, restarts the lock-claimed engine under the `PROPOSING_DESTRUCTIVE_OP` marker, and verifies `llm_path_healthy:true` + `status:ok`. Until then the engine is healthy but produces **zero calibration volume** — the one metric the recent work exists to move.
