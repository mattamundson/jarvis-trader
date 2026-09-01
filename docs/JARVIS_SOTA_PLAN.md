# JARVIS TRADER — State-of-the-Art ("Tony Stark Ready") Implementation Plan

> **Supersession note (2026-09-01):** Use
> [`docs/plans/master-implementation/README.md`](plans/master-implementation/README.md)
> as the current master implementation entrypoint. This document remains a
> historical SOTA planning reference and should be reconciled before new work is
> treated as adopted.

> Authored 2026-07-06. Grounded in a live, verified diagnosis of the running system
> (not a summary). Every task cites a real file path. Phases are ordered by
> dependency: reliability → data truth → experience → autonomy → hygiene → edge.
>
> **Owner legend:** `[AUTO]` = an agent/session can do it unattended in a worktree.
> `[AMO]` = requires Amo (GUI login, `.env` mutation, engine restart, shared-branch
> merge). `[AMO-GATE]` = built and staged autonomously, but flipped on only by Amo.

---

## 0. Verified ground truth (probed 2026-07-06 23:42 UTC / 18:42 CDT)

The prior read ("nothing works / ~8,150 crashloop") was **wrong**. Direct probes show:

| Subsystem | Verified state | Evidence |
|---|---|---|
| Engine `/health` | **UP, fast** — warm calls ~20 ms, cold 0.54 s, 200 OK | `curl time_total` x4 |
| `status` / LLM path | `ok` / `llm_path_healthy=true` | `/health` body |
| Restart behavior | **4 health-timeouts 22:11–22:40 UTC, none since**; recovers on its own | `engine/logs/port_guardian_restarts.jsonl` = 7 lines lifetime |
| "81,503 restarts" | PM2 **lifetime** counter, not tonight's rate | `pm2 describe` |
| Fragility | Under load *spikes*, blocking SQLite reads stall the async loop → `/health` momentarily 5–12 s → a 2 s port_guardian probe force-restarts a *serving* engine → self-amplifying | code read of `_health_inner` + timing |
| IB data feed | **BLIND** — Gateway (4002) down; `.env` `IB_ACCOUNT_ID` also wrong | `ibkr_data_connected=false`, error-log spam |
| TV MCP health | **flaps** true/false (CDP probe fails under load / TV Desktop not running) | two probes 20 min apart |
| Dashboard | Rich — 33–50 routes, already Orbitron/Tony-Stark styled | `dashboard/app/` |
| DB / tests / edges | 325 MB DB, 7,678-test suite green, MES+MGC trend edges gate-v2 PASS | prior verification |
| Repo hygiene | Trunk `fix/corey-standalone-vertex-routing` **71 ahead of master**, **30 open PRs, 20+ worktrees** | `git`, `gh pr list` |

**One-sentence truth:** *JARVIS is not broken — it is fragile under machine contention,
blind on real broker data, and fragmented across branches. "State of the art" =
make it spike-proof, real-data-true, coherent, and glanceable, with safe autonomy.*

---

## 1. North Star — what "Tony Stark ready" means here

Five properties, in priority order. A feature that doesn't serve one of these is out of scope.

1. **Reliable** — never falls over under its own or the machine's load; degrades gracefully; self-heals; every "outage" is observable and explained.
2. **Real-data-true** — every signal traces to a fresh, quality-gated data source; the system *refuses to pretend* (fail-closed to `NO_TRADE`/`HOLD` when blind, and *says so loudly*).
3. **Coherent** — one source of truth (one trunk, one HUD), not 30 PRs and 20 worktrees; one glance answers "is JARVIS healthy, what does it think, what has it done, what's it about to do."
4. **Safe autonomy** — it can run the loop end-to-end (analyze → decide → paper-execute → learn) without a human babysitting, inside hard, tested safety rails, with `LIVE_TRADING_ENABLED=False` until an explicit graduation.
5. **Sharp** — a growing stable of *validated* edges (gate-v2 + execution-fidelity), regime-aware routing, and cost-controlled intelligence.

