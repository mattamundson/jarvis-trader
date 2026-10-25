# JARVIS — Money-No-Object Rebuild Blueprint (v2.0)

**Authored:** 2026-09-23
**Author:** Hermes (default profile) for Amo
**Status:** DESIGN ONLY — nothing in this document has been implemented, provisioned, purchased, or deployed.
**Supersedes:** `docs/JARVIS_SOTA_PLAN.md` (2026-07-06) — that plan was a *stabilization* plan for a running
system. This is a *rebuild* blueprint for the system as it should exist.
**Related:** `JARVIS_REBUILD_DASHBOARD_SPEC_v2.0.md`, `JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md`,
`JARVIS_REBUILD_DATA_INFRA_PROCUREMENT_v2.0.md`

**Asset-class mandate (scope fence — this is load-bearing):** JARVIS trades **futures, options, and
equities.** Concretely: index/rates **futures** (micros: MES, MNQ, MCL, MGC, M2K), **options** (equity-index
options — SPY, QQQ, SPX, VIX and their chains), and **equities** (the optionable single names already in the
watchlist: AAPL, TSLA, and whatever the equities sleeve validates). **Commodities research belongs to
`amo-arbitrage`, not to JARVIS** — that system owns ag/energy curves, WASDE vintages, weather ensembles and
satellite data. The amo-arbitrage work is referenced in this plan set only as a *planning pattern* to
emulate (blueprint + procurement list + owner-action + handoff, committed as durable artifacts), never as an
asset-class template. If a purchase, a sleeve, or a data feed in these documents does not serve futures,
options, or equities, it is out of scope by default and must be justified explicitly.

**Single-operator mandate (equally load-bearing):** JARVIS is a **personal system with exactly one user** —
Amo. There is no team, no org, no second operator, no product, and no customer. Consequences that run through
every layer of this plan:

- **There is no labor line in the cost model.** The build and the upkeep are agent loops (Hermes, Cursor,
  night-shift) plus Amo's own hours. Amo's hours are a **calendar constraint, not a cash cost**, and they are
  the scarcest input in the system — so the plan optimizes for *minimizing required attention*, not for
  maximizing capability.
- **No multi-user machinery.** No roles, no permissions model, no user management, no SSO, no tenancy, no
  audit-for-compliance. One operator, one auth boundary (Basic Auth + Tailscale), one audit trail that exists
  to make *the system* honest, not to satisfy a regulator.
- **No productization anywhere.** No public API, no paying users, no white-label, no marketing surface. If
  that ever changes it is a separate project with its own plan — not a silent assumption inside this one.
- **Verification cannot be delegated to the agent that produced the work.** The adversarial pass is run by a
  *different* agent instance/model than the one that built the strategy, and the final call is Amo's. That is
  the only structural need for "someone else," and it costs minutes, not a salary.
- **Ops must survive Amo being absent.** Self-healing, fail-closed, loud alerting, documented runbooks — because
  there is no one on call.

**Safety boundary (unchanged, non-negotiable):** this blueprint does not authorize live order routing.
`LIVE_TRADING_ENABLED` stays `False`. `DO_NOT_TRADE_SYMBOLS` membership, kill-switch thresholds, risk
parameters, and `.env` runtime values are **not** changed by anything in these documents. Any change to
those surfaces is a `[safety-review]` PR with Amo's explicit sign-off. No safety decision is ever routed
through an LLM.

---

## 0. How to read this

Four documents, in dependency order:

| # | Document | Answers |
|---|---|---|
| 1 | **BLUEPRINT** (this) | What the system should be, layer by layer, and why |
| 2 | **DASHBOARD_SPEC** | What the operator surface should be, screen by screen |
| 3 | **WORK_BREAKDOWN** | The task-level path from here to there, with exact paths and gates |
| 4 | **DATA_INFRA_PROCUREMENT** | What to buy, from whom, at what cost, and what only Amo can do |

A note on the framing. "Money is no object" does **not** mean "buy everything." It means the binding
constraint stops being budget and becomes *attention and credibility*. The single most expensive mistake
available to a well-funded trading system is buying resolution it cannot yet interpret. So this blueprint
buys, in strict order: **truth → validation → execution fidelity → breadth → polish.** Every purchase is
justified by the measurement it unlocks, not by the feature it enables.

---

## 1. Verified ground truth (probed 2026-09-23)

Everything below was read from the live system or repo, not recalled.

### 1.1 Host reality

| Fact | Value | Source |
|---|---|---|
| CPU | 14 logical cores | `os.cpu_count()` |
| RAM | 33.8 GB | `psutil.virtual_memory()` |
| System disk | 1023 GB total, **9.6 GB free** | `shutil.disk_usage('C:/')` |
| WSL2 | Ubuntu, running, 14 cores / ~5 GB allocated | `wsl -l -v`, `free -g` |
| Docker | installed (`Docker Desktop`), engine pipe flaky | `which docker` + prior probe |
| Node / pnpm | v22.23.2 / 11.22.0 | `node --version` |
| Python | 3.11.15 (engine venv), 3.14.4 (system), uv 0.11.19 | `python --version` |

**Two immediate structural facts:** (a) the machine is running a *trading engine*, a *dashboard*, a
*Hermes control plane*, a *brain daemon*, a *RAG index*, *38 open PRs* and *14 worktrees* on one
consumer Windows box with **9.6 GB of free disk**; (b) the research plane and the trading plane share
that box, so research compute can and does degrade trading-plane latency. Both are architecture problems,
not hygiene problems.

### 1.2 Engine surface area

| Fact | Value | Source |
|---|---|---|
| API routers | **85 files** | `engine/routers/` |
| Backtest/research modules | **271 files** | `engine/backtest/` |
| Test files | **735** | `engine/tests/` |
| Agent modules | 34 | `engine/agents/` |
| LLM modules | 11 | `engine/llm/` |
| Execution/broker modules | 18 | `engine/execution/` |
| DB | SQLite `jarvis_trader.db` — **55 tables**; `jarvis.db` — **0 tables (ghost)** | direct `sqlite_master` query |
| Ports in play | 8010 engine · 3010 dashboard · 8030 master-api · 8077 brain daemon · 9121 hermes-desktop · 9222 TV CDP · 4002 IB paper | repo + runtime |

### 1.3 Dashboard surface area

