# JARVIS Rebuild — Work Breakdown & Execution Gates (v2.0)

**Authored:** 2026-09-23 · **Status:** DESIGN ONLY — nothing implemented
**Companion to:** `JARVIS_REBUILD_BLUEPRINT_v2.0.md`, `JARVIS_REBUILD_DASHBOARD_SPEC_v2.0.md`,
`JARVIS_REBUILD_DATA_INFRA_PROCUREMENT_v2.0.md`

**Scope fence:** JARVIS is **futures + options + equities**. Commodities research (ag/energy curves, WASDE,
weather, satellite) is **`amo-arbitrage`'s mandate** and is out of scope here — no task in this breakdown may
buy, ingest, or model commodity data. Crypto and prediction markets appear only as isolated research
surfaces that never feed the trading authority.

**Single-operator mandate:** JARVIS is a **personal system with exactly one user — Amo.** No team, no org, no
product, no customers, and **no labor line anywhere**. Every task is either `[AUTO]` (agent loops) or an
operator gate. Amo's hours are the calendar constraint, so tasks are scoped to minimize required attention.

**Owner legend:** `[AUTO]` agent-executable in a worktree · `[AMO]` requires Amo (GUI login, budget, sign-off,
trunk decision) · `[AMO-GATE]` built autonomously, flipped on only by Amo · `[SAFETY]` requires a
`[safety-review]` PR + Amo's explicit sign-off.

