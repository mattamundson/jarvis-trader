# JARVIS-MIP-1.1 Complete Implementation Bundle

**Snapshot base commit:** `6b1217d7e846c3281ced802ea47df25f94714c9d`<br>
**Generated:** 2026-09-12<br>
**Purpose:** archival, reviewable rendering of every planning/code artifact created in this session

> Generated snapshot: source files remain authoritative. Regenerate this document after changes; do not edit embedded copies.

## Included files

- `.github/workflows/plan-validation.yml`
- `docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_1.1.md`
- `docs/plans/jarvis-mip-1.1/ADOPTION_REVIEW.md`
- `docs/plans/jarvis-mip-1.1/adoption-decisions.schema.json`
- `docs/plans/jarvis-mip-1.1/adoption_decisions.json`
- `docs/plans/jarvis-mip-1.1/charters/A-01.md`
- `docs/plans/jarvis-mip-1.1/charters/A-02.md`
- `docs/plans/jarvis-mip-1.1/charters/A-03.md`
- `docs/plans/jarvis-mip-1.1/charters/A-06.md`
- `docs/plans/jarvis-mip-1.1/charters/K-01.md`
- `docs/plans/jarvis-mip-1.1/charters/O-01.md`
- `docs/plans/jarvis-mip-1.1/charters/O-05.md`
- `docs/plans/jarvis-mip-1.1/evidence/A-01/contradictions.md`
- `docs/plans/jarvis-mip-1.1/evidence/A-01/mutation-spine.md`
- `docs/plans/jarvis-mip-1.1/evidence/A-01/runtime-inventory.json`
- `docs/plans/jarvis-mip-1.1/evidence/O-01/check-inventory.json`
- `docs/plans/jarvis-mip-1.1/evidence/O-01/debt-baseline.json`
- `docs/plans/jarvis-mip-1.1/evidence/PAG-0-adoption.json`
- `docs/plans/jarvis-mip-1.1/plan.schema.json`
- `docs/plans/jarvis-mip-1.1/templates/evidence-manifest.example.json`
- `docs/plans/jarvis-mip-1.1/templates/work-package-charter.md`
- `docs/plans/jarvis-mip-1.1/work_packages.json`
- `scripts/validate_jarvis_mip.py`
- `tests/plan/test_validate_jarvis_mip.py`

## Full contents

<details>
<summary><code>.github/workflows/plan-validation.yml</code></summary>

<pre><code>name: JARVIS MIP Validation

permissions:
  contents: read

