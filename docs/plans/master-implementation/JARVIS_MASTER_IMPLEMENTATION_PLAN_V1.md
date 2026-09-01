# JARVIS Master Implementation Plan v1.0

Status: candidate v1.0 prepared 2026-09-01. This is the control document for moving JARVIS from exploratory spikes to formal implementation.

## 1. Executive Product Charter

JARVIS is a personal institutional-style quantitative trading platform for Amo. The goal is not an alert bot and not a fixed daily-return machine. The goal is to maximize long-run geometric growth subject to drawdown, risk of ruin, execution constraints, portfolio heat, data quality, and human-governed promotion gates.

The system must answer:

- Is this strategy statistically credible after honest costs and validation?
- Which market regimes support or degrade the edge?
- Is the latest decision using point-in-time data that was actually available?
- What is the distribution of capital outcomes under edge decay and drawdown?
- Should a candidate stay research-only, move to paper, enter canary, or retire?
- Can the operator trust the current state at a glance?

Non-goals:

- No fixed 5-10% daily target.
- No live trading automation without explicit live-promotion approval.
- No LLM authority over hard risk limits, final sizing, or broker write credentials.
- No dashboard path that bypasses server-side risk, safety, OMS, and reconciliation.

Definition of success:

- A reproducible research and paper-execution platform that fails closed, records evidence, and produces only human-gated live eligibility.

## 2. Current State Summary

The conversation-history checkpoint classified formal implementation as `NOT STARTED` because no adopted master implementation plan existed. This package closes that planning gap but does not by itself prove runtime behavior.

What exists:

- FastAPI engine and Next.js dashboard.
- Paper-only JARVIS runtime assumptions.
- Extensive research, backtest, gate-v2, feature, dashboard, and autonomy spikes.
- Current open PRs and issues around feature integrity, Command Center V2, trade intent, Phase Oscillator parity, Initial Balance, and VWAP.
- Existing loops for JARVIS ROI, audit, branch convergence, dashboard guard, engine health, and related monitoring.

What remains unproven:

- An adopted end-state architecture mapped to current repo code.
- A validated integrated paper product against the new plan gates.
- A production-ready operator Command Center.
- A complete paper-to-canary promotion campaign.
- Any live deployment.

## 3. End-State Architecture

Target flow:

```text
Market and alternative data
  -> point-in-time data platform
  -> feature platform
  -> strategies plus AI intelligence
  -> Judge V3 and validation evidence
  -> portfolio construction
  -> deterministic risk engine
  -> execution intent and OMS
  -> broker adapter
  -> reconciliation and event log
  -> Command Center
```

Ownership boundaries:

- Data platform owns source provenance, freshness, timestamps, and point-in-time availability.
- Feature platform owns registered feature IDs, versions, parity state, causal state, and as-of snapshots.
- Strategies produce trade intent, not broker orders.
- Judge V3 rejects or classifies evidence; missing evidence never passes.
- Risk accepts, rejects, sizes, or reduces deterministic intents.
- OMS owns order lifecycle, idempotency, retries, ambiguous broker-result handling, and recovery.
- Broker adapter executes only approved OMS orders.
- Reconciliation treats broker state as authoritative.
- Command Center observes state and submits authenticated intents; it never holds broker credentials.
- AI researches, critiques, summarizes, tests, and proposes; it never owns hard risk or capital authorization.

Failure policy:

- Stale state fails closed.
- Missing verdict fails closed.
- Unavailable feature fails closed.
- Ambiguous broker result requires reconciliation and must not auto-retry.
- Risk-reducing operator actions are easier than risk-increasing actions.

## 4. Product And Command Center Specification

The Command Center is the operator control plane. It should be a dense, real-time trading workstation, not a marketing dashboard.

Primary surfaces:

1. Command Center - current trust state, vitals, positions, orders, pending intents, next action.
2. Today's Market - regime, macro, session, futures sentiment, catalyst context.
3. Trade Workstation - preview, risk-adjusted sizing, approval, submission, and blocked-state explanation.
4. Positions And Orders - broker-sourced positions, open orders, protective children, fills, reconciliation state.
5. Risk Center - kill switch, heat, drawdown, daily loss, stale-state gates, limits.
6. Strategy Monitor - per-strategy gate state, live paper eligibility, recent decisions, degradation.
7. Research Lab - trials, fingerprints, validation status, feature ablation, holdout discipline.
8. Backtesting - reproducible campaigns, WFO, CPCV, costs, stress, Monte Carlo.
9. Judge / Validation - evidence cards, failure reasons, promotion status.
10. Capital Path - milestone probabilities, ruin, drawdown, edge haircut, risk frontier.
11. Performance Analytics - paper-trade truth, slippage, Brier/calibration, R-multiple distributions.
12. Trade Journal - decision trace, post-trade notes, realized vs expected.
13. System Health - engine, dashboard, IB paper, TV MCP, LLM, data feeds, loops.
14. Configuration / Admin - read-mostly config, protected toggles, explicit safety-review flags.

Acceptance for a Command Center build:

