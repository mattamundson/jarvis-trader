# JARVIS Master Implementation Plan v1.1

**Plan ID:** `JARVIS-MIP-1.1`<br>
**Generated:** 2026-09-01<br>
**Repository baseline:** `master@1d8f93992205d1dcacc05e0466d89247f2c789d1`<br>
**Plan status:** **ADOPTED — PAG-0 OPEN**<br>
**Formal implementation status:** **NOT STARTED**<br>
**Planning Adoption Gate (PAG-0):** **OPEN**<br>
**Implementation Start Gate (ISG-0):** **CLOSED**

> This normalized document is the adoption candidate for the next JARVIS
> architecture. It does not authorize implementation, paper-order mutation,
> canary activity, live trading, risk-limit changes, or strategy promotion.

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

The decision invariant is `known_at <= decision_at`, but underlying timestamps
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
unrealized P&L, pending-order exposure, heat, concentration, correlation, and
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
4. Positions & Orders
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
| A | Platform & Architecture |
| B | Data Engineering |
| C | Feature Engineering |
| D | Strategy Research |
| E | Judge & Statistical Validation |
| F | Portfolio Construction |
| G | Capital Path |
| H | Risk Management |
| I | Execution / OMS |
| J | Broker Integration |
| K | Command Center / UX |
| L | AI Intelligence & Agents |
| M | Observability & Operations |
| N | Security & Access |
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