---

## 2. Phased roadmap

### P0 — STABILIZE (reliability foundation) — *mostly shipped tonight*

**Objective:** the engine cannot be knocked over by a transient load spike, and every
restart is explained.

| # | Task | Owner | Status | Files |
|---|---|---|---|---|
| P0.1 | `/health` single-flight snapshot cache (collapse polling storm) | `[AUTO]` | **DONE** `f75e44f` | `engine/routers/health_router.py` |
| P0.2 | port_guardian probe 2 s→8 s + `port_bound` restart diagnostics | `[AUTO]` | **DONE** `f75e44f` | `engine/scripts/port_guardian.py` |
| P0.3 | conftest snapshot-reset fixture (test hygiene for the cache) | `[AUTO]` | **DONE** `f75e44f` | `engine/tests/conftest.py` |
| P0.4 | PM2 log rotator (archive-then-clear) + `pm2-logrotate` installer | `[AUTO]` | **DONE** `b274a8a` | `scripts/rotate_pm2_logs.ps1` |
| P0.5 | Offload the uncached synchronous SQLite calls in `_health_inner` (`db_manager.health_check`, `get_pending_approval_stats`, futures-sentiment) to `asyncio.to_thread` so a cache miss never blocks the loop even once | `[AUTO]` | TODO | `engine/routers/health_router.py` |
| P0.6 | Throttle/dedupe the IBKR `ConnectionRefused` log line (exponential backoff + "still down, N suppressed" summaries) so the error log stops regrowing at the source | `[AUTO]` (build) / `[AMO]` (restart) | TODO | `engine/data/market_data.py`, IBKR connector |
| P0.7 | Make `READINESS_DEADLINE` adaptive to observed boot time (record boot durations; set deadline = p95×1.5) instead of a fixed 360 s | `[AUTO]` | TODO | `engine/scripts/port_guardian.py` |
| P0.8 | Apply P0.1–P0.4 to the running engine | `[AMO]` restart | TODO | `restart_engine.ps1` |

**Acceptance:** run a synthetic load burst (20 concurrent `/health` + a `pytest -n auto`
storm) and confirm `/health` p95 < 1 s and **zero** health-timeout restarts.

---

### P1 — DATA TRUTH (make signals real, not stale)

**Objective:** every traded symbol has a fresh, quality-gated feed, and blindness is loud.

| # | Task | Owner | Files |
|---|---|---|---|
| P1.1 | Relog IB Gateway paper (port 4002) via GUI | `[AMO]` | IB Gateway app |
| P1.2 | Fix `engine/.env` `IB_ACCOUNT_ID` `DUP662235`→`DUR162217` (the real-time-subscribed paper account) | `[AMO]` | `engine/.env` |
| P1.3 | After P1.1/P1.2 + restart, verify `ibkr_data_connected=true` and `/prices/snapshot` returns non-`csv`/non-stale bars for MES/MGC/MCL/MNQ | `[AUTO]` verify | `/health`, `/brokers/positions`, `/prices/snapshot` |
| P1.4 | **Data-freshness kill-gate**: any symbol whose newest bar age > interval-scaled threshold is forced to `NO_TRADE` and surfaced RED on the HUD (extend the existing `bar_quality_gate` write-time guard to a *read-time freshness* guard on the decision path) | `[AUTO]` | `engine/data/bar_quality_gate.py`, decision path |
| P1.5 | Feed-provenance stamp on every signal: `{source, bar_age_s, quality}` persisted with the decision so the HUD/audit can prove what each call was based on | `[AUTO]` | pipeline result schema, DB |
| P1.6 | TV MCP flap fix: cache last-good CDP result with a longer TTL + a background refresher, and distinguish "TV Desktop not installed" (steady, expected) from "CDP transiently unreachable" so it stops flipping top-line health | `[AUTO]` | `engine/routers/health_router.py:121` |
| P1.7 | Corey #market-updates freshness already surfaced in `/health`; wire it into the HUD as a first-class tile (sole sanctioned futures-sentiment source) | `[AUTO]` | HUD |

