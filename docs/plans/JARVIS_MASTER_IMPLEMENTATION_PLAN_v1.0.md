# JARVIS MASTER IMPLEMENTATION PLAN v1.0

**Plan ID:** JARVIS-MIP-1.0  
**Owner authorization:** 2026-09-02  
**Repository adoption:** **PENDING MERGE OF PR #768**  
**Formal implementation:** **NOT STARTED**  
**First queued WP:** `A-01` Runtime Truth Baseline & Contradiction Register  
**ISG-0:** **OPEN / NOT YET SATISFIED**  
**Reachable planning baseline:** `master@e2a1006e3eb7d35a840487c80899b33103b52277`

> This is the canonical repository implementation plan for future JARVIS work. Historical roadmap/canon documents remain evidence but do not govern new implementation when they conflict with this plan. Pre-plan PRs #749, #754, #756 and RT-3 are technical spikes to harvest selectively, not completed implementation.

## 1. Mission

Build JARVIS as a deterministic, point-in-time-correct, replayable, auditable systematic trading research and execution platform with institutional-style validation discipline and a human operator control plane.

The system must create falsifiable hypotheses, reject weak strategies, apply deterministic portfolio/risk policy, route only governed trade intents through one OMS/broker path, reconcile broker state, measure execution/forward evidence, and halt/degrade/retire strategies when evidence weakens.

Capital-path milestones such as `$3k → $10k → $25k → $100k → $300k` are research scenarios, not return promises.

## 2. Non-negotiable principles

1. Disprove strategies rather than tune them until they pass.
2. Information not known by `decision_at` is invalid for that decision.
3. Verified broker state is authority for executable positions/orders/fills/account.
4. One mutation spine: `Strategy/Human → Intent → Portfolio/Risk → OMS → Broker → Reconcile`.
5. Hard risk, sizing, limits and halts are deterministic and non-LLM.
6. AI may research/classify/explain/criticize; it may not enable live, raise risk or send broker orders.
7. Zero quantity is a valid NO TRADE result.
8. Stale/unavailable/ambiguous state is explicit and blocks safety-critical mutations.
9. One operator product; do not proliferate permanent V2/V3 dashboards.
10. Paper/canary/live are evidence states, not convenience flags.
11. Failures and rejected trials remain recorded.
12. Reconciliation/restart recovery/alerts/provenance precede live capital.

## 3. Verification ladder

| Rung | Evidence | Permitted claim |
|---|---|---|
| E0 | lint/typecheck/compile | builds/typechecks/lints |
| E1 | deterministic unit/property tests | unit-tested |
| E2 | integration/replay | integration-tested |
| E3 | full local paper path observed | paper E2E observed |
| E4 | real IBKR paper round-trip observed | broker-paper verified |
| E5 | explicitly authorized tiny live canary | live-canary observed |

Financial numbers require independent value-level assertions in addition to the rung above.

## 4. Source-of-truth hierarchy

| Domain | Authority |
|---|---|
| Broker account/positions/orders/fills | verified broker API + staleness state |
| JARVIS intents/decisions/risk/audit/operator actions | durable operational ledger (SQLite through paper) |
| Runtime risk policy | versioned Risk Policy artifact + active hash |
| Trading eligibility | Judge lifecycle registry keyed by strategy+instrument+TF+version |
| Research datasets | immutable manifest + content hashes |
| Research attempts | preregistered Trial Ledger |
| Feature values | PIT Feature Store + versions |
| Strategy result | Judge Evidence Bundle |
| Instrument metadata | Instrument Master |
| UI | never authoritative; server contracts only |
| Future implementation plan | this plan + adopted ADR/WP evidence |

## 5. Target architecture

**Single repository, modular monolith first.** Services/datastores are split only after measured need.

```text
COMMAND CENTER
      │ HTTP commands / WS-SSE observations
      ▼
ENGINE API / COMPOSITION ROOT
      │
      ├─ PIT Data / Feature Compiler
      ├─ Research / Trial Ledger / Judge V3
      ├─ Deterministic Strategies
      ├─ Portfolio Construction
      ├─ Versioned Risk Policy
      ├─ AI Context (advisory only)
      │
      ▼
TRADE INTENT
      ▼
SINGLE OMS STATE MACHINE
      ▼
BROKER ADAPTER
      ▼
IBKR PAPER / later isolated CANARY
      ▼
RECONCILIATION
      ▼
AUDIT / PERFORMANCE / CAPITAL PATH
```

Target engine domains: `core`, `data`, `features`, `research`, `judge`, `strategies`, `portfolio`, `risk`, `execution`, `brokers`, `capital_path`, `intelligence`, `observability`, `api`; `main.py` becomes composition/bootstrap only.

## 6. Persistence baseline