| Fact | Value | Source |
|---|---|---|
| Page routes | **58** (`page.tsx`) | `find dashboard/app -name page.tsx` |
| Components | **191** `.tsx` | `dashboard/components/` |
| Shared lib modules | 52 | `dashboard/lib/` |
| Stack | Next.js 15.3 · React 19 · Tailwind 3.4 · SWR 2.3 · Recharts 2.15 · lightweight-charts 5.1 · Radix primitives · three/@react-three-fiber | `dashboard/package.json` |
| Tests | node:test unit + vitest component + Playwright e2e + bundle-budget + runtime-contract + guards scripts | `dashboard/package.json` scripts |
| Auth | HTTP Basic at the edge (`dashboard/middleware.ts`), framed as a trading control surface | `dashboard/middleware.ts` |

### 1.4 Validation authority (the part that actually matters)

| Fact | Value | Source |
|---|---|---|
| Gate v2 PF CI lower floor | `GATE_PF_CI_LOWER = 1.10` | `engine/backtest/_gate_v2_helpers.py:35` |
| Gate v2 p_edge (CORE) | `GATE_P_EDGE = 0.95` | `:38` |
| Gate v2 p_edge (ALT) | `GATE_P_EDGE_ALT = 0.60` | `:79` |
| MC 95th DD (CORE / ALT) | `0.05` / `0.04` | `:41`, `:46` |
| Fixed-params min PF | `GATE_FIXED_PARAMS_MIN_PF = 1.20` | `engine/backtest/_constants.py:17` |
| DSR gate | `DSR_GATE_MIN = 0.10` (CORE); campaign floor `0.30` | `forward_test.py:414`, `build_verdict_trust_register.py:41` |
| Verdict staleness | `MAX_VERDICT_AGE_DAYS = 14` | `gate_v2_policy.py` |
| Authorizing verdict | only `verdict == "PASS"`; default-deny on missing | `gate_v2_policy.py` |
| Verdict artifacts on file | **23 entries** in `engine/data/gate_v2_verdicts/` (incl. README, CSV, archive, DM studies) | directory listing |
| Blocklist | `DO_NOT_TRADE_SYMBOLS = {MGC, MCL, MNQ, M2K}` | `engine/backtest/signals.py:135` |
| Enabled paper instruments | `ACTIVE_INSTRUMENTS` = those with `enabled=True` in `paper_config.py` — currently **MES (1h)** only | `paper_config.py:350` |
| Options watchlist | `SPY, QQQ, AAPL, TSLA` | `engine/config.py` ~L638 |
| Options validation gap | SPY has a **REJECTED** WFE verdict and trades anyway; QQQ/AAPL/TSLA have **no verdict on file at all** — an absent verdict, not a failing one (Amo accepted 2026-08-03, documented in `engine/CLAUDE.md`) | `engine/CLAUDE.md`, `wfe_snapshots` query |

### 1.5 Repo/governance reality

| Fact | Value | Source |
|---|---|---|
| Open PRs | **38** | `gh pr list --state open` |
| Worktrees | **14** | `git worktree list` |
| CI | GitHub Actions workflows present (`ci.yml`, `pr-governance.yml`, `safety-invariant-check.yml`, `deploy-check.yml`, `p0-verify.yml`, `claude-pr-review.yml`, `ci-startup-canary.yml`, `es-research-platform.yml`) — hosted runs have been failing **before steps execute** (billing/spend-limit) | `.github/workflows/`, PR #913 annotations |
| Governance | PR governance requires plan/program/work-package/phase/safety-class/objective/dependencies/acceptance-criteria/verification-rung/evidence/migration/production-impact metadata | `.github/workflows/pr-governance.yml`, PR #913 body |

### 1.6 The one-sentence truth

> JARVIS is not under-built — it is **over-built and under-verified**: 85 routers, 271 research modules and
> 58 dashboard routes sit on a single consumer Windows box with 9.6 GB free, backed by SQLite, where the
> **validation authority covers 1 of the 5 symbols actually trading**, and 38 PRs / 14 worktrees mean
> nobody can answer "what is deployed?" without archaeology.

---

## 2. The honest triage: what I would keep, rebuild, and retire

This is the most important section in the document. A rebuild that keeps everything is not a rebuild.

### 2.1 KEEP (genuinely good, load-bearing, hard-won)

| Asset | Why it survives |
|---|---|
| **Gate v2 + its thresholds** (`_gate_v2_helpers.py`) | The single best thing in the repo. PF-CI-lower + p_edge + MC-DD + DSR at campaign trial count is a real deflation-aware gate. It stays as the *authority*. |
| **The Judge** — CPCV, PSR/DSR, CSCV-PBO, content-addressed trial ledger (`engine/backtest/cpcv.py`, `deflated_sharpe.py`, `campaign_trials.py`, `family_fdr.py`, `evaluation_harness.py`) | Correct, tested, and the thing that makes every other purchase worth anything. |
| **`gate_v2_policy.is_strategy_authorized()`** | A genuine single source of truth for "may this symbol submit orders", with default-deny and staleness. Keep the *contract*, reimplement the *storage*. |
| **Safety layer** (`engine/risk/safety_layer.py`) | Pure Python, never LLM-driven, hardcoded limits. Correct design. |
| **`DO_NOT_TRADE_SYMBOLS` precedence** | Blocklist beats every carve-out. Keep exactly as is. |
| **5-stage agent pipeline + agent roster** (`engine/agents/`) | Good *evidence* machinery. Demote from decision-maker to evidence-producer (see L7). |
| **Trade-intent / approval / OMS skeleton** (`trade_intents_router.py`, `approval/`, `execution/oms_v2.py`, `order_lifecycle_ledger.py`) | Right shape: intent → risk → OMS → broker adapter. Needs fidelity, not replacement. |
| **Dashboard stack choice** (Next 15 / React 19 / Tailwind / lightweight-charts / SWR) | Correct stack. The problem is 58 routes and 191 components, not the framework. |
| **Verification culture** | `rules/verification.md`, guards scripts, bundle budget, runtime-contract checks, Playwright. Rare and valuable — keep and enforce. |
| **Market-brief + post-mortem + journal loops** | Real learning surface. Keep, wire to the Judge. |

### 2.2 REBUILD (right idea, wrong substrate)