**Acceptance:** with IB up, `/prices/snapshot` for all four futures shows `source=ibkr|tv`,
`bar_age_s` < threshold; with IB *pulled*, every futures signal flips to `NO_TRADE` and the
HUD shows a RED data tile within one poll.

---

### P2 — THE JARVIS HUD (the "Tony Stark" experience)

**Objective:** one screen answers, at a glance and in real time: *Is JARVIS healthy? What
does it believe? What has it done? What is it about to do? Can I trust it right now?*
The pieces already exist scattered across 33–50 routes — **the SOTA move is unification,
not net-new pages.**

| # | Task | Owner | Files |
|---|---|---|---|
| P2.1 | Audit the existing dashboard routes; map each widget to one of the 5 HUD zones below; identify overlap/dead pages | `[AUTO]` (agent fan-out — genuinely parallel) | `dashboard/app/**` |
| P2.2 | Build `/hud` — a single full-bleed command view with 5 zones: **(A) Vitals** (engine/DB/LLM/IB/TV/data-freshness, each green/amber/red with latency), **(B) Conviction** (per-symbol current stance + gate-v2/fidelity verdict + provenance), **(C) Ledger** (open positions, today's P&L, kill-switch state), **(D) Pipeline tape** (live 5-stage agent reasoning stream for the last decision), **(E) Next action** (what the engine will evaluate next + countdown) | `[AUTO]` | `dashboard/app/hud/` |
| P2.3 | Real-time transport: replace SWR polling on the HUD with SSE/WebSocket from the engine's existing `/events/recent` stream so the tape updates live without hammering `/health` (also reduces the very polling load P0 mitigates) | `[AUTO]` | engine events router, HUD client |
| P2.4 | "Trust pane" verdict: a single top-line **TRUST: HIGH/DEGRADED/BLIND** computed from data freshness + gate verdicts + safety state — the one-glance answer | `[AUTO]` | HUD, `/health` aggregation |
| P2.5 | Design system pass: consistent Orbitron/JetBrains, motion on state transitions, dark HUD aesthetic; theme-aware; no external asset fetches | `[AUTO]` | `dashboard/` styles |
| P2.6 | Mobile/Discord parity: the TRUST verdict + vitals pushed to the existing `discord-jarvis` MCP so the HUD is glanceable off-desk | `[AUTO]` | discord bridge |

**Acceptance:** open `/hud`, pull the IB feed, and watch Zone A + the Trust pane flip to
BLIND live (SSE, no refresh); restore it and watch them recover. A newcomer understands
JARVIS's entire state in < 10 seconds.

---

### P3 — SAFE AUTONOMY (close the loop, inside rails)

**Objective:** JARVIS runs analyze→decide→paper-execute→learn unattended, provably safe.

| # | Task | Owner | Files |
|---|---|---|---|
| P3.1 | Activate the execution-fidelity readiness path (PR #276, already wired): `READINESS_EDGE_MODE=wfo_plus_fidelity` + `ALLOW_PAPER_SIMULATED_ORDERS=True` | `[AMO-GATE]` | `engine/.env` |
| P3.2 | Accrue ~15 real IB paper fills for MES/MGC to satisfy the execution-fidelity criterion (edge already proven offline via gate-v2; this proves *execution*, not the edge — the calendar-infeasibility reframe) | `[AUTO]` runs once P1+P3.1 done | pipeline, `engine/readiness/phase3_criteria.py` |
| P3.3 | Safety-layer stress tests: kill-switch, daily-loss halt, drawdown halt, position caps — each with a red-team test that tries to bypass it | `[AUTO]` | `engine/risk/safety_layer.py`, tests |
| P3.4 | Autonomy heartbeat loop (compile via `/loopify`): every cycle preflight-checks deps, stamps GREEN/RED, fail-closes to `NO_TRADE` on any blind/stale/degraded input, notifies Amo only on RED | `[AUTO]` (report-only) / `[AMO-GATE]` (live) | `scripts/loops/`, registry |
| P3.5 | Post-decision learning: persist realized-vs-expected slippage + outcome, feed the Brier calibration surface already in `/health`, and auto-widen fidelity thresholds if live slippage drifts | `[AUTO]` | analytics, DB |
| P3.6 | `LIVE_TRADING_ENABLED` stays **False** through all of P3. Graduation to live is a separate, explicit, documented gate with its own checklist — **never** flipped autonomously | `[AMO]` | policy |

**Acceptance:** the heartbeat loop runs a full session unattended in paper mode, produces
a correct decision tape, halts correctly when a safety rail is tripped in a drill, and
pages Amo exactly once per genuine RED (no green-on-error, no spam).

---

### P4 — CONVERGENCE & HYGIENE (one source of truth)

**Objective:** kill the fragmentation that makes "what is even deployed?" unanswerable.

| # | Task | Owner | Files |
|---|---|---|---|
| P4.1 | Ratify `fix/corey-standalone-vertex-routing` as the de-facto trunk (it *is* what the engine runs); reconcile with `master` via PR #279; decide: fast-forward master to trunk, or keep the long-lived branch as trunk and retire `master` | `[AMO]` merge | git |
| P4.2 | Triage the 30 open PRs: merge the green safety-reviewed ones (incl. #276/#277/#278 + tonight's P0 PR), close the stale/superseded, rebase the rest | `[AMO]` gates merges, `[AUTO]` triages | `gh pr list` |
| P4.3 | Prune the 20+ worktrees under `.claude/worktrees/` whose branches are merged/dead (archive any with uncommitted work first — never delete work) | `[AUTO]` (report) / `[AMO]` (confirm) | `git worktree` |
| P4.4 | Single deploy story: document + script the one canonical "what's running and how to restart it" path (`restart_engine.ps1` + PM2 + port_guardian) so state is never ambiguous | `[AUTO]` | `docs/`, `scripts/` |
| P4.5 | Branch-protection + CI gate on the ratified trunk so drift can't silently reaccumulate | `[AMO]` | GitHub settings |

**Acceptance:** `git branch` + `gh pr list` + `git worktree list` each fit on one screen;
`docs/CURRENT_STATE.md` matches reality; one command answers "is the live engine on the
latest trunk?"

---

### P5 — SHARPEN (edge & intelligence)

**Objective:** more validated edges, regime-aware, cost-controlled.

| # | Task | Owner |
|---|---|---|
| P5.1 | Run the X-bookmark→backtest edge pipeline to completion; promote only gate-v2 + fidelity PASS candidates (2 Tier-A currently fail `mc_dd>6%` on equity-threshold — re-test at correct account size) | `[AUTO]` |
| P5.2 | Regime-aware routing: condition edge selection on the current volatility/trend regime (the `regime` dashboard route already computes this — wire it to the router) | `[AUTO]` |
| P5.3 | LLM cost control: the real cost lever is Claude Code model choice, not the engine (per the 07-06 cost refute); add a per-decision LLM-cost budget + the cheaper-failover-only design already on master | `[AUTO]` |
| P5.4 | Expand beyond MES/MGC only after each new symbol clears the *same* gate-v2 + execution-fidelity bar — no exceptions (MCL/MNQ remain BLOCKED until they do) | `[AUTO]` + `[AMO]` gate |

---

## 3. TONIGHT'S CRITICAL PATH — the working prototype we can test

This is the minimal sequence to a *demonstrably working, real-data* JARVIS tonight. It
interleaves the autonomous work (done/ready) with Amo's two GUI actions.

```
[DONE ][AUTO] P0.1-P0.4  health cache + port_guardian + log rotator  -> committed, PR pending
[STEP1][AMO ] Relog IB Gateway paper (4002) in the GUI               ~2 min
[STEP2][AMO ] Edit engine/.env: IB_ACCOUNT_ID DUP662235 -> DUR162217  ~1 min
[STEP3][AMO ] .\restart_engine.ps1   (applies P0 fixes + new .env)   ~229 s boot
[STEP4][AUTO] Verify: /health status=ok, ibkr_data_connected=true,
              tv+llm healthy, /prices/snapshot MES fresh (non-csv)
[STEP5][AUTO] Trigger ONE live pipeline run on MES; confirm the
              5-stage tape produces a real, provenance-stamped decision
[STEP6][AUTO] Confirm the decision surfaces on the dashboard
```

After STEP 6 we have proven the **entire loop end-to-end on real data**: fresh IB bars →
5-agent pipeline → gated decision → dashboard. That is the "working prototype we can test
tonight." The HUD (P2) and autonomy loop (P3) are the next sessions' build; the prototype
proves the spine works first.

**Why the two Amo steps can't be skipped:** IB Gateway login is an interactive GUI auth
(no headless path), and `.env` mutation + engine restart are Tier-3 gated by standing
policy. Everything *around* them is already done or automatable.

---

## 4. Amo's gated actions (the short list only you can do)

1. **IB Gateway relog** (paper, port 4002) — restores real broker data (unblocks P1, P3.2).
2. **`engine/.env` `IB_ACCOUNT_ID` → `DUR162217`** — points at the real-time-subscribed paper account.
3. **`.\restart_engine.ps1`** — applies the P0 fixes + the `.env` change (no `--reload`).
4. **Merge gating** — approve the P0 PR (below) + triage the 30 open PRs / master reconcile (P4).
5. **Later, explicitly:** flip `READINESS_EDGE_MODE`/`ALLOW_PAPER_SIMULATED_ORDERS` (P3.1) and, much later and separately, `LIVE_TRADING_ENABLED` (P3.6).

Everything not on this list is autonomous.

---

## 5. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| P0 cache serves stale health after a state change | Low | 1 s TTL; kill-switch enforced by safety layer not `/health`; TTL env-tunable to 0 |
| Widened probe timeout hides a genuinely hung engine longer | Low | Still caught within 1–2 polls (max ~16 s vs 360 s deadline); `port_bound` diagnostic distinguishes hung-vs-slow |
| Engine restart under contention re-triggers a boot cascade | Medium | Restart when peer-session load is low; P0.7 adaptive deadline; P0.5 removes the last blocking call |
| IB relog doesn't fix data (account/subscription) | Medium | P1.3 verifies `/prices/snapshot` freshness explicitly before claiming success |
| Machine contention (root cause) recurs from many Claude sessions | High | Don't fan out agents *onto the engine host* during load-sensitive work; P2.3 SSE cuts dashboard poll load |
| Branch reconcile discards live commits | Medium | P4.1 uses a PR + ahead/behind verification; **never** `checkout master`+restart without re-verifying (per 07-06 reversal) |

---

## 6. Execution notes

- **Contention discipline:** the verified root cause of the fragility is machine
  contention. Do **not** blindly run 10 parallel agents *on the engine host* during
  reliability-sensitive steps — that recreates the exact spike. Fan out agents only for
  host-independent parallel work (P2.1 route audit, P4.2 PR triage, P5.1 backtests).
- **Every "done" is verified, not assumed** (rules/verification.md health gates).
- **Fail-closed everywhere:** blind/stale/degraded input → `NO_TRADE`/`HOLD`, loudly.
- **Archive, never delete** (worktrees, logs, branches).
- This plan is the source of truth for the SOTA build; update the status column as
  phases land.