- **Operational through paper:** SQLite/WAL.
- **Research:** immutable Parquet + dataset manifests + DuckDB.
- **Redis:** optional realtime/cache coordination; never canonical truth.
- **Postgres/QuestDB:** future ADR only if measured requirements justify migration.

## 7. Instrument / data / PIT model

One **Instrument Master** owns root/broker symbol, asset class, exchange, currency, timezone, sessions, tick/point value, multiplier, price precision, quantity step, margin metadata, contract resolution and supported order types.

Observation time contract:

```text
event_at
published_at       # where relevant
received_at
available_at
computed_at
known_at=max(available_at,computed_at)
decision_at
```

Any decision feature must satisfy `known_at <= decision_at`.

Executable market data additionally requires approved provider class, verified contract, acceptable freshness, valid session and quality/provenance pass.

## 8. Feature / Strategy / Judge

Feature registry separates: source integrity, causal integrity, formula parity, statistical evidence and deployment eligibility.

`ported != parity != causal != validated != deployable`.

Initial deterministic baseline remains a regime-filtered relative-strength momentum/breakout-pullback family. ML begins only after deterministic candidate datasets + Judge exist; simple logistic/GBDT/calibration baselines precede RL.

Judge lifecycle:

```text
RESEARCH_REJECT → RESEARCH_ONLY → PAPER_CANDIDATE → PAPER_VALIDATED
→ CANARY_CANDIDATE → LIVE_ELIGIBLE → DEGRADED / RETIRED
```

Lifecycle is strategy+instrument+TF+version specific. Judge checks causal integrity, preregistered trials, purged WFO/CPCV, honest DSR/PBO, parameter plateaus, costs, regimes, edge haircuts, ablation, placebos/falsification, locked holdout, paper evidence and canary evidence. Research code cannot self-write PASS.

## 9. Portfolio / Risk

Portfolio owns broker-mapped positions, cash/equity, P&L, pending exposure, factor/correlation exposure, portfolio heat, allocation and attribution.

Risk is one versioned policy artifact. Position sizing permits zero and derives from equity, approved risk fraction, stop distance and Instrument Master point value/multiplier plus portfolio/margin/correlation constraints.

AI cannot alter active risk policy, raise limits, clear critical halt, enable live or send an order.

## 10. OMS / broker

Canonical flow:

```text
Candidate/Human → TradeIntent → Eligibility/Portfolio → Risk
→ OMS claim/state machine → Broker Adapter → ACK/FILL/REJECT/AMBIGUOUS
→ Reconciliation → Position/Audit events
```

OMS requirements: durable transitions, idempotency/fingerprints, atomic route claim, no automatic retry after ambiguous broker outcome, broker-side protection where supported, partial-fill handling, cancel/replace/reduce/flatten, restart recovery and reconciliation.

Browser holds no broker credentials and never calls IBKR directly.

## 11. Capital Path

Capital Path is separate from fixed-PnL sequence-risk Monte Carlo.

```text
Equity[t+1] = Equity[t] * (1 + risk_fraction[t] * R_net[t])
```

Report target-before-ruin, conditional target time, milestone first passage, DD/underwater/tail distributions and risk-policy sensitivity across IID/moving-block/stationary/day/regime/model/edge uncertainty. Forecasts separate sampling error from model disagreement. Capital Path never writes active risk policy automatically.

## 12. AI / Codex authority

Runtime AI: context, catalyst, research critique, post-trade explanation; no hard capital authority.

Development topology:

```text
Plan/Architecture      Human + ChatGPT
Implementation         Codex bounded by WP
Independent Test       separate agent
Adversarial Review     separate agent
CI                     deterministic
Merge/Promotion        human governed by safety class
Live/Capital           human only
```

Codex may not autonomously merge S3/S4, change live flags/credentials/risk ceilings, mark LIVE_ELIGIBLE, delete failed trials or place broker orders.

## 13. Canonical operator surfaces

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

Every critical displayed number carries value, unit, source/provenance, timestamp/freshness and relevant policy/data/evidence version. `UNAVAILABLE` is never rendered as zero.

## 14. Environment ladder

```text
RESEARCH → BACKTEST → REPLAY → PAPER → CANARY → LIVE
```

Credentials, broker accounts/ports, permissions and mutation rights are isolated. Lower environments may not activate higher-environment credentials by default.

## 15. Safety classes

- **S0:** docs/research/non-runtime.
- **S1:** read-only/runtime foundation.
- **S2:** paper mutation/execution infrastructure.
- **S3:** risk/eligibility/safety-critical.
- **S4:** canary/live capital or credentials.

## 16. Programs A–P

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

## 17. Delivery phases / gates