on:
  pull_request:
    paths:
      - &quot;docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_1.1.md&quot;
      - &quot;docs/plans/jarvis-mip-1.1/**&quot;
      - &quot;scripts/validate_jarvis_mip.py&quot;
      - &quot;tests/plan/**&quot;
      - &quot;.github/workflows/plan-validation.yml&quot;
  push:
    branches: [main, master]
    paths:
      - &quot;docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_1.1.md&quot;
      - &quot;docs/plans/jarvis-mip-1.1/**&quot;
      - &quot;scripts/validate_jarvis_mip.py&quot;
      - &quot;tests/plan/**&quot;
      - &quot;.github/workflows/plan-validation.yml&quot;

concurrency:
  group: jarvis-mip-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: Validate plan graph
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: &quot;3.12&quot;
      - name: Validate adoption candidate
        run: python scripts/validate_jarvis_mip.py --profile structural
      - name: Run validator regression tests
        run: python -m unittest discover -s tests/plan -p &quot;test_*.py&quot; -v
</code></pre>

</details>

<details>
<summary><code>docs/plans/JARVIS_MASTER_IMPLEMENTATION_PLAN_1.1.md</code></summary>

<pre><code># JARVIS Master Implementation Plan v1.1

**Plan ID:** `JARVIS-MIP-1.1`&lt;br&gt;
**Generated:** 2026-09-01&lt;br&gt;
**Repository baseline:** `master@1d8f93992205d1dcacc05e0466d89247f2c789d1`&lt;br&gt;
**Plan status:** **ADOPTED — PAG-0 OPEN**&lt;br&gt;
**Formal implementation status:** **NOT STARTED**&lt;br&gt;
**Planning Adoption Gate (PAG-0):** **OPEN**&lt;br&gt;
**Implementation Start Gate (ISG-0):** **CLOSED**

&gt; This normalized document is the adoption candidate for the next JARVIS
&gt; architecture. It does not authorize implementation, paper-order mutation,
&gt; canary activity, live trading, risk-limit changes, or strategy promotion.

The machine-readable work-package graph is
[`jarvis-mip-1.1/work_packages.json`](jarvis-mip-1.1/work_packages.json). Its
schema is [`jarvis-mip-1.1/plan.schema.json`](jarvis-mip-1.1/plan.schema.json), and its
structural validator is [`scripts/validate_jarvis_mip.py`](../../scripts/validate_jarvis_mip.py).
The graph, rather than a copied Markdown register, is the authoritative source
for work-package identity, dependencies, phase, safety class, Codex level, and
status.

Human adoption decisions are recorded in the
[`ADOPTION_REVIEW.md`](jarvis-mip-1.1/ADOPTION_REVIEW.md) packet and its
[`adoption_decisions.json`](jarvis-mip-1.1/adoption_decisions.json)
machine-readable register. Future WPs use
the [`work-package charter`](jarvis-mip-1.1/templates/work-package-charter.md)
and [`evidence manifest`](jarvis-mip-1.1/templates/evidence-manifest.example.json)
templates. These supporting artifacts remain pending and cannot open a gate by
their presence alone.

Session-level review artifacts are the normalized
[`conversation history`](jarvis-mip-1.1/SESSION_CONVERSATION_HISTORY.md), the
full [`implementation bundle`](jarvis-mip-1.1/IMPLEMENTATION_CODE_BUNDLE.md),
and the standalone [`HTML status report`](jarvis-mip-1.1/SESSION_REPORT.html).
They are generated/reference views and never override the source graph or
evidence records.

---

## 0. How to use this plan

```text
Mission
  └─ Program (A-P)
      └─ Epic / capability
          └─ Work Package (stable ID, for example E-04)
              └─ approved WP charter
                  └─ Task / PR
                      └─ Validation evidence
                          └─ Milestone / promotion gate
```

Work-package statuses are:

```text
NOT_STARTED → READY → IN_PROGRESS → BLOCKED → VALIDATION → DONE
```

`SUPERSEDED` is permitted only by an explicit plan change. A merged PR does
not close a work package. Acceptance criteria and the required evidence must
be observed and attached before a package can become `DONE`.

All 103 register entries begin as `NOT_STARTED`. The register is intentionally
not a substitute for a WP charter. A package may become `READY` only after its
charter satisfies the Definition of Ready in Section 14.

### 0.1 Verification ladder

| Rung | Evidence | Permitted claim |
|---|---|---|
| E0 | lint, typecheck, compile | builds, typechecks, or lints |
| E1 | deterministic unit/property tests | unit-tested |
| E2 | integration and replay through domain contracts | integration-tested |
| E3 | full local paper path observed | paper E2E observed |
| E4 | real IBKR paper round trip observed | broker-paper verified |
| E5 | explicitly authorized tiny live canary | live-canary observed |

Numeric correctness is a separate requirement at every rung. Never use
“verified,” “works,” “done,” or equivalent language above the evidence
actually observed.

### 0.2 Gate correction introduced in v1.1

Version 1.0 made Phase 0 evidence both a prerequisite for and a consequence of
opening ISG-0. Version 1.1 removes that circularity:

1. **Plan adoption** accepts the governing direction.
2. **PAG-0** authorizes planning, inventory, baseline, and ADR work only.
3. **ISG-0** may open only after the Phase 0 evidence and decisions are accepted.

PAG-0 does not authorize runtime business-logic changes. ISG-0 does not open
implicitly when PAG-0 opens or when a Phase 0 PR merges.

---

## 1. Executive product charter

### 1.1 Mission

Build JARVIS into a deterministic, event-driven, point-in-time-correct,
replayable, auditable systematic trading research and execution platform with
institutional-style validation discipline and a human operator control plane.

JARVIS exists to:

- create falsifiable hypotheses;
- reject weak or invalid strategies through honest data and trial accounting;
- convert only eligible strategy candidates into controlled trade intents;
- apply deterministic portfolio and risk policy;
- execute and reconcile through broker-authoritative state;
- measure execution and forward evidence;
- estimate milestone, drawdown, and ruin distributions without promising returns;
- degrade, halt, or retire strategies when evidence weakens.

### 1.2 Capital objective

`$3k → $10k → $25k → $100k → $300k` is a scenario family for Capital
Path research, not an account-state claim or promised schedule. Capital Path
must distinguish broker equity, allocatable equity, strategy risk equity, and
scenario starting equity.

### 1.3 Product principles

1. **Disprove first.** Research exists to falsify strategies.
2. **Point-in-time or invalid.** Decision inputs must have been knowable by the decision time.
3. **Broker authority.** A current, complete, account-verified broker snapshot is authoritative for executable positions, orders, fills, and account state.
4. **One mutation spine.** Strategy/Human → Intent → Portfolio reservation → Risk → OMS → Broker → Reconcile.
5. **Risk is non-LLM.** Sizing, limits, authorization, and halts are deterministic.
6. **AI is contextual.** AI cannot increase risk, enable live trading, or write broker orders.
7. **Zero is valid.** No component may coerce a zero-sized decision into a trade.
8. **No silent fallback.** Unavailable, stale, partial, or ambiguous state is labeled and blocks unsafe mutation.
9. **One product.** Do not maintain permanent v2/v3 operator control planes.
10. **Evidence before promotion.** Paper, canary, and live are evidence states, not convenience flags.
11. **Failures are assets.** Rejections and incidents remain in the ledger.
12. **Boring operations before capital.** Reconciliation, recovery, alerts, and provenance precede live capital.

### 1.4 Non-goals

- guaranteed daily returns;
- default 0DTE, naked options, or excessive leverage;
- reinforcement learning as the first model layer;
- LLM-owned risk, sizing, execution, or promotion;
- premature microservices;
- mandatory Postgres, QuestDB, or Redis migration without measured need;
- every broker or asset class before the core path is proven;
- tuning a strategy merely to make a gate pass;
- treating a chart appearance or ThinkScript port as causal production truth.

### 1.5 Initial scope constraint

Before ISG-0 opens, A-02/A-03 must select an explicit first executable scope.
The default adoption candidate is **one IBKR paper futures contract family
(MES) through one broker adapter**, with other assets quarantined behind legacy
compatibility boundaries. The equity relative-strength baseline is a separate
research benchmark and does not implicitly authorize equity or option orders.

---

## 2. Why Phase 0 exists

The baseline contains contradictory claims about runtime ports, Python paths,
datastores, risk defaults, human approval, eligibility, and execution
authority. It also contains overlapping broker gateways, executors, routers,
order managers, OMS implementations, and paper ledgers. A-01 must derive the
current state from code, configuration schemas, CI, generated inventories, and
observed runtime evidence rather than copying a static status table.

Known defects carried into the plan include:

- Initial Balance completed values appearing before range completion (#751);
- VWAP Globex/RTH session ambiguity (#752);
- non-equivalent legacy KAMA, Phase, and STC variants;
- delayed/future/session semantics in legacy studies;
- historical undercount risk in campaign trials;
- missing source-to-render numeric verification;
- overlapping execution authorities.

Pre-plan PRs #749, #754, and #756 and the RT-3 branch remain frozen for later
harvest. Their code and tests are inputs, not completed work packages.

---

## 3. Source-of-truth hierarchy

| Domain | Authority |
|---|---|
| Broker account, positions, open orders, fills | current, complete, account-verified broker API snapshot |
| JARVIS intents, decisions, risk checks, audit, operator actions | durable operational ledger; SQLite through paper |
| Runtime risk policy | approved versioned Risk Policy artifact and active hash |
| Trading eligibility | Judge lifecycle keyed by strategy version, instrument, timeframe, and evidence version |
| Research datasets | immutable manifest and content hashes |
| Research attempts | preregistered Trial Ledger with trial-family identity |
| Feature values | PIT Feature Store and feature/data/code versions |
| Strategy result | Judge Evidence Bundle |
| Instrument metadata | Instrument Master plus broker-qualified contract identity |
| UI | never authoritative; observes and mutates only through server contracts |
| Documentation | adopted MIP for future direction; generated/runtime artifacts for factual state |

A lower-authority layer may cache or display a higher-authority value only with
provenance and freshness. During migration, A-02 must name an interim authority
and conflict behavior for every domain; a future authority that does not yet
exist cannot silently become current truth.

---

## 4. Target architecture

JARVIS remains a single-repository modular monolith until measured constraints
justify a service boundary.

```text
Command Center
      │ authenticated HTTP commands; WS/SSE observations
      ▼
Engine API / composition root
      ├─ Research + Judge
      ├─ Strategies (candidate generation only)
      ├─ Portfolio + reservation
      ├─ deterministic Risk Policy
      └─ contextual Intelligence
                    │
Candidate/Human → TradeIntent → Eligibility → Reservation → RiskDecision
                    │
                    ▼
              Single OMS aggregate
                    │
                    ▼
               Broker Adapter
                    │
                    ▼
                   IBKR
                    │
                    ▼
              Reconciliation
                    │
                    ▼
        Portfolio corrections + Audit events
```

Target engine domains are `core`, `data`, `features`, `research`, `judge`,
`strategies`, `portfolio`, `risk`, `execution`, `brokers`, `capital_path`,
`intelligence`, `observability`, and `api`. `main.py` becomes composition and
bootstrap only. Migration is incremental and enforced by dependency tests; it
is not a mass file move.

### 4.1 Persistence

- **Operational:** SQLite WAL through paper while measured durability and concurrency remain adequate.
- **Research:** immutable Parquet datasets, content-addressed manifests, DuckDB analysis, and immutable evidence artifacts.
- **Optional:** Redis may coordinate realtime/cache activity but is never canonical. Postgres and QuestDB require a measured ADR.

Backups, restore drills, integrity checks, dataset correction/supersession, and
infrastructure migration thresholds are required contracts, not deferred
operational details.

### 4.2 Safety-critical migration pattern

S2/S3 replacements must use observe → shadow → compare → replay → isolated
paper → cutover → rollback-window → retire. Existing deterministic safety
checks remain veto-capable until the replacement has the required evidence.
Ambiguous divergences default to no new exposure.

---

## 5. Instrument, data, and time model

Instrument Master owns stable instrument-family metadata. Broker-qualified
contracts separately own broker IDs, local symbol, expiry, last trade date,
trading class, qualification time, and roll state. Every order and fill records
the qualified contract identity used at that time.

Observations preserve, where applicable:

```text
effective_at / event_at
published_at
received_at
available_at
computed_at
ingested_at
revision_id / supersedes_revision_id
known_at = max(available_at, computed_at)
decision_at
```

The decision invariant is `known_at &lt;= decision_at`, but underlying timestamps
and revisions remain available for bitemporal audit. Bar finalization, clock
skew, out-of-order arrival, vendor correction, DST, holiday, early-close,
futures trade-date, and RTH/ETH rules must be explicit.

Executable data additionally requires an approved provider class, verified
contract identity, acceptable freshness, valid session, passed quality gate,
and attached provenance. Display or research fallback is explicitly
non-executable.

---

## 6. Feature and strategy architecture

The Feature Registry separately records source integrity, causal integrity,
formula parity, statistical evidence, and deployment eligibility.

```text
ported != parity != causal != validated != deployable
```

Golden Vector parity requires actual source-platform output with source version
and tolerances. Backtest, replay, paper, and live use one causal feature graph;
display-only global values are isolated.

Every deterministic strategy declares its hypothesis, universe, timeframe,
information set, geometry, stop, target, expiry, dependencies, costs, and
version before evaluation. Strategies emit candidates or intents and cannot
allocate capital, decide final size, write Judge verdicts, or call brokers.

The v1.1 scope separates:

- a minimal MES strategy used to prove the execution platform; and
- a cross-sectional relative-strength equity research benchmark.

ML begins only after PIT candidate datasets and Judge V3 exist. The first
comparison is logistic regression versus a calibrated boosted-tree family.
ML may meta-label candidates but cannot invent risk geometry.

---

## 7. Judge V3

```text
RESEARCH_REJECT → RESEARCH_ONLY → PAPER_CANDIDATE → PAPER_VALIDATED
                → CANARY_CANDIDATE → LIVE_ELIGIBLE
                → DEGRADED / RETIRED
```

Lifecycle records are scoped to strategy version, instrument, timeframe, and
evidence version and include typed reason codes. Each campaign preregisters the
observation unit, dependence assumptions, label horizon, purge/embargo,
trial-family ID, search space, selection rule, primary metrics, costs, minimum
sample, tests, thresholds, and invalidation rules.

Judge may require source integrity, PIT integrity, parity, trial accounting,
purged validation, CPCV, DSR/PBO where statistically applicable, parameter
stability, costs, regimes, edge haircuts, ablations, placebos, locked holdout,
paper evidence, and canary evidence. The campaign protocol determines which
methods are appropriate; a checklist of fashionable metrics is not proof.

Research credentials cannot write verdicts. Holdout access is controlled and
logged. Evidence is immutable, expires or is invalidated on material
data/code/cost/trial changes, and is never silently overwritten.

---

## 8. Portfolio, risk, and execution

Portfolio derives broker-authoritative positions, cash, equity, realized and
unrealized P&amp;L, pending-order exposure, heat, concentration, correlation, and
attribution. It distinguishes broker equity, allocatable equity, strategy risk
equity, and scenario equity.

Risk is one versioned artifact with schema version, environment, scope,
effective time, expiry, approvals, units, dependencies, signature/hash, and
supersession. Environment may select an approved policy; it may not silently
override individual risk limits.

```text
account_risk = strategy_risk_equity * permitted_risk_fraction
risk_per_unit = abs(entry - stop) * instrument_point_value
qty = floor(account_risk / risk_per_unit)
```

`qty = 0` is valid throughout preview, reservation, decision, OMS, UI, and
audit. Concurrent intents use durable risk reservations with expiration and
release semantics so individually valid intents cannot jointly exceed limits.

The OMS owns order-lifecycle legality and durable transitions, not portfolio
truth or strategy eligibility. It supports idempotency, request fingerprints,
atomic claims, partial fills, cancel/replace, protective orders, restart
recovery, and an `AMBIGUOUS` state. Ambiguous broker outcomes are reconciled,
never automatically resubmitted.

Protection states distinguish pending, protected, degraded, unprotected, and
emergency-exit-pending conditions. Admission-time risk and continuous risk are
separate controls. The browser never holds broker credentials or calls IBKR.

---

## 9. Capital Path

Capital Path is separate from fixed-R sequence-risk Monte Carlo.

```text
Risk_t = f_t * Equity_t
Equity_{t+1} = Equity_t * (1 + f_t * R_t_net)
```

It reports competing target/ruin/censored outcomes, first-passage milestones,
conditional target time, drawdown, underwater duration, tail loss, and policy
sensitivity. Models include IID baseline, moving/stationary blocks,
day/regime-conditioned paths, parameter uncertainty, execution uncertainty,
and edge degradation.

Every result carries evidence lifecycle, sample size, effective sample size,
period, costs, haircut, model, disagreement, Monte Carlo error, parameter
uncertainty, data quality, and credibility. Capital Path is read-only decision
support and cannot write active policy.

---

## 10. AI authority

Runtime AI may normalize context, summarize, critique, classify catalysts,
explain anomalies, review trades, and propose research hypotheses. It may not
own final sizing, hard risk, eligibility, broker writes, live enablement,
policy changes, halt clearing, or strategy promotion. An AI outage must never
weaken Risk, Safety, OMS, or reconciliation.

M8 is not on the critical path to paper/canary promotion unless an adopted
strategy explicitly requires an AI-derived, PIT-governed feature.

---

## 11. Operator product

The product retains 14 canonical capabilities, which may be grouped into fewer
top-level navigation entries:

1. Command Center
2. Today / Market
3. Trade Workstation
4. Positions &amp; Orders
5. Risk Center
6. Strategy Monitor
7. Research Lab
8. Backtesting
9. Judge / Validation
10. Capital Path
11. Performance Analytics
12. Trade Journal
13. System Health
14. Configuration / Admin

Every critical value carries value, unit, provenance, timestamp, freshness,
quality, and applicable version. Explicit states include `LIVE/VERIFIED`,
`DELAYED`, `STALE`, `PARTIAL`, `CACHED/NON_EXECUTABLE`, `UNAVAILABLE`, and
`MISMATCH`. Unavailable is never rendered as zero.

HTTP owns authenticated mutations; WS/SSE owns observations. Streams have
authentication, sequence, resume, gap, duplicate, and reconnect semantics.
Lost observation connectivity cannot mutate state or confirm an earlier
command. Server and broker confirmation appropriate to the action are required
before success is displayed.

---

## 12. Environments and evidence boundaries

| Environment | Data | Mutation | Purpose | Maximum claim |
|---|---|---|---|---|
| RESEARCH | immutable historical | none | hypotheses/trials | E1/E2 |
| BACKTEST | historical manifests | simulator | deterministic evaluation | E2 |
| REPLAY | event replay | simulated OMS/broker | timing/PIT/incidents | E2 |
| LOCAL_PAPER | fixtures/live-like | local simulator | full local path | E3 |
| IBKR_PAPER | live data | IB paper account only | broker round trip | E4 |
| CANARY | live | isolated tiny live capital | controlled proof | E5 |
| LIVE | live | explicitly approved capital | controlled production | ongoing E5/SLO |

Credentials, ports, accounts, data, and mutation rights are isolated. Lower
environments cannot discover or activate higher-environment credentials.

---

## 13. Definition of Ready and Done

### 13.1 Required WP charter

Every package requires a versioned charter containing:

```text
plan/WP/program/epic/phase/milestone/status
safety class, decision class, owner, independent reviewers
objective and non-goals
dependencies and named input/output/domain contracts
authoritative data sources
acceptance criteria and required verification rung
numeric, PIT, security, and adversarial test plans as applicable
migration, compatibility, shadowing, rollback, and disable plan
observability and evidence-manifest path
residual risks and assumptions
```

A package is `READY` only when dependencies are satisfied or explicitly
mocked, no architecture decision is hidden inside implementation, and the
charter is approved at the required decision class.

### 13.2 Definition of Done

A package becomes `DONE` only when acceptance criteria pass, touched code is
lint/type clean, required deterministic and integration/replay tests pass,
the required runtime/broker rung is observed, financial values are
cross-checked, PIT/session rules are tested where relevant, safety regressions
pass for S2+, contracts/docs are updated, evidence is attached, residual risk
is recorded, and no duplicate authority was created.

---

## 14. Programs and delivery phases

| ID | Program |
|---|---|
| A | Platform &amp; Architecture |
| B | Data Engineering |
| C | Feature Engineering |
| D | Strategy Research |
| E | Judge &amp; Statistical Validation |
| F | Portfolio Construction |
| G | Capital Path |
| H | Risk Management |
| I | Execution / OMS |
| J | Broker Integration |
| K | Command Center / UX |
| L | AI Intelligence &amp; Agents |
| M | Observability &amp; Operations |
| N | Security &amp; Access |
| O | DevOps / CI-CD |
| P | Paper → Canary → Production |

| Phase | Objective | Gate |
|---:|---|---|
| 0 | adoption, truth baseline, architecture/IA/governance decisions | ISG-0 |
| 1 | core contracts, policy, security, observability, reproducible build | M1 |
| 2 | PIT data, feature foundation, trial ledger | M2 |
| 3 | deterministic research and Judge V3 | M3 |
| 4 | portfolio, risk, OMS, and broker consolidation | M4 |
| 5 | trustworthy read-only operator product | M5 |
| 6 | integrated IBKR paper control plane | M6 |
| 7 | Capital Path and robust risk frontier | M7 |
| 8 | optional contextual AI | M8 |
| 9 | extended integrated paper evidence | M9 |
| 10 | canary readiness without enablement | M10 |
| 11 | explicitly approved tiny live canary | M11 |
| 12 | controlled production and continuous research | M12 |

Calendar ranges are capacity scenarios only until A-01/O-01 are accepted.
Paper, canary, and live gates are evidence-driven and have no promised date.

---

## 15. Milestone behavior

Gates are default-deny. “Mostly passing” is not passing. Waivers require an
owner, documented risk acceptance, and expiry and cannot waive core capital or
safety invariants. Material data, code, cost, policy, or trial changes may
invalidate earlier evidence. Canary and live always require explicit human
authorization.

ISG-0 additionally requires:

- adopted plan and PAG-0 evidence;
- accepted runtime contradiction baseline;
- accepted source hierarchy and architecture ADRs;
- accepted IA and PR/evidence governance;
- frozen spike disposition;
- explicit first executable asset/broker scope;
- no unresolved contradiction capable of changing safety architecture.

---

## 16. Work-package register and governance

The authoritative register contains **34 explicit epics and 103 unique WPs**,
all initialized to `NOT_STARTED`. See the machine graph for exact epic
membership, dependencies, provisional objectives/acceptance policy, evidence
profiles, and classifications. The provisional text does not replace the
original WP intent or the approved charter required before `READY`. Evidence
profiles separate minimum ladder rung from
required reviews, runtime observations, numeric cross-checks, and PIT checks;
one scalar rung is not treated as a complete closure specification.

Safety classes:

- S0: docs/research/non-runtime;
- S1: read-only/runtime foundation;
- S2: paper mutation/execution infrastructure;
- S3: risk, eligibility, or safety critical;
- S4: canary/live capital or credentials.

Codex levels:

- A0: analyze, propose, or test; human owns mutation/decision;
- A1: bounded non-capital implementation and tests;
- A2: complex research/UI/paper code with independent review.

Safety class describes failure impact; decision class describes approval
authority; evidence rung describes observation depth. They must not be treated
as interchangeable. Codex cannot merge S3/S4, activate capital, increase risk,
or grant promotion.

---

## 17. Legacy disposition and spike policy

The current deterministic safety layer is retained behind a refactored
interface until replacement evidence exists. SQLite remains through paper.
Gate V2 metrics and verdicts remain historical evidence while Judge V3 becomes
future authority. Existing execution modules are reviewed and harvested into
one OMS/broker contract rather than preserved as parallel writers. Dashboard
routes consolidate into one product. Old canons and roadmaps remain historical
and become superseded for future direction only after adoption.

Pre-plan spike dispositions remain:

- #749: hold and harvest C/E/G concepts;
- #754: hold and harvest UI/read-model patterns;
- #756: hold and harvest H/I/J concepts;
- RT-3: freeze until M4/M6 dependencies permit the work.

No spike is merged as a bundle or credited as a completed WP.

---

## 18. Testing, operations, and security direction

Testing includes domain unit/property tests, integration/replay tests,
adversarial leakage and broker-failure tests, restart recovery, and numeric
source → engine → proxy → render verification. Screenshot-only validation is
insufficient.

Directional SLOs require no unexplained executable broker/local mismatch, no
unprotected open position, durable correlation/audit IDs for every S2+
mutation, freshness blocking for new exposure, restart recovery without
duplicates, and no weakening of deterministic controls during an LLM outage.

Threat modeling covers browser mutation, CSRF/SSRF/XSS, proxy path handling,
prompt injection, replay, duplicate orders, stolen tokens, stale quotes,
supply chain, and data poisoning. Audit events preserve actor, principal,
correlation/causation, environment, aggregate version, policy/code/data
versions, and tamper-evident hashes where required.

---

## 19. Research, paper, canary, and live governance

Every experiment starts with a PLAN event. Trial-family identity prevents
resetting multiplicity merely by renaming a campaign. Failures remain recorded.
Locked holdout access is controlled and logged.

An integrated paper campaign freezes strategy, policy, data, session, and
execution versions and records all eligible opportunity intervals, downtime,
missed signals, overrides, exclusions, fills, rejects, partials, protection,
costs, freshness, reconciliation, drift, and calibration. Material behavior
changes create a new version or campaign segment.

No date authorizes live trading. Canary requires M10 and explicit human
authorization of strategy version, instrument, maximum risk/size, Risk Policy,
broker environment, evidence objective, halt limits, and rollback. Scaling is
evidence-banded and separately approved for each policy version. No component
self-enables after a critical halt.

---

## 20. Change control

- wording or evidence-link correction: patch version;
- WP scope/dependency/acceptance change: minor version and changelog;
- source-of-truth, safety, domain, or live-promotion change: ADR and human approval;
- superseded WPs and failed evidence remain in history.

Every implementation PR must identify plan, program, WP, phase/milestone,
safety and decision classes, objective, dependencies, acceptance criteria,
verification rung, evidence, migration/rollback, and production/capital impact.

---

## 21. Adoption checklist

The plan may be structurally complete while adoption and implementation remain
closed.

- [x] Product mission and non-goals accepted
- [x] Source-of-truth hierarchy accepted
- [x] Modular-monolith target accepted
- [x] SQLite-through-paper and Parquet/DuckDB research decision accepted
- [x] Instrument Master and broker-contract identity decision accepted
- [x] Judge V3 authority and lifecycle accepted
- [x] Risk/AI boundary accepted
- [x] Single OMS/broker-adapter consolidation accepted
- [x] Fourteen operator capabilities accepted
- [x] Phase and milestone order accepted
- [x] S0-S4, decision-class, and E0-E5 governance accepted
- [x] Existing spike treatment accepted
- [x] Human canary/live gate accepted
- [x] Initial executable asset and broker scope accepted
- [x] PAG-0 explicitly opened
- [ ] Phase 0 evidence accepted
- [ ] ISG-0 explicitly opened

Until the final item is checked and reflected in a reviewed graph update,
formal implementation remains **NOT STARTED**.

---

## 22. First queue after PAG-0

This queue is planning and truth work, not strategy tuning or trading buttons:

1. A-01 Runtime truth baseline and contradiction register
2. O-01 CI baseline and debt classification
3. A-02 Source-of-truth hierarchy ADR
4. A-03 Target architecture ADR
5. A-06 Legacy deprecation registry
6. K-01 Operator IA and route consolidation plan
7. O-05 PR/Codex/evidence governance

After those artifacts are accepted, a human may open ISG-0. The preferred first
implementation slice is a read-only MES/IBKR paper snapshot with Instrument
Master identity, broker freshness/completeness, reconciliation, canonical
events, an API read model, one UI panel, and numeric/provenance E2E evidence.
It explicitly excludes order placement, strategy promotion, AI, Capital Path,
multi-asset support, and live credentials.

---

## 23. Internal structural validation

Run:

```bash
python scripts/validate_jarvis_mip.py --profile adoption-candidate
python scripts/validate_jarvis_mip.py --profile structural
```

The adoption-candidate profile additionally requires the plan to remain
unadopted with PAG-0 and ISG-0 closed. The structural profile supports governed
future states but requires every open or passed gate to reference an evidence
manifest. Both profiles check plan identity, 34 epics, 103 unique WPs, programs
A-P, phases 0-12, PAG-0/ISG-0/M1-M12 definitions, dependency existence,
dependency cycles, forward-phase dependencies, status/safety/Codex/evidence
enums, phase/milestone consistency, charter/evidence-manifest requirements, and
exact bidirectional epic membership. Regression tests exercise invalid graph
mutations, and a path-filtered CI workflow runs both the adoption profile and
the tests for planning-artifact changes.

A passing validator means the graph is structurally coherent. It does not mean
the plan is adopted, a WP is Ready, behavior works, or any E3-E5 evidence was
observed.

---

## Appendix A — Planning sources

The planning inventory includes root and scoped agent/project memory,
`README.md`, `docs/CURRENT_STATE.md`, the former Unified Canon and integrated
roadmap, strategic capability/risk/execution documents, engine configuration,
database/data/portfolio/backtest/execution/risk code, dashboard route
manifests, CI workflows, spikes #749/#754/#756, RT-3, and issues #751/#752.
A-01 remains the formal machine-derived baseline and does not claim every file
has already been line-reviewed.

## Appendix B — Historical versus future authority

After adoption, the old Unified Canon, April integrated roadmap, strategic
execution spine, static eligibility tables, stale runtime examples, and
pre-plan “implementation complete” artifacts remain historical evidence but
do not govern new work. They are not deleted or retroactively invalidated.

## Appendix C — v1.1 changelog

- normalized and deduplicated the v1.0 planning input;
- retained all 16 programs and 103 stable WPs in a machine-readable graph;
- represented all 34 Program-to-Epic-to-WP relationships explicitly;
- added gate objects and reviewed evidence profiles instead of a scalar-only rung;
- added a JSON Schema and lifecycle-aware structural/adoption validation profiles;
- added deterministic negative regression tests and path-filtered CI validation;
- added an adoption review packet plus WP charter and evidence-manifest templates;
- split plan adoption/PAG-0 from ISG-0 to remove circular gating;
- made per-WP charters mandatory before `READY`;
- clarified interim authorities and safety-critical shadow migration;
- narrowed the default first executable scope to MES/IBKR paper;
- separated the equity RS research baseline from execution proof;
- added broker-contract identity, bitemporal revisions, risk reservations,
  continuous risk, evidence invalidation, and paper-mode distinctions;
- kept every adoption checkbox unchecked and both PAG-0 and ISG-0 closed.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/ADOPTION_REVIEW.md</code></summary>

<pre><code># JARVIS-MIP-1.1 Adoption Review Packet

**Decision state:** ACCEPTED&lt;br&gt;
**PAG-0:** OPEN&lt;br&gt;
**ISG-0:** CLOSED

This packet supports human review of the adoption candidate. Completing this
document does not change a gate by itself. Any adopted decision must also be
recorded in a reviewed update to `work_packages.json` with an evidence manifest.
The synchronized machine-readable decision register is
[`adoption_decisions.json`](adoption_decisions.json); its schema is
[`adoption-decisions.schema.json`](adoption-decisions.schema.json).

## Review protocol

For each decision, choose exactly one disposition:

- **ACCEPT** — adopt as written;
- **AMEND** — identify the required plan change;
- **REJECT** — identify why the plan cannot proceed.

Record the accountable human, UTC timestamp, plan commit, and rationale. Do not
use a blanket approval for all decisions. Do not open PAG-0 until every required
adoption decision is ACCEPT or an approved amendment has been incorporated.

## Decision record

| ID | Decision | Disposition | Accountable human | Evidence/rationale |
|---|---|---|---|---|
| AD-01 | Product mission and non-goals | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-02 | Source-of-truth hierarchy | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-03 | Modular-monolith target | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-04 | SQLite through paper; Parquet/DuckDB for research | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-05 | Instrument Master and broker-contract identity | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-06 | Judge V3 authority and lifecycle | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-07 | Deterministic Risk / contextual AI boundary | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-08 | Single OMS and broker-adapter consolidation | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-09 | Fourteen operator capabilities and consolidated IA | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-10 | Phase and milestone order | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-11 | Safety, decision, Codex, and evidence classifications | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-12 | Treatment of PRs #749/#754/#756 and RT-3 | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-13 | Human-only canary/live authorization | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-14 | MES through IBKR paper as the first executable scope | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |

## Required questions

### Product and capital

1. Is the mission a research and execution platform rather than an alert bot or
   LLM trader?
2. Are Capital Path milestones scenarios rather than return promises?
3. Is live activity prohibited until the human-controlled M10/M11 process?

### Authority

1. Is a current, complete, account-verified broker snapshot authoritative for
   executable account, position, order, and fill state?
2. Is SQLite the operational intent/audit mirror through paper rather than a
   replacement for broker truth?
3. Is eligibility scoped to strategy version, instrument, timeframe, and
   evidence version?
4. May environment configuration select an approved Risk Policy without
   overriding individual limits?

### Architecture and scope

1. Is the modular monolith the default until measured requirements justify a
   service boundary?
2. Is the first executable slice limited to MES and IBKR paper?
3. Are equity relative-strength research and options execution explicitly
   outside that first execution slice?
4. Must safety-critical migrations use shadow comparison and rollback windows?

### Governance

1. Are all 103 WPs `NOT_STARTED` until their own charters pass DoR?
2. Does a merged PR remain insufficient to mark a WP `DONE`?
3. Are S3/S4 merge, capital, promotion, and risk-increase decisions human-owned?
4. Are failed trials and superseded evidence retained?

## PAG-0 opening record

Leave this section untouched until AD-01 through AD-14 are resolved.

The complete Phase 0 planning set has draft—not approved—charters:

| WP | Draft charter |
|---|---|
| A-01 | [`charters/A-01.md`](charters/A-01.md) |
| A-02 | [`charters/A-02.md`](charters/A-02.md) |
| A-03 | [`charters/A-03.md`](charters/A-03.md) |
| A-06 | [`charters/A-06.md`](charters/A-06.md) |
| K-01 | [`charters/K-01.md`](charters/K-01.md) |
| O-01 | [`charters/O-01.md`](charters/O-01.md) |
| O-05 | [`charters/O-05.md`](charters/O-05.md) |

Their presence establishes review readiness only; it does not satisfy their
dependencies, approve their contents, make them `READY`, or authorize execution.

```text
Decision: OPEN
Authorized by: repository owner via user instruction
Authorized at (UTC): 2026-09-12T06:54:00Z
Plan commit: b2455710bf0abd83db0c933e1b5e082d07bed4e0
Adoption evidence manifest: docs/plans/jarvis-mip-1.1/evidence/PAG-0-adoption.json
Scope: A-01, O-01, A-02, A-03, A-06, K-01, O-05 planning work only
Explicit exclusions: runtime business logic, order mutation, risk changes,
strategy promotion, canary/live credentials, and ISG-0 opening
```

## ISG-0 opening record

ISG-0 cannot be considered until PAG-0 is authorized and its Phase 0 evidence
has been accepted.

```text
Decision: NOT ELIGIBLE
Authorized by: —
Authorized at (UTC): —
Phase 0 evidence manifest: —
First implementation WP charter: —
```
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/adoption-decisions.schema.json</code></summary>

<pre><code>{
  &quot;$schema&quot;: &quot;https://json-schema.org/draft/2020-12/schema&quot;,
  &quot;title&quot;: &quot;JARVIS MIP Adoption Decisions&quot;,
  &quot;type&quot;: &quot;object&quot;,
  &quot;additionalProperties&quot;: false,
  &quot;required&quot;: [&quot;schema_version&quot;, &quot;plan_id&quot;, &quot;reviewed_plan_commit&quot;, &quot;decision_state&quot;, &quot;pag_0&quot;, &quot;isg_0&quot;, &quot;decisions&quot;],
  &quot;properties&quot;: {
    &quot;schema_version&quot;: {&quot;const&quot;: &quot;1.0&quot;},
    &quot;plan_id&quot;: {&quot;const&quot;: &quot;JARVIS-MIP-1.1&quot;},
    &quot;reviewed_plan_commit&quot;: {&quot;type&quot;: [&quot;string&quot;, &quot;null&quot;], &quot;pattern&quot;: &quot;^[0-9a-f]{40}$&quot;},
    &quot;decision_state&quot;: {&quot;enum&quot;: [&quot;PENDING&quot;, &quot;ACCEPTED&quot;, &quot;REJECTED&quot;]},
    &quot;pag_0&quot;: {&quot;enum&quot;: [&quot;CLOSED&quot;, &quot;OPEN&quot;]},
    &quot;isg_0&quot;: {&quot;enum&quot;: [&quot;CLOSED&quot;, &quot;OPEN&quot;]},
    &quot;decisions&quot;: {
      &quot;type&quot;: &quot;array&quot;, &quot;minItems&quot;: 14, &quot;maxItems&quot;: 14,
      &quot;items&quot;: {
        &quot;type&quot;: &quot;object&quot;, &quot;additionalProperties&quot;: false,
        &quot;required&quot;: [&quot;id&quot;, &quot;title&quot;, &quot;disposition&quot;, &quot;accountable_human&quot;, &quot;decided_at&quot;, &quot;rationale&quot;],
        &quot;properties&quot;: {
          &quot;id&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^AD-(0[1-9]|1[0-4])$&quot;},
          &quot;title&quot;: {&quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1},
          &quot;disposition&quot;: {&quot;enum&quot;: [&quot;PENDING&quot;, &quot;ACCEPT&quot;, &quot;AMEND&quot;, &quot;REJECT&quot;]},
          &quot;accountable_human&quot;: {&quot;type&quot;: [&quot;string&quot;, &quot;null&quot;]},
          &quot;decided_at&quot;: {&quot;type&quot;: [&quot;string&quot;, &quot;null&quot;], &quot;format&quot;: &quot;date-time&quot;},
          &quot;rationale&quot;: {&quot;type&quot;: [&quot;string&quot;, &quot;null&quot;]}
        }
      }
    }
  }
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/adoption_decisions.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.0&quot;,
  &quot;plan_id&quot;: &quot;JARVIS-MIP-1.1&quot;,
  &quot;reviewed_plan_commit&quot;: &quot;b2455710bf0abd83db0c933e1b5e082d07bed4e0&quot;,
  &quot;decision_state&quot;: &quot;ACCEPTED&quot;,
  &quot;pag_0&quot;: &quot;OPEN&quot;,
  &quot;isg_0&quot;: &quot;CLOSED&quot;,
  &quot;decisions&quot;: [
    {
      &quot;id&quot;: &quot;AD-01&quot;,
      &quot;title&quot;: &quot;Product mission and non-goals&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-02&quot;,
      &quot;title&quot;: &quot;Source-of-truth hierarchy&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-03&quot;,
      &quot;title&quot;: &quot;Modular-monolith target&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-04&quot;,
      &quot;title&quot;: &quot;SQLite through paper and Parquet/DuckDB research&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-05&quot;,
      &quot;title&quot;: &quot;Instrument Master and broker-contract identity&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-06&quot;,
      &quot;title&quot;: &quot;Judge V3 authority and lifecycle&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-07&quot;,
      &quot;title&quot;: &quot;Deterministic Risk and contextual AI boundary&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-08&quot;,
      &quot;title&quot;: &quot;Single OMS and broker-adapter consolidation&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-09&quot;,
      &quot;title&quot;: &quot;Fourteen operator capabilities and consolidated IA&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-10&quot;,
      &quot;title&quot;: &quot;Phase and milestone order&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-11&quot;,
      &quot;title&quot;: &quot;Safety, decision, Codex, and evidence classifications&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-12&quot;,
      &quot;title&quot;: &quot;Pre-plan spike treatment&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-13&quot;,
      &quot;title&quot;: &quot;Human-only canary/live authorization&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    },
    {
      &quot;id&quot;: &quot;AD-14&quot;,
      &quot;title&quot;: &quot;MES through IBKR paper as first executable scope&quot;,
      &quot;disposition&quot;: &quot;ACCEPT&quot;,
      &quot;accountable_human&quot;: &quot;repository_owner_via_user_instruction&quot;,
      &quot;decided_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
      &quot;rationale&quot;: &quot;Accepted by the repository owner through the explicit 2026-09-12 instruction to proceed after receiving the required adoption authorization text.&quot;
    }
  ]
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/A-01.md</code></summary>

<pre><code># A-01 — Runtime Truth Baseline and Contradiction Register

**Status:** APPROVED FOR PAG-0 — IN PROGRESS&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Gate:** ISG-0

## Objective

Produce a machine-derived, evidence-linked inventory of current runtime authorities and contradictions without changing runtime behavior.

## Non-goals

- Resolve contradictions in production code.
- Change eligibility, risk, execution, broker, or live settings.
- Declare target systems authoritative before migration.

## Scope and outputs

1. Inventory configuration sources, routers, dashboard routes, scheduled jobs, order writers, broker readers, ledger writers, eligibility sources, risk limits, instrument maps, databases, and CI checks.
2. Create `evidence/A-01/runtime-inventory.json` with commands, commit, counts, paths, and hashes.
3. Create `evidence/A-01/contradictions.md` with ID, competing claims, observed evidence, safety impact, interim authority, target authority, owner WP, and status.
4. Create `evidence/A-01/mutation-spine.md` tracing every paper/live-capable mutation entry point.

## Acceptance criteria

- [ ] Inventory is generated at the recorded commit and reproducible.
- [ ] Every discovered mutation path has an owner and authority classification.
- [ ] Known plan contradictions are represented; omissions are documented.
- [ ] No runtime, environment, eligibility, risk, or broker state is modified.
- [ ] Independent review confirms evidence claims do not exceed observation.

## Verification

Minimum E0 for inventory generation plus human/static evidence review. Runtime claims require separately labeled observation and must not be inferred from code.

## Rollback

Documentation/evidence only. Revert the commit; preserve superseded evidence in history.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/A-02.md</code></summary>

<pre><code># A-02 — Source-of-Truth Hierarchy and Canon ADR

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Dependencies:** A-01&lt;br&gt;
**Gate:** ISG-0

## Objective

Adopt one conflict-resolving authority for every critical domain, including an explicit interim authority while target systems are not yet implemented.

## Non-goals

- Implement Judge, Risk Policy, OMS, or broker adapters.
- Treat a proposed target as current runtime truth.
- Delete historical evidence or operational runbooks.

## Required decision table

For broker state, ledger events, risk policy, eligibility, datasets, trials, features, strategy evidence, instruments, UI, and documentation, record current authority, interim authority, target authority, freshness/completeness conditions, conflict behavior, migration WP, and retirement criterion.

## Acceptance criteria

- [ ] Every A-01 authority conflict has a default-deny resolution or named blocking owner.
- [ ] Broker authority requires verified account, completeness, and freshness—not source name alone.
- [ ] Environment values cannot silently override an approved Risk Policy.
- [ ] UI and prose are never executable authorities.
- [ ] ADR is approved by the accountable human before downstream contracts rely on it.

## Verification and rollback

E0 document/link validation plus independent comparison to A-01 evidence. Supersede the ADR with a versioned replacement; never rewrite historical decisions.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/A-03.md</code></summary>

<pre><code># A-03 — Target Bounded-Context Architecture ADR

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Dependencies:** A-01, A-02&lt;br&gt;
**Gate:** ISG-0

## Objective

Define enforceable modular-monolith boundaries, dependency direction, public contracts, and forbidden shortcuts before runtime refactoring begins.

## Non-goals

- Mass-move files or split services.
- Select implementation details hidden inside later WPs.
- Preserve duplicate authorities for compatibility.

## Required decisions

Define boundaries for core, data, features, research, Judge, strategies, portfolio, risk, execution, brokers, Capital Path, intelligence, observability, and API. Specify ownership of transactions, durable events, composition, and dependency enforcement.

## Acceptance criteria

- [ ] Strategies cannot import broker implementations or allocate capital.
- [ ] Intelligence cannot import risk/OMS broker-write capabilities.
- [ ] API routers depend on application contracts rather than direct DB/broker mutations.
- [ ] OMS, portfolio, risk, and reconciliation responsibilities are non-overlapping.
- [ ] Forbidden imports are suitable for automated enforcement.
- [ ] Initial executable boundary is MES through IBKR paper unless AD-14 amends it.

## Verification and rollback

E0 architecture review against A-01 mutation paths and A-02 authorities. Changes require a superseding ADR and migration impact analysis.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/A-06.md</code></summary>

<pre><code># A-06 — Legacy Deprecation Registry

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Dependencies:** A-01, A-03&lt;br&gt;
**Gate:** ISG-0

## Objective

Classify every high-risk legacy module, route, document, store, and technical spike with an evidence-gated migration and retirement disposition.

## Required dispositions

`KEEP`, `WRAP`, `SHADOW`, `HARVEST`, `REPLACE`, `RETIRE`, or `TEST_DOUBLE_ONLY`.

Each entry records current writers/readers, authority, replacement WP, compatibility boundary, shadow comparison, cutover evidence, rollback window, and retirement gate.

## Acceptance criteria

- [ ] All A-01 mutation paths and competing authorities appear in the registry.
- [ ] No execution path is retained merely because it is currently imported.
- [ ] Deterministic safety remains veto-capable until replacement evidence is accepted.
- [ ] PRs #749/#754/#756 and RT-3 remain frozen and mapped to harvest WPs.
- [ ] Retirement never deletes failed trials, incidents, or audit evidence.

## Verification and rollback

E0 inventory reconciliation against A-01. Registry changes preserve history and require explicit supersession rather than row deletion.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/K-01.md</code></summary>

<pre><code># K-01 — Operator Product IA and Wireframe Approval

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Dependencies:** A-03&lt;br&gt;
**Gate:** ISG-0

## Objective

Map every current dashboard route to one canonical operator information architecture and approve non-executable wireframes before control surfaces are built.

## Non-goals

- Add broker mutations or client-authoritative financial math.
- Create a permanent v2/v3 route tree.
- Represent unavailable data as zero.

## Required outputs

A machine-derived route inventory and mapping with `CANONICAL`, `CHILD_VIEW`, `REDIRECT`, `COMPATIBILITY`, `EXTERNAL_DEPENDENCY`, or `RETIRE` disposition; navigation model; critical-value provenance contract; degraded-state wireframes; mutation-class inventory.

## Acceptance criteria

- [ ] All current routes are mapped exactly once and route-manifest parity is retained.
- [ ] Fourteen capabilities fit a coherent navigation model without duplicate control planes.
- [ ] LIVE/DELAYED/STALE/PARTIAL/CACHED/UNAVAILABLE/MISMATCH states are visible.
- [ ] Every critical number reserves value, unit, source, timestamp, freshness, and version.
- [ ] Wireframes contain no executable action before its milestone dependency.

## Verification and rollback

E0 route-manifest and link checks plus human wireframe approval. Existing routes remain available until redirect and numeric-equivalence evidence is accepted.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/O-01.md</code></summary>

<pre><code># O-01 — CI Baseline and Debt Classification

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S0 / D0 / A1&lt;br&gt;
**Dependencies:** A-01&lt;br&gt;
**Gate:** ISG-0

## Objective

Record the canonical checks and classify their baseline results so new work cannot hide or increase existing debt.

## Non-goals

- Fix all baseline failures.
- weaken, skip, or relabel a failing safety check as passing.
- Treat compilation as runtime evidence.

## Outputs

1. `evidence/O-01/check-inventory.json`: command, domain, environment, duration, dependencies, evidence rung, blocking status, owner, and last result.
2. `evidence/O-01/debt-baseline.json`: stable finding ID, first observation, affected path, severity, disposition, owner WP, and expiry where waived.
3. A touched-domain rule that rejects newly introduced debt without suppressing existing findings.

## Acceptance criteria

- [ ] Every required workflow/check is inventoried without executing unsafe broker/live actions.
- [ ] Results distinguish PASS, FAIL, SKIP, FLAKY, and ENVIRONMENT_BLOCKED.
- [ ] Baseline debt is machine-readable and cannot excuse new findings.
- [ ] Commands and commit are reproducible; secrets are excluded.
- [ ] E0 results are not described as runtime verification.

## Verification

E0: validate schemas, rerun safe canonical checks, and compare deterministic output. Broker-dependent checks are classified, not fabricated.

## Rollback

Revert enforcement if it incorrectly blocks unrelated changes; retain the baseline artifact and incident record.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/charters/O-05.md</code></summary>

<pre><code># O-05 — Branch, PR, Codex, and Evidence Governance

**Status:** DRAFT — NOT READY; PAG-0 CLOSED&lt;br&gt;
**Safety / Decision / Codex:** S3 / D3 / A0&lt;br&gt;
**Dependencies:** A-02, O-01&lt;br&gt;
**Gate:** ISG-0

## Objective

Define and enforce the approval, evidence, and automation boundaries for every implementation PR without granting an AI or CI system capital authority.

## Non-goals

- Auto-merge S3/S4 work.
- infer human approval from CI, comments, or prior approvals.
- permit live flags, credentials, risk increases, or strategy promotion.

## Required controls

Validate plan/WP IDs, READY status, dependencies, safety/decision/Codex classes, acceptance criteria, evidence profile, migration/rollback, capital impact, required reviewers, and evidence manifests. Define expiring exception records.

## Acceptance criteria

- [ ] S3/S4 changes require the designated human and independent review.
- [ ] S4 capital or credential actions cannot be performed by Codex or CI credentials.
- [ ] A passing build cannot satisfy runtime evidence.
- [ ] Missing/invalid WP or evidence metadata fails closed.
- [ ] Branch protection and CODEOWNERS gaps are reported rather than assumed configured.
- [ ] Rollback of governance cannot silently authorize a prohibited mutation.

## Verification and rollback

Minimum E2 for policy tests and representative PR-metadata fixtures before enforcement. Start in report-only mode, compare results, then gate; emergency disable must alert and leave S3/S4 default-deny controls intact.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/A-01/contradictions.md</code></summary>

<pre><code># A-01 Contradiction Register (Static Baseline)

**Status:** IN PROGRESS — static evidence only; runtime observations outstanding.

| ID | Domain | Competing claims | Interim safe interpretation | Owner WP |
|---|---|---|---|---|
| CTR-001 | Eligibility | Root/engine/static tables and live eligibility endpoints have historically disagreed. | Static prose cannot authorize a trade; default deny on ambiguity. | A-02, D-08 |
| CTR-002 | Risk policy | Code defaults, comments, and environment values differ. | Observe active runtime before making numeric claims; do not change limits. | A-02, H-01 |
| CTR-003 | Datastore | Older architecture names PostgreSQL/Redis/QuestDB while the operational manager uses SQLite WAL. | SQLite is the observed code-path baseline; runtime use remains unobserved. | A-02, A-06 |
| CTR-004 | Execution | Gateway, connector, executor, order manager, router, OMS, and reconcilers overlap. | No module is declared the sole writer until runtime tracing and J-02 ADR. | A-03, A-06, J-02 |
| CTR-005 | Paper mode | Internal simulation, ledger-only paper, and IBKR paper are described under one label. | Preserve LOCAL_PAPER and IBKR_PAPER as separate evidence environments. | A-02, N-02 |
| CTR-006 | Runtime docs | File sizes, router counts, Python paths, and service claims are stale across docs. | Machine-generated inventory and observed health outrank copied counts. | A-01, O-03, M-03 |
| CTR-007 | Dashboard truth | UI routes and numbers can outlive their sources or external master-api availability. | UI is presentation only; unavailable is not zero. | K-01, K-12 |

This register does not resolve runtime truth. Resolution requires evidence named by the owning WP; absence of a contradiction here is not proof of consistency.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/A-01/mutation-spine.md</code></summary>

<pre><code># A-01 Mutation-Spine Static Inventory

**Status:** IN PROGRESS. These are candidate mutation surfaces discovered statically, not proof they are reachable or active.

## Execution candidates

- `engine/execution/ib_gateway.py`
- `engine/execution/ib_gateway_connector.py`
- `engine/execution/ib_order_manager.py`
- `engine/execution/ibkr_executor.py`
- `engine/execution/oms_v2.py`
- `engine/execution/order_router.py`
- `engine/execution/submission_dedup.py`
- broker and position reconcilers under `engine/execution/`

## Required follow-up before A-01 validation

1. Enumerate every API and scheduler caller of place/cancel/replace/flatten operations.
2. Identify composition-time implementation selection and environment guards.
3. Observe process/runtime configuration without exposing secrets.
4. Classify each path as writer, read-only adapter, simulator, test double, or dead code.
5. Confirm local/broker ambiguity and retry behavior.

No listed path is authorized, deprecated, or safe merely because it appears here.
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/A-01/runtime-inventory.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.0&quot;,
  &quot;work_package&quot;: &quot;A-01&quot;,
  &quot;status&quot;: &quot;IN_PROGRESS&quot;,
  &quot;commit&quot;: &quot;b2455710bf0abd83db0c933e1b5e082d07bed4e0&quot;,
  &quot;generated_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
  &quot;method&quot;: &quot;static machine-derived inventory; no runtime/broker observation&quot;,
  &quot;counts&quot;: {
    &quot;engine_python_files&quot;: 1726,
    &quot;engine_router_files&quot;: 84,
    &quot;execution_python_files&quot;: 17,
    &quot;risk_python_files&quot;: 23,
    &quot;dashboard_pages&quot;: 54,
    &quot;github_workflows&quot;: 7
  },
  &quot;execution_modules&quot;: [
    &quot;engine/execution/__init__.py&quot;,
    &quot;engine/execution/ib_gateway.py&quot;,
    &quot;engine/execution/ib_gateway_connector.py&quot;,
    &quot;engine/execution/ib_order_manager.py&quot;,
    &quot;engine/execution/ibkr_executor.py&quot;,
    &quot;engine/execution/ibkr_reconciler.py&quot;,
    &quot;engine/execution/oms_v2.py&quot;,
    &quot;engine/execution/order_gateway_factory.py&quot;,
    &quot;engine/execution/order_router.py&quot;,
    &quot;engine/execution/paper_trade_logger.py&quot;,
    &quot;engine/execution/polymarket_connector.py&quot;,
    &quot;engine/execution/portfolio_allocator.py&quot;,
    &quot;engine/execution/position_reconciler.py&quot;,
    &quot;engine/execution/robinhood_connector.py&quot;,
    &quot;engine/execution/schwab_connector.py&quot;,
    &quot;engine/execution/submission_dedup.py&quot;,
    &quot;engine/execution/test_submission_dedup.py&quot;
  ],
  &quot;workflow_files&quot;: [
    &quot;.github/workflows/ci.yml&quot;,
    &quot;.github/workflows/claude-pr-review.yml&quot;,
    &quot;.github/workflows/deploy-check.yml&quot;,
    &quot;.github/workflows/es-research-platform.yml&quot;,
    &quot;.github/workflows/p0-verify.yml&quot;,
    &quot;.github/workflows/plan-validation.yml&quot;,
    &quot;.github/workflows/safety-invariant-check.yml&quot;
  ],
  &quot;authoritative_limitations&quot;: [
    &quot;Does not prove which paths are active at runtime.&quot;,
    &quot;Does not observe IBKR or current process state.&quot;,
    &quot;Dynamic imports and external services require follow-up observation.&quot;
  ]
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/O-01/check-inventory.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.0&quot;,
  &quot;work_package&quot;: &quot;O-01&quot;,
  &quot;status&quot;: &quot;IN_PROGRESS&quot;,
  &quot;checks&quot;: [
    {&quot;id&quot;:&quot;PLAN-STRUCTURE&quot;,&quot;command&quot;:&quot;python scripts/validate_jarvis_mip.py --profile structural&quot;,&quot;rung&quot;:&quot;E0&quot;,&quot;classification&quot;:&quot;REQUIRED&quot;,&quot;result&quot;:&quot;PASS&quot;},
    {&quot;id&quot;:&quot;PLAN-UNIT&quot;,&quot;command&quot;:&quot;python -m unittest discover -s tests/plan -p &#x27;test_*.py&#x27; -v&quot;,&quot;rung&quot;:&quot;E1&quot;,&quot;classification&quot;:&quot;REQUIRED&quot;,&quot;result&quot;:&quot;PASS&quot;},
    {&quot;id&quot;:&quot;ENGINE-LINT&quot;,&quot;command&quot;:&quot;cd engine &amp;&amp; .venv/bin/ruff check . --config ruff.toml&quot;,&quot;rung&quot;:&quot;E0&quot;,&quot;classification&quot;:&quot;REQUIRED_NOT_RUN_THIS_EVIDENCE&quot;,&quot;result&quot;:&quot;UNOBSERVED&quot;},
    {&quot;id&quot;:&quot;ENGINE-TEST&quot;,&quot;command&quot;:&quot;cd engine &amp;&amp; .venv/bin/python -m pytest tests/ -m &#x27;not slow&#x27;&quot;,&quot;rung&quot;:&quot;E1_E2_MIXED&quot;,&quot;classification&quot;:&quot;REQUIRED_NOT_RUN_THIS_EVIDENCE&quot;,&quot;result&quot;:&quot;UNOBSERVED&quot;},
    {&quot;id&quot;:&quot;DASHBOARD-TYPE&quot;,&quot;command&quot;:&quot;cd dashboard &amp;&amp; ./node_modules/.bin/tsc --noEmit&quot;,&quot;rung&quot;:&quot;E0&quot;,&quot;classification&quot;:&quot;REQUIRED_NOT_RUN_THIS_EVIDENCE&quot;,&quot;result&quot;:&quot;UNOBSERVED&quot;},
    {&quot;id&quot;:&quot;DASHBOARD-BUILD&quot;,&quot;command&quot;:&quot;cd dashboard &amp;&amp; pnpm run build&quot;,&quot;rung&quot;:&quot;E0&quot;,&quot;classification&quot;:&quot;REQUIRED_NOT_RUN_THIS_EVIDENCE&quot;,&quot;result&quot;:&quot;UNOBSERVED&quot;}
  ],
  &quot;limitations&quot;:[&quot;PASS entries cover planning artifacts only.&quot;,&quot;UNOBSERVED is not PASS, FAIL, or SKIP.&quot;]
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/O-01/debt-baseline.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;:&quot;1.0&quot;,
  &quot;work_package&quot;:&quot;O-01&quot;,
  &quot;status&quot;:&quot;IN_PROGRESS&quot;,
  &quot;findings&quot;:[
    {&quot;id&quot;:&quot;DEBT-PLAN-001&quot;,&quot;severity&quot;:&quot;medium&quot;,&quot;finding&quot;:&quot;No JSON Schema execution is wired into CI; semantic validator duplicates only part of the schema.&quot;,&quot;owner_wp&quot;:&quot;O-01&quot;,&quot;disposition&quot;:&quot;OPEN&quot;},
    {&quot;id&quot;:&quot;DEBT-PLAN-002&quot;,&quot;severity&quot;:&quot;high&quot;,&quot;finding&quot;:&quot;Phase 0 runtime and full CI evidence remain unobserved.&quot;,&quot;owner_wp&quot;:&quot;A-01/O-01&quot;,&quot;disposition&quot;:&quot;OPEN&quot;}
  ]
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/evidence/PAG-0-adoption.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.0&quot;,
  &quot;plan_id&quot;: &quot;JARVIS-MIP-1.1&quot;,
  &quot;gate_id&quot;: &quot;PAG-0&quot;,
  &quot;decision&quot;: &quot;OPEN&quot;,
  &quot;authorized_by&quot;: &quot;repository_owner_via_user_instruction&quot;,
  &quot;authorized_at&quot;: &quot;2026-09-12T06:54:00Z&quot;,
  &quot;reviewed_plan_commit&quot;: &quot;b2455710bf0abd83db0c933e1b5e082d07bed4e0&quot;,
  &quot;authorization_source&quot;: &quot;User instruction dated 2026-09-12: proceed&quot;,
  &quot;scope&quot;: [
    &quot;A-01&quot;,
    &quot;O-01&quot;,
    &quot;A-02&quot;,
    &quot;A-03&quot;,
    &quot;A-06&quot;,
    &quot;K-01&quot;,
    &quot;O-05&quot;
  ],
  &quot;explicit_exclusions&quot;: [
    &quot;runtime_business_logic&quot;,
    &quot;order_mutation&quot;,
    &quot;risk_limit_changes&quot;,
    &quot;strategy_promotion&quot;,
    &quot;canary_credentials&quot;,
    &quot;live_trading&quot;,
    &quot;ISG-0_opening&quot;
  ]
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/plan.schema.json</code></summary>

<pre><code>{
  &quot;$schema&quot;: &quot;https://json-schema.org/draft/2020-12/schema&quot;,
  &quot;$id&quot;: &quot;https://jarvis.local/schemas/jarvis-mip-1.1.json&quot;,
  &quot;title&quot;: &quot;JARVIS Master Implementation Plan&quot;,
  &quot;type&quot;: &quot;object&quot;,
  &quot;additionalProperties&quot;: false,
  &quot;required&quot;: [
    &quot;schema_version&quot;,
    &quot;plan_id&quot;,
    &quot;plan_status&quot;,
    &quot;formal_implementation_status&quot;,
    &quot;planning_adoption_gate&quot;,
    &quot;implementation_start_gate&quot;,
    &quot;generated&quot;,
    &quot;repository_baseline&quot;,
    &quot;programs&quot;,
    &quot;epics&quot;,
    &quot;phases&quot;,
    &quot;gates&quot;,
    &quot;work_packages&quot;
  ],
  &quot;properties&quot;: {
    &quot;schema_version&quot;: { &quot;const&quot;: &quot;1.1&quot; },
    &quot;plan_id&quot;: { &quot;const&quot;: &quot;JARVIS-MIP-1.1&quot; },
    &quot;plan_status&quot;: { &quot;enum&quot;: [&quot;ADOPTION_CANDIDATE&quot;, &quot;ADOPTED&quot;, &quot;SUPERSEDED&quot;] },
    &quot;formal_implementation_status&quot;: { &quot;enum&quot;: [&quot;NOT_STARTED&quot;, &quot;ACTIVE&quot;, &quot;COMPLETE&quot;] },
    &quot;planning_adoption_gate&quot;: { &quot;$ref&quot;: &quot;#/$defs/gateStatus&quot; },
    &quot;implementation_start_gate&quot;: { &quot;$ref&quot;: &quot;#/$defs/gateStatus&quot; },
    &quot;generated&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;format&quot;: &quot;date&quot; },
    &quot;repository_baseline&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[0-9a-f]{40}$&quot; },
    &quot;programs&quot;: {
      &quot;type&quot;: &quot;array&quot;,
      &quot;minItems&quot;: 16,
      &quot;maxItems&quot;: 16,
      &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/program&quot; }
    },
    &quot;epics&quot;: {
      &quot;type&quot;: &quot;array&quot;,
      &quot;minItems&quot;: 1,
      &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/epic&quot; }
    },
    &quot;phases&quot;: {
      &quot;type&quot;: &quot;array&quot;,
      &quot;minItems&quot;: 13,
      &quot;maxItems&quot;: 13,
      &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/phase&quot; }
    },
    &quot;gates&quot;: {
      &quot;type&quot;: &quot;array&quot;,
      &quot;minItems&quot;: 14,
      &quot;maxItems&quot;: 14,
      &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/gate&quot; }
    },
    &quot;work_packages&quot;: {
      &quot;type&quot;: &quot;array&quot;,
      &quot;minItems&quot;: 103,
      &quot;maxItems&quot;: 103,
      &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/workPackage&quot; }
    }
  },
  &quot;$defs&quot;: {
    &quot;gateStatus&quot;: { &quot;enum&quot;: [&quot;CLOSED&quot;, &quot;OPEN&quot;, &quot;PASSED&quot;] },
    &quot;program&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [&quot;id&quot;, &quot;name&quot;],
      &quot;properties&quot;: {
        &quot;id&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]$&quot; },
        &quot;name&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 }
      }
    },
    &quot;epic&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [&quot;id&quot;, &quot;program&quot;, &quot;title&quot;, &quot;work_packages&quot;],
      &quot;properties&quot;: {
        &quot;id&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]-E[1-9][0-9]*$&quot; },
        &quot;program&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]$&quot; },
        &quot;title&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;work_packages&quot;: {
          &quot;type&quot;: &quot;array&quot;,
          &quot;minItems&quot;: 1,
          &quot;uniqueItems&quot;: true,
          &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/wpId&quot; }
        }
      }
    },
    &quot;phase&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [&quot;id&quot;, &quot;name&quot;, &quot;exit_gate&quot;],
      &quot;properties&quot;: {
        &quot;id&quot;: { &quot;type&quot;: &quot;integer&quot;, &quot;minimum&quot;: 0, &quot;maximum&quot;: 12 },
        &quot;name&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;exit_gate&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^(ISG-0|M(?:[1-9]|1[0-2]))$&quot; }
      }
    },
    &quot;gate&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [&quot;id&quot;, &quot;status&quot;, &quot;authority&quot;, &quot;required_work_packages&quot;, &quot;evidence_manifest&quot;],
      &quot;properties&quot;: {
        &quot;id&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^(PAG-0|ISG-0|M(?:[1-9]|1[0-2]))$&quot; },
        &quot;status&quot;: { &quot;$ref&quot;: &quot;#/$defs/gateStatus&quot; },
        &quot;authority&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;required_work_packages&quot;: {
          &quot;type&quot;: &quot;array&quot;,
          &quot;uniqueItems&quot;: true,
          &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/wpId&quot; }
        },
        &quot;evidence_manifest&quot;: { &quot;type&quot;: [&quot;string&quot;, &quot;null&quot;] }
      }
    },
    &quot;wpId&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]-[0-9]{2}$&quot; },
    &quot;evidenceRequirements&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [
        &quot;minimum_rung&quot;,
        &quot;required_reviews&quot;,
        &quot;required_observations&quot;,
        &quot;numeric_cross_check&quot;,
        &quot;pit_verification&quot;
      ],
      &quot;properties&quot;: {
        &quot;minimum_rung&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^E[0-5]$&quot; },
        &quot;required_reviews&quot;: { &quot;type&quot;: &quot;array&quot;, &quot;uniqueItems&quot;: true, &quot;items&quot;: { &quot;type&quot;: &quot;string&quot; } },
        &quot;required_observations&quot;: { &quot;type&quot;: &quot;array&quot;, &quot;uniqueItems&quot;: true, &quot;items&quot;: { &quot;type&quot;: &quot;string&quot; } },
        &quot;numeric_cross_check&quot;: { &quot;type&quot;: &quot;boolean&quot; },
        &quot;pit_verification&quot;: { &quot;type&quot;: &quot;boolean&quot; }
      }
    },
    &quot;workPackage&quot;: {
      &quot;type&quot;: &quot;object&quot;,
      &quot;additionalProperties&quot;: false,
      &quot;required&quot;: [
        &quot;id&quot;,
        &quot;program&quot;,
        &quot;epic&quot;,
        &quot;phase&quot;,
        &quot;milestone&quot;,
        &quot;title&quot;,
        &quot;status&quot;,
        &quot;dependencies&quot;,
        &quot;safety_class&quot;,
        &quot;codex_level&quot;,
        &quot;charter_required&quot;,
        &quot;objective&quot;,
        &quot;acceptance_summary&quot;,
        &quot;evidence_requirements&quot;,
        &quot;charter_path&quot;,
        &quot;evidence_manifest_path&quot;
      ],
      &quot;properties&quot;: {
        &quot;id&quot;: { &quot;$ref&quot;: &quot;#/$defs/wpId&quot; },
        &quot;program&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]$&quot; },
        &quot;epic&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^[A-P]-E[1-9][0-9]*$&quot; },
        &quot;phase&quot;: { &quot;type&quot;: &quot;integer&quot;, &quot;minimum&quot;: 0, &quot;maximum&quot;: 12 },
        &quot;milestone&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^(ISG-0|M(?:[1-9]|1[0-2]))$&quot; },
        &quot;title&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;status&quot;: {
          &quot;enum&quot;: [&quot;NOT_STARTED&quot;, &quot;READY&quot;, &quot;IN_PROGRESS&quot;, &quot;BLOCKED&quot;, &quot;VALIDATION&quot;, &quot;DONE&quot;, &quot;SUPERSEDED&quot;]
        },
        &quot;dependencies&quot;: { &quot;type&quot;: &quot;array&quot;, &quot;uniqueItems&quot;: true, &quot;items&quot;: { &quot;$ref&quot;: &quot;#/$defs/wpId&quot; } },
        &quot;safety_class&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^S[0-4]$&quot; },
        &quot;codex_level&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;pattern&quot;: &quot;^A[0-2]$&quot; },
        &quot;charter_required&quot;: { &quot;const&quot;: true },
        &quot;objective&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;acceptance_summary&quot;: { &quot;type&quot;: &quot;string&quot;, &quot;minLength&quot;: 1 },
        &quot;evidence_requirements&quot;: { &quot;$ref&quot;: &quot;#/$defs/evidenceRequirements&quot; },
        &quot;charter_path&quot;: { &quot;type&quot;: [&quot;string&quot;, &quot;null&quot;] },
        &quot;draft_charter_path&quot;: { &quot;type&quot;: [&quot;string&quot;, &quot;null&quot;] },
        &quot;evidence_manifest_path&quot;: { &quot;type&quot;: [&quot;string&quot;, &quot;null&quot;] }
      }
    }
  }
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/templates/evidence-manifest.example.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.0&quot;,
  &quot;plan_id&quot;: &quot;JARVIS-MIP-1.1&quot;,
  &quot;work_package_id&quot;: &quot;A-01&quot;,
  &quot;charter_version&quot;: &quot;1.0&quot;,
  &quot;status&quot;: &quot;DRAFT&quot;,
  &quot;commit&quot;: &quot;0000000000000000000000000000000000000000&quot;,
  &quot;created_at&quot;: &quot;2026-09-02T00:00:00Z&quot;,
  &quot;actor&quot;: {
    &quot;type&quot;: &quot;human_or_agent&quot;,
    &quot;id&quot;: &quot;replace-me&quot;
  },
  &quot;versions&quot;: {
    &quot;code&quot;: &quot;replace-me&quot;,
    &quot;data&quot;: null,
    &quot;config&quot;: null,
    &quot;risk_policy&quot;: null
  },
  &quot;checks&quot;: [
    {
      &quot;command&quot;: &quot;python scripts/validate_jarvis_mip.py --profile adoption-candidate&quot;,
      &quot;result&quot;: &quot;PASS&quot;,
      &quot;evidence_rung&quot;: &quot;E0&quot;,
      &quot;observed_at&quot;: &quot;2026-09-02T00:00:00Z&quot;,
      &quot;artifact&quot;: null
    }
  ],
  &quot;numeric_cross_checks&quot;: [],
  &quot;pit_checks&quot;: [],
  &quot;reviews&quot;: [],
  &quot;runtime_observations&quot;: [],
  &quot;residual_risks&quot;: [],
  &quot;limitations&quot;: [
    &quot;Example only; this is not completion evidence.&quot;
  ],
  &quot;approvals&quot;: []
}
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/templates/work-package-charter.md</code></summary>

<pre><code># Work Package Charter: `&lt;WP-ID&gt;`

## Control metadata

| Field | Value |
|---|---|
| Plan | `JARVIS-MIP-1.1` |
| Program / Epic | `&lt;PROGRAM&gt;` / `&lt;EPIC&gt;` |
| Work Package | `&lt;WP-ID&gt;` |
| Charter version | `0.1-draft` |
| Status | `DRAFT` |
| Phase / Gate | `&lt;PHASE&gt;` / `&lt;GATE&gt;` |
| Safety / Decision / Codex | `&lt;S#&gt;` / `&lt;D#&gt;` / `&lt;A#&gt;` |
| Accountable human | `&lt;NAME&gt;` |
| Implementation owner | `&lt;NAME OR AGENT&gt;` |
| Independent reviewer | `&lt;NAME&gt;` |

## Objective

State one observable outcome. Do not describe implementation activity as the
outcome.

## Non-goals

- Explicitly excluded behavior.
- Adjacent capability deferred to another WP.

## Dependencies

| WP / contract | Required state | Evidence or mock |
|---|---|---|
| `&lt;ID&gt;` | `&lt;DONE/approved contract&gt;` | `&lt;path&gt;` |

## Authority and contracts

### Authoritative inputs

| Value/domain | Authority | Freshness/completeness rule | Failure behavior |
|---|---|---|---|
| `&lt;VALUE&gt;` | `&lt;SOURCE&gt;` | `&lt;RULE&gt;` | `&lt;FAIL CLOSED/DEGRADE&gt;` |

### Input contracts

- `&lt;named contract and version&gt;`

### Output contracts

- `&lt;named contract and version&gt;`

### Forbidden dependencies and mutations

- `&lt;domain or mutation this WP may not perform&gt;`

## Acceptance criteria

- [ ] Criterion is deterministic and observable.
- [ ] Unavailable, stale, partial, and ambiguous states are specified.
- [ ] No duplicate authority or bypass is introduced.

## Verification plan

| Requirement | Evidence |
|---|---|
| Minimum rung | `&lt;E0-E5&gt;` |
| Unit/property | `&lt;tests&gt;` |
| Integration/replay | `&lt;tests&gt;` |
| Numeric cross-check | `&lt;inputs and expected values, or N/A&gt;` |
| PIT/session/timezone | `&lt;adversarial cases, or N/A&gt;` |
| Security/adversarial | `&lt;cases, or N/A&gt;` |
| Runtime/broker observation | `&lt;procedure, or N/A&gt;` |

## Migration and compatibility

Describe observe → shadow → compare → replay → isolated paper → cutover. Name
the compatibility boundary and the authority during migration.

## Rollback and disable plan

Required for S2+. State the disable mechanism, preserved data, recovery steps,
and conditions that prohibit automatic retry or re-enable.

## Observability and audit

List events, reason codes, metrics, traces, freshness states, actor identity,
and correlation/causation requirements.

## Evidence manifest

`&lt;repo-relative path created during VALIDATION&gt;`

## Residual risks and assumptions

| Risk/assumption | Impact | Owner | Resolution or acceptance |
|---|---|---|---|
| `&lt;ITEM&gt;` | `&lt;IMPACT&gt;` | `&lt;OWNER&gt;` | `&lt;ACTION&gt;` |

## Approvals

| Role | Decision | Identity | UTC timestamp | Evidence |
|---|---|---|---|---|
| Accountable human | PENDING | — | — | — |
| Independent reviewer | PENDING | — | — | — |
| Safety/capital owner, if required | PENDING | — | — | — |
</code></pre>

</details>

<details>
<summary><code>docs/plans/jarvis-mip-1.1/work_packages.json</code></summary>

<pre><code>{
  &quot;schema_version&quot;: &quot;1.1&quot;,
  &quot;plan_id&quot;: &quot;JARVIS-MIP-1.1&quot;,
  &quot;plan_status&quot;: &quot;ADOPTED&quot;,
  &quot;formal_implementation_status&quot;: &quot;NOT_STARTED&quot;,
  &quot;planning_adoption_gate&quot;: &quot;OPEN&quot;,
  &quot;implementation_start_gate&quot;: &quot;CLOSED&quot;,
  &quot;generated&quot;: &quot;2026-09-01&quot;,
  &quot;repository_baseline&quot;: &quot;1d8f93992205d1dcacc05e0466d89247f2c789d1&quot;,
  &quot;programs&quot;: [
    {
      &quot;id&quot;: &quot;A&quot;,
      &quot;name&quot;: &quot;Platform &amp; Architecture&quot;
    },
    {
      &quot;id&quot;: &quot;B&quot;,
      &quot;name&quot;: &quot;Data Engineering&quot;
    },
    {
      &quot;id&quot;: &quot;C&quot;,
      &quot;name&quot;: &quot;Feature Engineering&quot;
    },
    {
      &quot;id&quot;: &quot;D&quot;,
      &quot;name&quot;: &quot;Strategy Research&quot;
    },
    {
      &quot;id&quot;: &quot;E&quot;,
      &quot;name&quot;: &quot;Judge &amp; Statistical Validation&quot;
    },
    {
      &quot;id&quot;: &quot;F&quot;,
      &quot;name&quot;: &quot;Portfolio Construction&quot;
    },
    {
      &quot;id&quot;: &quot;G&quot;,
      &quot;name&quot;: &quot;Capital Path&quot;
    },
    {
      &quot;id&quot;: &quot;H&quot;,
      &quot;name&quot;: &quot;Risk Management&quot;
    },
    {
      &quot;id&quot;: &quot;I&quot;,
      &quot;name&quot;: &quot;Execution / OMS&quot;
    },
    {
      &quot;id&quot;: &quot;J&quot;,
      &quot;name&quot;: &quot;Broker Integration&quot;
    },
    {
      &quot;id&quot;: &quot;K&quot;,
      &quot;name&quot;: &quot;Command Center / UX&quot;
    },
    {
      &quot;id&quot;: &quot;L&quot;,
      &quot;name&quot;: &quot;AI Intelligence &amp; Agents&quot;
    },
    {
      &quot;id&quot;: &quot;M&quot;,
      &quot;name&quot;: &quot;Observability &amp; Operations&quot;
    },
    {
      &quot;id&quot;: &quot;N&quot;,
      &quot;name&quot;: &quot;Security &amp; Access&quot;
    },
    {
      &quot;id&quot;: &quot;O&quot;,
      &quot;name&quot;: &quot;DevOps / CI-CD&quot;
    },
    {
      &quot;id&quot;: &quot;P&quot;,
      &quot;name&quot;: &quot;Paper to Canary to Production&quot;
    }
  ],
  &quot;epics&quot;: [
    {
      &quot;id&quot;: &quot;A-E1&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;title&quot;: &quot;Runtime canon and governance&quot;,
      &quot;work_packages&quot;: [
        &quot;A-01&quot;,
        &quot;A-02&quot;,
        &quot;A-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;A-E2&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;title&quot;: &quot;Core architecture and composition&quot;,
      &quot;work_packages&quot;: [
        &quot;A-03&quot;,
        &quot;A-04&quot;,
        &quot;A-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;B-E1&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;title&quot;: &quot;Instrument and live-data truth&quot;,
      &quot;work_packages&quot;: [
        &quot;B-01&quot;,
        &quot;B-02&quot;,
        &quot;B-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;B-E2&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;title&quot;: &quot;Reproducible research data and replay&quot;,
      &quot;work_packages&quot;: [
        &quot;B-03&quot;,
        &quot;B-04&quot;,
        &quot;B-06&quot;,
        &quot;B-07&quot;,
        &quot;B-08&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;C-E1&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;title&quot;: &quot;Feature governance, causal audit and parity&quot;,
      &quot;work_packages&quot;: [
        &quot;C-01&quot;,
        &quot;C-02&quot;,
        &quot;C-05&quot;,
        &quot;C-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;C-E2&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;title&quot;: &quot;PIT feature runtime and ablation&quot;,
      &quot;work_packages&quot;: [
        &quot;C-03&quot;,
        &quot;C-04&quot;,
        &quot;C-07&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;D-E1&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;title&quot;: &quot;Deterministic strategy protocol and families&quot;,
      &quot;work_packages&quot;: [
        &quot;D-01&quot;,
        &quot;D-02&quot;,
        &quot;D-03&quot;,
        &quot;D-04&quot;,
        &quot;D-05&quot;,
        &quot;D-08&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;D-E2&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;title&quot;: &quot;Meta-labeling and statistical ML&quot;,
      &quot;work_packages&quot;: [
        &quot;D-06&quot;,
        &quot;D-07&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;E-E1&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;title&quot;: &quot;Trial accounting and validation mechanics&quot;,
      &quot;work_packages&quot;: [
        &quot;E-01&quot;,
        &quot;E-02&quot;,
        &quot;E-03&quot;,
        &quot;E-04&quot;,
        &quot;E-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;E-E2&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;title&quot;: &quot;Falsification, holdout and forward Judge&quot;,
      &quot;work_packages&quot;: [
        &quot;E-06&quot;,
        &quot;E-07&quot;,
        &quot;E-08&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;F-E1&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;title&quot;: &quot;Portfolio truth and exposure&quot;,
      &quot;work_packages&quot;: [
        &quot;F-01&quot;,
        &quot;F-02&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;F-E2&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;title&quot;: &quot;Allocation and attribution&quot;,
      &quot;work_packages&quot;: [
        &quot;F-03&quot;,
        &quot;F-04&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;G-E1&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;title&quot;: &quot;Dynamic capital simulation&quot;,
      &quot;work_packages&quot;: [
        &quot;G-01&quot;,
        &quot;G-02&quot;,
        &quot;G-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;G-E2&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;title&quot;: &quot;Risk frontier and decision support&quot;,
      &quot;work_packages&quot;: [
        &quot;G-04&quot;,
        &quot;G-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;H-E1&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;title&quot;: &quot;Policy, sizing and trade gates&quot;,
      &quot;work_packages&quot;: [
        &quot;H-01&quot;,
        &quot;H-02&quot;,
        &quot;H-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;H-E2&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;title&quot;: &quot;Drawdown, halts and adversarial safety&quot;,
      &quot;work_packages&quot;: [
        &quot;H-04&quot;,
        &quot;H-05&quot;,
        &quot;H-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;I-E1&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;title&quot;: &quot;Intent and OMS lifecycle&quot;,
      &quot;work_packages&quot;: [
        &quot;I-01&quot;,
        &quot;I-02&quot;,
        &quot;I-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;I-E2&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;title&quot;: &quot;Protection, order management and recovery&quot;,
      &quot;work_packages&quot;: [
        &quot;I-04&quot;,
        &quot;I-05&quot;,
        &quot;I-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;J-E1&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;title&quot;: &quot;Broker contract and IB paper consolidation&quot;,
      &quot;work_packages&quot;: [
        &quot;J-01&quot;,
        &quot;J-02&quot;,
        &quot;J-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;J-E2&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;title&quot;: &quot;Execution evidence and live boundary&quot;,
      &quot;work_packages&quot;: [
        &quot;J-04&quot;,
        &quot;J-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;K-E1&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;title&quot;: &quot;Product IA and operator cockpit&quot;,
      &quot;work_packages&quot;: [
        &quot;K-01&quot;,
        &quot;K-02&quot;,
        &quot;K-03&quot;,
        &quot;K-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;K-E2&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;title&quot;: &quot;Trade and position control surfaces&quot;,
      &quot;work_packages&quot;: [
        &quot;K-04&quot;,
        &quot;K-05&quot;,
        &quot;K-11&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;K-E3&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;title&quot;: &quot;Research, capital and performance surfaces&quot;,
      &quot;work_packages&quot;: [
        &quot;K-07&quot;,
        &quot;K-08&quot;,
        &quot;K-09&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;K-E4&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;title&quot;: &quot;Health, admin and numeric trust&quot;,
      &quot;work_packages&quot;: [
        &quot;K-10&quot;,
        &quot;K-12&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;L-E1&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;title&quot;: &quot;AI authority and contextual intelligence&quot;,
      &quot;work_packages&quot;: [
        &quot;L-01&quot;,
        &quot;L-02&quot;,
        &quot;L-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;L-E2&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;title&quot;: &quot;Critic, post-trade learning and evaluation&quot;,
      &quot;work_packages&quot;: [
        &quot;L-04&quot;,
        &quot;L-05&quot;,
        &quot;L-06&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;M-E1&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;title&quot;: &quot;Audit, event, trace and health foundation&quot;,
      &quot;work_packages&quot;: [
        &quot;M-01&quot;,
        &quot;M-02&quot;,
        &quot;M-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;M-E2&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;title&quot;: &quot;Alerting and incident replay&quot;,
      &quot;work_packages&quot;: [
        &quot;M-04&quot;,
        &quot;M-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;N-E1&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;title&quot;: &quot;Secrets, environments and authorization&quot;,
      &quot;work_packages&quot;: [
        &quot;N-01&quot;,
        &quot;N-02&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;N-E2&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;title&quot;: &quot;Threat model and security automation&quot;,
      &quot;work_packages&quot;: [
        &quot;N-03&quot;,
        &quot;N-04&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;O-E1&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;title&quot;: &quot;CI, verification and reproducible builds&quot;,
      &quot;work_packages&quot;: [
        &quot;O-01&quot;,
        &quot;O-02&quot;,
        &quot;O-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;O-E2&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;title&quot;: &quot;Release evidence and agent/PR governance&quot;,
      &quot;work_packages&quot;: [
        &quot;O-04&quot;,
        &quot;O-05&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;P-E1&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;title&quot;: &quot;Integrated paper evidence and promotion&quot;,
      &quot;work_packages&quot;: [
        &quot;P-01&quot;,
        &quot;P-02&quot;,
        &quot;P-03&quot;
      ]
    },
    {
      &quot;id&quot;: &quot;P-E2&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;title&quot;: &quot;Canary, scaling, degradation and retirement&quot;,
      &quot;work_packages&quot;: [
        &quot;P-04&quot;,
        &quot;P-05&quot;,
        &quot;P-06&quot;,
        &quot;P-07&quot;,
        &quot;P-08&quot;
      ]
    }
  ],
  &quot;phases&quot;: [
    {
      &quot;id&quot;: 0,
      &quot;name&quot;: &quot;Adoption and truth baseline&quot;,
      &quot;exit_gate&quot;: &quot;ISG-0&quot;
    },
    {
      &quot;id&quot;: 1,
      &quot;name&quot;: &quot;Core platform, policy and observability&quot;,
      &quot;exit_gate&quot;: &quot;M1&quot;
    },
    {
      &quot;id&quot;: 2,
      &quot;name&quot;: &quot;PIT data and feature foundation&quot;,
      &quot;exit_gate&quot;: &quot;M2&quot;
    },
    {
      &quot;id&quot;: 3,
      &quot;name&quot;: &quot;Deterministic research and Judge V3&quot;,
      &quot;exit_gate&quot;: &quot;M3&quot;
    },
    {
      &quot;id&quot;: 4,
      &quot;name&quot;: &quot;Risk, OMS and broker consolidation&quot;,
      &quot;exit_gate&quot;: &quot;M4&quot;
    },
    {
      &quot;id&quot;: 5,
      &quot;name&quot;: &quot;Read-only operator product&quot;,
      &quot;exit_gate&quot;: &quot;M5&quot;
    },
    {
      &quot;id&quot;: 6,
      &quot;name&quot;: &quot;Integrated paper control plane&quot;,
      &quot;exit_gate&quot;: &quot;M6&quot;
    },
    {
      &quot;id&quot;: 7,
      &quot;name&quot;: &quot;Capital Path and robust risk optimization&quot;,
      &quot;exit_gate&quot;: &quot;M7&quot;
    },
    {
      &quot;id&quot;: 8,
      &quot;name&quot;: &quot;AI contextual intelligence&quot;,
      &quot;exit_gate&quot;: &quot;M8&quot;
    },
    {
      &quot;id&quot;: 9,
      &quot;name&quot;: &quot;Extended integrated paper validation&quot;,
      &quot;exit_gate&quot;: &quot;M9&quot;
    },
    {
      &quot;id&quot;: 10,
      &quot;name&quot;: &quot;Canary readiness&quot;,
      &quot;exit_gate&quot;: &quot;M10&quot;
    },
    {
      &quot;id&quot;: 11,
      &quot;name&quot;: &quot;Tiny live canary&quot;,
      &quot;exit_gate&quot;: &quot;M11&quot;
    },
    {
      &quot;id&quot;: 12,
      &quot;name&quot;: &quot;Controlled production and continuous research&quot;,
      &quot;exit_gate&quot;: &quot;M12&quot;
    }
  ],
  &quot;gates&quot;: [
    {
      &quot;id&quot;: &quot;PAG-0&quot;,
      &quot;status&quot;: &quot;OPEN&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [],
      &quot;evidence_manifest&quot;: &quot;docs/plans/jarvis-mip-1.1/evidence/PAG-0-adoption.json&quot;
    },
    {
      &quot;id&quot;: &quot;ISG-0&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;A-01&quot;,
        &quot;A-02&quot;,
        &quot;A-03&quot;,
        &quot;A-06&quot;,
        &quot;K-01&quot;,
        &quot;O-01&quot;,
        &quot;O-05&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M1&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;A-04&quot;,
        &quot;A-05&quot;,
        &quot;B-01&quot;,
        &quot;H-01&quot;,
        &quot;H-05&quot;,
        &quot;L-01&quot;,
        &quot;M-01&quot;,
        &quot;M-02&quot;,
        &quot;M-03&quot;,
        &quot;N-01&quot;,
        &quot;N-02&quot;,
        &quot;N-03&quot;,
        &quot;O-02&quot;,
        &quot;O-03&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M2&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;B-02&quot;,
        &quot;B-03&quot;,
        &quot;B-04&quot;,
        &quot;B-05&quot;,
        &quot;B-06&quot;,
        &quot;B-07&quot;,
        &quot;B-08&quot;,
        &quot;C-01&quot;,
        &quot;C-02&quot;,
        &quot;C-03&quot;,
        &quot;C-04&quot;,
        &quot;C-05&quot;,
        &quot;C-06&quot;,
        &quot;E-01&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M3&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;C-07&quot;,
        &quot;D-01&quot;,
        &quot;D-02&quot;,
        &quot;D-03&quot;,
        &quot;D-04&quot;,
        &quot;D-05&quot;,
        &quot;D-06&quot;,
        &quot;D-08&quot;,
        &quot;E-02&quot;,
        &quot;E-03&quot;,
        &quot;E-04&quot;,
        &quot;E-05&quot;,
        &quot;E-06&quot;,
        &quot;E-07&quot;,
        &quot;L-04&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M4&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;F-01&quot;,
        &quot;F-02&quot;,
        &quot;F-03&quot;,
        &quot;H-02&quot;,
        &quot;H-03&quot;,
        &quot;H-06&quot;,
        &quot;I-01&quot;,
        &quot;I-02&quot;,
        &quot;I-03&quot;,
        &quot;I-04&quot;,
        &quot;I-06&quot;,
        &quot;J-01&quot;,
        &quot;J-02&quot;,
        &quot;J-03&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M5&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;K-02&quot;,
        &quot;K-03&quot;,
        &quot;K-06&quot;,
        &quot;K-07&quot;,
        &quot;K-10&quot;,
        &quot;K-11&quot;,
        &quot;K-12&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M6&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;F-04&quot;,
        &quot;I-05&quot;,
        &quot;J-04&quot;,
        &quot;K-04&quot;,
        &quot;K-05&quot;,
        &quot;K-09&quot;,
        &quot;M-04&quot;,
        &quot;M-05&quot;,
        &quot;N-04&quot;,
        &quot;O-04&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M7&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;G-01&quot;,
        &quot;G-02&quot;,
        &quot;G-03&quot;,
        &quot;G-04&quot;,
        &quot;G-05&quot;,
        &quot;H-04&quot;,
        &quot;K-08&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M8&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;plan_gate_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;D-07&quot;,
        &quot;L-02&quot;,
        &quot;L-03&quot;,
        &quot;L-05&quot;,
        &quot;L-06&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M9&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;E-08&quot;,
        &quot;P-01&quot;,
        &quot;P-02&quot;,
        &quot;P-03&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M10&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;J-05&quot;,
        &quot;P-04&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M11&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;P-05&quot;,
        &quot;P-07&quot;
      ],
      &quot;evidence_manifest&quot;: null
    },
    {
      &quot;id&quot;: &quot;M12&quot;,
      &quot;status&quot;: &quot;CLOSED&quot;,
      &quot;authority&quot;: &quot;human_product_capital_owner&quot;,
      &quot;required_work_packages&quot;: [
        &quot;P-06&quot;,
        &quot;P-08&quot;
      ],
      &quot;evidence_manifest&quot;: null
    }
  ],
  &quot;work_packages&quot;: [
    {
      &quot;id&quot;: &quot;A-01&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Runtime truth baseline and contradiction register&quot;,
      &quot;status&quot;: &quot;IN_PROGRESS&quot;,
      &quot;dependencies&quot;: [],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Runtime truth baseline and contradiction register without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/A-01.md&quot;,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;A-02&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Source-of-truth hierarchy and canon ADR&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Source-of-truth hierarchy and canon ADR without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/A-02.md&quot;
    },
    {
      &quot;id&quot;: &quot;A-03&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Target bounded-context architecture ADR&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;,
        &quot;A-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Target bounded-context architecture ADR without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/A-03.md&quot;
    },
    {
      &quot;id&quot;: &quot;A-04&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Core domain contracts&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-03&quot;,
        &quot;B-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Core domain contracts without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;A-05&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Composition-root refactor plan&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Composition-root refactor plan without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;A-06&quot;,
      &quot;program&quot;: &quot;A&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Legacy deprecation registry&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;,
        &quot;A-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;A-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Legacy deprecation registry without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/A-06.md&quot;
    },
    {
      &quot;id&quot;: &quot;B-01&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Instrument Master&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-02&quot;,
        &quot;A-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Instrument Master without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-02&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Market-data provider contracts and provenance&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Market-data provider contracts and provenance without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-03&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Historical research data lake&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-01&quot;,
        &quot;B-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Historical research data lake without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-04&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Point-in-time event model&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Point-in-time event model without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-05&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Exchange calendar and session service&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-01&quot;,
        &quot;B-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Exchange calendar and session service without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-06&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Data-quality gate and quarantine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-02&quot;,
        &quot;B-03&quot;,
        &quot;B-05&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Data-quality gate and quarantine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-07&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Historical/live replay service&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-03&quot;,
        &quot;B-04&quot;,
        &quot;B-05&quot;,
        &quot;B-06&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Historical/live replay service without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;B-08&quot;,
      &quot;program&quot;: &quot;B&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Data-vendor qualification&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-02&quot;,
        &quot;B-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;B-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Data-vendor qualification without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-01&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Feature Registry V3&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Feature Registry V3 without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-02&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Feature availability contract&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-04&quot;,
        &quot;C-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Feature availability contract without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-03&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;PIT Feature Store&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-03&quot;,
        &quot;B-04&quot;,
        &quot;C-01&quot;,
        &quot;C-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E2&quot;,
      &quot;objective&quot;: &quot;Deliver PIT Feature Store without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-04&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Single feature compiler across modes&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-07&quot;,
        &quot;C-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Single feature compiler across modes without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-05&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Legacy ThinkScript causal audit&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-01&quot;,
        &quot;C-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Legacy ThinkScript causal audit without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-06&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Golden Vector parity framework&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-01&quot;,
        &quot;C-04&quot;,
        &quot;C-05&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Golden Vector parity framework without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;C-07&quot;,
      &quot;program&quot;: &quot;C&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Feature-family taxonomy and ablation hooks&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-03&quot;,
        &quot;C-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;C-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Feature-family taxonomy and ablation hooks without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-01&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Deterministic Strategy Protocol&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;C-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Deterministic Strategy Protocol without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-02&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Outcome and R-label engine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-07&quot;,
        &quot;D-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Outcome and R-label engine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-03&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Cost/slippage repricing engine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-01&quot;,
        &quot;B-03&quot;,
        &quot;D-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Cost/slippage repricing engine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-04&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Relative-strength momentum baseline&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-04&quot;,
        &quot;D-01&quot;,
        &quot;D-02&quot;,
        &quot;D-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Relative-strength momentum baseline without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-05&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Strategy family library contracts&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;D-01&quot;,
        &quot;D-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Strategy family library contracts without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-06&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Meta-label dataset builder&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-07&quot;,
        &quot;D-02&quot;,
        &quot;D-04&quot;,
        &quot;E-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Meta-label dataset builder without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-07&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 8,
      &quot;milestone&quot;: &quot;M8&quot;,
      &quot;title&quot;: &quot;Baseline statistical ML models&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;D-06&quot;,
        &quot;E-07&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Baseline statistical ML models without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;D-08&quot;,
      &quot;program&quot;: &quot;D&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Strategy lifecycle registry&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;D-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;D-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Strategy lifecycle registry without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-01&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 2,
      &quot;milestone&quot;: &quot;M2&quot;,
      &quot;title&quot;: &quot;Immutable preregistered trial ledger&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Immutable preregistered trial ledger without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-02&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Purged CV and CPCV engine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-04&quot;,
        &quot;D-02&quot;,
        &quot;E-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Purged CV and CPCV engine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-03&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Judge V3 orchestrator&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-01&quot;,
        &quot;D-08&quot;,
        &quot;E-01&quot;,
        &quot;E-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Judge V3 orchestrator without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-04&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Honest DSR/PBO and trial accounting&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;E-01&quot;,
        &quot;E-02&quot;,
        &quot;E-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Honest DSR/PBO and trial accounting without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-05&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Parameter plateau and stability&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;E-02&quot;,
        &quot;E-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Parameter plateau and stability without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-06&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Stress, ablation and falsification harness&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;C-07&quot;,
        &quot;D-03&quot;,
        &quot;E-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Stress, ablation and falsification harness without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-07&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Locked holdout and immutable evidence bundle&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-03&quot;,
        &quot;E-01&quot;,
        &quot;E-03&quot;,
        &quot;E-04&quot;,
        &quot;E-05&quot;,
        &quot;E-06&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Locked holdout and immutable evidence bundle without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;E-08&quot;,
      &quot;program&quot;: &quot;E&quot;,
      &quot;phase&quot;: 9,
      &quot;milestone&quot;: &quot;M9&quot;,
      &quot;title&quot;: &quot;Paper evidence Judge extension&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;E-03&quot;,
        &quot;P-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;E-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Paper evidence Judge extension without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;F-01&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Authoritative portfolio state model&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;F-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Authoritative portfolio state model without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;F-02&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Exposure/factor/correlation model&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-01&quot;,
        &quot;F-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;F-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Exposure/factor/correlation model without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;F-03&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Portfolio allocator contract&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;D-08&quot;,
        &quot;F-02&quot;,
        &quot;H-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;F-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Portfolio allocator contract without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;F-04&quot;,
      &quot;program&quot;: &quot;F&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Portfolio attribution&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;F-01&quot;,
        &quot;F-03&quot;,
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;F-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Portfolio attribution without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;G-01&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Capital Path core accounting&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;F-01&quot;,
        &quot;H-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;G-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Capital Path core accounting without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;G-02&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Capital Path resampling ensemble&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;G-01&quot;,
        &quot;E-07&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;G-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Capital Path resampling ensemble without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;G-03&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Parameter/edge uncertainty and stress&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;G-02&quot;,
        &quot;E-06&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;G-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Parameter/edge uncertainty and stress without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;G-04&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Robust risk-policy frontier&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;G-03&quot;,
        &quot;H-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;G-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Robust risk-policy frontier without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;G-05&quot;,
      &quot;program&quot;: &quot;G&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Milestone/forecast API and evidence&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;G-01&quot;,
        &quot;G-02&quot;,
        &quot;G-03&quot;,
        &quot;G-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;G-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Milestone/forecast API and evidence without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-01&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Versioned Risk Policy artifact&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-02&quot;,
        &quot;A-04&quot;,
        &quot;B-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Versioned Risk Policy artifact without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-02&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Zero-allowed position sizing&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-01&quot;,
        &quot;F-03&quot;,
        &quot;H-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Zero-allowed position sizing without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-03&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Trade/portfolio risk gates&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;F-02&quot;,
        &quot;H-01&quot;,
        &quot;H-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Trade/portfolio risk gates without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-04&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Drawdown governor and hysteresis&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;G-01&quot;,
        &quot;H-01&quot;,
        &quot;H-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Drawdown governor and hysteresis without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-05&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Kill switch and halt state machine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;H-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Kill switch and halt state machine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;H-06&quot;,
      &quot;program&quot;: &quot;H&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Risk adversarial verification suite&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;H-02&quot;,
        &quot;H-03&quot;,
        &quot;H-05&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;H-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Risk adversarial verification suite without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-01&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Trade Intent contract&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;D-01&quot;,
        &quot;F-03&quot;,
        &quot;H-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Trade Intent contract without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-02&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Single OMS state machine&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;I-01&quot;,
        &quot;H-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Single OMS state machine without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-03&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Idempotency and duplicate prevention&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;I-01&quot;,
        &quot;I-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Idempotency and duplicate prevention without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-04&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Protective bracket semantics&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;I-02&quot;,
        &quot;J-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Protective bracket semantics without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-05&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Order-management intents&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;I-02&quot;,
        &quot;I-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Order-management intents without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;I-06&quot;,
      &quot;program&quot;: &quot;I&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Restart recovery and reconciliation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;I-02&quot;,
        &quot;J-03&quot;,
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;I-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Restart recovery and reconciliation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;J-01&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Broker adapter interface&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;,
        &quot;B-01&quot;,
        &quot;I-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;J-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Broker adapter interface without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;J-02&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;IBKR paper adapter consolidation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;J-01&quot;,
        &quot;A-06&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;J-E1&quot;,
      &quot;objective&quot;: &quot;Deliver IBKR paper adapter consolidation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;J-03&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;phase&quot;: 4,
      &quot;milestone&quot;: &quot;M4&quot;,
      &quot;title&quot;: &quot;Broker-authoritative state and reconciliation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;J-01&quot;,
        &quot;F-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;J-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Broker-authoritative state and reconciliation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;J-04&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Execution-quality capture&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;J-02&quot;,
        &quot;J-03&quot;,
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;J-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Execution-quality capture without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;J-05&quot;,
      &quot;program&quot;: &quot;J&quot;,
      &quot;phase&quot;: 10,
      &quot;milestone&quot;: &quot;M10&quot;,
      &quot;title&quot;: &quot;Live-canary broker boundary&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;J-02&quot;,
        &quot;J-03&quot;,
        &quot;N-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;J-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Live-canary broker boundary without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-01&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Operator product IA and wireframe approval&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Operator product IA and wireframe approval without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/K-01.md&quot;
    },
    {
      &quot;id&quot;: &quot;K-02&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Command Center read-only cockpit&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;F-01&quot;,
        &quot;H-01&quot;,
        &quot;J-03&quot;,
        &quot;M-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Command Center read-only cockpit without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-03&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Today / Market and Signal workspace&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;B-02&quot;,
        &quot;C-04&quot;,
        &quot;D-08&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Today / Market and Signal workspace without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-04&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Trade Workstation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-02&quot;,
        &quot;I-01&quot;,
        &quot;I-02&quot;,
        &quot;H-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Trade Workstation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-05&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Positions and Orders&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-02&quot;,
        &quot;I-05&quot;,
        &quot;J-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Positions and Orders without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-06&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Risk Center&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;H-01&quot;,
        &quot;H-03&quot;,
        &quot;H-05&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Risk Center without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-07&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Research / Backtest / Judge workspace&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;E-03&quot;,
        &quot;E-07&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E3&quot;,
      &quot;objective&quot;: &quot;Deliver Research / Backtest / Judge workspace without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-08&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 7,
      &quot;milestone&quot;: &quot;M7&quot;,
      &quot;title&quot;: &quot;Capital Path workspace&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;G-05&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E3&quot;,
      &quot;objective&quot;: &quot;Deliver Capital Path workspace without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-09&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Performance and Journal&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;F-04&quot;,
        &quot;J-04&quot;,
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E3&quot;,
      &quot;objective&quot;: &quot;Deliver Performance and Journal without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-10&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;System Health / Admin&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-01&quot;,
        &quot;M-03&quot;,
        &quot;N-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E4&quot;,
      &quot;objective&quot;: &quot;Deliver System Health / Admin without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-11&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Realtime observation transport&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;M-01&quot;,
        &quot;M-02&quot;,
        &quot;K-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Realtime observation transport without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;K-12&quot;,
      &quot;program&quot;: &quot;K&quot;,
      &quot;phase&quot;: 5,
      &quot;milestone&quot;: &quot;M5&quot;,
      &quot;title&quot;: &quot;Numeric/provenance E2E verification&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;K-02&quot;,
        &quot;K-03&quot;,
        &quot;K-06&quot;,
        &quot;K-10&quot;,
        &quot;O-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;K-E4&quot;,
      &quot;objective&quot;: &quot;Deliver Numeric/provenance E2E verification without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-01&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;AI authority boundary and capability policy&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-02&quot;,
        &quot;A-03&quot;,
        &quot;H-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E1&quot;,
      &quot;objective&quot;: &quot;Deliver AI authority boundary and capability policy without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-02&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 8,
      &quot;milestone&quot;: &quot;M8&quot;,
      &quot;title&quot;: &quot;Context intelligence service&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;B-02&quot;,
        &quot;L-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Context intelligence service without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-03&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 8,
      &quot;milestone&quot;: &quot;M8&quot;,
      &quot;title&quot;: &quot;Catalyst/event intelligence&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;L-02&quot;,
        &quot;C-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Catalyst/event intelligence without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-04&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 3,
      &quot;milestone&quot;: &quot;M3&quot;,
      &quot;title&quot;: &quot;Research critic agent&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;E-01&quot;,
        &quot;E-03&quot;,
        &quot;L-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Research critic agent without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-05&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 8,
      &quot;milestone&quot;: &quot;M8&quot;,
      &quot;title&quot;: &quot;Post-trade learning and explanation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;F-04&quot;,
        &quot;J-04&quot;,
        &quot;L-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A2&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Post-trade learning and explanation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;L-06&quot;,
      &quot;program&quot;: &quot;L&quot;,
      &quot;phase&quot;: 8,
      &quot;milestone&quot;: &quot;M8&quot;,
      &quot;title&quot;: &quot;Agent evaluation and prompt-security harness&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;L-02&quot;,
        &quot;L-04&quot;,
        &quot;N-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;L-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Agent evaluation and prompt-security harness without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: true
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;M-01&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Canonical event and audit schema&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;M-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Canonical event and audit schema without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;M-02&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Structured logging and tracing&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;M-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Structured logging and tracing without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;M-03&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Health model and SLOs&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;,
        &quot;M-02&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;M-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Health model and SLOs without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;M-04&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Alerting and escalation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;M-03&quot;,
        &quot;H-05&quot;,
        &quot;J-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;M-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Alerting and escalation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;M-05&quot;,
      &quot;program&quot;: &quot;M&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Incident replay and forensic bundle&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;M-01&quot;,
        &quot;M-02&quot;,
        &quot;B-07&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;M-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Incident replay and forensic bundle without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;N-01&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Secrets/authentication baseline&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;N-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Secrets/authentication baseline without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;N-02&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Environment and authorization matrix&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-02&quot;,
        &quot;N-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;N-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Environment and authorization matrix without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;N-03&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Threat model&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-03&quot;,
        &quot;N-02&quot;,
        &quot;L-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;N-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Threat model without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;N-04&quot;,
      &quot;program&quot;: &quot;N&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Security/dependency audit automation&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;N-01&quot;,
        &quot;N-03&quot;,
        &quot;O-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;N-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Security/dependency audit automation without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;O-01&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;CI baseline and debt classification&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S0&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;O-E1&quot;,
      &quot;objective&quot;: &quot;Deliver CI baseline and debt classification without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E0&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/O-01.md&quot;
    },
    {
      &quot;id&quot;: &quot;O-02&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Testing tiers and verification ladder&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;O-01&quot;,
        &quot;A-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;O-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Testing tiers and verification ladder without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;O-03&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;phase&quot;: 1,
      &quot;milestone&quot;: &quot;M1&quot;,
      &quot;title&quot;: &quot;Reproducible dev/build environment&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;O-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;O-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Reproducible dev/build environment without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;O-04&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;phase&quot;: 6,
      &quot;milestone&quot;: &quot;M6&quot;,
      &quot;title&quot;: &quot;Release evidence manifest&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;O-02&quot;,
        &quot;M-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S1&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;O-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Release evidence manifest without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;O-05&quot;,
      &quot;program&quot;: &quot;O&quot;,
      &quot;phase&quot;: 0,
      &quot;milestone&quot;: &quot;ISG-0&quot;,
      &quot;title&quot;: &quot;Branch/PR/Codex governance&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;A-02&quot;,
        &quot;O-01&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;O-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Branch/PR/Codex governance without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: false,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: &quot;docs/plans/jarvis-mip-1.1/charters/O-05.md&quot;
    },
    {
      &quot;id&quot;: &quot;P-01&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 9,
      &quot;milestone&quot;: &quot;M9&quot;,
      &quot;title&quot;: &quot;Integrated paper campaign&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;D-08&quot;,
        &quot;E-07&quot;,
        &quot;F-01&quot;,
        &quot;H-06&quot;,
        &quot;I-06&quot;,
        &quot;J-04&quot;,
        &quot;K-05&quot;,
        &quot;M-04&quot;,
        &quot;O-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Integrated paper campaign without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-02&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 9,
      &quot;milestone&quot;: &quot;M9&quot;,
      &quot;title&quot;: &quot;Execution-fidelity gate&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-01&quot;,
        &quot;J-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S2&quot;,
      &quot;codex_level&quot;: &quot;A1&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Execution-fidelity gate without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-03&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 9,
      &quot;milestone&quot;: &quot;M9&quot;,
      &quot;title&quot;: &quot;Paper strategy promotion gate&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-01&quot;,
        &quot;P-02&quot;,
        &quot;E-08&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E1&quot;,
      &quot;objective&quot;: &quot;Deliver Paper strategy promotion gate without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-04&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 10,
      &quot;milestone&quot;: &quot;M10&quot;,
      &quot;title&quot;: &quot;Canary readiness review&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-03&quot;,
        &quot;G-04&quot;,
        &quot;H-06&quot;,
        &quot;I-06&quot;,
        &quot;J-05&quot;,
        &quot;N-02&quot;,
        &quot;O-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Canary readiness review without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-05&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 11,
      &quot;milestone&quot;: &quot;M11&quot;,
      &quot;title&quot;: &quot;Tiny live canary&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Tiny live canary without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E5&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;explicitly_authorized_live_canary_evidence&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-06&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 12,
      &quot;milestone&quot;: &quot;M12&quot;,
      &quot;title&quot;: &quot;Controlled scaling policy&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-05&quot;,
        &quot;G-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Controlled scaling policy without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E5&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;explicitly_authorized_live_canary_evidence&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-07&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 11,
      &quot;milestone&quot;: &quot;M11&quot;,
      &quot;title&quot;: &quot;Degradation, halt and rollback policy&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-04&quot;,
        &quot;H-05&quot;,
        &quot;M-04&quot;
      ],
      &quot;safety_class&quot;: &quot;S4&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Degradation, halt and rollback policy without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E4&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;,
          &quot;human_capital_owner&quot;
        ],
        &quot;required_observations&quot;: [
          &quot;ibkr_paper_round_trip_or_drill&quot;
        ],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    },
    {
      &quot;id&quot;: &quot;P-08&quot;,
      &quot;program&quot;: &quot;P&quot;,
      &quot;phase&quot;: 12,
      &quot;milestone&quot;: &quot;M12&quot;,
      &quot;title&quot;: &quot;Continuous research and retirement cycle&quot;,
      &quot;status&quot;: &quot;NOT_STARTED&quot;,
      &quot;dependencies&quot;: [
        &quot;P-03&quot;,
        &quot;L-05&quot;,
        &quot;E-03&quot;
      ],
      &quot;safety_class&quot;: &quot;S3&quot;,
      &quot;codex_level&quot;: &quot;A0&quot;,
      &quot;charter_required&quot;: true,
      &quot;epic&quot;: &quot;P-E2&quot;,
      &quot;objective&quot;: &quot;Deliver Continuous research and retirement cycle without creating a competing authority or bypassing an upstream control boundary.&quot;,
      &quot;acceptance_summary&quot;: &quot;PROVISIONAL \u2014 closure requires the approved WP charter criteria and an evidence manifest satisfying this profile.&quot;,
      &quot;evidence_requirements&quot;: {
        &quot;minimum_rung&quot;: &quot;E2&quot;,
        &quot;required_reviews&quot;: [
          &quot;independent_review&quot;,
          &quot;human_safety_review&quot;
        ],
        &quot;required_observations&quot;: [],
        &quot;numeric_cross_check&quot;: true,
        &quot;pit_verification&quot;: false
      },
      &quot;charter_path&quot;: null,
      &quot;evidence_manifest_path&quot;: null,
      &quot;draft_charter_path&quot;: null
    }
  ]
}
</code></pre>

</details>

<details>
<summary><code>scripts/validate_jarvis_mip.py</code></summary>

<pre><code>#!/usr/bin/env python3
&quot;&quot;&quot;Validate the machine-readable JARVIS Master Implementation Plan graph.&quot;&quot;&quot;

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = ROOT / &quot;docs/plans/jarvis-mip-1.1/work_packages.json&quot;
DEFAULT_ADOPTION = ROOT / &quot;docs/plans/jarvis-mip-1.1/adoption_decisions.json&quot;
WP_ID = re.compile(r&quot;^[A-P]-\d{2}$&quot;)
STATUSES = {
    &quot;NOT_STARTED&quot;,
    &quot;READY&quot;,
    &quot;IN_PROGRESS&quot;,
    &quot;BLOCKED&quot;,
    &quot;VALIDATION&quot;,
    &quot;DONE&quot;,
    &quot;SUPERSEDED&quot;,
}
SAFETY_CLASSES = {f&quot;S{number}&quot; for number in range(5)}
CODEX_LEVELS = {f&quot;A{number}&quot; for number in range(3)}
EVIDENCE_RUNGS = {f&quot;E{number}&quot; for number in range(6)}
PROFILES = {&quot;structural&quot;, &quot;adoption-candidate&quot;}
PHASE_ZERO_CHARTERS = {&quot;A-01&quot;, &quot;A-02&quot;, &quot;A-03&quot;, &quot;A-06&quot;, &quot;K-01&quot;, &quot;O-01&quot;, &quot;O-05&quot;}


class ValidationError(ValueError):
    &quot;&quot;&quot;Raised when the plan graph violates a structural invariant.&quot;&quot;&quot;


def require(condition: bool, message: str) -&gt; None:
    if not condition:
        raise ValidationError(message)


def load_graph(path: Path) -&gt; dict[str, Any]:
    with path.open(encoding=&quot;utf-8&quot;) as handle:
        graph = json.load(handle)
    require(isinstance(graph, dict), &quot;graph root must be an object&quot;)
    return graph


def validate_adoption(adoption: dict[str, Any], profile: str) -&gt; None:
    require(adoption.get(&quot;plan_id&quot;) == &quot;JARVIS-MIP-1.1&quot;, &quot;adoption: unexpected plan_id&quot;)
    decisions = adoption.get(&quot;decisions&quot;)
    require(isinstance(decisions, list) and len(decisions) == 14, &quot;adoption: expected 14 decisions&quot;)
    require([item.get(&quot;id&quot;) for item in decisions] == [f&quot;AD-{i:02d}&quot; for i in range(1, 15)], &quot;adoption: IDs must be AD-01 through AD-14&quot;)
    for item in decisions:
        disposition = item.get(&quot;disposition&quot;)
        require(disposition in {&quot;PENDING&quot;, &quot;ACCEPT&quot;, &quot;AMEND&quot;, &quot;REJECT&quot;}, f&quot;{item.get(&#x27;id&#x27;)}: invalid disposition&quot;)
        if disposition != &quot;PENDING&quot;:
            require(item.get(&quot;accountable_human&quot;), f&quot;{item[&#x27;id&#x27;]}: decision requires accountable_human&quot;)
            require(item.get(&quot;decided_at&quot;), f&quot;{item[&#x27;id&#x27;]}: decision requires decided_at&quot;)
            require(item.get(&quot;rationale&quot;), f&quot;{item[&#x27;id&#x27;]}: decision requires rationale&quot;)
    if profile == &quot;adoption-candidate&quot;:
        require(adoption.get(&quot;decision_state&quot;) == &quot;PENDING&quot;, &quot;adoption: decision state must remain PENDING&quot;)
        require(adoption.get(&quot;pag_0&quot;) == &quot;CLOSED&quot;, &quot;adoption: PAG-0 must remain closed&quot;)
        require(adoption.get(&quot;isg_0&quot;) == &quot;CLOSED&quot;, &quot;adoption: ISG-0 must remain closed&quot;)
        require(all(item[&quot;disposition&quot;] == &quot;PENDING&quot; for item in decisions), &quot;adoption: decisions must remain PENDING&quot;)


def validate_bundle(graph: dict[str, Any], adoption: dict[str, Any], profile: str) -&gt; dict[str, int]:
    counts = validate_graph(graph, profile=profile)
    validate_adoption(adoption, profile=profile)
    require(adoption.get(&quot;pag_0&quot;) == graph.get(&quot;planning_adoption_gate&quot;), &quot;bundle: PAG-0 status mismatch&quot;)
    require(adoption.get(&quot;isg_0&quot;) == graph.get(&quot;implementation_start_gate&quot;), &quot;bundle: ISG-0 status mismatch&quot;)
    if adoption.get(&quot;decision_state&quot;) == &quot;ACCEPTED&quot;:
        require(all(item[&quot;disposition&quot;] == &quot;ACCEPT&quot; for item in adoption[&quot;decisions&quot;]), &quot;adoption: ACCEPTED requires all decisions accepted&quot;)
        require(adoption.get(&quot;reviewed_plan_commit&quot;), &quot;adoption: ACCEPTED requires reviewed_plan_commit&quot;)
    if adoption.get(&quot;pag_0&quot;) == &quot;OPEN&quot;:
        require(adoption.get(&quot;decision_state&quot;) == &quot;ACCEPTED&quot;, &quot;adoption: PAG-0 requires accepted decisions&quot;)
    if adoption.get(&quot;isg_0&quot;) == &quot;OPEN&quot;:
        require(adoption.get(&quot;pag_0&quot;) == &quot;OPEN&quot;, &quot;adoption: ISG-0 requires PAG-0 open&quot;)
    return counts


def validate_graph(graph: dict[str, Any], profile: str = &quot;adoption-candidate&quot;) -&gt; dict[str, int]:
    require(profile in PROFILES, f&quot;unknown validation profile {profile}&quot;)
    require(graph.get(&quot;plan_id&quot;) == &quot;JARVIS-MIP-1.1&quot;, &quot;unexpected plan_id&quot;)
    require(graph.get(&quot;schema_version&quot;) == &quot;1.1&quot;, &quot;unexpected schema_version&quot;)
    if profile == &quot;adoption-candidate&quot;:
        require(graph.get(&quot;plan_status&quot;) == &quot;ADOPTION_CANDIDATE&quot;, &quot;plan must remain an adoption candidate&quot;)
        require(graph.get(&quot;formal_implementation_status&quot;) == &quot;NOT_STARTED&quot;, &quot;formal implementation must remain NOT_STARTED&quot;)
        require(graph.get(&quot;planning_adoption_gate&quot;) == &quot;CLOSED&quot;, &quot;planning adoption gate must remain closed&quot;)
        require(graph.get(&quot;implementation_start_gate&quot;) == &quot;CLOSED&quot;, &quot;ISG-0 must remain closed&quot;)

    programs = graph.get(&quot;programs&quot;)
    require(isinstance(programs, list), &quot;programs must be a list&quot;)
    program_ids = [program.get(&quot;id&quot;) for program in programs]
    require(program_ids == list(&quot;ABCDEFGHIJKLMNOP&quot;), &quot;programs must cover A-P in order&quot;)

    packages = graph.get(&quot;work_packages&quot;)
    require(isinstance(packages, list), &quot;work_packages must be a list&quot;)
    require(len(packages) == 103, f&quot;expected 103 work packages, found {len(packages)}&quot;)
    ids = [package.get(&quot;id&quot;) for package in packages]
    require(len(ids) == len(set(ids)), &quot;work-package IDs must be unique&quot;)
    require(all(isinstance(item, str) and WP_ID.fullmatch(item) for item in ids), &quot;invalid work-package ID&quot;)
    by_id = {package[&quot;id&quot;]: package for package in packages}

    phase_counts: Counter[int] = Counter()
    for package in packages:
        package_id = package[&quot;id&quot;]
        require(package.get(&quot;program&quot;) == package_id[0], f&quot;{package_id}: program does not match ID&quot;)
        require(package.get(&quot;status&quot;) in STATUSES, f&quot;{package_id}: invalid status&quot;)
        require(package.get(&quot;safety_class&quot;) in SAFETY_CLASSES, f&quot;{package_id}: invalid safety class&quot;)
        require(package.get(&quot;codex_level&quot;) in CODEX_LEVELS, f&quot;{package_id}: invalid Codex level&quot;)
        evidence = package.get(&quot;evidence_requirements&quot;)
        require(isinstance(evidence, dict), f&quot;{package_id}: evidence_requirements must be an object&quot;)
        require(evidence.get(&quot;minimum_rung&quot;) in EVIDENCE_RUNGS, f&quot;{package_id}: invalid evidence rung&quot;)
        for field in (&quot;required_reviews&quot;, &quot;required_observations&quot;):
            require(isinstance(evidence.get(field), list), f&quot;{package_id}: {field} must be a list&quot;)
            require(len(evidence[field]) == len(set(evidence[field])), f&quot;{package_id}: duplicate {field}&quot;)
        for field in (&quot;numeric_cross_check&quot;, &quot;pit_verification&quot;):
            require(isinstance(evidence.get(field), bool), f&quot;{package_id}: {field} must be boolean&quot;)
        if package.get(&quot;safety_class&quot;) == &quot;S4&quot;:
            require(
                &quot;human_capital_owner&quot; in evidence[&quot;required_reviews&quot;],
                f&quot;{package_id}: S4 evidence requires human_capital_owner&quot;,
            )
        require(package.get(&quot;charter_required&quot;) is True, f&quot;{package_id}: charter_required must be true&quot;)
        draft_charter = package.get(&quot;draft_charter_path&quot;)
        if draft_charter:
            require(package.get(&quot;status&quot;) == &quot;NOT_STARTED&quot;, f&quot;{package_id}: draft charter is only valid for NOT_STARTED&quot;)
            charter_path = ROOT / draft_charter
            require(charter_path.is_file(), f&quot;{package_id}: draft charter path does not exist&quot;)
            charter = charter_path.read_text(encoding=&quot;utf-8&quot;)
            require(charter.startswith(f&quot;# {package_id} —&quot;), f&quot;{package_id}: draft charter heading mismatch&quot;)
            require(&quot;**Status:** DRAFT — NOT READY; PAG-0 CLOSED&quot; in charter, f&quot;{package_id}: draft charter must remain gated&quot;)
        require(isinstance(package.get(&quot;objective&quot;), str) and package[&quot;objective&quot;], f&quot;{package_id}: objective is required&quot;)
        require(
            isinstance(package.get(&quot;acceptance_summary&quot;), str) and package[&quot;acceptance_summary&quot;],
            f&quot;{package_id}: acceptance_summary is required&quot;,
        )
        if package.get(&quot;status&quot;) != &quot;NOT_STARTED&quot;:
            require(package.get(&quot;charter_path&quot;), f&quot;{package_id}: active status requires charter_path&quot;)
        if package.get(&quot;status&quot;) == &quot;DONE&quot;:
            require(package.get(&quot;evidence_manifest_path&quot;), f&quot;{package_id}: DONE requires evidence_manifest_path&quot;)
        phase = package.get(&quot;phase&quot;)
        require(isinstance(phase, int) and 0 &lt;= phase &lt;= 12, f&quot;{package_id}: phase must be 0-12&quot;)
        expected_milestone = &quot;ISG-0&quot; if phase == 0 else f&quot;M{phase}&quot;
        require(package.get(&quot;milestone&quot;) == expected_milestone, f&quot;{package_id}: milestone/phase mismatch&quot;)
        phase_counts[phase] += 1
        dependencies = package.get(&quot;dependencies&quot;)
        require(isinstance(dependencies, list), f&quot;{package_id}: dependencies must be a list&quot;)
        require(len(dependencies) == len(set(dependencies)), f&quot;{package_id}: duplicate dependency&quot;)
        for dependency in dependencies:
            require(dependency in by_id, f&quot;{package_id}: missing dependency {dependency}&quot;)
            require(by_id[dependency][&quot;phase&quot;] &lt;= phase, f&quot;{package_id}: forward-phase dependency {dependency}&quot;)

    require(set(phase_counts) == set(range(13)), &quot;delivery phases must cover 0-12&quot;)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(package_id: str) -&gt; None:
        if package_id in visiting:
            raise ValidationError(f&quot;dependency cycle includes {package_id}&quot;)
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency in by_id[package_id][&quot;dependencies&quot;]:
            visit(dependency)
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in ids:
        visit(package_id)

    epics = graph.get(&quot;epics&quot;)
    require(isinstance(epics, list), &quot;epics must be a list&quot;)
    epic_names = [epic.get(&quot;id&quot;) for epic in epics]
    require(len(epic_names) == len(set(epic_names)), &quot;epic IDs must be unique&quot;)
    epic_members = [item for epic in epics for item in epic.get(&quot;work_packages&quot;, [])]
    require(Counter(epic_members) == Counter(ids), &quot;every work package must appear in one epic&quot;)
    epic_by_id = {epic[&quot;id&quot;]: epic for epic in epics}
    for package in packages:
        epic_id = package.get(&quot;epic&quot;)
        require(epic_id in epic_by_id, f&quot;{package[&#x27;id&#x27;]}: missing epic {epic_id}&quot;)
        require(epic_by_id[epic_id].get(&quot;program&quot;) == package[&quot;program&quot;], f&quot;{package[&#x27;id&#x27;]}: epic/program mismatch&quot;)
        require(package[&quot;id&quot;] in epic_by_id[epic_id][&quot;work_packages&quot;], f&quot;{package[&#x27;id&#x27;]}: epic backlink mismatch&quot;)

    phases = graph.get(&quot;phases&quot;)
    require(isinstance(phases, list), &quot;phases must be a list&quot;)
    require([phase.get(&quot;id&quot;) for phase in phases] == list(range(13)), &quot;phases must cover 0-12 in order&quot;)

    gates = graph.get(&quot;gates&quot;)
    require(isinstance(gates, list), &quot;gates must be a list&quot;)
    gate_ids = [gate.get(&quot;id&quot;) for gate in gates]
    expected_gates = [&quot;PAG-0&quot;, &quot;ISG-0&quot;, *(f&quot;M{number}&quot; for number in range(1, 13))]
    require(gate_ids == expected_gates, &quot;gates must cover PAG-0, ISG-0 and M1-M12 in order&quot;)
    for gate in gates:
        gate_id = gate[&quot;id&quot;]
        require(gate.get(&quot;status&quot;) in {&quot;CLOSED&quot;, &quot;OPEN&quot;, &quot;PASSED&quot;}, f&quot;{gate_id}: invalid gate status&quot;)
        require(isinstance(gate.get(&quot;authority&quot;), str) and gate[&quot;authority&quot;], f&quot;{gate_id}: authority is required&quot;)
        required = gate.get(&quot;required_work_packages&quot;)
        require(isinstance(required, list), f&quot;{gate_id}: required_work_packages must be a list&quot;)
        require(len(required) == len(set(required)), f&quot;{gate_id}: duplicate required work package&quot;)
        require(all(item in by_id for item in required), f&quot;{gate_id}: unknown required work package&quot;)
        if gate[&quot;status&quot;] != &quot;CLOSED&quot;:
            require(gate.get(&quot;evidence_manifest&quot;), f&quot;{gate_id}: open/passed gate requires evidence_manifest&quot;)
    gate_by_id = {gate[&quot;id&quot;]: gate for gate in gates}
    require(gate_by_id[&quot;PAG-0&quot;][&quot;status&quot;] == graph.get(&quot;planning_adoption_gate&quot;), &quot;PAG-0 status mismatch&quot;)
    require(gate_by_id[&quot;ISG-0&quot;][&quot;status&quot;] == graph.get(&quot;implementation_start_gate&quot;), &quot;ISG-0 status mismatch&quot;)
    for phase in phases:
        require(phase.get(&quot;exit_gate&quot;) in gate_by_id, f&quot;phase {phase.get(&#x27;id&#x27;)}: unknown exit gate&quot;)
    if profile == &quot;adoption-candidate&quot;:
        for package_id in PHASE_ZERO_CHARTERS:
            require(by_id[package_id].get(&quot;draft_charter_path&quot;), f&quot;{package_id}: Phase 0 draft charter is required&quot;)

    return {
        &quot;work_packages&quot;: len(packages),
        &quot;programs&quot;: len(programs),
        &quot;phases&quot;: len(phase_counts),
        &quot;epics&quot;: len(epics),
        &quot;gates&quot;: len(gates),
        &quot;dependencies&quot;: sum(len(package[&quot;dependencies&quot;]) for package in packages),
    }


def main() -&gt; int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(&quot;graph&quot;, nargs=&quot;?&quot;, type=Path, default=DEFAULT_GRAPH)
    parser.add_argument(&quot;--profile&quot;, choices=sorted(PROFILES), default=&quot;adoption-candidate&quot;)
    parser.add_argument(&quot;--adoption&quot;, type=Path, default=DEFAULT_ADOPTION)
    args = parser.parse_args()
    try:
        counts = validate_bundle(load_graph(args.graph), load_graph(args.adoption), profile=args.profile)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f&quot;JARVIS-MIP validation: FAIL: {exc}&quot;, file=sys.stderr)
        return 1
    print(&quot;JARVIS-MIP validation: PASS&quot;)
    for name, count in counts.items():
        print(f&quot;  {name}: {count}&quot;)
    print(&quot;  dependency_cycles: 0&quot;)
    print(&quot;  forward_phase_dependencies: 0&quot;)
    print(f&quot;  profile: {args.profile}&quot;)
    return 0


if __name__ == &quot;__main__&quot;:
    raise SystemExit(main())
</code></pre>

</details>

<details>
<summary><code>tests/plan/test_validate_jarvis_mip.py</code></summary>

<pre><code>from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(&quot;validate_jarvis_mip&quot;, ROOT / &quot;scripts/validate_jarvis_mip.py&quot;)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class PlanValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -&gt; None:
        cls.valid = VALIDATOR.load_graph(VALIDATOR.DEFAULT_GRAPH)
        cls.adoption = VALIDATOR.load_graph(VALIDATOR.DEFAULT_ADOPTION)

    def graph(self) -&gt; dict:
        return copy.deepcopy(self.valid)

    def candidate_graph(self) -&gt; dict:
        graph = self.graph()
        graph.update(plan_status=&quot;ADOPTION_CANDIDATE&quot;, planning_adoption_gate=&quot;CLOSED&quot;)
        graph[&quot;gates&quot;][0].update(status=&quot;CLOSED&quot;, evidence_manifest=None)
        return graph

    def candidate_adoption(self) -&gt; dict:
        adoption = copy.deepcopy(self.adoption)
        adoption.update(reviewed_plan_commit=None, decision_state=&quot;PENDING&quot;, pag_0=&quot;CLOSED&quot;)
        for item in adoption[&quot;decisions&quot;]:
            item.update(disposition=&quot;PENDING&quot;, accountable_human=None, decided_at=None, rationale=None)
        return adoption

    def assert_invalid(self, graph: dict, message: str, profile: str = &quot;structural&quot;) -&gt; None:
        with self.assertRaisesRegex(VALIDATOR.ValidationError, message):
            VALIDATOR.validate_graph(graph, profile=profile)

    def test_adopted_pag0_bundle_is_valid(self) -&gt; None:
        counts = VALIDATOR.validate_bundle(self.graph(), copy.deepcopy(self.adoption), &quot;structural&quot;)
        self.assertEqual(counts[&quot;work_packages&quot;], 103)
        self.assertEqual(counts[&quot;epics&quot;], 34)
        self.assertEqual(counts[&quot;gates&quot;], 14)

    def test_duplicate_work_package_is_rejected(self) -&gt; None:
        graph = self.graph()
        graph[&quot;work_packages&quot;][1][&quot;id&quot;] = graph[&quot;work_packages&quot;][0][&quot;id&quot;]
        self.assert_invalid(graph, &quot;IDs must be unique&quot;)

    def test_missing_dependency_is_rejected(self) -&gt; None:
        graph = self.graph()
        graph[&quot;work_packages&quot;][0][&quot;dependencies&quot;] = [&quot;P-99&quot;]
        self.assert_invalid(graph, &quot;missing dependency P-99&quot;)

    def test_dependency_cycle_is_rejected(self) -&gt; None:
        graph = self.graph()
        graph[&quot;work_packages&quot;][0][&quot;dependencies&quot;] = [&quot;A-01&quot;]
        self.assert_invalid(graph, &quot;dependency cycle&quot;)

    def test_epic_mismatch_is_rejected(self) -&gt; None:
        graph = self.graph()
        graph[&quot;work_packages&quot;][0][&quot;epic&quot;] = &quot;A-E2&quot;
        self.assert_invalid(graph, &quot;epic backlink mismatch&quot;)

    def test_ready_package_requires_charter(self) -&gt; None:
        graph = self.graph()
        package = graph[&quot;work_packages&quot;][0]
        package[&quot;draft_charter_path&quot;] = None
        package[&quot;charter_path&quot;] = None
        package[&quot;status&quot;] = &quot;READY&quot;
        self.assert_invalid(graph, &quot;active status requires charter_path&quot;)

    def test_done_package_requires_evidence_manifest(self) -&gt; None:
        graph = self.graph()
        package = graph[&quot;work_packages&quot;][0]
        package[&quot;draft_charter_path&quot;] = None
        package[&quot;status&quot;] = &quot;DONE&quot;
        package[&quot;charter_path&quot;] = &quot;docs/plans/charters/A-01.md&quot;
        self.assert_invalid(graph, &quot;DONE requires evidence_manifest_path&quot;)

    def test_open_gate_requires_evidence_manifest(self) -&gt; None:
        graph = self.graph()
        graph[&quot;gates&quot;][2][&quot;status&quot;] = &quot;OPEN&quot;
        self.assert_invalid(graph, &quot;open/passed gate requires evidence_manifest&quot;, profile=&quot;structural&quot;)

    def test_structural_profile_allows_governed_future_state(self) -&gt; None:
        graph = self.graph()
        graph[&quot;plan_status&quot;] = &quot;ADOPTED&quot;
        graph[&quot;planning_adoption_gate&quot;] = &quot;OPEN&quot;
        graph[&quot;gates&quot;][0][&quot;status&quot;] = &quot;OPEN&quot;
        graph[&quot;gates&quot;][0][&quot;evidence_manifest&quot;] = &quot;docs/plans/evidence/PAG-0.json&quot;
        VALIDATOR.validate_graph(graph, profile=&quot;structural&quot;)
        self.assert_invalid(graph, &quot;plan must remain an adoption candidate&quot;, profile=&quot;adoption-candidate&quot;)

    def test_s4_evidence_requires_human_capital_owner(self) -&gt; None:
        graph = self.graph()
        package = next(item for item in graph[&quot;work_packages&quot;] if item[&quot;id&quot;] == &quot;P-04&quot;)
        package[&quot;evidence_requirements&quot;][&quot;required_reviews&quot;].remove(&quot;human_capital_owner&quot;)
        self.assert_invalid(graph, &quot;P-04: S4 evidence requires human_capital_owner&quot;)

    def test_adoption_decision_requires_human_evidence(self) -&gt; None:
        adoption = copy.deepcopy(self.adoption)
        adoption[&quot;decisions&quot;][0][&quot;accountable_human&quot;] = None
        with self.assertRaisesRegex(VALIDATOR.ValidationError, &quot;accountable_human&quot;):
            VALIDATOR.validate_adoption(adoption, &quot;structural&quot;)

    def test_adoption_candidate_rejects_decided_items(self) -&gt; None:
        adoption = self.candidate_adoption()
        item = adoption[&quot;decisions&quot;][0]
        item.update(
            disposition=&quot;ACCEPT&quot;,
            accountable_human=&quot;human-owner&quot;,
            decided_at=&quot;2026-09-02T00:00:00Z&quot;,
            rationale=&quot;Reviewed and accepted.&quot;,
        )
        with self.assertRaisesRegex(VALIDATOR.ValidationError, &quot;decisions must remain PENDING&quot;):
            VALIDATOR.validate_adoption(adoption, &quot;adoption-candidate&quot;)

    def test_bundle_rejects_gate_status_drift(self) -&gt; None:
        adoption = copy.deepcopy(self.adoption)
        adoption[&quot;pag_0&quot;] = &quot;CLOSED&quot;
        with self.assertRaisesRegex(VALIDATOR.ValidationError, &quot;bundle: PAG-0 status mismatch&quot;):
            VALIDATOR.validate_bundle(self.graph(), adoption, &quot;structural&quot;)

    def test_pag0_requires_accepted_decisions(self) -&gt; None:
        graph = self.graph()
        adoption = copy.deepcopy(self.adoption)
        adoption[&quot;decision_state&quot;] = &quot;PENDING&quot;
        with self.assertRaisesRegex(VALIDATOR.ValidationError, &quot;PAG-0 requires accepted decisions&quot;):
            VALIDATOR.validate_bundle(graph, adoption, &quot;structural&quot;)

    def test_adoption_candidate_requires_all_phase_zero_draft_charters(self) -&gt; None:
        graph = self.candidate_graph()
        package = next(item for item in graph[&quot;work_packages&quot;] if item[&quot;id&quot;] == &quot;A-02&quot;)
        package[&quot;draft_charter_path&quot;] = None
        self.assert_invalid(graph, &quot;A-02: Phase 0 draft charter is required&quot;, profile=&quot;adoption-candidate&quot;)


if __name__ == &quot;__main__&quot;:
    unittest.main()
</code></pre>

</details>