| Asset | Verdict | Why |
|---|---|---|
| **Storage** | SQLite → **Postgres 16 + TimescaleDB** | 55 tables, blocking reads on the async loop, two DB files (one a ghost), quarantine tables, corrupt-archive table. SQLite is the single largest source of the "fragile under load" class of bugs. |
| **Process supervision** | PM2 + `port_guardian` → **systemd (Linux) / WinSW (Windows)** with real probes | The guardian once killed a *healthy* engine because a probe exceeded 2 s under contention (fixed in PR #913). Self-restarting supervisors that can kill serving processes are an anti-pattern. |
| **Health** | `/health` single-flight cache → **typed health contract + SLO burn** | Health must be a contract with named legs (`ibgateway_alive`, `execution_connected_verified`, `ib_execution_stale`, `ibkr_data_connected`) and explicit "unknown" semantics, never a boolean that a stub can satisfy. |
| **Verdict storage** | JSON files in `engine/data/gate_v2_verdicts/` → **DB table + content-addressed artifact store** | 23 files, ignored-by-git, force-added by hand, no schema. Verdicts are the most load-bearing data in the system and they live in a directory. |
| **Data ingestion** | ad-hoc loaders per symbol → **one PIT ingestion framework** | `bar_quality_gate.py` exists and is good; it needs to become the *only* door into the store, with `ingest_ts` / `vintage_ts` / `source_hash` on every row. |
| **Dashboard IA** | 58 routes → **~14 surfaces** with one HUD | Route sprawl is why "is JARVIS healthy?" needs 6 tabs. |
| **LLM pipeline role** | decision-maker → **evidence summarizer + hypothesis generator under a trial budget** | An LLM must never be the authority on whether an edge exists or whether it is safe to trade. |
| **Secrets** | `.env` files → **1Password / vault + generated runtime env** | Keeps working locally; makes rotation and audit possible. |

### 2.3 RETIRE (delete, archive, or stop maintaining)

| Asset | Action | Why |
|---|---|---|
| `engine/data/jarvis.db` (0 tables) | **Delete after archive** | Ghost DB. Two DB files is a bug generator; docs already flag it. |
| `*_quarantine` tables as a permanent state | Replace with a **rejected-rows table + reason + replay tool** | Quarantine without a replay path is a landfill. |
| `daily_pnl_corrupt_archive` | One-time reconciliation, then retire | An archive table inside the live DB is a smell. |
| `engine/backtest/archive/`, `engine/data/backups/`, `*.bak*` in-tree | Move to object storage / cold archive | Disk is at 9.6 GB free. |
| 20+ root-level CSV/MD analysis dumps (`*.csv`, `*-Whatitdoes.csv`, `build_output.txt`, `files.zip`) | Move to `archive/` or out of repo | Repo root is being used as a scratch dir; it makes `git status` useless (106 dirty entries, and 3251 in the parent `master-jarvis` workspace). |
| Superseded research runners (the 271-file set) | **Triage to ~40 kept, rest archived** | Each runner is a maintenance and confusion tax. Keep the ones with verdicts. |
| Stale worktrees (14) and stale PRs (38) | Archive branches, close superseded, keep ≤3 live | "What is deployed" must be answerable. |
| `six`-style duplicate symbol configs (`MCL` appears twice, `MNQ` twice, `MES` twice in `paper_config.py`) | One entry per symbol with explicit timeframe sub-configs | Duplicate keys are how a "disabled" strategy keeps firing. |

---

## 3. The five invariants

Every design decision below is downstream of these. They are ordered; earlier ones win.

1. **Truth before features.** No surface may display a number it cannot trace to a fresh, quality-gated,
   point-in-time source. Unavailable is a valid, loud, first-class state. `NO_TRADE` / `BLIND` /
   `UNVERIFIED` are *answers*, not failures.
2. **One authority per question.** Exactly one component answers "is this symbol tradable"
   (`gate_v2_policy` contract), one answers "is the engine healthy" (health contract), one answers
   "does this edge survive deflation" (the Judge). No surface may re-derive a verdict.
3. **Fail closed, and say why.** Any missing/stale/ambiguous input degrades to the safe state and emits a
   machine-readable reason. Safety is pure Python and never LLM-mediated.
4. **Replayability is the asset.** Raw vendor payloads are immutable, hashed, and stored before
   transformation. Every number in the system must be recomputable from artifacts. If a claim cannot be
   replayed, it cannot be published.
5. **One screen answers "am I safe to trade right now?"** If answering that requires more than one
   glance, the UI has failed regardless of how much data it shows.

---

## 4. Target architecture, layer by layer

### L0 — Host & runtime substrate

**The core architectural move: split the planes.**

| Plane | Runs | Where | Why there |
|---|---|---|---|
| **Trading plane** | engine (FastAPI), IB Gateway, order path, risk, kill switch | **Dedicated Linux host** (mini-PC or small cloud VM) with UPS, wired network, systemd units, `Restart=on-failure` with backoff, `WatchdogSec` | This is the plane where a 30-second stall costs money. It must not share a kernel, disk, or CPU with research. |
| **Research plane** | backtests, sweeps, CPCV/PBO, ML training, LLM experiments | **Cloud burst** (spot CPU/GPU) + WSL2 for local iteration | Bursty by nature; should not degrade trading latency; should be reproducible from a container image. |
| **Operator plane** | dashboard (Next 15), Discord/WhatsApp push, mobile | **Local-first** (current model) + Tailscale ingress | The operator console is private, low-latency, and adjacent to safety state. The amo-arbitrage cloud pattern is explicitly *wrong* here (see the 2026-09-15 divergence memo). |
| **Control plane** | Hermes agent, cron, night-shift loops, RAG/gbrain | Current Windows box, containerized where possible | Already works; keep it off the trading plane's critical path. |

**Windows reality check.** The trading plane moving to Linux is the single highest-value infrastructure
change available, because it converts "PM2 + port_guardian + OneDrive + PowerShell wedge + 9.6 GB free"
into "systemd + journald + 400 GB free." The operator plane can stay Windows — that is where Amo works.

**Concrete substrate decisions:**

- **Containers everywhere except the broker.** Engine, worker, dashboard, ingestion, Postgres, Redis all
  as containers with pinned digests. IB Gateway stays a native process (its GUI auth is interactive) —
  but the *engine* talks to it over a documented local socket/port contract.
- **One image, three entrypoints.** `jarvis-engine`, `jarvis-worker` (scheduler/ingestion), `jarvis-api`
  (read-only public/API surface). Identical dependency resolution across dev/CI/prod; kills the
  `requirements.txt` vs `requirements-core.txt` split that currently exists only to dodge a broken pin.
- **Supervision:** `systemd` units with `RestartSec`, `StartLimitBurst`, `MemoryMax`, and a *liveness
  probe that never kills a serving process* — probes report, supervisors restart only on a real
  failed health contract, and a restart requires two consecutive failures.
- **No `--reload`, ever, in any plane.** Already a rule; make it structurally impossible via the unit file.

**Acceptance:** kill -9 the engine under a synthetic 20×/health load burst; the trading plane recovers in
< 60 s with zero false restarts, and the research plane's CPU burn does not move engine p99 latency.

### L1 — Data lakehouse (the foundation everything else stands on)

**Principle: one door in, immutable raw, point-in-time always.**

```
vendor API ──▶ ingest worker ──▶ RAW (immutable, hashed, object storage)
                                   │
                                   ├─▶ normalize ─▶ STORE (Timescale hypertables)
                                   │                   bars_1m/5m/1h/1d per symbol
                                   │                   ticks (opt-in, bounded retention)
                                   │                   options_chain (surface snapshots)
                                   │                   fundamentals (vintage-stamped)
                                   │                   positioning (CFTC, flows)
                                   │
                                   └─▶ quality gate ─▶ ACCEPTED | REJECTED(+reason, replayable)
```

**Schema rules (non-negotiable):**
- Every row carries `ingest_ts` (when we learned it), `vintage_ts` (when the source published it),
  `source` (vendor id), `source_hash` (content hash of the raw payload), `quality` (gate verdict).
- Bars are stored **as published**, never back-adjusted in place. Continuous/back-adjusted series are
  *derived views* with their own provenance, because the current repo's use of `{SYM}_CONT_ADJ` as the
  only series is exactly what makes calendar/roll strategies impossible to backtest.
- **Per-contract curves are first-class.** For futures, store `(symbol, delivery_month)` rows with
  settlement/volume/OI. This unlocks roll yield, calendar spreads, and honest execution modelling.
- **Vintage everything the government revises.** WASDE, NASS, CPI, payrolls — snapshot as published. You
  cannot buy this back later.

**Quality gate contract (extends the existing `bar_quality_gate.py`):**
`freshness` (age vs interval-scaled threshold) · `completeness` (gaps vs session calendar) · `monotonicity`
· `range sanity` (|Δ| vs ATR) · `volume sanity` · `duplicate` · `session coverage`. A symbol failing any
check is `UNTRADEABLE` for that interval, with the failing check named.

**Read path:** research and production read from the *same* store with the same PIT semantics. No
"research uses the CSV, prod uses the API" split — that is how a backtest and a live decision diverge.

**Acceptance:** delete every derived table and rebuild them from RAW; every verdict and every dashboard
number reproduces bit-for-bit. Pull a vendor feed and confirm every dependent symbol flips to
`UNTRADEABLE` with a named reason within one poll.

### L2 — State store, cache, and event bus

| Need | Choice | Rationale |
|---|---|---|
| Transactional state | **Postgres 16** | Positions, orders, intents, approvals, ledger, config, verdicts, journal. ACID, real concurrent readers, no blocking-the-event-loop class of bug. |
| Time series | **TimescaleDB** extension | Same Postgres, hypertables + continuous aggregates. One store to back up. |
| Research analytics | **DuckDB over Parquet** | Fast columnar scans over the immutable raw/derived files; zero server. |
| Cache / hot state | **Redis** (already present) | Price snapshots, single-flight locks, alert cooldowns, rate-limit counters. |
| Event bus | **Redis Streams** → NATS JetStream when consumer count > ~5 | Decision events, fills, health transitions, pipeline stage transitions. Enables SSE fan-out to the HUD without polling. |
| Object storage | **S3-compatible (R2)** | Immutable raw vendor payloads, model artifacts, verdict artifacts, backups. |

**Kill the polling storm structurally:** the dashboard subscribes to a stream; `/health` becomes a
cheap read of a materialized status row updated by the health worker. No more N widgets × M poll
intervals hammering one endpoint.

**Acceptance:** 20 concurrent HUD clients plus a research sweep produce no measurable engine latency
change; event stream replay from a cursor reconstructs the last hour of system state.

### L3 — Research & validation harness (the Judge)

This layer decides what is allowed to be believed. It is the moat.

**Components:**

1. **Experiment registry.** Every run is a row: hypothesis, code hash, data snapshot hash, params, trial
   count, metrics, artifact path, author (human or agent). No run, no verdict.
2. **Trial ledger (campaign-scoped).** Content-addressed; the honest deflation denominator. Every
   configuration evaluated — including the ones nobody liked — increments the campaign count. (This is
   what exposed MGC's DSR collapse at true trial count and the rank11 deflation measurement.)
3. **The Judge:** CPCV with embargo, PSR/DSR at campaign count, CSCV-PBO, block-bootstrap CIs, cost
   stress, family-wise FDR across the tested family.
4. **Gate v2 as the *policy* layer** on top of the Judge: `PF_CI_LOWER ≥ 1.10`, `p_edge ≥ 0.95`
   (CORE) / `≥ 0.60` (ALT), `MC_95th_DD ≤ 5%` (CORE) / `≤ 4%` (ALT), `fixed_params_min_PF ≥ 1.20`,
   `DSR ≥ 0.10`, `≥ MIN_OOS_TRADES_TOTAL`, `rolling_wfo ≥ MODERATE`.
5. **Forward evidence contract.** Paper-forward fills with slippage vs expectation; a verdict is not
   promotable without it. C1-style trade counts stay as a *gate*, never as a target to engineer toward.
6. **Adversarial review lane.** Every PASS gets an automatic "try to kill it" pass: parameter-neighbor
   robustness, regime-slice stability, cost sensitivity, data-revision sensitivity, and a
   seed/bootstrap re-draw. A PASS that cannot survive being attacked is not a PASS.
7. **Verdict store.** Postgres table + content-addressed artifact. Schema-versioned, immutable,
   supersedable, with `verdict`, `reason`, `family`, `strategy_id`, `as_of`, `expires_at`, `evidence[]`.
   The 23 JSON files become rows plus artifacts.

**The verdict contract (single source of truth):**

```
is_tradable(symbol, strategy_id, now) -> TradabilityVerdict
  = DENY  if symbol ∈ DO_NOT_TRADE_SYMBOLS            (highest precedence, unconditional)
  = DENY  if symbol ∈ VALIDATION_ONLY_INSTRUMENTS
  = DENY  if paper_config[symbol].enabled is False
  = DENY  if no fresh PASS verdict for (symbol, strategy family)
  = DENY  if data quality ≠ ACCEPTED for the required interval
  = DENY  if kill switch latched / daily loss / drawdown breach
  = ALLOW otherwise, with the verdict id that authorized it
```

Every ALLOW carries the verdict id. Every DENY carries the reason code. The dashboard renders the same
function — it never re-implements it.

**Acceptance:** a lucky-noise series with PSR > 0.95 must FAIL at campaign trial count (already proven in
the ported Judge tests); a genuine edge must PASS; and flipping any single input (stale data, missing
verdict, blocklisted symbol) must flip the decision with the correct reason code.

### L4 — Strategy portfolio (stop trading one strategy)

The current system has one live instrument (MES 1h SMA trend) and an options watchlist with no verdicts
on file. That is not a portfolio; it is a bet with a dashboard.

**Target sleeves** (each with its own gate path, its own forward-evidence clock, and its own risk budget).
**Scope fence:** every sleeve below is futures, options, or equities. The crypto and prediction-market rows
are explicitly **isolated, non-core, research-only** — they are not JARVIS's mandate and never feed the core
trading authority; commodities belong to `amo-arbitrage` and are not represented here at all.

| Sleeve | Instruments | Edge source | Data requirement |
|---|---|---|---|
| **Trend / managed-futures** | MES, MNQ, MCL, MGC, M2K (+ more micros) | Time-series momentum, breakout, ATR-trail | Deep continuous + per-contract history |
| **Intraday auction / structure** | MES, MNQ | Session structure, ONH/ONL, value-area, auction imbalance | Intraday bars + volume profile, real-time |
| **Volatility / options** | SPY, QQQ, SPX, VIX | Regime-conditioned premium selling, defined-risk verticals, skew, term structure | Full options surface (IV, greeks, OI by strike), intraday |
| **Relative value / spreads** | MES/MNQ ratio, calendar spreads, crack/crush (later) | Mean reversion in spreads, roll yield | Per-contract curves |
| **Macro / event** | Index futures, rates proxy | Scheduled-event drift, pre/post-event vol | PIT macro vintages, event calendar |
| **Crypto (small, isolated)** | BTC/ETH perps | Trend + funding-rate carry | Exchange API, funding history |
| **Prediction markets (research-only)** | Polymarket | Calibration arbitrage vs model probability | Market + orderbook history |

**Portfolio construction:** correlation-aware risk budgeting across sleeves, volatility targeting,
fractional Kelly capped hard, drawdown governor, per-sleeve and portfolio-level kill switches. A sleeve
that loses its verdict loses its budget automatically — no human step.

**Promotion ladder (per sleeve, no exceptions):**
`hypothesis → registry → Judge → gate v2 → adversarial pass → paper forward (n trades, slippage within
tolerance) → shadow live (no orders, compare to paper) → canary (minimum size) → scaled`.
Each rung is a stored artifact; a sleeve cannot skip a rung because a dashboard is green.

**Acceptance:** ≥2 sleeves with forward-confirmed evidence; a portfolio-level risk report where every
number is derivable from stored artifacts.

### L5 — Risk & portfolio construction

| Component | Contract |
|---|---|
| **Risk policy (versioned, hashed)** | Every decision records the policy hash that sized it. Changing risk = new policy version, never an edit in place. |
| **Pre-trade checks** | Symbol allowed · verdict fresh · data quality · max contracts per symbol · gross/net exposure · portfolio heat · correlation bucket · daily loss remaining · drawdown remaining · kill-switch state · duplicate-intent suppression. All pure functions, all unit-tested, all fail-closed. |
| **Sizing** | ATR/vol-targeted, futures-aware (multiplier-correct — the repo already fixed equity-vs-futures sizing once), with a hard per-trade risk cap and a portfolio cap. |
| **Kill switch** | Latchable, timestamped, reason-coded, persisted, *and tested for the unlatch path*. Latching must survive a restart; unlatching must be a deliberate, logged, human act. |
| **Drawdown governor** | Scales risk down by tier as drawdown deepens, before the hard switch. |
| **Limits** | Daily loss, max drawdown, max open positions, max new positions per session, max order rate, fat-finger band (price sanity vs last/ATR). |

**Acceptance:** a red-team suite where each rail is attacked by a test that *tries* to bypass it (the
repo already has the beginnings of this). Every bypass attempt must fail closed and log.

### L6 — Execution & OMS

Current shape is right (`TradeIntent → Risk → OMS → Broker adapter`). The gap is **fidelity**.

| Piece | Target |
|---|---|
| **Broker adapters** | IBKR (primary), Alpaca (equities paper), Schwab (later), crypto exchange adapter. One interface, contract-tested with a fake broker. |
| **Order types** | Market, limit, stop, stop-limit, bracket (parent + STP child), OCO, GTC/DAY, TIF-correct for futures vs options. |
| **Execution algos** | TWAP / iceberg / participation-capped for size; never market-sweep a thin book. |
| **Reconciliation** | Continuous position + order reconciliation against the broker; drift is an *alert*, not a silent fix. |
| **TCA** | Every fill stores expected vs realized price, slippage in ticks and bps, latency, and venue. TCA feeds back into the cost model the Judge uses — closing the loop between backtest assumptions and reality. |
| **Idempotency** | Client order ids, submission dedup (repo has `submission_dedup.py`), and a lifecycle ledger so a restart cannot double-submit. |
| **Simulator** | A broker simulator with configurable latency, partial fills, and rejects — so paper results are not fantasy. |

**Acceptance:** shadow-mode fills within tolerance of paper; a forced broker disconnect leaves the OMS in
a provably consistent state with no orphan orders; TCA report for the last N trades.

### L7 — Intelligence layer (LLM/RAG/agents)

**Reframe: the LLM is a researcher and a narrator, never an authority.**

| Component | Target |
|---|---|
| **Evidence pipeline** | Agents produce *typed evidence objects* (claim, source, confidence, timestamp), never free-text verdicts that become decisions. |
| **Decision narrative** | The "why" shown on the HUD is assembled from evidence objects + the Judge verdict, so it cannot hallucinate a reason. |
| **Hypothesis generation** | LLM proposes strategies *into the registry* under a hard trial budget — every proposal increments the campaign trial count, which is exactly what keeps deflation honest. |
| **Provider routing** | Multi-provider with cost/latency/quality routing and a budget per decision; a decision that cannot afford its LLM budget degrades to rules-only, not to a fabricated narrative. |
| **Eval harness** | Golden decision set + regression eval: prompt/model change must not silently change decisions. Prompt versions are artifacts. |
| **RAG** | Vault + trade journal + post-mortems + research notes into one retrieval layer with citations; retrieval is *evidence with provenance*, not vibes. |
| **Cost accounting** | Per-decision, per-agent, per-model cost rows (the repo has the beginnings: `pipeline_llm_costs`, `cost_tracker.py`). |

**Acceptance:** disabling every LLM provider leaves the system fully functional, fully honest, and
degraded *in narrative only* — decisions, sizing and safety are unaffected.

### L8 — Observability & SLOs

| Layer | Target |
|---|---|
| **Metrics** | Prometheus (already installed) with named SLIs: decision latency, data freshness per symbol, order round-trip, reconciliation drift, error budget burn. |
| **Traces** | OpenTelemetry across pipeline stages and the order path — one trace per decision. |
| **Logs** | Structured JSON, correlation-id per decision, rotated, never containing secrets (repo has a log sanitizer — keep and test it). |
| **Dashboards** | Grafana for engineering SLOs (separate from the operator HUD — different audiences, different jobs). |
| **Alerts** | Route by *cause*: data stale → data owner channel; safety latch → immediate page; verdict expired → research channel; CI red → engineering. No green-on-error, no spam. |
| **Synthetic canary** | A scheduled end-to-end probe (data → decision → paper order → reconcile) that runs on a schedule and reports health as a *decision*, not a ping. |
| **Dead-man switch** | If the heartbeat stops, something must scream. Absence of alerts must not look like health. |

**Acceptance:** every incident class in the last 90 days is detectable from metrics alone; the synthetic
canary fails loudly when any leg is broken.

### L9 — Security, secrets, governance

| Concern | Target |
|---|---|
| **Secrets** | Vault/1Password-backed, injected at runtime; `.env` only as a local dev convenience. Rotation runbook + rotation test. Never in argv (the IBC/DCE lessons already learned). |
| **Auth** | Engine API key + per-route scopes; dashboard Basic Auth at the edge + Tailscale for remote; public routes are an explicit allowlist with no control-plane data. |
| **Least privilege** | Broker credentials scoped to the trading plane; research plane has read-only market data access, no broker keys. |
| **Audit** | Every safety-relevant action (latch, unlatch, config change, order, manual override) writes an append-only audit row with actor, reason, before/after. |
| **CI** | Required checks: ruff, mypy, tests, secret scan, dependency audit, migration check, gate-v2 invariant tests. Protected trunk; no direct pushes. |
| **Governance** | `[safety-review]` label + CODEOWNERS on `risk/`, `execution/`, `config.py`, `signals.py`, kill-switch paths. Amo's sign-off is the merge gate. |
| **Backups** | Postgres PITR + nightly logical dump + restore drill (a backup never restored is a hope). |

### L10 — Product surface (the operator HUD)

Specified in full in `JARVIS_REBUILD_DASHBOARD_SPEC_v2.0.md`. Summary of the architectural decision:
**58 routes → 1 HUD + ~13 focused surfaces**, one design system, SSE-first realtime, typed data contracts,
and a hard rule that every displayed number carries provenance and freshness.

### L11 — Ops automation & self-healing

| Loop | Cadence | Contract |
|---|---|---|
| Data freshness watchdog | 1 min | Detects stale/absent feeds; marks symbols untradeable; alerts by cause |
| Decision heartbeat | per session | Runs the pipeline; fail-closed on any degraded input; writes a decision row |
| Reconciliation | 1 min during session | Broker vs internal positions/orders; drift → alert, never auto-fix silently |
| Verdict freshness | daily | Expires verdicts at 14 days; auto-demotes symbols whose evidence lapsed |
| Research loop | nightly | Registry → Judge → adversarial → report; proposes, never promotes |
| Backup + restore drill | nightly / weekly | Verifies restorability, not just completion |
| Incident post-mortem | on incident | Template + stored artifact + linked decision ids |
| Self-audit | weekly | Verifies the invariants in §3 against live state, and *fails loudly* if the system drifted |

---

## 5. Migration strategy: strangler fig, never big-bang

The rebuild must not stop the system from working, because the system currently holds live paper evidence
(the MES forward clock) and the operator depends on it daily.

**Rules:**
1. **No big-bang cutover.** Every layer is replaced behind a stable interface, one at a time.
2. **The interface is the contract.** `is_tradable()`, the health contract, the verdict contract, and the
   decision row schema are frozen *before* their implementations move.
3. **Dual-run and compare.** New and old implementations run side by side; divergence is logged and must
   reach zero before the old path is retired. This applies to the verdict path, the decision path, and
   the portfolio math.
4. **Evidence clock continuity.** The MES paper forward count must never reset. Migration must preserve
   the trade ledger's identity and history (import, verify counts, then switch reads).
5. **Rollback is a first-class artifact.** Every phase ships with a documented rollback and a tested
   restore path.
6. **Archive, never delete.** Old tables, branches, worktrees, and artifacts get archived to cold storage
   with a manifest, then removed from the live tree.

---

## 6. Phases, gates, and acceptance

Each phase has an **entry gate** (what must be true to start), an **exit gate** (what must be true to
finish), and an explicit **rollback**. Detailed task-level work lives in the WORK_BREAKDOWN doc.

| Phase | Name | Exit gate (the thing that must be true) |
|---|---|---|
| **P0** | Truth & hygiene | Disk ≥ 15% free; repo root clean; ≤3 worktrees; ≤5 open PRs; ghost DB gone; `git status` readable; all suites green on the safe marker set |
| **P1** | Substrate split | Trading plane on Linux under systemd; research plane containerized; engine p99 unaffected by a research CPU burn; zero false restarts in a 72 h soak |
| **P2** | Data lakehouse | One ingestion door; PIT stamps on every row; per-contract curves loaded; quality gate enforced read-side; derived tables rebuildable from RAW |
| **P3** | Verdict authority | Verdicts in DB + artifact store; `is_tradable()` is the only authority; every trading symbol has a fresh verdict *or* is explicitly, visibly unverified; blocklist precedence proven by test |
| **P4** | Judge wired | Campaign trial ledger feeds DSR at true count; adversarial pass mandatory for PASS; the lucky-noise test fails at campaign count; verdict provenance replayable |
| **P5** | Risk & execution fidelity | Bracket/stop/TIF correct; reconciliation drift alerting; TCA on every fill; shadow-mode within tolerance; kill-switch latch survives restart and unlatch is logged |
| **P6** | HUD rebuild | One screen answers "safe to trade now?" in <10 s; every number has provenance + freshness; realtime via stream (no polling storm); a11y + perf budget met |
| **P7** | Portfolio breadth | ≥2 sleeves with forward evidence; options sleeve has a real surface store and honest verdicts (or is explicitly OFF); risk budget per sleeve enforced |
| **P8** | Autonomy & hardening | Unattended session runs end-to-end in paper; every rail red-teamed; synthetic canary green; SLOs met for 30 days; post-mortems automated |

**Note on P7 and the options gap.** The current state — SPY trading on a REJECTED verdict and QQQ/AAPL/TSLA
trading with *no* verdict — is the clearest example of why the rebuild exists. The rebuild does not
retroactively halt those (that is Amo's call, and a routing change); it makes the gap *visible and
unignorable* on the HUD until a real verdict exists.

---

## 7. Cost model

All figures are planning estimates `[ASSUMPTION]`; vendor pricing is negotiated and tiered. Detail and
vendor names live in the procurement document.

| Aspect | Year-1 indicative `[ASSUMPTION]` | Note |
|---|---|---|
| Market data (futures deep + per-contract, equities, options surface) | $25k–$150k | The only purchase that creates edge; see procurement doc |
| Reference/alt data (fundamentals vintages, positioning, news) | $5k–$60k | Mostly cheap; engineering-heavy |
| Infrastructure (dedicated Linux host, cloud research burst, storage, observability) | $6k–$40k | Compute is *not* the constraint |
| LLM inference (multi-provider, per-decision budget) | $3k–$30k | Control is a budget, not a ceiling |
| **Labor** | **$0** | There is no labor line. Build and upkeep are agent loops; Amo's hours are the calendar constraint, not a cost. |
| **Total realistic year 1 (cash)** | **~$40k–$280k** | All external services. Nothing else. |

**Correction on the record — two superseded passes, disclosed.** (1) The first pass priced "people" at
**$250k–$600k**, i.e. 2 full-time engineers. (2) The second pass "corrected" that to $25k–$195k of contracted
build labor by dividing 78 tasks into engineer-days. **Both were wrong for the same reason: they priced
labor at all.** JARVIS is a single-operator personal system (see the single-operator mandate above); the 78
tasks are executed by agent loops, and the only non-agent input is Amo's attention, which is not a cash
line. What the task count *does* legitimately measure is **required attention**: 78 tasks, 73 tagged
`[AUTO]`, and 11 gate rows that need Amo's explicit call. That is the honest resource statement, and it is
expressed in **gates and hours, not people**.

**The honest "money is no object" answer:** money buys exactly one thing here — **resolution** (better data,
cleaner validation). It does not buy conviction, and it does not buy the build, because the build is agent
work. The system's binding constraint is *credible, cost-surviving, forward-confirmed edge*, which is gated
by the harness in L3 — which is why L3 comes before breadth, and why data is the only purchase that matters.

**What the 11 gate rows actually are (attention, not headcount).** The 78-task breakdown carries **8 `[AMO]`
+ 3 `[AMO-GATE]`** tags (plus 13 `[SAFETY]` rows that need a `[safety-review]` sign-off). These are not build
hours — they are **decisions only the operator can make**: budget approval, trunk ratification, broker and
entitlement account actions, symbol-promotion sign-off, live-trading graduation. Each is minutes to hours.
The one item that cannot be self-supplied is **adversarial review of a PASS by an agent that did not produce
it** — solved by running the review in a *different* session/model, not by hiring anyone.

---

## 8. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Rebuild becomes a permanent project that never ships | **High** | High | Strangler-fig with per-phase exit gates; every phase independently valuable; no phase depends on a later phase to be useful |
| R2 | Validation authority stays thin (1 of 5 symbols) while breadth grows | High | **Critical** | P3/P4 before P7; the HUD renders unverified symbols as UNVERIFIED, not as normal |
| R3 | Data vendor lock-in / licensing terms block a future redistribution decision | Medium | Low–High | Immutable raw archive; buy internal-use terms now, treat any redistribution licence as a separate future decision (not a current goal) |
| R4 | Machine/disk failure destroys evidence | Medium | High | Object-storage raw archive, Postgres PITR, tested restore drills, off-box backups |
| R5 | A "safety" refactor silently weakens a rail | Medium | **Critical** | `[safety-review]` + CODEOWNERS + invariant tests that fail closed + dual-run comparison |
| R6 | LLM narrative drifts from the Judge's verdict | Medium | High | Narrative assembled from typed evidence objects; eval harness on golden decisions |
| R7 | Overfitting re-enters through breadth (more strategies = more trials = more false discovery) | **High** | High | Campaign trial ledger as the single deflation denominator; every proposal increments it |
| R8 | Operator trust collapses from one wrong number on the HUD | Medium | High | Provenance + freshness on every number; "unavailable" is a first-class state |
| R9 | Cost creep in data subscriptions without a matching measurement | Medium | Medium | Every purchase must name the measurement it unlocks; quarterly review |
| R10 | Bus factor: one machine, one operator, one agent stack | **High** | High | Documented runbooks, reproducible containers, restore drills, self-healing + fail-closed + loud alerting so the system survives Amo's absence. The mitigation is **reproducibility, not a second person** |

---

## 9. Anti-patterns this design refuses

1. **Buying alt data before the trial ledger exists.** Unlogged trials make deflation a lie.
2. **Scaling infrastructure before edge.** Faster losses are still losses.
3. **Loosening a gate to make a dashboard green.** `0/99`-style honesty is the most valuable number on a page.
4. **Letting an LLM decide anything safety-relevant.** It narrates; the Judge and the safety layer decide.
5. **Trading an unverified symbol quietly.** Unverified is a visible state, never a default.
6. **Engineering toward a forward-evidence count.** Changing parameters to make trades happen creates a new strategy and resets the clock.
7. **Self-restarting supervisors that can kill serving processes.** Report loudly; restart only on a real, confirmed failure.
8. **Two sources of truth for anything.** One authority per question (§3.2), enforced by test.
9. **Big-bang cutover of a system holding live evidence.** Strangler fig only.
10. **Deleting evidence to free disk.** Archive to object storage with a manifest.
11. **Publishing a number that cannot be replayed from artifacts.**
12. **Mobile/voice/polish before the decision content deserves a push notification.**

---

## 10. What only Amo can do

These are the human gates. Everything else in this blueprint is agent-executable.

1. **Approve the plane split** (trading plane → dedicated Linux host) and the budget for it.
2. **Broker account actions:** IBKR market-data entitlements (the 354/10168/10197 class of errors), paper-account ID correctness, and any subscription purchase.
3. **Sign `[safety-review]` PRs** — risk, execution, config, kill-switch, symbol gates.
4. **Authorize the options gap decision:** halt SPY/QQQ/AAPL/TSLA paper routing until verdicts exist, or accept the gap in writing (current state is accepted-but-visible).
5. **Data licensing decisions** if anything ever becomes public.
6. **The live-trading graduation decision** — never autonomous, never implied.
7. **Ratify the trunk** (which branch is master of truth) so the 38-PR backlog can be resolved.
8. **The GitHub billing/spend fix** so CI can run at all.

---

## 11. Open decisions (need an answer before P2)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Trading plane host | (a) dedicated mini-PC (b) cloud VM near broker (c) stay on Windows with hard isolation | **(a)** — cheapest latency-honest option, no cloud dependency for order routing |
| D2 | Store | (a) Postgres+Timescale (b) ClickHouse (c) stay SQLite | **(a)** |
| D3 | Data vendor for deep futures | (a) Databento (b) CME DataMine direct (c) both | **(a)** for research depth, **(b)** later for licensing if public |
| D4 | Options surface vendor | (a) ORATS (b) CBOE DataShop (c) CME FOP settles | **(c)+ delayed IBKR now**, buy (a) when the vol sleeve is funded |
| D5 | Verdict storage | (a) DB + artifact store (b) keep JSON files | **(a)** |
| D6 | Dashboard rebuild scope | (a) full IA rebuild (b) incremental page-by-page | **(a)** — the IA *is* the problem |
| D7 | Trunk | (a) fast-forward master to current trunk (b) keep long-lived branch | **(a)**, with protection on |
| D8 | Options gap | (a) halt until verdicts (b) accept-and-display | **(b) now, (a) at P7** — visibility first, routing change only with Amo's call |

---

## 12. Definition of done

JARVIS is "rebuilt" when all of the following are simultaneously true and provable from artifacts:

1. One command answers *what is running, where, on which commit* — and the answer is short.
2. Every displayed number traces to a fresh, quality-gated, PIT source, and says so.
3. One screen answers *am I safe to trade right now?* in under ten seconds, including *why*.
4. `is_tradable()` is the only authority on tradability, and every trading symbol is either
   freshly verified or loudly unverified.
5. Every PASS survived the Judge at true campaign trial count *and* an adversarial pass.
6. Every sleeve that trades has forward evidence with realized slippage inside tolerance.
7. Every safety rail has a red-team test that fails closed.
8. Every raw vendor payload is immutable, hashed, and replayable; every derived number is rebuildable.
9. The system runs a full session unattended in paper mode, halts correctly in a drill, and pages
   exactly once per genuine red.
10. The research plane can burn all the CPU it wants without moving trading-plane latency.
11. `git status`, `git worktree list`, and `gh pr list` each fit on one screen.
12. Restore-from-backup has been executed, not just configured.

---

## Appendix A — Current → target mapping (quick reference)

| Layer | Now | Target |
|---|---|---|
| Host | Windows 11, 9.6 GB free, all planes | Trading plane Linux/dedicated; research burst; operator local |
| Supervision | PM2 + port_guardian | systemd/WinSW, two-strike restart, never kills a serving process |
| Store | SQLite (55 tables) + ghost DB | Postgres 16 + TimescaleDB |
| Raw data | per-symbol CSVs/caches | Immutable hashed object store + Parquet |
| Quality | write-time bar gate | read-time quality contract, named failure reasons |
| Verdicts | 23 JSON files in a directory | DB rows + content-addressed artifacts |
| Trial ledger | partially adopted | mandatory for every experiment |
| Judge | present (CPCV/DSR/PBO) | wired into the verdict path at campaign count |
| Risk | safety layer + config | versioned hashed policy + pre-trade check suite + governor |
| Execution | intent → OMS → IBKR | + algos, TCA, reconciliation alerting, simulator |
| LLM | decision-adjacent | evidence/narrative only, budgeted, evaluated |
| Observability | /health + logs | SLIs, traces, SLO burn, dead-man, synthetic canary |
| UI | 58 routes, 191 components | 1 HUD + ~13 surfaces, one design system, SSE |
| Repo | 38 PRs, 14 worktrees, 106 dirty working-tree entries | protected trunk, ≤5 PRs, ≤3 worktrees |

## Appendix B — Verified sources used

`engine/routers/` · `engine/backtest/` · `engine/tests/` · `engine/backtest/_gate_v2_helpers.py` ·
`engine/backtest/_constants.py` · `engine/backtest/gate_v2_policy.py` · `engine/backtest/signals.py:135` ·
`engine/backtest/paper_config.py` · `engine/config.py` · `engine/CLAUDE.md` · `engine/requirements-core.txt` ·
`dashboard/package.json` · `dashboard/middleware.ts` · `dashboard/app/**` · `dashboard/lib/` ·
`.github/workflows/` · `docs/JARVIS_SOTA_PLAN.md` · `docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_v1.0.md` ·
`second-brain/reports/night-shift/AMO_ARBITRAGE_VS_JARVIS_ARCH_DECISION_2026-09-15.md` ·
live probes: `sqlite_master` on `engine/data/jarvis_trader.db`, `os.cpu_count()`, `psutil`, `shutil.disk_usage`,
`gh pr list`, `git worktree list`, `wsl -l -v`.

*Nothing in this document was implemented. No credentials were read. No paid resource was created.
No live-trading, risk, kill-switch, broker-routing, or symbol-gate change was made or proposed for
immediate execution.*