- One screen shows `TRUST: HIGH | DEGRADED | BLIND`.
- Vitals distinguish engine health, broker state, data freshness, LLM path, TV MCP, and kill switch.
- Mutations go through authenticated server APIs.
- Every displayed trading number has a source/provenance path.
- The UI degrades visibly when dependencies are down.
- Pulling or simulating a data-feed failure flips the trust state without a refresh.

## 5. Data And Feature Architecture

Data timestamps:

```text
event_at <= available_at <= known_at <= decision_at
known_at = max(available_at, computed_at)
```

Mandatory fields:

- `event_at`
- `available_at`
- `computed_at`
- `known_at`
- `decision_at`
- `source`
- `source_version`
- `quality`
- `bar_age_s` or equivalent freshness measure

Feature registry dimensions:

- source_integrity: unknown, reviewed, verified, new_design
- causal_integrity: unknown, safe, safe_core, safe_concept, safe_formula, delayed, rewrite_required, rejected
- parity: unported, pending, approximate, failed, passed, not_applicable
- statistical_evidence: untested, research, project_validated_prior, oos_pass, paper_pass, live_pass, rejected
- deployment: research_only, context_only, risk_only, paper_allowed, live_allowed, deprecated

Core invariant:

```text
ported != parity
parity != causal
causal != validated
validated != live
```

## 6. Strategy Framework

Strategy work starts as hypotheses. It graduates only through evidence:

```text
Hypothesis
  -> codify
  -> historical test
  -> out-of-sample validation
  -> paper
  -> measure
  -> tiny canary
  -> measure
  -> scale or kill
```

Strategy outputs are intents with immutable terms:

- symbol
- side
- entry logic
- stop
- target
- invalidation
- time-in-force
- max quantity ceiling
- source data fingerprint
- feature vector version
- strategy config hash
- Judge verdict ID

No strategy can execute directly against the broker.

## 7. Judge V3 Design

Judge V3 is an evidence gate, not an optimism engine.

Lifecycle states:

- RESEARCH_FAIL
- RESEARCH_ONLY
- PAPER_CANDIDATE
- PAPER_VALIDATED
- CANARY_CANDIDATE
- LIVE_ELIGIBLE
- DEGRADED
- RETIRED

Minimum evidence dimensions:

- causal integrity
- source parity where relevant
- purged validation
- locked holdout
- OOS sample size
- DSR
- honest trial count
- PBO
- parameter plateau
- feature-family ablation
- cost stress
- regime stress
- edge haircut

Rule: missing evidence must never produce PASS.

## 8. Portfolio, Risk, Capital Path

Risk is deterministic and non-LLM.

Initial risk hypotheses remain research-only until validated:

- Standard trade risk around 0.50% equity.
- Higher-quality trade around 0.75% equity.
- Hard single-trade ceiling hypothesis around 1.00% equity.
- Normal portfolio heat around 2%; absolute heat around 3%.
- Sector heat around 1.25-1.5%.

These are not production rules.

Capital Path must model:

- dynamic compounding
- first-passage probability to milestones
- drawdown and underwater duration
- ruin and halt probabilities
- dependence-preserving resampling
- model ensemble spread
- edge haircuts at 100%, 75%, 50%, 25%, and 0%
- risk-policy frontier, not just maximum CAGR

## 9. Execution, OMS, Broker, Reconciliation

Execution flow:

```text
Trade intent
  -> fresh broker state
  -> fresh market state
  -> risk engine
  -> safety layer
  -> OMS
  -> IBKR paper
  -> order/fill/position events
  -> reconciliation
  -> Command Center
```

Rules:

- Paper port is 4002.
- Live port 4001 remains blocked and must not be expected reachable.
- Browser must not call IBKR directly.
- Broker state is authoritative.
- Reconciliation is mandatory after restart, ambiguous submit, or external broker action.
- Ambiguous broker result stays `SUBMITTING` or `RECONCILIATION_REQUIRED`; no automatic retry.

## 10. Environment Ladder

```text
RESEARCH -> BACKTEST -> REPLAY -> PAPER -> CANARY -> LIVE
```

Each environment must define:

- credentials
- data source
- mutation rights
- broker permissions
- monitoring
- promotion gates
- rollback path
- human approval requirements

Live trading remains a separate gate. This plan does not authorize it.

## 11. Workstreams

Programs:

A. Platform and Infrastructure
B. Data Engineering
C. Feature Engineering
D. Strategy Research
E. Judge and Statistical Validation
F. Portfolio Construction
G. Capital Path
H. Risk Management
I. Execution and OMS
J. Broker Integration
K. Command Center and UX
L. AI Intelligence and Agents
M. Observability
N. Security
O. DevOps and CI/CD
P. Paper to Canary to Production

Every work item must map to:

- program
- epic
- capability
- acceptance criteria
- validation evidence
- production impact
- owner/gate

## 12. Dependency Graph

Research chain:

```text
Data contracts
  -> PIT data store
  -> feature registry and feature store
  -> strategy framework
  -> Judge V3
  -> validated trade distributions
  -> Capital Path
  -> risk-policy optimization
```

Execution chain:

```text
Broker adapter
  -> order state machine
  -> reconciliation
  -> paper OMS
  -> Trade Workstation
```

Convergence:

```text
Validated strategies
  + risk engine
  + paper OMS
  + Command Center
  -> integrated paper campaign
  -> canary eligibility
```

## 13. Delivery Phases

| Phase | Objective | Exit Gate |
|---|---|---|
| 0 | Planning and inventory | This package exists; PR/issue/spike disposition recorded; backlog seeded |
| 1 | Platform foundations | Repo state, CI, runtime, and docs are coherent enough to support planned work |
| 2 | Research and data foundation | PIT contracts, feature registry, trial ledger, and freshness gates exist |
| 3 | Deterministic strategies and Judge | Strategy framework produces evidence-gated intents |
| 4 | Paper execution infrastructure | OMS, idempotency, brackets, recovery, and reconciliation pass drills |
| 5 | Command Center | Operator sees trust, state, risk, and actions in one control plane |
| 6 | Integrated paper system | End-to-end paper campaign runs with evidence capture |
| 7 | Capital Path and risk optimization | Capital distribution and risk frontier inform sizing policy |
| 8 | AI intelligence layer | AI improves research/review without owning risk authority |
| 9 | Extended paper validation | Sufficient live paper sample and stability evidence |
| 10 | Tiny canary | Separate explicit human-gated live/canary approval |
| 11 | Controlled production | Strict monitored scale-up after canary evidence |
| 12 | Continuous research automation | Backlog and validation loops keep improving the system |

## 14. Milestone Gates

M0 - Plan adopted:

- Master plan package exists.
- Inventory and PR disposition exists.
- Backlog exists and is loop-drainable.
- Amo explicitly accepts the plan as the implementation control document.

M1 - Research foundation ready:

- Feature registry enforced.
- PIT availability tested.
- Trial ledger records PLAN -> RESULT -> SELECTION.
- Golden vectors exist for priority indicators.

M2 - Data-truth ready:

- Data freshness is checked at decision time.
- Feed provenance is persisted with each signal.
- Blind/stale data forces HOLD or NO_TRADE.

M3 - Judge ready:

- Missing evidence rejects.
- Honest trial count affects DSR/PBO.
- Cost, regime, parameter, and ablation stress are included.

M4 - Paper execution ready:

- Broker connectivity.
- Idempotency.
- Order state machine.
- Protected brackets.
- Restart recovery.
- Reconciliation.
- Stale-data rejection.
- Duplicate prevention.
- Emergency flatten.
- Integration and chaos tests.

M5 - Command Center ready:

- Trust state.
- Vitals.
- Positions/orders.
- Pending intents.
- Risk controls.
- Pipeline tape.
- Numeric provenance.
- Degraded states.

M6 - Integrated paper campaign ready:

- Research -> intent -> risk -> OMS -> broker paper -> reconciliation -> journal works end to end.
- Paper campaign captures enough evidence for promotion decisions.

M7 - Canary eligible:

- Legal/broker gates cleared.
- Live port/network policy explicitly changed and secured.
- Human approval policy set.
- Live kill switch and stop enforcement verified.
- Separate canary checklist approved.

## 15. Codex Operating Model

Use Codex for:

- bounded implementation
- tests
- static and causal audits
- adversarial review
- docs and traceability
- loop engineering
- PR triage

Human-gated:

- strategy promotion
- risk-limit changes
- live enablement
- broker execution authority
- `.env` and secret mutation
- destructive cleanup
- shared branch merge/push

Maker-checker rule:

- Implementation agent writes.
- Independent checker tries to break it.
- CI provides deterministic gate evidence.
- Promotion remains human-gated.

## 16. Treatment Of Existing Work

Open spikes and PRs are evidence, not implementation, unless this plan adopts them.

- PR #749: keep as research foundation candidate; harden after plan adoption.
- PR #754: treat as Command Center reference spike; extract UX/API lessons before building final control plane.
- PR #756: treat as paper trade-intent/OMS reference spike; reuse only after OMS contract is approved.
- PR #755: treat as source-parity safety-review candidate; decide through validation evidence.
- Issues #750-#753: retain as plan-seeded work items.

See `PR_ISSUE_SPIKE_DISPOSITION_2026-09-01.md` for the live disposition matrix.

## 17. First Implementation Backlog

The first actionable backlog is in `IMPLEMENTATION_BACKLOG.json`. The loop drains the top 10 unblocked items per pass, then re-ranks.

Pass 1 completed by this package:

1. Create plan package.
2. Define product charter.
3. Define architecture.
4. Define Command Center specification.
5. Define data/feature/Judge/risk/OMS/environment architecture.
6. Define workstreams.
7. Define dependency graph.
8. Define milestone gates.
9. Disposition existing PRs/issues/spikes.
10. Seed machine-readable backlog.

Next pass starts with validation and current-state hardening, not feature expansion.