| Phase | Objective | Gate |
|---|---|---|
| 0 | Plan adoption, runtime truth, CI baseline, source hierarchy, architecture, IA, governance | ISG-0 |
| 1 | Core contracts, Instrument/Risk/Event/Environment foundations | M1 |
| 2 | PIT data, Feature Store, parity, trial ledger | M2 |
| 3 | Deterministic strategies + Judge V3 | M3 |
| 4 | One Risk/OMS/Broker/Reconciliation execution core | M4 |
| 5 | Read-only trustworthy operator product | M5 |
| 6 | Integrated paper control plane | M6 |
| 7 | Capital Path + robust risk frontier | M7 |
| 8 | Evaluated contextual AI intelligence | M8 |
| 9 | Frozen integrated paper campaign | M9 |
| 10 | Canary readiness only; no live order yet | M10 |
| 11 | Tiny explicitly authorized live canary | M11 |
| 12 | Controlled evidence-banded production/research cycle | M12 |

No calendar date authorizes live trading.

## 18. ISG-0 exit criteria

- runtime truth baseline completed;
- safety/product-architecture contradictions resolved or explicitly blocking;
- source hierarchy adopted;
- target architecture ADR adopted;
- operator IA/deprecation map adopted;
- CI/debt baseline established;
- branch/PR/Codex governance enforced;
- spike branches frozen except explicit harvest work.

## 19. Formal implementation queues

### Phase 0 — ISG-0 prerequisites

1. `A-01` Runtime truth baseline & contradiction register — **QUEUED FIRST**
2. `O-01` CI baseline/debt classification
3. `A-02` Source-of-truth hierarchy ADR
4. `A-03` Target bounded-context architecture ADR
5. `K-01` Operator product IA & wireframes/deprecation map
6. `O-05` Branch/PR/Codex governance
7. `O-02/O-03` Verification and build foundations required by ISG-0

### Phase 1 — blocked until ISG-0

These packages may be designed during Phase 0, but runtime implementation may not begin until ISG-0 is satisfied and their Definition of Ready evidence is approved.

1. `B-01` Instrument Master
2. `H-01` Versioned Risk Policy
3. `M-01` Canonical Event/Audit schema
4. `N-02` Environment/authorization matrix
5. `A-04` Core domain contracts

## 20. Known research blockers

- Issue #751 Initial Balance causal leak: affected evidence requires corrected feature version + impact re-run.
- Issue #752 VWAP RTH/Globex/session semantics: explicit session policy + corrected evidence required.
- Legacy KAMA/Phase/STC variants remain separate until source parity is certified.
- Historical campaign-trial undercount concerns require preregistered Judge V3 trial accounting.

## 21. Pre-plan spike disposition

- **#749:** HOLD/HARVEST into Feature/Trial/Judge/Capital Path WPs; do not merge as one implementation bundle.
- **#754:** HOLD/HARVEST UI patterns; no permanent Command Center V2 product tree.
- **#756:** HOLD/HARVEST trade-intent/idempotency ideas after H/I/J contracts.
- **RT-3:** FREEZE until M4/M6 dependencies.

## 22. Definition of Ready

A WP requires: stable ID/program, objective/non-goals, satisfied dependencies, contracts, safety class, owner mode, acceptance criteria, required E0–E5 rung, numeric/PIT tests where relevant, migration/rollback for S2+, and no hidden unresolved architecture choice.

## 23. Definition of Done

A WP is DONE only after acceptance, touched-code quality, required unit/property/integration/runtime evidence, numeric checks, PIT/session checks, safety regression for S2+, docs/contracts/evidence manifest, residual risks, and confirmation that no new duplicate source of truth/authority was created.

## 24. Governance

Decision classes:

- D0 planning/docs — normal review.
- D1 read-only runtime/data — technical review + tests.
- D2 paper mutation — independent review + E3/E4 evidence as specified.
- D3 safety/eligibility/risk — human approval + safety review + adversarial evidence.
- D4 canary/live capital — explicit human authorization only.

Every implementation PR includes:

```text
Plan: JARVIS-MIP-1.x
Program:
Work Package:
Phase/Milestone:
Safety Class:
Objective:
Dependencies:
Acceptance Criteria:
Verification Rung:
Evidence:
Migration/Rollback:
Production/Capital Impact:
```

## 25. Current formal status

**Owner authorization:** GRANTED 2026-09-02.  
**Repository adoption:** pending merge of PR #768.  
**Formal implementation:** NOT STARTED.  
**Current phase:** pre-Phase-0 adoption.  
**First queued WP:** A-01.  
**ISG-0:** open but not satisfied.  
**Live/canary authorization:** NOT GRANTED.

The following are planned Phase-0 deliverables and do not exist until their work packages land:

- `docs/plans/JARVIS_PLAN_ADOPTION_2026-09-02.md`
- `docs/plans/JARVIS_PHASE_0_STATUS.md`
- `docs/plans/phase0/A-01_RUNTIME_TRUTH_BASELINE.md`

The detailed PlanLife work-package hierarchy is governed by JARVIS-MIP v1.0 after repository adoption and will be materialized and updated in repository registers as Phase 0 governance lands.