**Test-marker law (from the repo's own hazard):** never pass a bare `pytest -m` override. It *replaces* the
default marker exclusion and can re-enable `integration_ib` tests that submit real paper orders. Use the
default marker selection, or `-m "not slow and not manual and not integration_ib"`, or `-k` filters.

---

## Phase P0 — Truth & hygiene (the floor)

*Entry:* nothing. *Exit:* the repo and the machine are readable, and every claim about state is verifiable.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P0-1 | Free disk: archive `engine/data/backups/`, `engine/backtest/archive/`, `*.bak*`, `files.zip`, stray caches to object storage with a manifest | `[AUTO]` | `engine/data/backups/`, `engine/backtest/archive/` | `shutil.disk_usage('C:/').free` ≥ 15% ; manifest lists every archived path + hash |
| P0-2 | Clean repo root: move the ~60 root-level `*.csv` / `*-Whatitdoes.csv` / `build_output.txt` / `FILES_CREATED.txt` dumps into `docs/archive/root-scratch/` | `[AUTO]` | repo root | `git status --porcelain \| wc -l` drops from 106 to < 40 |
| P0-3 | Retire the ghost DB | `[AUTO]` | `engine/data/jarvis.db` (0 tables) | File archived + deleted; no code references it (`grep -rn "jarvis\.db" engine/`) |
| P0-4 | Quarantine tables → rejected-rows table with reason + replay tool | `[AUTO]` | `engine/data/jarvis_trader.db` (`*_quarantine`), new `engine/data/rejected_rows.py` | A rejected row can be replayed end-to-end; test proves it |
| P0-5 | Worktree/branch triage: archive merged/dead worktrees to a tagged archive branch; keep ≤ 3 live | `[AUTO]` (report) / `[AMO]` (confirm) | `git worktree list` (14) | `git worktree list \| wc -l` ≤ 3 |
| P0-6 | PR triage: close superseded, merge green safety-reviewed, rebase the rest; target ≤ 5 open | `[AMO]` gates merges / `[AUTO]` triages | 38 open PRs | `gh pr list --state open \| wc -l` ≤ 5 |
| P0-7 | Trunk ratification: decide master vs long-lived branch; protect the trunk | `[AMO]` | GitHub settings, `master` | `git log --oneline -1 master` is the commit the engine runs |
| P0-8 | Restore CI: fix the GitHub billing/spend gate so workflows can start | `[AMO]` | GitHub account | `gh run list --limit 1` shows a run with steps, not `startup_failure` |
| P0-9 | Baseline test truth: run the safe marker set on engine + dashboard, record pass/fail counts to an artifact | `[AUTO]` | `engine/tests/`, `dashboard/tests/` | Artifact records exact counts; no "full green" claim without it |
| P0-10 | Repo hygiene guards: pre-commit hook blocking new root-level scratch files and files > 5 MB | `[AUTO]` | `.pre-commit-config.yaml` | A test commit with a stray CSV is rejected |

**P0 exit gate:** disk ≥ 15% free · untracked < 200 · worktrees ≤ 3 · open PRs ≤ 5 · CI runs · baseline
artifact written · ghost DB gone.

---

## Phase P1 — Substrate split (trading plane vs research plane)

*Entry:* P0 exit. *Exit:* research compute cannot degrade trading latency; zero false restarts in 72 h.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P1-1 | Choose and provision the trading-plane host (D1) | `[AMO]` | — | Host reachable; UPS + wired network confirmed |
| P1-2 | Containerize the engine: one image, entrypoints `engine` / `worker` / `api`; pinned digests | `[AUTO]` | new `infra/docker/Dockerfile`, `docker-compose.yml` | Image builds reproducibly; identical deps in dev/CI/prod |
| P1-3 | Kill the requirements split by fixing the `questdb==1.2.1` pin (it has no py3.12 wheel and is why `requirements-core.txt` exists) | `[AUTO]` | `engine/requirements.txt`, `engine/requirements-core.txt` | One requirements file installs clean on Linux + Windows |
| P1-4 | systemd units (Linux) / WinSW (Windows) with two-strike restart and `MemoryMax` | `[AUTO]` | new `infra/systemd/jarvis-*.service` | `kill -9` the engine under load → recovers < 60 s, zero false restarts |
| P1-5 | Retire `port_guardian`'s kill path; convert it to a **reporter** that never kills a serving process | `[AUTO]` + `[SAFETY]` | `engine/scripts/port_guardian.py`, `engine/tests/test_port_guardian_orphan_kill.py` | Test asserts a healthy-but-slow engine is **never** killed |
| P1-6 | Health contract: typed legs with `OK/DEGRADED/DOWN/UNKNOWN/STALE`, named probes, `unknown` on probe failure | `[AUTO]` | `engine/routers/health_router.py`, new `engine/health/contract.py` | A stub broker can no longer report healthy (proves the SIMULATOR-stub hazard is closed) |
| P1-7 | Move blocking SQLite calls off the event loop (or eliminate them with P2's Postgres) | `[AUTO]` | `engine/routers/health_router.py`, DB layer | Synthetic 20×`/health` burst: p95 < 1 s |
| P1-8 | Research-plane isolation: backtests/sweeps run in containers with CPU/memory caps | `[AUTO]` | `infra/docker/`, runner scripts | Burn all 14 cores in research; engine p99 latency unchanged |
| P1-9 | 72 h soak with synthetic load + research burn; record restart/latency evidence | `[AUTO]` | artifact: `reports/soak_<date>.md` | Zero false restarts; latency SLO met |

**P1 exit gate:** soak artifact shows zero false restarts and unaffected latency; health contract rejects stubs.

---

## Phase P2 — Data lakehouse

*Entry:* P1 exit. *Exit:* one ingestion door, PIT stamps everywhere, derived data rebuildable from RAW.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P2-1 | Stand up Postgres 16 + TimescaleDB; schema for bars, per-contract curves, options, fundamentals, positioning, quality | `[AUTO]` | new `infra/db/migrations/*.sql` | Migrations apply forward and back; schema test passes |
| P2-2 | RAW layer: immutable, hashed, object-stored vendor payloads | `[AUTO]` | new `engine/ingest/raw_store.py` | Re-ingesting the same payload is a no-op; hash mismatch is an alert |
| P2-3 | One ingestion door: every loader goes through the framework (`ingest_ts`, `vintage_ts`, `source`, `source_hash`, `quality`) | `[AUTO]` | `engine/ingest/`, replaces ad-hoc loaders in `engine/backtest/fetch_*.py` | A new source cannot be added without passing the framework |
| P2-4 | Quality gate as a **read-time contract** with named failing checks | `[AUTO]` | `engine/data/bar_quality_gate.py` → `engine/data/quality.py` | Pulled feed → symbol flips `UNTRADEABLE` with the check name within one poll |
| P2-5 | Per-contract curves (settlement/volume/OI per delivery month) — unlocks calendar/roll/crush | `[AUTO]` (after procurement) | `engine/ingest/curves.py` | A calendar spread backtest runs end-to-end for the first time |
| P2-6 | Migrate existing SQLite history into Postgres with count reconciliation | `[AUTO]` | migration script + report | Row counts match per table; ledger identity preserved (see P3-6) |
| P2-7 | Derived-series provenance: back-adjusted/continuous series are views with their own lineage | `[AUTO]` | `engine/ingest/derive.py` | Rebuild derived tables from RAW; every verdict reproduces |
| P2-8 | Data freshness SLA per feed + owner + alert route | `[AUTO]` | `engine/monitoring/`, alert config | A stopped feed pages the owner, not the void |

**P2 exit gate:** delete every derived table → rebuild from RAW → all verdicts and dashboard numbers reproduce.

---

## Phase P3 — Verdict authority

*Entry:* P2 exit. *Exit:* `is_tradable()` is the only authority; blocklist precedence proven by test.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P3-1 | Verdict store: Postgres table + content-addressed artifact; schema-versioned, immutable, supersedable | `[AUTO]` | new `engine/verdicts/store.py`, migration | 23 JSON files import with identical semantics |
| P3-2 | Freeze the `is_tradable(symbol, strategy_id, now)` contract; keep `gate_v2_policy` semantics (default-deny, 14-day staleness) | `[AUTO]` | `engine/backtest/gate_v2_policy.py` → `engine/verdicts/policy.py` | Contract tests: missing/stale/FAIL/blocklisted all DENY with correct reason codes |
| P3-3 | **Blocklist precedence test**: `DO_NOT_TRADE_SYMBOLS` beats every carve-out including MES's | `[AUTO]` `[SAFETY]` | `engine/tests/test_do_not_trade_gate.py` | Test proves MCL/MNQ/MGC/M2K can never be allowed by any path |
| P3-4 | Dual-run: old and new authority both computed per decision; divergence logged until zero | `[AUTO]` | `engine/backtest/signals.py`, decision path | Divergence artifact reaches 0 for N sessions before cutover |
| P3-5 | Dashboard/API consume the authority (never re-derive) | `[AUTO]` | `engine/routers/*`, `dashboard/lib/*` | A grep test proves no second implementation exists |
| P3-6 | **Ledger identity preservation**: MES paper history imported without resetting the forward clock | `[AUTO]` `[SAFETY]` | `paper_trades` migration | Trade count before == after; no new fills from the migration |
| P3-7 | Surface the options gap: SPY REJECTED-but-trading and QQQ/AAPL/TSLA verdict-absent render as loud anomalies | `[AUTO]` | `/evidence` surface, `engine/routers/readiness_router.py` | Screenshot baseline shows the anomaly rows |

**P3 exit gate:** one authority, proven by test; every trading symbol is freshly verified or loudly unverified.

---

## Phase P4 — Judge wired into the verdict path

*Entry:* P3 exit. *Exit:* every PASS survived the Judge at true campaign count **and** an adversarial pass.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P4-1 | Campaign trial ledger mandatory: every experiment (including LLM-proposed) increments the count | `[AUTO]` | `engine/backtest/campaign_trials.py`, `cpcv.py` | Attempting a verdict without a ledger row fails |
| P4-2 | DSR computed at campaign count in the live verdict path | `[AUTO]` | `engine/backtest/deflated_sharpe.py` | The lucky-noise fixture: PSR > 0.95 undeflated → FAILS at campaign count |
| P4-3 | Adversarial pass: parameter-neighbor robustness, regime-slice stability, cost stress, revision sensitivity, bootstrap redraw | `[AUTO]` | new `engine/backtest/adversarial.py` | A PASS that fails any attack is downgraded automatically |
| P4-4 | Family-wise FDR across the tested family | `[AUTO]` | `engine/backtest/family_fdr.py` | Family report generated per campaign |
| P4-5 | Forward-evidence contract wired to promotion (n trades + slippage tolerance) | `[AUTO]` `[SAFETY]` | `engine/backtest/forward_test.py`, promotion gate | Promotion without forward evidence is impossible by code |
| P4-6 | Verdict provenance replay: verdict → evidence artifacts → RAW data, one command | `[AUTO]` | new `engine/verdicts/replay.py` | Replay of any verdict reproduces its numbers exactly |

**P4 exit gate:** lucky-noise fails at campaign count; every PASS has an adversarial artifact; replay works.

---

## Phase P5 — Risk & execution fidelity

*Entry:* P4 exit. *Exit:* shadow-mode within tolerance; reconciliation alerting; kill-switch latch survives restart.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P5-1 | Versioned risk policy with hash recorded on every decision | `[AUTO]` `[SAFETY]` | `engine/config.py`, `engine/risk/` | Every decision row carries `policy_hash`; changing risk requires a new version |
| P5-2 | Pre-trade check suite (pure functions, fail-closed, unit-tested) | `[AUTO]` `[SAFETY]` | `engine/risk/pretrade.py` | Red-team tests attack each rail; every bypass fails closed |
| P5-3 | Order-type completeness: bracket (parent+STP), OCO, TIF-correct futures vs options, fat-finger band | `[AUTO]` `[SAFETY]` | `engine/execution/bracket_orders.py`, `oms_v2.py` | Contract tests per order type against the fake broker |
| P5-4 | Execution algos for size (TWAP/participation cap) | `[AUTO]` | `engine/execution/algos.py` | Simulator shows no market-sweep on a thin book |
| P5-5 | Reconciliation alerting: drift is an alert, never a silent fix | `[AUTO]` `[SAFETY]` | `engine/execution/position_reconciler.py`, `ibkr_reconciler.py` | Injected drift raises an alert and blocks new orders until resolved |
| P5-6 | TCA: expected vs realized, ticks/bps, latency, per fill; feeds the cost model | `[AUTO]` | new `engine/execution/tca.py` | TCA report for last N trades; cost model updated from it |
| P5-7 | Broker simulator (latency, partial fills, rejects) | `[AUTO]` | new `engine/execution/sim_broker.py` | Paper results stop being latency-free fantasy |
| P5-8 | Kill-switch hardening: latch survives restart; unlatch is deliberate, logged, audited | `[AUTO]` `[SAFETY]` | `engine/risk/safety_layer.py` | Restart test: latch persists; unlatch writes an audit row |
| P5-9 | Shadow mode: run live-intent without orders; compare to paper | `[AUTO]` `[AMO-GATE]` | new `engine/execution/shadow.py` | Shadow vs paper divergence within tolerance |

**P5 exit gate:** shadow within tolerance · every rail red-teamed · kill switch survives restart · TCA live.

---

## Phase P6 — HUD rebuild

*Entry:* P3 exit (needs the authority); can overlap P4/P5. *Exit:* the 10-second test passes; kill test passes.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P6-1 | Tokens + Tier-1 primitives + `StatValue` | `[AUTO]` | `dashboard/styles/tokens.css`, `dashboard/components/ui/*` | Visual baseline per primitive |
| P6-2 | Provenance types + zod contracts + generated client | `[AUTO]` | `dashboard/lib/contracts/*` | A backend shape change fails the build |
| P6-3 | Aggregate endpoints + multiplexed SSE stream | `[AUTO]` | `engine/routers/hud_router.py`, `dashboard/lib/stream.ts` | One connection; no per-widget polling |
| P6-4 | Global status rail + HUD zones A–E | `[AUTO]` | `dashboard/app/page.tsx`, `dashboard/components/blocks/*` | 10-second test + kill test pass |
| P6-5 | ESLint laws: `no-bare-numeric-render`, `no-client-metric-derivation`, `no-page-level-fetch-interval` | `[AUTO]` | `dashboard/eslint.config.mjs` | The laws are build errors, not review comments |
| P6-6 | Surfaces T1–T13, one at a time, with 301s from absorbed routes | `[AUTO]` | `dashboard/app/<surface>/` | Redirect tests + Playwright spec + visual baseline per surface |
| P6-7 | Route retirement + component disposition (usage audit, not by hand) | `[AUTO]` | `dashboard/app/**`, `dashboard/components/**` | 58 → 14 routes; usage report written |
| P6-8 | a11y gate + perf budgets per route | `[AUTO]` | Playwright + `check-bundle-budget.mjs` | axe clean; budgets enforced in CI |

**P6 exit gate:** Definition of Done §13 in the dashboard spec, verified by automated tests.

---

## Phase P7 — Portfolio breadth

*Entry:* P4 + P5 exit. *Exit:* ≥ 2 sleeves with forward evidence; risk budget per sleeve enforced.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P7-1 | Sleeve scaffolding: per-sleeve verdict family, forward clock, risk budget | `[AUTO]` | `engine/portfolio/sleeves.py` | A sleeve without a verdict gets zero budget automatically |
| P7-2 | Sleeve: intraday auction/structure (MES/MNQ) | `[AUTO]` | `engine/backtest/` new runners | Judge → gate v2 → adversarial → forward |
| P7-3 | Sleeve: volatility/options (SPY/QQQ/SPX/VIX) — requires the surface store (procurement) | `[AUTO]` | `engine/options/`, surface ingestion | Honest verdicts replace the current gap; or the sleeve stays explicitly OFF |
| P7-4 | Sleeve: relative value (index ratio, later calendar/crush) — requires per-contract curves | `[AUTO]` | new runners | Runs on curves from P2-5 |
| P7-5 | Portfolio construction: correlation-aware risk budgeting, vol targeting, fractional-Kelly cap, DD governor | `[AUTO]` `[SAFETY]` | `engine/portfolio/allocator.py` | Portfolio report derivable from artifacts; caps enforced |
| P7-6 | Promote at most one new sleeve to paper; keep the rest research-only until forward evidence exists | `[AMO-GATE]` `[SAFETY]` | promotion gate | Promotion artifact + Amo sign-off |

**P7 exit gate:** ≥ 2 sleeves with forward evidence; every other sleeve explicitly OFF and visibly unverified.

---

## Phase P8 — Autonomy & hardening

*Entry:* P6 + P7 exit. *Exit:* unattended paper session; SLOs met for 30 days; post-mortems automated.

| ID | Task | Owner | Files / paths | Verification |
|---|---|---|---|---|
| P8-1 | Unattended session loop: preflight → decide → paper-execute → reconcile → learn, fail-closed | `[AUTO]` | `scripts/loops/` | Full session artifact with a correct decision tape |
| P8-2 | Synthetic canary: data → decision → paper order → reconcile, scheduled | `[AUTO]` | `engine/monitoring/canary.py` | Canary fails loudly when any leg breaks |
| P8-3 | SLOs + error budgets + Grafana boards | `[AUTO]` | `engine/monitoring/`, `infra/grafana/` | Burn alerts fire on a synthetic SLO breach |
| P8-4 | Dead-man switch: absence of heartbeat is an alarm | `[AUTO]` | `engine/monitoring/deadman.py` | Killing the heartbeat pages within the window |
| P8-5 | Backup + **restore drill** (verified, not configured) | `[AUTO]` | `infra/backup/`, runbook | A restore is executed and recorded |
| P8-6 | Incident post-mortem automation with decision-id linkage | `[AUTO]` | `engine/journal/postmortem.py` | An injected incident produces a post-mortem artifact |
| P8-7 | Weekly invariant self-audit (§3 of the blueprint) against live state | `[AUTO]` | new `scripts/audit/invariants.py` | Audit fails loudly on drift |
| P8-8 | Live-trading graduation checklist prepared — **not executed** | `[AMO]` | `docs/LIVE_TRADING_READINESS.md` | Checklist exists; `LIVE_TRADING_ENABLED` still `False` |

**P8 exit gate:** 30 days of SLO compliance; canary + dead-man proven; restore drilled.

---

## Cross-cutting workstreams

| ID | Stream | Tasks | Owner |
|---|---|---|---|
| X-1 | Secrets: vault injection, rotation runbook + rotation test, never in argv | P0–P2 | `[AUTO]` |
| X-2 | Auth/scopes: engine key scopes, dashboard edge auth, Tailscale, public-route allowlist | P1 | `[AUTO]` |
| X-3 | Audit trail: append-only rows for every safety-relevant action | P3–P5 | `[AUTO]` `[SAFETY]` |
| X-4 | CI required checks: ruff, mypy, tests, secret scan, dep audit, migration check, gate-v2 invariants | P0 | `[AUTO]` |
| X-5 | CODEOWNERS on `risk/`, `execution/`, `config.py`, `signals.py`, kill-switch paths | P0 | `[AMO]` |
| X-6 | Runbooks: restart, incident, data-feed loss, broker disconnect, restore | P1–P8 | `[AUTO]` |
| X-7 | Evidence artifacts: every phase writes a report with commands + raw output | all | `[AUTO]` |

---

## Execution order & parallelism

```
P0 ──▶ P1 ──▶ P2 ──▶ P3 ──┬─▶ P4 ──▶ P7 ──┐
                          │               ├──▶ P8
                          └─▶ P5 ─────────┘
                          └─▶ P6 (needs P3; overlaps P4/P5)
```

- **Strictly serial:** P0 → P1 → P2 → P3 (each depends on the prior substrate).
- **Parallelizable:** P4 (research) ∥ P5 (execution) ∥ P6 (UI) — different surfaces, different owners.
- **Do not parallelize onto the trading host.** The repo's own diagnosis: machine contention is the root
  cause of the fragility class. Fan out agents only for host-independent work.

---

## Phase gate checklist (use this verbatim per phase)

```
[ ] Entry gate satisfied and recorded
[ ] Tasks complete with per-task verification command output captured
[ ] Exit gate measured, not asserted
[ ] Rollback documented and (for P1+) rehearsed
[ ] Evidence artifact written to reports/ with commands + raw output
[ ] Safety surface unchanged, or [safety-review] PR opened with Amo's sign-off
[ ] No credential read/printed; no paid resource created without explicit approval
[ ] Docs updated (this file's status column + CURRENT_STATE)
[ ] Old path retired only after dual-run divergence == 0
```

---

## What this plan deliberately does not do

- It does not halt SPY/QQQ/AAPL/TSLA paper routing. That is a routing change and Amo's call (D8). It makes
  the gap visible.
- It does not touch `DO_NOT_TRADE_SYMBOLS`, risk thresholds, kill-switch state, or `.env` runtime values.
- It does not enable live trading at any phase. P8-8 prepares a checklist; it does not flip anything.
- It does not reset the MES forward-evidence clock; P3-6 exists specifically to preserve it.
- It does not purchase or provision anything. See the procurement document for what to buy and who must
  approve it.
